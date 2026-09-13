# TiDB 文档离线 CHM 生成工具

把 TiDB 官方文档（`pingcap/docs-cn`，中文）打包成单个 CHM 离线文档。
全程在 macOS / Linux 上完成，不依赖 Windows，也不依赖 Microsoft HTML Help Workshop。

- 数据源：官方文档仓库，目录结构与 docs.pingcap.com 一致
- 支持按版本分支生成（release-6.5 ~ release-8.5）
- 默认剔除图片与视频，保证体积最小；可选保留图片
- 产物已被 7-Zip 独立校验：结构合法、内容与源 HTML 字节级一致

## 1. 目录结构

```
tidb-docs-chm/
├── build.sh                 一键构建脚本（推荐入口，支持 --images 等参数）
├── Makefile                 make build / images / verify 快捷方式
├── tools/                   构建与校验工具
│   ├── build_chm.py         流水线：TOC 解析 → Markdown 清洗 → HTML → CHM
│   ├── chmwriter.py         CHM 打包器（ITSF 容器）+ 只读解析器
│   └── verify_chm.py        产物自检：目录来源、索引泄漏、树统计、编码
├── docs/                    项目文档
│   ├── verification.md      验收记录（问题现象 / 根因 / 证据）
│   └── screenshots/         验收截图
├── repos/                   [gitignore] 文档源仓库，脚本自动克隆/更新
│   └── docs-cn/             pingcap/docs-cn（中文）
├── dist/                    [gitignore] 构建产物
│   ├── tidb-docs-cn/        无图版：**只有 tidb-docs-cn.chm**
│   └── tidb-docs-cn-images/ 含图片版：只有 tidb-docs-cn-images.chm
├── .venv/                   [gitignore] 脚本自动创建的 Python 虚拟环境
└── .gitignore
```

仓库里只提交**工具与文档**；文档源仓库（400+ MB）、构建产物、虚拟环境都不入库，
克隆后跑一次 `./build.sh` 即可全部重建。

打包用的 HTML 页面、`toc.hhc`、`docs.hhp` 等都只是**中间产物**（内容已经全部
嵌进 CHM），构建成功后会自动清理，`dist/` 里只留 CHM；需要浏览器可读的 HTML 版
或 Windows 重编工程时用 `--keep-html` / `--keep-hhp`。

## 2. 环境要求

- macOS 或 Linux
- Python 3.9+（系统自带即可，脚本自动创建虚拟环境并安装 `markdown` 库）
- git（克隆文档仓库）
- 可选：`pillow`（`--images` 压缩图片用；`build.sh --images` 会自动安装。
  没装时退回 macOS 自带 `sips`，只能降采样、不能做调色板量化）
- 可选：Free Pascal（`brew install fpc`）——提供 `chmcmd`，用于 **LZX 压缩 CHM**
  （体积约为未压缩的 1/3～1/4）；没装时自动退回内置打包器输出未压缩 CHM
- 可选：7-Zip（`7zz`，用于产物独立校验；没有则自动跳过校验步骤）

## 3. 一键生成（推荐）

```bash
cd ~/Documents/tidb-docs-chm

# 最新版（master 分支）
./build.sh

# 指定版本
./build.sh release-8.5

# 含图片版（默认 compact 压缩档，约 39 MB）
./build.sh --images

# 含图片、保留原图（约 124 MB）
./build.sh --images --image-profile original

# 不用 LZX 压缩（改用内置打包器，产物未压缩）
./build.sh --no-compress

# 需要浏览器可读的 HTML 版 / Windows 重编工程（不清理中间产物）
./build.sh --keep-html
./build.sh --keep-hhp
```

脚本幂等，可反复执行。它会依次完成：

1. 创建/复用 Python 虚拟环境，安装 `markdown`（含图片版再加 `pillow`）
2. 首次运行克隆文档仓库到 `repos/docs-cn`（约 400 MB，体积过滤只取 Markdown，约 1 分钟）；
   之后每次运行增量更新到目标分支最新
3. 解析官方目录 `TOC.md`，转换全部文档
4. 用 `chmcmd`（装了 FPC 的话）做 **LZX 压缩**打包到 `dist/`，否则用内置打包器
5. 用 7-Zip 做完整性校验（如果安装了的话）
6. 跑 `tools/verify_chm.py` 自检（目录来源、索引泄漏、树统计、正文编码）
7. 清理打包中间产物（HTML/工程文件），`dist/` 里只留 CHM；打印产物路径

产物在 `dist/tidb-docs-cn/`（指定版本时为 `dist/tidb-docs-<分支名>/`；含图片版为
`dist/tidb-docs-cn-images/`、`dist/tidb-docs-<分支名>-images/`）。

清理策略（`--prune`，`build.sh` 默认 `chm`）：

| 取值 | 保留 | 适用 |
| --- | --- | --- |
| `chm`（默认） | 仅 `*.chm` | 只要离线文档 |
| `hhp` | `*.chm` + `docs.hhp` / `toc.hhc` / `index.hhk` | 需要在 Windows 上用 `hhc.exe` 重编 |
| `none` | 全部（HTML 版、预览页、工程文件） | 想在浏览器里直接看 HTML |

## 4. 手动构建

需要更细粒度控制时直接调用流水线：

```bash
# 克隆源仓库（首次）
git clone --depth 1 --filter=blob:limit=200k \
    https://github.com/pingcap/docs-cn.git repos/docs-cn

# 最新版全量
python3 tools/build_chm.py --repo repos/docs-cn --out dist/tidb-docs-cn \
    --title "TiDB 中文文档" --chm tidb-docs-cn.chm --all --lang zh

# 指定版本
python3 tools/build_chm.py --repo repos/docs-cn --out dist/tidb-docs-8.5 \
    --title "TiDB 8.5 中文文档" --chm tidb-8.5.chm --all --lang zh --ref release-8.5

# 只打部分章节（章节名即 TOC.md 顶层标题）
python3 tools/build_chm.py --repo repos/docs-cn --out dist/tidb-docs-sample \
    --sections "快速上手,部署标准集群" --lang zh

# 含图片版：compact 压缩档（宽≤1200 + PNG 256 色）
python3 tools/build_chm.py --repo repos/docs-cn --out dist/tidb-docs-cn-images \
    --title "TiDB 中文文档（含图片）" --chm tidb-docs-cn-images.chm \
    --all --lang zh --images --image-profile compact
```

## 5. build_chm.py 参数说明

| 参数 | 说明 |
| --- | --- |
| `--repo <dir>` | 文档仓库路径（必填） |
| `--out <dir>` | 输出目录（必填） |
| `--all` | 收录 TOC.md 全部章节；默认只取前 3 个顶层章节 |
| `--sections "a,b"` | 按顶层章节名过滤，逗号分隔 |
| `--ref <branch>` | 按版本分支生成，自动 `git fetch` 并切换，如 `release-8.5` |
| `--lang zh/en` | 中文（GBK 目录 + 0x0804）/ 英文（0x0409），默认 zh |
| `--images` | 打包文档引用的图片；默认省略（原位留灰色占位提示） |
| `--compiler auto/builtin/chmcmd` | 打包器：`auto`（默认）= 有 `chmcmd` 就做 **LZX 压缩**，否则用内置打包器；`builtin` = 内置（未压缩）；`chmcmd` = 强制并报错 |
| `--image-profile original/compact/tiny` | 图片压缩档位，默认 `original`（见下文"图片压缩说明"） |
| `--image-max-width N` | 覆盖档位：最大宽度（像素，0=不缩放） |
| `--image-colors N` | 覆盖档位：PNG 调色板色数（0=保持真彩） |
| `--image-jpeg-quality Q` | 覆盖档位：JPEG 质量（0=不重编码） |
| `--toc-mode hhc/binary` | 目录形态，默认 `hhc`（见下文"目录形态说明"） |
| `--limit N` | 最多收录 N 篇，试跑用 |
| `--title` / `--chm` | CHM 标题与文件名 |

可用版本分支清单：

```bash
git ls-remote --heads https://github.com/pingcap/docs-cn.git | grep release-
```

### 目录形态说明（--toc-mode）

| 形态 | CHM 内包含 | 适用 |
| --- | --- | --- |
| `hhc`（默认） | 仅 `toc.hhc` 嵌套目录源 | 第三方阅读器（含 macOS 上的 CHM 阅读器），侧栏只显示目录树本身，最干净 |
| `binary` | 二进制 `/#TOCIDX` 等 5 个文件 | Windows hh.exe 原生读取；但部分第三方阅读器会把树中全部条目平铺成一级列表 |

当前使用 macOS 第三方阅读器查看时请保持默认 `hhc`。
需要 Windows hh.exe 原生目录时加 `--toc-mode binary`，或直接用 `docs.hhp`
走官方 `hhc.exe` 重编（两种诉求同时满足且为标准产物）。

### 图片压缩说明（--image-profile）

文档里的图以 UI 截图、Grafana 面板为主（多为 PNG 真彩、单张 1~4 MB）。
CHM 自身不做压缩，图片原样入库时体积很大，因此提供三档：

| 档位 | 处理 | 图片体积 | 整包 CHM | 说明 |
| --- | --- | --- | --- | --- |
| `original` | 原图入库 | 111.3 MB | 123.7 MB | 画质无损，体积最大 |
| `compact`（推荐） | 宽 ≤1200、PNG 256 色、JPEG q82 | 28.1 MB | 38.5 MB | 面板与截图文字仍清晰，体积约为原图 1/3 |
| `tiny` | 宽 ≤1000、PNG 128 色、JPEG q78 | 21.3 MB | 31.5 MB | 更小，小字号略糊 |

（实测数据来自 pingcap/docs-cn `master`，828 篇文档、472 张图，2026-09-13）

实现要点：

- 只对 `.png/.jpg/.jpeg/.bmp/.tif/.tiff` 处理；`.gif` 动图与 `.svg` 原样保留
- PNG 走"降采样 + 调色板量化"（Pillow MedianCut），比转 JPEG 更小且文字不糊；
  带透明通道的图先合成到白底再量化
- 压完反而更大的图，保留原图（构建日志会给出压缩张数/保留张数）
- 只想降采样、不想要调色板：`--image-colors 0`

### 压缩（LZX）说明（--compiler）

CHM 支持 LZX 压缩，但格式是微软专有的，官方编码器只在 Windows 的
`hhc.exe` 里。macOS/Linux 上不自己造轮子，直接复用 **Free Pascal 自带的
`chmcmd`**（`packages/chm` 内含 `paslzxcomp` 的 LZX 实现）：

```bash
brew install fpc        # 提供 chmcmd / chmls
./build.sh              # 默认 --compiler auto：有 chmcmd 就用它压缩
```

| 产物 | 内置打包器（未压缩） | `chmcmd`（LZX） |
| --- | --- | --- |
| 无图版 | 9.9 MB | **2.5 MB** |
| 含图版（compact 档） | 39.4 MB | **30.7 MB** |

（含图版压缩收益小，因为 PNG/JPEG 本身已压缩，LZX 主要压缩 HTML 文本。）

实现细节与取舍：

- `chmcmd` 用的工程文件是另写的 `docs.chmcmd.hhp`：**不写索引文件**、关掉全文索引，
  这样第三方阅读器不会把索引条目平铺进侧栏（Windows 官方导航用二进制目录树，
  实测与 `toc.hhc` 共存时侧栏仍正常）
- `docs.hhp` 仍是给 Windows `hhc.exe` 用的完整工程（含索引 + 全文搜索），
  `--keep-hhp` 才保留
- 压缩后构建会调用 FPC 的 `chmls` 把 CHM 解包，与打包前的源文件**逐字节比对**
  （无图版 834/834、含图版 1303/1303 一致才通过）
- 没装 FPC 时自动退回内置打包器（产物未压缩，功能一致），或用 `--no-compress` 显式指定

## 6. 产物清单

默认（`--prune chm`）`dist/` 里**只有 CHM**；下表其余文件是打包中间产物／可选产物：

| 文件 | 用途 |
| --- | --- |
| `*.chm` | 离线文档本体，Windows 双击用 hh.exe 打开，左侧目录树可折叠 |
| `tidb-docs-cn.chm` / `tidb-docs-cn-images.chm` | 无图版（LZX 后约 2.5 MB）/ 含图片版（compact 档 LZX 后约 30.7 MB） |
| `docs.hhp`（`--keep-hhp` 保留） | HTML Help 工程文件。Windows 上执行 `hhc.exe docs.hhp` 可用微软官方编译器重新编译（产物为 LZX 压缩的标准 CHM，体积约 1/3） |
| `toc.hhc`（`--keep-hhp` 保留） | 官方格式的目录源文件，**已打包进 CHM**（侧栏目录的唯一来源），磁盘上这份是给 `hhc.exe` 用的 |
| `index.hhk`（`--keep-hhp` 保留） | 官方格式的索引源文件，**不打进 CHM**（原因见下），只在磁盘上给 `hhc.exe` 用 |
| `index.html` + `*.html` + `style.css`（`--keep-html` 保留） | 打包 CHM 用的正文页面，同时可当作浏览器可读的 HTML 版 |
| `preview.html`（`--keep-html` 保留） | 模拟 CHM 阅读器窗口的预览页（左目录树 + 右内容），不进 CHM，仅本地预览用 |

## 7. 中文编码约定

hh.exe / hhc.exe 是 ANSI 程序，其解析的部分文件按系统活动代码页处理
（简体中文 Windows = CP936/GBK）：

| 内容 | 编码 | 原因 |
| --- | --- | --- |
| 正文 HTML | UTF-8 + **BOM** + `<meta charset>` | 带 BOM 时 hh.exe / 第三方阅读器直接按 UTF-8 解码，打开即不乱码（`--utf8-bom` 默认开启） |
| 正文 CSS | UTF-8 + BOM | 同上 |
| `/#STRINGS`（目录树标题） | GBK | hh.exe 按 ACP 解码 |
| `/#SYSTEM`（书名、默认页） | GBK | 同上 |
| `toc.hhc` / `index.hhk` / `docs.hhp` | GBK | hhc.exe 按 ANSI 读取 |

其他语言系统的 Windows 查看 CHM 需要调整 `chmwriter.TOC_TEXT_ENCODING` 与 `--lang`。

## 7.1 侧栏目录为什么只放 `toc.hhc`

CHM 里可以同时存在三种"目录/索引"数据：目录源 `toc.hhc`、索引源 `index.hhk`、
二进制目录树（`/#TOCIDX`、`/#TOPICS`、`/#STRINGS`、`/#URLTBL`、`/#URLSTR`）。
Windows 的 hh.exe 按需取用，但**第三方阅读器会把这些来源合并**进侧栏：

| CHM 内含 | macOS 第三方阅读器（CHM 阅读器-畅享版 / CHM Reader - Enjoy）的侧栏表现 |
| --- | --- |
| 仅 `toc.hhc` | 正常：一棵可折叠目录树（本工具默认形态） |
| `toc.hhc` + `index.hhk` | 目录树末尾多出一长串**平铺条目**（例如"术语表"下面接着一篇篇文档名） |
| 仅二进制目录树 | 整棵树被**平铺成一级列表**（没有层级） |

因此本工具的默认产物只保留 `toc.hhc`：`index.hhk` 与二进制目录树都不打进 CHM
（`--toc-mode binary` 是需要 Windows hh.exe 原生目录时的显式选择）。
构建结束会打印"目录卫生检查 OK"，也可随时用 `tools/verify_chm.py` 单独核对。

## 8. 实现说明

CHM 是微软专有格式，官方编译器只能在 Windows 上运行。本工具在 macOS/Linux
上从零实现了 ITSF 容器（`chmwriter.py`），用于**不依赖 FPC** 也能出包；
若要 LZX 压缩，则改走 FPC 的 `chmcmd`（见 §5"压缩（LZX）说明"）：

- ITSF / ITSP / PMGL / PMGI 头部与目录块，section 0 带 0x18 字节 `0x01FE` 前缀头
- `/#SYSTEM` 系统文件
- 二进制目录树 `/#TOCIDX` + `/#TOPICS` + `/#STRINGS` + `/#URLTBL` + `/#URLSTR`
  （hh.exe 只认二进制目录树，仅提供 `.hhc` 时左侧导航不会显示）
- 目录树节点按深度优先顺序写入（子节点紧跟父节点），兼容依赖
  "线性顺序 + 父指针"恢复层级的第三方阅读器
- 内置打包器为未压缩存储（微软格式允许的合法形态）；LZX 压缩由 `chmcmd` 负责

二进制布局参考：chmlib（`src/chm_lib.c`）、Free Pascal `packages/chm`、
7-Zip 源码 `CPP/7zip/Archive/Chm/ChmIn.cpp`。

## 9. 验证方法

```bash
python3 tools/verify_chm.py dist/tidb-docs-cn/tidb-docs-cn.chm   # 目录卫生：无索引泄漏 + 树统计
7zz t dist/tidb-docs-cn/tidb-docs-cn.chm          # 完整性测试 -> Everything is Ok
7zz l dist/tidb-docs-cn/tidb-docs-cn.chm          # 列出全部条目
7zz x dist/tidb-docs-cn/tidb-docs-cn.chm -o/tmp/c # 提取（加 --keep-html 构建后可与源 HTML 逐字节比对）
chmls extractall dist/tidb-docs-cn/tidb-docs-cn.chm /tmp/c  # FPC 的 chmls 解包（压缩包用）
```

`verify_chm.py` 输出示例（压缩方式 / 目录源 / 索引 / 树统计 / 链接缺失 / 正文编码）：

```
压缩方式  : LZX 压缩（内容已用 chmls 解包核对）
目录源    : /toc.hhc
索引文件  : 无
目录树    : 顶层章节 14 个，节点 949 个，最大层级 6 级
指向页面  : 833 个链接，缺失文件 0 个
正文编码  : 829/829 个 HTML 带 UTF-8 BOM（阅读器按默认编码打开即可正确显示）
结论      : 侧栏目录干净（仅一棵目录树，无索引泄漏）
```

阅读器侧的行为验证（含截图与复现步骤）见 [`docs/verification.md`](docs/verification.md)：
索引泄漏导致目录树"多出一长串条目"、图片压缩档的实际观感、以及 UTF-8 BOM 解决
"默认编码乱码"的对照实测。

macOS 上安装 7-Zip：从 https://www.7-zip.org 下载 `7z*-mac.tar.xz`，解出 `7zz` 放入 PATH。

## 10. 常见问题

**CHM 打开后左侧目录是空的或平铺的？**
本工具默认 `--toc-mode hhc`，侧栏只来自 `toc.hhc`（层级与官网一致）。
若你的阅读器只认二进制目录（表现为无侧栏），加 `--toc-mode binary`；
若出现全部条目平铺（表现为顶层多出一长串文档名），改回默认 `hhc`。

**目录树最下方多出一长串条目（例如"术语表"下面接着一篇篇文档名）？**
这是阅读器把 CHM 里的**索引文件**合并进了侧栏目录。本工具默认不把
`index.hhk`（以及二进制目录树）打进 CHM，所以重新生成后不会再出现；
若手上的 CHM 仍有该现象，说明它是旧产物，重新跑一次构建即可
（详见 §7.1）。

**重新生成后，阅读器里的目录还是旧的？**
macOS 第三方阅读器（CHM 阅读器-畅享版 / CHM Reader - Enjoy）对**已经打开的
同一个 CHM 文件不会重新加载**：文件换成新版本后，`open` 只是把旧窗口切到前台，
仍显示旧目录（实测：文件换成新版本后重新 `open` 仍是旧树；`⌘W` 关掉该文档窗口
或 `⌘Q` 退出阅读器后重新打开，则读到新树）。可用 `tools/verify_chm.py`
确认文件本身已经干净，再按上述方式重新打开。

**hh.exe 打开报错或内容异常？**
macOS 上无法直接验证 hh.exe 行为。用 `docs.hhp` 在 Windows 上
`hhc.exe docs.hhp` 重编一次即可得到微软官方标准 CHM，作为兜底。

**CHM 压缩是怎么做的？体积能到多少？**
直接复用 Free Pascal 自带的 `chmcmd`（内含 LZX 实现），不自己写压缩器：
`brew install fpc` 后 `./build.sh` 会自动用它。无图版 9.9 MB → **2.5 MB**，
含图版（compact 档）39.4 MB → **30.7 MB**。没装 FPC 时自动退回内置打包器
（未压缩，功能一致），也可用 `--no-compress` 显式指定。详见 §5"压缩（LZX）说明"。

**生成的文档里有视频吗？**
没有。构建时删除全部 `<iframe>`/`<video>`/YouTube、Bilibili 嵌入及其引导句；
图片默认也省略（`--images` 可保留）。

**含图片版太大，能再小些吗？**
可以，`--image-profile` 提供三档（原图 / compact / tiny，实测对比见 §5
"图片压缩说明"）。默认 compact 已把 111 MB 图片压到 28 MB（整包 39 MB，
约为原图版的 1/3）；`--image-profile tiny` 整包约 31 MB。
更细的控制用 `--image-max-width`（缩放宽度）、`--image-colors`（调色板色数）、
`--image-jpeg-quality`（JPEG 质量）；`--image-colors 0 --image-max-width 1600`
则是"只降采样、不动颜色"。含图版的体积主要由图片决定（LZX 对已压缩的
PNG/JPEG 收益很小，主要压缩 HTML 文本）。

**为什么 `dist/` 下只有 CHM，HTML 是中间产物吗？**

是。`build_chm.py` 的工作方式是"先把 Markdown 转成 HTML，再把这些 HTML
连同图片、目录源一起塞进 CHM"，所以 HTML 页面（833 个）、图片、`toc.hhc`、
`docs.hhp` 都只是**打包输入**；CHM 是完全自包含的，删掉它们不影响阅读。
构建成功后 `build.sh` 会自动清理这些中间产物（`--prune chm`，默认），
`dist/` 里只留 CHM。想保留浏览器可读的 HTML 版用 `--keep-html`，
想保留 Windows 重编工程用 `--keep-hhp`。

**用 `--keep-html` 后，HTML 版在浏览器里看不到图？**
CHM 内图片用的是 `/media/...` 绝对路径，`file://` 直接打开 HTML 取不到；
要看 HTML 版就起个本地服务：`python3 -m http.server 8000 -d dist/tidb-docs-cn-images`
然后访问 `http://localhost:8000/`，或者直接看 CHM。

**打开 CHM 中文是乱码，每次都要手动把"文本编码"改成 Unicode (UTF-8)？**

旧产物会这样：正文是 UTF-8，而 hh.exe / 第三方阅读器默认按系统 ANSI
（简体中文 = CP936/GBK）解码，只靠 `<meta charset>` 声明不足以让它们改判。
现在构建时会给每个正文 HTML 与 CSS 写上 **UTF-8 BOM**，阅读器据此直接按 UTF-8
解码，`文本编码` 保持默认（Default）就能正常显示；`--no-utf8-bom` 可关闭该行为。

目录树 `toc.hhc`、`/#STRINGS`、`/#SYSTEM` 仍是 GBK（hh.exe 按 ANSI 读），
两者互不冲突；`tools/verify_chm.py` 会报告"正文编码：N/N 个 HTML 带 UTF-8 BOM"。

**页内链接跳转正常吗？**
站内 `.md` 链接已重写为 `.html` 相对路径；指向 TiDB Cloud、Kubernetes
文档库等站外地址的链接保持原样（打开浏览器）。

**想生成英文版？**
`--repo` 指向 `pingcap/docs`（英文仓库）并加 `--lang en`，流程完全相同。

## 11. 已知限制

- LZX 压缩依赖第三方 `chmcmd`（FPC）；未安装时退回内置打包器，产物未压缩
- hh.exe 实际渲染效果无法在 macOS 上验证，兜底方案同上
- 站外链接不做转换
- 搜索索引未生成（我们用 `chmcmd` 时关掉了全文索引以保持侧栏干净）；
  需要搜索索引可用 `--keep-hhp` 后在 Windows 端 `hhc.exe` 重编
