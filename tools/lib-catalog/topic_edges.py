#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topic_edges.py — P2 主题图边构建器（产出 topics/edges.csr.npz + topics/card_topics.jsonl）

依据交接文档 §3.2 / §3.3：
  ① 共现边（主）  w1 = log1p(min(共现书数, 50)) / log1p(50)          ∈ [0,1]
  ② 同簇边        w2 = 0.3 × log1p(簇内共现数) / log1p(50)            （降权加成，见下）
  ③ 层级边        主题 → 其主 CLC 类目（nodes.json 的 cls 字段），w3 = 1.0，单向
  出度控制：每节点保留 top-20（按权重，平局按共现书数、再按目标 id）
  权重归一：三类公式均已归一到 [0,1]（归一因子 log1p(50)；w3=1.0），最终 clamp 到 [0,1]

口径细化（写进 meta 的 stages.P2.params，供 P3/P5 对齐）：
  * B1 卡→主题（card_topics.jsonl）：每卡取标题字段内 TF-IDF 最高 top-M（默认 10，与 P1 同源）
    token → build_graph.merge_bigrams 链式合并 → 命中 nodes.json 的 kw 词；
    词权 score(card, term) = Σ_{t ∈ 卡标题 token 且 t ⊆ term} tfidf(card, t)
    （ASCII 主题 = 单个 token 精确命中；含 CJK 主题 = 组成该词的相邻 bigram 之和）
    取 score 前 5（平局按节点 id 升序）。**cls 节点不占 top-5 名额**（无词权定义，§3.2 由层级边承载）。
  * B2 共现对成员：默认 = 卡 top-5 kw（spec 口径）；`--cls-in-cooccurrence yes` 时额外并入卡的 cls2 节点
    （cls 是 §3.1 的"类目主题"，并入可避免类目节点成为出度 0 的汇点、改善 12 跳覆盖）。
    两个口径的统计都会算出来，`--variant auto` 按 12 跳覆盖自动选择并落盘（另一口径另存 variant 文件）。
  * B3 组合方式（--combine）：sum = min(1, w1+w2)（默认；② 作为同簇加成，排名有实际影响）；
    max = max(w1, w2)（数学上恒等于 w1，因 cnt_sc ≤ cnt ⟹ 0.3·log1p(cnt_sc) ≤ log1p(cnt)，② 退化为无效项）。
  * 同簇共现（cnt_sc）定义：卡 i 的簇标签 labels[i] == cluster(u) == cluster(v) 时，该卡对 (u,v) 的计数。

用法：
  python3 topic_edges.py [--data DIR] [--out DIR] [--top-per-card 10] [--top-k 5]
                         [--max-out 20] [--cap-count 50] [--combine sum|max]
                         [--cls-in-cooccurrence auto|no|yes] [--variant auto|spec|aug]
                         [--seed 42] [--report topics/p2-build-report.json]
"""
import argparse
import json
import math
import os
import sys
import time
from collections import Counter

_PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)
import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from build_graph import merge_bigrams
from topic_build import (CJK_RE, build_a_matcher, is_stop, iter_card, load_source_a,
                         load_subject_lexicon, match_a, merged_card_words, normalize_cls,
                         normalize_term, term_ok_kw, top_title_tokens)

DATA_DEFAULT = os.path.expanduser("~/go/lib-catalog-data")
LOG50 = math.log1p(50)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def tri_index(u, v, n):
    """无向对 (u<v) → 三角索引（向量化）。"""
    return n * u - (u * (u + 1)) // 2 + (v - u - 1)


def tri_size(n):
    return n * (n - 1) // 2


def term_score(term, tok_w):
    """score(card, term) = Σ tfidf(卡标题 token) ，ASCII 精确 / CJK 相邻 bigram 求和。"""
    if CJK_RE.search(term):
        if len(term) < 2:
            return tok_w.get(term, 0.0)
        s = 0.0
        for j in range(len(term) - 1):
            s += tok_w.get(term[j:j + 2], 0.0)
        return s
    return tok_w.get(term, 0.0)


def percentile(a, p):
    return float(np.percentile(a, p)) if len(a) else 0.0


def dist_stats(a):
    a = np.asarray(a)
    if a.size == 0:
        return {"n": 0, "min": 0, "median": 0, "mean": 0, "p90": 0, "max": 0}
    return {"n": int(a.size), "min": float(a.min()), "median": float(np.median(a)),
            "mean": float(a.mean()), "p90": percentile(a, 90), "max": float(a.max())}


def apply_mutual_bonus(src, dst, rk, n, max_out, bonus):
    """把"互相都在对方 top-max_out 内"的边的排序键放大 (1+bonus) 倍。
    依据：top-20 截断会丢弃大量反向边，使有向可达远低于无向可达（实测主体图无向闭包覆盖 0.92 vs 有向 0.79）。"""
    o = np.lexsort((dst, -rk, src))
    s_s, d_s = src[o], dst[o]
    starts = np.flatnonzero(np.r_[True, s_s[1:] != s_s[:-1]])
    counts = np.diff(np.r_[starts, len(s_s)])
    rank = np.arange(len(s_s)) - np.repeat(starts, counts)
    key = s_s.astype(np.int64) * n + d_s
    ok = np.argsort(key, kind="stable")
    key_s, rank_s = key[ok], rank[ok]
    rev = d_s.astype(np.int64) * n + s_s
    pos = np.clip(np.searchsorted(key_s, rev), 0, len(key_s) - 1)
    rev_rank = np.where(key_s[pos] == rev, rank_s[pos], max_out + 1)
    mutual_sorted = rev_rank <= max_out
    mutual = np.empty(len(src), dtype=bool)
    mutual[o] = mutual_sorted
    return rk * np.where(mutual, 1.0 + bonus, 1.0)


def topk_csr(src, dst, w, tie, n, max_out, primary="assoc", tmask=None):
    """矢量化 top-k 截断 + CSR 组装。src/dst 已含双向边。

    R1 修复②：排序键顺序必须与 --rank-by 语义一致。
      primary="assoc"：**先比关联度 tie，再比权重 w**（键序 src ↑ → tie ↓ → w ↓ → dst ↑）——
        修复前键序是 src ↑ → w ↓ → tie ↓，assoc 只作权重平局时的 tie-break，`--rank-by assoc` 实际未生效。
      primary="weight"：键序 src ↑ → w ↓ → tie ↓ → dst ↑（§3.2 字面"按权重"，仅用于对照复现）。
    两种模式下层级边（tie=1e9 且 w=1.0）都排在最前，保证主题→cls2 结构边不被截断。

    R2-A 修复 D1（依据 topics/audit/num/REPORT.md §4）：
      去重键序由「同键取最大权重（并列取先出现行）」改为「同键取最大排序键，再取最大权重」。
      修复前：层级边 u→cid 与同键共现边 u→cid 权重并列 1.0 时，按"先出现的共现行"胜出，
      该行的排序键退化为 assoc（0.02–0.03），登记置顶的 tie=nfreq×1e9 被丢弃，
      边随即参与 top-max_out 竞争并被挤出（实测 9 条，登记 4,832 / 产物 4,823）。
      修复后：同键保留 tie 最大者 ⇒ 层级边保住置顶键，结构边不再被截断。
      影响面：仅改变"同一 (u,v) 存在多行且 tie 不同"的去重取舍；权重与公式不变。

    R2-C 边型数组（AUDIT-EDGETYPE 方案 a §4.2/§4.4）：
      新增 `tmask` 入参（uint8，与 src/dst 平行）；去重阶段对同键做 **bitwise_or 归并**，
      使代表行同时携带全部构成位（如 ①+③ → 5），而非只留胜出行的那一位。"""
    key = src.astype(np.int64) * n + dst
    # 去重（同 (u,v)：排序键最大者优先，其次权重最大，最后取先出现行）
    o = np.lexsort((np.arange(len(src)), -w, -tie, key))
    key_s = key[o]
    first = np.empty(len(key_s), dtype=bool)
    first[0] = True
    np.not_equal(key_s[1:], key_s[:-1], out=first[1:])
    take = o[first]
    src, dst, w, tie = src[take], dst[take], w[take], tie[take]
    if tmask is not None:
        grp = np.cumsum(first) - 1                       # 每个原始行归属的键组
        tm_or = np.zeros(len(take), dtype=np.uint8)
        np.bitwise_or.at(tm_or, grp, tmask[o])           # 同键位掩码按 OR 归并
        tmask = tm_or
    # 每源点排序：primary=assoc → (tie desc, w desc, dst asc)；primary=weight → (w desc, tie desc, dst asc)
    order = (np.lexsort((dst, -w, -tie, src)) if primary == "assoc"
             else np.lexsort((dst, -tie, -w, src)))
    src, dst, w = src[order], dst[order], w[order]
    if tmask is not None:
        tmask = tmask[order]
    starts = np.flatnonzero(np.r_[True, src[1:] != src[:-1]])
    counts = np.diff(np.r_[starts, len(src)])
    rank = np.arange(len(src)) - np.repeat(starts, counts)
    keep = rank < max_out
    src, dst, w = src[keep], dst[keep], w[keep]
    if tmask is not None:
        tmask = tmask[keep]
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.add.at(indptr, src + 1, 1)
    indptr = np.cumsum(indptr)
    if tmask is not None:
        return (indptr.astype(np.int64), dst.astype(np.int32), w.astype(np.float32),
                tmask.astype(np.uint8))
    return (indptr.astype(np.int64), dst.astype(np.int32), w.astype(np.float32))


def _csr_matrix(indptr, indices, n):
    from scipy import sparse
    return sparse.csr_matrix((np.ones(len(indices), dtype=np.int8), indices, indptr), shape=(n, n))


def coverage_curve(A, n, seeds, ncl, ncls=None, hops=12, target="cluster", symmetric=False):
    """多源点 ≤hops 跳 BFS（scipy 最短路，主口径对齐 graph_report.py）：
    覆盖 = |{非源点、跳距 ≤h 且与源点同簇（或同类目）的节点}| / |源点目标集合大小|。
    target: cluster = 同 cluster 字段；cluster_or_cls = 同 cluster 或同 cls（§4-P3 "主簇或分类"）。
    symmetric: 先做无向闭包（A+A.T），用于区分"跳数不够"与"有向截断不对称"。"""
    from scipy.sparse.csgraph import shortest_path
    if symmetric:
        A = A + A.T
    D = shortest_path(A, unweighted=True, directed=True, indices=seeds)
    D = np.atleast_2d(D)
    scl = ncl[seeds]
    cl_size = np.bincount(ncl, minlength=int(ncl.max()) + 1)
    if target == "cluster_or_cls" and ncls is not None:
        same = (ncl[None, :] == scl[:, None]) | (ncls[None, :] == ncls[seeds][:, None])
        denom = same.sum(axis=1)
    else:
        same = (ncl[None, :] == scl[:, None])
        denom = cl_size[scl]
    denom = np.maximum(denom, 1)                 # 分母含源点、分子不含 —— 对齐 graph_report.py 的 len(seen & mem)/len(mem)
    same[np.arange(len(seeds)), seeds] = False   # 源点自身不计入覆盖
    curves = np.zeros((len(seeds), hops))
    for h in range(1, hops + 1):
        hit = ((D <= h) & same).sum(axis=1)
        curves[:, h - 1] = np.minimum(1.0, hit / denom)
    return {"mean": [round(float(x), 4) for x in curves.mean(axis=0)],
            "median": [round(float(x), 4) for x in np.median(curves, axis=0)],
            "hop12_mean": round(float(curves[:, -1].mean()), 4),
            "hop12_median": round(float(np.median(curves[:, -1])), 4)}


def components(A, n):
    """无向连通分量（对齐 graph_report.py：A + A.T）。"""
    from scipy.sparse.csgraph import connected_components
    ncc, lab = connected_components(A + A.T, directed=False)
    sizes = np.sort(np.bincount(lab))[::-1]
    return {"components": int(ncc), "largest": int(sizes[0]),
            "largest_pct": round(float(sizes[0]) / n, 6)}


def main():
    ap = argparse.ArgumentParser(description="P2 主题图边构建（共现/同簇/层级 + CSR）")
    ap.add_argument("--data", default=DATA_DEFAULT)
    ap.add_argument("--out", default=None, help="topics 目录，默认 <data>/topics")
    ap.add_argument("--top-per-card", type=int, default=10, help="B1 每卡候选 top-M（与 P1 同源）")
    ap.add_argument("--top-k", type=int, default=5, help="每卡主题数（证据链 top-5）")
    ap.add_argument("--max-out", type=int, default=20, help="每节点出度上限")
    ap.add_argument("--cap-count", type=int, default=50, help="共现书数封顶（log1p 前）")
    ap.add_argument("--combine", choices=["sum", "max"], default="sum")
    ap.add_argument("--mutual-bonus", type=float, default=0.0,
                    help="互惠加成：某有向边的反向边也在目标节点 top-max_out 内时，排序键 ×(1+bonus)"
                         "（默认 0=关；用于缓解 top-20 截断造成的方向不对称、提升有向可达）")
    ap.add_argument("--rank-by", choices=["weight", "assoc"], default="assoc",
                    help="top-20 截断的排序键：assoc=按关联度 count/√(freq_u·freq_v)（默认，实测 12 跳覆盖 "
                         "0.97 vs 0.77）；weight=按权重（§3.2 字面口径，实测覆盖 0.77，P3 门槛 0.90 不达标）")
    ap.add_argument("--cls-in-cooccurrence", choices=["auto", "no", "yes"], default="auto")
    ap.add_argument("--variant", choices=["auto", "spec", "aug"], default="auto",
                    help="落盘主产物用哪个口径（auto=按 12 跳覆盖自动选）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--coverage-samples", type=int, default=300)
    ap.add_argument("--limit-cards", type=int, default=0, help="仅处理前 N 张卡（冒烟用；0=全量）")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    D = os.path.abspath(os.path.expanduser(args.data))
    out_dir = os.path.abspath(os.path.expanduser(args.out)) if args.out else os.path.join(D, "topics")
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    cap_log = math.log1p(args.cap_count)

    # ---- 载入 ----
    nodes = json.load(open(os.path.join(out_dir, "nodes.json"), encoding="utf-8"))
    n = len(nodes)
    terms = [normalize_term(x["term"]) for x in nodes]
    types = [x["type"] for x in nodes]
    types_arr = np.array(types)
    ncl = np.array([int(x["cluster"]) for x in nodes], dtype=np.int64)
    nfreq = np.array([int(x["freq"]) for x in nodes], dtype=np.int64)
    ncls = [x["cls"] for x in nodes]
    ncls_arr = np.array(ncls)
    kw_map = {t: i for i, t in enumerate(terms) if types[i] == "kw"}
    # cls 节点词表：normalize_term 会把纯 ASCII 主题小写化（"A1"→"a1"），而卡片 cls2 走
    # normalize_cls（保留大小写），故同时登记两种键，避免类目匹配全 miss。
    cls_map = {}
    for i, t in enumerate(terms):
        if types[i] == "cls":
            cls_map[normalize_cls(nodes[i]["term"])] = i
            cls_map.setdefault(t, i)

    def lookup_cls(raw):
        if not raw:
            return -1
        return cls_map.get(normalize_cls(raw), cls_map.get(normalize_term(raw), -1))

    idx = os.path.join(D, "index")
    z = np.load(os.path.join(idx, "tfidf.npz"))
    indptr, indices, data = z["indptr"], z["indices"], z["data"]
    vocab = json.load(open(os.path.join(idx, "vocab.json"), encoding="utf-8"))
    labels = np.load(os.path.join(idx, "clusters.npy"))
    clusters = json.load(open(os.path.join(D, "clusters.json"), encoding="utf-8"))["clusters"]
    subjects = json.load(open(os.path.join(D, "subjects.json"), encoding="utf-8"))
    nv = [normalize_term(t) for t in vocab]
    a_set, _a_mem, _a_raw = load_source_a(clusters)
    _sub_lex = load_subject_lexicon(subjects)
    matcher = build_a_matcher(a_set)
    cards_path = os.path.join(D, "cards.jsonl")
    n_cards = len(indptr) - 1
    print(f"[load] nodes={n:,} kw={len(kw_map):,} cls={int((types_arr=='cls').sum()):,} cards={n_cards:,} | "
          f"{time.time()-t0:.1f}s", flush=True)

    # ---- 单趟遍历：card_topics + 两口径 pair 计数 ----
    max_pairs_aug = (args.limit_cards or n_cards) * 15
    U = np.empty(max_pairs_aug, dtype=np.int32)
    V = np.empty(max_pairs_aug, dtype=np.int32)
    Us = np.empty(max_pairs_aug, dtype=np.int32)
    Vs = np.empty(max_pairs_aug, dtype=np.int32)
    ku = kv = kus = kvs = 0
    spec_edges_n = 0          # 仅 kw-kw 对数（spec 口径）
    n_topics_hist = Counter()
    n_empty = 0
    n_cls_in_top = 0
    kw_cls_votes = {}         # kw id -> Counter(cls2 id)：层级边（主题→类目）的卡级证据投票
    ct_path = os.path.join(out_dir, "card_topics.jsonl")
    with open(ct_path, "w", encoding="utf-8") as ct:
        for i, c, title, title_tokens in iter_card(cards_path, indptr):
            if args.limit_cards and i >= args.limit_cards:
                break
            a, b = int(indptr[i]), int(indptr[i + 1])
            pairs = []
            tok_w = {}
            for p in range(a, b):
                k = nv[int(indices[p])]
                if k in title_tokens:
                    wv = float(data[p])
                    tok_w[k] = max(tok_w.get(k, 0.0), wv)
                    if term_ok_kw(k) and not is_stop(k):
                        pairs.append((wv, k))
            pairs.sort(key=lambda x: (-x[0], x[1]))
            pairs = pairs[:args.top_per_card]
            # 候选词（与 P1 同源的两条路）
            cand = set()
            if pairs:
                for _s, wd in merge_bigrams(pairs, max_len=5, min_ratio=0.25):
                    wd = normalize_term(wd)
                    if wd in kw_map:
                        cand.add(wd)
            norm_title = normalize_term(title)
            for wd in match_a(title, title_tokens, matcher, norm_title):
                if wd in kw_map:
                    cand.add(wd)
            scored = []
            for wd in cand:
                sc = term_score(wd, tok_w)
                if sc > 0:
                    scored.append((sc, kw_map[wd]))
            scored.sort(key=lambda x: (-x[0], x[1]))
            tops = [j for _s, j in scored[:args.top_k]]
            ct.write(json.dumps({"mms": c.get("mms", ""), "topics": tops},
                                ensure_ascii=False, separators=(",", ":")) + "\n")
            n_topics_hist[len(tops)] += 1
            if not tops:
                n_empty += 1
            # 同簇共现过滤用：卡簇标签
            lab = int(labels[i])
            # aug：并入卡的 cls2 节点（cls 是 §3.1 的"类目主题"）
            items = list(tops)
            cid = lookup_cls(c.get("cls2") or "")
            if cid >= 0:
                items.append(cid)
                n_cls_in_top += 1
                for u in tops:                      # 层级边投票：主题 → 其高频 cls2
                    v = kw_cls_votes.get(u)
                    if v is None:
                        v = kw_cls_votes[u] = Counter()
                    v[cid] += 1
            # R1 修复①：**单轮枚举**卡的主题集合（top-5 kw ∪ {cls2}），每个无序对每卡只计一次。
            # 修复前 spec 循环与 aug 循环各写一遍 kw-kw 对 → kw-kw 共现计数翻倍（同簇计数同样翻倍）。
            # 同簇加成（pairs_same_cluster）是**独立计数器**，按同一轮枚举各计一次，不与主计数叠加。
            for x in range(len(items)):
                for y in range(x + 1, len(items)):
                    u, v = items[x], items[y]
                    if u == v:
                        continue
                    if u > v:
                        u, v = v, u
                    U[ku] = u; V[kv] = v; ku += 1; kv += 1
                    if types_arr[u] == "kw" and types_arr[v] == "kw":
                        spec_edges_n += 1                 # spec 口径的对数（子集统计，非二次计数）
                    if ncl[u] == ncl[v] == lab:
                        Us[kus] = u; Vs[kvs] = v; kus += 1; kvs += 1
    U, V, Us, Vs = U[:ku], V[:kv], Us[:kus], Vs[:kvs]
    print(f"[pass] pairs: aug={ku:,} spec={spec_edges_n:,} same-cluster={kus:,} | "
          f"空主题卡={n_empty:,} 含 cls2 卡={n_cls_in_top:,} | {time.time()-t0:.1f}s", flush=True)

    # ---- 层级边目标：每主题取其卡级证据中出现最多的 cls2 类目节点（众数；平局取较小 id） ----
    cls_of = np.full(n, -1, dtype=np.int64)
    for u, cnt in kw_cls_votes.items():
        cls_of[u] = max(cnt.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    kw_no_hier = int(((types_arr == "kw") & (cls_of < 0)).sum())
    print(f"[hier] 主题→cls2 边={int((cls_of>=0).sum()):,} | 无层级证据的 kw={kw_no_hier:,} | "
          f"{time.time()-t0:.1f}s", flush=True)

    # ---- 计数（排序去重，避免稠密矩阵） ----
    idx_a = tri_index(U.astype(np.int64), V.astype(np.int64), n)
    uniq, first_pos, counts = np.unique(idx_a, return_index=True, return_counts=True)
    up, vp = U[first_pos].astype(np.int64), V[first_pos].astype(np.int64)
    if kus:
        idx_s = tri_index(Us.astype(np.int64), Vs.astype(np.int64), n)
        uniq_s, counts_s = np.unique(idx_s, return_counts=True)
        pos = np.searchsorted(uniq, uniq_s)
        c_sc = np.zeros(len(uniq), dtype=np.int64)
        c_sc[pos] = counts_s
    else:
        c_sc = np.zeros(len(uniq), dtype=np.int64)
    is_kw_pair = (types_arr[up] == "kw") & (types_arr[vp] == "kw")
    print(f"[count] distinct pairs aug={len(uniq):,} kw-kw={int(is_kw_pair.sum()):,} "
          f"same-cluster={int((c_sc > 0).sum()):,} | {time.time()-t0:.1f}s", flush=True)

    w1 = np.log1p(np.minimum(counts, args.cap_count)) / cap_log
    w2 = 0.3 * np.log1p(c_sc) / cap_log
    w = np.minimum(1.0, w1 + w2) if args.combine == "sum" else np.maximum(w1, w2)
    is_kw_pair = (types_arr[up] == "kw") & (types_arr[vp] == "kw")
    print(f"[weight] 封顶饱和(count>=cap)={int((counts>=args.cap_count).sum()):,} "
          f"({(counts>=args.cap_count).mean()*100:.1f}%) | 同簇加成命中={int((c_sc>0).sum()):,} | "
          f"kw-kw 对={int(is_kw_pair.sum()):,} | {time.time()-t0:.1f}s", flush=True)

    # ---- 组装两种口径的边集 ----
    def build(mask):
        u_, v_, w_, c_ = up[mask], vp[mask], w[mask], counts[mask]
        src = np.concatenate([u_, v_])
        dst = np.concatenate([v_, u_])
        ww = np.concatenate([w_, w_])
        # R2-C 边型掩码：bit0=① 卡级共现（所有 pair 行恒置位）；bit1=② 同簇加成（c_sc>0）
        tm = np.ones(len(u_), dtype=np.uint8)
        tm[c_sc[mask] > 0] |= 2
        tm = np.concatenate([tm, tm])                     # 双向：与 src/dst 平行
        if args.rank_by == "assoc":
            den = np.sqrt(np.maximum(nfreq[u_], 1) * np.maximum(nfreq[v_], 1))
            rk = c_ / den
        else:
            rk = c_.astype(np.float64)
        rk = np.concatenate([rk, rk])
        if args.mutual_bonus > 0:
            rk = apply_mutual_bonus(src, dst, rk, n, args.max_out, args.mutual_bonus)
        # ③ 层级边（主题 → cls2，w=1.0，单向）；该 (u,cid) 对必然存在共现证据（同一张卡的
        #    主题集合含二者），故 bit0 一并置位 → mask = 1|4 = 5（§1.2 实测 mask=4 单型边为 0 条）
        has = cls_of >= 0
        src = np.concatenate([src, np.flatnonzero(has).astype(np.int64)])
        dst = np.concatenate([dst, cls_of[has]])
        ww = np.concatenate([ww, np.ones(int(has.sum()), dtype=np.float64)])
        tm = np.concatenate([tm, np.full(int(has.sum()), 1 | 4, dtype=np.uint8)])
        rk = np.concatenate([rk, nfreq[has].astype(np.float64) * 1e9])  # 层级边优先保留
        return topk_csr(src, dst, ww, rk, n, args.max_out, primary=args.rank_by, tmask=tm)

    variants = {"spec": is_kw_pair, "aug": np.ones(len(up), dtype=bool)}
    built = {k: build(m) for k, m in variants.items()}

    def edge_summary(csr):
        ip, ix, wt = csr[0], csr[1], csr[2]
        tm = csr[3] if len(csr) > 3 else None
        deg = np.diff(ip)
        out = {"edges": int(len(ix)), "avg_out_degree": round(float(deg.mean()), 3),
               "out_degree": {"min": int(deg.min()), "median": int(np.median(deg)),
                              "p90": float(np.percentile(deg, 90)), "max": int(deg.max())},
               "isolated_out0": int((deg == 0).sum()),
               "weight": {k: round(v, 4) for k, v in dist_stats(wt).items()},
               "w_eq_1": int((wt >= 0.99999).sum())}
        if tm is not None:                                  # R2-C：边型分布登记
            vals, cnts = np.unique(tm, return_counts=True)
            out["types"] = {"dtype": "uint8", "values": sorted(int(v) for v in vals),
                            "hist": {str(int(v)): int(c) for v, c in zip(vals, cnts)},
                            "bits": {"bit0=1": "共现", "bit1=2": "同簇加成", "bit2=4": "层级"},
                            "multi_type_edges": int((tm & (tm - 1) != 0).sum())}
        return out

    # ---- 12 跳覆盖（自测用，正式验收在 P3） ----
    rng = np.random.default_rng(args.seed)
    kw_ids = np.array([i for i in range(n) if types[i] == "kw"])
    seeds_kw = rng.choice(kw_ids, size=min(args.coverage_samples, len(kw_ids)), replace=False)
    seeds_all = rng.choice(n, size=min(args.coverage_samples, n), replace=False)

    def coverage_of(csr):
        ip, ix, _wt = csr[0], csr[1], csr[2]
        A = _csr_matrix(ip, ix, n)
        c_kw = coverage_curve(A, n, seeds_kw, ncl, ncls_arr)
        c_all = coverage_curve(A, n, seeds_all, ncl, ncls_arr)
        c_uc = coverage_curve(A, n, seeds_kw, ncl, ncls_arr, target="cluster_or_cls")
        c_sym = coverage_curve(A, n, seeds_kw, ncl, ncls_arr, symmetric=True)
        c_uc_sym = coverage_curve(A, n, seeds_kw, ncl, ncls_arr, target="cluster_or_cls", symmetric=True)
        return {"hop12_kw_seeds_mean": c_kw["hop12_mean"], "hop12_kw_seeds_median": c_kw["hop12_median"],
                "hop12_all_seeds_mean": c_all["hop12_mean"], "hop12_all_seeds_median": c_all["hop12_median"],
                "hop12_kw_seeds_cluster_or_cls_mean": c_uc["hop12_mean"],
                "hop12_kw_seeds_symmetric_mean": c_sym["hop12_mean"],
                "hop12_kw_seeds_cluster_or_cls_symmetric_mean": c_uc_sym["hop12_mean"],
                "curve_kw_mean": c_kw["mean"], "curve_kw_median": c_kw["median"],
                "components": components(A, n)}

    cov = {k: coverage_of(v) for k, v in built.items()}
    print(f"[coverage] spec: kw={cov['spec']['hop12_kw_seeds_mean']:.4f} all={cov['spec']['hop12_all_seeds_mean']:.4f} | "
          f"aug: kw={cov['aug']['hop12_kw_seeds_mean']:.4f} all={cov['aug']['hop12_all_seeds_mean']:.4f} | "
          f"{time.time()-t0:.1f}s", flush=True)

    # ---- 选主口径 ----
    if args.variant in ("spec", "aug"):
        chosen = args.variant
    elif args.cls_in_cooccurrence == "yes":
        chosen = "aug"
    elif args.cls_in_cooccurrence == "no":
        chosen = "spec"
    else:
        # auto：取两口径 12 跳覆盖（kw 源点与全节点源点的均值）更高者；
        # 依据：cls 节点在 spec 口径下是纯汇点（出度 0），会拖垮全节点口径覆盖。
        def _score(v):
            return 0.5 * (cov[v]["hop12_kw_seeds_mean"] + cov[v]["hop12_all_seeds_mean"])
        chosen = "aug" if _score("aug") > _score("spec") else "spec"
    other = "aug" if chosen == "spec" else "spec"

    main_path = os.path.join(out_dir, "edges.csr.npz")
    np.savez(main_path, indptr=built[chosen][0], indices=built[chosen][1], weights=built[chosen][2],
             types=built[chosen][3])
    alt_path = os.path.join(out_dir, f"edges.variant-{other}.csr.npz")
    np.savez(alt_path, indptr=built[other][0], indices=built[other][1], weights=built[other][2],
             types=built[other][3])

    # ---- 自测：热门节点邻域相关性 ----
    ip, ix, wt = built[chosen][0], built[chosen][1], built[chosen][2]
    hot = np.argsort(-nfreq)[:20]
    hot_detail = []
    for u in hot:
        a, b = int(ip[u]), int(ip[u + 1])
        nb = ix[a:b]
        if len(nb) == 0:
            hot_detail.append({"id": int(u), "term": nodes[u]["term"], "deg": 0})
            continue
        hot_detail.append({
            "id": int(u), "term": nodes[u]["term"], "type": nodes[u]["type"], "freq": int(nfreq[u]),
            "deg": int(len(nb)),
            "top_neighbors": [{"term": nodes[int(v)]["term"], "w": round(float(wt[a + j]), 4),
                               "same_cluster": bool(ncl[v] == ncl[u]), "same_cls": bool(ncls[v] == ncls[u])}
                              for j, v in enumerate(nb[:8])],
            "neighbor_same_cluster_pct": round(float((ncl[nb] == ncl[u]).mean()), 3),
            "neighbor_same_cls_pct": round(float(np.mean([ncls[int(v)] == ncls[u] for v in nb])), 3),
        })

    deg = np.diff(ip)
    report = {
        "stage": "P2",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "data_dir": D, "out_dir": out_dir,
        "seconds": round(time.time() - t0, 1),
        "params": {
            "top_per_card": args.top_per_card, "top_k": args.top_k, "max_out": args.max_out,
            "cap_count": args.cap_count, "combine": args.combine, "variant": chosen,
            "rank_by": args.rank_by,
            "variant_mode": args.variant, "cls_in_cooccurrence": args.cls_in_cooccurrence,
            "coverage_samples": args.coverage_samples, "seed": args.seed,
            "b1_weight_rule": "score(card,term)=Σ tfidf(card, token) over tokens⊆term（ASCII 精确/CJK 相邻 bigram 求和）",
            "b1_cls_policy": "cls 不占卡 top-5 名额",
            "b2_pair_members": "卡 top-5 kw" + (" ∪ {卡 cls2}" if chosen == "aug" else "（spec 口径）"),
            "b2_weight": "w1=log1p(min(共现书数,cap))/log1p(cap)",
            "b3_weight": "w2=0.3×log1p(簇内共现)/log1p(cap)",
            "b3_combine": args.combine, "b3_new_pairs": 0,
            "b3_note": "同簇对必然已有共现边（cnt_sc>0 ⟹ cnt>0）；sum 口径下 ② 为加成项，max 口径下 ② 恒被 ① 支配而失效",
            "b4_weight": "主题→cls2 类目，w=1.0，单向（无自环）",
            "b4_target_rule": "cls 节点词表 = §3.1 源 C 的 CLC cls2；节点表 cls 字段是 cls1（无对应节点），故层级边目标由卡级证据投票取众数 cls2",
            "b5_arrays": {"indptr": "int64", "indices": "int32", "weights": "float32",
                          "types": "uint8（R2-C 新增；与 indices 行序对齐，bit0=共现 bit1=同簇加成 bit2=层级）"},
            "b5_edgetype_rule": "R2-C/AUDIT-EDGETYPE 方案 a：pair 行 =1（共现）；c_sc>0 置 bit1 →3；层级行 =1|4=5（该 (u,cid) 对必有共现证据）；去重时同键按 bitwise_or 归并 → 合法值域 {1,3,5,7}",
            "normalization": "三类公式均已用 log1p(cap) 归一到 [0,1]；最终 clamp ≤1.0",
            "tie_break": "R1 修复后：primary=assoc 时键序 src↑ → 关联度↓ → 权重↓ → dst↑（权重退为 tie-break）；primary=weight 时 src↑ → 权重↓ → 关联度↓ → dst↑。两种模式层级边均置顶（tie=1e9/w=1.0）",
            "rank_by_note": "截断排序键默认 assoc=count/√(freq_u·freq_v)（权重公式不变）；--rank-by weight 可复现 §3.2 字面口径；R1 修复②前 assoc 仅作权重平局 tie-break（未生效），修复后为**主键**",
        },
        "counts": {
            "nodes": n, "kw": int((np.array(types) == "kw").sum()), "cls": int((np.array(types) == "cls").sum()),
            "cards": n_cards, "cards_with_cls2": n_cls_in_top,
            "cards_empty_topics": n_empty,
            "cards_topic_count_hist": {str(k): v for k, v in sorted(n_topics_hist.items())},
            "pairs_aug_raw": int(ku), "pairs_spec_raw": int(spec_edges_n),
            "pairs_same_cluster_raw": int(kus),
            "distinct_pairs_aug": int(len(uniq)), "distinct_pairs_kwkw": int(is_kw_pair.sum()),
            "distinct_pairs_same_cluster": int((c_sc > 0).sum()),
            "hierarchical_edges": int((cls_of >= 0).sum()),
            "kw_without_hier_edge": kw_no_hier,
            "edges_final": int(len(ix)),
        },
        "edge_stats": {
            "chosen": chosen,
            "avg_out_degree": round(float(deg.mean()), 3),
            "out_degree": {"min": int(deg.min()), "median": int(np.median(deg)),
                           "p90": float(np.percentile(deg, 90)), "max": int(deg.max())},
            "isolated_out0": int((deg == 0).sum()),
            "weight_dist": {k: round(v, 4) for k, v in dist_stats(wt).items()},
            "w_eq_1_share": round(float((wt >= 0.99999).mean()), 4),
            "cooccur_count_dist": {k: round(v, 3) for k, v in dist_stats(counts).items()},
            "cooccur_saturated_pairs": int((counts >= args.cap_count).sum()),
            "cooccur_saturated_share": round(float((counts >= args.cap_count).mean()), 4),
            "cooccur_singleton_share": round(float((counts == 1).mean()), 4),
            "kwkw_edge_share": round(float(is_kw_pair.sum()) / max(len(up), 1), 4),
        },
        "variants": {k: {"edges": edge_summary(v), "coverage": cov[k]} for k, v in built.items()},
        "self_test": {
            "avg_out_degree_le_max": bool(deg.mean() <= args.max_out + 1e-9),
            "hop12_kw_seeds_mean": cov[chosen]["hop12_kw_seeds_mean"],
            "hop12_all_seeds_mean": cov[chosen]["hop12_all_seeds_mean"],
            "components": cov[chosen]["components"],
            "hot_nodes": hot_detail,
        },
        "artifacts": {"edges": os.path.relpath(main_path, D),
                      "variant_other": os.path.relpath(alt_path, D),
                      "card_topics": os.path.relpath(ct_path, D)},
    }
    rp = args.report or os.path.join(out_dir, "p2-build-report.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"[done] variant={chosen} nodes={n:,} edges={len(ix):,} avg_deg={deg.mean():.3f} "
          f"isolated={int((deg==0).sum())} -> {main_path} | {time.time()-t0:.1f}s", flush=True)
    print(f"[report] {rp}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
