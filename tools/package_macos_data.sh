#!/usr/bin/env bash
# 把中文資料注入 CI 產出的 engine-only ScummVM.app，產出可交付的 macOS patch 包。
#
# 用法: package_macos_data.sh <engine-only.tar.gz> <輸出目錄>
#
# [HARD] 注入清單要含「全部」cht 檔 —— 別的專案漏過標題 .ovl，結果 macOS 版連
#        中文標題都不顯示。凡 dist-cht/ 有的都要注入，這裡用清單反查。
# [HARD] macOS 只有 bash 3.2（Apple 因 GPLv3 停在那版），不可以用 ${VAR^^}、
#        ${VAR,,}、declare -A、mapfile。本機 Linux 是 bash 5，這類語法完全測不出來，
#        而且會在整個 build 跑完之後的最後一行才爆 bad substitution。
# [HARD] 改動已簽名的 .app 會讓簽章失效 → 直接移除 _CodeSignature（「未簽」勝過
#        「壞簽」），並附「修復-macOS.command」讓玩家自己 ad-hoc 簽。
set -euo pipefail
TGZ="${1:?用法: package_macos_data.sh <engine-only.tar.gz> <輸出目錄>}"
OUT="${2:?用法: package_macos_data.sh <engine-only.tar.gz> <輸出目錄>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$OUT"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

tar xzf "$TGZ" -C "$STAGE"
APP="$STAGE/ScummVM.app"
[ -d "$APP" ] || { echo "### tar 裡沒有 ScummVM.app ###"; exit 1; }

# --- 注入中文資料 ---------------------------------------------------------
CHT="$APP/Contents/Resources/cht-data"
mkdir -p "$CHT"
# 這一軌實際會用到的檔（hi-res 字型本作用不到，故不注入）
for f in gob2_big5.fnt gob2_cht.tsv; do
  [ -s "$ROOT/dist-cht/$f" ] || { echo "### dist-cht/$f 不存在 ###"; exit 2; }
  cp "$ROOT/dist-cht/$f" "$CHT/"
done

# 引擎指紋：讓驗收看得出包裡的 binary 是哪一版引擎。中文資料沒動而只改引擎時，
# 比對 .fnt/.tsv 的 md5 一定全綠、包卻是舊的（2026-08-01 踩過，兩個 macOS 包
# 就是這樣停在修正前的版本還被判為通過）。
# [HARD] ENGINE_SRC 要指向**實際編出這顆 binary 的那棵樹**。在 CI 裡就是 runner
# 上套完 patch 的 scummvm 樹；拿本機的樹來算只是代理值，一旦兩邊不同步就會
# 印出一個「看起來對」的假指紋，比沒有還糟，所以這裡缺了就直接失敗。
: "${ENGINE_SRC:?請設 ENGINE_SRC 指向編出這顆 binary 的 scummvm 原始碼樹}"
bash "$ROOT/tools/engine_fingerprint.sh" "$ENGINE_SRC" > "$CHT/ENGINE.txt"
echo ">> 引擎指紋: $(cat "$CHT/ENGINE.txt")"

# --- 改成 wrapper：自動帶上 --extrapath ------------------------------------
# CFBundleExecutable 仍指向 scummvm，所以把原本的執行檔改名，
# 用同名 shell script 取代。
BIN="$APP/Contents/MacOS/scummvm"
mv "$BIN" "$APP/Contents/MacOS/scummvm.bin"
cat > "$BIN" <<'WRAP'
#!/bin/bash
HERE="$(cd "$(dirname "$0")" && pwd)"
CHT="$HERE/../Resources/cht-data"
# 遊戲資料夾放在 .app 旁邊、命名為 game 就會自動帶入；否則開啟動器讓你 Add Game。
BASE="$(cd "$HERE/../../.." && pwd)"
if [ -f "$BASE/game/intro.stk" ] || [ -f "$BASE/game/INTRO.STK" ]; then
  exec "$HERE/scummvm.bin" --extrapath="$CHT" --path="$BASE/game" --auto-detect "$@"
fi
exec "$HERE/scummvm.bin" --extrapath="$CHT" "$@"
WRAP
chmod 755 "$BIN"

# --- 簽章：改過就失效，移除比留著壞的好 -------------------------------------
rm -rf "$APP/Contents/_CodeSignature"

cat > "$STAGE/修復-macOS.command" <<'FIX'
#!/bin/bash
# macOS 會因為「來自網路、且未簽章」擋下這個 .app。跑一次這支就好。
cd "$(dirname "$0")"
xattr -cr ScummVM.app
codesign --force --deep --sign - ScummVM.app
echo "處理完成，可以開啟 ScummVM.app 了。"
read -n 1 -s -r -p "按任意鍵關閉…"
FIX
chmod 755 "$STAGE/修復-macOS.command"

cat > "$STAGE/讀我.txt" <<'TXT'
頑皮小精靈2 Gobliins 2 繁體中文化（macOS universal）
==================================================

【第一次使用請先跑「修復-macOS.command」】
這個 .app 沒有 Apple 開發者簽章，macOS 預設會擋下來。
跑一次那支腳本（處理隔離屬性 + ad-hoc 簽章）之後就能正常開啟。

這是 patch 版：只有中文化過的 ScummVM 引擎與中文資料，不含遊戲本體。
請自備正版遊戲，把遊戲資料夾放在 ScummVM.app 旁邊並命名為 game。

[重要] CD 音軌
這一版的音樂是 CD 紅皮書音軌。少了它 ScummVM 會彈一個阻擋式對話框，
必須先處理掉才進得去。請從你的 .cue/.bin 轉出音軌，命名為 track1.flac
放進 game 資料夾。轉檔指令見專案頁的 README。

遊戲版權屬於 Coktel Vision / M.D.O. 及其權利繼受人。
本專案不散布任何遊戲資源。
TXT

# --- 打包（[HARD] 資產檔名只能用 ASCII，包內的中文檔名不受限）---------------
OUTFILE="$OUT/Gobliins2-CHT-patch-macos-universal.tar.gz"
rm -f "$OUTFILE"
tar czf "$OUTFILE" -C "$STAGE" ScummVM.app 修復-macOS.command 讀我.txt

# --- 反查驗收：中文資料要在，遊戲資源不可以在 -------------------------------
LIST="$(tar tzf "$OUTFILE")"
for f in gob2_big5.fnt gob2_cht.tsv ENGINE.txt; do
  echo "$LIST" | grep -q "$f" || { echo "### 包內缺少 $f ###"; exit 3; }
done
# [雷] 這道防呆第一次就誤報：wrapper 會把原執行檔改名成 scummvm.bin，
# 而規則裡的 `\.bin$` 打到了它。先把我們自己放進去的檔排除，再查遊戲資源。
LEAK=$(echo "$LIST" \
  | grep -v 'Contents/MacOS/scummvm\.bin$' \
  | grep -Ei 'intro\.stk|gob\.lic|\.flac$|\.ROM$|\.bin$|\.cue$' || true)
if [ -n "$LEAK" ]; then
  echo "### patch 包混入了遊戲資源 ###"
  echo "$LEAK"
  exit 4
fi

echo ">> 完成: $OUTFILE"
ls -la "$OUTFILE"
