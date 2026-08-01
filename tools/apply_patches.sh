#!/usr/bin/env bash
# 把繁中化 patch 套到一棵乾淨的 ScummVM 樹上。
#
# 用法: apply_patches.sh <scummvm 原始碼目錄>
#
# [HARD] 目標樹必須已經 checkout 到 patches/UPSTREAM_COMMIT.txt 記的那個 commit。
# 這支不負責 clone —— clone 與 checkout 由呼叫端做，因為 CI 與本機的取得方式不同。
set -euo pipefail
TARGET="${1:?用法: apply_patches.sh <scummvm 原始碼目錄>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

[ -d "$TARGET" ] || { echo "找不到目錄: $TARGET"; exit 1; }

for p in "$ROOT"/patches/*.patch; do
  [ -e "$p" ] || continue
  echo ">> 套用 $(basename "$p")"
  ( cd "$TARGET" && patch -p1 --forward < "$p" )
done

# 防呆：確認繁中化的檔案真的進去了。patch 靜默沒套上是最難查的一種失敗——
# 後面照樣編得過，只是完全沒有中文。
for f in engines/gob/cht.cpp engines/gob/cht.h; do
  [ -s "$TARGET/$f" ] || { echo "### $f 不存在，patch 沒套成功 ###"; exit 2; }
done
grep -q "chtPrintTotText" "$TARGET/engines/gob/draw_v1.cpp" \
  || { echo "### draw_v1.cpp 沒有 chtPrintTotText，patch 沒套成功 ###"; exit 3; }
grep -q "cht.o" "$TARGET/engines/gob/module.mk" \
  || { echo "### module.mk 沒有 cht.o，patch 沒套成功 ###"; exit 4; }
grep -q "chtPostDraw" "$TARGET/engines/gob/video.cpp" \
  || { echo "### video.cpp 沒有 chtPostDraw，patch 沒套完整 ###"; exit 5; }

echo ">> patch 套用完成並通過檢查"
