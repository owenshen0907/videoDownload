# tabs/local_tab.py
from __future__ import annotations
from pathlib import Path
from typing import List
import hashlib
import gradio as gr

Row = List[str]  # [virtual_key, "", status]

def build_local_tab(CTX: dict):
    STEP_MIN = CTX["STEP_MIN"]
    STEP_MAX = CTX["STEP_MAX"]
    PAGE_TO_PATH = CTX["PAGE_TO_PATH"]
    extract_frames = CTX["extract_frames"]

    def _virtual_key_for_local(path: str) -> str:
        h = hashlib.sha1(Path(path).resolve().as_posix().encode("utf-8")).hexdigest()[:10]
        return f"local://{h}-{Path(path).name}"

    def _short(u: str, n: int = 28) -> str:
        return (u[:n] + "…") if len(u) > n else u

    def build_local_table(rows: List[Row], step_val: int) -> str:
        from urllib.parse import quote
        step_val = max(STEP_MIN, min(STEP_MAX, int(step_val or 1)))
        html = [
            "<table style='border-collapse:collapse;width:100%;font-size:14px'>",
            "<thead><tr>",
            "<th style='border:1px solid #ddd;padding:8px'>序号</th>",
            "<th style='border:1px solid #ddd;padding:8px'>文件名</th>",
            "<th style='border:1px solid #ddd;padding:8px'>状态</th>",
            f"<th style='border:1px solid #ddd;padding:8px'>抽帧（每 {step_val}s）</th>",
            "</tr></thead><tbody>",
        ]
        for i, (vkey, _d, status) in enumerate(rows, 1):
            can_extract = vkey in PAGE_TO_PATH
            fname = Path(PAGE_TO_PATH.get(vkey, vkey)).name
            ex = (
                f'<a href="/api/extract_by_page?page_url={quote(vkey, safe="")}&step={step_val}" target="_blank">抽帧</a>'
                if can_extract else "<span style='color:#999'>文件无效</span>"
            )
            html.append(
                "<tr>"
                f"<td style='border:1px solid #ddd;padding:8px'>{i}</td>"
                f"<td style='border:1px solid #ddd;padding:8px;word-break:break-all'>{fname}</td>"
                f"<td style='border:1px solid #ddd;padding:8px'>{status}</td>"
                f"<td style='border:1px solid #ddd;padding:8px'>{ex}</td>"
                "</tr>"
            )
        html.append("</tbody></table>")
        return "\n".join(html)

    def _rebuild_local_choices(rows: List[Row]) -> List[str]:
        return [f"{i+1}｜{_short(Path(PAGE_TO_PATH.get(rows[i][0], rows[i][0])).name)}" for i in range(len(rows))]

    # ---------- UI ----------
    local_uploader = gr.File(
        label="上传本地视频（可多选拖拽）",
        file_count="multiple",
        type="filepath",
        file_types=[".mp4", ".mov", ".mkv", ".flv", ".webm"]
    )
    local_step_slider = gr.Slider(STEP_MIN, STEP_MAX, value=1, step=1, label="抽帧间隔（秒）")

    with gr.Row():
        btn_local_refresh = gr.Button("↻ 刷新清单", variant="secondary")
        btn_local_clear   = gr.Button("🧹 清空清单", variant="secondary")
        btn_local_extract = gr.Button("🖼️ 抽帧所选（本地）", variant="primary")

    with gr.Row():
        with gr.Column(scale=1, min_width=300):
            local_select_multi = gr.CheckboxGroup(choices=[], label="选择多条（与右侧表格序号对应）", value=[])
            local_status_note  = gr.Markdown("")
        with gr.Column(scale=5):
            local_results_html = gr.HTML(label="本地文件清单")
            local_extract_msg  = gr.HTML()

    local_rows_state = gr.State([])  # List[Row]，形如 [virtual_key, "", status]

    # ---------- 事件 ----------
    def on_local_files_added(paths: list[str] | None, step_val: int):
        rows: List[Row] = []
        if paths:
            for p in paths:
                if not p:
                    continue
                pth = Path(p)
                if not pth.exists():
                    continue
                vkey = _virtual_key_for_local(str(pth))
                PAGE_TO_PATH[vkey] = str(pth.resolve())
                rows.append([vkey, "", f"✅ 已就绪 · {pth.name}"])

        if not rows:
            return "<p>尚未选择有效视频文件。</p>", [], gr.update(choices=[], value=[]), "⚠️ 无文件"

        table = build_local_table(rows, step_val)
        choices = _rebuild_local_choices(rows)
        return table, rows, gr.update(choices=choices, value=[]), f"已加入 {len(rows)} 个文件"

    def on_local_refresh(rows: List[Row], step_val: int):
        alive_rows: List[Row] = []
        for vkey, d, st in rows or []:
            if vkey in PAGE_TO_PATH and Path(PAGE_TO_PATH[vkey]).exists():
                fname = Path(PAGE_TO_PATH[vkey]).name
                alive_rows.append([vkey, d, f"✅ 已就绪 · {fname}"])
        table = build_local_table(alive_rows, step_val)
        choices = _rebuild_local_choices(alive_rows)
        return table, alive_rows, gr.update(choices=choices, value=[]), f"清单刷新：{len(alive_rows)} 个有效文件"

    def on_local_clear():
        # 只清 UI 状态（不删除 PAGE_TO_PATH 中的映射，以便路由还能下载 zip）
        return "<p>清单已清空。</p>", [], gr.update(choices=[], value=[]), "已清空"

    def do_local_extract(rows: List[Row], selected_list: List[str], step_val: int):
        if not rows:
            return "请先上传文件或刷新清单"
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

        from urllib.parse import quote
        missing, ok_links, fail_notes = [], [], []
        for i in indices:
            vkey, _d, _st = rows[i]
            vp = PAGE_TO_PATH.get(vkey)
            if not vp or not Path(vp).exists():
                missing.append(i + 1)
                continue
            ok, zip_path, log = extract_frames(vp, step_val)
            if not ok:
                fail_notes.append(f"第{i+1}行：{log}")
            else:
                href = f"/api/extract_by_page?page_url={quote(vkey, safe='')}&step={step_val}"
                ok_links.append(f"第{i+1}行：<a href='{href}' target='_blank'>下载zip</a>")

        parts = []
        if ok_links:
            parts.append("✅ 抽帧完成：<br>" + "<br>".join(ok_links))
        if missing:
            parts.append("⚠️ 以下文件缺失或不可读，已跳过：" + "、".join(map(str, missing)))
        if fail_notes:
            parts.append("❌ 失败详情：<br>" + "<br>".join(fail_notes))
        return "<br><br>".join(parts) if parts else "没有可抽帧的条目。"

    # 事件绑定
    local_uploader.change(
        on_local_files_added,
        inputs=[local_uploader, local_step_slider],
        outputs=[local_results_html, local_rows_state, local_select_multi, local_status_note],
    )

    btn_local_refresh.click(
        on_local_refresh,
        inputs=[local_rows_state, local_step_slider],
        outputs=[local_results_html, local_rows_state, local_select_multi, local_status_note],
    )

    btn_local_clear.click(
        on_local_clear,
        inputs=[],
        outputs=[local_results_html, local_rows_state, local_select_multi, local_status_note],
    )

    btn_local_extract.click(
        do_local_extract,
        inputs=[local_rows_state, local_select_multi, local_step_slider],
        outputs=[local_extract_msg],
        show_progress="full"
    )