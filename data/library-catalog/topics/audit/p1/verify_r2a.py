#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_r2a.py — R2-A（F2/F2b 双计数 + F1 排序键 + D1 层级边）修复的独立验证

只读主体代码与产物；只写 audit/p1/evidence/r2a-*.json。
验证项：
  V1 P1 产物不变量 + 规模 + 报告 A1 一致性（新旧对照）
  V2 F2/F2b：独立复现「修复前双计数比率」与「修复后按卡去重比率」→ 得出被误剔词集 F，
     核对 |F| 与 A 源漏斗 Δ 一致，且 F 中每个词都在新 nodes.json 中；核对 max ratio ≤ 1.0
  V3 F1/F1b：独立重算每节点主导簇卡数 max_cc，验证新 nodes.json 顺序 == sort(-max_cc,-freq,term)
     （即 (-freq, term) 次级键恢复生效），并统计 term→id 迁移量
  V4 D1：新 edges 中层级边实存数 == 登记数；AUDIT-NUM 列出的 9 条缺失层级边按 term 核对已落地；
     抽验边权重（同词对）与 R1 版对照
  V5 D1 净效应（隔离实验）：用修复后代码 + pre-r2 nodes 重跑，与 edges.csr.pre-r2.npz 逐边比对

用法：
  python3 verify_r2a.py --p1-only     # V1/V2/V3（P1 重建后）
  python3 verify_r2a.py               # 全部（P2 重建后）
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

SRC_DIR = "/home/wzh/go/reasonix-scripts/lib-catalog"
for _p in (os.path.expanduser("~/go/pylibs"), SRC_DIR):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
import numpy as np          # noqa: E402
import topic_build as tb    # noqa: E402  只调用其原语（match_a/term_extensions/merged_card_words）

T0 = time.time()
RES = {}


def log(m):
    print(f"[{time.time()-T0:6.1f}s] {m}", flush=True)


def dump(audit, name, obj):
    p = os.path.join(audit, "evidence", f"r2a-{name}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    log(f"  -> evidence/r2a-{name}.json ({os.path.getsize(p):,} B)")


def load_csr(p):
    z = np.load(p)
    return z["indptr"], z["indices"], z["weights"]


def edge_map(csr):
    ip, ix, wt = csr
    m = {}
    for u in range(len(ip) - 1):
        for p in range(int(ip[u]), int(ip[u + 1])):
            m[(u, int(ix[p]))] = float(wt[p])
    return m


# ---------------------------------------------------------------------------
def v1_artifacts(T, audit, nodes, report, report_pre):
    log("== V1 产物不变量 / 规模 / A1 ==")
    keys = {"id", "term", "type", "freq", "cluster", "cls", "sources"}
    bad = [e["term"] for e in nodes if set(e.keys()) != keys]
    ids_ok = [e["id"] for e in nodes] == list(range(len(nodes)))
    uniq = len({e["term"] for e in nodes}) == len(nodes)
    n = len(nodes)
    inv = {"n": n, "in_5k_20k": 5000 <= n <= 20000, "schema_bad": len(bad),
           "id_continuous": ids_ok, "term_unique": uniq,
           "freq_zero": sum(1 for e in nodes if e["freq"] == 0),
           "kw": sum(1 for e in nodes if e["type"] == "kw"),
           "cls": sum(1 for e in nodes if e["type"] == "cls"),
           "report_nodes": report["counts"]["nodes"],
           "report_kw": report["counts"]["kw"],
           "report_cls": report["counts"]["cls"],
           "truncated": report["counts"]["truncated"],
           "sources": dict(Counter("+".join(e["sources"]) for e in nodes)),
           "report_sources": report["counts"]["sources"],
           "pre_r2_n": len(json.load(open(os.path.join(T, "nodes.pre-r2.json"), encoding="utf-8")))}
    inv["a1_ok"] = (inv["n"] == inv["report_nodes"] and inv["kw"] == inv["report_kw"]
                    and inv["cls"] == inv["report_cls"] and inv["sources"] == inv["report_sources"])
    log(f"  nodes={n:,} (pre-r2 {inv['pre_r2_n']:,}) ∈[5k,20k]={inv['in_5k_20k']} "
        f"schema_bad={inv['schema_bad']} id_ok={ids_ok} A1={inv['a1_ok']} "
        f"truncated={inv['truncated']}")
    dump(audit, "p1-invariants", inv)
    return inv


def v2_containment(D, IX, T, audit, nodes_new, report):
    """独立复现：修复前（双计数）vs 修复后（按卡去重）的长词包含率，得出被误剔词集 F。"""
    log("== V2 F2/F2b 包含率双计数：修复前/后独立复现 ==")
    a_set, _mem, _raw = tb.load_source_a(IX["clusters"])
    matcher = tb.build_a_matcher(a_set)
    cards_path = os.path.join(D, "cards.jsonl")
    top_m = report["params"]["top_per_card"]
    min_df = report["params"]["min_df"]

    # 趟1：code 的 b_df（用于 b_keep_cjk，两版一致）
    b_df = Counter()
    for i, _c, title, tt in tb.iter_card(cards_path, IX["indptr"]):
        pairs = tb.top_title_tokens(i, IX["indptr"], IX["indices"], IX["data"], IX["nv"], tt, top_m)
        if pairs:
            for w in tb.merged_card_words(pairs):
                b_df[w] += 1
    b_keep_cjk = {w for w, v in b_df.items()
                  if v >= min_df and tb.term_ok_kw(w) and not tb.is_stop(w)
                  and tb.CJK_RE.search(w) and len(w) >= 2}

    ext_old, ext_new = Counter(), Counter()      # 双计数 vs 按卡去重
    cand = defaultdict(set)
    old_code_increments = 0
    for i, _c, title, tt in tb.iter_card(cards_path, IX["indptr"]):
        pairs = tb.top_title_tokens(i, IX["indptr"], IX["indices"], IX["data"], IX["nv"], tt, top_m)
        nt = tb.normalize_term(title)
        # --- 修复前：pass1(A 扩展) 与 pass1.5(B-CJK 扩展) 各自 ext_seen，各 +1 ---
        A_set = set()
        for w in tb.match_a(title, tt, matcher, nt):
            ex = tb.term_extensions(w, nt)
            cand[w] |= ex
            A_set |= ex
        B_set = set()
        if pairs:
            for w in tb.merged_card_words(pairs):
                if w in b_keep_cjk:
                    ex = tb.term_extensions(w, nt)
                    cand[w] |= ex
                    B_set |= ex
        for e in A_set:
            ext_old[e] += 1
            old_code_increments += 1
        for e in B_set:
            ext_old[e] += 1
            old_code_increments += 1
        # --- 修复后：同卡同一扩展词只计一次 ---
        for e in A_set | B_set:
            ext_new[e] += 1

    # 独立 freq（= 该词的卡片数，与 P1 口径一致：A 匹配 ∪ B-keep ∪ cls2）
    freq = Counter()
    for i, c, title, tt in tb.iter_card(cards_path, IX["indptr"]):
        pairs = tb.top_title_tokens(i, IX["indptr"], IX["indices"], IX["data"], IX["nv"], tt, top_m)
        nt = tb.normalize_term(title)
        keys = set()
        for w in tb.match_a(title, tt, matcher, nt):
            keys.add(w)
        if pairs:
            for w in tb.merged_card_words(pairs):
                if w in b_df and b_df[w] >= min_df and tb.term_ok_kw(w) and not tb.is_stop(w):
                    keys.add(w)
        cls2 = tb.normalize_cls(c.get("cls2") or "")
        if tb.term_ok_cls(cls2):
            keys.add(cls2)
        for w in keys:
            freq[w] += 1

    def ratio(w, ext):
        f = freq.get(w, 0)
        if f <= 0:
            return 1.0
        best = 0.0
        for e in cand.get(w, ()):
            c = ext.get(e, 0)
            if c:
                best = max(best, c / float(f))
        return best

    flips, max_new, gt1_new, max_old, gt1_old = [], 0.0, 0, 0.0, 0
    for w in a_set:
        if freq.get(w, 0) <= 0:
            continue
        ro, rn = ratio(w, ext_old), ratio(w, ext_new)
        max_old = max(max_old, ro)
        max_new = max(max_new, rn)
        if ro > 1.0:
            gt1_old += 1
        if rn > 1.0:
            gt1_new += 1
        if ro >= 0.9 > rn:
            flips.append({"term": w, "freq": freq[w], "ratio_old": round(ro, 4),
                          "ratio_new": round(rn, 4)})
    node_terms = {e["term"] for e in nodes_new}
    flips_in_nodes = sum(1 for f in flips if f["term"] in node_terms)
    res = {"a_set_n": len(a_set), "ext_old_increments": old_code_increments,
           "old_ratio_max": round(max_old, 4), "new_ratio_max": round(max_new, 4),
           "old_terms_ratio_gt1": gt1_old, "new_terms_ratio_gt1": gt1_new,
           "flip_terms": len(flips), "flip_terms_in_new_nodes": flips_in_nodes,
           "flip_sample": flips[:15],
           "report_a_containment_ratio_max": report["counts"].get("a_containment_ratio_max"),
           "report_a_terms_ratio_gt1": report["counts"].get("a_terms_ratio_gt1"),
           "report_source_a_kept": report["counts"]["source_a_kept"],
           "report_source_a_dropped_embedded": report["counts"]["source_a_dropped_embedded"]}
    # 与 build report 交叉核对
    res["cross_check_report_ratio_max"] = (res["report_a_containment_ratio_max"] == res["new_ratio_max"])
    res["cross_check_report_gt1"] = (res["report_a_terms_ratio_gt1"] == res["new_terms_ratio_gt1"])
    pre = json.load(open(os.path.join(T, "p1-build-report.pre-r2.json"), encoding="utf-8"))
    res["funnel_delta"] = {
        "a_kept": [pre["counts"]["source_a_kept"], report["counts"]["source_a_kept"],
                   report["counts"]["source_a_kept"] - pre["counts"]["source_a_kept"]],
        "a_dropped_embedded": [pre["counts"]["source_a_dropped_embedded"],
                               report["counts"]["source_a_dropped_embedded"],
                               report["counts"]["source_a_dropped_embedded"]
                               - pre["counts"]["source_a_dropped_embedded"]],
        "matches_flip_count": (
            report["counts"]["source_a_kept"] - pre["counts"]["source_a_kept"] == len(flips)
            and pre["counts"]["source_a_dropped_embedded"]
            - report["counts"]["source_a_dropped_embedded"] == len(flips)),
    }
    log(f"  ratio_max 修复前={max_old:.4f}(>1 的词 {gt1_old}) → 修复后={max_new:.4f}(>1 的词 {gt1_new})")
    log(f"  被误剔词集 F={len(flips)} 个，其中已回归新 nodes.json={flips_in_nodes}；"
        f"A 源漏斗 Δ 与 |F| 一致={res['funnel_delta']['matches_flip_count']}")
    dump(audit, "containment", res)
    return res


def v3_order(D, IX, T, audit, nodes, report):
    """独立重算 max_cc 并验证排序键；统计 pre-r2 → r2a 的 id 迁移。"""
    log("== V3 F1 排序键：独立重算 max_cc 并复核交付顺序 ==")
    a_set, _m, _r = tb.load_source_a(IX["clusters"])
    matcher = tb.build_a_matcher(a_set)
    top_m = report["params"]["top_per_card"]
    min_df = report["params"]["min_df"]
    b_df = Counter()
    for i, _c, title, tt in tb.iter_card(os.path.join(D, "cards.jsonl"), IX["indptr"]):
        pairs = tb.top_title_tokens(i, IX["indptr"], IX["indices"], IX["data"], IX["nv"], tt, top_m)
        if pairs:
            for w in tb.merged_card_words(pairs):
                b_df[w] += 1
    b_keep = {w for w, v in b_df.items() if v >= min_df and tb.term_ok_kw(w) and not tb.is_stop(w)}
    cl = defaultdict(Counter)
    freq = Counter()
    for i, c, title, tt in tb.iter_card(os.path.join(D, "cards.jsonl"), IX["indptr"]):
        pairs = tb.top_title_tokens(i, IX["indptr"], IX["indices"], IX["data"], IX["nv"], tt, top_m)
        nt = tb.normalize_term(title)
        keys = set(tb.match_a(title, tt, matcher, nt))
        if pairs:
            for w in tb.merged_card_words(pairs):
                if w in b_keep:
                    keys.add(w)
        cls2 = tb.normalize_cls(c.get("cls2") or "")
        if tb.term_ok_cls(cls2):
            keys.add(cls2)
        if not keys:
            continue
        lab = int(IX["labels"][i])
        for w in keys:
            freq[w] += 1
            cl[w][lab] += 1
    rows = []
    for e in nodes:
        cc = cl.get(e["term"], Counter())
        rows.append({"id": e["id"], "term": e["term"], "freq": e["freq"],
                     "max_cc": max(cc.values()) if cc else 0,
                     "my_freq": freq.get(e["term"], 0), "cluster": e["cluster"],
                     "my_cluster": (max(cc.items(), key=lambda kv: (kv[1], -kv[0]))[0] if cc else None)})
    freq_bad = [r for r in rows if r["my_freq"] != r["freq"]]
    cl_bad = [r for r in rows if r["my_cluster"] != r["cluster"]]
    key = [(-r["max_cc"], -r["freq"], r["term"]) for r in rows]
    order_ok = key == sorted(key)
    # id 迁移
    pre = {e["term"]: e["id"] for e in json.load(open(os.path.join(T, "nodes.pre-r2.json"),
                                                     encoding="utf-8"))}
    moved = sum(1 for r in rows if r["term"] in pre and pre[r["term"]] != r["id"])
    common = sum(1 for r in rows if r["term"] in pre)
    head = [(r["term"], r["id"], r["freq"], r["max_cc"]) for r in rows[:6]]
    res = {"n": len(rows), "freq_mismatch": len(freq_bad), "cluster_mismatch": len(cl_bad),
           "order_equals_int_key": order_ok, "distinct_max_cc": len({r["max_cc"] for r in rows}),
           "moved_ids_vs_pre_r2": moved, "common_terms": common,
           "moved_pct_of_common": round(100.0 * moved / max(common, 1), 2),
           "head6": head, "pre_r2_head6": [(e["term"], e["id"]) for e in
                                           json.load(open(os.path.join(T, "nodes.pre-r2.json"),
                                                          encoding="utf-8"))[:6]],
           "max_cc_zero": sum(1 for r in rows if r["max_cc"] == 0)}
    log(f"  freq 不符={len(freq_bad)} cluster 不符={len(cl_bad)} | 顺序==sort(-max_cc,-freq,term)={order_ok} "
        f"| 共有词 {common:,} 中 id 迁移 {moved:,}（{res['moved_pct_of_common']}%）")
    log(f"  head6(pre-r2)={res['pre_r2_head6']}  head6(r2a)={[h[:2] for h in head]}")
    dump(audit, "order", res)
    return res


def recompute_cls_of(D, T, nodes_path, ct_path):
    """独立复算层级边目标：每 kw 取其卡级证据（top-5 kw 卡 ∩ 有 cls2 的卡）中出现最多的 cls2 节点，
    众数、平局取较小 id（与 topic_edges.py L352-355 的登记规则一致）。"""
    nodes = json.load(open(nodes_path, encoding="utf-8"))
    cls_id = {}
    for i, x in enumerate(nodes):
        if x["type"] == "cls":
            cls_id[tb.normalize_cls(x["term"])] = i
    votes = defaultdict(Counter)
    with open(os.path.join(D, "cards.jsonl"), encoding="utf-8") as fc, \
            open(ct_path, encoding="utf-8") as ft:
        for lc, lt in zip(fc, ft):
            c, t = json.loads(lc), json.loads(lt)
            cid = cls_id.get(tb.normalize_cls(c.get("cls2") or ""))
            if cid is None:
                continue
            for u in t["topics"]:
                votes[int(u)][cid] += 1
    return {u: max(cnt.items(), key=lambda kv: (kv[1], -kv[0]))[0] for u, cnt in votes.items()}


def check_hier(csr_path, D, T, nodes_path, ct_path):
    """登记层级边 (u, cls_of[u]) 在产物中实存多少条。"""
    ip, ix, wt = load_csr(csr_path)
    emap = edge_map((ip, ix, wt))
    cls_of = recompute_cls_of(D, T, nodes_path, ct_path)
    nodes = json.load(open(nodes_path, encoding="utf-8"))
    kw = [i for i, x in enumerate(nodes) if x["type"] == "kw"]
    registered = [u for u in kw if u in cls_of]
    present = [u for u in registered
               if (u, cls_of[u]) in emap and emap[(u, cls_of[u])] >= 0.99999]
    missing = [u for u in registered if u not in set(present)]
    return {"registered": len(registered), "present": len(present), "missing": len(missing),
            "missing_ids": missing,
            "missing_terms": [nodes[u]["term"] for u in missing],
            "cls_of_sample": {nodes[u]["term"]: nodes[cls_of[u]]["term"] for u in registered[:5]}}


def v4_d1(T, audit, nodes, report, pre_report, D):
    """层级边实存 == 登记；AUDIT-NUM 的 9 条缺失边已落地（pre/post 对照）；抽验权重。"""
    log("== V4 D1 层级边存活性（独立复算 cls_of）==")
    post = check_hier(os.path.join(T, "edges.csr.npz"), D, T,
                      os.path.join(T, "nodes.json"), os.path.join(T, "card_topics.jsonl"))
    pre = check_hier(os.path.join(T, "edges.csr.pre-r2.npz"), D, T,
                     os.path.join(T, "nodes.pre-r2.json"), os.path.join(T, "card_topics.pre-r2.jsonl"))
    ip, ix, wt = load_csr(os.path.join(T, "edges.csr.npz"))
    emap = edge_map((ip, ix, wt))
    terms = [tb.normalize_term(x["term"]) for x in nodes]
    # --- 9 条 AUDIT-NUM 缺失边：用 pre-r2 证据复算的目标 + term 名称，跨版本核对 ---
    pre_cls_of = recompute_cls_of(D, T, os.path.join(T, "nodes.pre-r2.json"),
                                  os.path.join(T, "card_topics.pre-r2.jsonl"))
    pre_nodes = json.load(open(os.path.join(T, "nodes.pre-r2.json"), encoding="utf-8"))
    pre_t2i = {x["term"]: i for i, x in enumerate(pre_nodes)}
    pre_emap = edge_map(load_csr(os.path.join(T, "edges.csr.pre-r2.npz")))
    post_t2i = {x["term"]: i for i, x in enumerate(nodes)}
    post_cls_of = recompute_cls_of(D, T, os.path.join(T, "nodes.json"),
                                   os.path.join(T, "card_topics.jsonl"))
    probe_terms = [pre_nodes[u]["term"] for u in sorted(pre["missing_ids"])]
    probe_res = []
    for t in probe_terms:
        pu = pre_t2i[t]
        pt = pre_nodes[pre_cls_of[pu]]["term"]          # pre-r2 证据下的登记目标
        u = post_t2i.get(t)
        ct = nodes[post_cls_of[u]]["term"] if (u is not None and u in post_cls_of) else None
        pre_has = (pu, pre_cls_of[pu]) in pre_emap
        same_target = (ct == pt)
        v = post_t2i.get(ct) if ct else None
        post_has = (u, v) in emap if (u is not None and v is not None) else None
        probe_res.append({"term": t, "pre_r2_target": pt, "pre_r2_present": bool(pre_has),
                          "r2a_target": ct, "target_unchanged": same_target,
                          "r2a_u": u, "r2a_v": v, "r2a_registered_edge_present": bool(post_has),
                          "r2a_w": emap.get((u, v)) if post_has else None})
    # --- 抽验 3 条普通边权重：程序化取"两版都存在且非层级"的 3 条（按 r2a 权重降序取前 3） ---
    term_of = {i: x["term"] for i, x in enumerate(nodes)}
    pre_term_pair = {(pre_nodes[a]["term"], pre_nodes[b]["term"]): w for (a, b), w in pre_emap.items()}
    pairs = []
    for (u, v), w in sorted(emap.items(), key=lambda kv: -kv[1]):
        a, b = term_of[u], term_of[v]
        if nodes[v]["type"] == "cls" or nodes[u]["type"] == "cls":
            continue
        pw = pre_term_pair.get((a, b), pre_term_pair.get((b, a)))
        if pw is None:
            continue
        pairs.append({"pair": [a, b], "u": u, "v": v, "w_r2a": w, "w_pre_r2": pw,
                      "identical": w == pw})
        if len(pairs) == 3:
            break
    samp = pairs
    res = {"post": post, "pre_r2": pre,
           "registered_from_report": report["counts"]["hierarchical_edges"],
           "pre_r2_registered_from_report": pre_report["counts"]["hierarchical_edges"],
           "matches_registered": post["registered"] == post["present"],
           "pre_r2_missing": pre["missing"],
           "probe_9_previously_missing": probe_res,
           "probe_9_registered_present": all(p["r2a_registered_edge_present"] for p in probe_res),
           "probe_9_targets_unchanged": sum(1 for p in probe_res if p["target_unchanged"]),
           "probe_9_pre_r2_present": sum(1 for p in probe_res if p["pre_r2_present"]),
           "sample_edge_weights": samp,
           "sample_weights_identical": all(x["identical"] for x in samp),
           "edges_final": len(ix), "nodes": len(nodes)}
    log(f"  r2a:  登记层级边={post['registered']:,} 实存={post['present']:,} 缺={post['missing']} "
        f"（报告登记 {report['counts']['hierarchical_edges']:,}）")
    log(f"  pre-r2: 登记={pre['registered']:,} 实存={pre['present']:,} 缺={pre['missing']} "
        f"（复现 AUDIT-NUM D1）")
    log(f"  9 条历史缺失边：pre-r2 实存 {res['probe_9_pre_r2_present']}/9 → r2a 各自登记目标实存 "
        f"{sum(1 for p in probe_res if p['r2a_registered_edge_present'])}/9"
        f"（其中目标未变 {res['probe_9_targets_unchanged']}/9；目标变更者为 P1 卡 top-5 变化导致众数 cls2 漂移）")
    log(f"  抽验 3 条普通边权重与 pre-r2 逐位相同={res['sample_weights_identical']} "
        f"{[(x['pair'], x['w_r2a'], x['w_pre_r2']) for x in samp]}")
    dump(audit, "d1", res)
    return res


def v5_isolation(D, T, audit):
    """D1 净效应：修复后代码 + pre-r2 nodes 的产物 vs edges.csr.pre-r2.npz。"""
    log("== V5 D1 隔离实验（同 pre-r2 nodes，仅换修复后的截断代码）==")
    iso = os.path.join(audit, "scratch", "r2a-d1-isolation", "edges.csr.npz")
    if not os.path.exists(iso):
        log("  [skip] 隔离实验产物不存在")
        return {"skipped": True}
    ip_a, ix_a, wt_a = load_csr(os.path.join(T, "edges.csr.pre-r2.npz"))
    ip_b, ix_b, wt_b = load_csr(iso)
    a, b = edge_map((ip_a, ix_a, wt_a)), edge_map((ip_b, ix_b, wt_b))
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    common = set(a) & set(b)
    w_diff = [k for k in common if a[k] != b[k]]
    nodes_pre = json.load(open(os.path.join(T, "nodes.pre-r2.json"), encoding="utf-8"))
    terms = [tb.normalize_term(x["term"]) for x in nodes_pre]
    types = [x["type"] for x in nodes_pre]
    fmt = lambda ks: [[terms[u], terms[v]] for u, v in ks[:12]]
    # 9 条新增边是否恰为 (u, cls_of_pre[u]) 的层级边，且 w=1.0
    pre_cls = recompute_cls_of(D, T, os.path.join(T, "nodes.pre-r2.json"),
                               os.path.join(T, "card_topics.pre-r2.jsonl"))
    added_hier = [(u, v) for (u, v) in only_b if pre_cls.get(u) == v and b[(u, v)] >= 0.99999]
    from collections import Counter as _C
    dropped_types = dict(_C(f"{types[u]}->{types[v]}" for (u, v) in only_a))
    res = {"edges_pre_r2": len(a), "edges_d1fixed_same_nodes": len(b),
           "only_in_pre_r2": len(only_a), "only_in_d1fixed": len(only_b),
           "weight_diff_on_common": len(w_diff),
           "added_all_are_registered_hier": len(added_hier) == len(only_b),
           "added_hier_w1": all(b[k] >= 0.99999 for k in added_hier),
           "dropped_type_breakdown": dropped_types,
           "added_hier_terms": [[terms[u], terms[v]] for u, v in added_hier],
           "only_in_pre_r2_sample": fmt(only_a), "only_in_d1fixed_sample": fmt(only_b)}
    log(f"  pre-r2={len(a):,} 边 / 修复后同节点={len(b):,} 边 | 消失={len(only_a)} 新增={len(only_b)} "
        f"| 共同边权重不同={len(w_diff)}")
    log(f"  消失样本={res['only_in_pre_r2_sample'][:4]}")
    log(f"  新增样本={res['only_in_d1fixed_sample'][:4]}")
    log(f"  9 条新增边全部是登记层级边={res['added_all_are_registered_hier']}（w=1.0 "
        f"{res['added_hier_w1']}）；被顶替的 9 条边类型={res['dropped_type_breakdown']}"
        f"（各源点让位给层级边的尾部边，总数不变）")
    dump(audit, "d1-isolation", res)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.expanduser("~/go/lib-catalog-data"))
    ap.add_argument("--audit", default=os.path.expanduser("~/go/lib-catalog-data/topics/audit/p1"))
    ap.add_argument("--p1-only", action="store_true")
    args = ap.parse_args()
    D = os.path.abspath(os.path.expanduser(args.data))
    A = os.path.abspath(os.path.expanduser(args.audit))
    T = os.path.join(D, "topics")
    os.makedirs(os.path.join(A, "evidence"), exist_ok=True)
    log(f"== VERIFY-R2A 开始 data={D} ==")
    nodes = json.load(open(os.path.join(T, "nodes.json"), encoding="utf-8"))
    report = json.load(open(os.path.join(T, "p1-build-report.json"), encoding="utf-8"))
    pre_report = json.load(open(os.path.join(T, "p1-build-report.pre-r2.json"), encoding="utf-8"))
    idx = os.path.join(D, "index")
    z = np.load(os.path.join(idx, "tfidf.npz"))
    IX = {"indptr": z["indptr"], "indices": z["indices"], "data": z["data"],
          "nv": [tb.normalize_term(t) for t in json.load(open(os.path.join(idx, "vocab.json"),
                                                              encoding="utf-8"))],
          "labels": np.load(os.path.join(idx, "clusters.npy")),
          "clusters": json.load(open(os.path.join(D, "clusters.json"), encoding="utf-8"))["clusters"]}
    RES["v1"] = v1_artifacts(T, A, nodes, report, pre_report)
    if not args.p1_only:
        RES["v2"] = v2_containment(D, IX, T, A, nodes, report)
        RES["v3"] = v3_order(D, IX, T, A, nodes, report)
    else:
        RES["v2"] = v2_containment(D, IX, T, A, nodes, report)
        RES["v3"] = v3_order(D, IX, T, A, nodes, report)
    if not args.p1_only:
        p2 = json.load(open(os.path.join(T, "p2-build-report.json"), encoding="utf-8"))
        p2_pre = json.load(open(os.path.join(T, "p2-build-report.pre-r2.json"), encoding="utf-8"))
        RES["v4"] = v4_d1(T, A, nodes, p2, p2_pre, D)
        RES["v5"] = v5_isolation(D, T, A)
    log("== 结论 ==")
    v1, v2, v3 = RES["v1"], RES["v2"], RES["v3"]
    log(f"  V1 规模 {v1['pre_r2_n']:,}→{v1['n']:,} ∈[5k,20k]={v1['in_5k_20k']} A1={v1['a1_ok']}")
    log(f"  V2 ratio_max {v2['old_ratio_max']}→{v2['new_ratio_max']}；误剔词回归 "
        f"{v2['flip_terms_in_new_nodes']}/{v2['flip_terms']}；漏斗 Δ 一致="
        f"{v2['funnel_delta']['matches_flip_count']}")
    log(f"  V3 freq 不符={v3['freq_mismatch']} cluster 不符={v3['cluster_mismatch']} "
        f"排序键恢复={v3['order_equals_int_key']}")
    if "v4" in RES:
        log(f"  V4 层级边 pre-r2 缺 {RES['v4']['pre_r2_missing']} 条 → r2a 缺 "
            f"{RES['v4']['post']['missing']} 条（登记 {RES['v4']['post']['registered']:,}，"
            f"实存 {RES['v4']['post']['present']:,}）→ {RES['v4']['matches_registered']}；"
            f"9 条历史缺失边（按各自登记目标）落地="
            f"{RES['v4']['probe_9_registered_present']}")
    log("== VERIFY DONE ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
