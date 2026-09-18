#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compile_cards.py — 图书馆目录「编译层」v2（参考 Agentic-RAG P3-3 编译层设计）

把原始导出数据编译为规范化书卡数据集 cards.jsonl，并为图谱/簇层预备结构：

  v1 → v2 变更：
    1. 读取 catalog_full.csv，为每本书附分类号 cn / 大类 cls / 二级 cls2（中图法）
       —— 支持标准分类号 / 复分号（B-53）/ 馆藏代码（CTC:B、NKWK、ER 等）；
          外文小说区作者排架码（ZOL/AUS2 等）不视为分类号
    2. 顺带产出书架层 shelves.json（含每架 top 学科）与学科目录 subjects.json
    3. 输出目录参数化（v2 构建期默认 ~/go/lib-catalog-data-v2）

  输入:  <src>/books.csv               （188,512 行；行级修复 year 引号瑕疵，防御性保留）
         <src>/catalog_full.csv        （221,767 行；分类号解析来源）
         <src>/shelf_index.csv         （书架索引）
         <src>/涵泳特藏_*.jsonl ×3     （特藏清单补充）
  输出:  <out>/cards.jsonl             （每行一张卡）
         <out>/shelves.json           （书架层）
         <out>/subjects.json          （学科目录：标准学科组 + 馆藏代码组）
         <out>/compile_report.json

书卡字段:
  mms/title/creator/publisher/year/language/type/hc/loc/src
  cn:  分类号（如 "A121" / "TP311.13" / "B-53" / "CTC:B"；无则空串）
  cls: 大类字母（如 "A" / "TP" / "CTC"；无则空串）
  cls2: 字母+首位数字（如 "A1" / "TP3"；复分/代码形式为字母本身）
  src: "main" = 主数据集；"hy" = 仅见于涵泳特藏清单（位置未详）

用法:
  python3 compile_cards.py [--src DIR] [--out DIR]
    src 默认: /mnt/c/Users/汪子恒/Desktop/南科大图书馆藏书目录
    out 默认: ~/go/lib-catalog-data
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

NCOL_BOOKS = 9
HEADER_BOOKS = ["mms", "title", "creator", "publisher", "year", "language", "type",
                "holdings_count", "locations"]
NCOL_CAT = 13

HY_FILES = ["涵泳特藏_直取.jsonl", "涵泳特藏_穷举补全.jsonl", "涵泳特藏_穷举补全2.jsonl"]

# 中图法大类名称（22 大类 + T 类二级学科）
CLC_NAMES = {
    "A": "马克思主义、列宁主义、毛泽东思想、邓小平理论",
    "B": "哲学、宗教", "C": "社会科学总论", "D": "政治、法律", "E": "军事",
    "F": "经济", "G": "文化、科学、教育、体育", "H": "语言、文字", "I": "文学",
    "J": "艺术", "K": "历史、地理", "N": "自然科学总论", "O": "数理科学和化学",
    "P": "天文学、地球科学", "Q": "生物科学", "R": "医药、卫生",
    "S": "农业科学", "T": "工业技术", "U": "交通运输", "V": "航空、航天",
    "X": "环境科学、安全科学", "Z": "综合性图书",
    "TB": "一般工业技术", "TD": "矿业工程", "TE": "石油、天然气工业",
    "TF": "冶金工业", "TG": "金属学与金属工艺", "TH": "机械、仪表工业",
    "TJ": "武器工业", "TK": "能源与动力工程", "TL": "原子能技术",
    "TM": "电工技术", "TN": "无线电电子学、电信技术", "TP": "自动化技术、计算机技术",
    "TQ": "化学工业", "TR": "摄影技术", "TS": "轻工业、手工业", "TT": "手工业",
    "TU": "建筑科学", "TV": "水利工程",
}

# 馆藏区代码（非中图法；出现于馆藏位置数据）
COLLECTION_CODES = {"ER", "OC", "VI", "CTC", "MCC", "NKWK", "WGS", "PLY"}

# 中图法 T 类标准二级学科（用于标准/馆藏代码分组）
T_SUBCLASSES = {"TB", "TD", "TE", "TF", "TG", "TH", "TJ", "TK", "TL", "TM",
                "TN", "TP", "TQ", "TR", "TS", "TT", "TU", "TV"}

CN_RE = re.compile(r"^([A-Za-z]+)(.*)$")


def fix_row(row, ncol):
    """修复未转义逗号造成的列数偏移（year 字段回归）。返回修复后行或 None。"""
    if len(row) == ncol:
        return row
    if len(row) > ncol:
        k = len(row) - ncol
        return row[:4] + [",".join(row[4:5 + k])] + row[5 + k:]
    return None


def classify_cn(call_number: str):
    """从完整索书号解析 (cn, cls, cls2)。支持：
       - 标准中图法（A121 / TP311.13 / I247.57）
       - 复分号（B-53 / TU-092.2 / Q-332）
       - 馆藏代码（CTC:B / MCC:B / NKWK / ER / OC / VI）
       外文小说区作者排架码（ZOL 第6架 / AUS2 …）解析为空。
    """
    s = (call_number or "").strip()
    if not s:
        return "", "", ""
    first = re.split(r"[\s/]", s, maxsplit=1)[0]
    if not first:
        return "", "", ""
    # 0) 代码:子类 形式（CTC:B /164、MCC:B/3）
    m = re.match(r"^([A-Za-z]{2,8}):([A-Za-z]+)$", first)
    if m:
        code, sub = m.group(1).upper(), m.group(2).upper()
        return f"{code}:{sub}", code, sub
    # 1) 字母段 + 剩余段
    m = CN_RE.match(first)
    letters, rest = m.group(1).upper(), m.group(2)
    rest_ok = (bool(re.fullmatch(r"[0-9][0-9.]*(?:-[0-9][0-9.]*)*|-[0-9][0-9.]*", rest))
               if rest else False)
    if len(letters) == 1:
        if rest == "":
            return letters, letters, letters                  # 单字母大类
        if rest_ok:
            if rest.startswith("-"):
                return letters + rest, letters, letters       # 复分（B-53）
            d1 = next(c for c in rest if c.isdigit())
            return letters + rest, letters, letters + d1
        return "", "", ""
    if len(letters) == 2:
        if rest_ok:
            if rest.startswith("-"):
                return letters + rest, letters, letters
            d1 = next(c for c in rest if c.isdigit())
            return letters + rest, letters, letters + d1
        if rest == "" and letters in COLLECTION_CODES:
            return letters, letters, letters                  # 馆藏代码（ER/OC/VI）
        return "", "", ""
    # 3+ 字母：仅白名单馆藏代码（NKWK）保留；其余（作者排架码）为空
    if letters in COLLECTION_CODES:
        return letters, letters, letters
    return "", "", ""


def is_std_cls(code: str) -> bool:
    """标准中图法学科（单字母大类 或 T 类二级）。"""
    return len(code) == 1 or code in T_SUBCLASSES


def main():
    ap = argparse.ArgumentParser(description="图书馆目录编译层 v2")
    ap.add_argument("--src", default="/mnt/c/Users/汪子恒/Desktop/南科大图书馆藏书目录",
                    help="原始数据目录（含 books.csv / catalog_full.csv / shelf_index.csv / 涵泳特藏_*.jsonl）")
    ap.add_argument("--out", default=os.path.expanduser("~/go/lib-catalog-data"),
                    help="输出数据目录")
    args = ap.parse_args()

    t0 = time.time()
    src = args.src
    src_books = os.path.join(src, "books.csv")
    if not os.path.exists(src_books):
        sys.exit(f"[compile] 找不到 {src_books}")

    # ---- 1) books.csv → cards（分类号稍后回填） ----
    cards = []
    fixed = 0
    bad_rows = []
    hc_bad = 0
    with open(src_books, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        header = next(rd)
        if [h.strip() for h in header][:NCOL_BOOKS] != HEADER_BOOKS:
            sys.exit(f"[compile] books.csv 表头不符: {header}")
        for ln, row in enumerate(rd, start=2):
            if len(row) != NCOL_BOOKS:
                row2 = fix_row(row, NCOL_BOOKS)
                if row2 is None:
                    bad_rows.append(ln)
                    continue
                row = row2
                fixed += 1
            try:
                hc = int(row[7])
            except ValueError:
                hc = 0
                hc_bad += 1
            cards.append({
                "mms": row[0], "title": row[1], "creator": row[2],
                "publisher": row[3], "year": row[4], "language": row[5],
                "type": row[6], "hc": hc, "loc": row[8], "src": "main",
                "cn": "", "cls": "", "cls2": "",
            })
    if bad_rows:
        sys.exit(f"[compile] {len(bad_rows)} 行无法修复，中止（行号样例 {bad_rows[:5]}）")
    n_main = len(cards)
    print(f"[compile] books.csv → {n_main} 卡（修复 {fixed} 行；hc 异常 {hc_bad}）", flush=True)

    # ---- 2) catalog_full.csv → mms→分类号 映射 + 书架聚合 ----
    mms_pos = {c["mms"]: i for i, c in enumerate(cards)}
    cn_by_mms = {}
    shelf_cls = {}
    n_cat = 0
    cat_fixed = 0
    cn_hit = 0
    cat_missing = 0
    with open(os.path.join(src, "catalog_full.csv"), encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        next(rd)
        for row in rd:
            n_cat += 1
            if len(row) != NCOL_CAT:
                row2 = fix_row(row, NCOL_CAT)
                if row2 is None:
                    continue
                row = row2
                cat_fixed += 1
            m = row[0]
            cn, cls, cls2 = classify_cn(row[10])
            lib, sub, shelf = row[7], row[9], row[11]
            key = (lib, sub, shelf)
            if cls:
                shelf_cls.setdefault(key, Counter())[cls] += 1
            if m in mms_pos:
                if cls:
                    cn_hit += 1
                if m not in cn_by_mms and cn:
                    cn_by_mms[m] = (cn, cls, cls2)
            else:
                cat_missing += 1
    for m, i in mms_pos.items():
        t = cn_by_mms.get(m)
        if t:
            c = cards[i]
            c["cn"], c["cls"], c["cls2"] = t
    n_with_cn = sum(1 for c in cards if c["cn"])
    print(f"[compile] catalog_full.csv → {n_cat} 行（修复 {cat_fixed}）；"
          f"分类号命中 {cn_hit} 行 / {len(cn_by_mms)} 书；孤儿位置行 {cat_missing}", flush=True)

    # ---- 3) shelf_index.csv → shelves.json（+ top 学科） ----
    shelves = []
    sp = os.path.join(src, "shelf_index.csv")
    if os.path.exists(sp):
        with open(sp, encoding="utf-8-sig", newline="") as f:
            rd = csv.reader(f)
            next(rd)
            for row in rd:
                if len(row) < 5:
                    continue
                lib, lname, sub, shelf, cnt = row[0], row[1], row[2], row[3], row[4]
                key = (lib, sub, shelf)
                tops = []
                cc = shelf_cls.get(key)
                if cc:
                    tops = [[k, v] for k, v in cc.most_common(8)]
                shelves.append({
                    "library": lib, "library_name": lname, "sublocation": sub,
                    "shelf": shelf, "books_count": int(cnt) if cnt.isdigit() else cnt,
                    "top_subjects": tops,
                })
        print(f"[compile] shelf_index.csv → {len(shelves)} 书架（{sum(1 for s in shelves if s['top_subjects'])} 架有学科画像）", flush=True)

    # ---- 4) 涵泳特藏 jsonl → 补充标记/新增 ----
    seen_hy = set()
    hy_tagged = 0
    hy_new = 0
    for fn in HY_FILES:
        p = os.path.join(src, fn)
        if not os.path.exists(p):
            print(f"[compile] 警告: 缺 {fn}，跳过")
            continue
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            m = o["mms"]
            if m in seen_hy:
                continue
            seen_hy.add(m)
            i = mms_pos.get(m)
            if i is None:
                cards.append({
                    "mms": m, "title": o.get("title", ""),
                    "creator": o.get("creator", ""), "publisher": o.get("publisher", ""),
                    "year": o.get("year", ""), "language": o.get("language", ""),
                    "type": o.get("type", ""), "hc": len(o.get("holdings", [])),
                    "loc": "", "src": "hy", "cn": "", "cls": "", "cls2": "",
                })
                hy_new += 1
            else:
                c = cards[i]
                if not c["loc"].strip():
                    c["src"] = "hy"
                    hy_tagged += 1
    print(f"[compile] 涵泳特藏: 清单 {len(seen_hy)} 条 | 标记 {hy_tagged} 条 | 新增 {hy_new} 条", flush=True)

    # ---- 5) subjects.json（学科目录：标准学科组 + 馆藏代码组） ----
    cls_cnt = Counter()
    cls2_by_cls = defaultdict(Counter)
    for c in cards:
        if c["cls"]:
            cls_cnt[c["cls"]] += 1
            cls2_by_cls[c["cls"]][c["cls2"]] += 1

    def mk_item(code, cnt):
        subs = [[k, v] for k, v in cls2_by_cls[code].most_common() if k != code]
        return {
            "code": code,
            "name": CLC_NAMES.get(code, "馆藏代码"),
            "count": cnt,
            "sub": subs[:30],
        }

    classes, collections = [], []
    for code, cnt in cls_cnt.most_common():
        (classes if is_std_cls(code) else collections).append(mk_item(code, cnt))
    subjects = {
        "total_cards": len(cards),
        "total_with_cn": n_with_cn,
        "classes": classes,
        "collections": collections,
    }

    # ---- 6) 写出 ----
    os.makedirs(args.out, exist_ok=True)
    out_cards = os.path.join(args.out, "cards.jsonl")
    with open(out_cards, "w", encoding="utf-8") as f:
        for c in cards:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(os.path.join(args.out, "shelves.json"), "w", encoding="utf-8") as f:
        json.dump({"shelves": shelves}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "subjects.json"), "w", encoding="utf-8") as f:
        json.dump(subjects, f, ensure_ascii=False, indent=1)

    report = {
        "src": os.path.abspath(src),
        "out": os.path.abspath(args.out),
        "cards_total": len(cards),
        "cards_main": n_main,
        "cards_hy_tagged": hy_tagged,
        "cards_hy_new": hy_new,
        "fixed_rows": fixed,
        "cat_rows": n_cat,
        "cat_fixed_rows": cat_fixed,
        "cards_with_cn": n_with_cn,
        "cn_coverage": round(n_with_cn / max(len(cards), 1), 4),
        "std_classes": len(classes),
        "collections": len(collections),
        "shelves": len(shelves),
        "hy_list_total": len(seen_hy),
        "compile_seconds": round(time.time() - t0, 1),
    }
    with open(os.path.join(args.out, "compile_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    assert len(cards) == n_main + hy_new, "卡片数自检失败"
    print(f"[compile] 完成: {len(cards)} 卡 → {out_cards}（{time.time() - t0:.1f}s）", flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
