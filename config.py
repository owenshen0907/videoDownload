from pathlib import Path

BASE = Path(__file__).resolve().parent

VIDEOS = BASE / "videos"
VIDEOS.mkdir(exist_ok=True)

FRAMES = BASE / "frames"
FRAMES.mkdir(exist_ok=True)

# 用哪个本机浏览器读取 Cookie（yt-dlp 支持：chrome / safari / firefox 等）
BROWSER = "chrome"
PROFILE = "Default"  # Chrome 常见：Default / Profile 1 / Profile 2

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REFERER = "https://www.douyin.com/"

# 抽帧限制
STEP_MIN = 1
STEP_MAX = 60