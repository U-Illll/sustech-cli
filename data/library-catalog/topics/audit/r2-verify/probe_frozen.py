#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_frozen.py — 为 R2-E 基线升级，探明 R2 后各 FROZEN 键的实际取值。只读。"""
import json
import math
import os
from collections import Counter

import numpy as np

T = os.path.expanduser("~/go/lib-catalog-data/topics")
D = os.path.expanduser("~/go/lib-catalog-data")
nodes = json.load(open(os.path.join(T, "nodes.json"), encoding="utf-8"))
by = {x["term"]: x for x in nodes}
term_of = {x["id"]: x["term"] for x in nodes}
ncl = {x["id"]: int(x["cluster"]) for x in nodes}
nfreq = {x["id"]: int(x["freq"]) for x in nodes}
typ = {x["id"]: x["type"] for x in nodes}

print("=== 节点表 ===")
print("nodes=%d kw=%d cls=%d" % (len(nodes), sum(1 for x in nodes if x["type"] == "kw"),
                                 sum(1 for x in nodes if x["type"] == "cls")))
vic = [x for x in nodes if x["term"] != x["term"].lower()]
print("m2 大写节点=%d" % len(vic))

# ---- 共现计数（aug：top-5 kw ∪ {cls2}）----
cls2id = {x["term"].upper(): x["id"] for x in nodes if x["type"] == "cls"}
labels = np.load(os.path.join(D, "index", "clusters.npy"))
cnt, csc = Counter(), Counter()
with open(os.path.join(D, "cards.jsonl"), encoding="utf-8") as fc, \
     open(os.path.join(T, "card_topics.jsonl"), encoding="utf-8") as ft:
    for i, (lc, lt) in enumerate(zip(fc, ft)):
        c, t = json.loads(lc), json.loads(lt)
        lab = int(labels[i])
        items = list(t["topics"])
        cid = cls2id.get((c.get("cls2") or "").strip().upper(), -1)
        if cid >= 0:
            items.append(cid)
        for x in range(len(items)):
            for y in range(x + 1, len(items)):
                a, b = items[x], items[y]
                if a == b:
                    continue
                if a > b:
                    a, b = b, a
                cnt[(a, b)] += 1
                if ncl.get(a) == ncl.get(b) == lab:
                    csc[(a, b)] += 1


def pair_vals(ta, tb):
    a, b = by[ta]["id"], by[tb]["id"]
    k = (min(a, b), max(a, b))
    c = cnt.get(k, 0)
    sc = csc.get(k, 0)
    w = min(1.0, math.log1p(min(c, 50)) / math.log1p(50) + 0.3 * math.log1p(sc) / math.log1p(50))
    assoc = c / math.sqrt(max(nfreq[k[0]], 1) * max(nfreq[k[1]], 1))
    return c, sc, w, assoc


print("\n=== ce1 / ce2 现值 ===")
c, sc, w, _ = pair_vals("settlement", "entanglement")
print("ce1 settlement-entanglement: c=%d sc=%d w=%.10f stored_f32=%.10f" % (c, sc, w, float(np.float32(w))))
for ta, tb in (("经济学", "economist"), ("经济学", "economic")):
    c, sc, w, a = pair_vals(ta, tb)
    print("ce2 %s-%s: c=%d sc=%d w=%.6f assoc=%.6f (round4=%.4f)" % (ta, tb, c, sc, w, a, round(a, 4)))

# ---- D1 层级边 ----
votes = {}
with open(os.path.join(D, "cards.jsonl"), encoding="utf-8") as fc, \
     open(os.path.join(T, "card_topics.jsonl"), encoding="utf-8") as ft:
    for lc, lt in zip(fc, ft):
        c, t = json.loads(lc), json.loads(lt)
        cid = cls2id.get((c.get("cls2") or "").strip().upper(), -1)
        if cid < 0:
            continue
        for u in t["topics"]:
            votes.setdefault(u, Counter())[cid] += 1
hier = {u: max(cc.items(), key=lambda kv: (kv[1], -kv[0]))[0] for u, cc in votes.items()}
z = np.load(os.path.join(T, "edges.csr.npz"))
ip, ix = z["indptr"], z["indices"]
present = set()
for u in range(len(nodes)):
    for q in range(int(ip[u]), int(ip[u + 1])):
        present.add((u, int(ix[q])))
missing = [(u, v) for u, v in hier.items() if (u, v) not in present]
print("\n=== D1 ===")
print("登记层级边=%d 实存=%d 缺失=%d" % (len(hier), len(hier) - len(missing), len(missing)))

# ---- F2 现值 ----
p1 = json.load(open(os.path.join(T, "p1-build-report.json"), encoding="utf-8"))["counts"]
p1pre = json.load(open(os.path.join(T, "p1-build-report.pre-r2.json"), encoding="utf-8"))["counts"]
print("\n=== F2 ===")
for k in ("a_containment_ratio_max", "a_terms_ratio_gt1", "source_a_kept",
          "source_a_dropped_embedded", "a_terms_ratio_ge_0.9"):
    print("  %-28s now=%-10s pre-r2=%s" % (k, p1.get(k), p1pre.get(k)))
ev = json.load(open(os.path.join(T, "audit", "p1", "evidence", "ext_double_count.json"), encoding="utf-8"))
flips = [x["term"] for x in (ev.get("flip_sample") or [])]
terms = set(by)
print("  证据快照 double_count_events=%s ratio_gt1=%s flips=%s" % (
    ev.get("double_count_events"), ev.get("ratio_gt1_terms"), ev.get("fragment_drop_flips")))
print("  flip 样本 %d 条，在表 %d 条" % (len(flips), sum(1 for t in flips if t in terms)))

# ---- 类型数组 ----
print("\n=== 边表/类型 ===")
print("npz keys=%s nnz=%d" % (list(z.keys()), len(ix)))
if "types" in z:
    ty = z["types"]
    print("  types dtype=%s len=%d 值域=%s" % (ty.dtype, len(ty), sorted(set(int(x) for x in ty))))
wt = z["weights"]
print("  w min=%.6f mean=%.6f eq1=%d (%.4f)" % (wt.min(), wt.mean(), int((wt >= 0.99999).sum()),
                                               (wt >= 0.99999).mean()))
z0 = np.load(os.path.join(T, "edges.csr.pre-r2.npz"))
print("  pre-r2 nnz=%d keys=%s" % (len(z0["indices"]), list(z0.keys())))
print("  三数组与 pre-r2 逐位一致: indptr=%s indices=%s weights=%s" % (
    np.array_equal(ip, z0["indptr"]), np.array_equal(ix, z0["indices"]),
    np.array_equal(wt, z0["weights"])))
