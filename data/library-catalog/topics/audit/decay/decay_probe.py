#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decay_probe.py — AUDIT-DECAY 衰减专项探针（只读主体，写只在 audit/decay/）

目的：回答两个问题
  Q1 0.86 是怎么来的？「v1 文档图 0.730/0.636/0.584 → 每跳系数 ~0.86」能否独立复算成立？
  Q2 主题图 edges.csr.npz 上真实逐跳衰减是多少？0.86 与之偏差多大？该不该改？

方法（全部独立实现，不复用 topic_graph.py / topics_report.py 的函数）：
  A. 溯源复算：对 v1 文档图三个语义衰减余弦值，枚举候选推导式逐条复算并与 0.86 比对
  B. 主题图实测：自写「逐跳乘性最优路径 BFS」（层快照 + 首访定型 + 同跳取最大），
     在 decay=1.0（去掉硬编码系数）与 decay=0.86 两版下测 1–6 跳 score 分布与真实比值
  C. 可辨识性拆解：证明 score_d(h) = Πw × d^h ⟹ 系数 d 与边权 w 不可联合辨识，
     故「0.86 是否真实」是伪问题；真正可测的是 ratio_pure(h) 与阈值放行数
  D. around 影响抽测：0.86 vs 1.0 vs 校准值下的分层 top-k / 跨跳 top-k / 阈值放行数
  E. 交叉校验：与 topics-report.json 既有实测列逐项比对（复现性）

约束：不访问网络；不写主体目录；产物落 audit/decay/。用法：
    python3 decay_probe.py            # 打印表 + 写 decay-probe.json
    python3 decay_probe.py --json-out /path/to.json
"""

import argparse
import json
import math
import os
import sys
from collections import Counter

# --- 依赖：系统 python 无 numpy，沿用工程既有做法注入 ~/go/pylibs -------------
_PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)

import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TOPICS = os.path.dirname(os.path.dirname(HERE))       # <data>/topics
DATA = os.path.dirname(TOPICS)                        # <data>
DECAY_DOC = 0.86                                      # 被审计的硬编码系数
V1_DOC_GRAPH = [0.730, 0.636, 0.584]                  # v1 文档图 1/2/3 跳语义余弦（基线口径）
V1_DOC_GRAPH_ALT = [0.750, 0.658, 0.606]              # 同口径 400 源点重跑（baseline-p0-curve400）
V1_RANDOM_BASELINE = 0.408

# ===========================================================================
# A. 溯源复算
# ===========================================================================


def provenance_audit():
    """对 0.730/0.636/0.584 → 0.86 的候选推导式逐条独立复算。

    注意：这三个数是「各跳节点与源点的平均余弦相似度」（语义相似度），
    而 0.86 是「score 连乘里的逐跳因子」（边权乘积的额外乘子）——量纲不同。
    本函数只做数值复算，量纲问题在报告 §2 单独判。
    """
    def ratios(v):
        c1, c2, c3 = v
        r21, r32 = c2 / c1, c3 / c2
        geo = math.sqrt(r21 * r32)                     # = sqrt(c3/c1)
        lnfit = math.exp(sum(math.log(x) for x in (r21, r32)) / 2)
        lr = math.log(c1) + math.log(c2) + math.log(c3)   # 线性回归 ln c ~ hop
        # 最小二乘斜率（x=1,2,3）
        mx = 2.0
        my = lr / 3.0
        sxy = sum((h - mx) * (math.log(c) - my) for h, c in zip((1, 2, 3), v))
        sxx = 2.0
        linslope = math.exp(sxy / sxx)
        # 绝对值开 h 次方（假设 c_h = d^h）
        roots = [c ** (1.0 / h) for h, c in zip((1, 2, 3), v)]
        # 扣随机基线后再算比值（c-baseline 才是"超额相似度"）
        ex = [c - V1_RANDOM_BASELINE for c in v]
        r21b, r32b = ex[1] / ex[0], ex[2] / ex[1]
        geo_b = math.sqrt(r21b * r32b)
        return {
            "input": v,
            "ratio_hop2_over_hop1": r21,
            "ratio_hop3_over_hop2": r32,
            "geo_mean_of_ratios": geo,
            "loglin_fit_factor": linslope,
            "abs_root_per_hop": roots,
            "baseline_sub_ratios": [r21b, r32b],
            "baseline_sub_geo": geo_b,
        }

    main = provenance_audit_one = ratios(V1_DOC_GRAPH)
    alt = ratios(V1_DOC_GRAPH_ALT)

    # 候选「能不能算出 0.86」清单
    cands = [
        ("r21 = c2/c1", main["ratio_hop2_over_hop1"]),
        ("r32 = c3/c2", main["ratio_hop3_over_hop2"]),
        ("geo(r21,r32)", main["geo_mean_of_ratios"]),
        ("loglin fit", main["loglin_fit_factor"]),
        ("c1^(1/1)", main["abs_root_per_hop"][0]),
        ("c2^(1/2)", main["abs_root_per_hop"][1]),
        ("c3^(1/3)", main["abs_root_per_hop"][2]),
        ("c2^(1/3) [错位一跳]", V1_DOC_GRAPH[1] ** (1.0 / 3.0)),
        ("baseline-sub geo", main["baseline_sub_geo"]),
        ("r21 (400源重跑)", alt["ratio_hop2_over_hop1"]),
        ("geo (400源重跑)", alt["geo_mean_of_ratios"]),
        ("0.86^3 vs c2", DECAY_DOC ** 3),
    ]
    rows = []
    for name, val in cands:
        rows.append({"formula": name, "value": val,
                     "delta_vs_086": val - DECAY_DOC,
                     "rel_err_pct": (val - DECAY_DOC) / DECAY_DOC * 100.0,
                     "rounds_to_086": round(val, 2) == DECAY_DOC})
    return {"main": main, "alt": alt, "candidates": rows}


def report_field_audit():
    """核对 topics-report.json 的衰减字段：哪些是实测、哪些是纯理论线。"""
    p = os.path.join(TOPICS, "topics-report.json")
    if not os.path.exists(p):
        return {"found": False}
    d = json.load(open(p, encoding="utf-8"))
    dec = d.get("decay", {})
    theo_ok = all(abs(float(r["theory_086"]) - DECAY_DOC ** r["hop"]) < 1e-9
                  for r in dec.get("per_hop", []) if r.get("theory_086") is not None)
    per = []
    for r in dec.get("per_hop", [])[:6]:
        hop = r["hop"]
        ew = r.get("path_edge_weight_mean")
        eff = r.get("effective_hop_factor")
        per.append({
            "hop": hop,
            "score_mean": r.get("score_mean"),
            "retention_vs_prev": r.get("retention_vs_prev"),
            "path_edge_weight_mean": ew,
            "effective_hop_factor": eff,
            "theory_086": r.get("theory_086"),
            "eff_eq_ew_times_086": (None if ew is None or eff is None
                                    else abs(eff - ew * DECAY_DOC) < 1e-12),
        })
    return {
        "found": True,
        "decay_factor_field": dec.get("decay_factor"),
        "theory_086_is_pure_086_pow_hop": bool(theo_ok),
        "definition_line": d.get("definitions", {}).get("decay"),
        "theory_line": d.get("definitions", {}).get("decay_theory"),
        "mean_edge_weight_global": dec.get("mean_edge_weight_global"),
        "mean_edge_weight_on_best_paths": dec.get("mean_edge_weight_on_best_paths"),
        "per_hop": per,
        "note": "theory_086 列 = 0.86^hop 纯理论线（假设边权恒 1），非实测；"
                "无任何字段是「独立拟合出的逐跳衰减系数」",
    }


# ===========================================================================
# B. 主题图实测：逐跳乘性最优路径 BFS（独立实现）
# ===========================================================================


def best_path_bfs(seed, hops, indptr, indices, weights, decay, threshold=0.0):
    """逐跳乘性最优路径 BFS（独立自写，语义对齐文档口径）。

      (a) 层快照：第 h 跳只读第 h-1 跳结束时的分数
      (b) 首访定型：已入区节点的 layer/parent 不再改写
      (c) 同跳取最大：同跳多父指向同一新节点取最高分（平局按 id 升序）
    返回 levels[h] / scores[h] / parents[h]（h=0 为第 1 跳）。
    """
    score = {seed: 1.0}
    parent = {seed: -1}
    layer = {seed: 0}
    levels, scores, parents = [], [], []
    frontier = [seed]
    for h in range(1, hops + 1):
        prev = {u: score[u] for u in frontier}
        cand = {}
        for u in frontier:
            su = prev[u]
            for p in range(int(indptr[u]), int(indptr[u + 1])):
                v = int(indices[p])
                if v in score:
                    continue
                s = su * float(weights[p]) * decay
                if s < threshold:
                    continue
                cur = cand.get(v)
                if cur is None or s > cur[0] or (s == cur[0] and u < cur[1]):
                    cand[v] = (s, u)
        if not cand:
            for _ in range(h, hops + 1):
                levels.append([]); scores.append([]); parents.append([])
            break
        nn = sorted(cand)
        levels.append(nn)
        scores.append([cand[v][0] for v in nn])
        parents.append([cand[v][1] for v in nn])
        for v in nn:
            score[v] = cand[v][0]; parent[v] = cand[v][1]; layer[v] = h
        frontier = nn
    return levels, scores, parents


def make_seeds(types, cluster, n, seed=42, samples=400):
    """复刻 topics_report.py 的源点抽样：kw 且 cluster>=0，default_rng(seed).choice。"""
    pool_all = np.flatnonzero(types == "kw")
    pool = pool_all[cluster[pool_all] >= 0]
    rng = np.random.default_rng(seed)
    return rng.choice(pool, size=int(min(samples, len(pool))), replace=False).astype(np.int64)


def pctl(a, q):
    return float(np.percentile(a, q)) if a.size else float("nan")


def measure(seeds, indptr, indices, weights, decay, hops, threshold=0.0):
    """多源点逐跳统计：新增节点数 / score 分布 / 真实比值 / 最优路平均边权。"""
    per = []
    raw = []            # 每个源点的逐跳 score 均值（用于逐点配对比值）
    for h in range(1, hops + 1):
        raw.append([])
    for s in seeds:
        levels, scores, _ = best_path_bfs(int(s), hops, indptr, indices, weights,
                                          decay, threshold)
        for h in range(hops):
            raw[h].append(float(np.mean(scores[h])) if len(scores[h]) else float("nan"))
    for h in range(1, hops + 1):
        vals = np.array(raw[h - 1], dtype=np.float64)
        live = vals[np.isfinite(vals)]
        prev = np.array(raw[h - 2], dtype=np.float64) if h >= 2 else None
        # 逐源点配对比值（两个跳都非空才计入）
        ret_pt = float("nan")
        if prev is not None:
            m = np.isfinite(vals) & np.isfinite(prev) & (prev > 0)
            if m.any():
                ret_pt = float(np.mean(vals[m] / prev[m]))
        per.append({
            "hop": h,
            "samples_with_new_nodes": int(live.size),
            "score_mean": float(live.mean()) if live.size else None,
            "score_median": float(np.median(live)) if live.size else None,
            "score_p10": pctl(live, 10), "score_p25": pctl(live, 25),
            "score_p75": pctl(live, 75), "score_p90": pctl(live, 90),
            "score_min": float(live.min()) if live.size else None,
            "score_max": float(live.max()) if live.size else None,
            "retention_paired_mean": ret_pt,
            "theory_decay_pow_hop": decay ** h,
        })
    # 均值口径比值（非配对，与既有报告可比）
    for i, r in enumerate(per):
        if i == 0:
            r["retention_mean_ratio"] = None
            continue
        a, b = per[i]["score_mean"], per[i - 1]["score_mean"]
        r["retention_mean_ratio"] = (a / b) if (a and b) else None
    return per


def load_graph():
    z = np.load(os.path.join(TOPICS, "edges.csr.npz"))
    indptr, indices, weights = z["indptr"], z["indices"], z["weights"]
    nodes = json.load(open(os.path.join(TOPICS, "nodes.json"), encoding="utf-8"))
    order = np.argsort([int(x["id"]) for x in nodes])
    nodes = [nodes[int(i)] for i in order]
    types = np.array([str(x.get("type") or "") for x in nodes], dtype=object)
    cluster = np.array([int(x.get("cluster", -1)) for x in nodes], dtype=np.int64)
    terms = [str(x.get("term") or "") for x in nodes]
    return indptr, indices, weights, types, cluster, terms


# ===========================================================================
# D. around 影响抽测
# ===========================================================================


def around_probe(seeds, indptr, indices, weights, decays, hops, top=12, threshold=0.05):
    """0.86 vs 其他系数：分层 top-k 集合、跨跳 top-k 集合、阈值放行节点数。"""
    out = {}
    for d in decays:
        lay = [set() for _ in range(hops)]
        adm = [0] * hops
        glob = {}
        for s in seeds:
            levels, scores, _ = best_path_bfs(int(s), hops, indptr, indices, weights,
                                              d, threshold)
            for h in range(hops):
                if not levels[h]:
                    continue
                adm[h] += len(levels[h])
                idx = np.argsort([-x for x in scores[h]])[:top]
                for i in idx:
                    lay[h].add(int(levels[h][int(i)]))
                for v, sc in zip(levels[h], scores[h]):
                    glob[int(v)] = max(glob.get(int(v), 0.0), float(sc))
        gtop = sorted(glob.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
        out[f"{d:.6g}"] = {
            "decay": d,
            "admitted_nodes_by_hop": adm,
            "admitted_total": int(sum(adm)),
            "layer_topk_union": [len(x) for x in lay],
            "layer_topk_sets": [sorted(x) for x in lay],
            "global_topk": [v for v, _ in gtop],
        }
    return out


def jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(set(a) & set(b)) / len(set(a) | set(b))


# ===========================================================================
# main
# ===========================================================================


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default=os.path.join(HERE, "decay-probe.json"))
    ap.add_argument("--samples", type=int, default=400)
    ap.add_argument("--hops", type=int, default=6)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--probe-seeds", type=int, default=60, help="around 抽测源点数")
    args = ap.parse_args()

    indptr, indices, weights, types, cluster, terms = load_graph()
    n = len(indptr) - 1
    print(f"[图] 节点 {n} / 边 {len(indices)} / 平均出度 {len(indices)/n:.4f} / "
          f"边权 均 {weights.mean():.6f} 中位 {np.median(weights):.6f} "
          f"min {weights.min():.6f} max {weights.max():.6f}")

    # ---- A 溯源 ----
    prov = provenance_audit()
    print("\n[A] 0.730/0.636/0.584 → 0.86 候选推导式复算")
    print(f"{'推导式':<24}{'值':>12}{'vs 0.86':>12}{'相对误差%':>12}  四舍五入=0.86")
    for r in prov["candidates"]:
        print(f"{r['formula']:<24}{r['value']:>12.6f}{r['delta_vs_086']:>+12.6f}"
              f"{r['rel_err_pct']:>+12.3f}  {r['rounds_to_086']}")

    # ---- 报告字段核对 ----
    rep = report_field_audit()
    print(f"\n[A2] topics-report.json decay: factor={rep.get('decay_factor_field')} "
          f"theory_086==0.86^hop: {rep.get('theory_086_is_pure_086_pow_hop')}")
    for r in rep.get("per_hop", []):
        print(f"     hop{r['hop']} score_mean={r['score_mean']} "
              f"retention={r['retention_vs_prev']} ew={r['path_edge_weight_mean']} "
              f"eff={r['effective_hop_factor']} theo={r['theory_086']} "
              f"eff==ew*0.86:{r['eff_eq_ew_times_086']}")

    # ---- B 主题图实测 ----
    seeds = make_seeds(types, cluster, n, seed=args.seed, samples=args.samples)
    seeds2 = make_seeds(types, cluster, n, seed=7, samples=args.samples)
    print(f"\n[B] 源点 {len(seeds)} 个（kw∩cluster≥0, seed={args.seed}）；"
          f"对照样本 {len(seeds2)} 个（seed=7）")
    meas = {}
    for tag, sd, ss in (("d086", DECAY_DOC, seeds), ("d1", 1.0, seeds), ("d1_seed7", 1.0, seeds2)):
        meas[tag] = measure(ss, indptr, indices, weights, sd, args.hops, 0.0)

    hdr = (f"{'hop':>3} {'新增节点':>9} {'score均值':>11} {'中位':>10} {'P10':>9} {'P90':>9} "
           f"{'纯比值':>9} {'×0.86比值':>10} {'0.86^h':>9} {'偏差%':>9}")
    print("\n[B1] decay=1.0（去掉硬编码系数）—— 图自身的逐跳真实衰减")
    print(hdr)
    for r, r86 in zip(meas["d1"], meas["d086"]):
        pm = r["retention_mean_ratio"]
        print(f"{r['hop']:>3} {r['samples_with_new_nodes']:>9} {r['score_mean']:>11.6f} "
              f"{r['score_median']:>10.6f} {r['score_p10']:>9.6f} {r['score_p90']:>9.6f} "
              f"{(pm if pm else float('nan')):>9.4f} "
              f"{r86['retention_mean_ratio'] if r86['retention_mean_ratio'] else float('nan'):>10.4f} "
              f"{r['theory_decay_pow_hop']:>9.4f} "
              f"{(100*(r['theory_decay_pow_hop']-pm)/r['theory_decay_pow_hop'] if pm and r['hop']>1 else 0.0):>+9.2f}")

    print("\n[B2] decay=0.86（现行实现）")
    print(hdr)
    for r in meas["d086"]:
        pm = r["retention_mean_ratio"]
        print(f"{r['hop']:>3} {r['samples_with_new_nodes']:>9} {r['score_mean']:>11.6f} "
              f"{r['score_median']:>10.6f} {r['score_p10']:>9.6f} {r['score_p90']:>9.6f} "
              f"{(pm if pm else float('nan')):>9.4f} {float('nan'):>10.4f} "
              f"{r['theory_decay_pow_hop']:>9.4f} "
              f"{(100*(r['theory_decay_pow_hop']-pm)/r['theory_decay_pow_hop'] if pm and r['hop']>1 else 0.0):>+9.2f}")

    # ---- C 可辨识性拆解 ----
    sep = []
    for i, (a, b) in enumerate(zip(meas["d1"], meas["d086"]), start=1):
        if a["score_mean"] and b["score_mean"]:
            sep.append({"hop": i, "ratio_086_over_1": b["score_mean"] / a["score_mean"],
                        "expected_086_pow_h": DECAY_DOC ** i,
                        "rel_gap": abs(b["score_mean"] / a["score_mean"] - DECAY_DOC ** i)
                                   / DECAY_DOC ** i})
    print("\n[C] 可辨识性：score_0.86(h)/score_1.0(h) 应恒 = 0.86^h（系数=纯尺度因子）")
    for r in sep:
        print(f"     hop{r['hop']}: 实测比 {r['ratio_086_over_1']:.9f} vs 0.86^{r['hop']} "
              f"{r['expected_086_pow_h']:.9f} 相对偏差 {r['rel_gap']:.2e}")

    # ---- 交叉校验 ----
    xchk = []
    for r, rp in zip(meas["d086"], rep.get("per_hop", [])):
        if rp.get("score_mean") and r["score_mean"]:
            xchk.append({"hop": r["hop"], "probe": r["score_mean"],
                         "report": rp["score_mean"],
                         "rel_diff": abs(r["score_mean"] - rp["score_mean"]) / rp["score_mean"]})
    print("\n[E] 与本仓 topics-report.json 实测列交叉校验（decay=0.86, 无阈值）")
    for r in xchk:
        print(f"     hop{r['hop']}: probe {r['probe']:.9f} vs report {r['report']:.9f} "
              f"相对差 {r['rel_diff']:.2e}")

    # ---- D around 抽测 ----
    ps = make_seeds(types, cluster, n, seed=args.seed, samples=args.probe_seeds)
    decays = [DECAY_DOC, 1.0, 0.8944271909999159, 0.8712328767123288]
    ap_res = around_probe(ps, indptr, indices, weights, decays, hops=3, top=12,
                          threshold=0.05)
    print("\n[D] around 影响抽测（60 源点 / hops≤3 / 层内 top-12 / threshold=0.05）")
    base = ap_res[f"{DECAY_DOC:.6g}"]
    print(f"{'decay':>10} {'放行总数':>9} {'逐跳放行':>18} {'层内top12并集':>14} "
          f"{'层内top12 vs 0.86(交/并)':>24} {'跨跳top12 vs 0.86':>18}")
    for k, v in ap_res.items():
        ov = [jaccard(s1, s2) for s1, s2 in zip(v["layer_topk_sets"], base["layer_topk_sets"])]
        inter = [len(set(a) & set(b)) for a, b in zip(v["layer_topk_sets"],
                                                      base["layer_topk_sets"])]
        union = [len(set(a) | set(b)) for a, b in zip(v["layer_topk_sets"],
                                                      base["layer_topk_sets"])]
        gj = jaccard(v["global_topk"], base["global_topk"])
        print(f"{v['decay']:>10.6f} {v['admitted_total']:>9} "
              f"{str(v['admitted_nodes_by_hop']):>18} {str(v['layer_topk_union']):>14} "
              f"{str([f'{i}/{u}' for i, u in zip(inter, union)]):>24} {gj:>18.4f}")

    # ---- D2 无阈值下的层内序不变性（解析结论的经验验证） ----
    ap0 = around_probe(ps, indptr, indices, weights, decays, hops=3, top=12, threshold=0.0)
    inv = {}
    b0 = ap0[f"{DECAY_DOC:.6g}"]
    for k, v in ap0.items():
        inv[k] = [jaccard(a, b) for a, b in zip(v["layer_topk_sets"], b0["layer_topk_sets"])]
    print("\n[D2] threshold=0（无剪枝）下层内 top-12 集合一致性（对 0.86）—— 验证解析结论")
    for k, v in inv.items():
        print(f"     decay={float(k):.6f}: {[round(x,6) for x in v]}  放行总数 {ap0[k]['admitted_total']}")

    # ---- C2 口径分歧：既有报告的「有效逐跳因子」是「比的均值」，曲线真实衰减是「均值的比」 ----
    div = []
    for i, (r86, rp) in enumerate(zip(meas["d086"], rep.get("per_hop", [])), start=1):
        eff = rp.get("effective_hop_factor")
        ret = r86["retention_mean_ratio"]
        if eff is None or ret is None:
            continue
        div.append({"hop": i, "report_effective_hop_factor": eff,
                    "probe_actual_retention": ret,
                    "understatement_pct": (ret - eff) / ret * 100.0})
    print("\n[C2] 口径分歧：既有列『有效逐跳因子』（= 最优路边权均值 × 0.86，比的均值）"
          " vs 曲线真实逐跳衰减（= 均值的比）")
    for r in div:
        print(f"     hop{r['hop']}: 既有列 {r['report_effective_hop_factor']:.4f} vs "
              f"曲线真实 {r['probe_actual_retention']:.4f}"
              f"（既有列低估真实衰减 {r['understatement_pct']:.2f}%）")

    # ---- B0 稳定性：两个独立源点样本 ----
    stab = []
    for a, b in zip(meas["d1"][1:], meas["d1_seed7"][1:]):
        ra, rb = a["retention_mean_ratio"], b["retention_mean_ratio"]
        if ra and rb:
            stab.append({"hop": a["hop"], "seed42_ratio": ra, "seed7_ratio": rb,
                         "abs_gap": abs(ra - rb),
                         "rel_gap_pct": abs(ra - rb) / ra * 100.0})
    print("\n[B0] 样本稳定性（decay=1.0 纯比值，seed=42 vs seed=7，各 400 源点）")
    for r in stab:
        print(f"     hop{r['hop']}: {r['seed42_ratio']:.4f} vs {r['seed7_ratio']:.4f} "
              f"绝对差 {r['abs_gap']:.4f}（{r['rel_gap_pct']:.2f}%）")

    # ---- F 1–3 跳专项（任务书要求的最小口径） ----
    focus = {"d1": [], "d086": []}
    for tag in ("d1", "d086"):
        for r in meas[tag][:3]:
            ret = r["retention_mean_ratio"]
            focus[tag].append({
                "hop": r["hop"], "score_mean": r["score_mean"],
                "score_median": r["score_median"], "score_p10": r["score_p10"],
                "score_p90": r["score_p90"],
                "retention": ret,
                "dev_vs_086_pct": (None if not ret else (ret - DECAY_DOC) / DECAY_DOC * 100.0),
            })
    print("\n[F] 1–3 跳专项：实测逐跳比值 vs 0.86")
    for tag, name in (("d1", "纯比值(无系数)"), ("d086", "含0.86")):
        for r in focus[tag]:
            d = r["dev_vs_086_pct"]
            print(f"     {name} hop{r['hop']}: score均 {r['score_mean']:.6f} "
                  f"比值 {'n/a' if r['retention'] is None else format(r['retention'],'.4f')} "
                  f"vs 0.86 {'—' if d is None else format(d,'+.2f')+'%'}")

    # ---- 校准候选 ----
    cal = {}
    pure = [r["retention_mean_ratio"] for r in meas["d1"][1:] if r["retention_mean_ratio"]]
    if pure:
        cal["ratio_pure_geo_mean_hop2_3"] = float(math.exp(sum(math.log(x) for x in pure[:2]) / 2))
        cal["ratio_pure_min"] = float(min(pure)); cal["ratio_pure_max"] = float(max(pure))
    prov_main = prov["main"]
    cal["doc_graph_migrated_geo"] = prov_main["geo_mean_of_ratios"]
    cal["doc_graph_migrated_r21"] = prov_main["ratio_hop2_over_hop1"]
    cal["doc_graph_migrated_r32"] = prov_main["ratio_hop3_over_hop2"]
    cal["doc_graph_alt_geo"] = prov["alt"]["geo_mean_of_ratios"]

    res = {
        "meta": {
            "probe": "AUDIT-DECAY",
            "graph": {"nodes": n, "edges": int(len(indices)),
                      "mean_edge_weight": float(weights.mean()),
                      "min_edge_weight": float(weights.min()),
                      "max_edge_weight": float(weights.max())},
            "decay_audited": DECAY_DOC,
            "samples": int(len(seeds)), "seed": args.seed, "hops": args.hops,
            "threshold_for_measure": 0.0,
            "readonly_subject": True,
        },
        "A_provenance": prov,
        "A2_report_fields": rep,
        "B_measure_1p0": meas["d1"],
        "B_measure_0p86": meas["d086"],
        "B_measure_1p0_seed7": meas["d1_seed7"],
        "C_identifiability": sep,
        "C2_caliber_divergence": div,
        "B0_stability": stab,
        "F_focus_1to3": focus,
        "E_cross_check": xchk,
        "D_around": ap_res,
        "D2_no_threshold_invariance": {"per_decay": inv, "raw": ap0},
        "calibration_candidates": cal,
    }
    with open(args.json_out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f"\n[写出] {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
