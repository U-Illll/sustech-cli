#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_release.py — 图书馆目录「GitHub Release 分发包」导出器

从完整数据目录导出面向分发的瘦身版（供 sustech-cli 等项目使用）：
  - cards.jsonl.gz            书卡（gzip 压缩）
  - embeddings_int8.npy       bge 向量 int8 量化（N×512）
  - embeddings_scale.npy      每向量量化 scale（float32）
  - embeddings_meta.json      量化说明（还原公式）
  - knn_csr.npz               语义内链图（CSR）
  - clusters.json / clusters.npy / cluster_centroids.npy
  - subjects.json / shelves.json
  - tfidf/                    TF-IDF 稀疏三件套（.bin） + vocab/idf
  - manifest.json             版本/统计/文件清单（含 sha256）

用法:
  python3 export_release.py [--data DIR] [--out DIR] [--version v1]
"""
import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
import time

_PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)
import numpy as np

DATA_DEFAULT = os.path.expanduser("~/go/lib-catalog-data")
OUT_DEFAULT = os.path.expanduser("~/go/lib-catalog-release")


def resolve_data(args):
    return os.path.abspath(os.path.expanduser(
        getattr(args, "data", None) or os.environ.get("LIB_CATALOG_DATA") or DATA_DEFAULT))


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def quantize_int8(E):
    """每向量 max-abs 缩放量化。还原: v ≈ q * scale / 127。"""
    scale = np.abs(E).max(axis=1)                     # (N,)
    scale[scale == 0] = 1.0
    Q = np.round(E / scale[:, None] * 127.0).clip(-127, 127).astype(np.int8)
    return Q, scale.astype(np.float32)


def quality_check_against(E_full, E_used, Q, scale, n_queries=200, topn=20, chunk=8192):
    """对照实验：全维 float32 检索（基线） vs 发行库（投影+int8）的 top-K 重叠率。
    查询侧模拟真实流程：query 全维向量 → (如有 PCA) 投影 → 归一化。"""
    N = E_full.shape[0]
    rng = np.random.default_rng(0)
    q_idx = rng.choice(N, size=min(n_queries, N), replace=False)
    Qq_full = E_full[q_idx]                            # (q, 512)
    # 基线（全维 float32）
    S32 = E_full @ Qq_full.T
    top32 = np.argsort(-S32, axis=0)[:topn]
    # 发行库检索
    if E_used.shape[1] != E_full.shape[1]:
        # 查询投影（用库向量的等效投影：从 E_used 反推不可行；调用方已保证 E_used = E_full @ W.T）
        # 这里直接用 E_used 的行作为投影后查询的近似（query = 库内同一条目）
        Qq_proj = E_used[q_idx]
    else:
        Qq_proj = Qq_full
    # 归一化投影后查询
    nrm = np.linalg.norm(Qq_proj, axis=1, keepdims=True)
    nrm[nrm == 0] = 1.0
    Qq_proj = Qq_proj / nrm
    S8 = np.empty((N, top32.shape[1]), dtype=np.float32)
    sc = (scale / 127.0).astype(np.float32)
    for i0 in range(0, N, chunk):
        i1 = min(i0 + chunk, N)
        S8[i0:i1] = (Q[i0:i1].astype(np.float32) @ Qq_proj.T) * sc[i0:i1, None]
    top8 = np.argsort(-S8, axis=0)[:topn]
    inter = np.array([len(set(top32[:, j]) & set(top8[:, j])) for j in range(top32.shape[1])])
    return {
        "n_queries": int(top32.shape[1]),
        "topn": topn,
        "overlap_mean": float(inter.mean() / topn),
        "overlap_min": float(inter.min() / topn),
        "rank1_same": float((top32[0] == top8[0]).mean()),
    }


def export_tfidf(index_dir, out_tfidf):
    from scipy import sparse
    X = sparse.load_npz(os.path.join(index_dir, "tfidf.npz")).tocsr()
    os.makedirs(out_tfidf, exist_ok=True)
    X.indptr.astype(np.int32).tofile(os.path.join(out_tfidf, "indptr.bin"))
    X.indices.astype(np.int32).tofile(os.path.join(out_tfidf, "indices.bin"))
    X.data.astype(np.float32).tofile(os.path.join(out_tfidf, "data.f32.bin"))
    shutil.copyfile(os.path.join(index_dir, "vocab.json"), os.path.join(out_tfidf, "vocab.json"))
    np.load(os.path.join(index_dir, "idf.npy")).astype(np.float32).tofile(os.path.join(out_tfidf, "idf.f32.bin"))
    return {"rows": int(X.shape[0]), "cols": int(X.shape[1]), "nnz": int(X.nnz)}


def export_topics(D, out, files, note_file, strict=False):
    """topics 主题图导出版（**只生成，不发布**；沿用 v1 瘦身风格：CSR + uint8 量化权重）。

    产物（全部落 <out>/topics/）：
      nodes.json                主题节点表（kw + cls）
      edges_indptr.i64.bin      边表 CSR 行偏移（int64 LE, n+1）
      edges_indices.i32.bin     边表 CSR 列索引（int32 LE, nnz）
      edges_weights.u8.bin      边权 uint8 量化（w ≈ v/255，float32 原始 ∈[0,1]）
      edges_types.u8.bin        边型 bitmask（可选；源 npz 有 types 键时导出）
      card_topics_indptr.i32.bin 证据链 CSR 行偏移（int32 LE, N_cards+1）
      card_topics_ids.i32.bin   证据链主题 id（int32 LE, nnz；每卡 ≤5）
      meta.json                 口径登记（stages.P0–R2-C）
      manifest.topics.json      本节清单（含 sha256/统计/还原公式/**快照绑定**）

    R2-C 修复（AUDIT-EXPORT E1/E2/E5/E8/E10）：
      · E1 随包 meta 与随包数据**强制同源**：复制前把 meta 登记值与实测值逐项对齐，
           比对结果 + 源数据 sha256 写进 `manifest.topics.json#snapshot`；
           `strict=True` 不一致即失败，否则大声告警（绝不静默）。
      · E2 证据链行数断言：空行不再 `continue` 静默错位，行数必须 == cards.jsonl 行数。
      · E5 量化契约登记误差上界/分辨率/码位占用。
      · E8 manifest 增 `package_kind` 区分 topics 包与全量包。
      · E10 量化前显式拒绝 NaN/越界权重与 int32 溢出。
    """
    td = os.path.join(D, "topics")
    tdir = os.path.join(out, "topics")
    os.makedirs(tdir, exist_ok=True)

    # 源数据快照哈希（E1：供包内自证「meta 与数据同源」）
    snap_src = {}
    for name in ("nodes.json", "edges.csr.npz", "card_topics.jsonl", "meta.json", "cards.jsonl"):
        src = os.path.join(td, name) if name != "cards.jsonl" else os.path.join(D, name)
        snap_src[name] = sha256_file(src) if os.path.exists(src) else None

    # 节点表
    p = os.path.join(tdir, "nodes.json")
    shutil.copyfile(os.path.join(td, "nodes.json"), p)
    note_file(p, "主题节点表（JSON；{id,term,type:kw|cls,freq,cluster,cls,sources}）")

    # 边表 CSR + uint8 权重
    z = np.load(os.path.join(td, "edges.csr.npz"))
    indptr = z["indptr"].astype(np.int64)
    indices = z["indices"].astype(np.int32)
    w = z["weights"].astype(np.float32)
    if not (np.isfinite(w).all() and (w >= 0).all() and (w <= 1).all()):   # E10
        raise SystemExit("[export][ERR] 边权含 NaN/越界，拒绝量化导出（E10）")
    if len(indices) >= 2 ** 31 - 1:                                        # E10
        raise SystemExit("[export][ERR] nnz 超 int32 范围，拒绝导出（E10）")
    w_u8 = np.clip(np.round(w * 255.0), 0, 255).astype(np.uint8)
    p = os.path.join(tdir, "edges_indptr.i64.bin")
    indptr.tofile(p)
    note_file(p, "主题图 CSR 行偏移（int64 LE, n+1；与节点表行序对齐）")
    p = os.path.join(tdir, "edges_indices.i32.bin")
    indices.tofile(p)
    note_file(p, "主题图 CSR 列索引（int32 LE, nnz；有向，出度 ≤20；行内按构建期 rank 序，非列升序）")
    p = os.path.join(tdir, "edges_weights.u8.bin")
    w_u8.tofile(p)
    note_file(p, "主题图边权 uint8 LE（还原: w = v / 255.0；原始 float32 ∈[0,1]，1.0 = 层级边/饱和共现）")

    # 边型 bitmask（AUDIT-EDGETYPE 方案 a；源 npz 无 types 键时跳过并告警）
    types_src = z["types"].astype(np.uint8) if "types" in z.files else None
    if types_src is not None:
        p = os.path.join(tdir, "edges_types.u8.bin")
        types_src.tofile(p)
        note_file(p, "边型 bitmask uint8 LE（与 edges_indices 行序对齐；bit0=共现 bit1=同簇加成 bit2=层级）")
    else:
        print("[export][WARN] 源边表无 types 键，跳过 edges_types.u8.bin（AUDIT-EDGETYPE 方案 a 未落地）",
              file=sys.stderr, flush=True)

    # 证据链 CSR（卡 → top-5 主题）
    ip, ids = [0], []
    n_lines = 0
    with open(os.path.join(td, "card_topics.jsonl"), encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            if not line.strip():                                    # E2：不再静默 continue
                raise SystemExit(f"[export][ERR] card_topics.jsonl 第 {ln} 行为空 → 证据链会错位，拒绝导出（E2）")
            ids.extend(int(t) for t in json.loads(line).get("topics", ()))
            ip.append(len(ids))
            n_lines += 1
    cards_path = os.path.join(D, "cards.jsonl")
    if os.path.exists(cards_path):                                  # E2：与 cards.jsonl 行数对齐
        with open(cards_path, "rb") as f:
            n_cards_src = sum(1 for _ in f)
        if n_cards_src != n_lines:
            raise SystemExit(f"[export][ERR] card_topics.jsonl 行数 {n_lines} != cards.jsonl 行数 "
                             f"{n_cards_src} → 证据链行序不保证对齐，拒绝导出（E2）")
    ip_a = np.asarray(ip, dtype=np.int32)
    ids_a = np.asarray(ids, dtype=np.int32)
    p = os.path.join(tdir, "card_topics_indptr.i32.bin")
    ip_a.tofile(p)
    note_file(p, "证据链 CSR 行偏移（int32 LE, N_cards+1；与 cards.jsonl 行序一致）")
    p = os.path.join(tdir, "card_topics_ids.i32.bin")
    ids_a.tofile(p)
    note_file(p, "证据链主题 id（int32 LE, nnz；每卡 top-5 主题，按词权降序）")

    # 口径登记（E1：复制前必须与本次导出所用数据同源）
    meta_src = os.path.join(td, "meta.json")
    meta_check = {"checked": False, "consistent": None, "mismatches": [], "registered": {}, "measured": {}}
    if os.path.exists(meta_src):
        with open(meta_src, encoding="utf-8") as f:
            meta_obj = json.load(f)
        p2 = ((meta_obj.get("stages") or {}).get("P2") or {})
        c_p2, e_p2 = (p2.get("counts") or {}), (p2.get("edge_stats") or {})
        wd = e_p2.get("weight_dist") or {}
        # 包内 u8 反算（与消费方看到的一致），用于对账 meta 登记值
        u8_eq1 = int((w_u8 == 255).sum())
        registered = {
            "nodes": c_p2.get("nodes"),
            "edges": wd.get("n"),
            "cards": c_p2.get("cards"),
            "avg_out_degree": e_p2.get("avg_out_degree"),
            "weight_mean": wd.get("mean"),
            "w_eq_1_share": e_p2.get("w_eq_1_share"),
        }
        measured = {
            "nodes": int(len(indptr) - 1),
            "edges": int(len(indices)),
            "cards": int(len(ip_a) - 1),
            "avg_out_degree": round(float(np.diff(indptr).mean()), 3),
            "weight_mean": round(float(w.mean()), 4),
            "w_eq_1_share": round(u8_eq1 / max(len(w_u8), 1), 4),
        }
        tol = {"nodes": 0, "edges": 0, "cards": 0, "avg_out_degree": 5e-4,
               "weight_mean": 5e-5, "w_eq_1_share": 5e-5}
        for k, mv in measured.items():
            rv = registered.get(k)
            if rv is None:
                meta_check["mismatches"].append(f"{k}: meta 未登记")
            elif abs(float(rv) - float(mv)) > tol[k]:
                meta_check["mismatches"].append(f"{k}: meta={rv} vs 包内数据={mv}")
        meta_check.update({"checked": True, "consistent": not meta_check["mismatches"],
                           "registered": registered, "measured": measured,
                           "u8_recomputed_w_eq1_count": u8_eq1,
                           "meta_snapshot": {"stage": meta_obj.get("current_stage"),
                                             "updated_at": meta_obj.get("updated_at")}})
        p = os.path.join(tdir, "meta.json")
        shutil.copyfile(meta_src, p)
        note_file(p, "主题图口径登记（stages.P0–R2-C：参数/计数/统计/裁定；见 manifest#snapshot 的同源校验）")
        if meta_check["consistent"]:
            print("[export] E1 同源校验 PASS：随包 meta 登记值与随包数据逐项一致", flush=True)
        else:
            msg = ("[export][ERR] E1 随包 meta 与随包数据**不同源**：" + "; ".join(meta_check["mismatches"]))
            if strict:
                raise SystemExit(msg + "（--strict 下拒绝导出）")
            print(msg + "（未加 --strict，仅告警；请重跑对应阶段刷新 meta）", file=sys.stderr, flush=True)

    stats = {
        "nodes": int(len(indptr) - 1),
        "edges": int(len(indices)),
        "avg_outdeg": round(float(np.diff(indptr).mean()), 3),
        "max_outdeg": int(np.diff(indptr).max()),
        "cards": int(len(ip_a) - 1),
        "card_topic_links": int(len(ids_a)),
        "dtypes": {"indptr": "int64", "indices": "int32", "weights_u8": "uint8",
                   "card_indptr": "int32", "card_ids": "int32"},
        "restore": {"edge_weight": "w = v / 255.0", "nodes": "JSON 数组，id = CSR 行号",
                    "card_topics": "第 i 行（0-based）对应 cards.jsonl 第 i 行"},
        # E5：量化契约（误差上界/分辨率/码位占用）
        "quant": {"rule": "code = clip(round(w*255), 0, 255)", "step": 1.0 / 255.0,
                  "max_abs_err": 1.0 / 510.0, "w_min": round(float(w.min()), 6),
                  "w_max": round(float(w.max()), 6), "codes_used": int(len(np.unique(w_u8))),
                  "saturated_share": round(float((w_u8 == 255).mean()), 4),
                  "restore": "w ≈ v / 255.0"},
        "edge_types": ({"dtype": "uint8", "bits": {"0": "共现", "1": "同簇加成", "2": "层级"},
                        "hist": {str(int(k)): int(v) for k, v in
                                 zip(*np.unique(types_src, return_counts=True))}}
                       if types_src is not None else None),
    }
    p = os.path.join(tdir, "manifest.topics.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"name": "sustc-library-catalog-topics", "package_kind": "topics-only",
                   "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "snapshot": {"source_data_dir": D, "source_sha256": snap_src,
                                "meta_binding": meta_check},
                   "stats": stats,
                   "files": [x for x in files if x["path"].startswith("topics/")]}, f,
                  ensure_ascii=False, indent=1)
    note_file(p, "topics 导出版清单（各文件 sha256 / 还原公式 / 源数据快照与 meta 同源校验）")
    print(f"[export] topics 导出版 → {tdir}（{stats['nodes']} 节点 / {stats['edges']} 边 / "
          f"{stats['card_topic_links']} 条卡-主题链接）", flush=True)
    return stats


def main():
    ap = argparse.ArgumentParser(description="图书馆目录发行包导出器")
    ap.add_argument("--data", default=None, help="完整数据目录")
    ap.add_argument("--out", default=OUT_DEFAULT, help="发行包输出根目录")
    ap.add_argument("--version", default="v1", help="数据版本号（默认 v1）")
    ap.add_argument("--pca", type=int, default=384,
                    help="语义向量 PCA 目标维（默认 384；0 = 不降维，全 512 维）")
    ap.add_argument("--topics", action="store_true",
                    help="附带导出主题图（topics/ 子目录，只生成不发布；默认关闭，行为与 v1 一致）")
    ap.add_argument("--topics-only", action="store_true",
                    help="只导出主题图（跳过 v1 全量导出；用于快速生成样例）")
    ap.add_argument("--strict", action="store_true",
                    help="严格模式：随包 meta 与随包数据不同源时直接失败（E1）")
    args = ap.parse_args()

    D = resolve_data(args)
    index_dir = os.path.join(D, "index")
    out = os.path.join(args.out, args.version)
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    files = []

    def note_file(path, desc):
        files.append({
            "path": os.path.relpath(path, out),
            "size": os.path.getsize(path),
            "sha256": sha256_file(path),
            "note": desc,
        })

    # ---- 0) 仅导出主题图（P5 新增；不影响 v1 流程） ----
    if args.topics_only:
        tstats = export_topics(D, out, files, note_file, strict=args.strict)
        manifest = {
            "name": "sustc-library-catalog-topics", "version": args.version,
            "package_kind": "topics-only",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "南方科技大学图书馆公开检索系统导出（主题图 GraphRAG-lite 子集）",
            "license_note": "公开书目事实数据；仅供 sustech-cli 等项目离线使用（本包只生成不发布）",
            "stats": {"topics": tstats},
            "files": files,
            "total_bytes": sum(f["size"] for f in files),
        }
        with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        print(f"[export] 仅 topics 完成 → {out}（{time.time() - t0:.0f}s；"
              f"{manifest['total_bytes'] / 1e6:.2f} MB / {len(files)} 个文件）", flush=True)
        return

    # ---- 1) cards.jsonl.gz ----
    print("[export] cards.jsonl.gz …", flush=True)
    p = os.path.join(out, "cards.jsonl.gz")
    with open(os.path.join(D, "cards.jsonl"), "rb") as fi, \
         gzip.open(p, "wb", compresslevel=9) as fo:
        shutil.copyfileobj(fi, fo)
    note_file(p, "书卡（每行一个 JSON；字段: mms/title/creator/publisher/year/language/type/hc/loc/cn/cls/cls2/src）")

    # ---- 2) embeddings（可选 PCA → int8）+ 质量对照 ----
    print("[export] embeddings 量化/PCA + 质量对照 …", flush=True)
    E = np.load(os.path.join(index_dir, "embeddings.npy"))
    N_e, D_e = E.shape
    if args.pca and args.pca < D_e:
        from sklearn.decomposition import PCA
        t_p = time.time()
        pca = PCA(n_components=args.pca, svd_solver="randomized", random_state=42)
        pca.fit(E)
        W = pca.components_.astype(np.float32)        # (pca, 512)
        Eproj = (E @ W.T).astype(np.float32)
        nrm = np.linalg.norm(Eproj, axis=1, keepdims=True)   # 投影后重新归一化（保持余弦语义）
        nrm[nrm == 0] = 1.0
        Eproj = Eproj / nrm
        print(f"[export] PCA {D_e}→{args.pca}（fit+transform {time.time() - t_p:.0f}s；"
              f"解释方差 {pca.explained_variance_ratio_.sum():.4f}）", flush=True)
        p = os.path.join(out, "pca_components.f32.bin")
        W.tofile(p)
        note_file(p, f"PCA 投影矩阵 W（{args.pca}\u00d7{D_e}, float32 LE）；查询与库向量均需投影: v_p = v @ W.T，投影后再归一化")
        E_used, dim_used = Eproj, args.pca
    else:
        E_used, dim_used = E, D_e
    Q, scale = quantize_int8(E_used)
    p = os.path.join(out, "embeddings_int8.bin")
    Q.tofile(p)
    note_file(p, f"bge-small-zh-v1.5 向量 int8 量化（{N_e}\u00d7{dim_used}, int8 LE）；还原: v = q * scale / 127")
    p = os.path.join(out, "embeddings_scale.f32.bin")
    scale.tofile(p)
    note_file(p, f"每向量量化 scale（float32 LE, {N_e}）")
    qc = quality_check_against(E, E_used, Q, scale)
    with open(os.path.join(out, "embeddings_meta.json"), "w", encoding="utf-8") as f:
        json.dump({
            "model": "bge-small-zh-v1.5", "dim_full": int(D_e), "dim": int(dim_used),
            "n": int(N_e), "pca": bool(args.pca and args.pca < D_e),
            "dtype": "int8",
            "restore": ("v_p = (q * scale / 127.0); 检索时先对 raw 向量做 q_raw @ W.T 再归一化" if args.pca and args.pca < D_e
                        else "v = q * scale / 127.0"),
            "quality_vs_float32_full_dim": qc,
        }, f, ensure_ascii=False, indent=1)
    note_file(os.path.join(out, "embeddings_meta.json"), "量化/PCA 说明与质量对照（vs 全维 float32）")
    print(f"[export] 质量对照: top{qc['topn']} 重叠 均值 {qc['overlap_mean']:.4f} / 最小 {qc['overlap_min']:.4f}；rank1 一致 {qc['rank1_same']:.4f}", flush=True)

    # ---- 3) 图与簇 ----
    print("[export] 图与簇 …", flush=True)
    z = np.load(os.path.join(index_dir, "knn_csr.npz"))
    indptr = z["indptr"].astype(np.int64)
    indices = z["indices"].astype(np.int32)
    sims_u8 = np.clip(np.round(z["sims"].astype(np.float32) * 255.0), 0, 255).astype(np.uint8)
    p = os.path.join(out, "knn_indptr.i32.bin")
    indptr.astype(np.int32).tofile(p)
    note_file(p, "语义内链图 CSR 行偏移（int32 LE, N+1；每行恰 K 边）")
    p = os.path.join(out, "knn_indices.i32.bin")
    indices.tofile(p)
    note_file(p, "语义内链图 CSR 邻居行号（int32 LE, N×K）")
    p = os.path.join(out, "knn_sims.u8.bin")
    sims_u8.tofile(p)
    note_file(p, "邻居余弦相似度（uint8 LE：sim ≈ v / 255）")
    p = os.path.join(out, "clusters.i32.bin")
    np.load(os.path.join(index_dir, "clusters.npy")).astype(np.int32).tofile(p)
    note_file(p, "语义簇归属（int32 LE, N；行序对齐 cards）")
    p = os.path.join(out, "cluster_centroids.f32.bin")
    np.load(os.path.join(index_dir, "cluster_centroids.npy")).astype(np.float32).tofile(p)
    note_file(p, "簇质心（float32 LE, k×512）")
    p = os.path.join(out, "clusters.json")
    shutil.copyfile(os.path.join(D, "clusters.json"), p)
    note_file(p, "簇目录（id/大小/关键词/代表书/学科分布）")
    p = os.path.join(out, "subjects.json")
    shutil.copyfile(os.path.join(D, "subjects.json"), p)
    note_file(p, "学科目录（中图法 38 组 + 馆藏代码 10 组）")
    p = os.path.join(out, "shelves.json")
    shutil.copyfile(os.path.join(D, "shelves.json"), p)
    note_file(p, "书架层（416 架，含学科画像）")

    # ---- 4) tfidf 三件套 ----
    print("[export] tfidf …", flush=True)
    st = export_tfidf(index_dir, os.path.join(out, "tfidf"))
    for fn, desc in [
        ("indptr.bin", "CSR 行偏移（int32 LE, N+1）"),
        ("indices.bin", "CSR 列索引（int32 LE, nnz）"),
        ("data.f32.bin", "CSR 数据（float32 LE, nnz；L2 归一化 tf-idf）"),
        ("vocab.json", "词表（term 列表，id=下标）"),
        ("idf.f32.bin", "IDF 权重（float32 LE, V）"),
    ]:
        note_file(os.path.join(out, "tfidf", fn), desc)

    # ---- 5) 静态资源（README / examples） ----
    rf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "release_files")
    if os.path.isdir(rf):
        for root, _dirs, names in os.walk(rf):
            for nm in names:
                src_p = os.path.join(root, nm)
                rel = os.path.relpath(src_p, rf)
                dst_p = os.path.join(out, rel)
                os.makedirs(os.path.dirname(dst_p), exist_ok=True)
                shutil.copyfile(src_p, dst_p)
                note_file(dst_p, "静态资源（说明/示例；非数据文件）")
        print("[export] 静态资源已复制（README.md / examples/）", flush=True)

    # ---- 5.5) topics 导出版（可选，--topics） ----
    topics_stats = None
    if args.topics:
        print("[export] topics 导出版 …", flush=True)
        topics_stats = export_topics(D, out, files, note_file)

    # ---- 6) manifest ----
    gm = json.load(open(os.path.join(index_dir, "graph_meta.json"), encoding="utf-8"))
    cr = json.load(open(os.path.join(D, "compile_report.json"), encoding="utf-8"))
    manifest = {
        "name": "sustc-library-catalog-vector-db",
        "version": args.version,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "南方科技大学图书馆公开检索系统导出（2026-09-18 补抓版，188,512 书目）",
        "license_note": "公开书目事实数据；供 sustech-cli 等项目离线检索使用",
        "stats": {
            "cards": cr["cards_total"],
            "with_call_number": cr["cards_with_cn"],
            "shelves": cr["shelves"],
            "knn_k": gm["k"],
            "knn_mutual_ratio": gm["mutual_ratio"],
            "clusters": gm["clusters"],
            "dim": 512,
            "model": "bge-small-zh-v1.5",
            "tfidf": st,
            **({"topics": topics_stats} if topics_stats else {}),
        },
        "docid_rule": {
            "note": "与 Primo 记录标识的对应关系（供 sustech-cli 构造 reference/detailUrl）",
            "docid": "L:alma<mms>",
            "detail_url_template": "https://sustc.primo.exlibrisgroup.com.cn/discovery/fulldisplay?docid=alma{mms}&context=L&vid=86SUSTC_INST:86SUSTC_INST&lang=zh_CN",
        },
        "files": files,
        "total_bytes": sum(f["size"] for f in files),
    }
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"[export] 完成 → {out}（{time.time() - t0:.0f}s）", flush=True)
    print(f"[export] 总大小: {manifest['total_bytes'] / 1e6:.1f} MB（{len(files)} 个文件）", flush=True)
    print(json.dumps({k: v for k, v in manifest["stats"].items() if k != "tfidf"},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
