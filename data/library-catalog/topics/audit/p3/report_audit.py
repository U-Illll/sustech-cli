#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report_audit.py — AUDIT-P3：topics_report.py 三口径计算语义独立复算

约束：
  * 只读主体代码与数据（不 import topics_report.py，独立重实现）
  * 只写 audit/p3/ 目录
  * 不访问网络

做三件事：
  A. 独立复算三口径（①主簇 / ②主簇∪类目 / ③无向闭包）并对齐报告值
  B. 变体敏感性：V1「源点计入分子」（终审口径）、V2「源点同时出分母」
  C. 结构检查：连通分量 / 无向闭包饱和性 / 衰减 DP / 性能计时口径 / --json 字段

用法:  PYTHONPATH=~/go/pylibs python3 report_audit.py [--json audit-results.json]
"""
import argparse
import json
import os
import sys
import time
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
TOPICS = os.path.abspath(os.path.join(_HERE, "..", ".."))   # .../topics
PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(PYLIBS) and PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)
import numpy as np

DECAY = 0.86          # topics_report.DECAY
REPORT_HOPS = 12
REPORT_SEED = 42
REPORT_SAMPLES = 400

R = {}                # 结果累积


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


# ---------------------------------------------------------------- 载入
def load_nodes(path):
    raw = json.load(open(path, encoding="utf-8"))
    n = len(raw)
    cluster = np.array([int(x.get("cluster", -1)) for x in raw], dtype=np.int64)
    types = np.array([str(x.get("type", "?")) for x in raw], dtype=object)
    cls_code = np.array([str(x.get("cls", "") or "") for x in raw], dtype=object)
    ids = [int(x["id"]) for x in raw]
    assert ids == list(range(n)), "nodes.json id 非 0..n-1 顺序（审计脚本假设顺序）"
    return n, cluster, types, cls_code


def load_csr(path):
    z = np.load(path)
    return (z["indptr"].astype(np.int64), z["indices"].astype(np.int64),
            z["weights"].astype(np.float64))


def build_undirected(indptr, indices, weights, n):
    """独立构造无向支撑（dict 去重取 max 权重），不依赖 scipy A.maximum(A.T)。"""
    best = {}
    for u in range(n):
        for e in range(int(indptr[u]), int(indptr[u + 1])):
            v = int(indices[e]); w = float(weights[e])
            for a, b in ((u, v), (v, u)):
                k = (a, b)
                if k not in best or w > best[k]:
                    best[k] = w
    edges = sorted(best.items())
    ip = np.zeros(n + 1, dtype=np.int64)
    ix = np.empty(len(edges), dtype=np.int64)
    wt = np.empty(len(edges), dtype=np.float64)
    for t, ((u, v), w) in enumerate(edges):
        ix[t] = v; wt[t] = w
        ip[u + 1] += 1
    np.cumsum(ip, out=ip)
    return ip, ix, wt


def union_find_components(indptr, indices, n):
    """纯 Python 并查集（独立于 scipy connected_components）。"""
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for u in range(n):
        ru = find(u)
        for e in range(int(indptr[u]), int(indptr[u + 1])):
            rv = find(int(indices[e]))
            if ru != rv:
                parent[rv] = ru
    lab = {}
    comp = np.empty(n, dtype=np.int64)
    for i in range(n):
        r = find(i)
        if r not in lab:
            lab[r] = len(lab)
        comp[i] = lab[r]
    sizes = np.bincount(comp)
    return len(lab), comp, sizes


# ---------------------------------------------------------------- BFS
def bfs_np(indptr, indices, weights, src, hops, want_scores=True):
    """独立实现：CSR gather + lexsort 归约。返回 (levels, scores, parents)。
    levels[h] = 第 h 跳首访新增节点（源点已在 visited 中，永不出现在 levels）。"""
    n = len(indptr) - 1
    visited = np.zeros(n, dtype=bool)
    visited[src] = True
    frontier = np.array([src], dtype=np.int64)
    fs = np.ones(1, dtype=np.float64)
    levels, scores, pars = [], [], []
    for _ in range(hops):
        empty = (np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64),
                 np.empty(0, dtype=np.int64))
        if frontier.size == 0:
            levels.append(empty[0]); scores.append(empty[1]); pars.append(empty[2]); continue
        st = indptr[frontier]
        cnt = (indptr[frontier + 1] - st).astype(np.int64)
        tot = int(cnt.sum())
        if tot == 0:
            levels.append(empty[0]); scores.append(empty[1]); pars.append(empty[2])
            frontier = np.empty(0, dtype=np.int64); continue
        off = np.arange(tot, dtype=np.int64) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        pos = np.repeat(st, cnt) + off
        tgt = indices[pos]; ew = weights[pos]
        par_id = np.repeat(frontier, cnt); par_s = np.repeat(fs, cnt)
        keep = ~visited[tgt]
        tgt = tgt[keep]; ew = ew[keep]; par_id = par_id[keep]; par_s = par_s[keep]
        if tgt.size == 0:
            levels.append(empty[0]); scores.append(empty[1]); pars.append(empty[2])
            frontier = np.empty(0, dtype=np.int64); continue
        cand = par_s * ew * DECAY
        order = np.lexsort((cand, tgt))          # 组内 cand 升序 → 末项即组内最大
        ts = tgt[order]
        m = np.empty(len(ts), dtype=bool); m[-1] = True
        np.not_equal(ts[1:], ts[:-1], out=m[:-1])
        p = np.flatnonzero(m)
        tn = ts[p]; tv = cand[order][p]
        npv = par_id[order][p]          # par_id 已按 keep 过滤
        visited[tn] = True
        levels.append(tn); scores.append(tv); pars.append(npv)
        frontier = tn; fs = tv
    if not want_scores:
        return levels, None, None
    return levels, scores, pars


def bfs_py(adj, src, hops):
    """纯 Python 参考实现（独立于 numpy 路径），仅用于交叉校验。"""
    seen = {src}
    frontier = [src]
    levels = []
    for _ in range(hops):
        nxt = []
        for u in frontier:
            for v in adj[u]:
                if v not in seen:
                    seen.add(v); nxt.append(v)
        levels.append(nxt); frontier = nxt
    return levels


def bfs_scores_py(adjw, src, hops):
    """纯 Python 衰减 DP 参考：score(v)=max over 入边 (score(parent)*w*DECAY)。"""
    best = {src: 1.0}
    frontier = [src]
    levels, scores = [], []
    for _ in range(hops):
        cand = {}
        for u in frontier:
            su = best[u]
            for v, w in adjw[u]:
                if v in best:            # 首访优先（与主体同为 BFS 层语义）
                    continue
                s = su * w * DECAY
                if s > cand.get(v, -1.0):
                    cand[v] = s
        levels.append(sorted(cand)); scores.append(np.array([cand[v] for v in sorted(cand)]))
        for v, s in cand.items():
            best[v] = s
        frontier = list(cand)
    return levels, scores


def bfs_levels_scipy(indptr, indices, src, hops, n):
    """scipy bfs_tree 独立路径：用 predecessor 链算跳距（C 实现，独立于自研 BFS）。"""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import breadth_first_order
    A = csr_matrix((np.ones(len(indices), dtype=np.int8), indices, indptr), shape=(n, n))
    order, pred = breadth_first_order(A, src, directed=True, return_predecessors=True)
    dist = np.full(n, -1, dtype=np.int64)
    dist[src] = 0
    for v in order[1:]:
        p = pred[v]
        dist[v] = dist[p] + 1
    return [np.flatnonzero(dist == h) for h in range(1, hops + 1)]


# ---------------------------------------------------------------- 口径
def calibers_one(levels_dir, levels_und, src, cluster, cls_code, members, H):
    """返回该源点在 H 跳上 ①②③ 的分子/分母明细（V0 口径，外加变体所需量）。"""
    c = int(cluster[src]); csize = members[c]
    code = str(cls_code[src] or "")
    m_c = (cluster == c)
    m_u = (m_c | (cls_code == code)) if code else m_c
    usize = int(m_u.sum())
    out = {"csize": csize, "usize": usize, "code": code,
           "cum_same": np.zeros(H), "cum_union": np.zeros(H), "cum_und": np.zeros(H),
           "cum_reach": np.zeros(H, dtype=np.int64), "cum_reach_u": np.zeros(H, dtype=np.int64)}
    rs = ru = 0
    cs = cu = cuu = 0.0                      # 累计分子（② 与 ③ 同样按「累计」口径）
    for h in range(H):
        lv = levels_dir[h]
        if lv.size:
            rs += lv.size
            cs += float(np.count_nonzero(m_c[lv]))
            cu += float(np.count_nonzero(m_u[lv]))
        out["cum_same"][h] = cs
        out["cum_union"][h] = cu
        out["cum_reach"][h] = rs
        lu = levels_und[h]
        if lu.size:
            ru += lu.size
            cuu += float(np.count_nonzero(m_c[lu]))
        out["cum_und"][h] = cuu
        out["cum_reach_u"][h] = ru
    return out


def variants(det, H):
    """V0 as-implemented / V1 源点计入分子 / V2 源点同时出分母。"""
    csize = max(det["csize"], 1); usize = max(det["usize"], 1)
    v = {}
    for tag, num, den_c, den_u in (
            ("V0", 0, csize, usize),
            ("V1", 1, csize, usize),          # 源点 ∈ 主簇 ⊂ 主簇∪类目 ⇒ 分子 +1
            ("V2", 0, max(csize - 1, 1), max(usize - 1, 1))):
        v[tag] = {
            "c1": (det["cum_same"] + num) / den_c,
            "c2": (det["cum_union"] + num) / den_u,
            "c3": (det["cum_und"] + num) / den_c,
            # 次口径「同簇占比」= 可达节点中同簇比例（字面口径，不用于门槛）
            "share": det["cum_same"] / np.maximum(det["cum_reach"], 1),
        }
    return v


def run_calibers(tag, indptr, indices, weights, uip, uix, uw, cluster, cls_code,
                 members, srcs, H):
    """对一批源点跑三口径 × 三变体，返回逐跳均值/中位与明细。"""
    n = len(indptr) - 1
    ns = len(srcs)
    acc = {t: {k: np.zeros((ns, H)) for k in ("c1", "c2", "c3", "share")} for t in ("V0", "V1", "V2")}
    ceiling = np.zeros(ns)          # V0 下满覆盖时的上限 (csize-1)/csize
    reach_final = np.zeros(ns, dtype=np.int64)
    reachu_final = np.zeros(ns, dtype=np.int64)
    reach_hop = np.zeros((ns, H), dtype=np.int64)
    t0 = time.time()
    for i, s in enumerate(srcs):
        s = int(s)
        lv_d, _, _ = bfs_np(indptr, indices, weights, s, H, want_scores=False)
        lv_u, _, _ = bfs_np(uip, uix, uw, s, H, want_scores=False)
        det = calibers_one(lv_d, lv_u, s, cluster, cls_code, members, H)
        vs = variants(det, H)
        for t in ("V0", "V1", "V2"):
            for k in ("c1", "c2", "c3", "share"):
                acc[t][k][i] = vs[t][k]
        ceiling[i] = (det["csize"] - 1) / max(det["csize"], 1)
        reach_hop[i] = det["cum_reach"]
        reach_final[i] = det["cum_reach"][H - 1]
        reachu_final[i] = det["cum_reach_u"][H - 1]
    res = {"tag": tag, "samples": ns, "hops": H, "seconds": round(time.time() - t0, 1),
           "reach_mean_final": float(reach_final.mean()),
           "reach_mean_per_hop": reach_hop.mean(axis=0).tolist(),
           "reach_und_mean_final": float(reachu_final.mean()),
           "ceiling_mean_V0": float(ceiling.mean()),
           "srcs": [int(x) for x in srcs[:16]]}
    for t in ("V0", "V1", "V2"):
        res[t] = {k: {"mean": acc[t][k].mean(axis=0).tolist(),
                      "median": np.median(acc[t][k], axis=0).tolist(),
                      "final_mean": float(acc[t][k].mean(axis=0)[H - 1]),
                      "final_median": float(np.median(acc[t][k], axis=0)[H - 1])}
                  for k in ("c1", "c2", "c3", "share")}
    return res, acc, ceiling



def run_cluster_uniform_frame(indptr, indices, weights, uip, uix, uw, cluster, cls_code,
                              members, pool, H, n_pick=400, seed=REPORT_SEED):
    """graph_report.py 的抽样框：**簇均匀** + 每簇 1 个源点（对比 topics_report 的
    「节点均匀」框）。用于量化「口径对齐 graph_report」在抽样层的偏离。"""
    cl_list = sorted(members)
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(cl_list), size=min(n_pick, len(cl_list)), replace=False)
    pool_set_cl = {}
    for s in pool:
        pool_set_cl.setdefault(int(cluster[s]), []).append(int(s))
    srcs = []
    skipped = 0
    for ci in pick:
        c = cl_list[int(ci)]
        cand = pool_set_cl.get(c, [])
        if not cand:
            skipped += 1
            continue
        srcs.append(int(cand[int(rng.integers(len(cand)))]))
    if not srcs:
        return {"error": "no sources"}
    res, acc, ceil = run_calibers("cluster_uniform_frame", indptr, indices, weights,
                                  uip, uix, uw, cluster, cls_code, members,
                                  np.array(srcs, dtype=np.int64), H)
    res["clusters_picked"] = int(len(pick))
    res["clusters_skipped_no_kw"] = skipped
    res["ceiling_mean_V0"] = float(ceil.mean())
    return res

# ---------------------------------------------------------------- 检查
def check_connectivity(indptr, indices, n, cluster):
    ncc_uf, comp_uf, sizes_uf = union_find_components(indptr, indices, n)
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components
    nE = len(indices)
    A = csr_matrix((np.ones(nE, dtype=np.int8), indices, indptr), shape=(n, n))
    ncc_sp, cc_sp = connected_components(A + A.T, directed=False)
    sizes_sp = np.bincount(cc_sp)
    cl_cnt = Counter(int(x) for x in cluster if int(x) >= 0)
    return {
        "union_find": {"components": int(ncc_uf), "largest": int(sizes_uf.max()),
                       "singletons": int((sizes_uf == 1).sum())},
        "scipy": {"components": int(ncc_sp), "largest": int(sizes_sp.max()),
                  "singletons": int((sizes_sp == 1).sum())},
        "agree": bool(ncc_uf == ncc_sp and sizes_uf.max() == sizes_sp.max()),
        "negative_weights": int((np.load(os.path.join(TOPICS, "edges.csr.npz"))["weights"] < 0).sum()),
        "note_A_plus_AT": "report 用 A+A.T(ones) 求连通；口径③用 A0.maximum(A0.T)(max 权重)。"
                          "零权重边在 + 下仍为 0，在 maximum 下也为 0 —— 两者支撑集一致；"
                          "仅当存在负权重使 w_uv + w_vu == 0 时 A+A.T 会漏边。",
    }


def check_closure_saturation(uip, uix, uw, comp_sp, sizes_sp, cluster, members, srcs, H):
    """③ 是否真为「闭包」：无向 BFS 在 H 跳内是否覆盖整个连通分量。"""
    n = len(uip) - 1
    sat = 0; reach_full = []; unreached = []
    for s in srcs:
        s = int(s)
        lv, _, _ = bfs_np(uip, uix, uw, s, H, want_scores=False)
        cum = sum(int(x.size) for x in lv) + 1      # +1 = 源点自身
        cs = int(sizes_sp[comp_sp[s]])
        reach_full.append(cum)
        if cum >= cs:
            sat += 1
        else:
            unreached.append(cs - cum)
    return {"samples": len(srcs), "saturated_within_H": sat,
            "saturated_pct": sat / max(len(srcs), 1),
            "max_unreached": (max(unreached) if unreached else 0)}


def check_decay(indptr, indices, weights, srcs, H):
    """衰减：hop1 = 最优边权均值 × 0.86；DP 最优性；retention 语义。"""
    n = len(indptr) - 1
    sc = np.full((len(srcs), H), np.nan)
    par_mean = np.full((len(srcs), H), np.nan)
    for i, s in enumerate(srcs):
        lv, ss, pp = bfs_np(indptr, indices, weights, int(s), H)
        for h in range(H):
            if lv[h].size:
                sc[i, h] = ss[h].mean()
                if h == 0:
                    par_s = np.ones_like(ss[h])
                else:
                    look = np.zeros(n); look[lv[h - 1]] = ss[h - 1]
                    par_s = look[pp[h]]
                d = par_s * DECAY
                ok = d > 0
                if ok.any():
                    par_mean[i, h] = float((ss[h][ok] / d[ok]).mean())
    with np.errstate(invalid="ignore"):
        dm = np.array([np.nanmean(sc[:, h]) if np.any(~np.isnan(sc[:, h])) else np.nan
                       for h in range(H)])
        em = np.array([np.nanmean(par_mean[:, h]) if np.any(~np.isnan(par_mean[:, h])) else np.nan
                       for h in range(H)])
    ret = np.full(H, np.nan)
    for h in range(1, H):
        if np.isfinite(dm[h]) and np.isfinite(dm[h - 1]) and dm[h - 1] > 0:
            ret[h] = dm[h] / dm[h - 1]
    wbar = float(weights.mean())
    return {
        "hop1_mean_score": float(dm[0]),
        "hop1_path_edge_w_mean": float(em[0]),
        "hop1_identity_check": float(em[0] * DECAY),
        "theory_086_hop1": DECAY,
        "global_wbar": wbar,
        "theory_wbar_hop1": wbar,
        "decay_mean": [float(x) for x in dm],
        "path_edge_w_mean": [float(x) for x in em],
        "retention_ratio_of_means": [float(x) for x in ret],
        "weights_in_0_1": bool(float(weights.min()) >= 0 and float(weights.max()) <= 1.0),
        "dp_optimality_note": "w∈[0,1] 且 DECAY<1 ⇒ 更长路径得分必然更低，故「首访层得分=max over "
                              "该层入路」等于「该层全局最优路径」，主体 DP 在本数据上精确；"
                              "若出现 w>1 的边则不再成立，而 report 对 w>1 仅告警不拒收。",
    }


def check_perf(indptr, indices, weights, pool, seed, H, n_perf=50, n_warm=20):
    """性能计时口径：冷启动 vs 预热后；并测 mask/查表构造的额外开销。"""
    rng = np.random.default_rng(seed)
    srcs = rng.choice(pool, size=min(n_perf, len(pool)), replace=False).astype(np.int64)
    cold = np.empty(len(srcs))
    for i, s in enumerate(srcs):
        t0 = time.perf_counter(); bfs_np(indptr, indices, weights, int(s), H, want_scores=False)
        cold[i] = (time.perf_counter() - t0) * 1000
    for _ in range(n_warm):
        bfs_np(indptr, indices, weights, int(srcs[0]), H, want_scores=False)
    warm = np.empty(len(srcs))
    for i, s in enumerate(srcs):
        t0 = time.perf_counter(); bfs_np(indptr, indices, weights, int(s), H, want_scores=False)
        warm[i] = (time.perf_counter() - t0) * 1000
    return {"cold_p50": float(np.percentile(cold, 50)), "cold_p95": float(np.percentile(cold, 95)),
            "warm_p50": float(np.percentile(warm, 50)), "warm_p95": float(np.percentile(warm, 95)),
            "cold_first_ms": float(cold[0]),
            "note": "主体计时无 warm-up 且只计 BFS，不计簇掩码/父节点查表构造；"
                    "实际每样本 additionally 构造 lookup(n float32) 与布尔掩码。"}


def check_json_fields(rep_path):
    rep = json.load(open(rep_path, encoding="utf-8"))
    keys = sorted(rep.keys())
    cov = rep["coverage"]
    per_hop = cov["per_hop"]
    issues = []
    d = rep["definitions"]["coverage"]
    if "源点" not in d or "排除" not in d:
        issues.append("definitions.coverage 未写明「源点不计入分子」——字面「可达节点」会把源点算作可达")
    if not any("源点" in str(v) for v in cov["denominators"].values()):
        issues.append("coverage.denominators 四条均未提源点处理")
    if cov["final"]["gate"] == cov["final_union"]["gate"]:
        issues.append("final_union 沿用同一 0.90 门槛，但②分母(|簇∪类目|)量级不同，门槛不可比")
    hn = rep["decay"]["per_hop"]
    if any(x["score_mean"] != x["score_mean"] for x in hn if x["score_mean"] is not None):
        issues.append("decay 逐跳 score_mean 出现 NaN")
    if rep["config"]["samples"] != cov["samples"]:
        issues.append("config.samples 与 coverage.samples 不一致")
    nulls = [p["hop"] for p in hn if p["score_mean"] is None]
    return {"top_level_keys": keys, "definitions_coverage": d,
            "denominators": cov["denominators"],
            "final": cov["final"], "final_union": cov["final_union"],
            "final_undirected": cov["final_undirected"],
            "saturated_hops_null": nulls,
            "issues": issues,
            "sampling_fields": {k: cov[k] for k in ("samples", "source_type", "pool_size",
                                                    "dropped_no_cluster")},
            "connectivity": rep["connectivity"], "performance": rep["performance"],
            "cls_code": cov.get("cls_code")}


def check_sampling_entanglement(pool, seed=REPORT_SEED):
    """--samples 改变会移动 RNG 流，从而改变 perf 样本（同一 seed 下不可独立复现）。"""
    a1 = np.random.default_rng(seed); a1.choice(pool, size=400, replace=False)
    perf_a = a1.choice(pool, size=50, replace=False)
    a2 = np.random.default_rng(seed); a2.choice(pool, size=100, replace=False)
    perf_b = a2.choice(pool, size=50, replace=False)
    return {"perf_same_after_samples_400_vs_100": bool(np.array_equal(perf_a, perf_b)),
            "overlap_frac": float(len(np.intersect1d(perf_a, perf_b)) / 50.0)}


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(_HERE, "audit-results.json"))
    ap.add_argument("--cross-check", type=int, default=8)
    args = ap.parse_args()

    t_all = time.time()
    nodes_p = os.path.join(TOPICS, "nodes.json")
    cur_p = os.path.join(TOPICS, "edges.csr.npz")
    pre_p = os.path.join(TOPICS, "edges.csr.pre-r1.npz")
    rep_p = os.path.join(TOPICS, "topics-report.json")

    hr("[0] 载入数据（只读）")
    n, cluster, types, cls_code = load_nodes(nodes_p)
    members = Counter(int(c) for c in cluster if int(c) >= 0)
    ip, ix, w = load_csr(cur_p)
    print(f"n={n} nnz={len(ix)} clusters={len(members)} wbar={w.mean():.6f}")
    print(f"TOPICS={TOPICS}")

    uip, uix, uw = build_undirected(ip, ix, w, n)
    print(f"无向（独立构造）nnz={len(uix)}")

    pool_all = np.flatnonzero(types == "kw")
    pool = pool_all[cluster[pool_all] >= 0]
    print(f"pool(kw, cluster>=0)={len(pool)}  dropped(cluster<0)={len(pool_all)-len(pool)}")

    rng = np.random.default_rng(REPORT_SEED)
    srcs400 = rng.choice(pool, size=min(REPORT_SAMPLES, len(pool)), replace=False).astype(np.int64)
    rng_i = np.random.default_rng(20260918)
    srcs100 = rng_i.choice(pool, size=100, replace=False).astype(np.int64)

    # ---- 交叉校验：三条独立 BFS 路径必须给出相同 levels ----
    hr("[1] BFS 层语义交叉校验（自研 numpy / 纯 Python / scipy）")
    adj = [[int(v) for v in ix[ip[u]:ip[u + 1]]] for u in range(n)]
    ok_py = ok_sp = True
    for s in srcs400[:args.cross_check]:
        lv_np, _, _ = bfs_np(ip, ix, w, int(s), REPORT_HOPS, want_scores=False)
        set_np = [set(x.tolist()) for x in lv_np]
        set_py = [set(x) for x in bfs_py(adj, int(s), REPORT_HOPS)[:REPORT_HOPS]]
        while len(set_py) < REPORT_HOPS:
            set_py.append(set())
        set_sp = [set(x.tolist()) for x in bfs_levels_scipy(ip, ix, int(s), REPORT_HOPS, n)]
        ok_py &= (set_np == set_py)
        ok_sp &= (set_np == set_sp)
    print(f"自研 numpy == 纯 Python : {ok_py}")
    print(f"自研 numpy == scipy BFS : {ok_sp}")
    R["bfs_crosscheck"] = {"n_sources": args.cross_check, "match_pure_python": bool(ok_py),
                           "match_scipy": bool(ok_sp)}

    # 源点确实不在任何 level（复算主体「分子排除源点」的事实）
    s0 = int(srcs400[0])
    lv0, _, _ = bfs_np(ip, ix, w, s0, REPORT_HOPS, want_scores=False)
    src_in_levels = any(s0 in set(x.tolist()) for x in lv0 if x.size)
    R["source_in_levels"] = {"src": s0, "appears_in_any_level": bool(src_in_levels)}

    # ---- 衰减 DP 纯 Python 校验 ----
    adjw = [[(int(ix[e]), float(w[e])) for e in range(ip[u], ip[u + 1])] for u in range(n)]
    lev_py, sc_py = bfs_scores_py(adjw, s0, 3)
    _, sc_np, _ = bfs_np(ip, ix, w, s0, 3)
    dev = max(float(np.max(np.abs(sc_np[h] - sc_py[h]))) for h in range(3) if len(sc_py[h]))
    R["decay_dp_crosscheck"] = {"max_abs_dev": dev, "ok": dev < 1e-9}
    print(f"衰减 DP 纯 Python vs numpy 最大偏差: {dev:.3e}")

    # ---- A. 独立复算 ----
    hr("[2] 独立复算：当前边表 / 400 源点(seed=42)  —— 对齐 topics-report.json")
    cur400, acc_cur, ceil_cur = run_calibers(
        "current_400_seed42", ip, ix, w, uip, uix, uw, cluster, cls_code, members,
        srcs400, REPORT_HOPS)
    R["reproduce_current_400"] = cur400
    rep = json.load(open(rep_p, encoding="utf-8"))
    repc = rep["coverage"]
    rep_final = {"c1": repc["final"]["coverage_mean"], "c2": repc["final_union"]["coverage_mean"],
                 "c3": repc["final_undirected"]["coverage_mean"]}
    mine = {"c1": cur400["V0"]["c1"]["final_mean"], "c2": cur400["V0"]["c2"]["final_mean"],
            "c3": cur400["V0"]["c3"]["final_mean"]}
    R["vs_report_400"] = {k: {"report": rep_final[k], "audit": mine[k],
                              "abs_diff": abs(rep_final[k] - mine[k])} for k in mine}
    for k in ("c1", "c2", "c3"):
        print(f"  [{k}] report={rep_final[k]:.10f}  audit={mine[k]:.10f}  "
              f"diff={abs(rep_final[k]-mine[k]):.2e}")
    ph = repc["per_hop"]
    R["vs_report_perhop"] = {
        "c1_mean_max_abs_diff": max(abs(ph[h]["coverage_mean"] - cur400["V0"]["c1"]["mean"][h])
                                    for h in range(REPORT_HOPS)),
        "c2_mean_max_abs_diff": max(abs(ph[h]["union_coverage_mean"] - cur400["V0"]["c2"]["mean"][h])
                                    for h in range(REPORT_HOPS)),
        "c3_mean_max_abs_diff": max(abs(ph[h]["undirected_coverage_mean"] - cur400["V0"]["c3"]["mean"][h])
                                    for h in range(REPORT_HOPS)),
        "share_mean_max_abs_diff": max(abs(ph[h]["same_cluster_share_mean"] - cur400["V0"]["share"]["mean"][h])
                                       for h in range(REPORT_HOPS)),
        "reach_mean_max_abs_diff": max(abs(ph[h]["reach_mean"]
                                           - cur400["reach_mean_per_hop"][h])
                                       for h in range(REPORT_HOPS)),
    }
    print(f"  逐跳最大绝对偏差: ①{ R['vs_report_perhop']['c1_mean_max_abs_diff']:.2e} "
          f"②{R['vs_report_perhop']['c2_mean_max_abs_diff']:.2e} "
          f"③{R['vs_report_perhop']['c3_mean_max_abs_diff']:.2e} "
          f"次口径{R['vs_report_perhop']['share_mean_max_abs_diff']:.2e}")
    print(f"  V1 源点计入分子: ① {cur400['V1']['c1']['final_mean']:.6f} "
          f"② {cur400['V1']['c2']['final_mean']:.6f} ③ {cur400['V1']['c3']['final_mean']:.6f}")
    print(f"  V2 源点出分母  : ① {cur400['V2']['c1']['final_mean']:.6f} "
          f"② {cur400['V2']['c2']['final_mean']:.6f} ③ {cur400['V2']['c3']['final_mean']:.6f}")
    print(f"  V0 下满覆盖理论上限 mean((csize-1)/csize) = {cur400['ceiling_mean_V0']:.6f}")

    hr("[3] 独立 100 源点（seed=20260918，独立实现）")
    ind100, acc_i, ceil_i = run_calibers(
        "independent_100_seed20260918", ip, ix, w, uip, uix, uw, cluster, cls_code, members,
        srcs100, REPORT_HOPS)
    R["reproduce_independent_100"] = ind100
    print(f"  100 源点 V0: ① {ind100['V0']['c1']['final_mean']:.6f} "
          f"② {ind100['V0']['c2']['final_mean']:.6f} ③ {ind100['V0']['c3']['final_mean']:.6f}")
    print(f"  100 源点 V1: ① {ind100['V1']['c1']['final_mean']:.6f} "
          f"② {ind100['V1']['c2']['final_mean']:.6f} ③ {ind100['V1']['c3']['final_mean']:.6f}")
    # 报告自身 400 的前 100 源点（同口径，检验抽样波动）
    first100 = acc_cur["V0"]["c1"][:100].mean(axis=0)[REPORT_HOPS - 1]
    R["sampling_dispersion"] = {
        "report400_first100_c1": float(first100),
        "independent100_c1": ind100["V0"]["c1"]["final_mean"],
        "abs_gap": abs(float(first100) - ind100["V0"]["c1"]["final_mean"]),
        "V1_gap_400_vs_100": abs(cur400["V1"]["c1"]["final_mean"]
                                  - ind100["V1"]["c1"]["final_mean"]),
    }
    print(f"  报告 400 中前 100 源点 ①={first100:.6f} vs 独立 100 源点 ①="
          f"{ind100['V0']['c1']['final_mean']:.6f}")

    hr("[3b] 抽样框对比：节点均匀(topics_report) vs 簇均匀(graph_report)")
    cu = run_cluster_uniform_frame(ip, ix, w, uip, uix, uw, cluster, cls_code,
                                   members, pool, REPORT_HOPS)
    R["sampling_frame"] = {
        "node_uniform": {"samples": cur400["samples"],
                         "V0_c1": cur400["V0"]["c1"]["final_mean"],
                         "V1_c1": cur400["V1"]["c1"]["final_mean"],
                         "ceiling_V0": cur400["ceiling_mean_V0"],
                         "mean_1_over_csize": 1.0 - cur400["ceiling_mean_V0"]},
        "cluster_uniform": {"samples": cu.get("samples"),
                            "V0_c1": cu["V0"]["c1"]["final_mean"],
                            "V1_c1": cu["V1"]["c1"]["final_mean"],
                            "ceiling_V0": cu["ceiling_mean_V0"],
                            "mean_1_over_csize": 1.0 - cu["ceiling_mean_V0"],
                            "clusters_skipped_no_kw": cu.get("clusters_skipped_no_kw")},
    }
    print(f"  节点均匀框: n={cur400['samples']} V0①={cur400['V0']['c1']['final_mean']:.6f} "
          f"V1①={cur400['V1']['c1']['final_mean']:.6f} 上限={cur400['ceiling_mean_V0']:.6f}")
    print(f"  簇均匀框  : n={cu.get('samples')} V0①={cu['V0']['c1']['final_mean']:.6f} "
          f"V1①={cu['V1']['c1']['final_mean']:.6f} 上限={cu['ceiling_mean_V0']:.6f} "
          f"(跳过无 kw 的簇 {cu.get('clusters_skipped_no_kw')})")
    print(f"  ⇒ 同一张图、同一集定义，仅换抽样框 V0① 相差 "
          f"{abs(cur400['V0']['c1']['final_mean']-cu['V0']['c1']['final_mean'])*100:.2f}pp")

    hr("[4] 陈旧口径溯源：pre-R1 边表")
    if os.path.exists(pre_p):
        ip2, ix2, w2 = load_csr(pre_p)
        uip2, uix2, uw2 = build_undirected(ip2, ix2, w2, n)
        pre400, _, ceil_pre = run_calibers(
            "pre_r1_400_seed42", ip2, ix2, w2, uip2, uix2, uw2, cluster, cls_code, members,
            srcs400, REPORT_HOPS)
        R["reproduce_pre_r1_400"] = pre400
        print(f"  pre-R1 V0: ① {pre400['V0']['c1']['final_mean']:.10f} "
              f"② {pre400['V0']['c2']['final_mean']:.10f} ③ {pre400['V0']['c3']['final_mean']:.10f}")
        print(f"  pre-R1 V1: ① {pre400['V1']['c1']['final_mean']:.6f}")
        print(f"  README/acceptance 记载: ① 0.897210909202034 ② 0.9796500966591521 ③ 0.9200401344574874")
        R["stale_provenance"] = {
            "pre_r1_c1": pre400["V0"]["c1"]["final_mean"],
            "pre_r1_c2": pre400["V0"]["c2"]["final_mean"],
            "pre_r1_c3": pre400["V0"]["c3"]["final_mean"],
            "pre_r1_c1_V1": pre400["V1"]["c1"]["final_mean"],
            "documented_c1": 0.897210909202034,
            "documented_c2": 0.9796500966591521,
            "documented_c3": 0.9200401344574874,
            "matches_documented": bool(abs(pre400["V0"]["c1"]["final_mean"]
                                           - 0.897210909202034) < 1e-9),
        }
    else:
        R["stale_provenance"] = {"error": "pre-r1 边表不存在"}

    # ---- C. 结构检查 ----
    hr("[5] 连通分量（并查集 vs scipy）")
    conn = check_connectivity(ip, ix, n, cluster)
    R["connectivity"] = conn
    print(json.dumps(conn, ensure_ascii=False, indent=2)[:900])

    from scipy.sparse.csgraph import connected_components
    from scipy.sparse import csr_matrix
    A = csr_matrix((np.ones(len(ix), dtype=np.int8), ix, ip), shape=(n, n))
    _, cc_sp = connected_components(A + A.T, directed=False)
    sizes_sp = np.bincount(cc_sp)

    hr("[6] 口径③ 是否真的是「闭包」：H 跳内无向饱和率")
    sat = check_closure_saturation(uip, uix, uw, cc_sp, sizes_sp, cluster, members,
                                   srcs400, REPORT_HOPS)
    R["closure_saturation"] = sat
    print(json.dumps(sat, ensure_ascii=False, indent=2))

    hr("[7] 衰减计算语义")
    dec = check_decay(ip, ix, w, srcs400, REPORT_HOPS)
    R["decay"] = dec
    print(f"  hop1 得分 {dec['hop1_mean_score']:.6f} = 最优路平均边权 "
          f"{dec['hop1_path_edge_w_mean']:.6f} × 0.86 = {dec['hop1_identity_check']:.6f}")
    print(f"  report decay.per_hop[0]: score_mean={rep['decay']['per_hop'][0]['score_mean']:.6f} "
          f"path_edge_weight_mean={rep['decay']['per_hop'][0]['path_edge_weight_mean']:.6f}")
    R["decay"]["vs_report"] = {
        "audit_hop1_score": dec["hop1_mean_score"],
        "report_hop1_score": rep["decay"]["per_hop"][0]["score_mean"],
        "audit_hop1_path_w": dec["hop1_path_edge_w_mean"],
        "report_hop1_path_w": rep["decay"]["per_hop"][0]["path_edge_weight_mean"],
        "hop3_score_audit": dec["decay_mean"][2], "hop3_score_report": rep["decay"]["hop3_mean"]}
    print(f"  global wbar={dec['global_wbar']:.6f} (report {rep['decay']['mean_edge_weight_global']:.6f})")
    print(f"  retention(ratio-of-means)[1..3] = {dec['retention_ratio_of_means'][1:4]}")

    hr("[8] 性能计时口径")
    perf = check_perf(ip, ix, w, pool, REPORT_SEED, REPORT_HOPS)
    R["performance"] = {"audit": perf, "report": rep["performance"]}
    print(json.dumps(perf, ensure_ascii=False, indent=2))

    hr("[9] --json 字段与抽样品鉴")
    jf = check_json_fields(rep_p)
    ent = check_sampling_entanglement(pool)
    R["json_fields"] = jf
    R["sampling_entanglement"] = ent
    print(f"  top-level keys: {jf['top_level_keys']}")
    print(f"  issues: {jf['issues']}")
    print(f"  saturated hops (null): {jf['saturated_hops_null']}")
    print(f"  perf 样本随 --samples 变化: {ent}")

    R["meta"] = {"topics_dir": TOPICS, "report_hops": REPORT_HOPS, "report_seed": REPORT_SEED,
                 "decay": DECAY, "wall_seconds": round(time.time() - t_all, 1)}
    out = os.path.abspath(args.json)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2, default=float)
    print(f"\n[写出] {out}  总耗时 {R['meta']['wall_seconds']}s")


if __name__ == "__main__":
    main()
