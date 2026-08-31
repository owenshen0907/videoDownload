# 🎥 视频解析 · 下载 · 抽帧

支持 **抖音** 和 **小鹅通**（xiaoe-tech）。基于 yt-dlp + Playwright + ffmpeg。

目前以**命令行**为主（功能完整、已实测跑通）；图形界面还在，但先放着没打磨。

---

## 🚀 快速开始

### 1. 装依赖

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-cli.txt
```

```bash
.venv/bin/playwright install chromium
```

### 2. 装 ffmpeg（必须）

抽帧要用它；下载 HLS 时也靠它把分片封装成标准 mp4，否则只能得到 `.ts`。

```bash
brew install ffmpeg
```

Ubuntu/Debian 用 `sudo apt install ffmpeg`，Windows 用 `winget install Gyan.FFmpeg`。

### 3. 自检

```bash
./vd doctor
```

正常应该看到 ffmpeg / yt-dlp / playwright 都在，小鹅通登录态显示 `✅ 含登录标记`。

### 4. 下载

单条，链接直接从浏览器地址栏复制：

```bash
./vd "<把浏览器地址栏的课程链接粘这里>"
```

整门课批量下载（推荐，见下面的 CSV 一节）：

```bash
./vd csv 视频直达链接.csv --dry-run
```

`./vd` 会自动用项目里的 `.venv`。如果你用 conda 环境，直接 `python cli.py <链接>` 也一样。

---

## 📖 命令一览

| 命令 | 作用 |
| --- | --- |
| `./vd <链接>` | 下载（`./vd get <链接>` 的简写） |
| `./vd get <链接> <链接> ...` | 批量下载，已下载的自动跳过 |
| `./vd get <链接> --frames 5` | 下载完顺便每 5 秒抽一帧 |
| `./vd get <链接> --headed` | 显示浏览器窗口（解析不出来时用来看卡在哪） |
| `./vd get <链接> --wait 25000` | 加长等直链的时间，默认 15000 毫秒 |
| `./vd csv <清单.csv>` | 按 CSV 批量下载，支持并发与限流（批量首选） |
| `./vd csv <清单.csv> --dry-run` | 只看会生成什么路径，不下载 |
| `./vd batch <清单.md>` | 按 Markdown 清单批量下载 |
| `./vd batch <清单.md> --dry-run` | 只检查清单写得对不对，不下载 |
| `./vd template` | 生成一份清单模板 |
| `./vd frames "videos/xiaoe/*.mp4" --step 5` | 对已有视频抽帧，支持通配符 |
| `./vd ls` | 列出已下载的视频 |
| `./vd doctor` | 环境与登录态自检 |
| `./vd login <链接>` | 手动登录（只在 Chrome 里没登录时才需要） |

抽帧间隔支持 1~60 秒。

---

## 📊 用 CSV 批量下载（大批量首选）

课程目录导出成 CSV 之后，一条命令全下下来，自动按「阶段 / 小节」建目录、
按「序号 + 标题」命名。

```bash
./vd csv 视频直达链接.csv --dry-run
```

```bash
./vd csv 视频直达链接.csv --jobs 5 --interval 10
```

| 参数 | 说明 |
| --- | --- |
| `--out 目录` | 输出根目录，默认为 CSV 所在目录 |
| `--jobs N` | 并发数，默认 3 |
| `--interval S` | 相邻任务的启动间隔秒数，默认 10（限流，别调太小） |
| `--limit N` | 只跑前 N 条，先小批试跑用 |
| `--only 视频` | 只处理某个类型 |
| `--frames N` | 下载完顺便抽帧 |

### CSV 需要哪些列

列名自动识别，不用完全一致，包含关键词即可：

| 用途 | 认的列名关键词 |
| --- | --- |
| 链接（必需） | 直达链接 / 链接 / 地址 / url / link |
| 标题 | 标题 / 视频名称 / 名称 / title / name |
| 序号 | 原序号 / 序号 / 编号 / no |
| 目录层级 | 课程 / 阶段 / 小节 / 章节 / 分组（**按 CSV 里的列顺序**逐级建目录） |
| 类型 | 类型（用于 `--only` 过滤） |

文件名 = `<序号> <标题>.mp4`，路径 = `<输出根目录>/<阶段>/<小节>/`。
支持 Excel 导出的 BOM。**已下载的自动跳过**，中断后重跑同一条命令即可续传。

如果 CSV 里有两条会落到同一个文件名（同目录 + 同「序号 标题」），
`--dry-run` 会告警并指出是第几行冲突 —— 这种情况下第二条会被当成「已下载」跳过，
等于静默丢数据，所以务必先改掉再跑。

### 关于并发和限流

`--interval` 是**任务启动间隔**，`--jobs` 是同时在跑的上限。两者共同限流：
比如 `--jobs 5 --interval 10`，任务会在第 0、10、20、30、40 秒依次启动，
最多 5 个同时在跑。

别把 `--interval` 调到 0 去压榨速度 —— 直链是带签名的，短时间大量请求容易触发风控。

实测：一门 224 节的课程（`--jobs 5 --interval 10`，家用宽带）

| | 条数 | 耗时 | 体积 | 均速 |
| --- | --- | --- | --- | --- |
| 点播课 | 205 | 34.6 分钟 | 9.4 GB | 4.65 MB/s |
| 直播回放 | 14 | 11.1 分钟 | 16.8 GB | 25.7 MB/s |
| **合计** | **224** | — | **28 GB / 107 小时** | — |

结果用 ffprobe 全量校验：224 个文件都是有效 mp4（容器 + 视频轨 + 音频轨），
时长与课程页标注**逐条吻合**（无一条偏差超过 30 秒）。

途中出现过 1 条网络读超时，重跑同一条命令自动跳过已完成的 204 条、只补那 1 条即可。
全程没有触发风控。

两点提醒：

- **直播回放是 1080P，单条常在 1~2GB**，比点播课大一个量级。一门课的总量可能远超直觉，
  下载前先看一眼磁盘余量。
- 时间瓶颈是 `--interval` 而不是带宽：224 条 × 10 秒 ≈ 37 分钟，和实测吻合。

---

## 📋 用 Markdown 清单批量下载

自己整理一份 Markdown 清单，写上「视频名称 + 链接」，一条命令全下下来，
文件直接按你写的名字命名。

```bash
./vd template 我的课程.md
```

编辑这个文件，然后先干跑检查一遍：

```bash
./vd batch 我的课程.md --dry-run
```

会逐条列出：名称、平台、是否已下载。确认无误再真下：

```bash
./vd batch 我的课程.md
```

### 清单怎么写

每行一条，下面几种写法都认，可以混用：

```markdown
## 第1讲 形容词

- [01 形容词的分类](https://xxx.pc.xiaoe-tech.com/p/t_pc/course_pc_detail/video/v_aaa?product_id=course_x)
- [02 4种基本形式](https://xxx.pc.xiaoe-tech.com/p/t_pc/course_pc_detail/video/v_bbb?product_id=course_x)

| 视频名称 | 链接 |
| --- | --- |
| 03 活用总表 | https://xxx.pc.xiaoe-tech.com/p/t_pc/course_pc_detail/video/v_ccc |

04 て形 | https://xxx.pc.xiaoe-tech.com/p/t_pc/course_pc_detail/video/v_ddd

https://xxx.pc.xiaoe-tech.com/p/t_pc/course_pc_detail/video/v_eee
```

- 链接**直接从浏览器地址栏复制**，不用管里面的 `product_id`
- 只写链接不写名称，就用课程自带的标题
- 文件名不用加 `.mp4`；名字里有 `/ : ? *` 会自动替换
- 想排序整齐就自己在名字前加 `01 02 03`
- 名字撞了会自动加 `(2)`，不会覆盖已有文件
- `## 章节标题`、空行、`<!-- 注释 -->`、\`\`\` 代码块都会忽略
- **已下载的自动跳过**，清单可以放心重复跑；判重靠 `videos/<平台>/.index.json`
  记录的「资源编码 → 文件名」，所以你事后重命名文件也不会导致重复下载

---

## 🔐 小鹅通说明

### 点播和直播回放的区别

两种都支持，但入口不同，代码会自动分辨：

- **点播课**（`v_` 开头）：直接进课程详情页起播
- **直播回放**（`l_` 开头）：详情页上得先点「进入回看」，播放器会在**新标签页**里打开，
  清单是 `playlist_eof.m3u8`。回放通常是 1080P，文件比点播课大一个量级


小鹅通课程是**付费内容**，服务端按账号校验权限。本项目**不绕过任何购买校验**，
只是复用你自己已购买账号的登录态，把播放器真实请求的直链抓下来。

### 登录态：默认直接用你本机 Chrome 的

只要你平时在 Chrome 里登录着这个店铺，什么都不用做。
macOS 首次读取会弹钥匙串授权（Chrome Safe Storage），点「允许」即可。

Chrome 里没登录，才需要 `./vd login <链接>`：会弹出浏览器，登录完**直接关掉窗口**，
登录态存在 `.browser_profiles/`，和 Chrome 无关。

### 两个实际会踩的坑（代码已自动处理）

**1. 链接里的 `product_id` 会导致「无权限」**

同一节课常常挂在多个商品下。你复制到的链接带的 `product_id` 如果不是你实际购买的那个商品，
服务端会直接跳 `no_permission`，**明明有观看权限也进不去**。

代码会自动改用不带 `product_id` 的 `middle_page` 入口，由服务端匹配你有权限的商品，
两个入口都试。所以你直接粘浏览器里的链接就行，不用手动改。

**2. 下载下来的 mp4 打不开**

小鹅通的 HLS 是 MPEG-TS 分片。没装 ffmpeg 时会把 TS 原样拼进 `.mp4`，
扩展名是 mp4、内容其实是 TS，QuickTime 打不开。装了 ffmpeg 就没这问题；
真没装的话代码会检测文件头并老实改名 `.ts`（VLC / IINA 仍能播）。

### 排查

| 现象 | 处理 |
| --- | --- |
| `❌ 已登录，但没有观看权限` | 该账号没买/没领这门课；也可能 PC 端登录的账号和手机端买课的不是同一个 |
| `doctor` 读到 0 条 cookie | 钥匙串弹窗没点允许；或改用 `./vd login` |
| `❌ 未捕获到直链` | 加 `--headed` 看浏览器卡在哪，或 `--wait 25000` |
| `浏览器启动失败` | 登录窗口还开着 —— 同一 profile 不能被两个进程同时打开 |
| 解密特别慢 | 装 `pycryptodomex`（`requirements-cli.txt` 里有） |

---

## 📂 目录结构

```
vd                      # 命令行入口
cli.py                  # 命令实现
playlist.py             # 下载清单解析（Markdown 与 CSV）
playlist.example.md     # Markdown 清单模板
sniffer.py              # Playwright 嗅探直链（含登录态注入、入口回退）
downloader.py           # yt-dlp 下载 + HLS 解密 + 容器修正
cookie_source.py        # 登录态来源（本机 Chrome / 独立 profile）
frame_extractor.py      # ffmpeg 抽帧
utils.py  config.py     # 平台识别、命名、路径、配置

videos/
  ├── douyin/           # 抖音视频
  └── xiaoe/            # 小鹅通视频，命名 <资源id>__<课程标题>.mp4
  └── .index.json       # 资源编码 → 文件名，用于判重
frames/<视频名>/         # 抽帧结果（同名 .zip 是打包版）
.browser_profiles/      # 独立登录态（勿提交）
.cookies/               # 导出给 yt-dlp 的 cookie（勿提交）
```

---

## 🖥️ 图形界面（暂未打磨）

```bash
pip install -r requirements.txt && python app_gradio.py
```

需要 Python 3.10+（Gradio 要求）。功能和命令行一致，界面还没细调。

---

## ⚠️ 能力边界

- **不绕过购买校验**：必须用你自己有观看权限的账号，账号没权限就是下不了。
- **不破解商业级 DRM**：小鹅通部分课程走腾讯云 Widevine / FairPlay，这类即使抓到 m3u8
  也无法解密，本项目不会去绕过。**标准 HLS AES-128**（key 走普通 HTTP）的课程可以正常落盘 ——
  目前实测的课程属于这一类。
- **清晰度**：点播课抓的是播放器当前正在用的那一路，想要 1080P 先在网页播放器里切到 1080P
  再解析；直播回放本身就是 1080P。
- **直链有时效性**：解析完尽快下载。
- 下载内容请仅用于**个人学习备份**，不要二次传播；是否允许下载以课程方/平台的服务条款为准。
