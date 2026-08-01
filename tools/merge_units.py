#!/usr/bin/env python3
"""把翻譯單元的結果攤回「每種語言各一個 key」的譯文表，順便做機械驗證。

流程：
    units/NN.txt  →（subagent 翻譯）→ out/NN.tsv  →  本工具  →  translation.tsv

單元是「一句台詞」，但引擎查表的 key 是「某個語言的那一行原文」。
所以要把 U0001 的譯文複製給它底下六種語言的六個 key —— 這正是「翻一次、六語同步」
的兌現點，也是譯名不會在語言之間漂移的原因。

同時做這幾項機械檢查（都測不到語意，但每一項都會讓實機出錯）：
    1. 缺號 / 多號 / 重號
    2. 譯文為空
    3. 超出該框的字數上限
    4. 非 Big5 字元（會讓**整則**譯文被建構腳本丟掉，實機顯示原文）
    5. 原文有 %s 而譯文沒有（引擎會少代入一個變數）
    6. 簡體字與中國大陸用語

用法:
    merge_units.py <解開的 STK 目錄>
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_gob2_texts as E
import make_units  # noqa: F401  （共用 SHOW_ORDER 等常數，順便確保兩支同源）

CN_WORDS = ["视频", "視頻", "质量", "信息", "軟件", "网络", "網絡", "屏幕", "激光",
            "默认", "默認", "鼠标", "鼠標", "内存", "內存", "牛逼", "忽悠", "靠谱",
            "靠譜", "给力", "給力", "猫腻", "貓膩"]


def cht_len(s):
    """顯示欄數：中文字（非 ASCII）算 1 欄，ASCII 也算 1 欄。

    引擎排版是按像素算的（中文 16px、ASCII 6px），這裡只是給翻譯用的粗估上限，
    刻意算得比引擎嚴——寧可提前擋下來，也不要等實機截圖才發現被切掉。
    """
    return len(s)


def is_big5(s):
    try:
        s.encode("big5")
        return True
    except UnicodeEncodeError:
        return False


def main():
    src = sys.argv[1]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tdir = os.path.join(root, "translation")

    # 重建單元（跟 make_units.py 同一套邏輯，順序也一致）
    units = {}
    for ext, _ in E.LANGS:
        for f in sorted(glob.glob(os.path.join(src, f"*.{ext}"))
                        + glob.glob(os.path.join(src, f"*.{ext.upper()}"))):
            base = os.path.basename(f).rsplit(".", 1)[0].upper()
            for idx, text, _s, box in E.extract_file(f):
                u = units.setdefault((base, idx), {"lang": {}, "box": box})
                u["lang"][ext] = text
                if E.box_capacity(*box)[2] < E.box_capacity(*u["box"])[2]:
                    u["box"] = box

    by_text, merged = {}, []
    for key in sorted(units):
        u = units[key]
        sig = E.norm(u["lang"].get("ang") or u["lang"].get("usa")
                     or u["lang"].get("dat") or "")
        if not sig:
            continue
        if sig in by_text:
            tgt = by_text[sig]
            for lang, t in u["lang"].items():
                tgt["lang"].setdefault(lang, t)
            tgt["all"].append(u["lang"])
            if E.box_capacity(*u["box"])[2] < E.box_capacity(*tgt["box"])[2]:
                tgt["box"] = u["box"]
        else:
            m = {"lang": dict(u["lang"]), "box": u["box"], "all": [u["lang"]]}
            by_text[sig] = m
            merged.append(m)

    # 讀回譯文
    zh = {}
    dup = []
    for f in sorted(glob.glob(os.path.join(tdir, "out", "*.tsv"))):
        for ln, line in enumerate(open(f, encoding="utf-8"), 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "\t" not in line:
                print(f"  ! {os.path.basename(f)}:{ln} 沒有 TAB → 略過：{line[:40]}")
                continue
            uid, val = line.split("\t", 1)
            uid = uid.strip()
            if uid in zh:
                dup.append(uid)
            zh[uid] = val.strip()

    # --- 全域收斂：統一跨批漂移的譯名 -------------------------------------
    # [HARD] 按「錯誤寫法長度遞減」套用。子字串替換是循序的，短規則排前面
    #        會先吃掉長規則的目標（SQ1 的「死亡吃角子吃角子老虎」就是這樣來的）。
    conv_path = os.path.join(tdir, "converge.tsv")
    conv = []
    if os.path.exists(conv_path):
        for line in open(conv_path, encoding="utf-8"):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "\t" in line:
                a, b = line.split("\t", 1)
                conv.append((a.strip(), b.strip()))
        conv.sort(key=lambda ab: -len(ab[0]))
    nconv = 0
    for uid in zh:
        for a, b in conv:
            if a in zh[uid]:
                zh[uid] = zh[uid].replace(a, b)
                nconv += 1
    print(f"收斂表 {len(conv)} 條規則，套用 {nconv} 次")

    problems = []
    missing = []
    for i, m in enumerate(merged, 1):
        uid = f"U{i:04d}"
        if uid not in zh or not zh[uid]:
            missing.append(uid)
            continue
        val = zh[uid]
        cap = E.box_capacity(*m["box"])[2]
        if cht_len(val) > cap:
            problems.append(f"{uid} 超長 {cht_len(val)}/{cap}：{val}")
        if not is_big5(val):
            bad = [c for c in val if not is_big5(c)]
            problems.append(f"{uid} 非 Big5 字 {''.join(bad)}：{val}")
        en = m["lang"].get("ang") or m["lang"].get("dat") or ""
        if "%s" in en and "%s" not in val:
            problems.append(f"{uid} 原文有 %s 譯文沒有：{val}")
        for w in CN_WORDS:
            if w in val:
                problems.append(f"{uid} 中國用語「{w}」：{val}")

    print(f"單元 {len(merged)}／已翻 {len(merged) - len(missing)}"
          f"／未翻 {len(missing)}／重複編號 {len(set(dup))}")
    if missing:
        print("  未翻：" + " ".join(missing[:30])
              + (" …" if len(missing) > 30 else ""))
    if problems:
        print(f"  問題 {len(problems)} 項：")
        for p in problems[:40]:
            print("   -", p)
    else:
        print("  機械檢查全過")

    # 攤平成 translation.tsv：每個語言的每一行原文都指向同一句中文
    out = {}
    for i, m in enumerate(merged, 1):
        uid = f"U{i:04d}"
        if uid not in zh or not zh[uid]:
            continue
        for langmap in m["all"]:
            for _lang, text in langmap.items():
                out[E.norm(text)] = zh[uid]

    path = os.path.join(tdir, "translation.tsv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# 由 tools/merge_units.py 從 translation/out/*.tsv 產生，"
                 "**不要直接編輯這個檔**——下次合併會蓋掉。\n")
        for k in sorted(out):
            fh.write(k.replace("\t", " ") + "\t" + out[k] + "\n")
    print(f"→ {path}（{len(out)} 個 key）")
    return 1 if (missing or problems) else 0


if __name__ == "__main__":
    sys.exit(main())
