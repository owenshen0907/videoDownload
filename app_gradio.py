# app_gradio.py
from __future__ import annotations
from pathlib import Path
from urllib.parse import quote

import gradio as gr
from gradio import mount_gradio_app
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, FileResponse

# 你现有的依赖
from parser import sniff_serial
from downloader import download_video
from extractor import extract_frames
from state_store import PAGE_TO_PATH
from utils import detect_platform, extract_code, find_existing_by_code
from config import STEP_MIN, STEP_MAX

# 新增：两个 Tab 的模块
from tabs.link_tab import build_link_tab
from tabs.local_tab import build_local_tab

# 共享上下文，传给各 Tab，避免循环依赖
CTX = dict(
    STEP_MIN=STEP_MIN,
    STEP_MAX=STEP_MAX,
    PAGE_TO_PATH=PAGE_TO_PATH,
    sniff_serial=sniff_serial,
    download_video=download_video,
    extract_frames=extract_frames,
    detect_platform=detect_platform,
    extract_code=extract_code,
    find_existing_by_code=find_existing_by_code,
)

with gr.Blocks(title="抖音直链解析 + 固定目录下载 + 抽帧") as demo:
    gr.Markdown("# 🎥 抖音视频直链解析 · 下载 · 抽帧")

    with gr.Tabs():
        with gr.Tab("🔗 链接解析 / 下载 / 抽帧"):
            build_link_tab(CTX)   # ← 封装在 tabs/link_tab.py
        with gr.Tab("💻 本地上传 / 抽帧"):
            build_local_tab(CTX)  # ← 封装在 tabs/local_tab.py

# ---------- FastAPI 路由（保持原有逻辑） ----------
app = FastAPI()

@app.get("/api/download")
def api_download(direct_url: str | None = Query(default=None), page_url: str | None = Query(default=None)):
    ok, path, log = download_video(direct_url, page_url)
    return JSONResponse({"status": "ok" if ok else "error", "path": path, "log": log})

@app.get("/api/extract_by_page")
def api_extract_by_page(page_url: str = Query(...), step: int = Query(1)):
    vp = PAGE_TO_PATH.get(page_url)
    if not vp:
        return JSONResponse({"status": "error", "msg": "该链接尚未在服务器下载，无法抽帧。请先下载。"})
    ok, zip_path, log = extract_frames(vp, step)
    if not ok:
        return JSONResponse({"status": "error", "msg": log})
    return FileResponse(zip_path, filename=Path(zip_path).name)

# 挂 Gradio 到根路径
app = mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)