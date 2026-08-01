#!/usr/bin/env bash
# 印出「引擎原始碼指紋」：engines/gob 底下所有 *.cpp / *.h 的內容雜湊。
#
# 為什麼需要這個：verify_packages.sh 原本只比對包內中文資料（.fnt/.tsv）的 md5。
# 那對「改了譯文卻忘了重打包」有效，但對「改了引擎」完全無效——資料一個 byte
# 都沒變，驗收照樣全綠，而包裡裝的是舊引擎。
#
# 2026-08-01 就真的踩到：修完中文字上緣被切的 bug 之後跑驗收，六個包全部 ✓，
# 但其中兩個 macOS 包還是修正前的 binary。指紋比對是唯一看得出來的方式。
#
# [HARD] 這支要能在 macOS runner 上跑（CI 用它算指紋），所以不可以用 GNU 專屬的東西：
#   - macOS 沒有 `sha256sum`（那是 GNU coreutils），BSD 是 `shasum -a 256`。
#   - macOS 的 `sort` 不保證支援 `-z`，`xargs -0` 的行為也不同 → 改走 while read 迴圈。
#   - 雜湊**檔案內容**而不是 `sha256sum <路徑>` 的輸出，因為本機樹與 runner 上那棵樹的
#     絕對路徑不一樣，把路徑算進去兩邊永遠對不起來。
#
# 用法: engine_fingerprint.sh <scummvm 原始碼目錄>
set -euo pipefail
SRC="${1:?用法: engine_fingerprint.sh <scummvm 原始碼目錄>}"
[ -d "$SRC/engines/gob" ] || { echo "找不到 $SRC/engines/gob" >&2; exit 1; }

if command -v sha256sum >/dev/null 2>&1; then
  HASH="sha256sum"
else
  HASH="shasum -a 256"
fi

# 依相對順序排序後逐檔雜湊內容，再把那串雜湊值雜湊一次。
find "$SRC/engines/gob" \( -name '*.cpp' -o -name '*.h' \) \
  | LC_ALL=C sort \
  | while IFS= read -r f; do $HASH < "$f"; done \
  | awk '{print $1}' \
  | $HASH \
  | cut -c1-12
