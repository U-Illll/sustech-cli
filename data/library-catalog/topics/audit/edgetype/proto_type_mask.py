#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
proto_type_mask.py — AUDIT-EDGETYPE 专项：边型信息损失量化 + 方案 a 最小原型

只读主体（topics/edges.csr.npz、nodes.json、card_topics.jsonl、cards.jsonl、index/clusters.npy），
只写 topics/audit/edgetype/。

论证链：
  S0 载入正式产物，量化三数组的信息面
  S1 从 card_topics.jsonl(+cards.jsonl+clusters.npy) 重建 cnt / cnt_sc / cls_of
  S2 用 topic_edges.topk_csr 的逐位复刻重跑截断，与正式 edges.csr.npz 逐字节比对 → 保真门
  S3 对每条存活有向边计算真值 3-bit 边型掩码（COOCCUR|SAMECLUSTER|HIER）
  S4 仅凭 NPZ（+nodes.json 结构 + 两条可证明不变式）能判定多少、必须重算多少
  S5 方案 a 原型：小样例写入 types(u8)，验证往返 / 查询 / 向后兼容 / 体积
  S6 方案 a/b/c 成本对照，落盘离线掩码

用法：
  PYTHONPATH=~/go/pylibs python3 proto_type_mask.py [--data DIR] [--out DIR] [--sample-nodes 512]
"""
import argparse
import json
import math
import os
import re
import sys
import time
import unicodedata

_PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)
import numpy as np

# ---- 边型枚举（u8 bitmask；方案 a 的对外契约）--------------------------------
T_COOCCUR = 1 << 0   # ① 卡级共现 w1 = log1p(min(cnt,cap))/log1p(cap)
T_SAMECL = 1 << 1    # ② 同簇加成 w2 = 0.3·log1p(cnt_sc)/log1p(cap)
T_HIER = 1 << 2      # ③ 层级边 主题→众数 cls2，w3 = 1.0，单向
TYPE_NAMES = {0: "COOCCUR", 1: "SAMECLUSTER", 2: "HIER"}
ASCII_RE = re.compile(r"^[\x00-\x7f]+$")


def normalize_term(s):
    """逐位复刻 topic_build.normalize_term。"""
    s = re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))
    return s.lower() if ASCII_RE.match(s) else s.strip()


def normalize_cls(s):
    """逐位复刻 topic_build.normalize_cls。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or "")).strip()


def tri_index(u, v, n):
    """逐位复刻 topic_edges.tri_index（要求 u<v）。"""
    return n * u - (u * (u + 1)) // 2 + (v - u - 1)


def topk_csr(src, dst, w, tie, n, max_out, primary="assoc"):
    """逐位复刻 topic_edges.topk_csr（S2 保真门证明复刻正确）。"""
    key = src.astype(np.int64) * n + dst
    o = np.lexsort((np.arange(len(src)), -w, key))
    key_s = key[o]
    first = np.empty(len(key_s), dtype=bool)
    first[0] = True
    np.not_equal(key_s[1:], key_s[:-1], out=first[1:])
    take = o[first]
    src, dst, w, tie = src[take], dst[take], w[take], tie[take]
    order = (np.lexsort((dst, -w, -tie, src)) if primary == "assoc"
             else np.lexsort((dst, -tie, -w, src)))
    src, dst, w = src[order], dst[order], w[order]
    starts = np.flatnonzero(np.r_[True, src[1:] != src[:-1]])
    counts = np.diff(np.r_[starts, len(src)])
    rank = np.arange(len(src)) - np.repeat(starts, counts)
    keep = rank < max_out
    src, dst, w = src[keep], dst[keep], w[keep]
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.add.at(indptr, src + 1, 1)
    indptr = np.cumsum(indptr)
    return indptr.astype(np.int64), dst.astype(np.int32), w.astype(np.float32)


def load_nodes(out_dir):
    nodes = json.load(open(os.path.join(out_dir, "nodes.json"), encoding="utf-8"))
    n = len(nodes)
    terms = [normalize_term(x["term"]) for x in nodes]
    types_arr = np.array([x["type"] for x in nodes])
    ncl = np.array([int(x["cluster"]) for x in nodes], dtype=np.int64)
    nfreq = np.array([int(x["freq"]) for x in nodes], dtype=np.int64)
    cls_map = {}
    for i, t in enumerate(terms):
        if types_arr[i] == "cls":
            cls_map[normalize_cls(nodes[i]["term"])] = i
            cls_map.setdefault(t, i)
    return nodes, n, types_arr, ncl, nfreq, cls_map


def lookup_cls(cls_map, raw):
    if not raw:
        return -1
    return cls_map.get(normalize_cls(raw), cls_map.get(normalize_term(raw), -1))


def _grow(a, extra):
    return np.concatenate([a, np.empty(max(extra, 1 << 20), dtype=a.dtype)])


def reconstruct(data_dir, out_dir, n, ncl, cls_map, top_k):
    """S1：单趟重建 aug 口径 pair 集合 / 同簇计数 / 层级投票。"""
    ct_path = os.path.join(out_dir, "card_topics.jsonl")
    cards_path = os.path.join(data_dir, "cards.jsonl")
    labels = np.load(os.path.join(data_dir, "index", "clusters.npy"))
    cap = top_k * (top_k + 1) // 2 + top_k          # C(top_k+1,2) 上界
    U = np.empty(1 << 16, dtype=np.int32); V = np.empty(1 << 16, dtype=np.int32)
    Us = np.empty(1 << 16, dtype=np.int32); Vs = np.empty(1 << 16, dtype=np.int32)
    ku = kus = 0; n_cards = 0; votes = {}
    with open(cards_path, encoding="utf-8") as fc, open(ct_path, encoding="utf-8") as ft:
        for i, (lc, lt) in enumerate(zip(fc, ft)):
            c = json.loads(lc); rec = json.loads(lt)
            if (rec.get("mms") or "") != (c.get("mms") or ""):
                raise SystemExit(f"[fatal] card_topics 第 {i} 行 mms 与 cards.jsonl 不对齐")
            tops = rec.get("topics") or []
            items = list(tops)
            cid = lookup_cls(cls_map, c.get("cls2") or "")
            if cid >= 0:
                items.append(cid)
                for u in tops:
                    d = votes.setdefault(u, {})
                    d[cid] = d.get(cid, 0) + 1
            lab = int(labels[i])
            if ku + cap > len(U):
                U = _grow(U, cap); V = _grow(V, cap); Us = _grow(Us, cap); Vs = _grow(Vs, cap)
            m = len(items)
            for x in range(m):
                for y in range(x + 1, m):
                    u, v = items[x], items[y]
                    if u == v:
                        continue
                    if u > v:
                        u, v = v, u
                    U[ku] = u; V[ku] = v; ku += 1
                    if ncl[u] == ncl[v] == lab:
                        Us[kus] = u; Vs[kus] = v; kus += 1
            n_cards += 1
    U, V, Us, Vs = U[:ku], V[:ku], Us[:kus], Vs[:kus]
    uniq, first_pos, counts = np.unique(tri_index(U.astype(np.int64), V.astype(np.int64), n),
                                        return_index=True, return_counts=True)
    up, vp = U[first_pos].astype(np.int64), V[first_pos].astype(np.int64)
    c_sc = np.zeros(len(uniq), dtype=np.int64)
    if kus:
        uniq_s, counts_s = np.unique(tri_index(Us.astype(np.int64), Vs.astype(np.int64), n),
                                     return_counts=True)
        c_sc[np.searchsorted(uniq, uniq_s)] = counts_s
    cls_of = np.full(n, -1, dtype=np.int64)
    for u, d in votes.items():
        cls_of[u] = max(d.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    return dict(up=up, vp=vp, uniq=uniq, counts=counts, c_sc=c_sc, cls_of=cls_of,
                n_cards=n_cards, pairs_raw=ku, samesc_raw=kus, distinct=len(uniq))


def build_edges(R, n, nfreq, cap_count, max_out, rank_by="assoc", combine="sum"):
    """S2：复刻 topic_edges 的权重公式与组装（aug 口径）。"""
    up, vp, counts, c_sc = R["up"], R["vp"], R["counts"], R["c_sc"]
    cap_log = math.log1p(cap_count)
    w1 = np.log1p(np.minimum(counts, cap_count)) / cap_log
    w2 = 0.3 * np.log1p(c_sc) / cap_log
    w = np.minimum(1.0, w1 + w2) if combine == "sum" else np.maximum(w1, w2)
    src = np.concatenate([up, vp]); dst = np.concatenate([vp, up]); ww = np.concatenate([w, w])
    if rank_by == "assoc":
        rk = counts / np.sqrt(np.maximum(nfreq[up], 1) * np.maximum(nfreq[vp], 1))
    else:
        rk = counts.astype(np.float64)
    rk = np.concatenate([rk, rk])
    has = R["cls_of"] >= 0
    src = np.concatenate([src, np.flatnonzero(has).astype(np.int64)])
    dst = np.concatenate([dst, R["cls_of"][has]])
    ww = np.concatenate([ww, np.ones(int(has.sum()), dtype=np.float64)])
    rk = np.concatenate([rk, nfreq[has].astype(np.float64) * 1e9])
    return topk_csr(src, dst, ww, rk, n, max_out, primary=rank_by)


def truth_mask(R, n, types_arr, indptr, indices):
    """S3：为每条存活有向边计算真值 3-bit 掩码。"""
    u_of = np.repeat(np.arange(len(indptr) - 1, dtype=np.int64), np.diff(indptr))
    v_of = indices.astype(np.int64)
    lo = np.minimum(u_of, v_of); hi = np.maximum(u_of, v_of)
    pk = tri_index(lo, hi, n)
    pos = np.searchsorted(R["uniq"], pk)
    ok = np.zeros(len(pk), dtype=bool)
    lim = np.minimum(pos, len(R["uniq"]) - 1)
    ok = R["uniq"][lim] == pk
    mask = np.where(ok, np.uint8(T_COOCCUR), np.uint8(0))
    sc_ok = ok & (R["c_sc"][lim] > 0)                       # ② 只在已有 pair 上成立
    mask = np.where(sc_ok, mask | np.uint8(T_SAMECL), mask).astype(np.uint8)
    hier = (types_arr[u_of] == "kw") & (R["cls_of"][u_of] == v_of)
    mask = np.where(hier, mask | np.uint8(T_HIER), mask).astype(np.uint8)
    return mask, u_of, v_of, sc_ok, hier, ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.expanduser("~/go/lib-catalog-data"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--sample-nodes", type=int, default=512)
    ap.add_argument("--cap-count", type=int, default=50)
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--max-out", type=int, default=20)
    args = ap.parse_args()
    D = os.path.abspath(os.path.expanduser(args.data))
    out_dir = os.path.abspath(os.path.expanduser(args.out)) if args.out else os.path.join(D, "topics")
    A = os.path.join(out_dir, "audit", "edgetype")
    P = os.path.join(A, "proto")
    os.makedirs(P, exist_ok=True)
    t0 = time.time()
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "data_dir": D}

    # ---- S0 ----
    apath = os.path.join(out_dir, "edges.csr.npz")
    z = np.load(apath)
    indptr, indices, weights = z["indptr"], z["indices"], z["weights"]
    nodes, n, types_arr, ncl, nfreq, cls_map = load_nodes(out_dir)
    E = int(len(indices))
    res["S0_artifact"] = {
        "path": "topics/edges.csr.npz", "arrays": list(z.keys()),
        "dtypes": {k: str(z[k].dtype) for k in z.keys()},
        "nodes": n, "edges": E, "edge_array_bytes": {k: int(z[k].nbytes) for k in z.keys()},
        "file_bytes": os.path.getsize(apath),
        "info_lost": "边型（①②③ 组成）未落盘；weights 中 w1/w2 与 w3 不可分辨",
        "not_recoverable_from_npz": ["cnt(u,v)", "cnt_sc(u,v)", "cls_of[u]"]}
    print(f"[S0] edges={E:,} nodes={n:,} | {time.time()-t0:.1f}s", flush=True)

    # ---- S1 ----
    R = reconstruct(D, out_dir, n, ncl, cls_map, args.top_k)
    res["S1_reconstruct"] = {"inputs": ["topics/card_topics.jsonl", "cards.jsonl", "index/clusters.npy",
                                        "topics/nodes.json"],
                             "cards": R["n_cards"], "pairs_raw": R["pairs_raw"],
                             "samesc_raw": R["samesc_raw"], "distinct_pairs": R["distinct"],
                             "hier_edges": int((R["cls_of"] >= 0).sum()),
                             "kw_without_hier": int(((types_arr == "kw") & (R["cls_of"] < 0)).sum())}
    print(f"[S1] cards={R['n_cards']:,} pairs={R['pairs_raw']:,} distinct={R['distinct']:,} "
          f"hier={res['S1_reconstruct']['hier_edges']:,} | {time.time()-t0:.1f}s", flush=True)

    # ---- S2 保真门 ----
    ip2, ix2, w2 = build_edges(R, n, nfreq, args.cap_count, args.max_out)
    gate = {"indptr_equal": bool(np.array_equal(indptr, ip2)),
            "indices_equal": bool(np.array_equal(indices, ix2)),
            "weights_bitwise_equal": bool(np.array_equal(weights, w2)),
            "max_abs_weight_diff": float(np.max(np.abs(weights.astype(np.float64) - w2.astype(np.float64))))}
    gate["pass"] = gate["indptr_equal"] and gate["indices_equal"] and gate["weights_bitwise_equal"]
    res["S2_fidelity_gate"] = gate
    print(f"[S2] 保真门 pass={gate['pass']} | {time.time()-t0:.1f}s", flush=True)

    # ---- S3 真值掩码 ----
    mask, u_of, v_of, sc_ok, hier, ok = truth_mask(R, n, types_arr, indptr, indices)
    dist = []
    for m in range(8):
        c = int((mask == m).sum())
        dist.append({"mask": m,
                     "bits": [TYPE_NAMES[b] for b in range(3) if m >> b & 1] or ["(none)"],
                     "count": c, "share": round(c / E, 6)})
    res["S3_truth_mask"] = {
        "distribution": dist,
        "invariants": {
            "orphan_edges(mask=0)": int((mask == 0).sum()),
            "hier_implies_cooccur": bool(np.all((mask[hier] & T_COOCCUR) != 0)),
            "samesc_implies_cooccur": bool(np.all((mask[sc_ok] & T_COOCCUR) != 0)),
            "cooccur_edges": int((mask & T_COOCCUR).sum()),
            "samecluster_edges": int(sc_ok.sum()),
            "hier_edges": int(hier.sum())}}
    mt = sum(dist[m]["count"] for m in range(8) if bin(m).count("1") > 1)
    res["S3_truth_mask"]["invariants"]["multi_type_edges"] = mt
    print(f"[S3] 分布 " + " ".join(f"m{d['mask']}={d['count']:,}" for d in dist)
          + f" | 多型边={mt:,} | {time.time()-t0:.1f}s", flush=True)

    # ---- S4 仅凭 NPZ 的可判定性 ----
    hier_shape = (types_arr[u_of] == "kw") & (types_arr[v_of] == "cls")
    same_clu = ncl[u_of] == ncl[v_of]
    w_is1 = weights >= np.float32(0.999999)
    # 不变式 I0：hier ⟹ cooccur，且每条边必来自 ① 或 ③ ⟹ bit0 恒 = 1（无需重算即知）
    bit0_unknown = np.zeros(E, dtype=bool)
    # 不变式 I1：hier 权重恒为 1.0 ⟹ w<1.0 ⟹ bit2=0；仅 (kw→cls 形状 ∧ w==1.0) 时 bit2 不可判
    bit2_unknown = hier_shape & w_is1
    bit2_known0 = ~bit2_unknown
    # bit1：仅同簇边可能带 ②，w 中无法分离 w1/w2
    bit1_unknown = same_clu
    n_unknown = bit0_unknown.astype(np.uint8) + bit1_unknown.astype(np.uint8) + bit2_unknown.astype(np.uint8)
    res["S4_determinability"] = {
        "proofs": {
            "I0_hier_implies_cooccur": "③ 的投票卡必然把对 (主题, cls2) 并入 ① 的 pair 集 ⟹ bit0 ≡ 1",
            "I1_hier_weight_is_1": "③ w3=1.0 且去重取 max ⟹ 存活 w<1.0 ⟹ bit2=0",
            "I2_samecluster_is_pairwise": "② 是 (u,v) 对级加成，u,v 簇不同则 bit1=0"},
        "unknown_bits": {
            "bit0_COOCCUR": int(bit0_unknown.sum()),
            "bit1_SAMECLUSTER": int(bit1_unknown.sum()),
            "bit2_HIER": int(bit2_unknown.sum())},
        "edges_by_unknown_count": {
            "0_fully_determined": int((n_unknown == 0).sum()),
            "1_bit_unknown": int((n_unknown == 1).sum()),
            "2_bits_unknown": int((n_unknown == 2).sum())},
        "shares": {"fully_determined": round(float((n_unknown == 0).mean()), 6),
                   "needs_recompute": round(float((n_unknown > 0).mean()), 6)},
        "naive_shape_only_unknown(no I1 applied)": int(hier_shape.sum()),
        "bit1_known_zero_by_cluster_mismatch": int((~same_clu).sum()),
        "bit2_known_zero_by_w_or_shape": int(bit2_known0.sum()),
        "recompute_required_edges": int((n_unknown > 0).sum()),
        "recompute_required_share": round(float((n_unknown > 0).mean()), 6)}
    print(f"[S4] 全判定={int((n_unknown==0).sum()):,} 1位未知={int((n_unknown==1).sum()):,} "
          f"2位未知={int((n_unknown==2).sum()):,} | {time.time()-t0:.1f}s", flush=True)

    # 交叉校验：NPZ-only 推断的"已知 0"是否与真值冲突
    conflict = int(((~bit2_unknown) & hier).sum())                # 宣称 bit2=0 但真值有 ③ → 反例
    conflict1 = int(((~same_clu) & sc_ok).sum())
    res["S4_determinability"]["inference_selfcheck"] = {
        "bit2_false_zero_violations": conflict, "bit1_false_zero_violations": conflict1}

    # ---- S5 方案 a 原型 ----
    K = min(args.sample_nodes, n)
    cut = int(indptr[K])
    sub = {"indptr": indptr[:K + 1].copy(), "indices": indices[:cut].copy(), "weights": weights[:cut].copy()}
    typed = dict(sub); typed["types"] = mask[:cut].copy()
    legacy_p = os.path.join(P, "sample_legacy_3array.csr.npz")
    typed_p = os.path.join(P, "sample_typed_4array.csr.npz")
    z_legacy_p = os.path.join(P, "sample_legacy_3array.c.npz")
    z_typed_p = os.path.join(P, "sample_typed_4array.c.npz")
    np.savez(legacy_p, **sub); np.savez(typed_p, **typed)
    np.savez_compressed(z_legacy_p, **sub); np.savez_compressed(z_typed_p, **typed)
    b = lambda p: os.path.getsize(p)
    rt = np.load(typed_p)
    rt_ok = all(np.array_equal(rt[k], typed[k]) for k in typed)
    compat_ok = all(np.array_equal(np.load(typed_p)[k], sub[k]) for k in sub)
    u_of_s = np.repeat(np.arange(K, dtype=np.int64), np.diff(rt["indptr"]))

    def q(want):
        sel = (rt["types"] & want) == want
        return [{"u": nodes[int(u_of_s[j])]["term"], "v": nodes[int(rt["indices"][j])]["term"],
                 "w": round(float(rt["weights"][j]), 4), "mask": int(rt["types"][j])}
                for j in np.flatnonzero(sel)[:5]]

    full_raw = sum(int(z[k].nbytes) for k in z.keys())
    res["S5_prototype_a"] = {
        "sample": {"nodes": K, "edges": cut, "dir": "topics/audit/edgetype/proto/"},
        "files": [os.path.basename(legacy_p), os.path.basename(typed_p),
                  os.path.basename(z_legacy_p), os.path.basename(z_typed_p)],
        "roundtrip_ok": bool(rt_ok), "legacy_reader_compat_ok": bool(compat_ok),
        "bytes": {"legacy_3array": b(legacy_p), "typed_4array": b(typed_p),
                  "delta_uncompressed": b(typed_p) - b(legacy_p),
                  "legacy_savez_compressed": b(z_legacy_p), "typed_savez_compressed": b(z_typed_p),
                  "delta_compressed": b(z_typed_p) - b(z_legacy_p)},
        "sample_type_hist": {str(m): int((rt["types"] == m).sum()) for m in range(8)},
        "query_hier_sample": q(T_HIER), "query_samecluster_sample": q(T_SAMECL),
        "full_graph_projection": {
            "raw_array_bytes": full_raw, "with_types_u8": full_raw + E,
            "delta_bytes": E, "delta_pct_of_raw": round(E / full_raw * 100, 2),
            "delta_pct_of_file": round(E / os.path.getsize(apath) * 100, 2)},
        "query_cost": "位测试 O(deg) 向量化，与现有 CSR 遍历同阶，不引入新索引"}
    print(f"[S5] roundtrip={rt_ok} legacy_compat={compat_ok} delta={b(typed_p)-b(legacy_p)}B(样本) | "
          f"{time.time()-t0:.1f}s", flush=True)

    # ---- S6 方案成本 ----
    hier_n = int((mask & T_HIER).sum()); sc_n = int(sc_ok.sum())
    three_csr = 3 * (n + 1) * 8 + 2 * E * 8 + 2 * E * 4
    res["S6_scheme_cost"] = {
        "a_typemask_u8": {"extra_arrays": 1, "extra_bytes": E,
                          "schema": "additive（新增键 types）", "breakage": "无（旧读取方忽略新键）",
                          "query": "O(deg) 位测试", "migration": "重跑 P2 即可产出；无需重算节点"},
        "b_three_csr": {"extra_arrays": 6, "extra_bytes_est": three_csr,
                        "ratio_vs_a": round(three_csr / E, 2),
                        "breakage": "高：indptr 语义一分为三，现有读取方全部要改；②⊂① 无法独立成图",
                        "query": "单型查询少扫边，但跨型查询需三次遍历+合并",
                        "note": f"①{int((mask & T_COOCCUR).sum()):,} / ③{hier_n:,} / ②参与{sc_n:,}"},
        "c_status_quo": {"extra_arrays": 0, "extra_bytes": 0, "breakage": "无",
                         "query": "NPZ 内不可查；需重跑 P2 或读离线掩码",
                         "offline_mask": {"path": "topics/audit/edgetype/edge_type_mask.mask.npy",
                                          "bytes": int(mask.nbytes), "aligned_to": "edges.csr.npz 的 indices 行序"}}}
    np.save(os.path.join(A, "edge_type_mask.mask.npy"), mask)
    res["seconds"] = round(time.time() - t0, 1)
    rp = os.path.join(A, "edgetype-audit.json")
    json.dump(res, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[S6] 方案b外推={three_csr:,}B ({three_csr/E:.2f}×) vs 方案a={E:,}B | {time.time()-t0:.1f}s", flush=True)
    print(f"[done] -> {rp}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
