#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图书馆藏书目录导出 完整性检查（全量程序化交叉验证）

检查维度：文件清单 / CSV 格式严格扫描 / 键一致性 / holdings_count / locations /
公共字段 / db ↔ csv 全量 / shelf_index ↔ catalog / report.txt 复核 /
涵泳特藏 jsonl / 抓取日志。

用法:
  python3 check_completeness.py [--base DIR] [--out FILE]
"""
import argparse
import csv, io, json, os, re, sqlite3, sys
from collections import Counter, defaultdict

_ap = argparse.ArgumentParser(description="图书馆目录导出完整性检查")
_ap.add_argument("--base", default="/mnt/c/Users/汪子恒/Desktop/南科大图书馆藏书目录",
                 help="被检查数据目录（含 books.csv 等 10 文件）")
_ap.add_argument("--out", default=None, help="报告输出文件（默认仅打印）")
_args = _ap.parse_args()

BASE = os.path.abspath(os.path.expanduser(_args.base))
if not os.path.isdir(BASE):
    sys.exit(f"[check] 目录不存在: {BASE}")
OUT = []
def w(s=""):
    OUT.append(str(s)); print(s)

def strict_scan(path, ncol):
    bad = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        header = next(rd)
        for i, row in enumerate(rd, start=2):
            if len(row) != ncol:
                bad.append((i, len(row)))
    return header, bad

def read_fixed(path, ncol):
    """列数>ncol 时把 row[4:5+k] 合并回 year（修复未转义逗号）。"""
    fixed, unfixable, rows = 0, [], []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        header = next(rd)
        for i, row in enumerate(rd, start=2):
            if len(row) != ncol:
                if len(row) > ncol:
                    k = len(row) - ncol
                    row = row[:4] + [",".join(row[4:5 + k])] + row[5 + k:]
                    fixed += 1
                if len(row) != ncol:
                    unfixable.append((i, len(row), row[:8]))
                    continue
            rows.append(row)
    return header, rows, fixed, unfixable

# ================= 0. 文件清单 =================
w("=" * 72); w("0. 文件清单"); w("=" * 72)
for f in sorted(os.listdir(BASE)):
    p = os.path.join(BASE, f)
    w(f"  {f:44s} {os.path.getsize(p):>12,} bytes")

# ================= 1. 格式检查 =================
w(); w("=" * 72); w("1. 严格格式扫描 + 修复解析"); w("=" * 72)
hb, bad_b = strict_scan(f"{BASE}/books.csv", 9)
hc, bad_c = strict_scan(f"{BASE}/catalog_full.csv", 13)
w(f"books.csv 表头({len(hb)}列): {hb}")
w(f"  → 严格扫描异常行: {len(bad_b)} 行 | 列数分布: {dict(Counter(x[1] for x in bad_b))}")
w(f"catalog_full.csv 表头({len(hc)}列): {hc}")
w(f"  → 严格扫描异常行: {len(bad_c)} 行 | 列数分布: {dict(Counter(x[1] for x in bad_c))}")

hb2, books_rows, fix_b, unfix_b = read_fixed(f"{BASE}/books.csv", 9)
hc2, cat_rows, fix_c, unfix_c = read_fixed(f"{BASE}/catalog_full.csv", 13)
w(f"books.csv  修复 {fix_b} 行 → {len(books_rows)} 行（无法修复 {len(unfix_b)}）")
w(f"catalog_full.csv 修复 {fix_c} 行 → {len(cat_rows)} 行（无法修复 {len(unfix_c)}）")
for s in unfix_b[:3]: w(f"  books 未修复: {s}")
for s in unfix_c[:3]: w(f"  catalog 未修复: {s}")

# ================= 2. 键一致性 =================
w(); w("=" * 72); w("2. 键一致性"); w("=" * 72)
books = {}; dup_b = []
for r in books_rows:
    if r[0] in books: dup_b.append(r[0])
    books[r[0]] = r
cat = defaultdict(list)
for r in cat_rows: cat[r[0]].append(r)
w(f"books unique mms: {len(books)}（重复 {len(dup_b)}）")
w(f"catalog unique mms: {len(cat)}")
only_b = set(books) - set(cat); only_c = set(cat) - set(books)
w(f"仅 books 有: {len(only_b)} | 仅 catalog 有: {len(only_c)}")
if only_b: w(f"  样例: {list(only_b)[:5]}")
if only_c: w(f"  样例: {list(only_c)[:5]}")
empty_b = sum(1 for m in books if not m.strip()); empty_c = sum(1 for m in cat if not m.strip())
w(f"空 mms: books {empty_b} / catalog {empty_c}")

# ================= 3. holdings_count / locations =================
w(); w("=" * 72); w("3. holdings_count & locations ↔ catalog"); w("=" * 72)
hc_bad, loc_bad = [], []
for m, r in books.items():
    rows = cat.get(m, [])
    try: hcens = int(r[7])
    except ValueError: hcens = None
    if hcens != len(rows): hc_bad.append((m, r[7], len(rows)))
    exp = "; ".join(f"{x[8]}/{x[9]}" + (f"/{x[11]}" if x[11] else "") for x in rows)
    if r[8] != exp: loc_bad.append((m, r[8][:90], exp[:90]))
w(f"holdings_count 不一致: {len(hc_bad)} （样例 {hc_bad[:5]}）")
w(f"locations 不一致: {len(loc_bad)} （样例 {loc_bad[:3]}）")

# ================= 4. 公共字段 =================
w(); w("=" * 72); w("4. books ↔ catalog 公共字段"); w("=" * 72)
fld_bad = Counter(); samples = {}
for m, r in books.items():
    rows = cat.get(m)
    if not rows: continue
    x = rows[0]
    for idx, name in ((1,"title"),(2,"creator"),(3,"publisher"),(4,"year"),(5,"language"),(6,"type")):
        if r[idx] != x[idx]:
            fld_bad[name] += 1
            samples.setdefault(name, (m, r[idx][:60], x[idx][:60]))
w(f"不一致: {dict(fld_bad)}")
for k, s in samples.items(): w(f"  {k}: {s}")

# ================= 5. db ↔ csv =================
w(); w("=" * 72); w("5. db ↔ csv 全量对比"); w("=" * 72)
con = sqlite3.connect(f"{BASE}/sustc_library.db")
db_books = {r[0]: r for r in con.execute("SELECT mms,title,creator,publisher,year,language,type FROM books")}
w(f"db.books {len(db_books)} 行 / db.holdings {con.execute('SELECT COUNT(*) FROM holdings').fetchone()[0]} 行")
miss = set(books) ^ set(db_books)
w(f"books mms 集合差异: {len(miss)}")
db_fld_bad = Counter(); db_samples = {}
for m, r in books.items():
    d = db_books.get(m)
    if d is None: continue
    for idx, name in ((1,"title"),(2,"creator"),(3,"publisher"),(4,"year"),(5,"language"),(6,"type")):
        if r[idx] != d[idx]:
            db_fld_bad[name] += 1
            db_samples.setdefault(name, (m, r[idx][:60], d[idx][:60]))
w(f"字段不一致: {dict(db_fld_bad)}")
for k, s in db_samples.items(): w(f"  {k}: {s}")

db_hold = defaultdict(list)
for r in con.execute("SELECT mms,library,library_name,sublocation,call_number,shelf_location,status FROM holdings"):
    db_hold[r[0]].append(r)
hold_bad = 0; hold_samples = []
for m, rows in cat.items():
    a = sorted(tuple(x[7:13]) for x in rows)      # library..status (6 字段)
    b = sorted(tuple(x[1:7]) for x in db_hold.get(m, []))
    if a != b:
        hold_bad += 1
        if len(hold_samples) < 3: hold_samples.append((m, a[:1], b[:1]))
w(f"holdings 不一致 mms 数: {hold_bad} （样例 {hold_samples[:2]}）")
con.close()

# ================= 6. shelf_index =================
w(); w("=" * 72); w("6. shelf_index ↔ catalog 聚合"); w("=" * 72)
si = list(csv.DictReader(open(f"{BASE}/shelf_index.csv", encoding="utf-8-sig", newline="")))
w(f"shelf_index 数据行: {len(si)}")
agg_full = Counter((r[7], r[9], r[11]) for r in cat_rows)          # 含空 shelf
agg_nonempty = Counter({k: v for k, v in agg_full.items() if k[2]})  # 只看有架位
si_bad = []
si_keys = set()
for r in si:
    k = (r["library"], r["sublocation"], r["shelf_location"])
    si_keys.add(k)
    if agg_nonempty.get(k) != int(r["books_count"]):
        si_bad.append((k, r["books_count"], agg_nonempty.get(k, 0)))
w(f"shelf_index 键 {len(si_keys)} / catalog 非空架位键 {len(agg_nonempty)}")
w(f"计数不一致: {len(si_bad)} （样例 {si_bad[:5]}）")
only_si = si_keys - set(agg_nonempty); only_agg = set(agg_nonempty) - si_keys
w(f"仅 shelf_index: {len(only_si)} | 仅 catalog: {len(only_agg)}")
if only_si: w(f"  样例: {list(only_si)[:5]}")
if only_agg: w(f"  样例: {list(only_agg)[:5]}")
# books_count 合计
w(f"shelf_index books_count 合计: {sum(int(r['books_count']) for r in si)} / catalog 非空架位合计: {sum(agg_nonempty.values())}")

# ================= 7. report.txt 复核 =================
w(); w("=" * 72); w("7. report.txt 数字复核"); w("=" * 72)
rep = open(f"{BASE}/report.txt", encoding="utf-8").read()
def grab(pat):
    m = re.search(pat, rep)
    return int(m.group(1)) if m else None
r_total, r_uniq, r_hold = grab(r"记录总数.*?:\s*(\d+)"), grab(r"唯一书目.*?:\s*(\d+)"), grab(r"馆藏位置行.*?:\s*(\d+)")
w(f"report 声明: 原始行 {r_total} / unique {r_uniq} / 位置行 {r_hold}")
w(f"实际解析: unique {len(cat)} / 位置行 {len(cat_rows)}")
lib_cnt = Counter(); lib_uniq = defaultdict(set)
for r in cat_rows:
    lib_cnt[r[7]] += 1; lib_uniq[r[7]].add(r[0])
for line in rep.splitlines():
    m = re.match(r"\s+(\w+)\s+\(([^)]+)\):\s+(\d+)\s+位置\s+/\s+(\d+)\s+唯一书", line)
    if m:
        lib, _n, pos, uq = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        ok = (lib_cnt[lib], len(lib_uniq[lib])) == (pos, uq)
        w(f"  {lib}: report {pos}/{uq} vs 实际 {lib_cnt[lib]}/{len(lib_uniq[lib])} {'✓' if ok else '✗'}")
# 馆藏地 top40
sub_agg = Counter((r[7], r[9]) for r in cat_rows)
sec_sub = rep.split("=== 按馆藏地")[1].split("=== 按书架")[0]
rep_sub_lines = re.findall(r"^\s{2}(.+?):\s+(\d+)\s*$", sec_sub, re.M)
sub_bad = 0
for name, n in rep_sub_lines:
    lib, sub = name.split("/", 1)
    actual = sub_agg.get((lib, sub), 0)
    if actual != int(n):
        sub_bad += 1; w(f"  ✗ 馆藏地 {name}: report {n} vs 实际 {actual}")
w(f"馆藏地前40 复核: {len(rep_sub_lines)} 行, 不一致 {sub_bad}")
# 书架 top60
sec_shelf = rep.split("=== 按书架")[1]
rep_shelf_lines = re.findall(r"^\s{2}(.+?):\s+(\d+)\s*$", sec_shelf, re.M)
shelf_bad = 0
for name, n in rep_shelf_lines:
    parts = name.split("/")
    k = (parts[0], parts[1], parts[2]) if len(parts) == 3 else None
    actual = agg_nonempty.get(k, 0)
    if actual != int(n):
        shelf_bad += 1; w(f"  ✗ 书架 {name}: report {n} vs 实际 {actual}")
w(f"书架前60 复核: {len(rep_shelf_lines)} 行, 不一致 {shelf_bad}")

# ================= 8. 涵泳特藏 jsonl =================
w(); w("=" * 72); w("8. 涵泳特藏 jsonl"); w("=" * 72)
jl_files = ["涵泳特藏_直取.jsonl", "涵泳特藏_穷举补全.jsonl", "涵泳特藏_穷举补全2.jsonl"]
all_jl = {}   # mms -> (file, obj)
jl_dups = []
jl_bad = []
for fn in jl_files:
    n = 0; uniq = set()
    for ln, line in enumerate(open(f"{BASE}/{fn}", encoding="utf-8"), 1):
        line = line.strip()
        if not line: continue
        try: o = json.loads(line)
        except json.JSONDecodeError as e:
            jl_bad.append((fn, ln, str(e)[:60])); continue
        n += 1
        m = o.get("mms")
        if m in uniq: jl_dups.append((fn, m))
        uniq.add(m)
        if m in all_jl: jl_dups.append(("cross", m))
        else: all_jl[m] = (fn, o)
    w(f"  {fn}: {n} 行 / unique {len(uniq)}")
w(f"三文件合计 unique mms: {len(all_jl)}（跨文件/内部重复记录 {len(jl_dups)}，样例 {jl_dups[:5]}）")
w(f"非法 JSON 行: {len(jl_bad)} {jl_bad[:3]}")
# 与 catalog library_3 对比
lib3 = {m for m, rows in cat.items() if rows[0][7] == "library_3"}
jl_set = set(all_jl)
w(f"jsonl mms ⊆ catalog? {jl_set <= lib3}（jsonl 独有 {len(jl_set - lib3)}，catalog library_3 独有 {len(lib3 - jl_set)}）")
inter = jl_set & lib3
w(f"交集: {len(inter)}")
# jsonl mms 在 catalog 中的 library 分布（若不是 library_3）
lib_of = Counter(cat[m][0][7] for m in jl_set - lib3 if m in cat)
w(f"jsonl 中非 library_3 的 mms 其所属馆: {dict(lib_of)}")
# 抽样看结构
k0 = next(iter(all_jl))
w(f"样例条目({k0}): {json.dumps(all_jl[k0][1], ensure_ascii=False)[:200]}")

# ================= 9. 抓取日志 =================
w(); w("=" * 72); w("9. 抓取日志扫描"); w("=" * 72)
log = open(f"{BASE}/抓取日志.txt", encoding="utf-8", errors="replace").read()
w(f"日志大小: {len(log):,} 字符, {log.count(chr(10)):,} 行")
for kw in ["DELIVERED", "fatal", "FATAL", "error", "ERROR", "Traceback", "302816", "165937", "192252"]:
    c = log.count(kw)
    w(f"  关键词 {kw!r}: {c} 次")
# 找 302816 出现位置
for m in re.finditer(r".{0,80}302816.{0,80}", log):
    w(f"  302816 ctx: {m.group(0)[:160]!r}")
    break

w(); w("=" * 72); w("10. 结论见下方汇总"); w("=" * 72)
if _args.out:
    with open(_args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(OUT))
    print(f"\n[done] 报告已写 {_args.out}")
else:
    print("\n[done]（未指定 --out，报告仅打印）")
