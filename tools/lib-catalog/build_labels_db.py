#!/usr/bin/env python3
"""构建书标编号查询库（labels.db）——数据源：catalog_labeled.csv（2026-09-20 全量加工）
用法：python3 build_labels_db.py [输出路径]
默认输出：~/go/lib-catalog-data/labels.db
表结构：label(mms, seq, lib, sub, shelf, call) —— seq 为源行序（原序锚定用）
"""
import csv, os, sqlite3, sys
csv.field_size_limit(10**7)
SRC = os.path.expanduser('~/go/library-scrape-site-20260918/labels-20260920/catalog_labeled.csv')
OUT = os.path.expanduser('~/go/lib-catalog-data/labels.db')

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else OUT
    if os.path.exists(out):
        os.remove(out)
    con = sqlite3.connect(out)
    con.execute("CREATE TABLE label (mms TEXT, seq INTEGER, lib TEXT, sub TEXT, shelf TEXT, call TEXT)")
    n, batch = 0, []
    with open(SRC, encoding='utf-8-sig') as f:
        r = csv.DictReader(f)
        for row in r:
            batch.append((row['mms'], n, row['library_name'], row['sublocation'], row['shelf_location'],
                          row['call_number_pure']))
            n += 1
            if len(batch) >= 10000:
                con.executemany("INSERT INTO label VALUES (?,?,?,?,?,?)", batch); batch = []
    if batch:
        con.executemany("INSERT INTO label VALUES (?,?,?,?,?,?)", batch)
    con.execute("CREATE INDEX idx_label_mms ON label(mms)")
    con.commit()
    c = con.execute("SELECT COUNT(*) FROM label").fetchone()[0]
    m = con.execute("SELECT COUNT(DISTINCT mms) FROM label").fetchone()[0]
    con.close()
    print(f"[labels.db] {c} 行 / {m} mms -> {out}")

if __name__ == '__main__':
    main()
