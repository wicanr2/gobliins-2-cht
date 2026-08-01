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


# 倚天點陣字的尺寸與引擎排版參數，必須跟 draw_v1.cpp 的 chtPrintTotText 一致，
# 否則這裡算出來的「容得下幾個字」跟實機的 [CHTFIT] 警告對不起來。
CHT_W, CHT_H, MARGIN = 16, 15, 2


def box_capacity(box_w, box_h):
    """回傳 (每行幾字, 幾行, 總字數上限)。算法照抄 chtPrintTotText。"""
    avail_w = max(box_w - 2 * MARGIN, CHT_W)
    per_line = avail_w // CHT_W
    lines = max(box_h // CHT_H, 1)
    return per_line, lines, per_line * lines


def collect_item(data, pos, end):
    """把一個文字項目收成單一字串（換行為 \\n）。

    回傳 (字串, 是否字幕, (框寬, 框高))。框大小是**硬約束**：訊息框是遊戲美術的
    一部分、改不了，而中文字高是原字型的兩倍，譯文長一點就溢出框外。
    """
    if pos + 9 > end:
        return None, False, (0, 0)

    is_subtitle = bool(data[pos + 1] & 0x80)
    dest_x = u16(data, pos) & 0x7FFF
    dest_y = u16(data, pos + 2)
    box_w = u16(data, pos + 4) - dest_x + 1
    box_h = u16(data, pos + 6) - dest_y + 1
    box = (box_w, box_h)
    pos += 8
    pos += 1                                   # backColor

    # [雷] 這裡有一段「線／框」指令,每筆 9 bytes(8 座標 + 1 cmd),
    # 直到 uint16 == 0xFFFF 為止,再跳 2。漏掉這段的話會把座標當字元讀出來,
    # 抽出一堆二進位垃圾 —— 而且垃圾也會混進譯文表,實機永遠查不到。
    # 引擎端見 draw_v2.cpp 的 `while ((_destSpriteX = READ_LE_UINT16(ptr)) != -1)`。
    guard = 0
    while pos + 2 <= end and u16(data, pos) != 0xFFFF:
        pos += 9
        guard += 1
        if guard > 256:
            return None, is_subtitle, box
    pos += 2

    out = []
    last_y = None
    guard = 0

    while pos < end:
        guard += 1
        if guard > 20000:
            return None, is_subtitle, box

        cmd = data[pos]

        if cmd == 1:                           # 結束
            break

        if cmd in (2, 5):                      # 重新定位
            if pos + 5 > end:
                return None, is_subtitle, box
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
                return None, is_subtitle, box
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
                return None, is_subtitle, box
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

    return "".join(out), is_subtitle, box


def norm(s):
    """空白正規化。建表與查表兩邊都要套，否則實機比對必 MISS。"""
    return " ".join(s.split())


def extract_file(path):
    """回傳 [(索引, 原字串, 是否字幕, (框寬, 框高))]。"""
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
        text, is_sub, box = collect_item(data, off, off + size)
        if text is None:
            continue
        if not norm(text):
            continue
        items.append((i, text, is_sub, box))
    return items


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    out_tsv = None
    if "--tsv" in sys.argv:
        out_tsv = sys.argv[sys.argv.index("--tsv") + 1]

    seen = {}          # 正規化後的 key → [原字串, 來源清單, 最小框]
    stats = []

    for ext, label in LANGS:
        files = sorted(glob.glob(os.path.join(src, f"*.{ext}"))
                       + glob.glob(os.path.join(src, f"*.{ext.upper()}")))
        n = 0
        subs = 0
        for f in files:
            base = os.path.basename(f).rsplit(".", 1)[0]
            for idx, text, is_sub, box in extract_file(f):
                n += 1
                if is_sub:
                    subs += 1
                k = norm(text)
                if k not in seen:
                    seen[k] = [text, [], box]
                seen[k][1].append(f"{base}.{ext}#{idx}")
                # 同一句可能在多個語言檔各有一個框，取**最小容量**那個當上限：
                # 只要有任一版本容不下，實機就會在那個語言溢出。
                if box_capacity(*box)[2] < box_capacity(*seen[k][2])[2]:
                    seen[k][2] = box
        stats.append((ext, label, len(files), n, subs))

    print(f"{'副檔名':<8}{'語言':<6}{'檔數':>5}{'則數':>7}{'字幕型':>8}")
    for ext, label, nf, n, subs in stats:
        print(f".{ext:<7}{label:<6}{nf:>5}{n:>7}{subs:>8}")
    total = sum(s[3] for s in stats)
    print(f"\n合計 {total} 則，正規化後不重複 {len(seen)} 則")

    if out_tsv:
        with open(out_tsv, "w", encoding="utf-8") as fh:
            for k in sorted(seen):
                orig, srcs, box = seen[k]
                per_line, lines, cap = box_capacity(*box)
                # 欄位：key（正規化後，查表用）／譯文（留空）／字數上限／來源
                # [HARD] 第三欄是**硬約束**，不是建議值。訊息框改不了大小，
                #        譯文超過就被切掉，而畫面上只看得出「字壓到框邊」。
                fh.write("%s\t\t%d字(%dx%d)\t%s\n"
                         % (k.replace("\t", " "), cap, per_line, lines,
                            ",".join(srcs[:3])))
        print(f"→ 寫出 {out_tsv}")

        caps = [box_capacity(*v[2])[2] for v in seen.values()]
        caps.sort()
        print("字數上限分布： 最小 %d／中位 %d／最大 %d；"
              "上限 <20 字的有 %d 則"
              % (caps[0], caps[len(caps) // 2], caps[-1],
                 sum(1 for c in caps if c < 20)))


if __name__ == "__main__":
    main()
