# 验收记录

记录本项目主要兼容性与版式问题的**现象 → 根因 → 修复 → 证据**，便于复核与回归。

- 验收日期：2026-09-13
- 文档源：`pingcap/docs-cn` @ `924e58f`（828 篇文档、472 张图）
- 验收环境：macOS + **CHM 阅读器-畅享版 2.7.1**（`com.shrek.chmreaderenjoy`，
  App Store 名 CHM Reader - Enjoy）
- 复核命令：`./build.sh`（无图）、`./build.sh --images`（含图）后接
  `python3 tools/verify_chm.py <chm>`

## 1. 侧栏目录"多出一长串条目"

**现象**：目录树在顶层章节之后（例：`术语表` 下面）接着一长串平铺条目，
把第二层文档名全部摊在顶级。

**根因**：CHM 里同时放了目录源 `toc.hhc` 和索引源 `index.hhk` 时，
该阅读器会把**索引条目合并进目录面板并平铺**。用带 / 不带 `index.hhk` 的两个
同内容 CHM 对比可以稳定复现。

**修复**：构建流程不再生成 `index.hhk`，`/#SYSTEM` 也不声明索引；HHP 明确关闭
二进制索引和全文搜索。`chmcmd` 会附带 Windows 原生二进制目录，但传统 `toc.hhc`
仍是唯一的用户目录来源，且工程不创建自定义 `#WINDOWS` 窗口。

**证据**：[`screenshots/02-toc-leak-repro.jpg`](screenshots/02-toc-leak-repro.jpg)（复现）
对比 [`screenshots/01-toc-clean.jpg`](screenshots/01-toc-clean.jpg)（修复后）。

**附带发现**：阅读器对**已经打开的同名 CHM 不会重新加载**——文件换成新版本后
再次 `open` 只是把旧窗口切到前面，仍显示旧目录；`⌘W` 关掉该文档或 `⌘Q`
退出阅读器后重新打开，才会读到新内容（用带版本标记的测试 CHM 实测）。

## 2. 含图片版与图片压缩档

**现象**：默认产物省略图片；原图入库则 CHM 达 123.7 MB。

**修复**：`--images` 收录图片，`--image-profile` 提供三档压缩。PNG 采用
"降采样 + 调色板量化"（比转 JPEG 更小且文字更清晰），带透明通道的图先合成白底。

| 档位 | 处理 | 图片 | 整包 CHM |
| --- | --- | --- | --- |
| `original` | 原图入库 | 111.3 MB | 123.7 MB |
| `compact`（默认） | 宽 ≤1200、PNG 256 色、JPEG q82 | 28.1 MB | 38.5 MB |
| `tiny` | 宽 ≤1000、PNG 128 色、JPEG q78 | 21.3 MB | 31.5 MB |

**证据**：[`screenshots/03-images-render.jpg`](screenshots/03-images-render.jpg)
（compact 档在阅读器中的实际观感）、
[`screenshots/04-images-cover.jpg`](screenshots/04-images-cover.jpg)（封面页）。

## 3. 打开即乱码（默认编码）

**现象**：阅读器"文本编码"为 `Default` 时中文乱码，每次都要手动切到
`Unicode (UTF-8)`。

**根因**：该阅读器与 hh.exe 默认按系统 ANSI（简体中文 = CP936/GBK）解码正文，
只写 `<meta charset="utf-8">` 不足以让它们改判；而目录源 `toc.hhc`、`#STRINGS`
本来就是 GBK，所以侧栏正常、正文乱码。

**实测对照**（同一段中文，5 个变体，均在 `Default` 编码下打开）：

| 变体 | 结果 |
| --- | --- |
| UTF-8，语言 ID 0x0804 | 乱码 |
| **UTF-8 + BOM，语言 ID 0x0804** | **正常** |
| GBK（`gb18030` 写入），语言 ID 0x0804 | 正常 |
| UTF-8，语言 ID 0x0409 | 乱码 |
| **UTF-8 + BOM，语言 ID 0x0409** | **正常** |

**修复**：正文 HTML 与 CSS 统一写入 **UTF-8 BOM**（`--utf8-bom`，默认开启），
阅读器按 BOM 判定编码，`Default` 即可正确显示；正文仍是 UTF-8，不存在字符丢失。
`tools/verify_chm.py` 会报告"正文编码：N/N 个 HTML 带 UTF-8 BOM"。

**证据**：[`screenshots/05-encoding-default-noimage.jpg`](screenshots/05-encoding-default-noimage.jpg)、
[`screenshots/06-encoding-default-images.jpg`](screenshots/06-encoding-default-images.jpg)
（两版都在 `Default` 编码下正常显示）。

## 4. LZX 压缩

**做法**：压缩模式复用 Free Pascal 的 `chmcmd`（`packages/chm` 内含
`paslzxcomp` 的 LZX 实现）。`build_chm.py --compiler auto`（`build.sh` 默认）检测到
`chmcmd` 时使用 LZX；缺少工具时自动回退到内置未压缩打包器。只有显式指定
`--compiler chmcmd` 才会在工具缺失时报错。

| 产物 | 内置打包器（未压缩） | `chmcmd`（LZX） | 降幅 |
| --- | --- | --- | --- |
| 无图版 | 9.92 MB | **2.52 MB** | -75% |
| 含图版（compact 档） | 39.43 MB | **30.73 MB** | -22% |

**目录形态不变**：`chmcmd` 用的 `docs.chmcmd.hhp` 不写索引文件、关掉全文索引，
只保留二进制目录树（Windows hh.exe 原生导航）+ `toc.hhc`。实测该组合在
macOS 阅读器侧栏仍干净（用"有索引 / 无索引"两个变体对照复现过）。

**正确性验证**：构建时用 FPC 的 `chmls extractall` 把压缩 CHM 解包，与打包前的
源文件逐个字节比对——无图版 834/834、含图版 1303/1303 全部一致；另外
`7zz t` 报 `Everything is Ok`，阅读器实测中文、图片、目录树均正常。

**证据**：[`screenshots/07-lzx-compressed.jpg`](screenshots/07-lzx-compressed.jpg)
（2.5 MB 的 LZX 压缩产物在阅读器中的效果）。

内置打包器同样遵循标准 ITSF v3 顺序：`0x60` 字节 ITSF 头、固定 `0x18` 字节
Header Section 0、ITSP 目录、正文数据。回归测试会直接核对五个 64 位偏移字段和
ITSP 签名；正文不得放进 Section 0，否则 Windows 会报 `mk:@MSITStore` 无法打开。

## 5. 正文格式与链接（站点私有写法）

**现象**：部分页面（如"部署本地测试集群"）整段排版塌掉——`>` 引用、```` ``` ````
围栏代码块、有序列表都当普通文字铺在一起；正文里还会出现 `{{{ .company }}}`
这类模板标记；不少超链接指向官网，离线点不开。

**根因**：

1. `<div label="macOS">`、`<details>` 等 HTML 容器内的内容没有加 `markdown="1"`，
   容器里的 Markdown 根本没被渲染；
2. 即使渲染，Python-Markdown 的 `fenced_code` 也不认"列表项内缩进 4 空格"的围栏，
   会退化成行内 `code`；
3. `{{{ … }}}` 是官网站点的 Hugo 变量，构建时未做替换；
4. 官网 URL（`https://docs.pingcap.com/zh/tidb/<ver>/…`）未映射回本地页面。

**修复**（`tools/build_chm.py`）：

| 项 | 做法 | 实测 |
| --- | --- | --- |
| Hugo 变量 | 读仓库 `variables.json` 替换；未知键去掉标记 | 替换 74 处，未知 0 |
| HTML 容器 | `<div label=…>` / `<details>` 加 `markdown="1"` | 容器内列表/引用正常成块 |
| 代码围栏 | 统一转 `<pre><code>`（保留缩进与语言类名） | 7115 个代码块 |
| 官网链接 → 本地 | 目标在本 CHM 内才改内链 | 改内链 56 处 |
| 未收录页面链接 | 改指官网（GitHub/Cloud/K8s 等保持外链） | 1003 处改官网，1022 处保留外链 |
| 裸媒体链接 | `[x](/media/y.png)`：打包图片时保留，否则退化为纯文本 | 488 处（无图版） |

**证据**：
[`screenshots/08-page-format-fixed.jpg`](screenshots/08-page-format-fixed.jpg)（页面整体排版）、
[`screenshots/09-code-block-fixed.jpg`](screenshots/09-code-block-fixed.jpg)（代码块/列表/引用局部）。

**回归校验**（解包后扫描 HTML 里的 `href`/`src`）：

```
无图版：本地链接 9109，外链 3635，断链 0，缺失图片引用 0
含图版：本地链接 9111，外链 3635，断链 0，缺失图片引用 0
```

## 6. 直接打开与当前版式规则

- 每篇正文映射成 `p` + 16 位十六进制哈希的根目录文件名，目录和内链使用相同映射。
- 校验器解析 `/#SYSTEM`，强制默认页为 `index.html`、传统目录为 `toc.hhc`。
- 构建目录附带 `open-chm.cmd`；下载后首次运行会移除 Windows 的 `Zone.Identifier`
  网络来源标记，再打开 CHM，处理 `mk:@MSITStore` 拒绝访问。
- 正文不生成章节开头的重复目录；`.nav`、`.toc` 和 `[TOC]` 都会被清理。
- `{{< copyable ... >}}` 等网页短代码不会进入正文。
- 页面采用 1120 px 最大宽度及紧凑边距；列表、表格、代码块和引用块缩小空白。
- 标题内的 `<code>` 继承标题字号。
- 标题锚点保留中文并匹配官网规则，重复标题使用 `-1`、`-2` 后缀；跨版本官网链接不错误地指向当前 CHM。
- 有序列表按层级明确写入 `type="1"`、`type="a"`、`type="i"`，原 `start` 保留。
- 表格自动放入 `.tablewrap` 滚动容器。

v7.5 全量验收结果：773 个主题页全部使用短 ASCII 文件名；464/464 个有序列表
带明确类型；copyable 残留、页首导航、远程显示资源、本地断链和缺失锚点均为 0；LZX 解包后
777/777 个内容文件与打包前字节一致。

## 7. 通用复核清单

```bash
./build.sh && ./build.sh --images
python3 tools/verify_chm.py dist/tidb-docs-cn/tidb-docs-cn.chm
python3 tools/verify_chm.py dist/tidb-docs-cn-images/tidb-docs-cn-images.chm
7zz t dist/tidb-docs-cn/tidb-docs-cn.chm          # Everything is Ok
chmls extractall dist/tidb-docs-cn/tidb-docs-cn.chm /tmp/c   # 压缩包解包核对
```

期望结果：目录链接 0 缺失 / 无索引与全文数据库 / HTML 全部带 UTF-8 BOM /
主题文件名全部为短 ASCII 哈希 / 模板、页首导航和远程显示依赖为 0 /
本地链接与标题锚点 0 缺失 / 有序列表全部带层级类型 / LZX 解包字节一致。
阅读器侧请**先退出或用 ⌘W 关闭旧文档**，再打开新产物。
