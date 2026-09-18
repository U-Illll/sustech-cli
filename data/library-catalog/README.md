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
