# utils.py
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Optional, Tuple, Literal
from urllib.parse import urlparse, parse_qs

from config import BASE, PLATFORM_REFERER, COOKIES

Platform = Literal["douyin", "xiaoe"]

PLATFORM_DIRS = {
    "douyin": BASE / "videos" / "douyin",
    "xiaoe": BASE / "videos" / "xiaoe",
}

PLATFORM_LABELS = {
    "douyin": "抖音",
    "xiaoe": "小鹅通",
}

# 资源 id → 小鹅通 resource_type（middle_page 入口需要）
XIAOE_RESOURCE_TYPE = {"i": 1, "a": 2, "v": 3, "l": 4}

_UNSAFE_FS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def safe_filename(name: str, limit: int = 80) -> str:
    """把课程标题清成可用的文件名片段（保留中文，去掉路径分隔符和控制字符）。"""
    s = _UNSAFE_FS.sub("_", (name or "").strip())
    s = re.sub(r"\s+", " ", s).strip(" .")
    # 去掉常见的扩展名尾巴，避免出现 xxx.mp4.mp4
    s = re.sub(r"\.(mp4|mp3|m4a|ts|mov|mkv)$", "", s, flags=re.I)
    return s[:limit]


def normalize_xiaoe_url(url: str) -> Optional[str]:
    """
    把小鹅通课程链接换成 middle_page 入口。

    为什么要换：课程详情页链接里的 product_id 指的是「从哪个商品进来的」，
    如果这个商品不是你实际购买的那个（同一节课常常挂在多个商品下），
    服务端会直接判 no_permission —— 明明有观看权限也进不去。
    middle_page 不带 product_id，由服务端自己去匹配你有权限的商品。
    """
    code = extract_code_xiaoe(url)
    origin = origin_of(url)
    if not code or not origin:
        return None
    rtype = XIAOE_RESOURCE_TYPE.get(code.split("_", 1)[0], 3)
    return f"{origin}/p/t_pc/course_pc_detail/middle_page/{code}?resource_type={rtype}"


def cookie_file_for(platform: str) -> Path:
    """需要登录态的平台，嗅探时导出的 Netscape cookie 文件位置。"""
    return COOKIES / f"{platform}.txt"

def ensure_platform_dir(pf: Platform) -> Path:
    d = PLATFORM_DIRS[pf]
    d.mkdir(parents=True, exist_ok=True)
    return d

def detect_platform(url: str) -> Optional[Platform]:
    u = (url or "").lower()
    if "douyin.com" in u or "v.douyin.com" in u:
        return "douyin"
    # 小鹅通店铺域名形如 appXXXX.pc.xiaoe-tech.com / appXXXX.h5.xiaoeknow.com。
    # 商家还可以绑定自有域名，这类域名没法穷举（各家策略不同），
    # 但小鹅通会统一加 xet-pc. / .xet. 这层前缀，例如 app5xxx.xet-pc.citv.cn，
    # 所以靠这个前缀特征兜底，而不是维护域名白名单。
    # 连前缀都不带的，再退到 URL 路径特征（见 detect_platform_loose）。
    if ("xiaoe-tech.com" in u or "xiaoeknow.com" in u or "xiaoecloud.com" in u
            or "xet.tech" in u or "xeknow.com" in u
            or "xet-pc." in u or ".xet." in u):
        return "xiaoe"
    return None

# 小鹅通资源 id：v_(视频) a_(音频) i_(图文) l_(直播) term_(专栏/训练营) p_(打卡)
_XIAOE_ID = re.compile(r"\b((?:v|a|i|l|p|term|course)_[0-9a-zA-Z]{6,})")

def detect_platform_loose(url: str) -> Optional[Platform]:
    """
    先按域名识别；识别不出来时，用小鹅通独有的 URL 特征兜底，
    以支持商家绑定的自有域名（如 xxx.com/p/t_pc/course_pc_detail/video/v_xxx）。
    """
    pf = detect_platform(url)
    if pf:
        return pf
    u = url or ""
    if "/p/t_pc/" in u or "/p/course/" in u or "course_pc_detail" in u:
        if _XIAOE_ID.search(u):
            return "xiaoe"
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

def extract_code_xiaoe(url: str) -> Optional[str]:
    """
    规则（取“资源 id”，不取 product_id/course_id，保证一课一文件）：
    - .../course_pc_detail/video/v_xxxxxxxxxxxxxxxxxxxxxxxx?product_id=course_xxx => v_xxxxxxxxxxxxxxxxxxxxxxxx
    - .../course_pc_detail/audio/a_xxxx                                           => a_xxxx
    - 兜底：?resource_id=v_xxx / ?id=v_xxx
    """
    path = urlparse(url).path or ""
    m = _XIAOE_ID.search(path)
    if m:
        return m.group(1)

    qs = parse_qs(urlparse(url).query or "")
    for key in ("resource_id", "id", "video_id", "sub_id"):
        for val in qs.get(key, []):
            m2 = _XIAOE_ID.search(val)
            if m2:
                return m2.group(1)
            if val:
                return re.sub(r"[^0-9a-zA-Z_\-]", "", val)[:64] or None

    # 最后兜底：整条 URL 里第一个资源 id
    m3 = _XIAOE_ID.search(url or "")
    return m3.group(1) if m3 else None

def extract_code(platform: Platform, url: str) -> Optional[str]:
    if platform == "douyin":
        return extract_code_douyin(url)
    if platform == "xiaoe":
        return extract_code_xiaoe(url)
    return None

def origin_of(url: str) -> str:
    p = urlparse(url or "")
    if p.scheme and p.netloc:
        return f"{p.scheme}://{p.netloc}"
    return ""

def referer_for(platform: Optional[Platform], page_url: Optional[str]) -> str:
    """
    平台默认 Referer；小鹅通是一店一域名，取页面链接自身 origin。
    """
    ref = PLATFORM_REFERER.get(platform or "", None)
    if ref:
        return ref
    o = origin_of(page_url or "")
    return (o + "/") if o else ""

def target_path_for(platform: Platform, code: str, ext: Optional[str] = None) -> Path:
    # 默认 mp4；yt-dlp 下载时可能是别的容器，这里仅构造“基名”，让调用方选择 .mp4 或 .%(ext)s
    out_dir = ensure_platform_dir(platform)
    if ext:
        return out_dir / f"{code}.{ext}"
    else:
        return out_dir / f"{code}"

# 下载完成的文件，可能是任意扩展名；这些是下载中途产物，不算数
_PARTIAL_SUFFIXES = (".part", ".ytdl", ".temp")


def files_with_stem(directory: Path, stem: str) -> list:
    """
    找出 directory 下主干名等于 stem 的已完成文件。

    刻意不用 glob：课程标题里出现 [ ] 会被 glob 当成字符类，
    比如「a[1] test.*」匹配不到真实文件 a[1] test.mp4，导致重复下载。
    """
    if not directory.is_dir():
        return []
    out = []
    for p in directory.iterdir():
        if not p.is_file() or p.stem != stem:
            continue
        if p.suffix.lower() in _PARTIAL_SUFFIXES:
            continue
        out.append(p)
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def _index_file(platform: Platform) -> Path:
    return ensure_platform_dir(platform) / ".index.json"


def index_load(platform: Platform) -> dict:
    try:
        return json.loads(_index_file(platform).read_text(encoding="utf-8"))
    except Exception:
        return {}


def index_put(platform: Platform, code: str, path: Path) -> None:
    """记下「资源编码 → 实际文件名」。文件名可以是用户自定义的，靠这份索引才能判重。"""
    if not code:
        return
    data = index_load(platform)
    data[code] = path.name
    try:
        _index_file(platform).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def find_existing_by_code(platform: Platform, code: str) -> Optional[Path]:
    if platform not in PLATFORM_DIRS or not code:
        return None
    out_dir = ensure_platform_dir(platform)

    # 先查索引：用户用自定义名称下载的文件，只能靠索引找回来
    name = index_load(platform).get(code)
    if name:
        p = out_dir / name
        if p.is_file():
            return p
    # 匹配任意后缀（mp4、mkv、webm等），优先最新；排除 yt-dlp 的中间文件
    cands = [
        p for p in out_dir.glob(f"{code}*")
        if p.is_file()
        # 文件名是 <编码> 或 <编码>__<标题>
        and (p.stem == code or p.stem.startswith(code + "__"))
        and p.suffix.lower() not in (".part", ".ytdl", ".temp")
        # 排除 yt-dlp 未合并的分轨中间文件（形如 v_xxx.f137.mp4）
        and not re.fullmatch(rf"{re.escape(code)}\.f\d+", p.stem)
    ]
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not cands:
        return None
    # 索引自愈：旧格式命名的文件补记一次，之后就能直接命中索引
    index_put(platform, code, cands[0])
    return cands[0]

def pick_platform_and_code(page_url: Optional[str], direct_url: Optional[str]) -> Tuple[Optional[Platform], Optional[str], str]:
    """
    优先从 page_url 识别平台和编码；不行再尝试 direct_url。
    """
    src = page_url or direct_url or ""
    pf = detect_platform_loose(src) or detect_platform_loose(direct_url or "")
    if not pf:
        return None, None, "无法识别平台"
    code = extract_code(pf, page_url or "") or extract_code(pf, direct_url or "")
    if not code:
        return pf, None, "未能从链接中提取视频编码"
    return pf, code, "ok"
