# topics 子模块 — 图书馆主题图（GraphRAG-lite）· README 草案

> **状态**：P5 文档草案（可直接作为工具链 `README.md` 的「topics 主题图」章节并入）。
> **定位**：本模块是 v2 四层栈之上的**增量层**——所有产物落在 `~/go/lib-catalog-data/topics/`，
> **不改动 v1 既有文件**（`cards.jsonl` / `index/*` / `clusters.json` / `shelves.json` / `subjects.json`）。
> **数据快照**：2026-09-18 18:51（P0 ✅ / P1 ✅ / **P2 ✅ 已跑通并经调参定稿** / **P3 ✅ 已跑通（12 跳覆盖 0.8972，卡在门槛线上）** / P4 ⏳ 未实现）。

**阅读图例（全文沿用，请勿混淆）**

| 标记 | 含义 |
|---|---|
| ✅ | 已实测：数字/文件由本次实际读取或实际运行产出，来源标注在表内 |
| ⏳ | 计划中/未实现：脚本或命令尚不存在 |

> ⚠️ **一条必须先读的结论：12 跳覆盖「达标与否」目前取决于用哪个口径量它**
> · **§3.2 字面口径**（top-20 按**权重**截断）：**0.7744** → 明确 **FAIL**；handoff 写的回退（出度 20→30）实测只到 **0.8553**，**依然 FAIL**。
> · **改截断排序键为 `assoc`**（`共现书数/√(freq_u·freq_v)`，**权重公式一字未改**）：**0.8972（kw 源点）/ 0.9030（全节点源点）** → kw 口径差 **0.28pp** 未过、全节点口径**刚好过线**。
> · **按 §4-P3 原文口径**「簇 = 主簇**或分类**」：同一份主产物 = **0.9797** → **PASS**。
> · 三者都是同一张 `edges.csr.npz`。**结论：门槛卡在采样口径上，不是一个纯粹的图质量问题**（详见 `topics/p2-tuning.md` 与 §6-R1/R11）。
> 其余指标健康：**性能 p50 1.99ms**（门槛 <1s、理想 <300ms ✅）、CSR dtype 三项 OK、无向连通最大分量 **99.94%**、
> 6 跳覆盖 0.8969 ≈ 12 跳 0.8972 → **瓶颈不是跳数**；出度 20→30 仅 +0.6pp。

> 🔄 **本模块仍在快速迭代**：P2 的 `--rank-by` 已定为 **`assoc`**（默认），调参证据落 `topics/p2-tuning.md`。
> **本草案所有 P2/P3 数字为 2026-09-18 18:51 快照**；on-disk `topics/edges.csr.npz` = 18:50 那次运行
> （`--rank-by assoc --max-out 20 --variant auto` → aug、E=99,268、avg 出度 19.138）。

---

## 1. 模块定位

```
v2 四层栈（已完成，只读）
  cards.jsonl 188,512 卡 → index/{tfidf,embeddings} → index/knn_csr.npz（文档图 K=10） → release v1
                                                              │
        topics 增量层（本模块）◄───────────────────────────────┘（复用同一 tokenize / TF-IDF / 400 语义簇）
          nodes.json（5,187 主题） → edges.csr.npz（类型化边，出度≤20） → card_topics.jsonl（证据链）
                                                              │
                                              topic_graph.py：search / around / graph / summarize（≤12 跳加权 BFS）⏳
```

- **节点只收「主题」**：作者、出版社**不入节点**（不做作者网络/出版社网络）——交接文档 §0.1 硬约束。
- **不直接接入 LLM**：社区摘要/查询综合**只留接口存根**（见 §5），默认离线。
- **查询编排跳数上限 12 跳**（交接文档 §0.2 硬约束；文档图上 12 跳同簇覆盖 0.902 ✅）。

---

## 2. 数据 schema

### 2.1 `topics/nodes.json` — 主题节点表 ✅

顶层为 **JSON 数组**（不是对象），元素按 `id` 升序。字段 7 个，全量实测无缺字段 ✅
（来源：`acceptance/topics-p1.sh` 输出 `BAD_SCHEMA=0`，5,187 条全量抽检）。

| 字段 | 类型 | 说明 | 实测统计（本快照） |
|---|---|---|---|
| `id` | int | 节点 id，**连续 0..n-1** ✅ | 0 – 5,186 |
| `term` | str | 归一后的主题词（NFKC + 去空白 + 长度 1–16 + 纯 ASCII 转小写） | **全量唯一** ✅（5,187/5,187） |
| `type` | str | `kw`（主题词）\| `cls`（CLC 类目） | `kw` 4,838 / `cls` 349 ✅ |
| `freq` | int | 有书目证据的卡片数（**非** TF-IDF 权重） | min 1 / p25 17 / median 29 / p75 78 / p90 267 / max 11,534；**freq=0 共 0 条** ✅ |
| `cluster` | int | 主簇 id（400 语义簇之一，取该词频次最高的簇） | 0–399，**396 个不同取值**、**无 -1** ✅ |
| `cls` | str | `cls` 节点 = 自身类目码（`cls==term`）；`kw` 节点 = 该词的主**一级**类目（无则取簇 `top_subjects[0][0]`） | 356 个不同取值（349 个 `cls2` + 37 个一级类目）✅ |
| `sources` | str[] | 来源标记，取值 `"A"`/`"B"`/`"C"`（可组合） | `B` 3,481 / `A+B` 954 / `A` 403 / `C` 349 ✅ |

**示例（`nodes.json` 前 3 条原文）**

```json
[{"id": 0, "term": "经济", "type": "kw", "freq": 3598, "cluster": 362, "cls": "F", "sources": ["A", "B"]},
 {"id": 1, "term": "design", "type": "kw", "freq": 2836, "cluster": 195, "cls": "TP", "sources": ["A", "B"]},
 {"id": 2, "term": "D9", "type": "cls", "freq": 3717, "cluster": 243, "cls": "D9", "sources": ["C"]}]
```

**三源口径（来源：`topics/p1-build-report.json` → `params` + `counts`）✅**

| 源 | 内容 | 实测数字 |
|---|---|---|
| A | `clusters.json` 400 簇 keywords，归一/去重/停用词后 | 原始去重 3,345 → 形态过滤后 2,841（`p1-build.log`）→ 最终 `source_a_kept` **1,518**（剔零频 429 + 剔跨词碎片 894） |
| B | `index/tfidf.npz` 每卡标题内 TF-IDF top-10 token，经 `build_graph.merge_bigrams(max_len=5, min_ratio=0.25)` 链式合并 | 合并后去重 224,511；`df≥5` 21,965 / `df≥8` 13,585 / `df≥10` 10,862；`df≥min_df(12)` 保留 9,044 → 准入 **4,435**；剔除中文 2,822（其中长词包含率≥0.9 的碎片 1,801）、英文质量闸门不过 1,787 |
| C | `cards.jsonl` 的 CLC `cls2` 类目 | 349 |

**节点规模闸门**：`min_nodes=5000` / `max_nodes=20000`；超限按 `freq × 簇内代表性` 截断。本快照 5,187 ∈ [5000, 20000]，`truncated=false` ✅。
**停用词表**：**988** 词（`build_graph.STOP_TOKENS` + 本地 `EXTRA_STOPWORDS` + `ENGLISH_STOP_WORDS` + sklearn 停用词），全表落 `p1-build-report.json.params.stopwords`（登记进 `meta.json` 时省略，仅留 `stopword_count`）。
**抽检**：50 词分层抽检（高/中/低频 17/17/16），判噪声 2 条（`重大`、`业化`）→ **噪声率 0.04** ✅（门槛 <10%）。

### 2.2 `topics/edges.csr.npz` — 类型化边（CSR）✅

**已生成并通过实测核对**（来源：`topic_edges.py` 的 `b5_arrays` 断言 + 本次直接加载 `np.load` 校验；`p2-build-report.json`）。

| 键 | dtype | 形状（实测） | 语义 |
|---|---|---|---|
| `indptr` | **int64** ✅ | `(5188,)` = `(N+1,)` | CSR 行指针。节点 `i` 的**出边区间** = `indices[indptr[i] : indptr[i+1]]`，权重同区间。实测 `indptr[0]=0`、`indptr[-1]=99268`、单调不减 ✅ |
| `indices` | **int32** ✅ | `(99268,)` | 出边目标节点 `id`（取值 `0..N-1`，全部合法、无越界 ✅） |
| `weights` | **float32** ✅ | `(99268,)` | 与 `indices` 一一对应的边权，**已归一到 [0,1]**；实测 min 0.1763 / max **1.0** ✅ |

- **规模**：`N = 5,187`（= `nodes.json` 节点数）；**`E = 99,268` 条有向边** ✅。
- **有向性**：有向图，CSR 只存**出边**。①②（共现/同簇）**双向各落一条**；③ 层级边**单向**。
- **出度**：每节点按 `权重 desc → 共现书数 desc → 目标 id asc` 保留 **top-20**；实测 avg **19.138**、median 20、p90 20、**max 20** ✅；出度 0 的孤立节点 **3** 个。
- **文件**：主产物 `edges.csr.npz`（本次 auto 选中 **`aug`** 口径）；另一口径另存 **`edges.variant-spec.csr.npz`** ✅。

**三类边的权重公式（已落盘实现，来源：`topic_edges.py` docstring + `src` 代码）**

| # | 边型 | 方向 | 权重公式 | 实测 |
|---|---|---|---|---|
| ① | 同书共现（主） | **双向** | `w1 = log1p(min(共现书数, cap)) / log1p(cap)`，`cap=50` | 参与组合的 distinct 对 **330,426**；共现书数 median 2 / mean 5.31 / max **2,052**；封顶饱和对 3,878（**1.17%**） |
| ② | 同簇边（加成） | **双向** | `w2 = 0.3 × log1p(簇内共现数) / log1p(cap)` | 命中对 **9,167**；`--combine sum`（默认）时 `w=min(1, w1+w2)` |
| ③ | 主题 → CLC `cls2` 类目 | **单向** | `w3 = 1.0`（无自环） | 层级边 **4,832** 条；`kw` 无层级证据仅 6 个 ✅ |

**组合方式 `--combine`**：`sum`（默认）→ `w = min(1, w1+w2)`，② 作为同簇**加成**有实际排名影响；
`max` → `w = max(w1,w2)`，**数学上恒等于 w1**（`cnt_sc ≤ cnt` ⟹ `0.3·log1p(cnt_sc) ≤ log1p(cnt)`），② 退化为无效项。
**权重分布实测**：min 0.1763 / median 0.4093 / mean 0.5187 / p90 1.0 / max 1.0；**`w≈1` 占 11.38%**。
**口径细节点**（易踩）：③ 的层级边目标**不是** `nodes.json` 的 `cls` 字段——该字段是一级类目（无对应节点），
故实现为「由卡级证据投票取**众数 `cls2` 类目节点**」（`b4_target_rule`）。
**两种口径 `--cls-in-cooccurrence`**：`spec` = 卡 top-5 **仅 kw** 参与共现对；`aug` = 额外并入卡的 `cls2` 节点
（避免类目节点成为出度 0 的汇点）。`--variant auto` 按 12 跳覆盖自动选择主口径并落盘，另一口径另存。当前落盘（18:50 运行）：

| variant | distinct 对 | 权重落盘 | 12 跳覆盖（kw 源点） | 12 跳覆盖（全节点源点） |
|---|---|---|---|---|
| `spec` | 245,779（kw-kw） | `edges.variant-spec.csr.npz` | 0.8815 | 0.8450 |
| **`aug`（当前选中）** | 330,426 | **`edges.csr.npz`** | **0.8972** | **0.9030** |

> **`--rank-by`（截断排序键，默认 `assoc`）——本次最关键的参数**
> `assoc` = `共现书数 / √(freq_u · freq_v)`（**当前默认**）；`weight` = 照 §3.2 字面按**权重**排序。
> 排序键只决定 top-20 **保留哪 20 条边**，**权重公式完全不变**。实测差距巨大：
>
> | 配置（rank_by / max_out） | 平均出度 | 边数 | 12 跳覆盖（kw 源点） | 12 跳覆盖（全节点源点） | 同簇∪同类目 | 无向闭包 |
> |---|---|---|---|---|---|---|
> | `weight / 20`（§3.2 字面） | 19.138 | 99,268 | **0.7744** | 0.7874 | 0.8429 | 0.9200 |
> | `weight / 30`（handoff 的回退方案） | 27.814 | 144,272 | 0.8553 | 0.8670 | — | — |
> | **`assoc / 20`（当前主产物）** | 19.138 | 99,268 | **0.8972** | **0.9030** | 0.9797 | 0.9200 |
> | `assoc / 30` | 27.814 | 144,272 | 0.9028 | 0.9088 | 0.9845 | 0.9200 |
> | `assoc / 20 + 互惠加成 ×1 / ×3` | 19.138 | 99,268 | 0.8972 | 0.9030 | 0.9797 | 0.9200 |
>
> （表来源：`topics/p2-tuning.md`，400 个随机 kw 源点、seed=42、变体固定 aug。）
> **原因**：按权重排序会让**高频词互相垄断 20 个槽位**，低频节点被单向吸入枢纽后无路可回；
> 换成关联度排序后**平均出度更低**（19.138）却覆盖更高。
> **瓶颈诊断**：6 跳覆盖 0.8969 ≈ 12 跳 0.8972 → **瓶颈不是跳数**；无向闭包 0.9200 → 方向不对称只值 2.3pp；出度 20→30 仅 **+0.6pp**；
> 互惠加成实验**无效**（共现边互惠率已达 0.34）。
> 按 §4-P3 原文口径「簇 = 主簇**或分类**」，同一份主产物覆盖 = **0.9797 ≥ 0.90（PASS）**。

### 2.3 `topics/card_topics.jsonl` — 卡的 top-5 主题证据链 ✅

**已生成**：**188,512 行** ✅（= `cards.jsonl` 卡数），行序与 `cards.jsonl` 对齐。

| 字段 | 类型 | 说明 |
|---|---|---|
| `mms` | str | 书卡主键（如 `"991001047689704181"`） |
| `topics` | int[] | 该卡的 top-5 主题 `id`（按词权降序），指向 `nodes.json` 的 `id`；**`cls` 节点不占 top-5 名额** |

**实测分布（`p2-build-report.json` → `counts.cards_topic_count_hist`）**：
主题数 0 → 22,573 卡；1 → 32,886；2 → 38,925；3 → 34,190；4 → 25,063；5 → 34,875。
即**空主题卡 22,573 张（11.97%）**，含 `cls2` 的卡 179,587 张。
**词权规则**：`score(card, term) = Σ tfidf(card, token)`，`token ⊆ term`（ASCII 主题 = 单词精确命中；含 CJK 主题 = 组成该词的相邻 bigram 之和）；平局按节点 id 升序。
**约束**：本文件**只新增**，`cards.jsonl` 本体**未被改写**（交接文档 §3.3）。

### 2.4 `topics/meta.json` — 多阶段口径登记 ✅

**结构 = 「顶层 P0 遗留键（保持兼容）」+「`stages.<STAGE>` 分段」**，由 `topics_meta.py` 增量维护（读-改-写，`indent=2`、`ensure_ascii=False`）✅

| 键 | 类型 | 说明 |
|---|---|---|
| `stage` | str | **顶层遗留键，必须保持 `"P0"`** —— `acceptance/topics-p0.sh` 断言 `stage == "P0"`，**不得改动** ✅ |
| `baseline` / `generated_at` / `generator` / `data_dir` / `artifacts_dir_actual` | str | 顶层遗留：基线路径、生成时间、生成命令、数据目录 |
| `baseline_sha256` | str | `topics/baseline-p0.txt` 校验和 ✅ |
| `wall_seconds` | num | 基线复现耗时（实测 18.2）✅ |
| `baseline_numbers` | obj | P0 文档图基线全部数字（见 §3）✅ |
| `notes` | str[] | P0 口径备注（含「v1 既有文件全程只读」声明）✅ |
| `supplementary` | obj | `--curve-samples 400` 复跑补充（12 跳覆盖 0.911 / 69s）✅ |
| `stages.P0` | obj | 顶层遗留键的**镜像**（首次运行 `topics_meta.py` 时自动迁移）✅ |
| `stages.P1` | obj | P1 口径：`params` / `counts` / `freq_stats` / `noise_rate`(**0.04**) / `noise_sample` / `noisy_items` / `artifacts` / `report_file` ✅ |
| `stages.P2` | obj | P2 口径：`params`（含 `rank_by=assoc`）/ `counts` / `edge_stats` / `self_test`（`hop12_kw_seeds_mean=0.8972`、`hop12_all_seeds_mean=0.9030`）/ `artifacts` / `report_file`/**`tuning_evidence`**（=`topics/p2-tuning.md`）/**`acceptance_scripts`** ✅ 已登记 |
| `current_stage` / `updated_at` | str | 最近登记阶段 / 时间（当前 **`P2`** / `2026-09-18T18:50:53+0800`）✅ |
| `notes_meta` | str[] | 多阶段结构说明（追加式留痕）✅ |

**登记器用法**

```bash
python3 topics_meta.py --stage P1 --data ~/go/lib-catalog-data --report topics/p1-build-report.json
python3 topics_meta.py --stage P2 --data ~/go/lib-catalog-data --report topics/p2-build-report.json   # ⏳ 待执行
python3 topics_meta.py --stage P1 --data ~/go/lib-catalog-data --dry-run                              # 只打印不写盘
```

---

## 3. 复现命令（可直接复制执行）

> 前置：`cd ~/go/reasonix-scripts/lib-catalog`；依赖 `~/go/pylibs`（脚本自带 `sys.path` 处理）。
> 数据目录以 `--data ~/go/lib-catalog-data` 指定（或环境变量 `LIB_CATALOG_DATA`）。

### P0 · 文档图基线 ✅（实测 17s）

```bash
python3 graph_report.py --data ~/go/lib-catalog-data 2>&1 | tee ~/go/lib-catalog-data/topics/baseline-p0.txt
# 官方基线输出（topics/baseline-p0.txt）
#   节点: 188,512 | 出度: 10 | 边: 1,885,120 | 互链率: 0.423
#   sim: 均 0.739 / 中位 0.738 / P10 0.635 ；簇: 400
#   12 跳: 覆盖均 0.902 / 中位 0.938
#   连通性: 无向分量 3 个；最大 188,488（99.99%）；簇内单一连通分量 397/400
#   语义衰减: 1 跳 0.730 / 2 跳 0.636 / 3 跳 0.584（随机基线 0.408）
```

### P1 · 主题节点构建 ✅（实测 54.3s → 5,187 节点）

```bash
python3 topic_build.py --data ~/go/lib-catalog-data \
        --report topics/p1-build-report.json \
        --sample-out topics/p1-sample50-candidates.txt
# 正式参数即默认值：--top-per-card 10 --min-df 12 --min-df-cjk 15
#                   --en-min-freq 200 --en-min-cls-rep 0.6 --en-min-len 9
#                   --min-nodes 5000 --max-nodes 20000 --seed 42
python3 topics_meta.py --stage P1 --data ~/go/lib-catalog-data --report topics/p1-build-report.json
```

> ⚠️ **口径以 argparse 为准**：`topic_build.py` 的 **docstring 写 `--min-df` 默认 8**，**argparse 实际默认 12**（`--min-df-cjk` 默认 15）。正式基线与 `p1-build-report.json` 均为 `min_df=12`；docstring 待修正。

### P2 · 构边 ✅（实测 13.6–14.2s → 99,268 条边）

```bash
python3 topic_edges.py --data ~/go/lib-catalog-data
# 参数即默认值：--top-per-card 10 --top-k 5 --max-out 20 --cap-count 50
#               --combine sum --cls-in-cooccurrence auto --variant auto
#               --rank-by assoc --seed 42 --coverage-samples 300
# 产出：topics/edges.csr.npz（主口径）、topics/edges.variant-spec.csr.npz（另一口径）、
#       topics/card_topics.jsonl（188,512 行）、topics/p2-build-report.json
python3 topics_meta.py --stage P2 --data ~/go/lib-catalog-data --report topics/p2-build-report.json   # ⏳ 待执行
```

> ⚠️ **`--rank-by` 是本次迭代新增、且已定为默认 `assoc` 的截断排序键**（调参证据见 `topics/p2-tuning.md`）：
> `assoc` 与 `weight`（§3.2 字面口径）选出**不同的 top-20 边集**，覆盖差 **0.7744 → 0.8972**（**权重公式一字未改**）。
> **当前 on-disk `edges.csr.npz` 由 `--rank-by assoc` 运行产出**；要复现 §3.2 字面口径请显式加 `--rank-by weight`。

**冒烟与调参**（P3 未达标时的调参杠杆，交接文档 §4-P3/§6；建议用 `--out` 写到 `topics/_exp/<tag>/` 以免覆盖主产物）：

```bash
python3 topic_edges.py --data ~/go/lib-catalog-data --limit-cards 5000        # 冒烟：仅前 5,000 卡
python3 topic_edges.py --data ~/go/lib-catalog-data --max-out 30              # 出度 20 → 30（当前已顶格 20，最直接杠杆）
python3 topic_edges.py --data ~/go/lib-catalog-data --rank-by weight          # 复现 §3.2 字面口径（当前默认 assoc）
python3 topic_edges.py --data ~/go/lib-catalog-data --cls-in-cooccurrence no  # 强制 spec 口径
python3 topic_edges.py --data ~/go/lib-catalog-data --variant aug             # 强制 aug 口径为主产物
python3 topic_edges.py --data ~/go/lib-catalog-data --coverage-samples 400    # 覆盖自测样本量（注意：读数随样本量变）
python3 topic_edges.py --data ~/go/lib-catalog-data --out topics/_exp/tag-01  # 参数搜索隔离输出目录
```

### P3 · 主题图质量报告 ✅ 脚本已落地并跑通

```bash
python3 topics_report.py --data ~/go/lib-catalog-data                    # 人类可读表（只读，不落盘）
python3 topics_report.py --data ~/go/lib-catalog-data --json             # stdout 输出结构化 JSON
python3 topics_report.py --data ~/go/lib-catalog-data --samples 400 --seed 42   # 覆盖曲线抽样源点数
python3 topics_report.py --mock                                          # 边表未就绪时的内存 mock 冒烟（不落盘）
```

参数：`--edges`（默认 `<out>/edges.csr.npz`）/ `--samples 400` / `--hops 12` / `--seed 42` /
`--source-type kw|all` / `--perf-samples 50` / `--random-baseline` / `--max-outdeg 20` /
`--json` / `--json-out PATH` / `--txt-out PATH`。
**只读保证**：仅在显式给出 `--txt-out` / `--json-out` 时才写出报告文件（本草案未使用这两个参数）。

**本次实测输出摘要（`--samples 400 --seed 42`，2026-09-18 18:51，总耗时 0.8s）**

| 检测项 | 实测 | 判定 |
|---|---|---|
| CSR 规格 | `indptr int64` / `indices int32` / `weights float32` 三项 OK；n=5,187、nnz=99,268 | ✅ |
| 节点 / 边 / 平均出度 | 5,187（kw 4,838 / cls 349）/ 99,268 / **19.14**；出度 min 0 / 中位 20 / p90 20 / **max 20** | ✅ ≤20 |
| 权重 | min 0.176 / 中位 0.409 / 均 0.519 / p90 1.000；`=0` 占 0.00%、`=1` 占 **11.38%** | — |
| **12 跳同簇覆盖（400 随机 kw 源点）** | **均 0.8972 / 中位 0.9286**（逐跳升至饱和，12 跳可达均 **5,042**） | 🔴 **FAIL（差 0.28pp）** |
| 连通性 | 无向分量 **4** 个；最大 5,184（**99.94%**）；单点分量 3 | ✅ 正常 |
| 衰减（`w_hop = w_parent × edge_w × 0.86`） | 1 跳均分 0.4427 / 3 跳 0.2891；**12 跳处已饱和**（平均得分记 `—`） | 🟡 见下注 |
| **性能（12 跳加权 BFS，50 样本）** | **p50 1.99ms / p95 2.49ms / max 2.97ms** | ✅ **PASS**（门槛 <1s，理想 <300ms） |

> ⚠️ **同一张图，换口径就换结论**（三列均为本次快照实测）：
> ① `topics_report.py` kw 源点口径 = **0.8972 → FAIL**；② P2 自测**全节点**源点口径 = **0.9030 → PASS（勉强）**；
> ③ §4-P3 原文「簇 = 主簇**或分类**」口径 = **0.9797 → PASS**。**门槛判定对采样口径高度敏感，须先冻结口径**（见 §6-R11）。

> 衰减口径说明（`topics_report.py` 原文）：`0.86` 是**逐跳因子**，可比量是「有效逐跳因子」= 最优路径平均边权 × 0.86；
> 「平均得分」必然低于纯 `0.86^hop` 理论线（边权均值 0.5148 < 1 会额外压低曲线），故**比理论线应看该列**。

> 📌 与任务书预期的差异已修正：任务书写的 `topics_report.py --data ... --json` **成立**（该脚本已落地且确有 `--json`）；
> 早前「脚本不存在 / `graph_report.py` 无 `--json`」的判断对本快照**已过期**——`graph_report.py` 本身仍无 `--json`，P3 用的是新脚本。

### 验收脚本

```bash
cd ~/go/reasonix-scripts/lib-catalog
bash acceptance/topics-p0.sh 2>&1 | tee ~/go/lib-catalog-data/topics/acceptance-p0.log   # ✅ PASS (pass=8 fail=0)
bash acceptance/topics-p1.sh 2>&1 | tee ~/go/lib-catalog-data/topics/acceptance-p1.log   # ✅ PASS (pass=17 fail=0)
bash acceptance/topics-p2.sh                                                             # ✅ 脚本已就绪（P2 产物完整）
```

| 脚本 | 状态 | 断言 | 实测 |
|---|---|---|---|
| `acceptance/topics-p0.sh` | ✅ | 基线含 12 跳且覆盖数 ∈ [0.882, 0.922]；`meta.json` 合法、顶层 `stage=P0`、`baseline` 指向 `baseline-p0.txt` | **PASS (8/0)**，覆盖 0.902 |
| `acceptance/topics-p1.sh` | ✅ | nodes.json 合法/规模 ∈[5000,20000]/7 字段/id 连续/term 唯一/无 freq=0/type 仅 kw&amp;cls；与构建报告 7 项计数一致；顶层仍 P0 + `stages.P1` 齐备、噪声率 ≤10% | **PASS (17/0)** |
| `acceptance/topics-p2.sh` | ✅ 已就绪 | 边表 CSR/dtype/出度/证据链与 `stages.P2` 一致性（详见脚本头注释） | 待主会话留痕（`topics/acceptance-p2.log` 尚未生成） |
| `acceptance/topics-p3.sh` | ⏳ 待建 | 建议：断言 `topics_report.py` 的 12 跳覆盖与门槛判定、性能 p95 < 1s、CSR dtype。**注意：按 kw 源点口径当前为 0.8972 → 该断言会 FAIL** | — |

> 另有 `topics/acceptance-p3-smoke.log`（18:43）与 `topics/p2-tuning.md`（18:51，调参证据）可作验收附件。

---

## 4. 未来查询 CLI 形态（P4 计划，⏳ 全部未实现）

> 脚本 `topic_graph.py` **尚未存在**。以下为**提案形态**，对齐 v1 `catalog_vector.py` 风格
> （子命令 + `--data` + `--json`；v1 现有子命令：`build/search/kw/hybrid/get/links/cluster/clusters/graph/subjects/shelves/stats/validate`）。

```bash
python3 topic_graph.py search "机器学习 入门"            # 种子命中（精确/子串/TF-IDF 近词扩展）
python3 topic_graph.py around <term> --hops 12          # 加权 BFS（≤12 跳），输出分层邻域
python3 topic_graph.py graph <term> --hops 12 --books   # 邻域 + 证据书（回查 card_topics.jsonl）
python3 topic_graph.py summarize <term>                 # LLM 接口：默认 mock（打印结构化区域）
```

**扩散规则（已由 P3 采用，见 `topics_report.py` 的 `DECAY=0.86`）**：`w_hop = w_parent × edge_w × 0.86`；
每跳 top-20 边、权重阈值 0.05、访问预算 ≤50k 节点。
**输出**：分层列表 `(hop, term, score, path)` + 证据书 top-k；支持 `--json`。
**性能目标**：12 跳单查询 < 1s（目标 < 300ms）；P3 报告已内置单查询计时（`--perf-samples 50`）。
**已知退化路径**：查询词不在 `nodes.json` 时须退化为 TF-IDF 近词扩展（P4 必测项）。

---

## 5. LLM 接口签名约定（存根协议草案）

> ⚠️ **本节全部为提案，待与作者（wormforce）讨论后定稿**。交接文档 §0.3 明确：**不直接接入 LLM**，
> 社区摘要/查询综合**只留接口**。以下任何一条都可以在讨论中被推翻。

### 5.1 函数签名

```python
# topics/topic_llm.py（⏳ 计划中，尚未创建）
def summarize_topic_region(region: dict) -> str:
    """把查询区域（region）渲染为一段人类可读摘要。

    入参 region: 见 5.2 结构（纯数据，无 LLM 依赖）。
    返回: str —— Markdown 纯文本段落（不返回 JSON；结构化数据由 CLI 的 --json 通道给出）。
    约定:
      - 确定性: TOPIC_LLM=mock 时同一 region 必须返回同一字符串（禁随机、禁时间戳）。
      - 不引入外部事实: 只允许使用 region 内的 term/cls/score/证据书字段，
        禁止补充模型自有的领域知识或对书目做推断。
      - 不触网: 除 TOPIC_LLM=<endpoint> 显式指定外，不得发起任何网络请求。
      - 失败回退: 任何异常 → 回退 mock 模板文，stderr 打 warning，退出码不变
        （--strict-llm 时以退出码 3 表示 LLM 失败）。
    """
```

### 5.2 入参 `region` 的结构（提案）

| 字段 | 类型 | 说明 |
|---|---|---|
| `seed` | obj | `{"id": int, "term": str}` —— 查询种子主题（BFS 起点） |
| `hops` | int | 实际扩散跳数（≤12） |
| `decay` | float | 每跳衰减系数（提案 0.86，已为 P3 采用） |
| `layers` | obj[] | 分层邻域，每层 `{"hop": int, "nodes": [{"id","term","score","path": [str]}]}`，按 `score` 降序 |
| `evidence` | obj[] | 证据书 `{"mms": str, "title": str, "topics": [int]}`（回查 `card_topics.jsonl`，默认 top-k） |
| `stats` | obj | `{"visited": int, "edges_scanned": int, "elapsed_ms": int}`（供摘要自述规模） |

### 5.3 环境变量 `TOPIC_LLM`

| 取值 | 行为 | 触网 |
|---|---|---|
| `off` | **纯结构化输出**（直接转储 region，`summarize` 不做文本渲染） | 否 |
| `mock`（**默认**） | 返回确定性模板文（如「种子『机器学习』，12 跳内关联 842 个主题，最强关联：…」） | 否 |
| `<endpoint>` | HTTP POST 到该 endpoint（协议/鉴权/预算待定，见待讨论点） | **是**（唯一允许触网的路径） |

**不触网约束与举证方式**：默认值即 `mock`；`TOPIC_LLM` 未设置时行为与 `mock` 完全一致。
P4 验收要求「`summarize` 默认 mock 可跑且不触网」，建议在**断网/无 DNS** 环境下执行一次作为举证。

### 5.4 待与作者讨论（本节相关）

1. `summarize_topic_region` 的**签名本身**（是否改为 `(region, *, style=...)`、是否返回结构化 `dict` 而非 `str`）；
2. `<endpoint>` 的**协议与鉴权**（OpenAI 兼容 `/v1/chat/completions`？本地模型？密钥来源？）；
3. **隐私边界**：送外部的字段是否只允许 `term`/`cls`/`score`，**禁止**送 `mms`、书名、卡片正文；
4. **调用预算**：单查询 token/费用上限、超时、缓存策略（同 region 结果是否落盘复用）；
5. 失败语义：回退 mock 后**是否**要以非零退出码暴露（提案 `--strict-llm` → exit 3）。

---

## 6. 已知边界与待确认

| # | 事项 | 状态 |
|---|---|---|
| **R1** | 🟡 **P3 硬门槛卡在线上（P4 的放行依据）**：**§3.2 字面口径**（`--rank-by weight`）= **0.7744 FAIL**；handoff 的回退方案（出度 20→30）实测只到 **0.8553，仍 FAIL**；换排序键 `--rank-by assoc`（权重公式未改）= **0.8972（kw 源点）/ 0.9030（全节点源点）**；按 §4-P3 原文「簇 = 主簇**或分类**」= **0.9797 PASS**。**同一份主产物，结论取决于口径 → 需 author 拍板用哪个口径判定放行** | 🟡 **待拍板** |
| **R11** | 🟡 **覆盖口径未冻结（R1 的前置问题）**：同一张 `edges.csr.npz` 的 12 跳覆盖读数依次为 0.7744（§3.2 字面/weight）、0.8972（assoc·kw 源点）、0.9030（assoc·全节点源点）、0.9797（同簇∪同类目）——**跨 20+ 个百分点**。**建议把 `topics_report.py --samples 400 --seed 42`（kw 源点）冻结为验收口径并写进 `acceptance/topics-p3.sh`** | 🟡 **待冻结** |
| R2 | ✅ **已闭环**：`stages.P2` 已登记进 `meta.json`（18:50:53，`current_stage="P2"`，含 `tuning_evidence` / `acceptance_scripts`） | ✅ |
| R3 | `acceptance/topics-p2.sh` **已创建**（18:47）；`acceptance/topics-p3.sh` / `topics-p4.sh` 仍缺 | 🟡 |
| R4 | `topic_graph.py`（P4）与 `topic_llm.py` 存根均**未实现**；§5 接口仅为提案 | ⏳ |
| R5 | `topic_build.py` docstring 的 `--min-df` 默认值（8）与 argparse 实际默认值（**12**）**不一致** | 🟡 待修文档 |
| R6 | 空主题卡 **22,573 张（11.97%）** 无任何 top-5 主题（标题无命中词），对证据链召回的影响待评估 | 🟡 |
| R7 | 主题图无向连通分量 **4 个**，最大分量 5,184（**99.94%**）；另有 3 个出度 0 的孤立节点（P3 复核一致 ✅） | 🟡 正常 |
| R8 | 共现书数封顶 `cap=50`：实测饱和对仅 3,878（1.17%），但共现书数 **max 2,052** 远超封顶，热门词间分辨率被压平——见待讨论清单 | 🟡 |
| R9 | 兼容性举证：交接文档 §4-P5 要求「git 内 diff 证明未触碰 v1 文件」，但工具链目录**不是 git 仓库**（实测） | 🟡 见 `changelog-draft.md` §6 |
| R10 | `kw` 节点 `cls` 字段的一级类目（37 个）与 `cls` 节点的 `cls2` 类目（349 个）共用同一字段名，语义需在 schema 中区分 | 🟡 |

---

*草案结束。所有 ✅ 数字均可在下列来源文件中复核：`topics/nodes.json`、`topics/meta.json`（含 `stages.P0/P1/P2`）、`topics/edges.csr.npz`、`topics/edges.variant-spec.csr.npz`、`topics/card_topics.jsonl`、`topics/p1-build-report.json`、`topics/p2-build-report.json`、`topics/p1-build.log`、`topics/p2-build.log`、**`topics/p2-tuning.md`**、`topics/p1-sample50.txt`、`topics/baseline-p0.txt`、`topics/acceptance-{p0,p1}.log`、`topics/acceptance-p3-smoke.log`、`acceptance/topics-p{0,1,2}.sh`、`topics_report.py` 实跑输出。*
