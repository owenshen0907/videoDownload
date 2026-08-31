#!/usr/bin/env python3
"""
视频解析 / 下载 / 抽帧 命令行工具（抖音 · 小鹅通）

    ./vd doctor                      环境与登录态自检
    ./vd get <链接> [<链接>...]       解析并下载（可多条）
    ./vd get <链接> --frames 5       下载完顺便每 5 秒抽一帧
    ./vd csv <清单.csv>               按 CSV 批量下载（并发 + 限流，推荐）
    ./vd csv <清单.csv> --dry-run     先看会生成什么路径，不下载
    ./vd batch <清单.md>              按清单批量下载并按清单里的名字命名
    ./vd batch <清单.md> --dry-run    只检查清单写得对不对，不下载
    ./vd template                    生成一份清单模板
    ./vd frames <视频文件>...         对已有视频抽帧
    ./vd ls                          列出已下载的视频
    ./vd login <链接>                 手动登录（只在 Chrome 里没登录时才需要）

链接直接从浏览器地址栏复制即可，不用管里面的 product_id。
"""
from __future__ import annotations
import argparse
import asyncio
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional

from config import COOKIE_SOURCE, BROWSER, STEP_MIN, STEP_MAX
from utils import (
    detect_platform_loose, extract_code, find_existing_by_code,
    cookie_file_for, PLATFORM_DIRS, PLATFORM_LABELS,
)

OK, BAD, DOT = "✅", "❌", "·"


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


# ---------------------------------------------------------------- doctor

def cmd_doctor(args) -> int:
    print("环境")
    ff = shutil.which("ffmpeg")
    print(f"  ffmpeg     {ff or BAD + ' 未安装 —— 抽帧用不了，下载的 HLS 也只能存成 .ts'}")
    try:
        import yt_dlp
        print(f"  yt-dlp     {yt_dlp.version.__version__}")
    except Exception as e:
        print(f"  yt-dlp     {BAD} {e}")
    try:
        import playwright  # noqa: F401
        print("  playwright 已安装")
    except Exception:
        print(f"  playwright {BAD} 未安装（pip install playwright && playwright install chromium）")
    try:
        import Cryptodome  # noqa: F401
        print("  解密加速   pycryptodomex 已装")
    except Exception:
        print("  解密加速   未装 pycryptodomex，AES-128 解密会慢很多")

    print("\n登录态（小鹅通需要）")
    import cookie_source
    cookies = cookie_source.extract_from_chrome("xiaoe")
    if cookies:
        mark = f"{OK} 含登录标记" if cookie_source.looks_logged_in(cookies) else "⚠️  没看到登录标记，可能没登录"
        print(f"  本机 {BROWSER}：{len(cookies)} 条 cookie，{mark}")
        for d in sorted({c['domain'] for c in cookies}):
            print(f"      {d}")
    else:
        print(f"  本机 {BROWSER}：{BAD} 没读到 cookie")
        print("      macOS 首次读取会弹钥匙串授权，要点「允许」；")
        print("      或者用 ./vd login <链接> 单独登录一次。")
    f = cookie_file_for("xiaoe")
    print(f"  导出文件：{f if f.exists() else '尚未生成（解析或下载时会自动生成）'}")

    if args.url:
        pf = detect_platform_loose(args.url)
        print(f"\n链接\n  平台：{PLATFORM_LABELS.get(pf, BAD + ' 不支持')}"
              f"\n  编码：{extract_code(pf, args.url) if pf else '—'}")
    return 0


# ---------------------------------------------------------------- login

def cmd_login(args) -> int:
    from sniffer import open_login
    print("正在打开浏览器，请在窗口里完成登录，登录后直接关掉窗口…")
    print(open_login(args.url))
    return 0


# ---------------------------------------------------------------- get

def _download_one(url: str, headless: bool, wait_ms: int, cookie_mode: str,
                  idx: int, total: int, name: str = "") -> Optional[Path]:
    from sniffer import sniff_one
    from downloader import download_video

    prefix = f"[{idx}/{total}] " if total > 1 else ""
    pf = detect_platform_loose(url)
    if not pf:
        print(f"{prefix}{BAD} 不支持的平台：{url}")
        return None

    code = extract_code(pf, url)
    print(f"{prefix}{name or PLATFORM_LABELS[pf] + ' ' + str(code)}")

    existing = find_existing_by_code(pf, code) if code else None
    if existing:
        print(f"     {OK} 已存在，跳过：{existing.name}")
        return existing

    print(f"     {DOT} 解析直链…")
    _u, direct, status = asyncio.run(
        sniff_one(url, headless=headless, wait_ms=wait_ms, cookie_mode=cookie_mode))
    print(f"     {status}")
    if not direct:
        return None

    print(f"     {DOT} 下载中…")
    ok, path, log = download_video(direct, url, name=name or None)
    if not ok or not path:
        print(f"     {BAD} 下载失败\n{log}")
        return None

    p = Path(path)
    note = [ln for ln in log.splitlines() if "remux" in ln or "MPEG-TS" in ln]
    if note:
        print(f"     {DOT} {note[-1]}")
    print(f"     {OK} {p.name}  {_human(p.stat().st_size)}")
    return p


def cmd_get(args) -> int:
    urls = [u.strip() for u in args.urls if u.strip()]
    if not urls:
        print("没有给链接")
        return 2

    done: List[Path] = []
    failed: List[str] = []
    for i, u in enumerate(urls, 1):
        p = _download_one(u, headless=not args.headed, wait_ms=args.wait,
                          cookie_mode=args.cookies, idx=i, total=len(urls))
        (done if p else failed).append(p or u)

    if args.frames:
        print()
        _extract_many(done, args.frames)

    if len(urls) > 1 or failed:
        print(f"\n完成：成功 {len(done)} 条，失败 {len(failed)} 条")
        for u in failed:
            print(f"  {BAD} {u}")
    return 0 if not failed else 1


# ---------------------------------------------------------------- csv（并发 + 限流）

class _Stagger:
    """任务启动节流：保证相邻两个任务的启动时间至少相隔 interval 秒。"""

    def __init__(self, interval: float):
        self.interval = max(0.0, float(interval))
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if not self.interval:
            return
        async with self._lock:
            now = time.monotonic()
            if self._next > now:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self.interval


async def _run_concurrent(tasks, out_root: Path, jobs: int, interval: float,
                          headless: bool, cookie_mode: str, wait_ms: int,
                          frames: Optional[int]) -> tuple:
    from sniffer import shared_sniffer
    from downloader import download_video

    total = len(tasks)
    done, failed = [], []
    counter = {"n": 0}
    t0 = time.monotonic()

    async with shared_sniffer(headless=headless, cookie_mode=cookie_mode) as (sn, note):
        print(f"登录态：{note}")
        if not sn.logged_in:
            print("⚠️  没检测到登录标记，小鹅通课程很可能会失败。先跑 ./vd doctor 看看。")
        print(f"并发 {jobs}，任务启动间隔 {interval}s")
        print()

        sem = asyncio.Semaphore(jobs)
        gate = _Stagger(interval)

        async def work(item):
            async with sem:
                await gate.wait()
                started = time.monotonic()
                dest = out_root / item.subdir if item.subdir else out_root
                try:
                    direct, _title, status = await sn.sniff(item.url, wait_ms)
                except Exception as e:
                    direct, status = None, f"❌ 嗅探异常: {e}"

                if not direct:
                    counter["n"] += 1
                    print(f"[{counter['n']:>3}/{total}] {BAD} {item.name}\n"
                          f"          {status}")
                    failed.append((item, status))
                    return

                try:
                    ok, path, log = await asyncio.to_thread(
                        download_video, direct, item.url, item.name, dest)
                except Exception as e:
                    ok, path, log = False, None, f"下载异常: {e}"

                counter["n"] += 1
                cost = time.monotonic() - started
                if ok and path:
                    pth = Path(path)
                    size = pth.stat().st_size
                    speed = size / cost / 1024 / 1024 if cost > 0 else 0
                    cached = "（已存在）" if "already exists" in log else ""
                    print(f"[{counter['n']:>3}/{total}] {OK} {pth.name}  "
                          f"{_human(size)}  {cost:.0f}s  {speed:.1f}MB/s {cached}")
                    done.append(pth)
                else:
                    print(f"[{counter['n']:>3}/{total}] {BAD} {item.name}\n"
                          f"          {log.strip()[:200]}")
                    failed.append((item, log.strip()[:200]))

        try:
            await asyncio.gather(*(work(t) for t in tasks))
        except asyncio.CancelledError:
            print("\n已中断。已下载的不会重复下载，重跑同一条命令即可续传。")

    elapsed = time.monotonic() - t0
    total_bytes = sum(p.stat().st_size for p in done if p.exists())
    print(f"\n{'─' * 60}")
    print(f"完成 {len(done)}/{total}，失败 {len(failed)}")
    print(f"耗时 {elapsed/60:.1f} 分钟，共 {_human(total_bytes)}"
          + (f"，平均 {total_bytes/elapsed/1024/1024:.2f} MB/s" if elapsed > 0 else ""))
    if failed:
        print(f"\n失败清单（重跑同一条命令会自动跳过已成功的）：")
        for item, why in failed:
            print(f"  {BAD} 第{item.lineno}行 {item.name}")
            print(f"       {why}")

    if frames and done:
        print()
        _extract_many(done, frames)
    return done, failed


def cmd_csv(args) -> int:
    import playlist

    try:
        items, suspicious = playlist.parse_csv(args.file)
    except (FileNotFoundError, ValueError) as e:
        print(f"{BAD} {e}")
        return 2

    if suspicious:
        print(f"以下 {len(suspicious)} 行的链接有问题，已跳过：")
        for lineno, text in suspicious[:10]:
            print(f"  第 {lineno} 行：{text}")
        print()

    if args.only:
        items = [i for i in items if i.kind == args.only]
    if args.limit:
        items = items[:args.limit]
    if not items:
        print(f"{BAD} 没有可处理的条目")
        return 2

    out_root = Path(args.out).expanduser() if args.out else Path(args.file).resolve().parent
    print(f"CSV：{args.file}")
    print(f"输出：{out_root}")
    print(f"条目：{len(items)} 条\n")

    # 预检：哪些已下载、哪些待下载
    todo, exists, bad = [], [], []
    for it in items:
        pf = detect_platform_loose(it.url)
        if not pf:
            bad.append(it)
            continue
        from utils import files_with_stem
        dest = out_root / it.subdir if it.subdir else out_root
        hit = files_with_stem(dest, _safe(it.name))
        (exists if hit else todo).append(it)

    from collections import Counter

    # CSV 内部重名会静默丢数据：目标路径一样，后一条会被当成「已下载」跳过
    keyed = Counter((i.subdir, _safe(i.name)) for i in items)
    dups = [k for k, n in keyed.items() if n > 1]
    if dups:
        print(f"\n⚠️  CSV 里有 {len(dups)} 组条目会落到同一个文件名，"
              f"同组只会下到第一条，其余被当成「已下载」跳过：")
        for subdir, stem in dups[:5]:
            lines = [str(i.lineno) for i in items if (i.subdir, _safe(i.name)) == (subdir, stem)]
            print(f"     {subdir}/{stem}  ← 第 {', '.join(lines)} 行")
        print("     请在 CSV 里把标题或序号改成不重复的，再重跑。\n")

    print(f"  待下载 {len(todo)}   已存在 {len(exists)}   无法识别 {len(bad)}")
    kinds = Counter(i.kind for i in todo if i.kind)
    if kinds:
        print(f"  类型分布：{dict(kinds)}")
    if bad:
        print(f"\n{BAD} 无法识别平台的 {len(bad)} 条：")
        for it in bad[:5]:
            print(f"     第{it.lineno}行 {it.name}")

    if args.dry_run:
        print("\n前 10 条将要生成的路径：")
        for it in todo[:10]:
            rel = f"{it.subdir}/{_safe(it.name)}.mp4" if it.subdir else f"{_safe(it.name)}.mp4"
            print(f"  {rel}")
        est = len(todo) * args.interval / 60
        print(f"\n（--dry-run：没有下载）按并发 {args.jobs}、间隔 {args.interval}s 估算，"
              f"光启动节流就要 {est:.0f} 分钟")
        return 0

    if not todo:
        print("\n全部已下载，没有新任务。")
        return 0

    try:
        _done, failed = asyncio.run(_run_concurrent(
            todo, out_root, args.jobs, args.interval,
            not args.headed, args.cookies, args.wait, args.frames))
    except KeyboardInterrupt:
        print("\n已中断。重跑同一条命令会跳过已下载的。")
        return 130
    return 0 if not failed else 1


def _safe(name: str) -> str:
    from utils import safe_filename
    return safe_filename(name)


# ---------------------------------------------------------------- batch

def cmd_batch(args) -> int:
    import playlist

    try:
        items, suspicious = playlist.parse_file(args.file)
    except FileNotFoundError as e:
        print(f"{BAD} {e}")
        return 2

    if suspicious:
        print("以下行看着像清单但没解析出来，已跳过：")
        for lineno, text in suspicious:
            print(f"  第 {lineno} 行：{text[:70]}")
        print()

    if not items:
        print(f"{BAD} 清单里没解析到任何链接。")
        print("   每行写成  - [视频名称](链接)  即可；可以用 ./vd template 生成一份模板。")
        return 2

    print(f"清单：{args.file}\n解析到 {len(items)} 条\n")

    # 先整体过一遍：平台能不能认、是否已下载。写错的清单在这一步就该发现。
    rows, bad = [], 0
    for i, it in enumerate(items, 1):
        pf = detect_platform_loose(it.url)
        code = extract_code(pf, it.url) if pf else None
        existing = find_existing_by_code(pf, code) if (pf and code) else None
        name = it.name or "（用课程自带标题）"
        if not pf:
            state, bad = f"{BAD} 不支持的平台", bad + 1
        elif not code:
            state, bad = f"{BAD} 认不出视频编码", bad + 1
        elif existing:
            state = f"{OK} 已下载"
        else:
            state = "待下载"
        print(f"  {i:>2}. {name[:34]:<34} {PLATFORM_LABELS.get(pf, '—'):<5} {state}")
        rows.append((it, pf, code, existing))

    if bad:
        print(f"\n{BAD} 有 {bad} 条无法处理，请检查清单里的链接。")
    if args.dry_run:
        print("\n（--dry-run：只检查清单，没有下载）")
        return 1 if bad else 0

    todo = [(it, pf) for (it, pf, code, existing) in rows if pf and code and not existing]
    if not todo:
        print("\n清单里的视频都已下载，没有新任务。")
        if args.frames:
            print()
            _extract_many([e for (_i, _p, _c, e) in rows if e], args.frames)
        return 0

    print(f"\n开始下载 {len(todo)} 条…\n")
    done, failed = [], []
    for i, (it, pf) in enumerate(todo, 1):
        p = _download_one(it.url, headless=not args.headed, wait_ms=args.wait,
                          cookie_mode=args.cookies, idx=i, total=len(todo),
                          name=it.name)
        (done if p else failed).append(p or f"第 {it.lineno} 行 {it.name or it.url}")

    if args.frames:
        print()
        all_files = [e for (_i, _p, _c, e) in rows if e] + done
        _extract_many(all_files, args.frames)

    print(f"\n完成：成功 {len(done)} 条，失败 {len(failed)} 条")
    for f in failed:
        print(f"  {BAD} {f}")
    return 0 if not failed else 1


def cmd_template(args) -> int:
    src = Path(__file__).resolve().parent / "playlist.example.md"
    dst = Path(args.out)
    if not src.is_file():
        print(f"{BAD} 找不到模板文件 {src}")
        return 2
    if dst.exists() and not args.force:
        print(f"{BAD} {dst} 已存在，加 --force 覆盖")
        return 2
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"{OK} 模板已生成：{dst}")
    print(f"   编辑好之后跑：./vd batch {dst} --dry-run   先检查")
    print(f"   确认没问题再跑：./vd batch {dst}")
    return 0


# ---------------------------------------------------------------- frames

def _extract_many(paths: List[Path], step: int) -> None:
    from frame_extractor import extract_frames
    raw = int(step)
    step = max(STEP_MIN, min(STEP_MAX, raw))
    if step != raw:
        print(f"注意：抽帧间隔只支持 {STEP_MIN}~{STEP_MAX} 秒，已按 {step}s 处理")
    for p in paths:
        ok, zip_path, log = extract_frames(str(p), step)
        if ok:
            frames_dir = Path(zip_path).with_suffix("")
            n = len(list(frames_dir.glob("*.jpg"))) if frames_dir.is_dir() else 0
            print(f"{OK} 抽帧 {p.name} → {n} 帧（每 {step}s）")
            print(f"     图片：{frames_dir}")
            print(f"     打包：{zip_path}")
        else:
            print(f"{BAD} 抽帧失败 {p.name}：{log}")


def cmd_frames(args) -> int:
    paths: List[Path] = []
    for pat in args.files:
        p = Path(pat)
        paths.extend([p] if p.is_file() else sorted(Path().glob(pat)))
    paths = [p for p in paths if p.is_file()]
    if not paths:
        print("没有找到视频文件")
        return 2
    _extract_many(paths, args.step)
    return 0


# ---------------------------------------------------------------- ls

def cmd_ls(args) -> int:
    total = 0
    for pf, d in PLATFORM_DIRS.items():
        if not d.is_dir():
            continue
        files = sorted([p for p in d.iterdir() if p.is_file() and not p.name.startswith(".")])
        if not files:
            continue
        print(f"{PLATFORM_LABELS[pf]}  ({d})")
        for p in files:
            print(f"  {_human(p.stat().st_size):>8}  {p.name}")
            total += 1
    print(f"\n共 {total} 个文件" if total else "还没有下载任何视频")
    return 0


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="vd", description="视频解析 / 下载 / 抽帧（抖音 · 小鹅通）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    def add_sniff_opts(p):
        p.add_argument("--headed", action="store_true", help="显示浏览器窗口（解析不出来时试试）")
        p.add_argument("--wait", type=int, default=15000, help="等直链出现的毫秒数（默认 15000）")
        p.add_argument("--cookies", default=COOKIE_SOURCE, choices=["chrome", "profile", "auto"],
                       help="登录态来源，默认 %(default)s")

    g = sub.add_parser("get", help="解析并下载")
    g.add_argument("urls", nargs="+", help="视频链接，可多条")
    g.add_argument("--frames", type=int, metavar="秒", help="下载完顺便按每 N 秒抽一帧")
    add_sniff_opts(g)
    g.set_defaults(func=cmd_get)

    d = sub.add_parser("doctor", help="环境与登录态自检")
    d.add_argument("url", nargs="?", help="顺便检查这条链接能不能识别")
    d.set_defaults(func=cmd_doctor)

    lg = sub.add_parser("login", help="手动登录（Chrome 里没登录时才需要）")
    lg.add_argument("url", help="任意一条该店铺的链接")
    lg.set_defaults(func=cmd_login)

    fr = sub.add_parser("frames", help="对已有视频抽帧")
    fr.add_argument("files", nargs="+", help="视频文件路径，支持通配符")
    fr.add_argument("--step", type=int, default=1, help="每 N 秒一帧（默认 1）")
    fr.set_defaults(func=cmd_frames)

    b = sub.add_parser("batch", help="按 Markdown 清单批量下载并按指定名称命名")
    b.add_argument("file", help="清单文件（.md）")
    b.add_argument("--dry-run", action="store_true", help="只检查清单，不下载")
    b.add_argument("--frames", type=int, metavar="秒", help="下载完顺便按每 N 秒抽一帧")
    add_sniff_opts(b)
    b.set_defaults(func=cmd_batch)

    tp = sub.add_parser("template", help="生成一份清单模板")
    tp.add_argument("out", nargs="?", default="下载清单.md", help="输出文件名")
    tp.add_argument("--force", action="store_true", help="已存在时覆盖")
    tp.set_defaults(func=cmd_template)

    c = sub.add_parser("csv", help="按 CSV 清单批量下载（支持并发与限流）")
    c.add_argument("file", help="CSV 文件")
    c.add_argument("--out", help="输出根目录，默认为 CSV 所在目录")
    c.add_argument("--jobs", type=int, default=3, help="并发数，默认 3")
    c.add_argument("--interval", type=float, default=10,
                   help="相邻任务的启动间隔秒数，默认 10（限流，别调太小）")
    c.add_argument("--limit", type=int, help="只处理前 N 条，先小批试跑用")
    c.add_argument("--only", help="只处理某个类型，如 --only 视频")
    c.add_argument("--dry-run", action="store_true", help="只检查，不下载")
    c.add_argument("--frames", type=int, metavar="秒", help="下载完顺便抽帧")
    add_sniff_opts(c)
    c.set_defaults(func=cmd_csv)

    ls = sub.add_parser("ls", help="列出已下载的视频")
    ls.set_defaults(func=cmd_ls)

    # 不写子命令时，直接把参数当链接：./vd "<链接>"
    argv = sys.argv[1:]
    if argv and argv[0] not in sub.choices and not argv[0].startswith("-"):
        argv = ["get"] + argv

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
