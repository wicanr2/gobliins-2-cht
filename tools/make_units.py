#!/usr/bin/env python3
"""把六種語言的字串合併成「翻譯單元」，一句只翻一次。

為什麼要這一步：`extract_gob2_texts.py` 抽出 2155 條**不重複字串**，但那 2155 條
其實只是同樣的台詞被寫成六種語言。逐條翻等於同一句話翻六次——工作量灌水兩倍以上，
而且六份譯文各自措辭，玩家切語言就看到不一樣的中文（譯名漂移的最大來源）。

合併的依據是 **TOT 檔名 + 項目索引**：`GOB01.ang#24` 與 `GOB01.dat#24` 是同一句台詞
的英法兩版。合成一個單元 → 翻一次 → 六個 key 全指向同一句中文。

[雷] 檔名不一定對得上。片頭有 `DEMOUSA`／`DEMOUSA0`／`INTRO`／`INTRO0` 四個 TOT
     裝著同一段旁白，base 不同就併不到一起。這種只能靠**內容相同的英文**再收斂一次
     （見下方第二輪合併），不然同一句旁白會翻出四份。

輸出：
    translation/units.tsv   單元表（unit_id / 上限字數 / 各語言原文）
    translation/units/NN.txt 給翻譯 subagent 的分批檔

用法:
    make_units.py <解開的 STK 目錄> [--batch-size 60]
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_gob2_texts as E

# 給翻譯看的順序：英文優先（好讀），法文是原文（英文含糊時的依據）
SHOW_ORDER = ["ang", "usa", "dat", "all", "esp", "ita"]
LANG_NAME = {"ang": "英", "usa": "美", "dat": "法(原文)",
             "all": "德", "esp": "西", "ita": "義"}


def main():
    src = sys.argv[1]
    batch_size = 60
    if "--batch-size" in sys.argv:
        batch_size = int(sys.argv[sys.argv.index("--batch-size") + 1])

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tdir = os.path.join(root, "translation")

    # (base, idx) → {lang: 原字串}，另記最小框
    units = {}
    for ext, _ in E.LANGS:
        for f in sorted(glob.glob(os.path.join(src, f"*.{ext}"))
                        + glob.glob(os.path.join(src, f"*.{ext.upper()}"))):
            base = os.path.basename(f).rsplit(".", 1)[0].upper()
            for idx, text, _is_sub, box in E.extract_file(f):
                u = units.setdefault((base, idx), {"lang": {}, "box": box})
                u["lang"][ext] = text
                if E.box_capacity(*box)[2] < E.box_capacity(*u["box"])[2]:
                    u["box"] = box

    print(f"依 TOT+索引 合併 → {len(units)} 個單元")

    # 第二輪：英文（或法文）內容完全相同的單元再併一次。
    # 片頭那種「同一段旁白裝在四個 TOT 裡」就是靠這步收斂的。
    by_text = {}
    merged = []
    for key in sorted(units):
        u = units[key]
        sig = E.norm(u["lang"].get("ang") or u["lang"].get("usa")
                     or u["lang"].get("dat") or "")
        if not sig:
            continue
        if sig in by_text:
            tgt = by_text[sig]
            tgt["keys"].append(key)
            for lang, t in u["lang"].items():
                tgt["lang"].setdefault(lang, t)
            if E.box_capacity(*u["box"])[2] < E.box_capacity(*tgt["box"])[2]:
                tgt["box"] = u["box"]
        else:
            m = {"keys": [key], "lang": dict(u["lang"]), "box": u["box"]}
            by_text[sig] = m
            merged.append(m)

    print(f"再依英文內容合併 → {len(merged)} 個單元（實際要翻的句數）")

    os.makedirs(os.path.join(tdir, "units"), exist_ok=True)
    with open(os.path.join(tdir, "units.tsv"), "w", encoding="utf-8") as fh:
        for i, m in enumerate(merged, 1):
            per, lines, cap = E.box_capacity(*m["box"])
            en = E.norm(m["lang"].get("ang") or m["lang"].get("usa") or "")
            fr = E.norm(m["lang"].get("dat") or "")
            srcs = ",".join(f"{b}#{n}" for b, n in m["keys"][:4])
            fh.write(f"U{i:04d}\t{cap}\t{per}x{lines}\t{en}\t{fr}\t{srcs}\n")

    # 分批檔：一批 batch_size 個單元
    nb = 0
    for start in range(0, len(merged), batch_size):
        nb += 1
        chunk = merged[start:start + batch_size]
        path = os.path.join(tdir, "units", f"{nb:02d}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            for j, m in enumerate(chunk, start + 1):
                per, lines, cap = E.box_capacity(*m["box"])
                fh.write(f"### U{j:04d}  上限 {cap} 字（每行 {per} 字 × {lines} 行）\n")
                for lang in SHOW_ORDER:
                    if lang in m["lang"]:
                        fh.write(f"{LANG_NAME[lang]}: {E.norm(m['lang'][lang])}\n")
                fh.write("\n")
    print(f"→ translation/units.tsv 與 translation/units/01..{nb:02d}.txt")

    caps = sorted(E.box_capacity(*m["box"])[2] for m in merged)
    print("上限字數：最小 %d／中位 %d／最大 %d；<15 字的有 %d 句"
          % (caps[0], caps[len(caps) // 2], caps[-1],
             sum(1 for c in caps if c < 15)))


if __name__ == "__main__":
    main()
