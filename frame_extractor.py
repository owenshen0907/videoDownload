# extractor.py
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path
from typing import Tuple

from config import FRAMES, STEP_MIN, STEP_MAX

def extract_frames(video_path: str, step_sec: int) -> Tuple[bool, str, str]:
    """
    每 step_sec 秒抽一帧，输出到 frames/<video_stem>/frame_00001.jpg，并打包为 zip
    返回: (ok, zip_path_or_err, log)
    """
    try:
        step = max(STEP_MIN, min(STEP_MAX, int(step_sec)))
    except Exception:
        step = 1

    vp = Path(video_path)
    if not vp.exists():
        return False, "", f"视频不存在: {video_path}"

    out_dir = FRAMES / vp.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    out_tpl = out_dir / "frame_%05d.jpg"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(vp),
        "-vf", f"fps=1/{step}",
        str(out_tpl)
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        return False, "", proc.stdout[-1000:] if proc.stdout else "ffmpeg 执行失败"

    # 打包 zip
    zip_path = shutil.make_archive(str(out_dir), "zip", str(out_dir))
    return True, zip_path, f"抽帧完成：间隔 {step}s"