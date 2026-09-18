#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topics_report.py — 图书馆主题图（GraphRAG-lite）P3 图验收报告

口径**对齐** graph_report.py（P0 文档图报告），仅把"节点域"从 188.5k 文档换成
5,187 主题节点、"簇"从 clusters.npy 换成 nodes.json 的 cluster 字段：

  1. 基础统计：节点数 / 边数 / 平均出度 / 出度分布(min,median,p90,max) /
     权重分布(min,median,mean,p90,max) / 权重为 0、为 1 的比例 / 节点类型分布(kw/cls)
  2. 12 跳覆盖曲线：随机抽样源点做 ≤N 跳有向 BFS（沿出边），逐跳统计
     「已覆盖节点中与源点**同簇**的比例」，同簇 = nodes.json 的 cluster 字段相等；
     源点 cluster = -1 的样本**丢弃并单列计数**（不参与均值，避免污染口径）
  3. 连通性：边视为无向，连通分量数 + 最大分量节点数及占比（与 graph_report 同法）
  4. 衰减：沿 BFS 路径累乘  w_hop = w_parent × edge_w × 0.86
     （交接文档 §3.4 定义的扩散规则；每个新节点取其**入边中得分最大的路径**，
      即逐层乘性最优路径），与理论线 0.86^hop 及可选随机基线对照
  5. 性能：12 跳加权 BFS 单查询计时（p50/p95/max 毫秒）+ 达标判定（<1s，理想 <300ms）

CSR 规格断言（与 P2/Part C1 对齐的硬要求）：
  indptr  int64 (n+1)   indices  int32   weights  float32
  dtype 不符 → 明确报错退出；结构/取值异常（出度>20、权重越界）→ 告警并计数。

用法：
  python3 topics_report.py                                   # 读 <out>/edges.csr.npz，人类可读表
  python3 topics_report.py --samples 400 --seed 42
  python3 topics_report.py --json --json-out topics/topics-report.json
  python3 topics_report.py --mock                            # 边表未就绪时的内存 mock 冒烟（不落盘）
  python3 topics_report.py --edges /tmp/mock/edges.csr.npz   # 指定外部边表路径

只读数据目录既有文件；仅在显式给出 --txt-out/--json-out 时写出报告文件。
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

# 衰减系数：对齐交接文档 §3.4「w_hop = w_parent × edge_w × 0.86」
DECAY = 0.86
# 12 跳覆盖硬门槛（交接文档 §4 P3 验收）
COVERAGE_GATE = 0.90


def resolve_data(args):
    return os.path.abspath(os.path.expanduser(
        getattr(args, "data", None) or os.environ.get("LIB_CATALOG_DATA") or DATA_DEFAULT))


def resolve_out(args, data_dir):
    return os.path.abspath(os.path.expanduser(
        getattr(args, "out", None) or os.path.join(data_dir, "topics")))


# --------------------------------------------------------------------------
# 载入：主题节点表
# --------------------------------------------------------------------------
def load_nodes(path):
    """读取 topics/nodes.json，返回 (n, cluster[int32], type[str 数组], term[list])。"""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list) or not raw:
        raise SystemExit(f"[ERR] {path} 不是非空 JSON 数组")
    n = len(raw)
    cluster = np.full(n, -1, dtype=np.int32)
    types = []
    terms = []
    ids = np.full(n, -1, dtype=np.int64)
    for k, node in enumerate(raw):
        try:
            i = int(node["id"])
        except (KeyError, TypeError, ValueError):
            raise SystemExit(f"[ERR] {path} 第 {k} 项缺 id 字段")
        if not (0 <= i < n):
            raise SystemExit(f"[ERR] {path} 第 {k} 项 id={i} 越界（期望 0..{n - 1}）")
        ids[k] = i
        c = node.get("cluster", -1)
        cluster[k] = int(c) if c is not None else -1
        types.append(str(node.get("type", "?")))
        terms.append(str(node.get("term", "")))
    if len(set(ids.tolist())) != n:
        raise SystemExit(f"[ERR] {path} 的 id 字段存在重复")
    if not np.array_equal(ids, np.arange(n, dtype=np.int64)):
        # id 非 0..n-1 顺序排列：按 id 重排，保证数组下标 == 节点 id
        order = np.argsort(ids, kind="stable")
        cluster = cluster[order]
        types = [types[i] for i in order]
        terms = [terms[i] for i in order]
    return n, cluster, np.array(types, dtype=object), terms


# --------------------------------------------------------------------------
# 载入：CSR 边表（含硬断言）
# --------------------------------------------------------------------------
DTYPE_SPEC = {"indptr": np.int64, "indices": np.int32, "weights": np.float32}


def load_csr(path, n, label):
    """读取 CSR 边表并做 dtype/结构断言。返回 (indptr, indices, weights, checks)。"""
    if not os.path.exists(path):
        raise SystemExit(
            f"[ERR] 边表不存在: {path}\n"
            f"      若 P2 尚未产出 edges.csr.npz，请先跑冒烟：--mock（内存 mock，不落盘），\n"
            f"      或 --edges <外部 mock 路径>；待 P2 完成后可直接全量跑。")
    with np.load(path) as z:
        keys = set(z.files)
        missing = [k for k in DTYPE_SPEC if k not in keys]
        if missing:
            raise SystemExit(f"[ERR] {path} 缺数组键: {missing}（现有键: {sorted(keys)}）")
        indptr = z["indptr"]
        indices = z["indices"]
        weights = z["weights"]

    checks = []
    bad = []
    for key, arr in (("indptr", indptr), ("indices", indices), ("weights", weights)):
        want = DTYPE_SPEC[key]
        if arr.dtype != want:
            bad.append(f"{key}: dtype={arr.dtype}，期望 {np.dtype(want)}")
        else:
            checks.append(f"{key} {arr.dtype} OK")
    if bad:
        raise SystemExit(
            f"[ERR] {label} dtype 断言失败（与 P2/Part C1 规格不符）:\n  - " + "\n  - ".join(bad))

    indptr = np.ascontiguousarray(indptr, dtype=np.int64)
    indices = np.ascontiguousarray(indices, dtype=np.int32)
    weights = np.ascontiguousarray(weights, dtype=np.float32)

    if indptr.shape[0] != n + 1:
        raise SystemExit(f"[ERR] {label} indptr 长度 {indptr.shape[0]}，期望 n+1={n + 1}")
    if int(indptr[0]) != 0:
        raise SystemExit(f"[ERR] {label} indptr[0]={int(indptr[0])}，期望 0")
    if int(indptr[-1]) != len(indices):
        raise SystemExit(
            f"[ERR] {label} indptr[-1]={int(indptr[-1])} != len(indices)={len(indices)}")
    if len(indices) != len(weights):
        raise SystemExit(f"[ERR] {label} indices({len(indices)}) 与 weights({len(weights)}) 长度不等")
    if np.any(np.diff(indptr) < 0):
        raise SystemExit(f"[ERR] {label} indptr 非单调不减")
    if len(indices) and (indices.min() < 0 or indices.max() >= n):
        raise SystemExit(
            f"[ERR] {label} indices 越界: [{int(indices.min())}, {int(indices.max())}] vs n={n}")
    checks.append(f"结构 OK（n={n:,}, nnz={len(indices):,}）")
    return indptr, indices, weights, checks


def synth_mock_csr_v2(n, cluster, types, terms, node_cls, seed, max_outdeg=20):
    """边表未就绪时合成同规格 mock CSR（纯内存，绝不写数据目录）。

    模拟 P2 设计：① 共现边（簇内有偏，~75% 同簇）② 层级边 kw→cls（w=1.0，单向）
    ③ top-20 截断 ④ 权重归一到 [0,1]。dtype/shape/出度上界与真实边表一致。
    """
    rng = np.random.default_rng(seed)
    kw_ids = np.flatnonzero(types == "kw")
    cls_by_code = {}
    for i in np.flatnonzero(types == "cls"):
        cls_by_code.setdefault(terms[int(i)], int(i))
    by_cluster = {}
    for i in kw_ids:
        c = int(cluster[i])
        if c >= 0:
            by_cluster.setdefault(c, []).append(int(i))

    indptr = np.zeros(n + 1, dtype=np.int64)
    idx_out, w_out = [], []
    for u in range(n):
        out = []
        if types[u] == "kw":
            # 出度 ~ lognormal(2.1, 0.6)（中位 ~8、均值 ~10），截断到 [1, max_outdeg-1]
            deg = int(np.clip(round(float(rng.lognormal(2.1, 0.6))), 1, max_outdeg - 1))
            c = int(cluster[u])
            seen = {int(u)}
            for _ in range(deg * 2):  # 多试几次以补足去重后的度
                if len(out) >= deg:
                    break
                if c >= 0 and rng.random() < 0.75 and len(by_cluster.get(c, ())) > 1:
                    pool = by_cluster[c]
                    v = int(pool[int(rng.integers(len(pool)))])
                else:
                    v = int(kw_ids[int(rng.integers(len(kw_ids)))])
                if v in seen:
                    continue
                seen.add(v)
                w = float(rng.uniform(0.05, 1.0)) * (0.3 if cluster[v] == c else 1.0)
                out.append((v, w))
            # 层级边：主题 → cls 类目（w=1.0，单向）
            code = node_cls[u]
            if code and code in cls_by_code:
                tgt = cls_by_code[code]
                if tgt != u and all(v != tgt for v, _ in out):
                    out.append((tgt, 1.0))
        out = sorted(out, key=lambda t: (-t[1], t[0]))[:max_outdeg]
        for v, w in out:
            idx_out.append(v)
            w_out.append(w)
        indptr[u + 1] = indptr[u] + len(out)

    indices = np.array(idx_out, dtype=np.int32)
    weights = np.array(w_out, dtype=np.float32)
    if len(weights):
        wmax = float(weights.max())
        if wmax > 0:
            weights = (weights / np.float32(wmax)).astype(np.float32)
    return indptr, indices, weights


# --------------------------------------------------------------------------
# 图结构：padded 邻接（出度上界小 → 稠密 padding 让逐跳扩展全向量化）
# --------------------------------------------------------------------------
def build_padded(indptr, indices, weights):
    """返回 (NB, WB)：NB (n,D) int32（-1 padding），WB (n,D) float32（padding 0）。"""
    n = len(indptr) - 1
    deg = np.diff(indptr).astype(np.int64)
    D = int(deg.max()) if n else 0
    if D == 0:
        return (np.full((n, 1), -1, np.int32), np.zeros((n, 1), np.float32))
    NB = np.full((n, D), -1, dtype=np.int32)
    WB = np.zeros((n, D), dtype=np.float32)
    for u in range(n):
        a, b = int(indptr[u]), int(indptr[u + 1])
        k = b - a
        if k:
            NB[u, :k] = indices[a:b]
            WB[u, :k] = weights[a:b]
    return NB, WB


def scatter_max(tgt, val, n):
    """按 target 归约最大值，返回 (唯一 target 升序, 对应最大 val, 该最大值的原下标)。

    用 lexsort((val, tgt)) 后取每组末项：组内 val 升序 → 末项即组内最大；
    np.lexsort 稳定排序 → 平局时取输入序靠后者，结果确定。
    """
    if len(tgt) == 0:
        return (np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float32),
                np.empty(0, dtype=np.int64))
    order = np.lexsort((val, tgt))
    ts = tgt[order]
    vs = val[order]
    last = np.empty(len(ts), dtype=bool)
    last[-1] = True
    np.not_equal(ts[1:], ts[:-1], out=last[:-1])
    pos = np.flatnonzero(last)
    return ts[pos], vs[pos], order[pos]


def weighted_bfs(src, hops, NB, WB, visited, decay=DECAY):
    """逐跳有向加权 BFS。返回 (levels, scores, parents)：
      levels[h-1]  = 第 h 跳**新增**节点 id 数组（拓扑口径，与 graph_report.bfs_levels 等价）
      scores[h-1]  = 对应节点的路径得分（w_hop = w_parent × edge_w × decay 的逐层最优路径）
      parents[h-1] = 最优路径上的父节点 id（=-1 表示该节点即源点）

    逐跳扩展全向量化：frontier → NB[frontier] → 掩掉已访问 → scatter_max 取最优入路。
    """
    n = NB.shape[0]
    visited[:] = False
    visited[src] = True
    frontier = np.array([src], dtype=np.int64)
    fs = np.ones(1, dtype=np.float32)
    levels, scores, pars = [], [], []
    for _ in range(hops):
        if frontier.size == 0:
            levels.append(np.empty(0, dtype=np.int64))
            scores.append(np.empty(0, dtype=np.float32))
            pars.append(np.empty(0, dtype=np.int64))
            continue
        nb = NB[frontier]                       # (f, D)
        ok = nb >= 0
        if not ok.any():
            levels.append(np.empty(0, dtype=np.int64))
            scores.append(np.empty(0, dtype=np.float32))
            pars.append(np.empty(0, dtype=np.int64))
            frontier = np.empty(0, dtype=np.int64)
            continue
        D = NB.shape[1]
        flat_ok = ok.ravel()
        tgt = nb[ok].astype(np.int64)
        par_s = np.repeat(fs, D)[flat_ok]
        par_id = np.repeat(frontier, D)[flat_ok]
        ew = WB[frontier][ok]
        keep = ~visited[tgt]
        tgt = tgt[keep]
        cand = (par_s[keep] * ew[keep] * np.float32(decay)).astype(np.float32)
        tn, tv, tpos = scatter_max(tgt, cand, n)
        if tn.size == 0:
            levels.append(np.empty(0, dtype=np.int64))
            scores.append(np.empty(0, dtype=np.float32))
            pars.append(np.empty(0, dtype=np.int64))
            frontier = np.empty(0, dtype=np.int64)
            continue
        visited[tn] = True
        levels.append(tn)
        scores.append(tv)
        pars.append(par_id[keep][tpos])
        frontier = tn
        fs = tv
    return levels, scores, pars


def random_walk_decay(src, hops, indptr, indices, weights, rng, n, decay=DECAY):
    """随机基线：沿随机出边游走 hops 步，累乘 edge_w × decay（无去重、无最优路径）。"""
    cur = int(src)
    s = 1.0
    out = np.empty(hops, dtype=np.float32)
    for h in range(hops):
        a, b = int(indptr[cur]), int(indptr[cur + 1])
        if b > a:
            e = a + int(rng.integers(b - a))
            s *= float(weights[e]) * decay
            cur = int(indices[e])
        else:
            cur = int(rng.integers(n))    # 死端 → 重新随机跳（基线语义：无结构可依）
            s *= decay
        out[h] = s
    return out


# --------------------------------------------------------------------------
# 统计小工具
# --------------------------------------------------------------------------
def json_safe(o):
    """递归把非有限浮点（NaN/Inf）转成 None —— json.dump 会写出裸 NaN，不是合法 JSON。"""
    if isinstance(o, dict):
        return {k: json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [json_safe(v) for v in o]
    if isinstance(o, (float, np.floating)):
        v = float(o)
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def pct_stats(arr):
    if len(arr) == 0:
        return {"min": 0.0, "median": 0.0, "mean": 0.0, "p90": 0.0, "max": 0.0}
    a = np.asarray(arr, dtype=np.float64)
    return {"min": float(a.min()), "median": float(np.median(a)),
            "mean": float(a.mean()), "p90": float(np.percentile(a, 90)), "max": float(a.max())}


def fmt_stats(s, nd=3):
    return (f"min {s['min']:.{nd}f} / 中位 {s['median']:.{nd}f} / 均 {s['mean']:.{nd}f} / "
            f"p90 {s['p90']:.{nd}f} / max {s['max']:.{nd}f}")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="主题图（GraphRAG-lite）P3 质量报告")
    ap.add_argument("--data", default=None, help="数据目录（默认 ~/go/lib-catalog-data）")
    ap.add_argument("--out", default=None, help="主题图产物目录（默认 <data>/topics）")
    ap.add_argument("--edges", default=None, help="边表路径（默认 <out>/edges.csr.npz）")
    ap.add_argument("--mock", action="store_true",
                    help="边表未就绪时用内存 mock CSR 冒烟（同 dtype/shape/出度上界；绝不落盘）")
    ap.add_argument("--samples", type=int, default=400, help="覆盖曲线抽样源点数（默认 400）")
    ap.add_argument("--hops", type=int, default=12, help="BFS 跳数上限（默认 12）")
    ap.add_argument("--seed", type=int, default=42, help="随机种子（默认 42，确定性）")
    ap.add_argument("--source-type", choices=["kw", "all"], default="kw",
                    help="源点类型（默认 kw）")
    ap.add_argument("--perf-samples", type=int, default=50, help="单查询计时样本数（默认 50）")
    ap.add_argument("--random-baseline", action="store_true", help="额外计算随机游走基线")
    ap.add_argument("--max-outdeg", type=int, default=20, help="出度上界（超标仅告警，默认 20）")
    ap.add_argument("--json", action="store_true", help="stdout 输出结构化 JSON（替代人类可读表）")
    ap.add_argument("--json-out", default=None, help="JSON 结果写出路径")
    ap.add_argument("--txt-out", default=None, help="人类可读表写出路径")
    args = ap.parse_args()

    t_start = time.time()
    D = resolve_data(args)
    OUT = resolve_out(args, D)
    nodes_path = os.path.join(OUT, "nodes.json")
    edges_path = os.path.abspath(os.path.expanduser(args.edges)) if args.edges \
        else os.path.join(OUT, "edges.csr.npz")
    if not os.path.exists(nodes_path):
        raise SystemExit(f"[ERR] 主题节点表不存在: {nodes_path}")

    n, cluster, types, terms = load_nodes(nodes_path)
    node_cls = np.array([""] * n, dtype=object)
    with open(nodes_path, encoding="utf-8") as f:
        for node in json.load(f):
            node_cls[int(node["id"])] = str(node.get("cls", "") or "")
    # 同类目口径（§4-P3「主簇或分类」）需要按 CLC 码分组
    cls_code = np.array([str(x or "") for x in node_cls], dtype=object)
    cls_code_cnt = Counter(c for c in cls_code.tolist() if c)
    n_cls_code = len(cls_code_cnt)

    # ---- 载入边表（或 mock） ----
    if args.mock:
        if os.path.exists(edges_path):
            print(f"[WARN] --mock 已指定，忽略真实边表 {edges_path}", file=sys.stderr)
        indptr, indices, weights = synth_mock_csr_v2(
            n, cluster, types, terms, node_cls, args.seed, args.max_outdeg)
        csr_label = f"MOCK（内存合成, seed={args.seed}）"
        csr_checks = [f"mock dtype OK: indptr {indptr.dtype} / indices {indices.dtype} / "
                      f"weights {weights.dtype}"]
        edges_src = "mock(in-memory)"
    else:
        indptr, indices, weights, csr_checks = load_csr(edges_path, n, "edges.csr.npz")
        csr_label = edges_path
        edges_src = edges_path

    NB, WB = build_padded(indptr, indices, weights)
    maxdeg = NB.shape[1]
    # 无向闭包（口径③）：用于区分"跳数不足"与"结构不可达"
    from scipy import sparse as _sp
    A0 = _sp.csr_matrix((weights, indices, indptr), shape=(n, n))
    U0 = A0.maximum(A0.T).tocsr()
    NBu, WBu = build_padded(U0.indptr.astype(np.int64),
                            U0.indices.astype(np.int32),
                            U0.data.astype(np.float32))

    # ---- 1. 基础统计 ----
    deg = np.diff(indptr).astype(np.int64)
    n_edges = int(len(indices))
    deg_stats = pct_stats(deg)
    deg_stats["min"] = int(deg.min()) if n else 0
    deg_stats["max"] = int(deg.max()) if n else 0
    deg_stats["median"] = int(np.median(deg)) if n else 0
    deg_stats["p90"] = int(np.percentile(deg, 90)) if n else 0
    w_stats = pct_stats(weights)
    zero_ratio = float(np.count_nonzero(weights == 0) / n_edges) if n_edges else 0.0
    one_ratio = float(np.count_nonzero(weights == 1.0) / n_edges) if n_edges else 0.0
    w_lo = int(np.count_nonzero(weights < 0)); w_hi = int(np.count_nonzero(weights > 1.0))
    over_deg = int(np.count_nonzero(deg > args.max_outdeg))
    type_counts = Counter(types.tolist())
    cluster_uniq = sorted(set(int(c) for c in cluster if c >= 0))
    n_no_cluster = int(np.count_nonzero(cluster < 0))

    # ---- 源点池 ----
    if args.source_type == "kw":
        pool_all = np.flatnonzero(types == "kw")
    else:
        pool_all = np.arange(n, dtype=np.int64)
    pool = pool_all[cluster[pool_all] >= 0]                      # 有簇源点（参与覆盖率）
    n_dropped_nocluster = int(len(pool_all) - len(pool))
    rng = np.random.default_rng(args.seed)
    nsamp = int(min(args.samples, len(pool)))
    srcs = rng.choice(pool, size=nsamp, replace=False).astype(np.int64)

    # 簇成员表（同簇覆盖率分母 = 图上同 cluster 字段的节点数，与 graph_report 同法）
    members = {}
    for i in range(n):
        c = int(cluster[i])
        if c >= 0:
            members.setdefault(c, 0)
            members[c] += 1

    # ---- 2/4. 覆盖曲线 + 衰减（一趟 BFS 出两个指标） ----
    H = args.hops
    cov = np.zeros((nsamp, H), dtype=np.float64)      # 主口径: 同簇节点覆盖比例(对齐 graph_report)
    cov_share = np.zeros((nsamp, H), dtype=np.float64)  # 次口径: 可达节点中同簇的占比
    cov_union = np.zeros((nsamp, H), dtype=np.float64)  # 口径②: 同簇∪同类目（§4-P3"主簇或分类"）
    cov_undir = np.zeros((nsamp, H), dtype=np.float64)  # 口径③: 无向闭包下的同簇覆盖
    reach = np.zeros((nsamp, H), dtype=np.int64)      # 累计可达节点数
    hop_nodes_mean = np.zeros(H, dtype=np.float64)    # 每跳新增节点数（均值）
    # 空跳（该跳无新增节点 = 已饱和）记 NaN，不得记 0——否则会把深跳均值拖成假衰减
    decay_score = np.full((nsamp, H), np.nan, dtype=np.float64)
    edge_w_path = np.full((nsamp, H), np.nan, dtype=np.float64)   # 最优路径上的真实边权
    hop_factor = np.full((nsamp, H), np.nan, dtype=np.float64)    # 有效逐跳因子 = 边权 × 0.86
    visited = np.zeros(n, dtype=bool)
    visited_u = np.zeros(n, dtype=bool)

    # 簇 / 类目 布尔掩码缓存（n=5187 很小，按需构造）
    _cmask, _kmask = {}, {}

    def cluster_mask(c):
        m = _cmask.get(c)
        if m is None:
            m = (cluster == c)
            _cmask[c] = m
        return m

    def code_mask(code):
        m = _kmask.get(code)
        if m is None:
            m = (cls_code == code)
            _kmask[code] = m
        return m

    for k, s in enumerate(srcs):
        levels, scores, pars = weighted_bfs(int(s), H, NB, WB, visited)
        c_src = int(cluster[s])
        csize = max(members.get(c_src, 1), 1)
        m_c = cluster_mask(c_src)
        _code = str(cls_code[s] or "")
        if _code:
            m_u = m_c | code_mask(_code)
        else:
            m_u = m_c
        usize = max(int(m_u.sum()), 1)
        cum_reach = 0
        cum_same = 0
        cum_union = 0
        for h in range(H):
            lv = levels[h]
            if lv.size:
                cum_reach += int(lv.size)
                cum_same += int(np.count_nonzero(m_c[lv]))
                cum_union += int(np.count_nonzero(m_u[lv]))
                hop_nodes_mean[h] += lv.size
                # 衰减：该跳新增节点的路径得分均值（乘性最优路径）
                sc = scores[h]
                decay_score[k, h] = float(sc.mean())
                # 最优路径的真实边权 = score_v / (score_parent × 0.86)
                par = pars[h]
                if h == 0:
                    par_s = np.ones_like(sc)          # 首跳父节点即源点，得分 1.0
                else:
                    prev_lv, prev_sc = levels[h - 1], scores[h - 1]
                    lookup = np.zeros(n, dtype=np.float32)
                    if prev_lv.size:
                        lookup[prev_lv] = prev_sc
                    par_s = lookup[np.clip(par, 0, None)]
                den = par_s * np.float32(DECAY)
                ok = den > 0
                if ok.any():
                    ew_t = sc[ok] / den[ok]
                    edge_w_path[k, h] = float(ew_t.mean())
                    hop_factor[k, h] = float(ew_t.mean() * DECAY)
            cov[k, h] = cum_same / csize
            cov_union[k, h] = cum_union / usize
            cov_share[k, h] = (cum_same / cum_reach) if cum_reach else 0.0
            reach[k, h] = cum_reach

        # 口径③：无向闭包 BFS（同簇分母不变，仅把可达域换成无向连通闭包）
        lv_u, _su, _pu = weighted_bfs(int(s), H, NBu, WBu, visited_u)
        cum_u = 0
        cum_u_same = 0
        for h in range(H):
            if lv_u[h].size:
                cum_u += int(lv_u[h].size)
                cum_u_same += int(np.count_nonzero(m_c[lv_u[h]]))
            cov_undir[k, h] = cum_u_same / csize
    hop_nodes_mean /= max(nsamp, 1)

    cov_mean = cov.mean(axis=0)
    cov_med = np.median(cov, axis=0)
    covs_mean = cov_share.mean(axis=0)
    covs_med = np.median(cov_share, axis=0)
    covu_mean = cov_union.mean(axis=0)
    covu_med = np.median(cov_union, axis=0)
    covd_mean = cov_undir.mean(axis=0)
    covd_med = np.median(cov_undir, axis=0)
    reach_mean = reach.mean(axis=0)
    reach_med = np.median(reach, axis=0)
    # 空跳以 NaN 表示 → 用 nanmean/nanmedian，并暴露每跳有效样本数
    valid_cnt = np.array([int(np.count_nonzero(~np.isnan(decay_score[:, h]))) for h in range(H)])
    with np.errstate(invalid="ignore"):
        decay_mean = np.array([np.nanmean(decay_score[:, h]) if valid_cnt[h] else float("nan")
                               for h in range(H)], dtype=np.float64)
        decay_med = np.array([np.nanmedian(decay_score[:, h]) if valid_cnt[h] else float("nan")
                              for h in range(H)], dtype=np.float64)
    # 无有效样本的跳记 NaN（JSON 侧转 null），不得记 0
    ew_mean = np.array([np.nanmean(edge_w_path[:, h]) if valid_cnt[h] else np.nan
                        for h in range(H)], dtype=np.float64)
    hopf_mean = np.array([np.nanmean(hop_factor[:, h]) if valid_cnt[h] else np.nan
                          for h in range(H)], dtype=np.float64)
    retention = np.full(H, np.nan, dtype=np.float64)
    for h in range(1, H):
        if np.isfinite(decay_mean[h]) and np.isfinite(decay_mean[h - 1]) and decay_mean[h - 1] > 0:
            retention[h] = decay_mean[h] / decay_mean[h - 1]
    theory = np.array([DECAY ** h for h in range(1, H + 1)], dtype=np.float64)

    # 第二条参照线：全图平均边权 × 0.86^(hop-1)（即 edge_w 取全图均值的衰减期望）
    wbar = float(weights.mean()) if n_edges else 0.0
    theory_w = np.array([wbar * (DECAY ** (h - 1)) for h in range(1, H + 1)], dtype=np.float64)

    final_cov_mean = float(cov_mean[H - 1]); final_cov_med = float(cov_med[H - 1])
    gate_pass = final_cov_mean >= COVERAGE_GATE

    # 随机基线（可选）
    walk_base = None
    if args.random_baseline:
        m = min(nsamp, 200)
        ws = rng.choice(pool, size=m, replace=False).astype(np.int64)
        acc = np.zeros(H, dtype=np.float64)
        for s in ws:
            acc += random_walk_decay(int(s), H, indptr, indices, weights, rng, n)
        walk_base = acc / max(m, 1)

    # ---- 3. 连通性（无向；与 graph_report 同法） ----
    from scipy import sparse
    from scipy.sparse.csgraph import connected_components
    A = sparse.csr_matrix((np.ones(n_edges, dtype=np.int8), indices, indptr), shape=(n, n))
    ncc, cc = connected_components(A + A.T, directed=False)
    csizes = np.bincount(cc)
    largest = int(csizes.max()) if len(csizes) else 0

    # ---- 5. 性能：12 跳单查询计时 ----
    perf_n = int(min(args.perf_samples, len(pool)))
    perf_srcs = rng.choice(pool, size=perf_n, replace=False).astype(np.int64)
    tim = np.empty(perf_n, dtype=np.float64)
    for i, s in enumerate(perf_srcs):
        t0 = time.perf_counter()
        weighted_bfs(int(s), H, NB, WB, visited)
        tim[i] = (time.perf_counter() - t0) * 1000.0
    p50 = float(np.percentile(tim, 50)); p95 = float(np.percentile(tim, 95)); tmax = float(tim.max())
    perf_verdict = "PASS(<300ms 理想档)" if p95 < 300 else ("PASS(<1s)" if p95 < 1000 else "FAIL(≥1s)")

    wall = time.time() - t_start

    # ---- 结果结构 ----
    result = {
        "stage": "P3",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "data_dir": D, "artifacts_dir": OUT, "edges_source": edges_src,
        "config": {"samples": nsamp, "hops": H, "seed": args.seed,
                   "source_type": args.source_type, "perf_samples": perf_n,
                   "max_outdeg": args.max_outdeg, "random_baseline": bool(args.random_baseline)},
        "definitions": {
            "same_cluster": "源点与目标节点的 nodes.json `cluster` 字段相等（cluster=-1 的源点丢弃并单列）",
            "coverage": "第 h 跳累计同簇覆盖 = |{可达节点 ∩ 同簇节点}| / |同簇节点总数|（图上 cluster 字段成员数）",
            "bfs": "有向出边、逐跳新增（首访即标记）、≤12 跳；levels 集合与 graph_report.bfs_levels 等价",
            "decay": "w_hop = w_parent × edge_w × 0.86；逐层取各节点入边中得分最大的路径（乘性最优）",
            "decay_theory": "0.86^hop（edge_w≡1 的理论线）",
            "connectivity": "边视为无向，scipy connected_components(A + A.T)",
            "csr_spec": "indptr int64(n+1) / indices int32 / weights float32；有向，权重∈[0,1]，每节点出度≤20",
        },
        "csr": {"path": csr_label, "dtype_checks": csr_checks,
                "indptr_dtype": str(indptr.dtype), "indices_dtype": str(indices.dtype),
                "weights_dtype": str(weights.dtype), "n": n, "nnz": n_edges,
                "max_outdeg_observed": int(deg.max()) if n else 0,
                "nodes_over_max_outdeg": over_deg,
                "weights_below_0": w_lo, "weights_above_1": w_hi},
        "nodes": {"count": n, "type_counts": dict(type_counts),
                  "kw": int(type_counts.get("kw", 0)), "cls": int(type_counts.get("cls", 0)),
                  "clusters": len(cluster_uniq), "cluster_minus1": n_no_cluster,
                  "cluster_min": (cluster_uniq[0] if cluster_uniq else -1),
                  "cluster_max": (cluster_uniq[-1] if cluster_uniq else -1)},
        "edges": {"count": n_edges,
                  "avg_outdeg": float(deg.mean()) if n else 0.0,
                  "outdeg": deg_stats,
                  "weights": w_stats,
                  "weight_zero_ratio": zero_ratio, "weight_one_ratio": one_ratio,
                  "weight_mean_global": wbar},
        "coverage": {
            "samples": nsamp, "source_type": args.source_type,
            "pool_size": int(len(pool)), "dropped_no_cluster": n_dropped_nocluster,
            "per_hop": [{"hop": h + 1, "coverage_mean": float(cov_mean[h]),
                         "coverage_median": float(cov_med[h]),
                         "same_cluster_share_mean": float(covs_mean[h]),
                         "same_cluster_share_median": float(covs_med[h]),
                         "union_coverage_mean": float(covu_mean[h]),
                         "union_coverage_median": float(covu_med[h]),
                         "undirected_coverage_mean": float(covd_mean[h]),
                         "undirected_coverage_median": float(covd_med[h]),
                         "reach_mean": float(reach_mean[h]),
                         "reach_median": float(reach_med[h]),
                         "new_nodes_mean": float(hop_nodes_mean[h])} for h in range(H)],
            "final": {"hop": H, "coverage_mean": final_cov_mean,
                      "coverage_median": final_cov_med,
                      "gate": COVERAGE_GATE, "pass": bool(gate_pass)},
            "final_union": {"hop": H, "coverage_mean": float(covu_mean[H - 1]),
                            "coverage_median": float(covu_med[H - 1]),
                            "gate": COVERAGE_GATE,
                            "pass": bool(covu_mean[H - 1] >= COVERAGE_GATE)},
            "final_undirected": {"hop": H, "coverage_mean": float(covd_mean[H - 1]),
                                 "coverage_median": float(covd_med[H - 1]),
                                 "gate": COVERAGE_GATE,
                                 "pass": bool(covd_mean[H - 1] >= COVERAGE_GATE)},
            "denominators": {
                "same_cluster": "同 cluster 字段的节点数（图上）",
                "union": "|cluster==c ∪ cls==C| 的节点数（图上，去重并集）",
                "undirected": "同 cluster 字段的节点数；可达域换为无向连通闭包",
                "same_cluster_share": "可达节点总数（字面口径，不用于门槛）"},
            "cls_code": {"distinct": n_cls_code}
        },
        "connectivity": {"components": int(ncc), "largest_component": largest,
                         "largest_pct": (largest / n if n else 0.0),
                         "singleton_components": int(np.count_nonzero(csizes == 1))},
        "decay": {"decay_factor": DECAY,
                  "per_hop": [{"hop": h + 1, "score_mean": float(decay_mean[h]),
                               "score_median": (float(decay_med[h]) if valid_cnt[h] else None),
                               "samples_with_new_nodes": int(valid_cnt[h]),
                               "retention_vs_prev": float(retention[h]),
                               "path_edge_weight_mean": (float(ew_mean[h])
                                                         if np.isfinite(ew_mean[h]) else None),
                               "effective_hop_factor": (float(hopf_mean[h])
                                                        if np.isfinite(hopf_mean[h]) else None),
                               "theory_086": float(theory[h]),
                               "theory_wbar": float(theory_w[h])} for h in range(H)],
                  "retention_hop2_hop1": (float(retention[1])
                                          if H > 1 and np.isfinite(retention[1]) else None),
                  "samples_with_new_nodes": valid_cnt.tolist(),
                  "mean_edge_weight_global": wbar,
                  "mean_edge_weight_on_best_paths": (float(np.nanmean(ew_mean))
                                                     if np.any(np.isfinite(ew_mean)) else None),
                  "hop1_mean": float(decay_mean[0]),
                  "hop3_mean": (float(decay_mean[min(2, H - 1)])
                                if np.isfinite(decay_mean[min(2, H - 1)]) else None),
                  "random_walk_baseline": (walk_base.tolist() if walk_base is not None else None)},
        "performance": {"hops": H, "samples": perf_n, "p50_ms": p50, "p95_ms": p95,
                        "max_ms": tmax, "mean_ms": float(tim.mean()) if perf_n else 0.0,
                        "target_ms": 1000, "ideal_ms": 300, "verdict": perf_verdict,
                        "pass": bool(p95 < 1000)},
        "wall_seconds": round(wall, 2),
    }

    # ---- 人类可读输出（风格对齐 graph_report.py） ----
    L = []
    add = L.append
    add("=== 主题图质量报告 (P3 / GraphRAG-lite) ===")
    add(f"数据: {D} | 产物: {OUT}")
    add(f"边表: {csr_label}")
    for c in csr_checks:
        add(f"  [CSR] {c}")
    add(f"节点: {n:,}（kw {type_counts.get('kw', 0):,} / cls {type_counts.get('cls', 0):,}）"
        f" | 边: {n_edges:,} | 平均出度: {(deg.mean() if n else 0):.2f}")
    add(f"出度: min {deg_stats['min']} / 中位 {deg_stats['median']} / "
        f"p90 {deg_stats['p90']} / max {deg_stats['max']}"
        + (f"  [告警: {over_deg} 个节点出度 >{args.max_outdeg}]" if over_deg else ""))
    add(f"权重: {fmt_stats(w_stats)}")
    add(f"权重 =0: {np.count_nonzero(weights == 0):,}（{zero_ratio:.2%}） | "
        f"=1: {np.count_nonzero(weights == 1.0):,}（{one_ratio:.2%}）")
    if w_lo or w_hi:
        add(f"  [告警] 权重越界: <0 {w_lo} / >1 {w_hi}")
    add(f"簇: {len(cluster_uniq)} 个（{cluster_uniq[0]}..{cluster_uniq[-1]}）"
        f" | cluster=-1 节点: {n_no_cluster}")

    add("")
    add(f"[12 跳同簇覆盖] {nsamp} 随机源点（type={args.source_type}, seed={args.seed}；"
        f"cluster=-1 源点丢弃 {n_dropped_nocluster}）")
    add("   跳   簇覆盖均   簇覆盖中位  同簇占比均  可达均      可达中位")
    for h in range(H):
        add(f"  {h + 1:>2}   {cov_mean[h]:.4f}    {cov_med[h]:.4f}     "
            f"{covs_mean[h]:.5f}   {reach_mean[h]:>9.1f}  {reach_med[h]:>9.1f}")
    add(f"  {H} 跳最终覆盖率: 均 {final_cov_mean:.4f} / 中位 {final_cov_med:.4f}"
        f"  [门槛 ≥{COVERAGE_GATE:.2f}: {'PASS' if gate_pass else 'FAIL'}]")

    add("")
    add("[覆盖三口径] 同一批源点，三种「域/分母」定义（分母见下方定义）")
    add("   跳   ①同簇-有向   ②同簇∪类目-有向  ③同簇-无向闭包   ①中位   ②中位   ③中位")
    for h in range(H):
        add(f"  {h + 1:>2}   {cov_mean[h]:.4f}       {covu_mean[h]:.4f}          "
            f"{covd_mean[h]:.4f}        {cov_med[h]:.4f}  {covu_med[h]:.4f}  {covd_med[h]:.4f}")
    add(f"  {H} 跳结论:  ① {final_cov_mean:.4f} [{'PASS' if gate_pass else 'FAIL'}]"
        f"   ② {float(covu_mean[H - 1]):.4f} [{'PASS' if covu_mean[H - 1] >= COVERAGE_GATE else 'FAIL'}]"
        f"   ③ {float(covd_mean[H - 1]):.4f} [{'PASS' if covd_mean[H - 1] >= COVERAGE_GATE else 'FAIL'}]")
    add("   分母定义:")
    add("     ① 同簇(主指标, 门槛 ≥0.90): |可达_有向 ∩ {cluster==c}| / |{cluster==c}|")
    add("     ② 同簇∪同类目(§4-P3 原文「主簇或分类」): |可达_有向 ∩ ({cluster==c} ∪ {cls==C})| / |{cluster==c} ∪ {cls==C}|")
    add("     ③ 无向闭包(区分「跳数不足」与「结构不可达」): |可达_无向 ∩ {cluster==c}| / |{cluster==c}|")
    add("     次列 同簇占比(字面口径, 不用于门槛): |可达 ∩ {cluster==c}| / |可达|")
    add("   读法: ①≈③ 且均 <0.90 → 结构不可达(孤立/弱连通簇), 加跳数无用;")
    add("         ① << ③ → 跳数/出度不足, 有优化空间。")

    add("")
    add(f"[连通性] 无向分量: {ncc} 个；最大 {largest:,}（{largest / n:.2%}）"
        f" | 单点分量 {int(np.count_nonzero(csizes == 1))}")

    add("")
    add(f"[衰减] w_hop = w_parent × edge_w × {DECAY}（逐层乘性最优路径）")
    add("   跳   平均得分    最优路平均边权  有效逐跳因子  理论0.86^hop  w̄×0.86^(hop-1)"
        + ("   随机游走基线" if walk_base is not None else ""))
    for h in range(H):
        if not np.isfinite(decay_mean[h]):
            line = (f"  {h + 1:>2}   {'—(已饱和)':<10}  {'—':<12}  {'—':<10}     "
                    f"{theory[h]:.4f}       {theory_w[h]:.4f}")
        else:
            line = (f"  {h + 1:>2}   {decay_mean[h]:.6f}    {ew_mean[h]:.4f}          "
                    f"{hopf_mean[h]:.4f}       {theory[h]:.4f}       {theory_w[h]:.4f}")
        if walk_base is not None:
            line += f"       {walk_base[h]:.6f}"
        add(line)
    add(f"  说明: 1 跳均分 {decay_mean[0]:.4f} / 3 跳均分 {decay_mean[min(2, H - 1)]:.4f}；"
        f"随机基线 = 沿随机出边游走（无去重、无最优路径）")
    sat = next((h + 1 for h in range(H) if valid_cnt[h] == 0), None)
    add(f"  饱和: " + (f"第 {sat} 跳起无新增节点（图上 12 跳预算远超实际需要，深跳已饱和）"
                     if sat else f"{H} 跳内始终有新增节点（未饱和）"))
    add(f"        0.86 是**逐跳因子**，可比量是「有效逐跳因子」= 最优路径平均边权 × 0.86"
        f"（首跳 {hopf_mean[0]:.4f}）")
    add(f"        平均得分是 edge_w×0.86 的连乘，边权均值 {ew_mean[0]:.4f}<1 会额外压低曲线，")
    add(f"        故「平均得分」必然低于纯 0.86^hop 理论线；比理论线用「有效逐跳因子」列。")

    add("")
    add(f"[性能] {H} 跳加权 BFS 单查询（{perf_n} 样本）: "
        f"p50 {p50:.2f}ms / p95 {p95:.2f}ms / max {tmax:.2f}ms → {perf_verdict}")
    add(f"[耗时] 总计 {wall:.1f}s")

    text = "\n".join(L)

    if args.txt_out:
        p = os.path.abspath(os.path.expanduser(args.txt_out))
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    if args.json_out:
        p = os.path.abspath(os.path.expanduser(args.json_out))
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(json_safe(result), f, ensure_ascii=False, indent=2)
            f.write("\n")
    if args.json:
        print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    else:
        print(text)


if __name__ == "__main__":
    main()
