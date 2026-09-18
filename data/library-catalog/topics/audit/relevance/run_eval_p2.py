#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立评测 · 路径 P2（种子=整词命中中 freq 最低者）+ 四命令语义覆盖检查。

P1（已跑）= search 工具自身排序首位命中为种子 —— 无人为挑选。
P2（本脚本）= 整词命中（src ∈ exact/token，排除 prefix/substr 碎片）中 freq 最低者为种子 ——
             规则同样确定、无人为挑选，语义上等价于「用户点查询里最专门的那个词」。
两者对照可把「种子排序缺陷」与「图/工具缺陷」分离。
"""
import os
import re
import subprocess
import sys

TOOL = "/home/wzh/go/reasonix-scripts/lib-catalog/topic_graph.py"
DATA = "/home/wzh/go/lib-catalog-data"
OUT = os.path.dirname(os.path.abspath(__file__))

QUERIES = [
    ("Q01", "机器学习 入门"), ("Q02", "量子 计算"), ("Q03", "中国 文学史"),
    ("Q04", "economics 教材"), ("Q05", "climate change"), ("Q06", "唐诗"),
    ("Q07", "数据结构 算法"), ("Q08", "佛教 哲学"), ("Q09", "deep learning"),
    ("Q10", "城市规划"),
]

HIT_RE = re.compile(r"^\s*(\d+)\s+(\S+)\s+(kw|cls)\s+(\d+)\s+\d+\s+(\S+)\s+(\S+)\s+([\d.]+)")


def run(args):
    p = subprocess.run([sys.executable, TOOL, "--data", DATA] + args,
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def hits(stdout):
    out = []
    for line in stdout.splitlines():
        m = HIT_RE.match(line)
        if m:
            out.append({"id": int(m.group(1)), "term": m.group(2), "freq": int(m.group(4)),
                        "cls": m.group(5), "src": m.group(6), "w": float(m.group(7))})
    return out


def main():
    raw = os.path.join(OUT, "raw")
    rows = []
    for qid, q in QUERIES:
        rc, so, _ = run(["search", q, "--top", "10"])
        hs = hits(so)
        whole = [h for h in hs if h["src"] in ("exact", "token")]
        pool = whole or hs
        seed = min(pool, key=lambda h: (h["freq"], h["id"])) if pool else None
        if seed is None:
            rows.append((qid, q, None, None, ""))
            continue
        rc2, so2, se2 = run(["around", str(seed["id"]), "--hops", "2", "--top", "10", "--evidence", "5"])
        with open(f"{raw}/{qid}-around-P2.txt", "w", encoding="utf-8") as f:
            f.write(f"$ topic_graph.py --data $D around {seed['id']} --hops 2 --top 10 --evidence 5\n")
            f.write(f"[exit={rc2}]  # P2 seed = {seed['term']} (整词命中中 freq 最低)\n{so2}\n---stderr---\n{se2}\n")
        rows.append((qid, q, seed["id"], seed["term"], so2))
        print(f"{qid}\t{q}\tP2seed={seed['id']}/{seed['term']}\tfreq={seed['freq']}\trc={rc2}")

    # 四命令语义覆盖：graph 与 around 同参一致性 + summarize 存根确定性
    cov = []
    for qid, tid in (("Q06", 529), ("Q09", 33)):
        rcg, sog, _ = run(["graph", str(tid), "--hops", "2", "--json-out", f"{raw}/graph-{qid}.json"])
        import json
        with open(f"{raw}/graph-{qid}.json", encoding="utf-8") as f:
            g = json.load(f)
        cov.append((qid, tid, rcg, len(g["nodes"]), len(g["edges"]), g["stats"]["visited"],
                    g["stats"]["edges_scanned"], round(g["stats"]["elapsed_ms"], 1)))
    s1 = run(["summarize", "529", "--hops", "2"])[1]
    s2 = run(["summarize", "529", "--hops", "2"])[1]
    with open(f"{raw}/COVERAGE.txt", "w", encoding="utf-8") as f:
        f.write("graph vs around 一致性（同 seed 同 hops=2）\n")
        for qid, tid, rc, n, e, visited, scanned, ms in cov:
            f.write(f"{qid}\tgraph {tid}\trc={rc}\tnodes={n}\tedges={e}\tvisited={visited}\tscanned={scanned}\t{ms}ms\n")
        f.write(f"\nsummarize 存根确定性（同参两次输出一致）: {s1 == s2}\n")
        f.write(f"summarize(seed=529) 长度={len(s1)} 字符\n")
    for r in cov:
        print("COV", r)
    print("summarize deterministic:", s1 == s2, "| len:", len(s1))


if __name__ == "__main__":
    main()
