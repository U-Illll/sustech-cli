#!/usr/bin/env python3
# verify_types_r2c.py — R2-C 边型数组独立复验（只读）
#
# 不信任产物自述：从 card_topics.jsonl + index/clusters.npy + nodes.json **独立重算**期望掩码。
#
# 关键口径（与 topic_edges.py 对齐，但独立实现）：
#   卡参与配对的节点集合 = top-5 kw ∪ {该卡 cls2}；card_topics.jsonl 只存 top-5 kw
#   （cls 不占 top-5 名额），故 cls2 不出现在该文件里 —— 本脚本据此刻意分两类验证。
#   · kw-kw 边：两端都在 card_topics 中 → **可全量独立重算**
#       bit0 ⇔ 共现卡数 > 0
#       bit1 ⇔ 存在卡：含二者 ∧ ncl[u]==ncl[v]==该卡簇标签 lab（lab 取自 index/clusters.npy）
#   · 含 cls 端点的边：cls2 不在 card_topics 中 → 不做 pair 重算，改做**不变式与健全性**验证
#       bit0 必置位（cls 只作为卡的 cls2 进入配对集，必与 top-5 kw 同卡）
#       bit1 ⇒ 两端同 cluster（c_sc>0 的必要条件）
#   · bit2：目标必为 cls / 源必为 kw / w==1.0 / 计数 == 构建日志声明值 / 每源点至多 1 条
# 另含：三数组与 R2-A 备份逐位一致 + 契约断言 + 抽样 ≥100 条覆盖全部四类掩码。
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
import numpy as np

DATA = "/home/wzh/go/lib-catalog-data"
T = os.path.join(DATA, "topics")
SAMPLE_N = 200


def main():
    fails = []
    print("=== A 三数组与 R2-A 备份逐位一致（同种子确定性）===")
    a = np.load(os.path.join(T, "edges.csr.pre-r2c.npz"))
    b = np.load(os.path.join(T, "edges.csr.npz"))
    for k in ("indptr", "indices", "weights"):
        ok = a[k].shape == b[k].shape and bool((a[k] == b[k]).all())
        fails += [] if ok else [f"bitdiff:{k}"]
        print(f"  {'OK' if ok else 'DIFF':5s} {k} {b[k].dtype} {b[k].shape}")

    ip, ix, w, t = b["indptr"], b["indices"], b["weights"], b["types"]
    row = np.repeat(np.arange(len(ip) - 1), np.diff(ip))

    print("=== B types 契约 ===")
    vals = sorted(int(v) for v in np.unique(t))
    for name, ok in (("dtype == uint8", t.dtype == np.uint8),
                     ("len(types) == nnz", len(t) == len(ix)),
                     ("值域 ⊆ {1,3,5,7}", set(vals) <= {1, 3, 5, 7}),
                     ("bit0 恒置位", bool((t & 1).all()))):
        fails += [] if ok else [name]
        print(f"  {'OK' if ok else 'FAIL':5s} {name}   (实测值域={vals})")

    nodes = json.load(open(os.path.join(T, "nodes.json"), encoding="utf-8"))
    ntype = np.array([n["type"] for n in nodes])
    ncl = np.array([n["cluster"] for n in nodes], dtype=np.int64)
    labels = np.load(os.path.join(DATA, "index", "clusters.npy")).astype(np.int64)

    print("=== C kw-kw 边：从 card_topics + clusters 全量独立重算 ===")
    kwset = set(np.flatnonzero(ntype == "kw").tolist())
    co = defaultdict(int)
    co_sc = defaultdict(int)
    with open(os.path.join(T, "card_topics.jsonl"), encoding="utf-8") as f:
        for i, line in enumerate(f):
            lab = int(labels[i])
            ids = sorted({int(x) for x in json.loads(line).get("topics", ())})
            for p in range(len(ids)):
                for q in range(p + 1, len(ids)):
                    u, v = ids[p], ids[q]
                    co[(u, v)] += 1
                    if ncl[u] == ncl[v] == lab:
                        co_sc[(u, v)] += 1
    kk = np.flatnonzero((ntype[row] == "kw") & (ntype[ix] == "kw"))
    bad0 = bad1 = bad2 = 0
    for e in kk:
        u, v = int(row[e]), int(ix[e])
        key = (u, v) if u < v else (v, u)
        exp = (1 if co.get(key, 0) > 0 else 0) | (2 if co_sc.get(key, 0) > 0 else 0)
        got = int(t[e])
        if (got & 1) != (exp & 1):
            bad0 += 1
        if (got & 2) != (exp & 2):
            bad1 += 1
        if got & 4:
            bad2 += 1
    for name, n_bad, tot in (("bit0 不符", bad0, len(kk)), ("bit1 不符", bad1, len(kk)),
                             ("kw-kw 边误置 bit2", bad2, len(kk))):
        fails += [] if n_bad == 0 else [f"kk:{name}"]
        print(f"  {'OK' if n_bad == 0 else 'FAIL':5s} {name}: {n_bad} / {tot}")

    print("=== D 含 cls 端点的边：不变式 + 健全性（cls2 不在 card_topics，无法 pair 重算）===")
    ce = np.flatnonzero((ntype[row] == "cls") | (ntype[ix] == "cls"))
    n_nobit0 = int((t[ce] & 1 == 0).sum())
    viol = int(((t[ce] & 2 > 0) & (ncl[row[ce]] != ncl[ix[ce]])).sum())
    for name, n_bad in (("bit0 必置位（cls 仅作为卡 cls2 进入配对集）", n_nobit0),
                        ("bit1 ⇒ 两端同 cluster（健全性）", viol)):
        fails += [] if n_bad == 0 else [f"cls:{name}"]
        print(f"  {'OK' if n_bad == 0 else 'FAIL':5s} {name}: 违例 {n_bad} / {len(ce)}")
    print(f"  INFO 反向不成立属预期：bit1 未置位但同 cluster 有 "
          f"{int(((t[ce] & 2 == 0) & (ncl[row[ce]] == ncl[ix[ce]])).sum())} 条"
          f"（c_sc 还要求该卡簇标签 lab == ncl[u]，非仅节点同簇）")

    print("=== E bit2 层级边：结构 + 计数 + 每源点唯一性 ===")
    b2 = np.flatnonzero(t & 4 > 0)
    src_cls_neigh = Counter()
    for e in np.flatnonzero(ntype[ix] == "cls"):
        src_cls_neigh[int(row[e])] += 1
    b2_per_src = Counter(int(row[e]) for e in b2)
    checks = [
        ("目标全为 cls", bool((ntype[ix[b2]] == "cls").all())),
        ("源全为 kw", bool((ntype[row[b2]] == "kw").all())),
        ("权重全为 1.0", bool((w[b2] == 1.0).all())),
        ("计数 == 构建日志声明 5,151", len(b2) == 5151),
        ("每源点至多 1 条 bit2", max(b2_per_src.values(), default=0) == 1),
        ("有 cls 邻点的源点均有且仅有 1 条 bit2",
         set(b2_per_src) == set(src_cls_neigh)),
    ]
    for name, ok in checks:
        fails += [] if ok else [f"bit2:{name}"]
        print(f"  {'OK' if ok else 'FAIL':5s} {name}")

    print("=== F 抽验 ≥100 条（覆盖全部四类掩码）===")
    rng = np.random.default_rng(20260918)
    sample = rng.choice(len(t), size=SAMPLE_N, replace=False)
    for val in vals:
        pos = np.flatnonzero(t == val)
        if len(pos):
            sample = np.union1d(sample, rng.choice(pos, size=min(25, len(pos)), replace=False))
    hit = Counter(int(t[e]) for e in sample)
    print(f"  抽样 {len(sample)} 条；覆盖 {sorted(hit)}；命中计数 {dict(sorted(hit.items()))}")
    ok = set(hit) == set(vals) and len(sample) >= 100
    fails += [] if ok else ["sample-coverage"]
    print(f"  {'OK' if ok else 'FAIL':5s} 抽样 ≥100 且四类齐全")

    print()
    print("总判定：", "ALL PASS" if not fails else f"FAIL -> {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
