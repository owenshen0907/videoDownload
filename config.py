from pathlib import Path

BASE = Path(__file__).resolve().parent

VIDEOS = BASE / "videos"
VIDEOS.mkdir(exist_ok=True)

FRAMES = BASE / "frames"
FRAMES.mkdir(exist_ok=True)

# Playwright 持久化登录目录：需要登录态的平台（小鹅通）在这里保存会话，
# 登录一次之后，后续解析/下载都复用同一份 profile。
PROFILES = BASE / ".browser_profiles"
PROFILES.mkdir(exist_ok=True)

# 嗅探时从 Playwright 导出的 Netscape 格式 cookie，供 yt-dlp 下载 m3u8 时复用登录态。
COOKIES = BASE / ".cookies"
COOKIES.mkdir(exist_ok=True)

# 用哪个本机浏览器读取 Cookie（yt-dlp 支持：chrome / safari / firefox 等）
# 仅用于抖音；小鹅通走上面的持久化 profile + 导出 cookie。
BROWSER = "chrome"
PROFILE = "Default"  # Chrome 常见：Default / Profile 1 / Profile 2

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REFERER = "https://www.douyin.com/"

# 各平台默认 Referer；为 None 表示用页面链接自身的 origin（小鹅通是一店一域名）
PLATFORM_REFERER = {
    "douyin": REFERER,
    "xiaoe": None,
}

# 需要登录态的平台
LOGIN_REQUIRED = {"xiaoe"}

# 登录态来源：
#   "chrome"  直接读本机 Chrome 已登录的 cookie（推荐，不用重复登录）
#   "profile" 用项目自己的 Playwright 持久化登录（.browser_profiles/）
#   "auto"    先 chrome，读不到再退回 profile
COOKIE_SOURCE = "auto"

# 小鹅通播放器不一定自动起播，嗅探时需要点一下播放并多等一会
XIAOE_EXTRA_WAIT_MS = 12000
# “打开浏览器登录”窗口最长等待时间（毫秒）
LOGIN_WAIT_MS = 600_000

# 抽帧限制
STEP_MIN = 1
STEP_MAX = 60
