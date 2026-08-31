# cookie_source.py
"""
登录态来源。支持三种，按需切换：

- chrome ：直接读本机 Chrome 已登录的 cookie（推荐，不用重复登录）
- profile：用项目自己的 Playwright 持久化 profile（.browser_profiles/）
- auto   ：先 chrome，拿不到再退回 profile

产出统一是一份 Netscape 格式 cookie 文件（.cookies/<平台>.txt），
Playwright 注入和 yt-dlp 下载共用同一份，避免“解析用 A 会话、下载用 B 会话”。
"""
from __future__ import annotations
import math
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import BROWSER, PROFILE
from utils import cookie_file_for

# 各平台需要带上的 cookie 域名特征。小鹅通一店多域（官方域 + 商家自有域），
# 登录态可能落在其中任意一个，所以全都收。
PLATFORM_COOKIE_DOMAINS: Dict[str, Tuple[str, ...]] = {
    "xiaoe": ("xiaoe-tech.com", "xiaoeknow.com", "xiaoecloud.com",
              "xet.tech", "xet-pc.", "xet.pomoho.com", "xeknow.com"),
    "douyin": ("douyin.com", "bytedance.com", "douyinvod.com"),
}

# 判断“看起来已登录”的 cookie 名（小鹅通）
LOGIN_HINT_NAMES = ("pc_user_key", "ko_token", "userInfo", "show_user_icon", "user_id")


# 1601-01-01 到 1970-01-01 的秒数（Chrome/WebKit 时间戳基准）
_WEBKIT_EPOCH_OFFSET = 11644473600


def normalize_expires(value) -> float:
    """
    把各种来源的过期时间统一成「Unix 秒」，无效/会话 cookie 统一返回 -1。

    必须做这层归一化：浏览器库里存的是 1601-epoch 微秒（如 1.3467e16），
    直接喂给 Playwright 会因为“不是合法时间戳”导致 add_cookies **整批**失败，
    登录态一条都注入不进去。
    """
    try:
        e = float(value or 0)
    except (TypeError, ValueError):
        return -1.0
    if not math.isfinite(e) or e <= 0:
        return -1.0

    if e > 1e14:                                  # 1601-epoch 微秒
        e = e / 1e6 - _WEBKIT_EPOCH_OFFSET
    elif e > 1e12:                                # Unix 毫秒
        e = e / 1000.0
    elif e > 1e10:                                # 1601-epoch 秒
        e = e - _WEBKIT_EPOCH_OFFSET

    if e <= 0 or e > 4e10:                        # 归一化后仍不合理 → 当会话 cookie
        return -1.0
    return float(int(e))


def _matches(domain: str, keys: Tuple[str, ...]) -> bool:
    d = (domain or "").lower().lstrip(".")
    return any(k.lower().lstrip(".") in d for k in keys)


# Chromium 系浏览器：主 cookie 库的候选位置（新版把 Cookies 挪到了 Network/ 下）
_CHROMIUM = ("chrome", "chromium", "edge", "brave", "vivaldi", "opera", "chrome_beta")


def _main_cookie_db(browser: str, profile: str) -> Optional[Path]:
    """
    定位浏览器的**主** cookie 库。

    必须显式定位：Chrome 新版会给扩展分配独立的 cookie store
    （如 Default/Storage/ext/<扩展id>/Cookies），而 yt-dlp 是“在 profile 目录下
    递归找最近修改的 Cookies 文件”，扩展那个通常更新更勤，于是会被误选——
    结果就是只读到几十条无关 cookie，站点登录态一条都拿不到。
    """
    roots: List[Path] = []
    try:
        from yt_dlp.cookies import _get_chromium_based_browser_settings
        bd = _get_chromium_based_browser_settings(browser.lower()).get("browser_dir")
        if bd:
            roots.append(Path(bd))
    except Exception:
        pass
    home = Path.home()
    roots += [
        home / "Library/Application Support/Google/Chrome",   # macOS
        home / ".config/google-chrome",                       # Linux
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data",  # Windows
    ]

    for root in roots:
        try:
            if not root or not root.is_dir():
                continue
        except Exception:
            continue
        pdir = Path(profile) if os.path.isabs(profile or "") else root / (profile or "Default")
        cands = [c for c in (pdir / "Network" / "Cookies", pdir / "Cookies") if c.is_file()]
        if cands:
            return max(cands, key=lambda x: x.stat().st_mtime)
    return None


def extract_from_chrome(platform: str,
                        browser: Optional[str] = None,
                        profile: Optional[str] = None) -> List[dict]:
    """
    从本机浏览器读取该平台相关的 cookie，返回 Playwright add_cookies 可用的结构。
    macOS 首次读取 Chrome cookie 会弹钥匙串授权（Chrome Safe Storage），属正常现象。
    """
    browser = browser or BROWSER
    profile = profile or PROFILE
    if not browser:
        return []
    try:
        from yt_dlp.cookies import extract_cookies_from_browser

        db = _main_cookie_db(browser, profile) if browser.lower() in _CHROMIUM else None
        if db:
            # 把主库单独复制到临时目录再交给 yt-dlp，确保它读的就是这一个文件。
            # 解密密钥不在 profile 目录里（macOS 走钥匙串、Windows 走 Local State），
            # 所以这样隔离不会影响解密。
            tmp = tempfile.mkdtemp(prefix="vd_cookies_")
            try:
                shutil.copy2(db, Path(tmp) / "Cookies")
                jar = extract_cookies_from_browser(browser, profile=tmp)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        else:
            jar = extract_cookies_from_browser(browser, profile=profile)
    except Exception:
        return []

    keys = PLATFORM_COOKIE_DOMAINS.get(platform, ())
    out: List[dict] = []
    for c in jar:
        if keys and not _matches(c.domain, keys):
            continue
        out.append({
            "name": c.name,
            "value": c.value or "",
            "domain": c.domain,
            "path": c.path or "/",
            "expires": normalize_expires(c.expires),
            "httpOnly": False,
            "secure": bool(c.secure),
            "sameSite": "Lax",
        })
    return out


def looks_logged_in(cookies: List[dict]) -> bool:
    names = {c.get("name") for c in cookies}
    return any(n in names for n in LOGIN_HINT_NAMES)


def dump_netscape(cookies: List[dict], path: Path) -> Optional[Path]:
    """写成 Netscape 格式，供 yt-dlp 的 --cookies 使用。"""
    if not cookies:
        return None
    lines = ["# Netscape HTTP Cookie File", "# generated by videoDownload", ""]
    fallback_exp = int(time.time()) + 7 * 86400
    for c in cookies:
        domain = c.get("domain") or ""
        name = (c.get("name") or "").replace("\t", "").replace("\n", "")
        if not domain or not name:
            continue
        value = (c.get("value") or "").replace("\t", "").replace("\n", "")
        expires = int(normalize_expires(c.get("expires")))
        if expires <= 0:
            expires = fallback_exp
        lines.append("\t".join([
            domain,
            "TRUE" if domain.startswith(".") else "FALSE",
            c.get("path") or "/",
            "TRUE" if c.get("secure") else "FALSE",
            str(expires), name, value,
        ]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def cookies_from_file(path: Path) -> List[dict]:
    """把导出的 Netscape cookie 文件读回 Playwright 结构（profile 模式下的兜底）。"""
    out: List[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 7:
                continue
            domain, _sub, cpath, secure, expires, name, value = parts
            out.append({
                "name": name, "value": value, "domain": domain, "path": cpath or "/",
                "expires": normalize_expires(expires),
                "httpOnly": False, "secure": secure.upper() == "TRUE", "sameSite": "Lax",
            })
    except Exception:
        return []
    return out


def prepare(platform: str, mode: str = "auto") -> Tuple[List[dict], str]:
    """
    按 mode 准备登录态。返回 (playwright_cookies, 说明文字)。
    同时把结果落到 .cookies/<平台>.txt 供 yt-dlp 复用。
    """
    mode = (mode or "auto").lower()
    if mode in ("chrome", "auto"):
        cookies = extract_from_chrome(platform)
        if cookies:
            dump_netscape(cookies, cookie_file_for(platform))
            tag = "已登录" if looks_logged_in(cookies) else "⚠️ 未见登录标记"
            return cookies, f"已从本机 {BROWSER} 读取 {len(cookies)} 条 cookie（{tag}）"
        if mode == "chrome":
            return [], (f"❌ 没能从本机 {BROWSER} 读到该平台 cookie："
                        f"确认用的是同一个浏览器/账号，macOS 首次读取需在钥匙串弹窗点“允许”")

    f = cookie_file_for(platform)
    if f.exists():
        return cookies_from_file(f), f"将使用已保存的登录态（{f.name}）"
    return [], "尚无登录态：请改用 Chrome 来源，或点『打开浏览器登录』"
