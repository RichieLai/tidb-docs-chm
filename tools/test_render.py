#!/usr/bin/env python3
"""build_chm.py 渲染回归测试。

重点盯住「代码块被 Markdown 二次解析」这一类问题：列表项、引用块里的围栏必然
被缩进（≥4 空格）或带 `> ` 前缀，若直接把 `<pre><code>` 写进正文，Markdown 会把
它当成段落文字，`# 注释` 变成标题、代码被拆成好几段。

用法：
    python3 tools/test_render.py            # 用例 + 全量文档扫描（仓库在时）
    python3 tools/test_render.py --fast     # 只跑用例
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_chm as B  # noqa: E402

EMPTY_STATS = {
    "videos": 0, "images": 0, "image_paths": [], "vars": 0, "vars_unknown": {},
    "ext_localized": 0, "ext_kept": 0, "md_external": 0, "code_blocks": 0,
    "media_links": 0,
}

# 渲染后不该出现的痕迹：标题/分隔线（代码内容被当成 Markdown 解析了）、
# 字面围栏、以及没被换回去的占位符
LEAK_RE = re.compile(r"<h[1-6][ >]|<hr\b|```|%%CHM-CODE-\d+%%")

CODE = """```toml
[server]
# 增大 gRPC 线程池
grpc-concurrency = 10

[raftstore]
# 针对写密集型负载进行优化
apply-pool-size = 4
```"""

CODE_TEXT = ("[server]\n# 增大 gRPC 线程池\ngrpc-concurrency = 10\n\n"
             "[raftstore]\n# 针对写密集型负载进行优化\napply-pool-size = 4")


def indent_lines(text: str, prefix: str) -> str:
    return "\n".join(prefix + ln if ln else ln for ln in text.split("\n"))


def render(md_text: str, keep_images: bool = False) -> str:
    stats = dict(EMPTY_STATS)
    _meta, body, code_blocks = B.clean_markdown(md_text, keep_images, stats)
    return B.unwrap_block_in_p(B.render_callouts(B.md_to_html(body, code_blocks)))


def check(name: str, md_text: str, *conditions: tuple[str, bool]) -> bool:
    """conditions 为 (说明, 是否满足)；有不满足的就打印实际渲染结果。"""
    html = render(md_text)
    failed = [label for label, ok in conditions if not ok]
    print(f"  {'OK  ' if not failed else 'FAIL'} {name}")
    for label in failed:
        print(f"        未满足：{label}")
        print("        ---- 实际渲染 ----")
        for line in html.strip().split("\n"):
            print(f"        {line}")
    return not failed


def cases() -> bool:
    print("[1/2] 渲染用例")
    ok = True

    # 1. 顶层围栏
    html = render(f"说明：\n\n{CODE}\n")
    ok &= check("顶层代码块", f"说明：\n\n{CODE}\n",
                ("代码内容原样保留", CODE_TEXT in html),
                ("无标题/围栏残留", not LEAK_RE.search(html)))

    # 2. 列表项内围栏（缩进 4 空格）—— 本次修复的主场景
    md = f"- 说明：\n\n{indent_lines(CODE, '    ')}\n"
    html = render(md)
    ok &= check("列表项内代码块", md,
                ("在 <li> 里生成 <pre><code>", "<li>" in html and html.count("<pre><code") == 1),
                ("代码没有被拆成段落", html.count("</li>") == 1 and CODE_TEXT in html),
                ("注释没变成标题", not LEAK_RE.search(html)))

    # 3. 嵌套列表（缩进 8 空格）
    md = f"- 说明：\n\n    - 二级：\n\n{indent_lines(CODE, '        ')}\n"
    html = render(md)
    ok &= check("嵌套列表内代码块", md,
                ("代码块在二级列表项里", html.count("<ul>") == 2 and html.count("<pre><code") == 1),
                ("无残留", not LEAK_RE.search(html)))

    # 4. 引用块内围栏（每行带 "> " 前缀）
    md = "> 说明：\n>\n" + indent_lines(CODE, "> ") + "\n>\n> 结束语。\n"
    html = render(md)
    ok &= check("引用块内代码块", md,
                ("代码块留在 <blockquote> 内", html.count("<blockquote>") == 1
                 and html.count("<pre><code") == 1),
                ("引用块后的正文仍在块内", "结束语。" in html.split("</blockquote>")[0]),
                ("无残留", not LEAK_RE.search(html)))

    # 5. 列表项 → 引用块 → 代码（缩进 + 引用前缀同时出现）
    md = f"- 说明：\n\n{indent_lines(CODE, '    > ')}\n"
    html = render(md)
    ok &= check("列表项内引用块里的代码块", md,
                ("渲染为 <pre><code>", html.count("<pre><code") == 1 and CODE_TEXT in html),
                ("无残留", not LEAK_RE.search(html)))

    # 6. 代码块后面还有列表项正文：不能被"挤出"列表
    md = f"- 说明：\n\n{indent_lines(CODE, '    ')}\n\n    代码块后面的说明。\n\n- 下一项\n"
    html = render(md)
    ok &= check("代码块后的列表正文", md,
                ("仍在同一个列表里", html.count("<ul>") == 1 and html.count("<li>") == 2),
                ("后续文字在 <li> 内", "代码块后面的说明。" in html.split("<li>")[1]),
                ("无残留", not LEAK_RE.search(html)))

    # 7. div 容器（<div label="…"> 交给 md_in_html 处理）
    md = f'<div label="TiKV">\n\n{CODE}\n</div>\n'
    html = render(md)
    ok &= check("div 容器内代码块", md,
                ("渲染为 <pre><code>", html.count("<pre><code") == 1),
                ("无残留", not LEAK_RE.search(html)))

    # 8. 代码里的 Markdown 语法保持原样
    md = "- 说明：\n\n    ```text\n    * 不是列表\n    | a | b |\n    <div>原样</div>\n    ```\n"
    html = render(md)
    ok &= check("代码里的 Markdown 语法不被解析", md,
                ("星号仍在代码里", "* 不是列表" in html),
                ("HTML 被转义", "&lt;div&gt;原样&lt;/div&gt;" in html),
                ("没生成表格/标题", html.count("<ul>") == 1 and "<hr" not in html))

    # 9. 未闭合的围栏保持原样，不吞掉后面的正文
    md = "- 说明：\n\n    ```toml\n    x = 1\n"
    html = render(md)
    ok &= check("未闭合围栏不吞正文", md, ("正文还在", "说明" in html))
    return ok


def corpus() -> bool:
    repo = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "repos", "docs-cn")
    if not os.path.isdir(repo):
        print("[2/2] 跳过全量扫描（未找到 repos/docs-cn，先跑一次 ./build.sh 拉源码）")
        return True
    print("[2/2] 全量文档扫描")
    pre_re = re.compile(r"<pre><code[^>]*>.*?</code></pre>", re.S)
    escaped_re = re.compile(r"</p>|</blockquote>|<h[1-6][ >]")
    broken: dict[str, int] = {}
    blocks = files = 0
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in (".git", "media")]
        for name in names:
            if not name.endswith(".md"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
            files += 1
            stats = dict(EMPTY_STATS)
            _meta, body, code_blocks = B.clean_markdown(raw, False, stats)
            html = B.unwrap_block_in_p(B.render_callouts(B.md_to_html(body, code_blocks)))
            blocks += stats["code_blocks"]
            bad = sum(1 for m in pre_re.finditer(html) if escaped_re.search(m.group(0)))
            bad += len(B.CODE_TOKEN_RE.findall(html)) + html.count("```")
            if bad:
                broken[os.path.relpath(path, repo)] = bad
    print(f"  {'OK  ' if not broken else 'FAIL'} 扫描 {files} 篇文档 / {blocks} 个代码块，"
          f"渲染异常 {sum(broken.values())} 处")
    for path, count in sorted(broken.items(), key=lambda x: -x[1])[:10]:
        print(f"        {count:3d}  {path}")
    return not broken


def main() -> int:
    ok = cases()
    if "--fast" not in sys.argv[1:]:
        ok &= corpus()
    print("\n结论：" + ("全部通过" if ok else "存在失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
