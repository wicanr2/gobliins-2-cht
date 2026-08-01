#!/usr/bin/env bash
# 用 CI 的 macOS patch 包，在本機注入遊戲本體，做出 full 完整版。
#
# [HARD] full 版只留本機 dist-all/，不上 GitHub —— 它含遊戲資源與 129M 的 CD 音軌。
# [HARD] 這一步只能在本機做，CI 拿不到遊戲檔（game/ 是 gitignore 的）。
# 注意：Linux 端無法 codesign 也無法啟動 .app，所以本機只能驗結構，
#       真正的驗收要在 Mac 上跑一次「修復-macOS.command」再開 .app。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:?用法: package_macos_full.sh <CI 的 patch tar.gz>}"
GAMEDIR="$ROOT/../game"
DIST="$ROOT/dist-all"; mkdir -p "$DIST"

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
tar xzf "$SRC" -C "$STAGE"
APP="$STAGE/ScummVM.app"

echo ">> 注入遊戲本體（含 CD 音軌）"
mkdir -p "$APP/Contents/Resources/game"
cp -r "$GAMEDIR"/* "$APP/Contents/Resources/game/"

# wrapper 改成優先用內嵌的 game
cat > "$APP/Contents/MacOS/scummvm" <<'WRAP'
#!/bin/bash
HERE="$(cd "$(dirname "$0")" && pwd)"
CHT="$HERE/../Resources/cht-data"
BUILTIN="$HERE/../Resources/game"
exec "$HERE/scummvm.bin" --extrapath="$CHT" --path="$BUILTIN" --auto-detect "$@"
WRAP
chmod 755 "$APP/Contents/MacOS/scummvm"

# [雷] 讀我.txt 是 CI 為 patch 版寫的，只換掉第一句會留下自相矛盾的內容：
# 「已內嵌遊戲本體」下面接著「請自備正版遊戲…本專案不散布任何遊戲資源」。
# full 版整段重寫，不要只做單行替換。
cat > "$STAGE/讀我.txt" <<'RM'
頑皮小精靈2 Gobliins 2 繁體中文化（macOS universal・完整版）
============================================================

【第一次使用請先跑「修復-macOS.command」】
這個 .app 沒有 Apple 開發者簽章，macOS 預設會擋下來。
跑一次那支腳本（處理隔離屬性 + ad-hoc 簽章）之後就能正常開啟。

這是完整版：遊戲本體與 CD 音軌都已內嵌在 ScummVM.app 裡，
跑過修復腳本後直接開啟即可，不必另外準備遊戲資料夾。

中文化的部分是 ScummVM 引擎的修改（GPLv3）與自製的中文資料。
遊戲版權屬於 Coktel Vision / M.D.O. 及其權利繼受人。

專案頁：https://github.com/wicanr2/gobliins-2-cht
RM

OUT="$DIST/Gobliins2-CHT-full-macos-universal.tar.gz"
rm -f "$OUT"
tar czf "$OUT" -C "$STAGE" ScummVM.app 修復-macOS.command 讀我.txt

# 驗收：full 版必含遊戲資源
# [雷] 不可以寫成 `tar tzf big.tar.gz | grep -q ...`：grep -q 找到就關管線，
# tar 吃到 SIGPIPE 回非零，在 set -o pipefail 下整條判失敗 —— 包明明是好的
# 卻報「沒有遊戲資源」。先把清單抓進變數再查。
LIST="$(tar tzf "$OUT")"
echo "$LIST" | grep -q "Resources/game/intro.stk"  || { echo "### full 包沒有遊戲資源 ###"; exit 1; }
echo "$LIST" | grep -q "Resources/game/track1.flac" || { echo "### full 包沒有 CD 音軌 ###"; exit 1; }
echo ">> 完成: $OUT ($(du -h "$OUT" | cut -f1))"
