# playlist.py
"""
下载清单（Markdown）解析。

清单是手工整理的，所以解析尽量宽容：常见的几种写法都认，
认不出来的行直接忽略而不是报错，但会把「看着像链接却没解析出来」的行报给用户。

支持的写法（可以在同一个文件里混用）：

    - [视频名称](链接)          Markdown 链接（推荐，从浏览器粘链接最省事）
    | 视频名称 | 链接 |          Markdown 表格
    视频名称 | 链接              竖线分隔
    视频名称<TAB>链接            制表符分隔
    链接                        只有链接：用课程自带标题命名
"""
from __future__ import annotations
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

URL_RE = re.compile(r"https?://\S+")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(\s*(https?://[^)\s]+)[^)]*\)")
TABLE_SEP_RE = re.compile(r"^\|?[\s:|-]+\|[\s:|-]*$")


@dataclass
class Item:
    name: str          # 用户指定的文件名；空字符串表示用课程自带标题
    url: str
    lineno: int
    subdir: str = ""   # 相对子目录（CSV 里的 阶段/小节），空表示不建子目录
    kind: str = ""     # CSV 里的「类型」列，仅用于展示和过滤


def _strip_md(text: str) -> List[Tuple[int, str]]:
    """去掉 HTML 注释和围栏代码块，返回 (行号, 行内容)。"""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out, in_fence = [], False
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        out.append((i, line))
    return out


def _clean_name(s: str) -> str:
    s = s.strip().strip("|").strip()
    s = re.sub(r"^[-*+]\s+", "", s)          # 列表符号
    s = re.sub(r"^#+\s+", "", s)             # 标题井号
    return s.strip().strip("`").strip()   # 名称里的序号保留，用户多半是故意写的


def parse_text(text: str) -> Tuple[List[Item], List[Tuple[int, str]]]:
    """返回 (清单条目, 疑似写错的行)。"""
    items: List[Item] = []
    suspicious: List[Tuple[int, str]] = []

    for lineno, line in _strip_md(text):
        if line.startswith("#") and not URL_RE.search(line):
            continue                          # 纯章节标题
        if TABLE_SEP_RE.match(line):
            continue                          # 表格分隔线
        if not URL_RE.search(line):
            continue                          # 没链接的行一律忽略

        # 1) Markdown 链接
        m = MD_LINK_RE.search(line)
        if m:
            items.append(Item(_clean_name(m.group(1)), m.group(2), lineno))
            continue

        url_m = URL_RE.search(line)
        url = url_m.group(0).rstrip(").,;、）")
        before = line[:url_m.start()]
        after = line[url_m.end():]

        # 2) 表格 / 竖线 / 制表符分隔：名称在链接左边
        name = ""
        if before.strip():
            name = _clean_name(before)
        elif after.strip("| \t"):
            # 也允许「链接 | 名称」这种反过来写的
            name = _clean_name(after)

        if not name and not url.startswith("http"):
            suspicious.append((lineno, line))
            continue
        items.append(Item(name, url, lineno))

    return items, suspicious


def parse_file(path: str | Path) -> Tuple[List[Item], List[Tuple[int, str]]]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"清单文件不存在：{p}")
    return parse_text(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- CSV

# 列名识别：CSV 列名各家写法不一，按关键词匹配，命中第一个就用
COL_URL = ("直达链接", "链接", "地址", "视频链接", "url", "link")
COL_TITLE = ("标题", "视频名称", "名称", "title", "name")
COL_SEQ = ("原序号", "序号", "编号", "no", "index")
COL_DIR = ("课程", "阶段", "小节", "章节", "分组", "分类")
COL_KIND = ("类型", "kind", "type")


def _pick(fieldnames, keys):
    """按关键词找列名，返回第一个命中的原始列名。"""
    for f in fieldnames:
        low = (f or "").strip().lower()
        if any(k.lower() in low for k in keys):
            return f
    return None


def _pick_all(fieldnames, keys):
    """找出所有命中的列，保持 CSV 里的原始顺序（用作目录层级）。"""
    out = []
    for f in fieldnames:
        low = (f or "").strip().lower()
        if any(k.lower() in low for k in keys):
            out.append(f)
    return out


def parse_csv(path: str | Path, dir_columns: Optional[List[str]] = None
              ) -> Tuple[List[Item], List[Tuple[int, str]]]:
    """
    读 CSV 清单。列名自动识别：
      链接列 → COL_URL；标题列 → COL_TITLE；序号列 → COL_SEQ
      目录层级 → COL_DIR 命中的所有列，按 CSV 原始顺序（如「课程」→「小节」）

    文件名规则：<序号> <标题>，没有序号就只用标题。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"CSV 文件不存在：{p}")

    # utf-8-sig：Excel 导出的 CSV 常带 BOM
    with p.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        url_col = _pick(fields, COL_URL)
        if not url_col:
            raise ValueError(f"CSV 里找不到链接列（表头：{fields}）")
        title_col = _pick(fields, COL_TITLE)
        seq_col = _pick(fields, COL_SEQ)
        kind_col = _pick(fields, COL_KIND)
        dir_cols = dir_columns if dir_columns is not None else _pick_all(fields, COL_DIR)

        items: List[Item] = []
        suspicious: List[Tuple[int, str]] = []
        for lineno, row in enumerate(reader, start=2):   # 表头占第 1 行
            url = (row.get(url_col) or "").strip()
            if not url:
                continue
            if not URL_RE.match(url):
                suspicious.append((lineno, f"{url[:60]}（不是合法链接）"))
                continue
            title = (row.get(title_col) or "").strip() if title_col else ""
            seq = (row.get(seq_col) or "").strip() if seq_col else ""
            name = f"{seq} {title}".strip() if seq else title
            subdir = "/".join(
                x for x in ((row.get(c) or "").strip() for c in dir_cols) if x)
            items.append(Item(name=name, url=url, lineno=lineno,
                              subdir=subdir,
                              kind=(row.get(kind_col) or "").strip() if kind_col else ""))
    return items, suspicious
