# 验收记录

记录本项目三个实质问题的**现象 → 根因 → 修复 → 证据**，便于复核与回归。

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

**修复**：`index.hhk` 只留在磁盘给 Windows `hhc.exe` 用，不打进 CHM；
`/#SYSTEM` 也不声明索引（`index_name=""`），并且默认不生成二进制目录树
（`--toc-mode hhc`）。构建末尾的"目录卫生检查"会在混入 `*.hhk` 或
`/#TOCIDX` 时报错退出。

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

**做法**：不自己写压缩器，直接复用 Free Pascal 的 `chmcmd`（`packages/chm`
内含 `paslzxcomp` 的 LZX 实现）。`build_chm.py --compiler auto`（`build.sh` 默认）
在检测到 `chmcmd` 时用它打包，否则退回内置打包器输出未压缩 CHM。

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

## 5. 通用复核清单

```bash
./build.sh && ./build.sh --images
python3 tools/verify_chm.py dist/tidb-docs-cn/tidb-docs-cn.chm
python3 tools/verify_chm.py dist/tidb-docs-cn-images/tidb-docs-cn-images.chm
7zz t dist/tidb-docs-cn/tidb-docs-cn.chm          # Everything is Ok
chmls extractall dist/tidb-docs-cn/tidb-docs-cn.chm /tmp/c   # 压缩包解包核对
```

期望结果：顶层章节 14 个 / 节点 949 个 / 最大层级 6 级 / 833 个链接 0 缺失 /
无索引文件 / 829 个 HTML 全部带 UTF-8 BOM / LZX 压缩 / `dist/` 下只留 CHM。
阅读器侧请**先退出或用 ⌘W 关闭旧文档**，再打开新产物。
