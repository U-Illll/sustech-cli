#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_graph.py — 图书馆目录「语义图谱层」（v2 新增；对齐 Agentic-RAG 的双链图机制）

在双索引（TF-IDF + bge 语义）之上构建：
  1. 语义内链图（kNN，每书 top-K 语义最近邻；CSR 存储）—— 对应记忆系统的 [[双链]] 图
  2. 语义簇（MiniBatchKMeans，k=400 类比记忆系统的主题簇）
     + 簇目录（关键词 + 代表书 + 学科分布）

输入:  <data>/cards.jsonl + <data>/index/{embeddings.npy, vocab.json, idf.npy}
输出:  <data>/index/knn_csr.npz          语义内链图（CSR: indptr/indices/sims）
       <data>/index/clusters.npy        簇归属（int32，行序对齐 cards）
       <data>/index/cluster_centroids.npy  簇质心（float32, k×512）
       <data>/clusters.json             簇目录
       <data>/index/graph_meta.json     图元数据（k/簇数/统计）

用法:
  python3 build_graph.py [--data DIR] [--k 10] [--clusters 400] [--limit N] [--block 512]
    --limit N: 冒烟模式（取前 N 本，输出到 <data>/graph_smoke/，不覆盖正式产物）
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

_PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)
import numpy as np

from catalog_vector import tokenize  # 复用同源分词

DATA_DEFAULT = os.path.expanduser("~/go/lib-catalog-data")


def resolve_data(args):
    d = (getattr(args, "data", None) or os.environ.get("LIB_CATALOG_DATA") or DATA_DEFAULT)
    return os.path.abspath(os.path.expanduser(d))


def build_knn(E, k, block):
    """分块 BLAS 全量 top-K 余弦（E 已归一化）。返回 (indptr, indices, sims)。"""
    N = E.shape[0]
    indptr = np.arange(0, (N + 1) * k, k, dtype=np.int64)
    indices = np.zeros(N * k, dtype=np.int32)
    sims = np.zeros(N * k, dtype=np.float16)
    t0 = time.time()
    nblocks = (N + block - 1) // block
    for bi, i0 in enumerate(range(0, N, block)):
        i1 = min(i0 + block, N)
        b = i1 - i0
        S = E[i0:i1] @ E.T                      # (b, N) float32
        S[np.arange(b), np.arange(i0, i1)] = -np.inf  # 排除自身
        part = np.argpartition(-S, k, axis=1)[:, :k]  # top-k（未排序）
        rows = np.arange(b)[:, None]
        vals = S[rows, part]
        order = np.argsort(-vals, axis=1)
        part = part[rows, order]
        vals = vals[rows, order]
        indices[i0 * k:i1 * k] = part.ravel()
        sims[i0 * k:i1 * k] = vals.ravel().astype(np.float16)
        del S, part, vals
        if bi % 20 == 0 or bi == nblocks - 1:
            el = time.time() - t0
            eta = el / (bi + 1) * (nblocks - bi - 1) if bi else 0
            print(f"[knn] 块 {bi + 1}/{nblocks}（{i1}/{N} 行；{el:.0f}s 已用，~{eta:.0f}s 剩余）", flush=True)
    return indptr, indices, sims


def mutual_ratio(N, k, indptr, indices):
    """互链率：A→B 且 B→A 的有向边占比（scipy 稀疏乘）。"""
    from scipy import sparse
    A = sparse.csr_matrix((np.ones(N * k, dtype=np.float32), indices, indptr), shape=(N, N))
    M = A.multiply(A.T)
    return float(M.nnz) / float(N * k)


# 关键词展示过滤：英文功能词 + 出版/著录 boilerplate（无主题信息量）
STOP_TOKENS = {
    "the", "of", "and", "in", "a", "to", "for", "with", "on", "an", "by", "at",
    "from", "as", "is", "are", "or", "its", "this", "that", "be", "no", "not",
    "author.", "author", "authors", "ed.", "ed", "eds", "editor", "editor.",
    "edited", "translator", "trans.", "trans", "ill.", "ill", "et", "al",
    "主编", "编著", "编委", "主审", "点校", "校注", "著", "编", "等", "译",
}


_STOP_RE = __import__("re").compile(r"^[a-z]\.?$|^[0-9][0-9.\-:/]*$")


def _is_cjk(t):
    return len(t) >= 2 and all("\u4e00" <= ch <= "\u9fff" for ch in t)


def merge_bigrams(scored, max_len=5, min_ratio=0.25):
    """链式合并重叠中文 bigram（"机器"+"器学"+"学习" → "机器学习"）。scored: [(score, token)] 降序。"""
    pool = [t for s, t in scored]
    used = set()
    merged = []
    for s, t in scored:
        if t in used:
            continue
        if not _is_cjk(t):
            merged.append((s, t))
            used.add(t)
            continue
        cur = t
        cur_s = s
        used.add(t)
        while len(cur) < max_len:
            tail = cur[-1]
            nxt = None
            for s2, t2 in scored:
                if t2 in used or not _is_cjk(t2):
                    continue
                if t2[0] == tail and s2 >= cur_s * min_ratio:
                    nxt = (s2, t2)
                    break
            if not nxt:
                break
            cur = cur + nxt[1][1:]
            used.add(nxt[1])
        merged.append((cur_s, cur))
    merged.sort(reverse=True)
    return merged


def cluster_keywords(cards_path, labels, vocab, idf, n_clusters, topn=12):
    """聚类关键词：簇内 token 频次 × idf。"""
    vmap = {t: i for i, t in enumerate(vocab)}
    V = len(vocab)
    cls_cnt = [Counter() for _ in range(n_clusters)]
    with open(cards_path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            c = json.loads(line)
            if i >= len(labels):
                break
            cl = int(labels[i])
            txt = (c.get("title") or "").replace("$$Q", " ")
            cnt = cls_cnt[cl]
            for t in tokenize(txt):
                j = vmap.get(t)
                if j is not None:
                    cnt[j] += 1
    kws = []
    for cl in range(n_clusters):
        cnt = cls_cnt[cl]
        if not cnt:
            kws.append([])
            continue
        scored = [(float(idf[j] * c), vocab[j]) for j, c in cnt.items()]
        scored.sort(key=lambda x: -x[0])
        filtered = [(s, t) for s, t in scored
                    if t not in STOP_TOKENS and not _STOP_RE.match(t)]
        cand = filtered[:60] if len(filtered) >= 8 else scored[:60]
        merged = merge_bigrams(cand)
        kws.append([t for _s, t in merged[:topn]])
    return kws


def cluster_exemplars(E, labels, centroids, n_clusters, topn=3):
    """代表书：簇内与质心最相似的书（行号）。"""
    members = defaultdict(list)
    for i, cl in enumerate(labels):
        members[int(cl)].append(i)
    exemplars = []
    for cl in range(n_clusters):
        idxs = members.get(cl, [])
        if not idxs:
            exemplars.append([])
            continue
        cen = centroids[cl]
        n = np.linalg.norm(cen)
        if n > 0:
            cen = cen / n
        sims = E[idxs] @ cen.astype(np.float32)
        order = np.argsort(-sims)[:topn]
        exemplars.append([int(idxs[o]) for o in order])
    return exemplars, members


def main():
    ap = argparse.ArgumentParser(description="图书馆目录语义图谱层")
    ap.add_argument("--data", default=None, help="数据目录（默认 $LIB_CATALOG_DATA 或 ~/go/lib-catalog-data）")
    ap.add_argument("--k", type=int, default=10, help="语义内链邻居数（默认 10，对齐记忆系统每页链接密度）")
    ap.add_argument("--clusters", type=int, default=400, help="语义簇数量（默认 400）")
    ap.add_argument("--limit", type=int, default=0, help="冒烟模式：仅前 N 本（输出到 graph_smoke/）")
    ap.add_argument("--block", type=int, default=512, help="kNN 分块大小（默认 512）")
    args = ap.parse_args()

    D = resolve_data(args)
    index_dir = os.path.join(D, "index")
    E = np.load(os.path.join(index_dir, "embeddings.npy"))
    N = E.shape[0]
    if args.limit and args.limit < N:
        E = E[:args.limit]
        N = args.limit
    t0 = time.time()
    k = min(args.k, N - 1)
    print(f"[graph] 载入 {N} × {E.shape[1]} 向量；k={k}，簇={args.clusters}", flush=True)

    # ---- 1) kNN 内链 ----
    indptr, indices, sims = build_knn(E, k, args.block)
    mr = mutual_ratio(N, k, indptr, indices)
    sims_f = sims.astype(np.float32)
    stats = {
        "sim_mean": float(sims_f.mean()),
        "sim_median": float(np.median(sims_f)),
        "sim_p10": float(np.percentile(sims_f, 10)),
    }
    print(f"[knn] 完成：{N}×{k} 边；互链率 {mr:.3f}；sim 均 {stats['sim_mean']:.3f} / 中位 {stats['sim_median']:.3f}", flush=True)

    # ---- 2) 语义簇 ----
    from sklearn.cluster import MiniBatchKMeans
    n_clusters = min(args.clusters, N)
    km = MiniBatchKMeans(n_clusters=n_clusters, batch_size=8192, n_init=3,
                         max_iter=300, random_state=42)
    t1 = time.time()
    labels = km.fit_predict(E).astype(np.int32)
    centroids = km.cluster_centers_.astype(np.float32)
    print(f"[cluster] KMeans 完成：{n_clusters} 簇（{time.time() - t1:.0f}s）；"
          f"大小 min/median/max = {np.bincount(labels).min()}/{int(np.median(np.bincount(labels)))}/{np.bincount(labels).max()}", flush=True)

    # ---- 3) 簇目录（关键词 + 代表书 + 学科分布） ----
    cards_path = os.path.join(D, "cards.jsonl")
    vocab = json.load(open(os.path.join(index_dir, "vocab.json"), encoding="utf-8"))
    idf = np.load(os.path.join(index_dir, "idf.npy"))
    kws = cluster_keywords(cards_path, labels, vocab, idf, n_clusters)
    exemplars, members = cluster_exemplars(E, labels, centroids, n_clusters)
    # 学科分布 + 代表书 mms（单次扫描）
    cls_by_cluster = [Counter() for _ in range(n_clusters)]
    ex_rows = set()
    for ex in exemplars:
        ex_rows.update(ex)
    row2mms = {}
    with open(cards_path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= N:
                break
            c = json.loads(line)
            cl = int(labels[i])
            if i in ex_rows:
                row2mms[i] = c["mms"]
            if c.get("cls"):
                cls_by_cluster[cl][c["cls"]] += 1
    clusters_doc = []
    for cl in range(n_clusters):
        ex_mms = [row2mms[r] for r in exemplars[cl] if r in row2mms]
        clusters_doc.append({
            "id": cl,
            "size": int((labels == cl).sum()),
            "keywords": kws[cl],
            "exemplars": ex_mms,
            "top_subjects": [[k2, v] for k2, v in cls_by_cluster[cl].most_common(5)],
        })

    # ---- 4) 输出 ----
    if args.limit:
        out_dir = os.path.join(D, "graph_smoke")
        os.makedirs(out_dir, exist_ok=True)
        np.savez_compressed(os.path.join(out_dir, "knn_csr.npz"), indptr=indptr, indices=indices, sims=sims)
        np.save(os.path.join(out_dir, "clusters.npy"), labels)
        np.save(os.path.join(out_dir, "cluster_centroids.npy"), centroids)
        with open(os.path.join(out_dir, "clusters.json"), "w", encoding="utf-8") as f:
            json.dump({"clusters": clusters_doc}, f, ensure_ascii=False, indent=1)
        print(f"[graph] 冒烟产物 → {out_dir}", flush=True)
    else:
        np.savez_compressed(os.path.join(index_dir, "knn_csr.npz"), indptr=indptr, indices=indices, sims=sims)
        np.save(os.path.join(index_dir, "clusters.npy"), labels)
        np.save(os.path.join(index_dir, "cluster_centroids.npy"), centroids)
        with open(os.path.join(D, "clusters.json"), "w", encoding="utf-8") as f:
            json.dump({"clusters": clusters_doc}, f, ensure_ascii=False, indent=1)
        meta = {
            "n": N, "k": k, "clusters": n_clusters,
            "mutual_ratio": mr, **stats,
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seconds": round(time.time() - t0, 1),
        }
        with open(os.path.join(index_dir, "graph_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"[graph] 产物 → {index_dir}（总计 {time.time() - t0:.0f}s）", flush=True)
        print(json.dumps(meta, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
