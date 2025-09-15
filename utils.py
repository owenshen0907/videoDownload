# utils.py
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional, Tuple, Literal

from config import BASE

Platform = Literal["douyin"]

PLATFORM_DIRS = {
    "douyin": BASE / "videos" / "douyin",
}

def ensure_platform_dir(pf: Platform) -> Path:
    d = PLATFORM_DIRS[pf]
    d.mkdir(parents=True, exist_ok=True)
    return d

def detect_platform(url: str) -> Optional[Platform]:
    u = (url or "").lower()
    if "douyin.com" in u or "v.douyin.com" in u:
        return "douyin"
    return None

def extract_code_douyin(url: str) -> Optional[str]:
    """
    规则：
    - 长链: https://www.douyin.com/video/7536306586487196969?...  => 7536306586487196969
    - 短链: https://v.douyin.com/nZasikV8ea4/                   => nZasikV8ea4
    """
    m = re.search(r"/video/([0-9]+)", url)
    if m:
        return m.group(1)
    m2 = re.search(r"https?://v\.douyin\.com/([^/?#]+)/?", url)
    if m2:
        return m2.group(1)
    return None

def extract_code(platform: Platform, url: str) -> Optional[str]:
    if platform == "douyin":
        return extract_code_douyin(url)
    return None

def target_path_for(platform: Platform, code: str, ext: Optional[str] = None) -> Path:
    # 默认 mp4；yt-dlp 下载时可能是别的容器，这里仅构造“基名”，让调用方选择 .mp4 或 .%(ext)s
    out_dir = ensure_platform_dir(platform)
    if ext:
        return out_dir / f"{code}.{ext}"
    else:
        return out_dir / f"{code}"

def find_existing_by_code(platform: Platform, code: str) -> Optional[Path]:
    out_dir = ensure_platform_dir(platform)
    # 匹配任意后缀（mp4、mkv、webm等），优先最新
    cands = sorted(out_dir.glob(f"{code}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None

def pick_platform_and_code(page_url: Optional[str], direct_url: Optional[str]) -> Tuple[Optional[Platform], Optional[str], str]:
    """
    优先从 page_url 识别平台和编码；不行再尝试 direct_url。
    """
    src = page_url or direct_url or ""
    pf = detect_platform(src)
    if not pf:
        return None, None, "无法识别平台"
    code = extract_code(pf, page_url or "") or extract_code(pf, direct_url or "")
    if not code:
        return pf, None, "未能从链接中提取视频编码"
    return pf, code, "ok"