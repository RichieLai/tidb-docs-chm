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
    return B.finalize_html(B.render_callouts(B.md_to_html(body, code_blocks)))


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

    # 10. 官网用 CSS 按层级切换有序列表标记；CHM 同时写 type 属性，
    # 避免旧版 hh.exe 把内层 a/b/c 错显示成 1/2/3。
    md = "1. 外层一\n\n    1. 内层一\n    2. 内层二\n\n2. 外层二\n"
    html = render(md)
    ok &= check("有序列表层级", md,
                ("外层使用数字", '<ol type="1">' in html),
                ("内层使用字母", '<ol type="a">' in html),
                ("外层序号未被拆开", html.count('<ol type="1">') == 1))

    # 11. 网页专用按钮短代码和页首 TOC 标记不应进入离线正文。
    md = "# 标题\n\n[TOC]\n\n{{< copyable \"shell-regular\" >}}\n\n```bash\necho ok\n```\n"
    html = render(md)
    ok &= check("网页模板标记清理", md,
                ("copyable 已移除", "copyable" not in html),
                ("页内 TOC 已移除", 'class="toc"' not in html and "[TOC]" not in html),
                ("代码仍正常", "echo ok" in html))

    # 12. 宽表格需要滚动容器，不能撑出 CHM 正文区域。
    md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    html = render(md)
    ok &= check("表格滚动容器", md,
                ("表格被容器包裹", '<div class="tablewrap"><table>' in html))

    # 13. 所有文章用短 ASCII 文件名，本地链接也必须指向相同映射。
    stats = dict(EMPTY_STATS)
    _meta, linked, _blocks = B.clean_markdown(
        "[目标](/nested/目标.md#章节)", False, stats,
        included={"nested/目标.md"}, web_prefix="https://example.invalid/"
    )
    expected = B.html_name_for_doc("nested/目标.md") + "#章节"
    ok &= check("短 ASCII 内链", "[目标](/nested/目标.md#章节)",
                ("链接使用哈希文件名", expected in linked),
                ("文件名只含 ASCII", B.html_name_for_doc("nested/目标.md").isascii()))

    # 14. 直接打开兼容工程只保留传统目录，不能生成自定义窗口、索引或全文库。
    hhp = B.build_hhp("TiDB v7.5", "tidb.chm", ["index.html", "toc.hhc"])
    ok &= check("直接打开 HHP 结构", "正文",
                ("声明传统目录", "Contents file=toc.hhc" in hhp),
                ("默认页正确", "Default topic=index.html" in hhp),
                ("无自定义窗口", "[WINDOWS]" not in hhp),
                ("无关键词索引", "Index file=" not in hhp and "Binary Index=No" in hhp),
                ("无全文数据库", "Full-text search=No" in hhp))

    # 15. 图片版资源也使用短 ASCII 文件名，避免 CHM 内部路径兼容问题。
    stats = dict(EMPTY_STATS)
    _meta, image_md, _blocks = B.clean_markdown("![架构图](/media/架构图.png)", True, stats)
    asset = B.local_asset_name("/media/架构图.png")
    ok &= check("短 ASCII 图片资源", "正文",
                ("图片链接已映射", asset in image_md),
                ("资源名只含 ASCII", asset.isascii()))

    # 16. 标题锚点必须与官网一致并保留中文，否则 CHM 内章节链接会失效。
    md = "## Point_Get 和 Batch_Point_Get\n\n## 第 2 步：创建 Access Key Pair\n"
    html = render(md)
    ok &= check("官网兼容标题锚点", md,
                ("中英文标题锚点一致", 'id="point_get-和-batch_point_get"' in html),
                ("中文步骤标题锚点一致", 'id="第-2-步创建-access-key-pair"' in html))

    # 17. 官网重复标题使用 -1 后缀；代码标题中的 <option> 是文字，不能被当标签删掉。
    md = ("## 重复标题\n\n## 重复标题\n\n"
          "### `config [show | set <option> <value> | placement-rules]`\n")
    html = render(md)
    ok &= check("重复和代码标题锚点", md,
                ("重复标题使用官网后缀", 'id="重复标题-1"' in html),
                ("尖括号参数保留", 'id="config-show--set-option-value--placement-rules"' in html))

    # 18. 仅把同版本官网链接本地化；跨版本链接必须继续指向原版本网页。
    stats = dict(EMPTY_STATS)
    source = ("[当前](https://docs.pingcap.com/zh/tidb/v7.5/target/#章节) "
              "[旧版](https://docs.pingcap.com/zh/tidb/v7.4/target/#旧章节)")
    _meta, linked, _blocks = B.clean_markdown(
        source, False, stats, link_index={"target": "target.md"},
        included={"target.md"}, web_prefix="https://docs.pingcap.com/zh/tidb/v7.5/"
    )
    ok &= check("官网跨版本链接", "正文",
                ("当前版本改成本地链接", B.html_name_for_doc("target.md") + "#章节" in linked),
                ("旧版本保持官网链接", "https://docs.pingcap.com/zh/tidb/v7.4/target/#旧章节" in linked))

    # 19. 少数上游链接意外重复写了 fragment，只保留第一个有效锚点。
    stats = dict(EMPTY_STATS)
    _meta, linked, _blocks = B.clean_markdown(
        "[RU](/ru.md#什么是-request-unit-ru#什么是-request-unit-ru)", False, stats,
        included={"ru.md"}
    )
    ok &= check("重复锚点清理", "正文",
                ("只保留一个 fragment",
                 linked.endswith(B.html_name_for_doc("ru.md") + "#什么是-request-unit-ru)")))
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
            html = B.finalize_html(B.render_callouts(B.md_to_html(body, code_blocks)))
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
