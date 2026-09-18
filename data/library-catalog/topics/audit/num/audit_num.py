#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_num.py — AUDIT-NUM 数值语义审计（独立重算，不引用施工方代码逻辑）

原则：期望值全部由**证据链**（card_topics.jsonl / cards.jsonl / nodes.json / index/clusters.npy）
      按交接文档 §3.2 的公式文字独立重算。施工方脚本（topic_edges.py 等）只读、不 import、
      不 exec、不复制其逻辑——本文件所有计数/权重/截断均为独立实现。

审计对象（只读）：
  topics/card_topics.jsonl     卡 → top-5 kw 证据链
  cards.jsonl                 卡 → cls2 / cls 类目证据（aug 成员、层级边投票）
  topics/nodes.json            节点表（freq / cluster / cls / type）
  topics/edges.csr.npz         主产物（当前）
  topics/edges.csr.pre-r1.npz  修复前基线（用于缺陷模型交叉验证）
  topics/edges.variant-spec.csr.npz  另一口径（spec：仅 kw 参与共现）
  index/clusters.npy           卡 → 400 簇标签（同簇加成、cluster 字段抽验）

期望公式（交接文档 §3.2 / meta.json.stages.P2.params）：
  ① 共现（双向）   w1 = log1p(min(共现书数, cap)) / log1p(cap)，cap=50
  ② 同簇加成（双向）w2 = 0.3 × log1p(簇内共现数) / log1p(cap)；combine=sum → w = min(1, w1+w2)
  ③ 层级（单向）   kw → 其卡级证据众数 cls2 节点，w3 = 1.0
  aug 成员 = 卡 top-5 kw ∪ {卡 cls2 节点}；同簇 = 卡簇标签 == cluster(u) == cluster(v)
  截断 = 每源点按排序键保留 top-20；assoc = cnt / √(freq_u · freq_v)（params.rank_by=assoc）

用法：PYTHONPATH=~/go/pylibs python3 audit_num.py [--data DIR] [--out DIR] [--sample 50]
"""
import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter

try:
    import numpy as np
except ImportError:  # pragma: no cover
    sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
    import numpy as np

DATA_DEFAULT = os.path.expanduser("~/go/lib-catalog-data")
LOG50 = math.log1p(50)
CAP = 50
TOL = 1e-6


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(paths):
    out = {}
    for p in paths:
        if os.path.exists(p):
            st = os.stat(p)
            out[p] = {"sha256": sha256(p), "size": st.st_size,
                      "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime))}
        else:
            out[p] = {"sha256": None, "size": None, "mtime": None}
    return out


def dist_stats(a):
    a = np.asarray(a)
    if len(a) == 0:
        return {}
    return {"n": int(len(a)), "min": float(a.min()), "median": float(np.median(a)),
            "mean": round(float(a.mean()), 4), "p90": float(np.percentile(a, 90)),
            "max": float(a.max())}


def recompute(data, top, sample_n):
    """独立重算：共现计数、同簇计数、层级边、卡级统计、P1 抽验累积。"""
    nodes = json.load(open(os.path.join(top, "nodes.json"), encoding="utf-8"))
    n = len(nodes)
    term = [x["term"] for x in nodes]
    typ = [x["type"] for x in nodes]
    freq = np.array([x["freq"] for x in nodes], dtype=np.int64)
    clus = np.array([x["cluster"] for x in nodes], dtype=np.int64)
    cls_field = [x["cls"] for x in nodes]
    cls2id = {x["term"]: x["id"] for x in nodes if x["type"] == "cls"}
    labels = np.load(os.path.join(data, "index", "clusters.npy"))

    # 抽样（按 freq 分层，确定性 linspace 取样）
    kw_ids = np.array([x["id"] for x in nodes if x["type"] == "kw"], dtype=np.int64)
    order = kw_ids[np.lexsort((kw_ids, freq[kw_ids]))]
    if sample_n >= len(order):
        sample = [int(x) for x in order]
    else:
        pos = np.linspace(0, len(order) - 1, sample_n).round().astype(int)
        sample = sorted(set(int(order[p]) for p in pos))
    samp_set = set(sample)
    low_terms = [(u, term[u].lower()) for u in sample]
    top5_cnt, raw_cnt = Counter(), Counter()
    clus_votes = {u: Counter() for u in sample}
    cls1_votes = {u: Counter() for u in sample}
    raw_clus_votes = {u: Counter() for u in sample}
    raw_cls1_votes = {u: Counter() for u in sample}
    clus_all = {u: Counter() for u in (int(x) for x in kw_ids)}
    cls1_all = {u: Counter() for u in (int(x) for x in kw_ids)}

    cnt, cnt_s, cnt_spec = {}, {}, {}
    hist = Counter()
    hier_votes = {}
    n_empty = n_cls2 = n_mismatch = n_lines = 0
    t0 = time.time()
    with open(os.path.join(data, "cards.jsonl"), encoding="utf-8") as fc, \
            open(os.path.join(top, "card_topics.jsonl"), encoding="utf-8") as ft:
        for i, (lc, lt) in enumerate(zip(fc, ft)):
            c = json.loads(lc)
            t = json.loads(lt)
            n_lines += 1
            if c.get("mms", "") != t.get("mms", ""):
                n_mismatch += 1
            tops = t["topics"]
            hist[len(tops)] += 1
            if not tops:
                n_empty += 1
            lab = int(labels[i])
            cid = cls2id.get((c.get("cls2") or "").strip().upper(), -1)
            items = list(tops)
            if cid >= 0:
                items.append(cid)
                n_cls2 += 1
                for u in tops:                       # 层级边投票：kw → 卡 cls2
                    hier_votes.setdefault(u, Counter())[cid] += 1
            # aug 口径：单轮枚举，每卡每无序对计一次
            for x in range(len(items)):
                ux = items[x]
                for y in range(x + 1, len(items)):
                    uy = items[y]
                    u, v = (ux, uy) if ux < uy else (uy, ux)
                    if u == v:
                        continue
                    k = u * n + v
                    cnt[k] = cnt.get(k, 0) + 1
                    if clus[u] == clus[v] == lab:     # 同簇加成
                        cnt_s[k] = cnt_s.get(k, 0) + 1
            # spec 口径：仅 top-5 kw 参与共现（计数与 aug 对同一对完全一致）
            for x in range(len(tops)):
                for y in range(x + 1, len(tops)):
                    u, v = (tops[x], tops[y]) if tops[x] < tops[y] else (tops[y], tops[x])
                    k = u * n + v
                    cnt_spec[k] = cnt_spec.get(k, 0) + 1
            # P1：全量复算 cluster / cls 证据累积 + 抽样卡频
            cls1 = (c.get("cls") or "").strip()
            for u in tops:
                clus_all[u][lab] += 1                      # 全量：卡簇标签投票
                if cls1:
                    cls1_all[u][cls1] += 1                 # 全量：卡一级类目投票
                if u in samp_set:
                    top5_cnt[u] += 1
                    clus_votes[u][lab] += 1
                    if cls1:
                        cls1_votes[u][cls1] += 1
            if samp_set:
                tl = (c.get("title") or "").lower()
                if tl:
                    for u, lt2 in low_terms:
                        if lt2 and lt2 in tl:          # 独立卡频代理：题名出现即计一卡
                            raw_cnt[u] += 1
                            raw_clus_votes[u][lab] += 1
                            if cls1:
                                raw_cls1_votes[u][cls1] += 1
    scan_s = time.time() - t0

    def arrays(d):
        ks = np.fromiter(d.keys(), dtype=np.int64, count=len(d))
        cs = np.fromiter(d.values(), dtype=np.int64, count=len(d))
        u, v = ks // n, ks % n
        o = np.lexsort((v, u))
        return u[o], v[o], cs[o]

    u, v, c = arrays(cnt)
    sc = np.array([cnt_s.get(int(a) * n + int(b), 0) for a, b in zip(u, v)], dtype=np.int64)
    su, sv, c_spec = arrays(cnt_spec)

    def w_of(ca, csa):
        w1 = np.log1p(np.minimum(ca, CAP)) / LOG50
        w2 = 0.3 * np.log1p(csa) / LOG50
        return w1, w2, np.minimum(1.0, w1 + w2)

    w1, w2, w = w_of(c, sc)
    sw1, sw2, sw = w_of(c_spec, np.zeros(len(c_spec), dtype=np.int64))
    typ_arr = np.array(typ, dtype=object)
    is_kw = (typ_arr[u] == "kw") & (typ_arr[v] == "kw")

    # ---- 全量复算 P1 的 cluster / cls 字段（用出厂证据链 top-5 卡集） ----
    full_cluster = {"declared_total": 0, "recomputable": 0, "match": 0,
                    "mismatch_ids": [], "mismatch_detail": []}
    full_cls = {"declared_total": 0, "with_cls1_evidence": 0, "match": 0, "fallback_used": 0,
                "mismatch_ids": [], "mismatch_detail": []}
    for i in range(n):
        if typ[i] != "kw":
            continue
        full_cluster["declared_total"] += 1
        cv = clus_all.get(i) or Counter()
        if cv:
            full_cluster["recomputable"] += 1
            exp = max(cv.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            if exp == clus[i]:
                full_cluster["match"] += 1
            else:
                full_cluster["mismatch_ids"].append(i)
                if len(full_cluster["mismatch_detail"]) < 200:
                    top = sorted(cv.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
                    full_cluster["mismatch_detail"].append(
                        {"id": i, "term": term[i], "declared": int(clus[i]), "recomputed": int(exp),
                         "declared_votes": int(cv.get(int(clus[i]), 0)), "recomputed_votes": int(top[0][1]),
                         "top2": [[int(a), int(b)] for a, b in top]})
        full_cls["declared_total"] += 1
        lv = cls1_all.get(i) or Counter()
        if lv:
            full_cls["with_cls1_evidence"] += 1
            exp = max(lv.items(), key=lambda kv: (kv[1], kv[0]))[0]
            if exp == cls_field[i]:
                full_cls["match"] += 1
            else:
                full_cls["mismatch_ids"].append(i)
                if len(full_cls["mismatch_detail"]) < 200:
                    top = sorted(lv.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
                    full_cls["mismatch_detail"].append(
                        {"id": i, "term": term[i], "declared": cls_field[i], "recomputed": exp,
                         "declared_votes": int(lv.get(cls_field[i], 0)), "recomputed_votes": int(top[0][1]),
                         "top2": [[a, int(b)] for a, b in top]})
        else:
            full_cls["fallback_used"] += 1
    full_cluster["match_rate"] = round(full_cluster["match"] / max(full_cluster["recomputable"], 1), 5)
    full_cls["match_rate"] = round(full_cls["match"] / max(full_cls["with_cls1_evidence"], 1), 5)

    # 影响面：字段不一致的节点在共现/截断链路上的暴露量
    exposure = {}
    for name, ids in (("cluster", full_cluster["mismatch_ids"]), ("cls", full_cls["mismatch_ids"])):
        m = np.zeros(n, dtype=bool)
        m[ids] = True
        inc = m[u] | m[v]
        exposure[name] = {
            "mismatch_nodes": len(ids),
            "pairs_incident": int(inc.sum()),
            "pairs_incident_with_same_cluster_bonus": int((inc & (sc > 0)).sum()),
            "distinct_pairs_total": int(len(u)),
            "share_of_pairs": round(float(inc.mean()), 5),
        }
    # cluster 字段直接喂 P2 同簇加成与 P3 冻结门槛（cluster_or_cls）
    exposure["note"] = ("cluster/cls 字段同时被 P2 同簇加成(②)与 P3 冻结门槛 cluster_or_cls 使用"
                        "（topic_edges.py: ncl/ncls 直读 nodes.json）")
    hier = {int(k): max(cc.items(), key=lambda kv: (kv[1], -kv[0]))[0] for k, cc in hier_votes.items()}
    stats = {
        "nodes": n, "kw": int(sum(1 for t in typ if t == "kw")),
        "cls": int(sum(1 for t in typ if t == "cls")), "cards": n_lines,
        "cards_with_cls2": n_cls2, "cards_empty_topics": n_empty,
        "cards_topic_count_hist": {str(k): int(x) for k, x in sorted(hist.items())},
        "mms_line_mismatch": n_mismatch,
        "pairs_aug_raw": int(c.sum()), "pairs_spec_raw": int(c_spec.sum()),
        "pairs_same_cluster_raw": int(sc.sum()),
        "distinct_pairs_aug": int(len(u)), "distinct_pairs_kwkw": int(is_kw.sum()),
        "distinct_pairs_same_cluster": int((sc > 0).sum()),
        "hierarchical_edges": len(hier),
        "kw_without_hier_edge": int(sum(1 for i in range(n) if typ[i] == "kw" and i not in hier)),
        "cooccur_count_dist": dist_stats(c), "cooccur_saturated_pairs": int((c >= CAP).sum()),
        "cooccur_saturated_share": round(float((c >= CAP).mean()), 4),
        "cooccur_singleton_share": round(float((c == 1).mean()), 4),
        "same_cluster_cnt_dist": dist_stats(sc), "same_cluster_hit_pairs": int((sc > 0).sum()),
        "w_ge_1_pair_share": round(float((w >= 1.0).mean()), 4),
        "scan_seconds": round(scan_s, 1),
    }
    p1 = {"sample": sample, "top5_cnt": dict(top5_cnt), "raw_cnt": dict(raw_cnt),
          "clus_votes": {str(k): {str(a): b for a, b in vv.items()} for k, vv in clus_votes.items()},
          "raw_clus_votes": {str(k): {str(a): b for a, b in vv.items()} for k, vv in raw_clus_votes.items()},
          "raw_cls1_votes": {str(k): dict(vv) for k, vv in raw_cls1_votes.items()},
          "cls1_votes": {str(k): dict(vv) for k, vv in cls1_votes.items()},
          "full_cluster": full_cluster, "full_cls": full_cls, "exposure": exposure}
    return {"u": u, "v": v, "c": c, "sc": sc, "w": w, "w1": w1, "w2": w2,
            "su": su, "sv": sv, "c_spec": c_spec, "sw": sw, "sw1": sw1, "sw2": sw2,
            "hier": hier, "hier_count": {int(k): int(max(vv.values())) for k, vv in hier_votes.items()},
            "freq": freq, "typ": typ, "typ_arr": typ_arr, "term": term,
            "clus": clus, "cls_field": cls_field, "nodes": nodes, "stats": stats, "p1": p1,
            "labels": labels}


def build_expected(R, primary, pairs="aug", double_kwkw=False, max_out=20, dedupe="intent"):
    """按公式 + 排序键独立重算每源点 top-max_out 边集。

    pairs: aug = 全部共现对；spec = 仅 kw-kw 对（两口径的 cnt/同簇计数相同）
    double_kwkw: 缺陷模型——kw-kw 对在 spec/aug 两轮各计一次（计数 ×2）
    dedupe: intent = 层级边排序键恒置顶（文档意图"结构边不被截断"）；
            code   = 同 (src,dst) 且权重并列时保留先出现的共现行（= 层级边的置顶键丢失）
    """
    n = len(R["freq"])
    freq = R["freq"]
    if pairs == "aug":
        pu, pv, pc, psc = R["u"], R["v"], R["c"], R["sc"]
    else:
        mask = (R["typ_arr"][R["su"]] == "kw") & (R["typ_arr"][R["sv"]] == "kw")
        pu, pv, pc = R["su"][mask], R["sv"][mask], R["c_spec"][mask]
        mapping = {int(a) * n + int(b): i for i, (a, b) in enumerate(zip(R["u"], R["v"]))}
        psc = np.array([R["sc"][mapping[int(a) * n + int(b)]] for a, b in zip(pu, pv)], dtype=np.int64)
    if double_kwkw:
        iskw = (R["typ_arr"][pu] == "kw") & (R["typ_arr"][pv] == "kw")
        pc = np.where(iskw, pc * 2, pc)
        psc = np.where(iskw, psc * 2, psc)
    pw = np.minimum(1.0, np.log1p(np.minimum(pc, CAP)) / LOG50 + 0.3 * np.log1p(psc) / LOG50)
    den = np.sqrt(np.maximum(freq[pu], 1) * np.maximum(freq[pv], 1))
    assoc = pc / den

    src = np.concatenate([pu, pv])
    dst = np.concatenate([pv, pu])
    ww = np.concatenate([pw, pw])
    rk = np.concatenate([assoc, assoc])
    hk = np.array(sorted(R["hier"].keys()), dtype=np.int64)
    if len(hk):
        src = np.concatenate([src, hk])
        dst = np.concatenate([dst, np.array([R["hier"][int(k)] for k in hk], dtype=np.int64)])
        ww = np.concatenate([ww, np.ones(len(hk))])
        rk = np.concatenate([rk, freq[hk].astype(np.float64) * 1e9])   # 层级边排序键置顶
    key = src.astype(np.int64) * n + dst
    if dedupe == "code":     # 与产物一致的"取最大权重行"去重：并列权重时保留先出现（共现）行
        o = np.lexsort((np.arange(len(src)), -ww, key))
        key_s = key[o]
        first = np.empty(len(key_s), dtype=bool)
        first[0] = True
        np.not_equal(key_s[1:], key_s[:-1], out=first[1:])
        t = o[first]
    else:                    # 文档意图：同键取最大排序键（层级边恒置顶）
        o = np.lexsort((-ww, -rk, key))
        key_s = key[o]
        first = np.empty(len(key_s), dtype=bool)
        first[0] = True
        np.not_equal(key_s[1:], key_s[:-1], out=first[1:])
        t = o[first]
    src, dst, ww, rk = src[t], dst[t], ww[t], rk[t]
    order = (np.lexsort((dst, -ww, -rk, src)) if primary == "assoc"
             else np.lexsort((dst, -rk, -ww, src)))
    src, dst, ww = src[order], dst[order], ww[order]
    starts = np.flatnonzero(np.r_[True, src[1:] != src[:-1]])
    counts = np.diff(np.r_[starts, len(src)])
    rank = np.arange(len(src)) - np.repeat(starts, counts)
    keep = rank < max_out
    return src[keep], dst[keep], ww[keep], (src, dst, ww)


def load_csr(path):
    z = np.load(path)
    ind, idx, wts = z["indptr"], z["indices"], z["weights"]
    src = np.repeat(np.arange(len(ind) - 1, dtype=np.int64), np.diff(ind))
    return src, idx.astype(np.int64), wts.astype(np.float64)


def evidence_table(R, pairs="aug", double_kwkw=False):
    """有证据边全集（含层级边），同 (u,v) 去重取最大 w，返回 key→(w,c,sc,w1,w2)。"""
    n = len(R["freq"])
    if pairs == "aug":
        pu, pv, pc, psc = R["u"], R["v"], R["c"], R["sc"]
    else:
        mask = (R["typ_arr"][R["su"]] == "kw") & (R["typ_arr"][R["sv"]] == "kw")
        pu, pv, pc = R["su"][mask], R["sv"][mask], R["c_spec"][mask]
        mapping = {int(a) * n + int(b): i for i, (a, b) in enumerate(zip(R["u"], R["v"]))}
        psc = np.array([R["sc"][mapping[int(a) * n + int(b)]] for a, b in zip(pu, pv)], dtype=np.int64)
    if double_kwkw:
        iskw = (R["typ_arr"][pu] == "kw") & (R["typ_arr"][pv] == "kw")
        pc = np.where(iskw, pc * 2, pc)
        psc = np.where(iskw, psc * 2, psc)
    w1 = np.log1p(np.minimum(pc, CAP)) / LOG50
    w2 = 0.3 * np.log1p(psc) / LOG50
    w = np.minimum(1.0, w1 + w2)
    src = np.concatenate([pu, pv])
    dst = np.concatenate([pv, pu])
    allk = src * n + dst
    allc = np.concatenate([pc, pc])
    allsc = np.concatenate([psc, psc])
    allw1 = np.concatenate([w1, w1])
    allw2 = np.concatenate([w2, w2])
    allw = np.concatenate([w, w])
    hk = np.array(sorted(R["hier"].keys()), dtype=np.int64)
    if len(hk):
        hd = np.array([R["hier"][int(k)] for k in hk], dtype=np.int64)
        allk = np.concatenate([allk, hk * n + hd])
        allc = np.concatenate([allc, np.zeros(len(hk), dtype=np.int64)])
        allsc = np.concatenate([allsc, np.zeros(len(hk), dtype=np.int64)])
        allw1 = np.concatenate([allw1, np.ones(len(hk))])
        allw2 = np.concatenate([allw2, np.zeros(len(hk))])
        allw = np.concatenate([allw, np.ones(len(hk))])
    o = np.lexsort((-allw, allk))
    ks = allk[o]
    first = np.empty(len(ks), dtype=bool)
    first[0] = True
    np.not_equal(ks[1:], ks[:-1], out=first[1:])
    sel = o[first]
    return {"key": ks[first], "w": allw[sel], "c": allc[sel], "sc": allsc[sel],
            "w1": allw1[sel], "w2": allw2[sel]}


def cmp_edges(R, art_path, ev, exp_primary, exp_alt, labels=("primary", "alt"), topn=12):
    n = len(R["freq"])
    ds, dd, dw = load_csr(art_path)
    dkey = ds * n + dd
    pos = np.searchsorted(ev["key"], dkey)
    pos = np.clip(pos, 0, len(ev["key"]) - 1)
    found = ev["key"][pos] == dkey
    buckets = Counter()
    samples = []
    ec, esc, ew = ev["c"][pos], ev["sc"][pos], ev["w"][pos]
    ew1, ew2 = ev["w1"][pos], ev["w2"][pos]
    delta = np.where(found, np.abs(dw - ew), np.nan)
    float_stats = {"max_abs_delta": round(float(np.nanmax(delta)), 9),
                   "mean_abs_delta": round(float(np.nanmean(delta)), 9),
                   "over_1e-6": int(np.nansum(delta > TOL))}
    for i in range(len(dkey)):
        if not found[i]:
            buckets["extra_no_evidence"] += 1
            if len(samples) < topn:
                samples.append({"kind": "extra_no_evidence", "src": int(ds[i]), "dst": int(dd[i]),
                                "term_src": R["term"][ds[i]], "term_dst": R["term"][dd[i]],
                                "disk_w": round(float(dw[i]), 6)})
            continue
        wd, we = float(dw[i]), float(ew[i])
        if abs(wd - we) <= TOL:
            buckets["ok"] += 1
            continue
        c, sc, w2v = float(ec[i]), float(esc[i]), float(ew2[i])
        alt = {"formula_missing_cluster_bonus": float(ew1[i]),
               "formula_max_combine": float(max(ew1[i], ew2[i])),
               "formula_uncapped_log1p": float(math.log1p(c) / LOG50)}
        hit = None
        for name, val in alt.items():
            if abs(wd - val) <= 1e-5:
                hit = name
                break
        if hit is None:
            base = wd - w2v
            imp = math.expm1(base * LOG50) if base > 0 else 0.0
            if abs(imp - 2 * c) <= max(1.0, 0.05 * c):
                hit = "count_double"
            else:
                hit = "count_mismatch"
        buckets[hit] += 1
        if len(samples) < topn:
            samples.append({"kind": hit, "src": int(ds[i]), "dst": int(dd[i]),
                            "term_src": R["term"][ds[i]], "term_dst": R["term"][dd[i]],
                            "disk_w": round(wd, 6), "exp_w": round(we, 6),
                            "cnt_evidence": int(c), "cnt_sc_evidence": int(sc),
                            "implied_cnt": (round(math.expm1(max(wd - w2v, 0) * LOG50), 2)
                                            if wd - w2v > 0 else 0)})

    def sets(src, dst):
        d = {}
        for a, b in zip(src.tolist(), dst.tolist()):
            d.setdefault(a, set()).add(b)
        return d

    D = sets(ds, dd)
    EP, EA = sets(exp_primary[0], exp_primary[1]), sets(exp_alt[0], exp_alt[1])
    slot = Counter()
    ex = []
    for u in range(n):
        du = D.get(u, set())
        ep, ea = EP.get(u, set()), EA.get(u, set())
        slot["sources_total"] += 1
        if du == ep:
            slot["src_exact_match_" + labels[0]] += 1
        if du == ea:
            slot["src_exact_match_" + labels[1]] += 1
        slot["slot_diff_vs_" + labels[0]] += len(du ^ ep)
        slot["slot_diff_vs_" + labels[1]] += len(du ^ ea)
        for v in sorted(du - ep):
            tag = "extra_in_alt" if v in ea else "extra_unexplained"
            slot[tag] += 1
            if len(ex) < topn:
                ex.append({"kind": "disk_extra", "src": u, "dst": int(v), "in_alt_top20": v in ea,
                           "term_src": R["term"][u], "term_dst": R["term"][v]})
        for v in sorted(ep - du):
            tag = "missing_in_alt" if v in ea else "missing_unexplained"
            slot[tag] += 1
            if len(ex) < topn:
                ex.append({"kind": "expected_missing", "src": u, "dst": int(v), "in_alt_top20": v in ea,
                           "term_src": R["term"][u], "term_dst": R["term"][v]})
    return {"path": art_path, "disk_edges": int(len(dkey)), "with_evidence": int(found.sum()),
            "extra_no_evidence": int((~found).sum()), "float_delta": float_stats,
            "weight_buckets": dict(buckets), "weight_samples": samples,
            "truncation": dict(slot), "truncation_samples": ex}


def hier_audit(R, art_path, topn=12):
    """层级边（主题 → 众数 cls2，w=1.0）在产物中的存活性审计。

    关注：层级边与共现边同键、且共现权重同为 1.0 时，去重保留共现行 → 层级边的
    「置顶排序键」丢失，可能被 top-20 截断挤出（与文档"结构边不被截断"的意图不符）。
    """
    n = len(R["freq"])
    pair_cnt = {int(a) * n + int(b): int(c) for a, b, c in zip(R["u"], R["v"], R["c"])}
    pair_sc = {int(a) * n + int(b): int(c) for a, b, c in zip(R["u"], R["v"], R["sc"])}
    ds, dd, dw = load_csr(art_path)
    present = set(zip(ds.tolist(), dd.tolist()))
    missing, at_risk = [], []
    for u, cid in R["hier"].items():
        a, b = (u, cid) if u < cid else (cid, u)
        c = pair_cnt.get(a * n + b, 0)
        s = pair_sc.get(a * n + b, 0)
        wp = min(1.0, math.log1p(min(c, CAP)) / LOG50 + 0.3 * math.log1p(s) / LOG50)
        rec = {"src": u, "term_src": R["term"][u], "dst": cid, "term_dst": R["term"][cid],
               "votes": R["hier_count"][u], "cooccur_cnt": c, "cooccur_same_cluster": s,
               "cooccur_w": round(wp, 6),
               "assoc": round(c / math.sqrt(max(R["freq"][u], 1) * max(R["freq"][cid], 1)), 6)}
        if wp >= 1.0 - 1e-12:
            at_risk.append(rec)
        if (u, cid) not in present:
            r2 = dict(rec)
            r2["replacement_edges"] = [
                {"dst": int(v), "term": R["term"][int(v)], "w": round(float(w2v), 6),
                 "type": R["typ"][int(v)]}
                for v, w2v in sorted(((int(b2), float(a2)) for a2, b2 in
                                      zip(dw[ds == u], dd[ds == u])), key=lambda x: -x[1])[:3]]
            missing.append(r2)
    return {"expected_hier_edges": len(R["hier"]),
            "duplicate_key_at_risk": len(at_risk),
            "present_in_artifact": len(R["hier"]) - len(missing),
            "missing_in_artifact": len(missing),
            "missing_share_of_kw": round(len(missing) / max(R["stats"]["kw"], 1), 5),
            "missing_detail": missing[:topn],
            "at_risk_sample": at_risk[:topn]}


def registrar_check(meta_path, report_path, R, art_path):
    """登记（meta.json / p2-build-report.json）与产物（CSR）逐项一致性。"""
    meta = json.load(open(meta_path, encoding="utf-8"))
    P2 = meta.get("stages", {}).get("P2", {})
    ds, dd, dw = load_csr(art_path)
    n = len(R["freq"])
    deg = np.bincount(ds, minlength=n)
    meas = {
        "counts": dict(R["stats"], edges_final=int(len(ds))),
        "edge_stats": {
            "edges": int(len(ds)), "avg_out_degree": round(float(deg.mean()), 3),
            "isolated_out0": int((deg == 0).sum()),
            "out_degree_max": int(deg.max()),
            "weight_min": round(float(dw.min()), 4), "weight_median": round(float(np.median(dw)), 4),
            "weight_mean": round(float(dw.mean()), 4), "weight_p90": round(float(np.percentile(dw, 90)), 4),
            "weight_max": round(float(dw.max()), 4),
            "w_eq_1_share": round(float((dw >= 1.0).mean()), 4),
            "cooccur_count_dist": R["stats"]["cooccur_count_dist"],
            "cooccur_saturated_pairs": R["stats"]["cooccur_saturated_pairs"],
            "cooccur_saturated_share": R["stats"]["cooccur_saturated_share"],
            "cooccur_singleton_share": R["stats"]["cooccur_singleton_share"],
            "distinct_pairs_aug": R["stats"]["distinct_pairs_aug"],
            "hierarchical_edges": R["stats"]["hierarchical_edges"],
        },
    }
    out = {"meta_generated_at": P2.get("generated_at"), "files": {}, "mismatch": [], "unregistered": []}
    rep = json.load(open(report_path, encoding="utf-8")) if report_path and os.path.exists(report_path) else {}
    for src_name, reg in (("meta.json#stages.P2.counts", P2.get("counts", {})),
                          ("meta.json#stages.P2.edge_stats", P2.get("edge_stats", {})),
                          ("p2-build-report.json#counts", rep.get("counts", {})),
                          ("p2-build-report.json#edge_stats", rep.get("edge_stats", {}))):
        for k, v in reg.items():
            if k in ("chosen",):
                continue
            if k in meas["counts"]:
                got = meas["counts"][k]
            elif k in meas["edge_stats"]:
                got = meas["edge_stats"][k]
            else:
                out["unregistered"].append({"registry": src_name, "key": k, "registered": v,
                                            "note": "本审计未独立复算该项"})
                continue
            if isinstance(v, dict) or isinstance(got, dict):
                continue
            try:
                same = abs(float(v) - float(got)) <= (1e-4 if isinstance(got, float) else 0)
            except (TypeError, ValueError):
                same = v == got
            if not same:
                out["mismatch"].append({"registry": src_name, "key": k, "registered": v,
                                        "recomputed": got})
    # 产物 vs 登记：层级边实际存在数
    hier = hier_audit(R, art_path)
    out["hierarchy_actual"] = {"registered": P2.get("counts", {}).get("hierarchical_edges"),
                               "evidence_expected": hier["expected_hier_edges"],
                               "present_in_artifact": hier["present_in_artifact"],
                               "missing_in_artifact": hier["missing_in_artifact"]}
    out["files"]["meta.json"] = {"generated_at": P2.get("generated_at"), "seconds": P2.get("seconds")}
    return out


def slot_diff(R, art_path, exp):
    """产物每源点 top-20 与期望边集的槽位差（轻量，用于排序键口径探针）。"""
    n = len(R["freq"])
    ds, dd, _ = load_csr(art_path)
    D = {}
    for a, b in zip(ds.tolist(), dd.tolist()):
        D.setdefault(a, set()).add(b)
    E = {}
    for a, b in zip(exp[0].tolist(), exp[1].tolist()):
        E.setdefault(a, set()).add(b)
    diff = 0
    match = 0
    extra = missing = 0
    for u in range(n):
        du, eu = D.get(u, set()), E.get(u, set())
        if du == eu:
            match += 1
        diff += len(du ^ eu)
        extra += len(du - eu)
        missing += len(eu - du)
    return {"sources_exact_match": match, "sources_total": n,
            "slot_diff": diff, "extra": extra, "missing": missing,
            "match_rate": round(match / n, 4)}


def p1_audit(R, sample):
    nodes = R["nodes"]
    res = {"freq": [], "cluster": {}, "cls": {}}
    f_ok = c_ok = cl_ok = 0
    for i in sample:
        nd = nodes[i]
        t5 = R["p1"]["top5_cnt"].get(i, 0)
        raw = R["p1"]["raw_cnt"].get(i, 0)
        res["freq"].append({"id": i, "term": nd["term"], "freq": nd["freq"], "top5_cards": t5,
                            "raw_title_cards": raw, "geq_top5": nd["freq"] >= t5,
                            "ratio_freq_top5": (round(nd["freq"] / t5, 3) if t5 else None)})
        f_ok += int(nd["freq"] >= t5)
        cv = {int(k): v for k, v in R["p1"]["clus_votes"].get(str(i), {}).items()}
        exp_cl = max(cv.items(), key=lambda kv: (kv[1], -kv[0]))[0] if cv else None
        res["cluster"][str(i)] = {"term": nd["term"], "declared": nd["cluster"], "recomputed": exp_cl,
                                  "match": exp_cl == nd["cluster"], "evidence_cards": sum(cv.values())}
        c_ok += int(exp_cl == nd["cluster"])
        lv = R["p1"]["cls1_votes"].get(str(i), {})
        exp_cls = max(lv.items(), key=lambda kv: (kv[1], kv[0]))[0] if lv else None
        res["cls"][str(i)] = {"term": nd["term"], "declared": nd["cls"], "recomputed": exp_cls,
                              "match": exp_cls == nd["cls"], "evidence_cards": sum(lv.values()),
                              "fallback_needed": exp_cls is None}
        cl_ok += int(exp_cls == nd["cls"])
    ns = len(sample)
    res["summary"] = {
        "n": ns, "freq_geq_top5": f_ok, "freq_geq_top5_rate": round(f_ok / ns, 3),
        "freq_eq_top5": sum(1 for r in res["freq"] if r["freq"] == r["top5_cards"]),
        "freq_eq_raw_title": sum(1 for r in res["freq"] if r["freq"] == r["raw_title_cards"]),
        "cluster_match": c_ok, "cluster_match_rate": round(c_ok / ns, 3),
        "cls_match": cl_ok, "cls_match_rate": round(cl_ok / ns, 3),
        "cls_fallback_cases": sum(1 for v in res["cls"].values() if v["fallback_needed"]),
    }
    return res


ARTIFACTS = ("edges.csr.npz", "edges.csr.pre-r1.npz", "edges.variant-spec.csr.npz")
FILES = ("topics/card_topics.jsonl", "topics/nodes.json", "topics/meta.json",
         "topics/p2-build-report.json", "topics/p2-build.log", "cards.jsonl",
         "index/clusters.npy")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA_DEFAULT)
    ap.add_argument("--out", default=os.path.join(DATA_DEFAULT, "topics", "audit", "num"))
    ap.add_argument("--sample", type=int, default=50)
    ap.add_argument("--top-div", type=int, default=12)
    a = ap.parse_args()
    top = os.path.join(a.data, "topics")
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    targets = [os.path.join(a.data, f) for f in FILES] + [os.path.join(top, f) for f in ARTIFACTS]
    snap0 = snapshot(targets)
    print("[snapshot] 已记录 %d 个输入的 sha256" % len(targets), flush=True)

    R = recompute(a.data, top, a.sample)
    print("[recompute] %.1fs distinct=%d kwkw=%d sc=%d hier=%d raw_pairs=%d" %
          (R["stats"]["scan_seconds"], R["stats"]["distinct_pairs_aug"],
           R["stats"]["distinct_pairs_kwkw"], R["stats"]["distinct_pairs_same_cluster"],
           R["stats"]["hierarchical_edges"], R["stats"]["pairs_aug_raw"]), flush=True)
    json.dump(R["stats"], open(os.path.join(a.out, "recompute.json"), "w"),
              ensure_ascii=False, indent=2)

    EV_AUG = evidence_table(R, "aug")
    EV_AUG_D = evidence_table(R, "aug", double_kwkw=True)
    EV_SPEC = evidence_table(R, "spec")
    EXP_A = build_expected(R, "assoc")
    EXP_A_CODE = build_expected(R, "assoc", dedupe="code")
    EXP_W = build_expected(R, "weight")
    EXP_W_D = build_expected(R, "weight", double_kwkw=True)
    EXP_W_D_CODE = build_expected(R, "weight", double_kwkw=True, dedupe="code")
    EXP_A_SPEC = build_expected(R, "assoc", pairs="spec")
    EXP_W_SPEC = build_expected(R, "weight", pairs="spec")
    print("[expected] 有证据边 aug=%d spec=%d | top20 intent=%d code_model=%d spec=%d" %
          (len(EV_AUG["key"]), len(EV_SPEC["key"]), len(EXP_A[0]), len(EXP_A_CODE[0]),
           len(EXP_A_SPEC[0])), flush=True)

    div = {"snapshot_start": snap0, "artifacts": {}}
    plan = {
        "edges.csr.npz": (EV_AUG, EXP_A, EXP_A_CODE, ("intent", "code_model")),
        "edges.csr.pre-r1.npz": (EV_AUG_D, EXP_W_D, EXP_W_D_CODE, ("intent_defect", "code_model_defect")),
        "edges.variant-spec.csr.npz": (EV_SPEC, EXP_A_SPEC, EXP_W_SPEC, ("spec_intent", "spec_weight")),
    }
    for fname in ARTIFACTS:
        p = os.path.join(top, fname)
        if not os.path.exists(p):
            continue
        ev, e1, e2, lb = plan[fname]
        r = cmp_edges(R, p, ev, e1, e2, labels=lb, topn=a.top_div)
        div["artifacts"][fname] = r
        print("[cmp] %-28s edges=%d 有证据=%d 权重非ok=%s | 槽位差 intent=%d code_model=%d" %
              (fname, r["disk_edges"], r["with_evidence"],
               {k: v for k, v in r["weight_buckets"].items() if k != "ok"},
               r["truncation"]["slot_diff_vs_" + lb[0]],
               r["truncation"]["slot_diff_vs_" + lb[1]]), flush=True)

    # ---- 排序键口径探针（主产物 vs 三种期望模型） ----
    cur = os.path.join(top, "edges.csr.npz")
    if os.path.exists(cur):
        div["ordering_probe"] = {
            "vs_assoc_intent": slot_diff(R, cur, EXP_A),
            "vs_weight_intent": slot_diff(R, cur, EXP_W),
            "vs_code_model_dedupe": slot_diff(R, cur, EXP_A_CODE),
        }
        print("[probe] 主产物槽位差：assoc期望 %d | weight期望 %d | 代码去重模型 %d" %
              (div["ordering_probe"]["vs_assoc_intent"]["slot_diff"],
               div["ordering_probe"]["vs_weight_intent"]["slot_diff"],
               div["ordering_probe"]["vs_code_model_dedupe"]["slot_diff"]), flush=True)

    # ---- 层级边存活性（本审计主发现） ----
    div["hierarchy"] = {}
    for fname in ARTIFACTS:
        p = os.path.join(top, fname)
        if os.path.exists(p):
            div["hierarchy"][fname] = hier_audit(R, p, topn=a.top_div)
    h = div["hierarchy"].get("edges.csr.npz", {})
    print("[hier] 期望 %d | 产物存在 %d | 缺失 %d | 同键并列权重高危 %d" %
          (h.get("expected_hier_edges", 0), h.get("present_in_artifact", 0),
           h.get("missing_in_artifact", 0), h.get("duplicate_key_at_risk", 0)), flush=True)

    # ---- 方法论自证：pre-r1 与「kw-kw 对双计」缺陷模型的吻合率 ----
    pre = os.path.join(top, "edges.csr.pre-r1.npz")
    if os.path.exists(pre):
        ds, dd, dw = load_csr(pre)
        key = ds * len(R["freq"]) + dd
        pos = np.clip(np.searchsorted(EV_AUG_D["key"], key), 0, len(EV_AUG_D["key"]) - 1)
        mod = EV_AUG_D["w"][pos]
        pos2 = np.clip(np.searchsorted(EV_AUG["key"], key), 0, len(EV_AUG["key"]) - 1)
        sgl = EV_AUG["w"][pos2]
        iskw = (R["typ_arr"][ds] == "kw") & (R["typ_arr"][dd] == "kw")
        match_mod = np.abs(dw - mod) <= 1e-5
        match_sgl = np.abs(dw - sgl) <= 1e-5
        div["methodology_proof"] = {
            "note": "pre-r1 权重 vs 独立重算：按对型建模（kw-kw 双计 / kw-cls 单计）= 缺陷模型；"
                    "若反事实地给全部对都双计则只吻合 kw-kw 那部分",
            "pre_r1_edges": int(len(dw)),
            "match_defect_model_per_pairtype": int(match_mod.sum()),
            "match_rate_per_pairtype": round(float(match_mod.mean()), 6),
            "match_single_count_model": int(match_sgl.sum()),
            "match_rate_single": round(float(match_sgl.mean()), 6),
            "kwkw_edges_in_pre_r1": int(iskw.sum()),
            "kwkw_match_rate": round(float(match_mod[iskw].mean()), 6) if iskw.any() else None,
            "kwcls_match_rate": round(float(match_mod[~iskw].mean()), 6) if (~iskw).any() else None,
        }
        print("[proof] pre-r1 vs 按对型缺陷模型 %.6f（kw-kw %s / kw-cls %s）；vs 单计模型 %.6f" %
              (div["methodology_proof"]["match_rate_per_pairtype"],
               div["methodology_proof"]["kwkw_match_rate"],
               div["methodology_proof"]["kwcls_match_rate"],
               div["methodology_proof"]["match_rate_single"]), flush=True)

    # ---- 登记 vs 产物 逐项一致性 ----
    div["registrar"] = registrar_check(os.path.join(top, "meta.json"),
                                       os.path.join(top, "p2-build-report.json"), R,
                                       os.path.join(top, "edges.csr.npz"))
    json.dump(div["registrar"], open(os.path.join(a.out, "registrar.json"), "w"),
              ensure_ascii=False, indent=2)
    print("[registrar] 登记-产物不一致 %d 项：%s" %
          (len(div["registrar"]["mismatch"]),
           [(m["key"], m["registered"], m["recomputed"]) for m in div["registrar"]["mismatch"]][:6]),
          flush=True)

    p1 = p1_audit(R, R["p1"]["sample"])
    p1["full_cluster"] = R["p1"]["full_cluster"]
    p1["full_cls"] = R["p1"]["full_cls"]
    p1["exposure"] = R["p1"]["exposure"]
    p1["raw_evidence_check"] = {}
    for u in R["p1"]["sample"]:
        rc = {int(k): v for k, v in R["p1"]["raw_clus_votes"].get(str(u), {}).items()}
        rl = R["p1"]["raw_cls1_votes"].get(str(u), {})
        p1["raw_evidence_check"][str(u)] = {
            "term": R["term"][u], "declared_cluster": int(R["clus"][u]),
            "declared_cls": R["cls_field"][u], "raw_cards": sum(rc.values()),
            "cluster_raw_mode": (int(max(rc.items(), key=lambda kv: (kv[1], -kv[0]))[0]) if rc else None),
            "cls1_raw_mode": (max(rl.items(), key=lambda kv: (kv[1], kv[0]))[0] if rl else None)}
    json.dump(p1, open(os.path.join(a.out, "p1.json"), "w"), ensure_ascii=False, indent=2)
    print("[p1-full] cluster 一致 %d/%d (%.4f) | cls 一致 %d/%d (%.4f) | cls 无证据回退 %d" %
          (p1["full_cluster"]["match"], p1["full_cluster"]["recomputable"],
           p1["full_cluster"]["match_rate"], p1["full_cls"]["match"],
           p1["full_cls"]["with_cls1_evidence"], p1["full_cls"]["match_rate"],
           p1["full_cls"]["fallback_used"]), flush=True)
    json.dump(div, open(os.path.join(a.out, "divergence.json"), "w"), ensure_ascii=False, indent=2)
    snap1 = snapshot(targets)
    drift = [k for k in snap0 if snap0[k]["sha256"] != snap1[k]["sha256"]]
    json.dump({"start": snap0, "end": snap1, "changed_during_audit": drift},
              open(os.path.join(a.out, "snapshot.json"), "w"), ensure_ascii=False, indent=2)
    print("[p1] n=%d freq>=top5 %d/%d | cluster %d/%d | cls %d/%d | fallback %d" %
          (p1["summary"]["n"], p1["summary"]["freq_geq_top5"], p1["summary"]["n"],
           p1["summary"]["cluster_match"], p1["summary"]["n"],
           p1["summary"]["cls_match"], p1["summary"]["n"], p1["summary"]["cls_fallback_cases"]),
          flush=True)
    print("[snapshot] 审计期间变动: %s" % (drift or "无"), flush=True)
    print("[done] %.1fs -> %s" % (time.time() - t0, a.out), flush=True)


if __name__ == "__main__":
    main()
