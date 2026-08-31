# tabs/link_tab.py
from __future__ import annotations
import asyncio
from pathlib import Path
from typing import List, Tuple

import gradio as gr

Row = List[str]  # [page_url, direct_url, status]
RUNNING = False  # 简单互斥

def build_link_tab(CTX: dict):
    STEP_MIN = CTX["STEP_MIN"]
    STEP_MAX = CTX["STEP_MAX"]
    PAGE_TO_PATH = CTX["PAGE_TO_PATH"]
    sniff_serial = CTX["sniff_serial"]
    download_video = CTX["download_video"]
    detect_platform = CTX["detect_platform"]
    extract_code = CTX["extract_code"]
    find_existing_by_code = CTX["find_existing_by_code"]
    open_login = CTX["open_login"]
    PLATFORM_LABELS = CTX["PLATFORM_LABELS"]

    EXAMPLES = [
        "https://v.douyin.com/nZasikV8ea4/",
        "https://appxxxxxxxxxxx.pc.xiaoe-tech.com/p/t_pc/course_pc_detail/video/v_xxxxxxxxxxxxxxxxxxxxxxxx?product_id=course_xxxxxxxxxxxxxxxxxxxxxxxxxx",
    ]

    # ---------- 工具 ----------
    def precheck_rows(urls: List[str]) -> Tuple[List[Row], List[str]]:
        rows, to_parse = [], []
        for u in urls:
            pf = detect_platform(u)
            if not pf:
                rows.append([u, "", "❓ 不支持的平台（目前支持：抖音、小鹅通）"])
                continue
            code = extract_code(pf, u)
            existing = find_existing_by_code(pf, code) if code else None
            if existing:
                PAGE_TO_PATH[u] = str(existing)
                rows.append([u, "", f"✅ 已下载 · {existing.name}"])
            else:
                rows.append([u, "", "⏳ 待解析"])
                to_parse.append(u)
        return rows, to_parse

    def _short(u: str, n: int = 28) -> str:
        return (u[:n] + "…") if len(u) > n else u

    def build_table(rows: List[Row], step_val: int) -> str:
        from urllib.parse import quote
        step_val = max(STEP_MIN, min(STEP_MAX, int(step_val or 1)))
        html = [
            "<table style='border-collapse:collapse;width:100%;font-size:14px'>",
            "<thead><tr>",
            "<th style='border:1px solid #ddd;padding:8px'>序号</th>",
            "<th style='border:1px solid #ddd;padding:8px'>平台</th>",
            "<th style='border:1px solid #ddd;padding:8px'>原始链接</th>",
            "<th style='border:1px solid #ddd;padding:8px'>直链预览</th>",
            "<th style='border:1px solid #ddd;padding:8px'>状态</th>",
            f"<th style='border:1px solid #ddd;padding:8px'>抽帧（每 {step_val}s）</th>",
            "</tr></thead><tbody>",
        ]
        for i, (u, direct, status) in enumerate(rows, 1):
            orig = f'<a href="{u}" target="_blank" rel="noopener">原始</a>'
            dspan = (f'<a href="{direct}" target="_blank" rel="noopener">直链</a>' if direct
                     else "<span style='color:#999'>待解析</span>")
            can_extract = (u in PAGE_TO_PATH)
            ex = (f'<a href="/api/extract_by_page?page_url={quote(u, safe="")}&step={step_val}" target="_blank">抽帧</a>'
                  if can_extract else "<span style='color:#999'>请先下载</span>")
            pf_label = PLATFORM_LABELS.get(detect_platform(u) or "", "—")
            html.append(
                "<tr>"
                f"<td style='border:1px solid #ddd;padding:8px'>{i}</td>"
                f"<td style='border:1px solid #ddd;padding:8px'>{pf_label}</td>"
                f"<td style='border:1px solid #ddd;padding:8px'>{orig}</td>"
                f"<td style='border:1px solid #ddd;padding:8px;word-break:break-all'>{dspan}</td>"
                f"<td style='border:1px solid #ddd;padding:8px'>{status}</td>"
                f"<td style='border:1px solid #ddd;padding:8px'>{ex}</td>"
                "</tr>"
            )
        html.append("</tbody></table>")
        return "\n".join(html)

    # ---------- UI ----------
    urls_in = gr.Textbox(label="视频链接（每行一个）", value="\n".join(EXAMPLES), lines=6)
    with gr.Row():
        headless = gr.Checkbox(value=True, label="无头模式（不弹窗）")
        wait_ms = gr.Slider(3000, 20000, value=8000, step=500, label="等待时长（毫秒）")
    cookie_mode = gr.Radio(
        choices=["chrome", "profile", "auto"],
        value=CTX.get("COOKIE_SOURCE", "auto"),
        label="登录态来源",
        info="chrome=直接复用本机 Chrome 的登录（推荐，不用重复登录）；profile=用下方按钮单独登录一次；auto=先 chrome 再 profile",
    )
    step_slider = gr.Slider(STEP_MIN, STEP_MAX, value=1, step=1, label="抽帧间隔（秒）")

    with gr.Row():
        btn_login   = gr.Button("🔐 打开浏览器登录（小鹅通等需登录的平台）", variant="secondary")
    gr.Markdown(
        "> 小鹅通课程需要**你自己已购买/已领取**的账号。"
        "如果你平时就在本机 Chrome 里登录着，把「登录态来源」选 `chrome` 即可，**不用再登录一次**"
        "（macOS 首次读取会弹钥匙串授权，点允许）。"
        "只有在 Chrome 里没登录时，才需要点上面的按钮弹出浏览器登录，登录完**直接关掉窗口**。"
    )

    with gr.Row():
        btn_parse   = gr.Button("一键解析", variant="primary")
        btn_dl      = gr.Button("⬇️ 下载所选（批量）", variant="secondary")
        btn_extract = gr.Button("🖼️ 抽帧所选（批量）", variant="secondary")

    with gr.Row():
        with gr.Column(scale=1, min_width=300):
            select_multi = gr.CheckboxGroup(choices=[], label="选择多条（与右侧表格序号对应）", value=[])
            status_note  = gr.Markdown("")
        with gr.Column(scale=5):
            results_html = gr.HTML(label="解析结果")
            extract_msg  = gr.HTML()

    rows_state = gr.State([])  # List[Row]

    # ---------- 解析（两阶段） ----------
    def run_batch(urls_text: str, headless_val: bool, wait_ms_val: int, step_val: int,
                  cookie_mode_val: str = "auto", prog=gr.Progress()):
        global RUNNING
        if RUNNING:
            yield results_html, rows_state, select_multi, status_note
            return
        RUNNING = True
        try:
            urls = [x.strip() for x in urls_text.splitlines() if x.strip()]
            if not urls:
                yield "<p>请输入至少一个有效链接</p>", [], gr.update(choices=[], value=[]), "⚠️ 无链接"
                return

            # ① 预检查
            rows_pre, to_parse = precheck_rows(urls)
            table1 = build_table(rows_pre, step_val)
            choices = [f"{i+1}｜{_short(rows_pre[i][0])}" for i in range(len(rows_pre))]
            yield table1, rows_pre, gr.update(choices=choices, value=[]), "清单已生成"

            # ② 仅解析未下载
            if not to_parse:
                return
            prog(0, desc="解析未下载的视频…")
            parsed = asyncio.run(sniff_serial(to_parse, headless=headless_val,
                                              wait_ms=wait_ms_val, cookie_mode=cookie_mode_val))
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

    def do_login(urls_text: str):
        urls = [x.strip() for x in (urls_text or "").splitlines() if x.strip()]
        target = next((u for u in urls if detect_platform(u) == "xiaoe"), None)
        if not target:
            return "⚠️ 请先在上面填入需要登录的平台链接（如小鹅通课程链接），再点登录。"
        return open_login(target)

    btn_login.click(
        do_login,
        inputs=[urls_in],
        outputs=[status_note],
        show_progress="full",
    )

    btn_parse.click(
        run_batch,
        inputs=[urls_in, headless, wait_ms, step_slider, cookie_mode],
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
            return build_table(rows, step_val), "所选视频全部已下载，未重复下载。", rows

        # 标记下载中
        for i in todo:
            rows[i][2] = "⬇️ 下载中…"

        # 逐条下载
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
        from urllib.parse import quote

        for i in indices:
            page_url, _, st = rows[i]
            vp = PAGE_TO_PATH.get(page_url)
            if not vp:
                not_downloaded.append(i + 1)
                continue
            from frame_extractor import extract_frames  # 延迟导入，避免循环
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