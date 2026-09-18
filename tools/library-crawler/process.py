#!/usr/bin/env python3
"""合并 records.jsonl → 去重(by mms) + 解析书架位置 → 导出 CSV/SQLite + 统计

用法: python3 process.py
输出: /tmp/library-scrape/final/
  - catalog_full.csv    行级(书×馆藏位置)，Excel 友好(utf-8-sig)
  - books.csv           书级(含馆藏数量与位置摘要)
  - sustc_library.db    SQLite(books + holdings 两表)
  - report.txt          统计报告
"""
import json, re, sqlite3, os
from pathlib import Path
from collections import defaultdict, Counter

BASE = Path("/tmp/library-scrape")
SRC = BASE / "output" / "records.jsonl"
HY1 = BASE / "hanyong_partial.jsonl"
HY2 = BASE / "hanyong_extra.jsonl"
HY3 = BASE / "hanyong_extra2.jsonl"
OUT = BASE / "final"
OUT.mkdir(parents=True, exist_ok=True)

LIB_NAMES = {
    'LYNN': '琳恩图书馆',
    'yidan': '一丹图书馆',
    'library_3': '涵泳图书馆',
}

def clean_multi(v):
    """清洗 Primo 多值字段（$$Q/$$T 等分隔符 + 重复值）"""
    if isinstance(v, list):
        v = "$$Q".join(str(x) for x in v)
    if not isinstance(v, str):
        return ''
    parts = re.split(r'\$\$[A-Z]', v)
    seen = []
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.append(p)
    return "; ".join(seen)

def parse_shelf(call):
    """从索书号提取书架位置"""
    if not call:
        return ''
    c = call.strip()
    m = re.search(r'第\s*(\d+)\s*排\s*([ABCD])\s*面', c)
    if m:
        return f"第{m.group(1)}排{m.group(2)}面"
    m = re.search(r'第\s*(\d+)\s*排(?!\s*[ABCD]\s*面)', c)
    if m:
        return f"第{m.group(1)}排"
    m = re.search(r'第\s*(\d+)\s*架(?:\s*Shelf\s*No\.?\s*(\d+))?', c)
    if m:
        if m.group(2):
            return f"第{m.group(1)}架(Shelf No.{m.group(2)})"
        return f"第{m.group(1)}架"
    return ''

def main():
    # ------------------------------------------------------------------
    # F9 修复（P4 修订轮）：CSV 转义 + 交付门禁
    #   原实现只对部分列调用 esc()，year/language/type/library/library_name/status
    #   直出 ⇒ year="1999, c1991" 一类真实数据把整行右移一列
    #   （实况：catalog_full.csv 187 行 / books.csv 193 行破损，共 380 行）。
    #   两个 helper 刻意留在 main() 内，使 tests/parity-process-py.py 的
    #   AST 抽取（clean_multi/parse_shelf/main + LIB_NAMES）无需任何改动仍然可用。
    # ------------------------------------------------------------------
    def esc(s):
        """RFC4180 条件转义：字段含 , ， " LF CR 时加引号、内部引号加倍。"""
        s = str(s or '')
        if any(ch in s for ch in ',，"\"\n\r'):
            return '"' + s.replace('"', '""') + '"'
        return s

    def esc_q(s):
        """强制加引号（RFC4180 允许，语义等价）：books.csv 的 title/creator/publisher/
        locations 自初版起恒加引号，保留写法使既有正确行逐字节不变。"""
        return '"' + str(s or '').replace('"', '""') + '"'

    def check_csv(path, cols, sample=3):
        """交付门禁：逐行 csv.reader 解析，字段数必须 == 表头列数；破损即拒绝发布。"""
        import csv
        try:
            csv.field_size_limit(2 ** 31 - 1)     # 交付件存在 >128KiB 单字段（ADV-4 #22）
        except OverflowError:
            pass
        bad, want, rows = [], cols, 0
        with open(path, 'r', encoding='utf-8-sig', newline='') as fh:
            rd = csv.reader(fh)
            header = next(rd, None)
            if header is not None:
                want = len(header)
            for lineno, row in enumerate(rd, start=2):
                rows += 1
                if len(row) != want and len(bad) < sample:
                    bad.append((lineno, len(row)))
        if want != cols or bad:
            raise SystemExit(f"[FATAL] {path} CSV 结构破损：期望 {cols} 列 / 表头 {want} 列 / "
                             f"破损行样例 {bad} → 拒绝发布")
        return rows

    # 1. 读入并合并（主数据 + 涵泳特藏数据）
    merged = {}
    total_lines = 0
    bad_lines = 0
    sources = [SRC, HY1, HY2, HY3]
    for src in sources:
        if not src.exists():
            continue
        print(f"读入源: {src}")
        with open(src) as f:
            for line in f:
                total_lines += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    bad_lines += 1
                    continue
                mms = rec.get('mms') or ''
                if not mms:
                    continue
                m = merged.get(mms)
                if m is None:
                    m = {
                        'mms': mms,
                        'title': clean_multi(rec.get('title', '')),
                        'creator': clean_multi(rec.get('creator', '')),
                        'publisher': clean_multi(rec.get('publisher', '')),
                        'year': clean_multi(rec.get('year', '')),
                        'language': clean_multi(rec.get('language', '')),
                        'type': clean_multi(rec.get('type', '')),
                        'holdings': [],
                        '_hkeys': set(),
                    }
                    merged[mms] = m
                else:
                    # 补全字段（取更长/非空）
                    for k in ('title', 'creator', 'publisher', 'year', 'language', 'type'):
                        nv = clean_multi(rec.get(k, ''))
                        if len(nv) > len(str(m[k])):
                            m[k] = nv
                for h in rec.get('holdings', []):
                    key = (h.get('lib', ''), h.get('sub', ''), h.get('call', ''))
                    if key not in m['_hkeys']:
                        m['_hkeys'].add(key)
                        m['holdings'].append(h)

    print(f"输入行数: {total_lines}，坏行: {bad_lines}，唯一书(mms): {len(merged)}")

    # 2. 导出 catalog_full.csv（行级）
    full_csv = OUT / "catalog_full.csv"
    n_rows = 0
    with open(full_csv, 'w', encoding='utf-8-sig') as f:
        f.write("mms,title,creator,publisher,year,language,type,library,library_name,sublocation,call_number,shelf_location,status\n")
        for m in merged.values():
            for h in m['holdings']:
                shelf = parse_shelf(h.get('call', ''))
                f.write(",".join([
                    esc(m['mms']), esc(m['title']), esc(m['creator']), esc(m['publisher']),
                    esc(m['year']), esc(m['language']), esc(m['type']),
                    esc(h.get('lib', '')), esc(LIB_NAMES.get(h.get('lib', ''), h.get('lib', ''))),
                    esc(h.get('sub', '')), esc(h.get('call', '')), esc(shelf),
                    esc(h.get('status', ''))
                ]) + "\n")
                n_rows += 1
    print(f"catalog_full.csv: {n_rows} 行（列结构门禁: {check_csv(full_csv, 13)} 行 OK）")

    # 3. 导出 books.csv（书级）
    books_csv = OUT / "books.csv"
    with open(books_csv, 'w', encoding='utf-8-sig') as f:
        f.write("mms,title,creator,publisher,year,language,type,holdings_count,locations\n")
        for m in merged.values():
            locs = []
            for h in m['holdings']:
                shelf = parse_shelf(h.get('call', ''))
                lib = LIB_NAMES.get(h.get('lib', ''), h.get('lib', ''))
                part = f"{lib}/{h.get('sub', '')}"
                if shelf:
                    part += f"/{shelf}"
                locs.append(part)
            f.write(",".join([
                esc(m['mms']), esc_q(m['title']), esc_q(m['creator']), esc_q(m['publisher']),
                esc(m['year']), esc(m['language']), esc(m['type']),
                esc(str(len(m['holdings']))), esc_q('; '.join(locs))
            ]) + "\n")
    print(f"books.csv: {len(merged)} 书（列结构门禁: {check_csv(books_csv, 9)} 行 OK）")

    # 4. SQLite
    db = OUT / "sustc_library.db"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute("""CREATE TABLE books (
        mms TEXT PRIMARY KEY, title TEXT, creator TEXT, publisher TEXT,
        year TEXT, language TEXT, type TEXT)""")
    cur.execute("""CREATE TABLE holdings (
        mms TEXT, library TEXT, library_name TEXT, sublocation TEXT,
        call_number TEXT, shelf_location TEXT, status TEXT)""")
    for m in merged.values():
        cur.execute("INSERT INTO books VALUES (?,?,?,?,?,?,?)",
                    (m['mms'], m['title'], m['creator'], m['publisher'], m['year'], m['language'], m['type']))
        for h in m['holdings']:
            cur.execute("INSERT INTO holdings VALUES (?,?,?,?,?,?,?)",
                        (m['mms'], h.get('lib', ''), LIB_NAMES.get(h.get('lib', ''), ''),
                         h.get('sub', ''), h.get('call', ''), parse_shelf(h.get('call', '')), h.get('status', '')))
    cur.execute("CREATE INDEX idx_holdings_mms ON holdings(mms)")
    cur.execute("CREATE INDEX idx_holdings_lib ON holdings(library)")
    cur.execute("CREATE INDEX idx_books_title ON books(title)")
    con.commit()
    con.close()
    print(f"sustc_library.db: OK")

    # 5. 统计报告
    rep = OUT / "report.txt"
    lib_counter = Counter()
    lib_books = defaultdict(set)
    sub_counter = Counter()
    shelf_counter = Counter()
    with open(rep, 'w', encoding='utf-8') as f:
        f.write("=== 南科大图书馆全馆藏统计报告 ===\n\n")
        f.write(f"记录总数(条目级原始行): {total_lines}\n")
        f.write(f"唯一书目(mms): {len(merged)}\n")
        f.write(f"馆藏位置行(书×位置): {n_rows}\n\n")
        for m in merged.values():
            for h in m['holdings']:
                lib = h.get('lib', '')
                lib_counter[lib] += 1
                lib_books[lib].add(m['mms'])
                sub_counter[(lib, h.get('sub', ''))] += 1
                shelf = parse_shelf(h.get('call', ''))
                if shelf:
                    shelf_counter[(lib, h.get('sub', ''), shelf)] += 1
        f.write("=== 按图书馆 ===\n")
        for lib, cnt in lib_counter.most_common():
            f.write(f"  {lib} ({LIB_NAMES.get(lib, '?')}): {cnt} 位置 / {len(lib_books[lib])} 唯一书\n")
        f.write("\n=== 按馆藏地(前40) ===\n")
        for (lib, sub), cnt in sub_counter.most_common(40):
            f.write(f"  {lib}/{sub}: {cnt}\n")
        f.write("\n=== 按书架(前60) ===\n")
        for (lib, sub, shelf), cnt in shelf_counter.most_common(60):
            f.write(f"  {lib}/{sub}/{shelf}: {cnt}\n")
    print(f"report.txt: OK")

    # 6. 书架索引（书架 → 书数汇总，按数字序）
    shelf_csv = OUT / "shelf_index.csv"
    def shelf_sort_key(item):
        (lib, sub, shelf), cnt = item
        mnum = re.search(r'第(\d+)', shelf)
        n = int(mnum.group(1)) if mnum else 99999
        return (lib, sub, n, shelf)
    shelf_csv_rows = 0
    with open(shelf_csv, 'w', encoding='utf-8-sig') as f:
        f.write("library,library_name,sublocation,shelf_location,books_count\n")
        for (lib, sub, shelf), cnt in sorted(shelf_counter.items(), key=shelf_sort_key):
            f.write(",".join([esc(lib), esc(LIB_NAMES.get(lib, '')), esc(sub), esc(shelf),
                              esc(str(cnt))]) + "\n")
            shelf_csv_rows += 1
    print(f"shelf_index.csv: {shelf_csv_rows} 个书架（列结构门禁: {check_csv(shelf_csv, 5)} 行 OK）")

    # 7. README
    readme = OUT / "README.md"
    with open(readme, 'w', encoding='utf-8') as f:
        f.write(f"""# 南方科技大学图书馆藏书目录（数据导出）

## 数据来源
图书馆公开检索系统（Ex Libris Primo VE）的公开查询接口，抓取时间 2026-09-14（晚间），并于 2026-09-18 完成遗留缺口补抓更新。
数据来自图书馆面向读者的正常检索通道，未使用任何登录态。

## 文件说明
| 文件 | 内容 |
|---|---|
| catalog_full.csv | **核心文件**：每行 = 一本书 × 一个馆藏位置（含书架位置） |
| books.csv | 书级视图（每行一本书，含馆藏数、位置摘要） |
| shelf_index.csv | 书架索引：每个书架上有多少本书（按图书馆/楼层/书架排号） |
| sustc_library.db | SQLite 数据库（books + holdings 两表，可 SQL 查询） |
| report.txt | 统计报告（按图书馆/馆藏地/书架） |
| 涵泳特藏_*.jsonl | 涵泳图书馆艺术特藏清单（1607 条的子集，见下） |

## 关键字段说明
- `library`: 馆代码（LYNN=琳恩图书馆 / yidan=一丹图书馆 / library_3=涵泳图书馆）
- `sublocation`: 馆内区域（如 3rd Floor / 1st Floor Compact Book Shelves）
- `call_number`: 完整索书号（如 `TP311.13 /113 第28排A面`）
- `shelf_location`: 解析出的书架位置（`第X排Y面` / `第X架`）
- `status`: 抓取时点的在架状态快照

## 书架体系说明（三种形态）
1. **第X排Y面**（中文书区）：X 为书架排号，Y 为 A/B 面 —— 按索书号顺序排架
2. **第X架 Shelf No.X**（琳恩一楼外文小说区）：按作者姓氏字母排序
3. **特藏无架号**：一丹特藏室（签名本/科技史/南科大文库）、涵泳艺术特藏按特藏方式管理

## 完整性说明
- 全馆藏书条目（含复本口径）：约 20.3 万条，本数据集收录约 {len(merged)} 条唯一书目
- 涵泳图书馆艺术特藏共 1607 条（该馆无索书号），本数据集收录其部分清单
- 个别记录可能因图书馆系统检索窗口限制未能收录（<1%）

## 注意事项
- `status` 为抓取时点快照，实时在架状态请以图书馆系统为准
- 各馆藏分布规则（简）：一丹 A-E/TP/TA-TM/TN/TQ-TV 分类 + 密集书库；琳恩 F-K/N-S/U-Z + 外文读物 + 过刊；涵泳 艺术特藏
""")
    print(f"README.md: OK")
    print()
    print(open(rep, encoding='utf-8').read()[:2000])

if __name__ == '__main__':
    main()
