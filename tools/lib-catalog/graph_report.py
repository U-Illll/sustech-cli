#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
graph_report.py — 语义图谱质量报告（验收工具；对齐 Agentic-RAG 口径并做规模归一化）

检测项（188.5k 节点 / 出度 10 的大图；对照记忆系统 44 页小图的口径讨论见输出说明）:
  1. 基础图统计（节点/边/互链率/sim 分布）
  2. 覆盖率曲线（1/2/3 跳可达节点数）
  3. 同簇覆盖率 vs 跳数（1/2/3/5/8/12 跳；400 簇抽样）—— 规模归一化的"同簇可达"口径
  4. 全局连通性（无向连通分量）与簇内连通性
  5. 语义衰减（1/2/3 跳节点与源点余弦 vs 随机基线）

用法:
  python3 graph_report.py [--data DIR] [--curve-samples 100] [--seed 42]
"""
import argparse
import json
import os
import sys
import time
from collections import Counter

_PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)
import numpy as np

DATA_DEFAULT = os.path.expanduser("~/go/lib-catalog-data")


def resolve_data(args):
    return os.path.abspath(os.path.expanduser(
        getattr(args, "data", None) or os.environ.get("LIB_CATALOG_DATA") or DATA_DEFAULT))


def bfs_levels(src, max_hops, indptr, indices):
    """返回每跳新增节点列表。"""
    seen = {src}
    frontier = [src]
    levels = []
    for _ in range(max_hops):
        nxt = []
        for u in frontier:
            a, b = int(indptr[u]), int(indptr[u + 1])
            for v in indices[a:b]:
                v = int(v)
                if v not in seen:
                    seen.add(v)
                    nxt.append(v)
        levels.append(nxt)
        frontier = nxt
        if not frontier:
            break
    return levels


def main():
    ap = argparse.ArgumentParser(description="语义图谱质量报告")
    ap.add_argument("--data", default=None)
    ap.add_argument("--curve-samples", type=int, default=100, help="覆盖曲线的簇样本数")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    D = resolve_data(args)
    idx = os.path.join(D, "index")
    z = np.load(os.path.join(idx, "knn_csr.npz"))
    indptr, indices = z["indptr"], z["indices"]
    sims = z["sims"].astype(np.float32)
    labels = np.load(os.path.join(idx, "clusters.npy"))
    N = len(labels)
    k = len(indices) // N
    gm = json.load(open(os.path.join(idx, "graph_meta.json"), encoding="utf-8"))
    rng = np.random.default_rng(args.seed)
    t0 = time.time()

    print("=== 语义图谱质量报告 ===")
    print(f"节点: {N:,} | 出度: {k} | 边: {len(indices):,} | 互链率: {gm['mutual_ratio']:.3f}")
    print(f"sim: 均 {gm['sim_mean']:.3f} / 中位 {gm['sim_median']:.3f} / P10 {gm['sim_p10']:.3f}")
    print(f"簇: {gm['clusters']}")

    # ---- 覆盖率曲线（3 跳） ----
    srcs = rng.choice(N, 200, replace=False)
    sizes = {1: [], 2: [], 3: []}
    for s in srcs:
        lv = bfs_levels(int(s), 3, indptr, indices)
        cum = 0
        for h in (1, 2, 3):
            if h <= len(lv):
                cum += len(lv[h - 1])
            sizes[h].append(cum)
    print(f"\n[覆盖率] 200 随机源点（可达节点数中位）："
          f"1 跳 {int(np.median(sizes[1]))} / 2 跳 {int(np.median(sizes[2]))} / 3 跳 {int(np.median(sizes[3]))}")

    # ---- 同簇覆盖率 vs 跳数 ----
    members = {}
    for i in range(N):
        members.setdefault(int(labels[i]), []).append(i)
    cl_list = sorted(members)
    pick = rng.choice(len(cl_list), size=min(args.curve_samples, len(cl_list)), replace=False)
    HOPS = [1, 2, 3, 5, 8, 12]
    cov = {h: [] for h in HOPS}
    for pi in pick:
        cl = cl_list[pi]
        mem = set(members[cl])
        src = int(rng.choice(members[cl]))
        lv = bfs_levels(src, max(HOPS), indptr, indices)
        seen = set()
        for h in range(1, max(HOPS) + 1):
            if h <= len(lv):
                seen.update(lv[h - 1])
            if h in cov:
                cov[h].append(len(seen & mem) / max(len(mem), 1))
    print(f"\n[同簇覆盖率 vs 跳数]（{len(pick)} 簇抽样，1 源点/簇）")
    for h in HOPS:
        arr = np.array(cov[h])
        print(f"   {h:>2} 跳: 覆盖均 {arr.mean():.3f} / 中位 {np.median(arr):.3f}")
    print("   说明: 记忆系统（44 页小图）的「3 跳同簇 ≥90%」为该规模口径；")
    print("         本图 188.5k 节点/出度 10，3 跳域仅 ~400 节点，等效口径为上表曲线。")

    # ---- 连通性 ----
    from scipy import sparse
    from scipy.sparse.csgraph import connected_components
    A = sparse.csr_matrix((np.ones(len(indices), dtype=np.int8), indices, indptr), shape=(N, N))
    ncc, cc = connected_components(A + A.T, directed=False)
    csizes = np.bincount(cc)
    print(f"\n[连通性] 无向分量: {ncc} 个；最大 {csizes.max():,}（{csizes.max() / N:.2%}）")
    multi = sum(1 for cl in cl_list if len(set(int(cc[m]) for m in members[cl])) > 1)
    print(f"  簇内单一连通分量: {len(cl_list) - multi}/{len(cl_list)} 簇")

    # ---- 语义衰减 ----
    E = np.load(os.path.join(idx, "embeddings.npy"))
    sub = rng.choice(N, 100, replace=False)
    l1, l2, l3 = [], [], []
    for s in sub:
        lv = bfs_levels(int(s), 3, indptr, indices)
        for h, acc in ((1, l1), (2, l2), (3, l3)):
            if h <= len(lv) and lv[h - 1]:
                acc.append(float((E[lv[h - 1]] @ E[int(s)]).mean()))
    base = float((E @ E[sub].T).mean())
    print(f"\n[语义衰减] 各跳节点与源点平均余弦: 1 跳 {np.mean(l1):.3f} / 2 跳 {np.mean(l2):.3f} / "
          f"3 跳 {np.mean(l3):.3f}（随机基线 {base:.3f}）")

    print(f"\n[耗时] {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
