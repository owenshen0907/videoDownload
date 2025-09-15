# downloader.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple
import shutil
import requests
import yt_dlp

from config import VIDEOS, BROWSER, PROFILE, UA, REFERER
from state_store import PAGE_TO_PATH
from utils import (
    pick_platform_and_code,
    target_path_for,
    find_existing_by_code,
)

def _browser_cookies():
    if not BROWSER:
        return None
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
        return extract_cookies_from_browser(BROWSER, profile=PROFILE)
    except Exception:
        return None

def _try_direct(direct_url: str, save_to: Path) -> Tuple[bool, Optional[Path], str]:
    cookies = _browser_cookies()
    headers = {"User-Agent": UA, "Referer": REFERER}
    save_to.parent.mkdir(parents=True, exist_ok=True)
    # 直链一般是 mp4；强制落到指定文件名
    try:
        with requests.get(direct_url, headers=headers, cookies=cookies, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(save_to, "wb") as f:
                shutil.copyfileobj(r.raw, f)
        return True, save_to, "direct ok"
    except Exception as e:
        return False, None, f"direct failed: {e}"

def _fallback_ytdlp(page_url: str, base_noext: Path) -> Tuple[bool, Optional[Path], str]:
    """
    yt-dlp 输出模板：<base_noext>.%(ext)s
    下载后寻找以编码为前缀的最新文件返回。
    """
    outtmpl = str(base_noext) + ".%(ext)s"
    logs = []
    def hook(d):
        if d.get("status") == "finished":
            logs.append(f"done: {d.get('filename')}")
    ydl_opts = {
        "outtmpl": outtmpl,
        "retries": 10,
        "fragment_retries": 10,
        "noprogress": True,
        "progress_hooks": [hook],
        "concurrent_fragment_downloads": 4,
        "http_headers": {"User-Agent": UA, "Referer": REFERER},
        "cookiesfrombrowser": (BROWSER, PROFILE, None, None) if BROWSER else None,
        "format": "bv*+ba/b",
        # 某些站点需要此项提高成功率，可按需开启：
        # "geo_bypass": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([page_url])
        # 返回编码匹配的最新文件
        code = base_noext.name
        saved = find_existing_by_code("douyin", code)  # 这里只有 douyin，更多平台时按 pf 传参
        return True, saved, "\n".join(logs) or "ytdlp ok"
    except Exception as e:
        return False, None, f"ytdlp failed: {e}"

def download_video(direct_url: Optional[str], page_url: Optional[str]) -> Tuple[bool, Optional[str], str]:
    """
    命名规范：videos/<platform>/<code>.<ext>
    逻辑：优先直链 -> 回退 ytdlp；成功后写入 PAGE_TO_PATH[page_url] = 保存路径
    """
    pf, code, msg = pick_platform_and_code(page_url, direct_url)
    if pf != "douyin" or not code:
        return False, None, f"不支持的平台或无法提取编码：{msg}"

    # 目标“基名”与默认直链文件名（mp4）
    base_noext = target_path_for(pf, code)          # e.g. videos/douyin/7536...
    mp4_target = target_path_for(pf, code, "mp4")   # e.g. videos/douyin/7536....mp4

    # 如果已存在同编码文件，直接返回“已存在”
    existing = find_existing_by_code(pf, code)
    if existing:
        if page_url:
            PAGE_TO_PATH[page_url] = str(existing)
        return True, str(existing), "already exists"

    # 直链优先
    if direct_url:
        ok, path, log = _try_direct(direct_url, mp4_target)
        if ok and path:
            if page_url:
                PAGE_TO_PATH[page_url] = str(path)
            return True, str(path), log

    # 回退 ytdlp（按页面链接）
    if page_url:
        ok2, path2, log2 = _fallback_ytdlp(page_url, base_noext)
        if ok2 and path2:
            PAGE_TO_PATH[page_url] = str(path2)
            return True, str(path2), log2

    return False, None, "download failed"