# downloader.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import re
import shutil
import subprocess
import requests
import yt_dlp

from config import BROWSER, PROFILE, UA, LOGIN_REQUIRED, COOKIE_SOURCE
from state_store import PAGE_TO_PATH
from utils import (
    Platform,
    pick_platform_and_code,
    target_path_for,
    files_with_stem,
    find_existing_by_code,
    index_put,
    safe_filename,
    referer_for,
    origin_of,
    PLATFORM_LABELS,
    PLATFORM_DIRS,
    cookie_file_for,
)


def _is_hls(url: str) -> bool:
    return ".m3u8" in (url or "").lower()


def _headers_for(pf: Optional[Platform], page_url: Optional[str]) -> Dict[str, str]:
    h = {"User-Agent": UA}
    ref = referer_for(pf, page_url)
    if ref:
        h["Referer"] = ref
        o = origin_of(ref)
        if o:
            h["Origin"] = o
    return h


def _browser_cookies():
    """
    读本机浏览器 cookie（抖音等无需登录态平台）。

    走 cookie_source 而不是直接调 yt-dlp：yt-dlp 是“在 profile 目录下递归找最近修改的
    Cookies 文件”，会误选 Chrome 给扩展分配的私有 cookie 库，结果一条站点 cookie 都读不到。
    """
    if not BROWSER:
        return None
    try:
        import cookie_source
        return _to_jar(cookie_source.extract_from_chrome("douyin"))
    except Exception:
        return None


def _to_jar(cookies):
    """把 cookie 字典列表转成 requests 能用的 cookiejar。"""
    if not cookies:
        return None
    import requests.cookies
    jar = requests.cookies.RequestsCookieJar()
    for c in cookies:
        try:
            jar.set(c["name"], c["value"], domain=c["domain"], path=c.get("path") or "/")
        except Exception:
            continue
    return jar


def _login_cookiejar(pf: Optional[Platform]):
    """把嗅探导出的 cookie 文件读成 requests 能用的 cookiejar。"""
    f = cookie_file_for(pf or "")
    if not f.exists():
        return None
    try:
        from http.cookiejar import MozillaCookieJar
        jar = MozillaCookieJar(str(f))
        jar.load(ignore_discard=True, ignore_expires=True)
        # 站点会往 cookie 里塞中文（店铺名、昵称等）。requests 组 Cookie 头时用
        # latin-1 编码，遇到中文直接抛 UnicodeEncodeError，整个请求发不出去。
        # 这里预先转成 UTF-8 字节的 latin-1 表示，发出去的字节和浏览器一致。
        for c in jar:
            if not c.value:
                continue
            try:
                c.value.encode("latin-1")
            except UnicodeEncodeError:
                c.value = c.value.encode("utf-8").decode("latin-1")
        return jar
    except Exception:
        return None


def _cookie_source(pf: Optional[Platform]) -> Tuple[Optional[str], Optional[tuple]]:
    """
    返回 (cookiefile, cookiesfrombrowser)。两者只能给 yt-dlp 其中一个。
    需要登录态的平台（小鹅通）用嗅探时导出的 cookie 文件，保证和播放器同一份会话。
    """
    f = cookie_file_for(pf or "")
    if not f.exists():
        # 还没解析过也能直接下载：现场取一份登录态导出成文件
        try:
            import cookie_source
            cookie_source.prepare(pf, COOKIE_SOURCE if pf in LOGIN_REQUIRED else "chrome")
        except Exception:
            pass
    if f.exists():
        return str(f), None
    # 没导出成功时，非登录态平台还可以让 yt-dlp 自己去读（成功率低，但聊胜于无）
    if BROWSER and pf not in LOGIN_REQUIRED:
        return None, (BROWSER, PROFILE, None, None)
    return None, None


def _try_direct(direct_url: str, save_to: Path, pf: Optional[Platform],
                page_url: Optional[str]) -> Tuple[bool, Optional[Path], str]:
    """非 HLS 的 mp4 直链：直接流式落盘。"""
    headers = _headers_for(pf, page_url)
    cookies = _login_cookiejar(pf) if pf in LOGIN_REQUIRED else _browser_cookies()
    save_to.parent.mkdir(parents=True, exist_ok=True)
    tmp = save_to.with_suffix(save_to.suffix + ".part")
    try:
        with requests.get(direct_url, headers=headers, cookies=cookies,
                          stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        tmp.replace(save_to)
        return True, save_to, "direct ok"
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return False, None, f"direct failed: {e}"


def _find_output(base_noext: Path) -> Optional[Path]:
    """在 base_noext 所在目录里找回 yt-dlp 落盘的文件（扩展名不定）。"""
    cands = files_with_stem(base_noext.parent, base_noext.name)
    return cands[0] if cands else None


def _ytdlp(url: str, base_noext: Path, pf: Platform,
           page_url: Optional[str]) -> Tuple[bool, Optional[Path], str]:
    """
    统一的 yt-dlp 下载：既能吃页面链接（抖音有内置 extractor），
    也能吃嗅探到的 m3u8/mp4 直链（走 generic + 原生 HLS，支持 AES-128 解密）。
    输出模板 <base_noext>.%(ext)s，下载完按编码找回落盘文件。
    """
    logs = []

    def hook(d):
        if d.get("status") == "finished":
            logs.append(f"done: {d.get('filename')}")

    cookiefile, cookiesfrombrowser = _cookie_source(pf)

    ydl_opts: Dict[str, Any] = {
        "outtmpl": str(base_noext) + ".%(ext)s",
        "retries": 10,
        "fragment_retries": 10,
        "noprogress": True,
        "progress_hooks": [hook],
        "concurrent_fragment_downloads": 8,
        "http_headers": _headers_for(pf, page_url or url),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        # 原生 HLS 下载器：加密 m3u8（AES-128）能带着同一份 header/cookie 取 key
        "hls_prefer_native": True,
    }
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile
    elif cookiesfrombrowser:
        ydl_opts["cookiesfrombrowser"] = cookiesfrombrowser

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        saved = _find_output(base_noext)
        if not saved:
            return False, None, "ytdlp 执行完成，但没有找到落盘文件"
        saved, note = _fix_container(saved)
        return True, saved, "\n".join(logs + ([note] if note else [])) or "ytdlp ok"
    except Exception as e:
        hint = ""
        if pf in LOGIN_REQUIRED and not cookiefile:
            hint = "（未找到登录 cookie：把「登录态来源」设为 chrome，或点『打开浏览器登录』）"
        return False, None, f"ytdlp failed{hint}: {e}"


def _fix_container(path: Path) -> Tuple[Path, str]:
    """
    没有 ffmpeg 时，yt-dlp 会把 HLS 的 MPEG-TS 分片原样拼进 .mp4 文件里 ——
    扩展名是 mp4，内容其实是 TS，QuickTime 之类打不开。
    有 ffmpeg 就无损 remux 成真正的 mp4；没有就老实改名 .ts（播放器仍能播）。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(1)
    except Exception:
        return path, ""
    if head != b"\x47" or path.suffix.lower() not in (".mp4", ".m4a"):
        return path, ""

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        tmp = path.with_name(path.stem + ".remux.mp4")
        proc = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(tmp)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(path)
            return path, "已 remux 为标准 mp4"
        tmp.unlink(missing_ok=True)
        return path, f"remux 失败，保留原文件：{(proc.stdout or '')[-200:]}"

    ts_path = path.with_suffix(".ts")
    path.replace(ts_path)
    return ts_path, "内容是 MPEG-TS：已改名 .ts（装 ffmpeg 后会自动转成 mp4）"


def _unique_stem(pf: Platform, stem: str) -> str:
    """同名文件已被别的视频占用时，加 (2) (3) 后缀，不覆盖已有文件。"""
    out_dir = PLATFORM_DIRS[pf]
    base, i = stem, 2
    while files_with_stem(out_dir, stem):
        stem = f"{base} ({i})"
        i += 1
    return stem


def download_video(direct_url: Optional[str], page_url: Optional[str],
                   name: Optional[str] = None,
                   dest_dir: Optional[Path] = None) -> Tuple[bool, Optional[str], str]:
    """
    命名规范：videos/<platform>/<name 或 code__标题>.<ext>
    逻辑：已存在直接复用 -> m3u8 走 yt-dlp -> mp4 直链流式落盘 -> 回退 yt-dlp（直链/页面）
    成功后写入 PAGE_TO_PATH[page_url] = 保存路径
    """
    pf, code, msg = pick_platform_and_code(page_url, direct_url)
    if not pf or not code:
        return False, None, f"不支持的平台或无法提取编码：{msg}"

    if dest_dir is not None:
        # 指定了输出目录（CSV 模式）：路径完全由调用方决定，判重直接看目标文件在不在
        out_dir = Path(dest_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = safe_filename(name or "") or code
        base_noext = out_dir / stem
        mp4_target = out_dir / f"{stem}.mp4"
        existing = _find_output(base_noext)
    else:
        # 文件名优先用调用方指定的名称（清单里写的），否则用「编码__课程标题」
        stem = safe_filename(name or "")
        if stem:
            stem = _unique_stem(pf, stem)
        else:
            stem = code
            try:
                from sniffer import title_for
                t = safe_filename(title_for(page_url or "") or "")
                if t:
                    stem = f"{code}__{t}"
            except Exception:
                pass
        base_noext = target_path_for(pf, stem)
        mp4_target = target_path_for(pf, stem, "mp4")
        existing = find_existing_by_code(pf, code)

    if existing:
        if page_url:
            PAGE_TO_PATH[page_url] = str(existing)
        return True, str(existing), "already exists"

    logs = []

    def _succeed(path) -> Tuple[bool, Optional[str], str]:
        p = Path(path)
        if dest_dir is None:
            index_put(pf, code, p)
        if page_url:
            PAGE_TO_PATH[page_url] = str(p)
        return True, str(p), ""

    if direct_url:
        if _is_hls(direct_url):
            # HLS 必须交给 yt-dlp 拉分片 + 解密 + ffmpeg 合并，不能直接存 m3u8 文本
            ok, path, log = _ytdlp(direct_url, base_noext, pf, page_url)
            if ok and path:
                return _succeed(path)[:2] + (log,)
            logs.append(log)
        else:
            ok, path, log = _try_direct(direct_url, mp4_target, pf, page_url)
            if ok and path:
                return _succeed(path)[:2] + (log,)
            logs.append(log)
            # mp4 直链失败：再让 yt-dlp 试一次同一条直链
            ok2, path2, log2 = _ytdlp(direct_url, base_noext, pf, page_url)
            if ok2 and path2:
                return _succeed(path2)[:2] + (log2,)
            logs.append(log2)

    # 回退：按页面链接下载。抖音有内置 extractor；小鹅通没有，靠上面的嗅探直链。
    if page_url and pf != "xiaoe":
        ok3, path3, log3 = _ytdlp(page_url, base_noext, pf, page_url)
        if ok3 and path3:
            return _succeed(path3)[:2] + (log3,)
        logs.append(log3)

    if pf == "xiaoe" and not direct_url:
        logs.append(f"{PLATFORM_LABELS[pf]}需要先『一键解析』拿到播放直链，才能下载")

    return False, None, "download failed\n" + "\n".join(x for x in logs if x)
