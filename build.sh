#!/usr/bin/env bash
#
# build.sh —— 一键生成 TiDB 中文离线文档（CHM）
#
# 用法:
#   ./build.sh                # 生成最新 master 版（无图，dist/tidb-docs-cn）
#   ./build.sh release-8.5    # 生成指定版本（分支名）
#   ./build.sh --images       # 生成含图片版（默认 compact 压缩档）
#   ./build.sh --images --image-profile original   # 含图片但保留原图
#   ./build.sh --keep-html    # 额外保留 HTML 版与 hhc/hhp 工程文件
#   ./build.sh --no-compress  # 不用 chmcmd 的 LZX 压缩（改用内置打包器）
#
# 产物默认只保留 CHM；HTML/工程文件是打包用中间产物，构建成功后自动清理。
# CHM 默认用 FPC 的 chmcmd 做 LZX 压缩（体积约 1/3），没装 chmcmd 时自动退回内置打包器。
# 幂等可重复执行：venv、源码仓库、产物均自动准备/更新。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO="$ROOT/repos/docs-cn"
DIST="$ROOT/dist"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"

# ---------------------------------------------------------------- 0. 参数
REF="master"
WITH_IMAGES=0
HAS_PROFILE=0
PRUNE="chm"
COMPILER="auto"
IMAGE_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --images|--keep-images)
            WITH_IMAGES=1
            ;;
        --compiler=*)
            COMPILER="${arg#--compiler=}"
            ;;
        --no-compress)
            COMPILER="builtin"
            ;;
        --compress)
            COMPILER="chmcmd"
            ;;
        --keep-html|--keep-all)
            PRUNE="none"
            ;;
        --keep-hhp)
            PRUNE="hhp"
            ;;
        --only-chm|--prune-chm)
            PRUNE="chm"
            ;;
        --image-profile=*)
            WITH_IMAGES=1
            HAS_PROFILE=1
            IMAGE_ARGS+=("$arg")
            ;;
        --image-max-width=*|--image-colors=*|--image-jpeg-quality=*)
            WITH_IMAGES=1
            IMAGE_ARGS+=("$arg")
            ;;
        --*)
            echo "未知参数：${arg}（支持 --images、--image-*、--keep-html、--keep-hhp、--no-compress）" >&2
            exit 2
            ;;
        *)
            REF="$arg"
            ;;
    esac
done

SUFFIX=""
if [ "$WITH_IMAGES" = 1 ]; then
    SUFFIX="-images"
    # 未显式指定档位时用 compact（体积约为原图的 1/3，文字仍清晰）
    if [ "$HAS_PROFILE" = 0 ]; then
        IMAGE_ARGS+=("--image-profile=compact")
    fi
fi

if [ "$REF" = "master" ]; then
    TITLE="TiDB 中文文档"
    OUT="$DIST/tidb-docs-cn${SUFFIX}"
    CHM="tidb-docs-cn${SUFFIX}.chm"
else
    TITLE="TiDB ${REF#release-} 中文文档"
    OUT="$DIST/tidb-docs-${REF#release-}${SUFFIX}"
    CHM="tidb-docs-${REF#release-}${SUFFIX}.chm"
fi
if [ "$WITH_IMAGES" = 1 ]; then
    TITLE="${TITLE}（含图片）"
fi

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- 1. Python
log "检查 Python 环境"
if [ ! -x "$PY" ]; then
    log "创建虚拟环境 $VENV"
    python3 -m venv "$VENV"
fi
if ! "$PY" -c "import markdown" 2>/dev/null; then
    log "安装依赖 markdown"
    "$VENV/bin/pip" install --quiet markdown
fi
if [ "$WITH_IMAGES" = 1 ] && ! "$PY" -c "import PIL" 2>/dev/null; then
    log "安装依赖 pillow（图片压缩用）"
    "$VENV/bin/pip" install --quiet pillow
fi

# ---------------------------------------------------------------- 2. 源仓库
if [ ! -d "$REPO/.git" ]; then
    log "克隆文档仓库（体积过滤，只取 Markdown）"
    git clone --depth 1 --filter=blob:limit=200k \
        "https://github.com/pingcap/docs-cn.git" "$REPO"
fi

log "更新源码到 $REF"
git -C "$REPO" fetch --depth 1 origin "$REF"
git -C "$REPO" checkout --force FETCH_HEAD
git -C "$REPO" clean -fdq

# ---------------------------------------------------------------- 3. 构建
log "构建 CHM: $TITLE"
mkdir -p "$OUT"
BUILD_ARGS=(
    --repo "$REPO"
    --out "$OUT"
    --title "$TITLE"
    --chm "$CHM"
    --prune "$PRUNE"
    --compiler "$COMPILER"
    --all --lang zh
)
if [ "$WITH_IMAGES" = 1 ]; then
    BUILD_ARGS+=(--images)
    if [ "${#IMAGE_ARGS[@]}" -gt 0 ]; then
        BUILD_ARGS+=("${IMAGE_ARGS[@]}")
    fi
fi
"$PY" "$ROOT/tools/build_chm.py" "${BUILD_ARGS[@]}"

# ---------------------------------------------------------------- 4. 校验
CHM_PATH="$OUT/$CHM"
if command -v 7zz >/dev/null 2>&1; then
    log "7-Zip 完整性校验"
    7zz t "$CHM_PATH" | grep -E "Everything is Ok|ERROR" || true
elif [ -x /tmp/7zz ]; then
    log "7-Zip 完整性校验"
    /tmp/7zz t "$CHM_PATH" | grep -E "Everything is Ok|ERROR" || true
else
    log "未找到 7zz，跳过独立校验（可选: brew install p7zip）"
fi

# ---------------------------------------------------------------- 5. 产物自检
log "产物自检（目录卫生 / 编码）"
"$PY" "$ROOT/tools/verify_chm.py" "$CHM_PATH" || exit 1

log "完成"
echo "  离线文档 : $CHM_PATH"
if [ "$PRUNE" = "none" ]; then
    echo "  效果预览 : $OUT/preview.html"
    echo "  官方工程 : $OUT/docs.hhp（Windows 上 hhc.exe docs.hhp 可重编标准 CHM）"
elif [ "$PRUNE" = "hhp" ]; then
    echo "  官方工程 : $OUT/docs.hhp（Windows 上 hhc.exe docs.hhp 可重编标准 CHM）"
else
    echo "  仅保留   : CHM（HTML/工程文件是打包中间产物，已清理）"
    echo "  如需 HTML 版：./build.sh --keep-html"
fi
