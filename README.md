# TiDB 中文文档离线 CHM 生成工具

把 TiDB 官方中文文档仓库 [`pingcap/docs-cn`](https://github.com/pingcap/docs-cn)
打包为可以在 Windows `hh.exe` 中直接打开的单文件 CHM。构建在 macOS 或 Linux
完成，不依赖 Microsoft HTML Help Workshop。

默认一次生成两个版本：

- **纯文字版**：去掉图片和视频，体积最小，完全离线显示正文。
- **压缩图片版**：图片随 CHM 离线打包，默认缩放并量化，兼顾清晰度和体积。

## 已固化的生成规则

这些规则来自 TiDB v7.5 CHM 的实际 Windows 打开和版式验收。

### Windows 直接打开兼容性

- 使用 Free Pascal `chmcmd` 生成 LZX 压缩 CHM。
- 正文 HTML 和 CSS 使用 UTF-8 BOM。
- `toc.hhc` 使用 GBK，适配简体中文 Windows 的 HTML Help 解析器。
- 使用一个传统 `toc.hhc` 目录；不创建自定义 `#WINDOWS` 窗口。
- 不生成关键词索引、二进制索引或全文搜索数据库。
- 默认入口固定为 `index.html`。
- 每篇正文使用 `p` 加 16 位十六进制哈希，图片使用 `m` 加哈希及原扩展名；所有
  CHM 内容文件都使用短 ASCII 文件名，避免路径、中文文件名和 URL 解析兼容问题。
- 所有目录项及正文内链同步指向哈希文件名。

### 离线与内容清理

- 所有正文、样式和选择保留的图片都打进 CHM，不依赖网络资源才能显示。
- 删除视频、iframe 和网页播放器。
- 删除 `{{< copyable "shell-regular" >}}` 等 Hugo 网页短代码。
- 删除 `[TOC]`、`.toc` 和 `.nav` 形式的文章开头重复导航；左侧 CHM 目录仍保留。
- 同版本站内链接优先改为 CHM 内链；跨版本、未收录内容和外部参考保留为普通外链。
- 标题锚点保留中文并与官网规则一致；重复标题使用 `-1`、`-2` 后缀。
- 生成独立的 `license.html`，保留来源和 CC BY-SA 3.0 说明。

### 当前正文版式

- 页面宽度和边距适配 Windows HTML Help，列表不会出现过大的左侧空白。
- 段落、代码块、引用块及表格采用紧凑间距。
- 宽表格放入可横向滚动的容器；表格单元格内进一步压缩间距。
- 标题层级清楚；标题中的代码名称继承标题字号，不会缩成正文代码大小。
- 一级有序列表显示 `1, 2, 3`，二级显示 `a, b, c`，三级显示 `i, ii, iii`；
  同时写入 CSS 和 HTML `type` 属性，以兼容旧版 CHM 渲染器。
- 原文的 `start` 起始序号保持不变。

## 环境要求

- macOS 或 Linux
- Python 3.9+
- Git
- Free Pascal 的 `chmcmd` 和 `chmls`
- 含图片版需要 Pillow，`build.sh` 会自动安装
- 可选：7-Zip，用于额外执行 CHM 完整性检查

macOS 可安装 Free Pascal：

```bash
brew install fpc
```

`chmcmd` 是默认构建所必需的工具。`--no-compress` 会启用项目自带的未压缩写入器，
只用于开发调试，不作为 Windows 直接打开兼容版的交付方式。

## 一键构建

```bash
git clone https://github.com/RichieLai/tidb-docs-chm.git
cd tidb-docs-chm

# 默认：最新版纯文字版 + 压缩图片版
./build.sh

# 指定 TiDB 版本
./build.sh release-7.5

# 只生成纯文字版
./build.sh release-7.5 --no-images

# 只生成压缩图片版
./build.sh release-7.5 --images
```

指定版本后的产物示例：

```text
dist/tidb-docs-7.5/tidb-docs-7.5.chm
dist/tidb-docs-7.5/open-chm.cmd
dist/tidb-docs-7.5-images/tidb-docs-7.5-images.chm
dist/tidb-docs-7.5-images/open-chm.cmd
```

### Windows 首次打开

Windows 会给浏览器、聊天软件或邮件下载的文件添加“网络来源”标记。HTML Help
可能因此直接提示 `无法打开文件: mk:@MSITStore:...`，即使 CHM 内容本身完整。

首次打开或重新下载后，双击与 CHM 同目录的 `open-chm.cmd`。它只执行两步：调用
PowerShell 的 `Unblock-File` 移除该 CHM 的 `Zone.Identifier`，然后打开 CHM；以后
可以直接双击 CHM。也可以右键 CHM，选择“属性”，勾选“解除锁定”后确定。

手动命令：

```powershell
Unblock-File -LiteralPath "C:\tidb-docs-7.5.chm"
```

微软说明：[下载的 CHM 无法正常显示](https://learn.microsoft.com/en-us/troubleshoot/windows-client/shell-experience/dot-chm-file-not-render-properly)
和 [Unblock-File](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/unblock-file)。

默认只保留 CHM。需要检查中间 HTML 或保留 Windows 工程时：

```bash
./build.sh release-7.5 --keep-html
./build.sh release-7.5 --keep-hhp
```

## 图片压缩

含图片版默认使用 `compact`：图片最大宽度 1200 像素、PNG 量化为 256 色、JPEG
质量 82。压缩后变大的文件会自动保留原图。

```bash
./build.sh release-7.5 --images --image-profile=compact
./build.sh release-7.5 --images --image-profile=tiny
./build.sh release-7.5 --images --image-profile=original
```

也可以单独覆盖参数：

```bash
./build.sh release-7.5 --images \
  --image-max-width=1100 \
  --image-colors=192 \
  --image-jpeg-quality=80
```

## 手动构建

```bash
python3 tools/build_chm.py \
  --repo repos/docs-cn \
  --out dist/tidb-docs-7.5 \
  --title "TiDB v7.5 中文文档" \
  --chm tidb-docs-7.5.chm \
  --ref release-7.5 --all --lang zh --compiler chmcmd
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--repo` | `pingcap/docs-cn` 本地 Git 仓库 |
| `--out` | 输出目录 |
| `--ref` | 文档分支，例如 `release-7.5` |
| `--all` | 收录 `TOC.md` 中全部章节 |
| `--sections` | 只生成指定顶层章节 |
| `--images` | 打包图片；省略时生成纯文字版 |
| `--image-profile` | `compact`、`tiny` 或 `original` |
| `--compiler` | 默认 `auto`，等同经过验证的 `chmcmd`；`builtin` 仅用于调试 |
| `--prune` | `chm` 只留 CHM；`hhp` 另留 HHP/HHC；`none` 保留全部中间文件 |
| `--limit` | 限制文章数量，用于快速试跑 |

## 校验

渲染回归测试：

```bash
make test
```

成品自检：

```bash
python3 tools/verify_chm.py dist/tidb-docs-7.5/tidb-docs-7.5.chm
```

校验器会检查：

- `toc.hhc` 目录是否存在，目录链接是否完整；
- 是否混入关键词索引或全文搜索数据库；
- `/#SYSTEM` 是否明确把启动页和目录声明为 `index.html`、`toc.hhc`；
- 所有 HTML 是否带 UTF-8 BOM；
- 所有主题页是否使用短 ASCII 哈希文件名；
- 是否残留 copyable 模板标记、页首导航或远程显示资源；
- 所有有序列表是否明确写入数字、字母或罗马数字类型；
- 所有本地 `href` 和 `src` 是否能在 CHM 中找到目标；
- 所有带章节片段的内链是否能找到对应标题锚点；
- LZX CHM 解包后的文件是否与打包前逐字节一致。

Windows 测试新版本前，请先关闭已经打开的同名 CHM，再覆盖文件并重新打开，避免
HTML Help 使用旧窗口中的缓存内容。

## 项目结构

```text
build.sh                 一键构建入口
Makefile                 build / images / test / verify 快捷命令
tools/build_chm.py       Markdown 清洗、链接转换、版式和打包流水线
tools/chmwriter.py       未压缩 CHM 写入器及只读解析器
tools/test_render.py     渲染规则及全量语料回归测试
tools/verify_chm.py      CHM 结构、离线资源、内链和版式自检
docs/verification.md    验收规则和证据
repos/docs-cn/           自动下载的官方文档仓库，不提交
dist/                    构建产物，不提交
```

## 许可

- 本项目构建工具采用 MIT License。
- TiDB 官方文档内容版权归 PingCAP 所有，采用 CC BY-SA 3.0。生成物会包含来源与许可说明。
