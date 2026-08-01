#!/usr/bin/env python3
"""靜態抽出 Gobliins 2 的全部文字（六種語言的側檔）。

跟一代最大的不同：**二代的文字不在 TOT 裡**（`textsOffset == 0`，實際讀 byte 確認過），
而是放在同名的語言側檔，由 `Resources::getLocTextFile` 依語言挑：

    .dat = 法（原文，則數最多）   .ang = 英/預設   .usa = 美
    .all = 德                     .esp = 西        .ita = 義

[雷] `.dat` 是**法文**，不是「資料檔」。副檔名完全看不出來，第一次掃資源很容易
     把它當無關檔案跳過——而它是最完整的那一份，要當翻譯的來源語言。

側檔格式（同 TOT 的文字表）:
    int16 itemsCount（& 0x3FFF）
    每項 int16 offset, int16 size    ← offset 相對檔案開頭

每個文字項目的讀法**嚴格照 `Draw_v2::printTotText`**（`draw_v2.cpp:190` 起）。
v2 的控制碼比 v1 多很多，照 v1 的抽法會抽出垃圾：

    ptr[0..1] destX（最高位元是「這是字幕」旗標）
    ptr[2..3] destY   ptr[4..5] right   ptr[6..7] bottom
    ptr[8]    backColor
    之後是字元流:
        1        結束
        2 / 5    重新定位（+4 bytes：offX, offY）→ Y 變了算換行
        3        字型＋顏色（+1 byte）
        4        前景色（+1 byte）
        6        可點文字（+1 byte colCmd；bit7 再吃 2、bit6 再吃 8）
        7        colCmd 歸零
        8 / 9    遮罩開關
        10       索引參照（+1 byte 個數，每個再吃 2 bytes）
        186      變數代入 → 記成 %s
        其餘     字面字元

[HARD] 這裡的收字邏輯必須跟引擎端的 `chtCollectTotText`（要加在 draw_v2.cpp）
       **逐條一致**，否則 key 對不起來、實機查表就 MISS ——
       單元測試會過、實機卻沒翻，是最難查的一種錯。

用法:
    extract_gob2_texts.py <解開的 STK 目錄> [--tsv 輸出.tsv]
"""
import glob
import os
import struct
import sys

# 語言副檔名 → 說明（順序＝抽字順序，法文優先當來源語言）
LANGS = [
    ("dat", "法"),
    ("ang", "英"),
    ("usa", "美"),
    ("all", "德"),
    ("esp", "西"),
    ("ita", "義"),
]


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def collect_item(data, pos, end):
    """把一個文字項目收成單一字串（換行為 \\n）。回傳 (字串, 是否字幕)。"""
    if pos + 9 > end:
        return None, False

    is_subtitle = bool(data[pos + 1] & 0x80)
    dest_y = u16(data, pos + 2)
    pos += 8
    pos += 1                                   # backColor

    out = []
    last_y = None
    guard = 0

    while pos < end:
        guard += 1
        if guard > 20000:
            return None, is_subtitle

        cmd = data[pos]

        if cmd == 1:                           # 結束
            break

        if cmd in (2, 5):                      # 重新定位
            if pos + 5 > end:
                return None, is_subtitle
            off_y = struct.unpack_from("<h", data, pos + 3)[0]
            y = dest_y + off_y
            if last_y is not None and y != last_y:
                out.append("\n")
            last_y = y
            pos += 5
            continue

        if cmd == 3:                           # 字型＋顏色
            pos += 2
            continue

        if cmd == 4:                           # 前景色
            pos += 2
            continue

        if cmd == 6:                           # 可點文字
            if pos + 2 > end:
                return None, is_subtitle
            col_cmd = data[pos + 1]
            pos += 2
            if col_cmd & 0x80:
                pos += 2
            if col_cmd & 0x40:
                pos += 8
            continue

        if cmd in (7, 8, 9):
            pos += 1
            continue

        if cmd == 10:                          # 索引參照
            if pos + 2 > end:
                return None, is_subtitle
            n = data[pos + 1]
            pos += 2 + n * 2
            continue

        if cmd == 186:                         # 變數代入
            out.append("%s")
            pos += 1
            continue

        # 字面字元。遊戲檔是 CP437，不是 latin-1 ——
        # 一代就是把 chr(c) 當 latin-1 用，害靜態抽的結果跟實機差了 13 則。
        out.append(bytes([cmd]).decode("cp437", errors="replace"))
        pos += 1

    return "".join(out), is_subtitle


def norm(s):
    """空白正規化。建表與查表兩邊都要套，否則實機比對必 MISS。"""
    return " ".join(s.split())


def extract_file(path):
    """回傳 [(索引, 原字串, 是否字幕)]。"""
    data = open(path, "rb").read()
    if len(data) < 2:
        return []
    count = struct.unpack_from("<h", data, 0)[0] & 0x3FFF
    items = []
    for i in range(count):
        p = 2 + i * 4
        if p + 4 > len(data):
            break
        off, size = struct.unpack_from("<hh", data, p)
        if not (0 < off < len(data) and 0 < size < 4000 and off + size <= len(data)):
            continue
        text, is_sub = collect_item(data, off, off + size)
        if text is None:
            continue
        if not norm(text):
            continue
        items.append((i, text, is_sub))
    return items


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    out_tsv = None
    if "--tsv" in sys.argv:
        out_tsv = sys.argv[sys.argv.index("--tsv") + 1]

    seen = {}          # 正規化後的 key → (原字串, 來源清單)
    stats = []

    for ext, label in LANGS:
        files = sorted(glob.glob(os.path.join(src, f"*.{ext}"))
                       + glob.glob(os.path.join(src, f"*.{ext.upper()}")))
        n = 0
        subs = 0
        for f in files:
            base = os.path.basename(f).rsplit(".", 1)[0]
            for idx, text, is_sub in extract_file(f):
                n += 1
                if is_sub:
                    subs += 1
                k = norm(text)
                if k not in seen:
                    seen[k] = (text, [])
                seen[k][1].append(f"{base}.{ext}#{idx}")
        stats.append((ext, label, len(files), n, subs))

    print(f"{'副檔名':<8}{'語言':<6}{'檔數':>5}{'則數':>7}{'字幕型':>8}")
    for ext, label, nf, n, subs in stats:
        print(f".{ext:<7}{label:<6}{nf:>5}{n:>7}{subs:>8}")
    total = sum(s[3] for s in stats)
    print(f"\n合計 {total} 則，正規化後不重複 {len(seen)} 則")

    if out_tsv:
        with open(out_tsv, "w", encoding="utf-8") as fh:
            for k in sorted(seen):
                orig, srcs = seen[k]
                # 第一欄是查表用的 key（正規化後），第二欄留空給譯文，
                # 第三欄記來源，方便回頭查是哪一關的哪一則
                fh.write(k.replace("\t", " ") + "\t\t" + ",".join(srcs[:3]) + "\n")
        print(f"→ 寫出 {out_tsv}")


if __name__ == "__main__":
    main()
