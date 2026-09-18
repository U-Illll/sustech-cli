#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立相关性评分采样器（审计方 · 只读主体，写只在 audit/relevance/）。

协议（先于结果固定）:
  对每条查询 q:  search "<q>" --top 10     → 取工具自身排序 **首位命中** 为主题种子 seed(q)
                 around <seed> --hops 2 --top 10 --evidence 5  → 邻域主题 top10 + 证据书 top5
  种子选择规则对 10 条一视同仁，无人为挑选（工具排序即规则）。
"""
import os
import re
import subprocess
import sys

TOOL = "/home/wzh/go/reasonix-scripts/lib-catalog/topic_graph.py"
DATA = "/home/wzh/go/lib-catalog-data"
OUT = os.path.dirname(os.path.abspath(__file__))

QUERIES = [
    ("Q01", "机器学习 入门"),
    ("Q02", "量子 计算"),
    ("Q03", "中国 文学史"),
    ("Q04", "economics 教材"),
    ("Q05", "climate change"),
    ("Q06", "唐诗"),
    ("Q07", "数据结构 算法"),
    ("Q08", "佛教 哲学"),
    ("Q09", "deep learning"),
    ("Q10", "城市规划"),
]

HIT_RE = re.compile(r"^\s*(\d+)\s+(\S+)\s+(kw|cls)\s+")


def run(args):
    p = subprocess.run([sys.executable, TOOL, "--data", DATA] + args,
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def first_hit(stdout):
    """工具自身排序的首位命中（字面段优先，其次扩展段，取文档顺序第一条）。"""
    for line in stdout.splitlines():
        m = HIT_RE.match(line)
        if m:
            return int(m.group(1)), m.group(2)
    return None, None


def main():
    raw = os.path.join(OUT, "raw")
    os.makedirs(raw, exist_ok=True)
    index = []
    for qid, q in QUERIES:
        rc1, so1, se1 = run(["search", q, "--top", "10"])
        with open(f"{raw}/{qid}-search.txt", "w", encoding="utf-8") as f:
            f.write(f"$ topic_graph.py --data $D search \"{q}\" --top 10\n")
            f.write(f"[exit={rc1}]\n{so1}\n---stderr---\n{se1}\n")
        sid, sterm = first_hit(so1)
        if sid is None:
            index.append((qid, q, None, None, rc1, ""))
            print(f"{qid}\t{q}\tNO_HIT\trc={rc1}")
            continue
        rc2, so2, se2 = run(["around", str(sid), "--hops", "2", "--top", "10", "--evidence", "5"])
        with open(f"{raw}/{qid}-around.txt", "w", encoding="utf-8") as f:
            f.write(f"$ topic_graph.py --data $D around {sid} --hops 2 --top 10 --evidence 5\n")
            f.write(f"[exit={rc2}]  # seed term = {sterm}  (search rank-1)\n{so2}\n---stderr---\n{se2}\n")
        index.append((qid, q, sid, sterm, rc2, so2))
        print(f"{qid}\t{q}\tseed={sid}/{sterm}\tsearch_rc={rc1}\taround_rc={rc2}")
    with open(f"{raw}/INDEX.tsv", "w", encoding="utf-8") as f:
        f.write("qid\tquery\tseed_id\tseed_term\taround_rc\n")
        for qid, q, sid, sterm, rc, _ in index:
            f.write(f"{qid}\t{q}\t{sid}\t{sterm}\t{rc}\n")


if __name__ == "__main__":
    main()
