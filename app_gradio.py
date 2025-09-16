# app_gradio.py
from __future__ import annotations
import asyncio
from pathlib import Path
from urllib.parse import quote
from typing import List, Tuple

import gradio as gr
from gradio import mount_gradio_app
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, FileResponse

from parser import sniff_serial
from downloader import download_video
from extractor import extract_frames
from state_store import PAGE_TO_PATH
from utils import detect_platform, extract_code, find_existing_by_code
from config import STEP_MIN, STEP_MAX

# 示例（有用户输入时自动忽略）
EXAMPLES = [
    "https://v.douyin.com/nZasikV8ea4/",
    "https://v.douyin.com/urI4O20_90U/",
]

RUNNING = False  # 简单互斥
Row = List[str]  # [page_url, direct_url, status]


# ---------- 工具 ----------
def precheck_rows(urls: List[str]) -> Tuple[List[Row], List[str]]:
    """
    立刻生成清单：已下载 -> 直接标注；未下载 -> 待解析
    返回 rows 与需要解析的 to_parse
    """
    rows, to_parse = [], []
    for u in urls:
        pf = detect_platform(u) or "douyin"
        code = extract_code(pf, u) if pf else None
        existing = find_existing_by_code(pf, code) if (pf and code) else None
        if existing:
            PAGE_TO_PATH[u] = str(existing)  # 让抽帧可立即用
            rows.append([u, "", f"✅ 已下载 · {existing.name}"])
        else:
            rows.append([u, "", "⏳ 待解析"])
            to_parse.append(u)
    return rows, to_parse


def _short(u: str, n: int = 28) -> str:
    return (u[:n] + "…") if len(u) > n else u


def build_table(rows: List[Row], step_val: int) -> str:
    """只读 HTML 表格；抽帧链接仅对已下载可点"""
    step_val = max(STEP_MIN, min(STEP_MAX, int(step_val or 1)))
    html = [
        "<table style='border-collapse:collapse;width:100%;font-size:14px'>",
        "<thead><tr>",
        "<th style='border:1px solid #ddd;padding:8px'>序号</th>",
        "<th style='border:1px solid #ddd;padding:8px'>原始链接</th>",
        "<th style='border:1px solid #ddd;padding:8px'>直链预览</th>",
        "<th style='border:1px solid #ddd;padding:8px'>状态</th>",
        f"<th style='border:1px solid #ddd;padding:8px'>抽帧（每 {step_val}s）</th>",
        "</tr></thead><tbody>",
    ]
    for i, (u, direct, status) in enumerate(rows, 1):
        orig = f'<a href="{u}" target="_blank" rel="noopener">原始</a>'
        dspan = (
            f'<a href="{direct}" target="_blank" rel="noopener">直链</a>'
            if direct else "<span style='color:#999'>待解析</span>"
        )
        can_extract = (u in PAGE_TO_PATH)
        ex = (
            f'<a href="/api/extract_by_page?page_url={quote(u, safe="")}&step={step_val}" target="_blank">抽帧</a>'
            if can_extract else "<span style='color:#999'>请先下载</span>"
        )
        html.append(
            "<tr>"
            f"<td style='border:1px solid #ddd;padding:8px'>{i}</td>"
            f"<td style='border:1px solid #ddd;padding:8px'>{orig}</td>"
            f"<td style='border:1px solid #ddd;padding:8px;word-break:break-all'>{dspan}</td>"
            f"<td style='border:1px solid #ddd;padding:8px'>{status}</td>"
            f"<td style='border:1px solid #ddd;padding:8px'>{ex}</td>"
            "</tr>"
        )
    html.append("</tbody></table>")
    return "\n".join(html)


# ---------- UI ----------
with gr.Blocks(title="抖音直链解析 + 固定目录下载 + 抽帧") as demo:
    gr.Markdown("""
# 🎥 抖音视频直链解析 · 下载 · 抽帧
- 点 **一键解析**：先列清单（已下载/待解析），**只解析未下载**的链接
- 左侧可**多选**条目 → **下载所选**：仅下载“尚未下载”的，**已下载不重复**
- 左侧可**多选**条目 → **抽帧所选**：仅对“已下载”的执行，按“每 N 秒一帧”打包 zip 返回
    """)

    urls_in = gr.Textbox(label="视频链接（每行一个）", value="\n".join(EXAMPLES), lines=6)
    with gr.Row():
        headless = gr.Checkbox(value=True, label="无头模式（不弹窗）")
        wait_ms = gr.Slider(3000, 20000, value=8000, step=500, label="等待时长（毫秒）")
    step_slider = gr.Slider(STEP_MIN, STEP_MAX, value=1, step=1, label="抽帧间隔（秒）")

    # 操作按钮
    with gr.Row():
        btn_parse   = gr.Button("一键解析", variant="primary")
        btn_dl      = gr.Button("⬇️ 下载所选（批量）", variant="secondary")
        btn_extract = gr.Button("🖼️ 抽帧所选（批量）", variant="secondary")

    # 左侧多选 + 右侧表格
    with gr.Row():
        with gr.Column(scale=1, min_width=300):
            select_multi = gr.CheckboxGroup(choices=[], label="选择多条（与右侧表格序号对应）", value=[])
            status_note  = gr.Markdown("")
        with gr.Column(scale=5):
            results_html = gr.HTML(label="解析结果")
            extract_msg  = gr.HTML()

    rows_state = gr.State([])  # List[Row]


    # ---------- 解析（两阶段） ----------
    def run_batch(urls_text: str, headless_val: bool, wait_ms_val: int, step_val: int, prog=gr.Progress()):
        global RUNNING
        if RUNNING:
            yield results_html, rows_state, select_multi, status_note
            return
        RUNNING = True
        try:
            urls = [x.strip() for x in urls_text.splitlines() if x.strip()]
            # 用户输入过 → 过滤示例
            # if any(u not in EXAMPLES for u in urls):
            #     urls = [u for u in urls if u not in EXAMPLES]
            if not urls:
                yield "<p>请输入至少一个有效链接</p>", [], gr.update(choices=[], value=[]), "⚠️ 无链接"
                return

            # ① 预检查：立即展示
            rows_pre, to_parse = precheck_rows(urls)
            table1 = build_table(rows_pre, step_val)
            choices = [f"{i+1}｜{_short(rows_pre[i][0])}" for i in range(len(rows_pre))]
            yield table1, rows_pre, gr.update(choices=choices, value=[]), "清单已生成"

            # ② 仅解析未下载
            if not to_parse:
                return
            prog(0, desc="解析未下载的视频…")
            parsed = asyncio.run(sniff_serial(to_parse, headless=headless_val, wait_ms=wait_ms_val))
            prog(1)

            dmap = {p: d for (p, d, _s) in parsed}
            smap = {p: s for (p, d, s) in parsed}
            merged: List[Row] = []
            for (u, d, s) in rows_pre:
                if s.startswith("⏳"):
                    d = dmap.get(u, "")
                    s = smap.get(u, "❌ 解析失败")
                merged.append([u, d, s])

            table2 = build_table(merged, step_val)
            choices2 = [f"{i+1}｜{_short(merged[i][0])}" for i in range(len(merged))]
            yield table2, merged, gr.update(choices=choices2, value=[]), "解析完成"
        finally:
            RUNNING = False

    btn_parse.click(
        run_batch,
        inputs=[urls_in, headless, wait_ms, step_slider],
        outputs=[results_html, rows_state, select_multi, status_note],
        show_progress="full"
    )


    # ---------- 批量下载 ----------
    def do_download(rows: List[Row], selected_list: List[str], step_val: int):
        if not rows:
            return gr.update(), "请先解析", rows
        if not selected_list:
            return gr.update(), "请先在左侧勾选至少一条", rows

        # 解析选中的序号
        indices: List[int] = []
        for s in selected_list:
            try:
                idx = int(s.split("｜", 1)[0]) - 1
                if 0 <= idx < len(rows):
                    indices.append(idx)
            except Exception:
                pass
        if not indices:
            return gr.update(), "选择解析失败", rows

        # 统计哪些已下载、哪些需要下载
        already, todo = [], []
        for i in indices:
            u, d, st = rows[i]
            if u in PAGE_TO_PATH or (st.startswith("✅ 已下载")):
                already.append(i)
            else:
                todo.append(i)

        if not todo:
            # 全部已下载
            return build_table(rows, step_val), "所选视频全部已下载，未重复下载。", rows

        # 标记下载中
        for i in todo:
            rows[i][2] = "⬇️ 下载中…"
        table_mid = build_table(rows, step_val)

        # 逐条下载（串行更稳定）
        ok_cnt, fail_cnt = 0, 0
        for i in todo:
            page_url, direct_url, _ = rows[i]
            ok, path, log = download_video(direct_url or None, page_url or None)
            if ok and path:
                PAGE_TO_PATH[page_url] = path
                rows[i][2] = f"✅ 已下载 · {Path(path).name}"
                ok_cnt += 1
            else:
                rows[i][2] = "❌ 下载失败"
                fail_cnt += 1

        tip = f"批量下载完成：成功 {ok_cnt} 条；失败 {fail_cnt} 条。"
        table_new = build_table(rows, step_val)
        return table_new, tip, rows

    btn_dl.click(
        do_download,
        inputs=[rows_state, select_multi, step_slider],
        outputs=[results_html, status_note, rows_state],
        show_progress="full"
    )


    # ---------- 批量抽帧 ----------
    def do_extract(rows: List[Row], selected_list: List[str], step_val: int):
        if not rows:
            return "请先解析"
        if not selected_list:
            return "请先在左侧勾选至少一条"

        indices: List[int] = []
        for s in selected_list:
            try:
                idx = int(s.split("｜", 1)[0]) - 1
                if 0 <= idx < len(rows):
                    indices.append(idx)
            except Exception:
                pass
        if not indices:
            return "选择解析失败"

        not_downloaded, ok_links, fail_notes = [], [], []
        for i in indices:
            page_url, _, st = rows[i]
            vp = PAGE_TO_PATH.get(page_url)
            if not vp:
                not_downloaded.append(i + 1)  # 用 1-based 序号提示
                continue
            ok, zip_path, log = extract_frames(vp, step_val)
            if not ok:
                fail_notes.append(f"第{i+1}行：{log}")
            else:
                href = f"/api/extract_by_page?page_url={quote(page_url, safe='')}&step={step_val}"
                ok_links.append(f"第{i+1}行：<a href='{href}' target='_blank'>下载zip</a>")

        parts = []
        if ok_links:
            parts.append("✅ 抽帧完成：<br>" + "<br>".join(ok_links))
        if not_downloaded:
            parts.append("⚠️ 以下未下载，已跳过：" + "、".join(map(str, not_downloaded)))
        if fail_notes:
            parts.append("❌ 失败详情：<br>" + "<br>".join(fail_notes))

        return "<br><br>".join(parts) if parts else "没有可抽帧的条目（可能都未下载）。"

    btn_extract.click(
        do_extract,
        inputs=[rows_state, select_multi, step_slider],
        outputs=[extract_msg],
        show_progress="full"
    )


# ---------- FastAPI 路由（与后端保持一致） ----------
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