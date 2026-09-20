# SUSTech Library Catalog — offline vector database

Offline dataset for SUSTech Library catalog search: **188,512 bibliographic records**
from the public Primo VE catalog (export 2026-09-18), compiled into an embeddable
vector database with semantic links, topic clusters and shelf-level locations.

Built by the `lib-catalog` toolchain, mirroring a memory-system architecture
(compile layer → dense vectors + sparse index → semantic link graph → topic clusters).

## Files

| File | Shape / Type | Description |
|---|---|---|
| `cards.jsonl.gz` | JSONL, 188,512 lines | Book cards: `mms/title/creator/publisher/year/language/type/hc/loc/cn/cls/cls2/src` |
| `embeddings_int8.bin` | int8 `[N, 384]`, C-order | bge-small-zh-v1.5 vectors, PCA→384 then int8-quantized |
| `embeddings_scale.f32.bin` | float32 `[N]` | Per-vector dequant scale: `v ≈ q * scale / 127` |
| `pca_components.f32.bin` | float32 `[384, 512]` | PCA matrix W; project queries: `q_p = q @ W.T`, then L2-normalize |
| `knn_indptr.i32.bin` | int32 `[N+1]` | Semantic link graph CSR row offsets (10 edges/row) |
| `knn_indices.i32.bin` | int32 `[N×10]` | Neighbor row indices |
| `knn_sims.u8.bin` | uint8 `[N×10]` | Cosine similarity `sim ≈ v / 255` |
| `clusters.i32.bin` | int32 `[N]` | Semantic cluster id per card |
| `clusters.json` | JSON | 400 cluster directory (keywords / exemplars / subject mix) |
| `cluster_centroids.f32.bin` | float32 `[400, 384]` | Cluster centroids (projected space) |
| `subjects.json` | JSON | CLC subject classes (38) + collection codes |
| `shelves.json` | JSON | 416 shelves with top-subject profiles |
| `tfidf/indptr.bin` `indices.bin` `data.f32.bin` | int32/int32/float32 | TF-IDF CSR (338,358 terms; 3,665,655 nnz; L2-normalized) |
| `tfidf/vocab.json` `idf.f32.bin` | JSON / float32 | Term vocabulary + IDF |
| `manifest.json` | JSON | Version, stats, per-file sha256 |
| `examples/node-client.js` | JS | Zero-dependency reference client (search / similar / links / cluster / docid) |

All binary files are **little-endian raw arrays** (no headers).

## Quick start (Node.js)

```bash
node examples/node-client.js . search "三体" --top 5           # keyword (TF-IDF)
node examples/node-client.js . similar <mms> --top 10          # semantic (int8 pipeline)
node examples/node-client.js . links <mms> --top 10            # precomputed graph neighbors
node examples/node-client.js . cluster <mms|#id>               # cluster directory
node examples/node-client.js . docid <mms>                     # Primo docId + detailUrl
```

## Semantic search pipeline (for integration)

1. Encode the query with **bge-small-zh-v1.5** → 512-d float vector → L2-normalize
2. Project: `q = normalize(q @ W.T)` with `W = pca_components.f32.bin` (512 → 384)
3. Score: `score[i] = Σ_j q8[i][j] * q[j] * scale[i] / 127` against `embeddings_int8.bin`
4. Top-K sort. (Expected quality: top-20 overlap ≈ 0.98 vs full 512-d float32, see `embeddings_meta.json`.)

Alternative: for the **keyword path**, tokenize query the same way as the build
(ASCII words + CJK character bigrams), look up term ids via `vocab.json`,
accumulate `Σ data[k] * q[col]` over the TF-IDF CSR, then sort.

## Primo mapping

- `docId = L:alma<mms>`, `reference` same
- `detailUrl`: see `manifest.json → docid_rule.detail_url_template`
- `creators ← creator.split(";")`; `date ← year`; `format ← type`; `availability ← loc`

## Source

Public bibliographic facts from the SUSTech Library public Primo read-only
interface (no login required). Intended for offline use with
[sustech-cli](https://github.com/wormforce/sustech-cli).

---

## GraphRAG topic layer (v2) — `topics/`

A topic-level GraphRAG layer built on top of the per-card data. All files are
plain JSON / NumPy little-endian arrays.

| File | Shape / Type | Description |
|---|---|---|
| `topics/nodes.json` | JSON array | **5,507 topic nodes** (`id/term/type/freq/cluster/cls/sources`; kw + CLC-class terms) |
| `topics/edges.csr.npz` | NPZ (i64/i32/f32/u8) | Weighted topic graph — `indptr`, `indices`, `weights` ∈ [0,1], and a per-edge `types` **bitmask** (1=co-occurrence, 2=same-cluster, 4=hierarchy); max out-degree 20, 105,414 edges |
| `topics/card_topics.jsonl` | JSONL × 188,512 | Per-card top-5 topics (evidence chain from topic → books) |
| `topics/meta.json` | JSON | Stage-wise registry (P0–P5 + R1/R2 fix records, calibers, judgments) |
| `topics/README.md` | MD | Field reference, CLI usage, caliber definitions |
| `topics/ACCEPTANCE-REPORT.md` | MD | End-to-end acceptance (147 assertions, all green) + independent audit records |
| `topics/INTERFACE-PROPOSAL.md` | MD | Proposed `summarize_topic_region(region) -> str` LLM interface — **stub only, not wired** (see note below) |
| `topics/audit/` | dir | 16 independent audit reports with reproducible checks |
| `topics/export-sample/` | dir | Quantized export sample (u8 weights + CSR, self-consistent) |

Verified quality gates: 12-hop same-cluster coverage **0.9927** (threshold 0.90),
99.95% single connected component, per-edge types verified over the full graph,
p50 query latency ~2.6 ms. History: an incremental fix round (R1/R2) and an
independent model review are documented in the reports.

> **LLM note**: the interface proposal is a frozen stub
> (`TOPIC_LLM=off`); it is intentionally not wired to any provider.
>
> `summarize_topic_region(region) -> str` — takes a diffusion region
> (nodes/edges/weights + evidence books) and returns a natural-language summary.
> sustech-cli itself does not embed an LLM today, so this interface is left for
> future integration (agent side or optional CLI capability).

## Book label layer (v3.1) — `labels.db`

A **location-level label index**: for every catalog location it resolves the
**book label call number** — the classification + accession code printed on the
physical book spine (e.g. `TP393.08 /5:2`) — enabling shelf-precise lookup
(book → label → shelf). Built from the 2026-09-20 labeled export.

| File | Shape / Type | Description |
|---|---|---|
| `labels.db` | SQLite | `label(mms, seq, lib, sub, shelf, call)` + `mms` index — 221,767 rows / 187,477 records |

Usage (stdlib `sqlite3`): `SELECT * FROM label WHERE mms = ?`. Multi-volume
works carry one row per volume (distinct `call` suffix). Rebuild:
`tools/lib-catalog/build_labels_db.py`; shared helpers:
`tools/lib-catalog/book_labels.py`.

## Toolchain — `tools/lib-catalog/`

The Python toolchain that built both layers, kept alongside for reproducibility:

- Data: `compile_cards.py`, `catalog_vector.py`, `build_graph.py`, `graph_report.py`, `export_release.py`
- Topic layer: `topic_build.py`, `topic_edges.py`, `topics_report.py`, `topic_graph.py` (search / around / graph / summarize CLI)
- Labels: `build_labels_db.py`, `book_labels.py` (call-number lookup; retrieval outputs show `[call]` + shelf line)
- Checks: `acceptance/` (topics-p0..p5.sh) and `tests/regression/` (237-check regression suite)

## Crawler — `tools/library-crawler/`

Resumable Primo crawler + incremental refresh pipeline (see `tools/library-crawler/README.md`).

