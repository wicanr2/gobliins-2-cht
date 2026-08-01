#!/usr/bin/env bash
# 烘倚天 Big5 字型 + 產生引擎讀的 Big5 譯文表。
# [HARD] Python 一律走 docker，不污染系統環境；容器一律 --name gob2-*。
set -euo pipefail
WP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WP"
mkdir -p dist-cht
docker run --rm --name gob2-fontbuild -v "$WP":/w -w /w python:3.12-slim bash -c '
  set -e
  pip install -q --root-user-action=ignore pillow >/dev/null 2>&1 || true
  # [HARD] --lo-pad-height 16：倚天 16×15 每字只有 15 列，而引擎用
  #   loadPrefixedRaw(stream, 16) 讀。不補列的話第 N 個字會偏 2N bytes ——
  #   畫面上有些字對、有些變別的字，而且字型涵蓋率檢查照樣回報 100%。
  python3 tools/build_eten_font.py translation/translation.tsv dist-cht --prefix gob2 --lo-pad-height 16
  # UTF-8 → Big5：引擎端是逐 byte 讀的，表必須是 Big5。
  python3 - <<PY
import codecs
src="translation/translation.tsv"; dst="dist-cht/gob2_cht.tsv"
n=dropped=0
with open(src, encoding="utf-8") as f, open(dst,"wb") as o:
    for line in f:
        line=line.rstrip("\n")
        if not line or line.startswith("#") or "\t" not in line: continue
        en,zh=line.split("\t",1)
        try:
            # key 編回遊戲資料的 CP437；譯文編成 Big5
            o.write(en.encode("cp437")+b"\t"+zh.encode("big5")+b"\n"); n+=1
        except UnicodeEncodeError as e:
            # [HARD] 非 Big5 字會讓整則譯文被丟棄，不是只掉那個字。要看得見。
            print(f"  [丟棄] 非 Big5 字: {zh}  ({e})"); dropped+=1
print(f"  Big5 譯文表: {n} 則" + (f"，丟棄 {dropped} 則" if dropped else ""))
PY
'
docker run --rm --name gob2-chown -v "$WP":/w python:3.12-slim chown -R 1000:1000 /w
ls -la dist-cht/
