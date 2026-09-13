#!/usr/bin/env python3
"""
verify_chm.py —— 检查 CHM 侧栏目录是否"干净"。

背景：第三方阅读器（macOS 上的"CHM 阅读器-畅享版"、CHM Reader - Enjoy 等）
除目录树外，还会把 CHM 内的**索引文件**（``*.hhk`` / ``#IDXHDR``）和
**二进制目录树**（``/#TOCIDX`` 等）合并进侧栏，表现为目录树末尾多出一长串
平铺条目（例如"术语表"下面接着一篇篇文档名）。本脚本用于独立核对：

  1. 目录来源（``/toc.hhc`` 还是二进制 ``/#TOCIDX``）
  2. 是否混入索引文件（会污染侧栏）
  3. 目录树统计：顶层章节数、节点总数、最大层级
  4. 目录指向的 HTML 是否都在 CHM 内

用法：
    python3 tools/verify_chm.py dist/tidb-docs-cn/tidb-docs-cn.chm

退出码：0 = 干净；1 = 存在索引泄漏或目录缺失。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chmwriter import ChmReader  # noqa: E402

TOKEN_RE = re.compile(r"<UL>|</UL>|<LI>", re.I)
LOCAL_RE = re.compile(r'name="Local"\s+value="([^"]*)"', re.I)
INDEX_MARKERS = ("#IDXHDR", "#IVB", "#INDEX")
BINARY_TOC = ("/#TOCIDX", "/#TOPICS", "/#STRINGS", "/#URLTBL", "/#URLSTR")
UTF8_BOM = b"\xef\xbb\xbf"


def looks_like_text(data: bytes) -> bool:
    return data.startswith((UTF8_BOM, b"<", b"\n", b"\r", b" "))


def extract_chm(chm_path: str) -> str | None:
    """用 FPC 的 chmls 把（可能被 LZX 压缩的）CHM 解包到临时目录，返回目录路径。"""
    if not shutil.which("chmls"):
        return None
    tmp = tempfile.mkdtemp(prefix="verify-chm-")
    res = subprocess.run(["chmls", "extractall", chm_path, tmp], capture_output=True)
    return tmp if res.returncode == 0 else None


def tree_stats(hhc_text: str) -> tuple[int, int, int]:
    """返回 (顶层节点数, 节点总数, 最大层级 1-based)。"""
    depth = 0
    top = total = 0
    max_depth = 1
    for m in TOKEN_RE.finditer(hhc_text):
        token = m.group(0).upper()
        if token == "<UL>":
            depth += 1
        elif token == "</UL>":
            depth = max(0, depth - 1)
        else:
            total += 1
            max_depth = max(max_depth, depth)
            if depth <= 1:
                top += 1
    return top, total, max_depth


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[-2].strip(), file=sys.stderr)
        return 2
    path = sys.argv[1]
    reader = ChmReader(path)
    names = sorted(reader.files)

    # 内容是否可直接读取；LZX 压缩的 CHM 需要先解包再核对正文/目录树
    try:
        readable = looks_like_text(reader.read("/index.html"))
    except KeyError:
        readable = False
    root = None
    if not readable:
        root = extract_chm(path)

    def read_bytes(name: str) -> bytes:
        if root:
            with open(os.path.join(root, name.lstrip("/")), "rb") as fh:
                return fh.read()
        return reader.read(name)

    index_files = [n for n in names if n.lower().endswith(".hhk")]
    index_files += [n for n in names if any(n.startswith(m) for m in INDEX_MARKERS)]
    binary = [n for n in names if n in BINARY_TOC]
    hhc = [n for n in names if n.lower().endswith(".hhc")]

    print(f"CHM       : {path}")
    print(f"条目总数  : {len(names)}（含系统文件）")
    print("压缩方式  : " + ("LZX 压缩（内容已用 chmls 解包核对）" if root
                            else ("未压缩" if readable else "LZX 压缩（未找到 chmls，无法解包核对）")))
    print(f"目录源    : {', '.join(hhc) if hhc else '（无 .hhc）'}"
          + ("，另有二进制目录树" if binary else ""))
    print(f"索引文件  : {', '.join(index_files) if index_files else '无'}")

    ok = True
    if index_files:
        ok = False
        print("  [失败] 索引文件会被阅读器平铺追加到目录树末尾，必须从 CHM 中移除")
    if binary and not hhc:
        print("  [提示] 只有二进制目录树：部分第三方阅读器会把整棵树平铺成一级列表")
    if binary and hhc:
        print("  [提示] 同时存在两种目录源（toc.hhc + 二进制目录树）："
              "第三方阅读器优先用 toc.hhc，实测侧栏正常")

    if hhc and (root or readable):
        text = read_bytes(hhc[0]).decode("gbk", "replace")
        top, total, max_depth = tree_stats(text)
        print(f"目录树    : 顶层章节 {top} 个，节点 {total} 个，最大层级 {max_depth} 级")
        locals_ = [v.split("#")[0] for v in LOCAL_RE.findall(text)]
        missing = sorted({v for v in locals_ if v and "/" + v not in reader.files})
        print(f"指向页面  : {len(locals_)} 个链接，缺失文件 {len(missing)} 个")
        if missing:
            ok = False
            print("  [失败] 目录指向的页面不在 CHM 内：", missing[:5])

    html_files = [n for n in names if n.endswith(".html")]
    if root or readable:
        bom = [n for n in html_files if read_bytes(n).startswith(UTF8_BOM)]
        print(f"正文编码  : {len(bom)}/{len(html_files)} 个 HTML 带 UTF-8 BOM"
              + ("（阅读器按默认编码打开即可正确显示）"
                 if html_files and len(bom) == len(html_files) else ""))
        if html_files and len(bom) < len(html_files):
            print("  [提示] 缺 BOM 的页面会被阅读器按系统 ANSI 解码（中文乱码），"
                  "建议重新构建时保持 --utf8-bom（默认开启）")
    else:
        print("正文编码  : 跳过（压缩内容未解包）")

    print("结论      : " + ("侧栏目录干净（仅一棵目录树，无索引泄漏）" if ok
                            else "侧栏目录存在污染或缺失，见上方 [失败] 项"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
