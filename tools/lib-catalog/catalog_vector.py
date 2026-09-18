#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
catalog_vector.py — 图书馆目录「向量索引层」（参考 memory-map/memory_vector.py 设计）

对 cards.jsonl 建立双索引：
  - TF-IDF 稀疏索引: scipy CSR；中文 bigram + 英文/数字 token；标题 ×2 加权；L2 归一化
  - 语义向量索引: bge-small-zh-v1.5（512 维 float32；CPU ~500 条/s；全量 ~5-6 min）

子命令:
  build                构建/重建双索引 → <data>/index/
  search  "查询"       语义检索（稠密余弦）
  kw      "查询"       关键词检索（TF-IDF 稀疏余弦）
  hybrid  "查询"       混合检索（0.6*语义 + 0.4*关键词）
  get     <mms>        按 mms 取书卡全貌
  stats                索引统计
  validate             一致性校验 + 冒烟

数据目录: $LIB_CATALOG_DATA 或 ~/go/lib-catalog-data
用法示例:
  python3 catalog_vector.py build
  python3 catalog_vector.py search "机器学习" --top 10
  python3 catalog_vector.py hybrid "费曼 物理" --top 5
"""
import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter

_PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)
import numpy as np

DATA_DEFAULT = os.path.expanduser("~/go/lib-catalog-data")
MODEL_DEFAULT = os.path.expanduser("~/go/models/bge-small-zh-v1.5")

# ---------- 分词（与 memory-map/memory_vector.py 同源） ----------
CJK = re.compile(r"[\u4e00-\u9fff]+")
LATIN = re.compile(r"[a-z0-9][a-z0-9_.\-]*")


def tokenize(text):
    """英文/数字/标识符 token + 中文连续串字符 bigram。"""
    tokens = []
    low = text.lower()
    for m in LATIN.finditer(low):
        tokens.append(m.group(0))
    spans = [m.span() for m in LATIN.finditer(low)]
    pos = 0
    for start, end in spans:
        tokens.extend(_cjk_bigrams(low[pos:start]))
        pos = end
    tokens.extend(_cjk_bigrams(low[pos:]))
    return tokens


def _cjk_bigrams(cjk_text):
    out = []
    seg = ""
    for ch in cjk_text:
        if "\u4e00" <= ch <= "\u9fff":
            seg += ch
        else:
            if seg:
                out.extend(_bigram(seg))
            seg = ""
    if seg:
        out.extend(_bigram(seg))
    return out


def _bigram(seg):
    if len(seg) >= 2:
        return [seg[i:i + 2] for i in range(len(seg) - 1)]
    return [seg]


def resolve_data(args):
    d = (getattr(args, "data", None) or os.environ.get("LIB_CATALOG_DATA")
         or DATA_DEFAULT)
    return os.path.abspath(os.path.expanduser(d))


# ================= build =================

def cmd_build(args):
    D = resolve_data(args)
    cards_path = os.path.join(D, "cards.jsonl")
    if not os.path.exists(cards_path):
        sys.exit(f"[build] 找不到 {cards_path}，先运行 compile_cards.py")
    index_dir = os.path.join(D, "index")
    os.makedirs(index_dir, exist_ok=True)
    t0 = time.time()

    # ---- 1) 扫描 cards：token 化 + df + offsets + 文本 ----
    doc_tfs = []
    df = Counter()
    offsets = []
    texts = []
    mms_list = []
    with open(cards_path, "rb") as f:
        while True:
            pos = f.tell()
            raw = f.readline()
            if not raw:
                break
            offsets.append(pos)
            c = json.loads(raw.decode("utf-8"))
            mms_list.append(c["mms"])
            title = (c.get("title") or "").replace("$$Q", " ")
            creator = (c.get("creator") or "").replace("$$Q", " ")
            publisher = (c.get("publisher") or "").replace("$$Q", " ")
            tf = Counter()
            tk = tokenize(title)
            tf.update(tk)
            tf.update(tk)  # 标题 ×2 加权
            tf.update(tokenize(f"{creator} {publisher}"))
            doc_tfs.append(tf)
            df.update(tf.keys())
            # 语义编码文本：仅 title + creator（不含 publisher——避免"出版社簇"污染主题聚类）
            texts.append(f"{title} {creator}".strip())
    N = len(doc_tfs)
    print(f"[build] 扫描 {N} 卡（{time.time() - t0:.1f}s），词表构建中…", flush=True)

    terms = sorted(df.keys())
    vocab = {t: i for i, t in enumerate(terms)}
    V = len(vocab)
    idf = np.zeros(V, dtype=np.float32)
    for t, j in vocab.items():
        idf[j] = math.log(N / df[t])
    print(f"[build] 词表 {V:,} terms，组装 CSR…", flush=True)

    # ---- 2) CSR 组装（预分配）+ L2 归一化 ----
    nnz = sum(len(tf) for tf in doc_tfs)
    rows = np.empty(nnz, dtype=np.int32)
    cols = np.empty(nnz, dtype=np.int32)
    vals = np.empty(nnz, dtype=np.float32)
    k = 0
    for i, tf in enumerate(doc_tfs):
        for t, w in tf.items():
            j = vocab[t]
            rows[k] = i
            cols[k] = j
            vals[k] = w * idf[j]
            k += 1
    from scipy import sparse
    X = sparse.coo_matrix((vals, (rows, cols)), shape=(N, V)).tocsr()
    X.sum_duplicates()
    norm = np.sqrt(np.asarray(X.multiply(X).sum(axis=1)).ravel())
    norm[norm == 0] = 1.0
    X = sparse.diags(1.0 / norm).dot(X).tocsr()
    sparse.save_npz(os.path.join(index_dir, "tfidf.npz"), X)
    with open(os.path.join(index_dir, "vocab.json"), "w", encoding="utf-8") as f:
        json.dump(terms, f, ensure_ascii=False)
    np.save(os.path.join(index_dir, "idf.npy"), idf)
    np.save(os.path.join(index_dir, "offsets.npy"), np.array(offsets, dtype=np.int64))
    with open(os.path.join(index_dir, "mms_index.json"), "w", encoding="utf-8") as f:
        json.dump({m: i for i, m in enumerate(mms_list)}, f, ensure_ascii=False)
    del doc_tfs
    print(f"[build] TF-IDF 完成: nnz={X.nnz:,}（{time.time() - t0:.1f}s）", flush=True)

    # ---- 3) 语义向量（bge-small-zh-v1.5） ----
    model_path = args.model or MODEL_DEFAULT
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_path)
    t1 = time.time()
    E = model.encode(texts, batch_size=args.batch, show_progress_bar=True,
                     normalize_embeddings=True)
    E = np.asarray(E, dtype=np.float32)
    np.save(os.path.join(index_dir, "embeddings.npy"), E)
    print(f"[build] 语义向量完成: {E.shape}（{time.time() - t1:.1f}s）", flush=True)

    meta = {
        "n": N,
        "dim": int(E.shape[1]),
        "vocab_size": V,
        "nnz": int(X.nnz),
        "model": os.path.basename(model_path),
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_seconds": round(time.time() - t0, 1),
    }
    with open(os.path.join(index_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[build] 全部完成（{time.time() - t0:.1f}s） → {index_dir}", flush=True)
    print(json.dumps(meta, ensure_ascii=False, indent=2), flush=True)


# ================= 索引与查询 =================

class Index:
    def __init__(self, D):
        self.D = D
        self.idx_dir = os.path.join(D, "index")
        self.cards_path = os.path.join(D, "cards.jsonl")
        self._offsets = None
        self._X = None
        self._vocab = None
        self._idf = None
        self._E = None
        self._model = None
        self._knn = None
        self._labels = None
        self._clusters_doc = None
        self._mmsi = None
        meta_p = os.path.join(self.idx_dir, "meta.json")
        self.meta = json.load(open(meta_p, encoding="utf-8")) if os.path.exists(meta_p) else {}

    def offsets(self):
        if self._offsets is None:
            self._offsets = np.load(os.path.join(self.idx_dir, "offsets.npy"))
        return self._offsets

    def X(self):
        if self._X is None:
            from scipy import sparse
            self._X = sparse.load_npz(os.path.join(self.idx_dir, "tfidf.npz"))
        return self._X

    def vocab(self):
        if self._vocab is None:
            with open(os.path.join(self.idx_dir, "vocab.json"), encoding="utf-8") as f:
                terms = json.load(f)
            self._vocab = {t: i for i, t in enumerate(terms)}
        return self._vocab

    def idf(self):
        if self._idf is None:
            self._idf = np.load(os.path.join(self.idx_dir, "idf.npy"))
        return self._idf

    def E(self):
        if self._E is None:
            self._E = np.load(os.path.join(self.idx_dir, "embeddings.npy"))
        return self._E

    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            mp = self.meta.get("model") and os.path.join(os.path.expanduser("~/go/models"), self.meta["model"])
            mp = mp if mp and os.path.isdir(mp) else MODEL_DEFAULT
            self._model = SentenceTransformer(mp)
        return self._model

    def read_cards(self, idxs):
        out = []
        with open(self.cards_path, "rb") as f:
            off = self.offsets()
            for i in idxs:
                f.seek(int(off[i]))
                out.append(json.loads(f.readline().decode("utf-8")))
        return out

    # ---- 图谱与簇（v2） ----
    def knn(self):
        if self._knn is None:
            p = os.path.join(self.idx_dir, "knn_csr.npz")
            if not os.path.exists(p):
                return None
            z = np.load(p)
            self._knn = (z["indptr"], z["indices"], z["sims"])
        return self._knn

    def labels(self):
        if self._labels is None:
            p = os.path.join(self.idx_dir, "clusters.npy")
            self._labels = np.load(p) if os.path.exists(p) else None
        return self._labels

    def links_of(self, i, top=None):
        knn = self.knn()
        if knn is None:
            return []
        indptr, indices, sims = knn
        a, b = int(indptr[i]), int(indptr[i + 1])
        pairs = list(zip(indices[a:b].tolist(), sims[a:b].astype(np.float32).tolist()))
        return pairs[:top] if top else pairs

    def clusters_doc(self):
        if self._clusters_doc is None:
            p = os.path.join(self.D, "clusters.json")
            self._clusters_doc = (json.load(open(p, encoding="utf-8"))["clusters"]
                                  if os.path.exists(p) else [])
        return self._clusters_doc

    def mmsi(self):
        if self._mmsi is None:
            p = os.path.join(self.idx_dir, "mms_index.json")
            self._mmsi = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
        return self._mmsi

    # ---- 查询 ----
    def q_kw(self, query):
        from scipy import sparse
        X, vocab, idf = self.X(), self.vocab(), self.idf()
        V = X.shape[1]
        cnt = Counter(t for t in tokenize(query) if t in vocab)
        if not cnt:
            return None
        js = np.fromiter((vocab[t] for t in cnt), dtype=np.int32, count=len(cnt))
        vs = np.fromiter((idf[vocab[t]] * w for t, w in cnt.items()),
                         dtype=np.float32, count=len(cnt))
        q = sparse.coo_matrix((vs, (np.zeros(len(js), dtype=np.int32), js)),
                              shape=(1, V)).tocsr()
        n = np.sqrt(np.asarray(q.multiply(q).sum()).ravel()[0])
        if n > 0:
            q = q / n
        return np.asarray((X @ q.T).todense()).ravel()

    def q_sem(self, query):
        try:
            E = self.E()
        except (FileNotFoundError, OSError):
            return None
        v = self.model().encode([query], normalize_embeddings=True)[0]
        return E @ np.asarray(v, dtype=np.float32)

    def q_hybrid(self, query, w_sem=0.6, w_kw=0.4):
        s_sem = self.q_sem(query)
        s_kw = self.q_kw(query)
        if s_sem is None and s_kw is None:
            return None
        if s_sem is None:
            return s_kw
        if s_kw is None:
            return s_sem
        return w_sem * s_sem + w_kw * s_kw


def topk(scores, k):
    k = min(k, len(scores))
    if k <= 0:
        return []
    part = np.argpartition(-scores, k - 1)[:k]
    part = part[np.argsort(-scores[part])]
    return [(int(i), float(scores[i])) for i in part]


def fmt_hit(rank, score, c):
    title = (c.get("title") or "").strip()
    creator = (c.get("creator") or "").split("$$Q")[0].strip()
    y = (c.get("year") or "").strip()
    lang = (c.get("language") or "").strip()
    cls = (c.get("cls") or "").strip()
    tags = [t for t in (cls, lang if lang and lang != "chi" else "") if t]
    title_suffix = f"  [{'·'.join(tags)}]" if tags else ""
    parts = []
    if creator:
        parts.append(creator[:52])
    if y:
        parts.append(y)
    if c.get("src") == "hy":
        parts.append("涵泳艺术特藏（清单收录，位置未详）")
    else:
        loc = (c.get("loc") or "").strip()
        if loc:
            segs = loc.split("; ")
            parts.append(segs[0] + (f" 等{len(segs)}处" if len(segs) > 1 else ""))
        if c.get("hc", 0) <= 0 and not loc:
            parts.append("无馆藏位置")
    return f" {rank:>2}. {score:.3f}  {title}{title_suffix}\n        " + " · ".join(parts)


def run_query(args, mode):
    D = resolve_data(args)
    if not os.path.exists(os.path.join(D, "index", "meta.json")):
        sys.exit(f"[query] 索引不存在（{D}/index），先运行 build")
    idx = Index(D)
    t0 = time.time()
    if mode == "sem":
        scores = idx.q_sem(args.query)
        if scores is None:
            print("[query] 语义索引缺失，回退关键词")
            scores = idx.q_kw(args.query)
            mode = "kw"
    elif mode == "kw":
        scores = idx.q_kw(args.query)
    else:
        scores = idx.q_hybrid(args.query)
    if scores is None:
        print(f"[query] 查询词未命中词表: {args.query!r}")
        return 1
    hits = topk(scores, args.top)
    cards = idx.read_cards([i for i, _ in hits])
    label = {"sem": "语义检索", "kw": "关键词检索(TF-IDF)", "hybrid": "混合检索(0.6语义+0.4关键词)"}[mode]
    print(f"=== {label}: {args.query}（top {len(hits)}，{time.time() - t0:.1f}s）=== ")
    for rank, ((i, s), c) in enumerate(zip(hits, cards), 1):
        print(fmt_hit(rank, s, c))
    return 0


# ================= 其它子命令 =================

def cmd_get(args):
    D = resolve_data(args)
    mp = os.path.join(D, "index", "mms_index.json")
    if not os.path.exists(mp):
        sys.exit("[get] 索引不存在，先运行 build")
    mms_map = json.load(open(mp, encoding="utf-8"))
    i = mms_map.get(args.mms)
    if i is None:
        sys.exit(f"[get] 未找到 mms={args.mms}")
    idx = Index(D)
    c = idx.read_cards([i])[0]
    for k in ("mms", "title", "creator", "publisher", "year", "language", "type", "hc", "cn", "cls", "src"):
        v = str(c.get(k, ""))
        print(f"  {k:>9}: {v}")
    loc = (c.get("loc") or "").strip()
    if loc:
        print(f"  locations: ")
        for seg in loc.split("; "):
            print(f"    - {seg}")
    if c.get("src") == "hy":
        print("  note: 涵泳艺术特藏（清单收录，位置未详）")
    lab = idx.labels()
    if lab is not None:
        print(f"  semantic_cluster: #{int(lab[i])}")
    pairs = idx.links_of(i, 5)
    if pairs:
        cards_n = idx.read_cards([j for j, _ in pairs])
        print("  links (top5):")
        for (j, s), cj in zip(pairs, cards_n):
            print(f"    - {s:.3f}  {cj.get('title', '')[:52]}")
    return 0


def _fmt_link_line(rank, score, c):
    creator = (c.get("creator") or "").split("$$Q")[0].strip()
    cls = (c.get("cls") or "").strip()
    parts = [x for x in (f"[{cls}]" if cls else "", creator[:40],
                         (c.get("year") or "").strip()) if x]
    loc = (c.get("loc") or "").strip()
    if loc:
        parts.append(loc.split("; ")[0][:36])
    return (f" {rank:>3}. {score:.3f}  {c.get('title', '')[:52]}"
            f"\n        " + " · ".join(parts))


def cmd_links(args):
    """展开语义内链：某书 → top-K 语义邻居（对齐记忆系统 [[双链]] 展开）。"""
    D = resolve_data(args)
    mp = os.path.join(D, "index", "mms_index.json")
    if not os.path.exists(mp):
        sys.exit("[links] 索引不存在，先运行 build")
    mms_map = json.load(open(mp, encoding="utf-8"))
    i = mms_map.get(args.mms)
    if i is None:
        sys.exit(f"[links] 未找到 mms={args.mms}")
    idx = Index(D)
    c0 = idx.read_cards([i])[0]
    pairs = idx.links_of(i, args.top)
    if not pairs:
        sys.exit("[links] 图索引不存在，先运行 build_graph.py")
    cards = idx.read_cards([j for j, _ in pairs])
    lab = idx.labels()
    cl = f"（语义簇 #{int(lab[i])}）" if lab is not None else ""
    print(f"=== 语义内链: {c0.get('title', '')[:60]}{cl} ===")
    for rank, ((j, s), c) in enumerate(zip(pairs, cards), 1):
        print(_fmt_link_line(rank, s, c) + f"  ←{j}")
    return 0


def _print_cluster(idx, doc, samples=0):
    print(f"=== 语义簇 #{doc['id']}（{doc['size']} 本）===")
    print(f"  关键词: {' / '.join(doc['keywords'][:10])}")
    subs = doc.get("top_subjects") or []
    if subs:
        print("  学科分布: " + "  ".join(f"{k}×{v}" for k, v in subs))
    pos = idx.mmsi()
    exs = [m for m in (doc.get("exemplars") or []) if m in pos]
    if exs:
        cards = idx.read_cards([pos[m] for m in exs])
        print("  代表书:")
        for c in cards:
            creator = (c.get("creator") or "").split("$$Q")[0].strip()[:36]
            print(f"    - {c.get('title', '')[:56]}  {creator}")
    if samples:
        labels = idx.labels()
        if labels is not None:
            ix = np.where(labels == doc["id"])[0][:samples]
            cards = idx.read_cards(ix.tolist())
            print(f"  样例（前 {len(cards)} 本）:")
            for c in cards:
                cls = (c.get("cls") or "").strip()
                print(f"    [{cls}] {c.get('title', '')[:56]}")


def cmd_cluster(args):
    D = resolve_data(args)
    idx = Index(D)
    docs = idx.clusters_doc()
    if not docs:
        sys.exit("[cluster] 簇目录不存在，先运行 build_graph.py")
    if args.mms:
        i = idx.mmsi().get(args.mms)
        if i is None:
            sys.exit(f"[cluster] 未找到 mms={args.mms}")
        labels = idx.labels()
        if labels is None:
            sys.exit("[cluster] 簇索引不存在")
        _print_cluster(idx, docs[int(labels[i])], samples=args.samples)
    elif args.id is not None:
        if not (0 <= args.id < len(docs)):
            sys.exit(f"[cluster] 簇 id 越界（0..{len(docs) - 1}）")
        _print_cluster(idx, docs[args.id], samples=args.samples)
    else:
        sys.exit("[cluster] 需要 <mms> 或 --id N")
    return 0


def cmd_clusters(args):
    D = resolve_data(args)
    idx = Index(D)
    docs = idx.clusters_doc()
    if not docs:
        sys.exit("[clusters] 簇目录不存在，先运行 build_graph.py")
    docs_sorted = sorted(docs, key=lambda d: -d["size"])
    print(f"=== 语义簇目录（共 {len(docs)} 簇；按大小列前 {min(args.top, len(docs))}）===")
    for d in docs_sorted[:args.top]:
        kws = " / ".join(d["keywords"][:6])
        print(f"  #{d['id']:>3}  {d['size']:>5} 本  {kws}")
    return 0


def cmd_graph(args):
    """图扩展：从某书出发，沿语义内链 BFS 展开（对齐记忆系统 link-follow）。"""
    D = resolve_data(args)
    idx = Index(D)
    if idx.knn() is None:
        sys.exit("[graph] 图索引不存在，先运行 build_graph.py")
    i = idx.mmsi().get(args.mms)
    if i is None:
        sys.exit(f"[graph] 未找到 mms={args.mms}")
    c0 = idx.read_cards([i])[0]
    seen = {i}
    frontier = [i]
    levels = []
    for _ in range(args.depth):
        nxt = []
        for node in frontier:
            for j, _s in idx.links_of(node):
                if j not in seen:
                    seen.add(j)
                    nxt.append(j)
        levels.append(nxt)
        frontier = nxt
        if not frontier:
            break
    total = sum(len(l) for l in levels)
    print(f"=== 图扩展: {c0.get('title', '')[:50]}（{args.depth} 跳，共 {total} 本可达）===")
    for d, lvl in enumerate(levels, 1):
        show = lvl[:args.top]
        cards = idx.read_cards(show)
        print(f"  --- 第 {d} 跳（{len(lvl)} 本，显示前 {len(show)}）---")
        for c in cards:
            cls = (c.get("cls") or "").strip()
            print(f"    [{cls}] {c.get('title', '')[:60]}")
    return 0


def cmd_subjects(args):
    D = resolve_data(args)
    p = os.path.join(D, "subjects.json")
    if not os.path.exists(p):
        sys.exit("[subjects] 学科目录不存在（重跑 compile_cards.py v2）")
    s = json.load(open(p, encoding="utf-8"))
    print(f"=== 学科目录（{s['total_with_cn']:,} / {s['total_cards']:,} 本有分类号）===")
    print("  ── 标准学科（中图法） ──")
    for c in s["classes"]:
        subs = " ".join(f"{k}×{v}" for k, v in c["sub"][:5])
        print(f"  {c['code']:>4}  {c['count']:>6}  {c['name']}  |  {subs}")
    cols = s.get("collections") or []
    if cols:
        print("  ── 馆藏代码（非中图法） ──")
        for c in cols:
            print(f"  {c['code']:>5}  {c['count']:>5}")
    return 0


def cmd_shelves(args):
    D = resolve_data(args)
    p = os.path.join(D, "shelves.json")
    if not os.path.exists(p):
        sys.exit("[shelves] 书架数据不存在（重跑 compile_cards.py v2）")
    shelves = json.load(open(p, encoding="utf-8"))["shelves"]
    q = (args.query or "").strip()
    hits = [s for s in shelves
            if not q or q in f"{s['library_name']}/{s['sublocation']}/{s['shelf']}"]
    print(f"=== 书架（共 {len(shelves)}，匹配 {len(hits)}）===")
    for s in hits[:args.top]:
        tops = " ".join(f"{k}×{v}" for k, v in (s.get("top_subjects") or [])[:4])
        print(f"  {s['library_name']}/{s['sublocation']}/{s['shelf']}  {s['books_count']} 本  | {tops}")
    return 0


def cmd_stats(args):
    D = resolve_data(args)
    idx = Index(D)
    if not idx.meta:
        sys.exit("[stats] 索引不存在，先运行 build")
    m = idx.meta
    print("=== 图书馆目录向量索引统计 ===")
    print(f"卡片数:    {m.get('n'):,}")
    print(f"词表:      {m.get('vocab_size'):,} terms")
    print(f"TF-IDF:    nnz={m.get('nnz'):,}（平均每卡 {m.get('nnz', 0) / max(m.get('n', 1), 1):.1f}）")
    print(f"语义向量:  {m.get('n')} × {m.get('dim')}（{m.get('model')}）")
    print(f"构建时间:  {m.get('built_at')}（耗时 {m.get('total_seconds')}s）")
    for fn in ("tfidf.npz", "vocab.json", "idf.npy", "embeddings.npy", "offsets.npy",
               "mms_index.json", "knn_csr.npz", "clusters.npy", "cluster_centroids.npy"):
        p = os.path.join(idx.idx_dir, fn)
        if os.path.exists(p):
            print(f"  {fn:18s} {os.path.getsize(p) / 1e6:8.1f} MB")
    gm_p = os.path.join(idx.idx_dir, "graph_meta.json")
    if os.path.exists(gm_p):
        gm = json.load(open(gm_p, encoding="utf-8"))
        print(f"语义图:    {gm['n']:,} 节点 × {gm['k']} 内链（互链率 {gm['mutual_ratio']:.2f}；"
              f"sim 中位 {gm['sim_median']:.3f}）")
        print(f"语义簇:    {gm['clusters']} 簇（构建于 {gm['built_at']}）")
    print(f"数据目录:  {D}")
    return 0


def cmd_validate(args):
    D = resolve_data(args)
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"  {'✓' if cond else '✗'} {name}{(' — ' + detail) if detail else ''}")
        if not cond:
            ok = False

    print("=== 校验 ===")
    idx = Index(D)
    if not idx.meta:
        sys.exit("[validate] 索引不存在，先运行 build")
    N = idx.meta["n"]
    off = idx.offsets()
    check("offsets 行数 == meta.n", len(off) == N, f"{len(off)} vs {N}")
    E = idx.E()
    check("embeddings 行数 == meta.n", E.shape[0] == N, f"{E.shape}")
    X = idx.X()
    check("tfidf 行数 == meta.n", X.shape[0] == N, f"{X.shape}")
    check("embeddings 已归一化", bool(np.allclose(np.linalg.norm(E[:100], axis=1), 1.0, atol=1e-3)))
    # 抽样读卡
    for i in (0, N // 2, N - 1):
        c = idx.read_cards([i])[0]
        check(f"抽样读卡 #{i}", bool(c.get("title")), c.get("title", "")[:40])
    # 冒烟查询
    s = idx.q_kw("图书馆")
    check("关键词冒烟(kw=图书馆)", s is not None and float(s.max()) > 0)
    s2 = idx.q_hybrid("物理学")
    check("混合冒烟(hybrid=物理学)", s2 is not None and float(s2.max()) > 0)
    # v2: 图与簇
    knn = idx.knn()
    if knn is not None:
        indptr, indices, sims = knn
        check("knn 行数 == meta.n", len(indptr) - 1 == N, f"{len(indptr) - 1}")
        check("knn 每行边数一致", len(indices) % N == 0 and len(indices) // N == int(indptr[1] - indptr[0]))
        lab = idx.labels()
        check("clusters 行数 == meta.n", lab is not None and len(lab) == N,
              f"{None if lab is None else len(lab)}")
        check("links 冒烟(#0)", len(idx.links_of(0)) > 0)
        docs = idx.clusters_doc()
        check("簇目录非空", len(docs) > 0, f"{len(docs)} 簇")
        if docs:
            kw_ok = sum(1 for d in docs if d.get("keywords"))
            check("簇关键词覆盖", kw_ok == len(docs), f"{kw_ok}/{len(docs)}")
    else:
        print("  ⚠ 图索引缺失（build_graph.py 未运行）")
    print("=== " + ("全部通过" if ok else "存在问题") + " ===")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="图书馆目录向量索引层")
    ap.add_argument("--data", default=None, help="数据目录（默认 $LIB_CATALOG_DATA 或 ~/go/lib-catalog-data）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="构建/重建双索引")
    b.add_argument("--model", default=None, help="embedding 模型路径")
    b.add_argument("--batch", type=int, default=128)

    s = sub.add_parser("search", help="语义检索")
    s.add_argument("query")
    s.add_argument("--top", type=int, default=10)
    k = sub.add_parser("kw", help="关键词检索（TF-IDF）")
    k.add_argument("query")
    k.add_argument("--top", type=int, default=10)
    h = sub.add_parser("hybrid", help="混合检索")
    h.add_argument("query")
    h.add_argument("--top", type=int, default=10)

    g = sub.add_parser("get", help="按 mms 取书卡")
    g.add_argument("mms")

    sub.add_parser("stats", help="索引统计")
    sub.add_parser("validate", help="一致性校验")

    lnk = sub.add_parser("links", help="展开语义内链（某书的 top-K 邻居）")
    lnk.add_argument("mms")
    lnk.add_argument("--top", type=int, default=12)
    cl = sub.add_parser("cluster", help="查看语义簇（<mms> 或 --id N）")
    cl.add_argument("mms", nargs="?", default=None)
    cl.add_argument("--id", type=int, default=None)
    cl.add_argument("--samples", type=int, default=0, help="附带簇内样例数")
    cls_ = sub.add_parser("clusters", help="语义簇目录")
    cls_.add_argument("--top", type=int, default=25)
    gr = sub.add_parser("graph", help="图扩展（沿语义内链 BFS）")
    gr.add_argument("mms")
    gr.add_argument("--depth", type=int, default=2)
    gr.add_argument("--top", type=int, default=10)
    sub.add_parser("subjects", help="学科目录")
    sh = sub.add_parser("shelves", help="书架查询")
    sh.add_argument("query", nargs="?", default=None)
    sh.add_argument("--top", type=int, default=30)

    args = ap.parse_args()
    if args.cmd == "build":
        return cmd_build(args)
    if args.cmd == "search":
        return run_query(args, "sem")
    if args.cmd == "kw":
        return run_query(args, "kw")
    if args.cmd == "hybrid":
        return run_query(args, "hybrid")
    if args.cmd == "get":
        return cmd_get(args)
    if args.cmd == "stats":
        return cmd_stats(args)
    if args.cmd == "validate":
        return cmd_validate(args)
    if args.cmd == "links":
        return cmd_links(args)
    if args.cmd == "cluster":
        return cmd_cluster(args)
    if args.cmd == "clusters":
        return cmd_clusters(args)
    if args.cmd == "graph":
        return cmd_graph(args)
    if args.cmd == "subjects":
        return cmd_subjects(args)
    if args.cmd == "shelves":
        return cmd_shelves(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
