# 🎥 视频直链解析 + 下载 + 抽帧

本项目基于 **Gradio + FastAPI + yt-dlp + ffmpeg**，支持以下功能：
- **一键解析视频直链（目前仅支持抖音）**
- **批量下载**（不会重复下载，已下载直接跳过）
- **批量抽帧**（已下载视频，按“每 N 秒一帧”抽取图片并打包为 zip）
- **前端界面友好**，可直接通过浏览器操作

---

## 🔧 环境准备

### 1. 创建 conda 环境
（Windows 使用 **Anaconda PowerShell**，macOS/Linux 使用终端）

```bash
conda create -n videoDownload python=3.11 -y
conda activate videoDownload
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 安装 ffmpeg（必须）

- **macOS**

  ```bash
  brew install ffmpeg
  ```

- **Ubuntu / Debian**

  ```bash
  sudo apt-get update && sudo apt-get install -y ffmpeg
  ```

- **Windows**

  ```bash
  choco install ffmpeg
  # 或
  winget install Gyan.FFmpeg
  ```

### 4. （可选）Playwright 浏览器内核

解析直链时如需调用 Playwright，需要先安装 Chromium 内核：

```bash
playwright install
```

---

## 🚀 运行

```bash
python app_gradio.py
```

控制台会输出类似信息：

```
Uvicorn running on http://0.0.0.0:7860
```

在浏览器中打开提示的 URL 即可使用。

---

## 🖥️ 使用方法

1. **在输入框中粘贴抖音视频链接（每行一个）**  
   默认提供两个示例链接，用户输入时会自动忽略示例。

2. **点击 一键解析：**
   - 立即生成视频清单（已下载 / 待解析）
   - 对未下载的视频自动尝试解析直链

3. **在左侧勾选视频 → 点击 下载所选：**
   - 仅下载“未下载”的视频；
   - 已下载的视频不会重复下载，会提示“所选视频全部已下载”。

4. **在左侧勾选视频 → 点击 抽帧所选：**
   - 仅对已下载的视频执行抽帧；
   - 可设置 **抽帧间隔（秒）**，默认 1 秒一帧，最大 60 秒；
   - 抽帧结果打包成 zip 文件下载。

---

## 📂 文件结构

```
videos/
  └── douyin/            # 下载的视频
frames/
  └── <视频文件名>/       # 对应视频的抽帧结果
```

---

## ⚠️ 注意事项

- **抖音直链有时效性**，建议直接使用“下载所选”保存到本地。
- **Playwright 解析可能会打开浏览器窗口**，勾选 **无头模式** 可避免弹窗。
- **已下载视频自动跳过解析**，避免重复浪费资源。