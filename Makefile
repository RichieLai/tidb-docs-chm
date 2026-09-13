# tidb-docs-chm —— 常用动作快捷方式（等价于直接跑 ./build.sh）

PY   := .venv/bin/python
DIST := dist
CHM        := $(DIST)/tidb-docs-cn/tidb-docs-cn.chm
CHM_IMAGES := $(DIST)/tidb-docs-cn-images/tidb-docs-cn-images.chm

.PHONY: help build images verify verify-images preview clean

help:
	@echo "make build          无图版 CHM  -> $(CHM)"
	@echo "make images         含图片版 CHM（compact 档）-> $(CHM_IMAGES)"
	@echo "make verify         自检两个 CHM（目录卫生 / 编码）"
	@echo "make preview        浏览器打开无图版预览页"
	@echo "make clean          删除 dist/（仅构建产物）"

build:
	./build.sh

images:
	./build.sh --images

verify:
	$(PY) tools/verify_chm.py $(CHM)
	@[ -f "$(CHM_IMAGES)" ] && $(PY) tools/verify_chm.py $(CHM_IMAGES) || true

preview:
	open $(DIST)/tidb-docs-cn/preview.html

clean:
	rm -rf $(DIST)
