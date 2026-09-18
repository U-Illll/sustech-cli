# topics 子模块 — 图书馆主题图（GraphRAG-lite）

> **状态**：**P5 定稿 · R2 同步版**（正式版，取代 `docs-draft/README-draft.md` 草案；草案保留为过程稿）。
> **定位**：本模块是 v2 四层栈之上的**增量层**——全部产物落 `~/go/lib-catalog-data/topics/`，
> **不改动 v1 既有文件**（`cards.jsonl` / `index/*` / `clusters.json` / `shelves.json` / `subjects.json`）。
> **数据快照**：2026-09-18 **R2 修复轮后**（`meta.json.updated_at` / `stages.R2-C`）——
> **5,507 节点 / 105,414 边**。历史快照留档（**仅供对账，均不进发行**）：
> R1 后（5,187 / 99,268）→ `edges.csr.pre-r1.npz`；R2-A 前 → `edges.csr.pre-r2.npz`；R2-C 前 → `edges.csr.pre-r2c.npz`。
>
> ⚠️ **数据形态（终审⑦要求；R2-C 后已更新）**：本图是**合成加权图**——边权由「同书共现书数」经 `log1p` 归一而来；
> ①共现与②同簇加成已合并为同一 `weights`（`w = min(1, w1 + w2)`），落盘后不区分来源。
> **R2-C 起新增逐边类型位图 `types`（uint8，见 §2.2）**，可精确还原三类边来源；
> 旧消费者若未升级，仍可用「`w = 1.0` 且目标 `type=cls`」作③层级边的**近似**识别
> ——该判据**不是**等价判据（`types ∈ {5,7}` 的层级边中，凡与同键共现边并列 `w=1.0` 者亦可被此判据命中，反之有共现边权重同为 1.0 的假阳性），仅作兜底。
> 依据：`w1 = log1p(min(共现书数,50))/log1p(50)`、`w2 = 0.3×log1p(簇内共现)/log1p(50)`。
>
> **R1 修复轮（2026-09-18，终审整改）**：① 共现重复计数（每对每卡只计一次）② `--rank-by assoc` 真正作为**主排序键**
> ③ 扩散改「层快照 + 首访定型」（不再超跳）④ 报告表述纠偏（400 采样 vs 全量、非同口径对比、衰减容忍定义）
> ⑤ 验收断言加固（权重独立重算 / 行数对齐 / 门槛硬编码 / 超跳回归 / 护栏）⑥ 相关性闭环 `p4-relevance.md` ⑦ 文档收口。
> 新旧对照与逐条证据见 `ACCEPTANCE-REPORT.md` **§10 R1 修复记录**。
>
> **R2 修复轮（2026-09-18，审计整改；本 README 的**当前终值**即此轮结果）**：
> **R2-A**（数据层）修 F2/F2b `ext_df` 双计数、F1/F1b 截断排序键浮点退化、**D1** 层级边被 top-20 截断吃掉（登记 4,832 / 实存 4,823 → **5,151 / 5,151，零丢失**）；
> **R2-B**（检索层）修 P4 ASCII 大小写归一、`search` 排序引入特异性、证据取样改「同簇闸门 + 一跳近邻覆盖度 + 多卷软去重」；
> **R2-C**（报告/导出层）重跑质量报告、重建导出版（修 AUDIT-EXPORT E1「随包 meta 与随包数据不同源」）、实施边型数组 `types`。
> 节点 5,187 → **5,507**（+320），边 99,268 → **105,414**，六脚本验收 **100 → 147 项全绿**。
> 逐条对照见 `meta.json#stages.R2-A|R2-B|R2-C` 与 `ACCEPTANCE-REPORT.md` **§11 R2 修复记录**。


## 阶段状态一览

| 阶段 | 脚本 | 状态 | 关键口径 | 实测（**R2 终值**） |
|---|---|---|---|---|
| P0 | `graph_report.py`（既有） | ✅ | 文档图基线（只读复现） | 12 跳覆盖 **0.902**，18.2s |
| P1 | `topic_build.py` | ✅ | 三源合一（A 簇关键词 / B 标题 TF-IDF / C CLC `cls2`） | **5,507** 节点（kw 5,158 / cls 349），34.0s |
| P2 | `topic_edges.py` | ✅ | 三类边 + top-20 截断（默认 `--rank-by assoc`） | **105,414** 边，14.3s；`types` uint8 位图 |
| P3 | `topics_report.py` | ✅ | 12 跳覆盖 / 性能 / 连通 / 衰减 | 三口径（400 采样 / kw 源点 / `pool_size=5158`）①**0.9246** ②**0.9927** ③**0.9286**；全节点源点(400) ①0.9202 / ②0.9854；穷举 **5,507** 源点 ①0.9237 / ②0.9867 |
| P4 | `topic_graph.py` | ✅ | `search` / `around` / `graph` / `summarize` + 近词扩展 | 四命令 exit 0，p50 **2.58ms** |
| P5 | 本文档 + 工具链 README v3 记录 + 接口协议 | ✅ | 导出样例**只生成、不发布** | 9 文件 / 4,255,902 B；见 §7、§8 |
| **R2-A/B/C** | 数据 / 检索 / 报告层修复轮 | ✅ | 审计整改（F1/F1b、F2/F2b、D1、E1、边型数组） | 六脚本 **147** 项断言全绿；见 §2.4 与 `ACCEPTANCE-REPORT.md` §11 |

> ✅ = 已实测（数字/文件来自本次实际读取或实际运行，来源标注在表内）。
> ⚠️ **P3 三口径读数的抽样口径必须一并给出**：本表 ①②③ 为「400 采样 / kw 源点」；
> 「全节点源点」列**仍是 400 采样**（`pool_size=5507`），**不是全量统计**；全量口径只有**穷举 5,507 源点**一行。
> 三类抽样**互不可比**，且**均不可与 v1 文档图基线 0.902 作同口径对比**（不同图 + 不同抽样口径）。


## ⚠️ 三条必须先读的结论

1. **P3 硬门槛判定：PASS**。按 §4-P3 原文口径「主题的簇 = 主簇**或分类**」= **② 0.9927 ≥ 0.90 → PASS**
   （R2-C 值；R1 后 0.9912，R1 前 0.9797），P4 已据此放行（裁定文本落 `meta.json.stages.P3.verdict`）。
2. **① 仅主簇 = 0.9246（R2-C；R1 后 0.9188，R1 前 0.8972）是并列的严格观察项**，R1 后已自然过 0.90；
   与 v1 文档图基线 0.902 **属不同图 + 不同抽样口径，非同口径对比**（v1 读数是 188,512 节点文档图、
   100 簇抽样；此处是 5,507 节点主题图、400 采样），**未被口径改写、如实并列报告**，不作门槛。
   **不调 P2 去救 ①**：出度 20→30 会破「平均出度 ≤20」规格，且实测收益仅 +0.6pp（已证伪，见 §8-R1）。
3. **同一张 `edges.csr.npz`，读数取决于口径**（R1 前同图跨口径 0.7744 / 0.8972 / 0.9030 / 0.9797 跨 20+ 个百分点）——
   报告必须同时给出**三口径 + 抽样口径 + 源点池规模**，禁止只报一个（见 §3.4、§8-R11）。


---

## 1. 模块定位

```
v2 四层栈（已完成，全程只读）
  cards.jsonl 188,512 卡 → index/{tfidf,embeddings} → index/knn_csr.npz（文档图 K=10） → release v1
                                                              │
        topics 增量层（本模块）◄───────────────────────────────┘（复用同一 tokenize / TF-IDF / 400 语义簇）
          nodes.json（5,507 主题） → edges.csr.npz（类型化边 + types 位图，出度≤20） → card_topics.jsonl（证据链）
                                                              │
                                              topic_graph.py：search / around / graph / summarize（≤12 跳加权 BFS）✅
```

- **节点只收「主题」**：作者、出版社**不入节点**（不做作者网络/出版社网络）——交接文档 §0.1 硬约束。
- **不直接接入 LLM**：社区摘要/查询综合**只留接口存根**（见 §6），默认离线（`TOPIC_LLM` 未设置 = `off`）。
- **查询编排跳数上限 12 跳**（交接文档 §0.2 硬约束；文档图上 12 跳同簇覆盖 0.902 ✅）。

---

## 2. 数据 schema

### 2.1 `topics/nodes.json` — 主题节点表 ✅

顶层为 **JSON 数组**（不是对象），元素按 `id` 升序（`indent=2`，可读）。字段 7 个，全量实测无缺字段 ✅
（来源：`acceptance/topics-p1.sh` 输出 `BAD_SCHEMA=0`，**5,507 条**全量抽检；本次以脚本复算一致）。

| 字段 | 类型 | 说明 | 实测统计（**R2 终值**） |
|---|---|---|---|
| `id` | int | 节点 id，**连续 0..n-1** ✅ | 0 – **5,506** |
| `term` | str | 归一后的主题词（NFKC + 去空白 + 长度 1–16 + 纯 ASCII 转小写） | **全量唯一** ✅（**5,507/5,507**） |
| `type` | str | `kw`（主题词）\| `cls`（CLC 类目） | `kw` **5,158** / `cls` **349** ✅ |
| `freq` | int | 有书目证据的卡片数（**非** TF-IDF 权重） | min 1 / p25 17 / median 29 / p75 76 / p90 256 / max **11,534**；**freq=0 共 0 条** ✅ |
| `cluster` | int | 主簇 id（400 语义簇之一，取该词频次最高的簇） | 0–399，**397 个不同取值**、**无 -1** ✅ |
| `cls` | str | `cls` 节点 = 自身类目码；`kw` 节点 = 该词的主**一级**类目（无则取簇 `top_subjects[0][0]`） | **356** 个不同取值（349 个 `cls2` + 37 个一级类目）✅ |
| `sources` | str[] | 来源标记，取值 `"A"`/`"B"`/`"C"`（可组合） | `B` **3,672** / `A+B` **1,010** / `A` **476** / `C` **349** ✅ |

**示例（`nodes.json` 前 3 条语义，缩进为 `indent=2`）**

```json
[{"id": 0, "term": "经济", "type": "kw", "freq": 3598, "cluster": 362, "cls": "F", "sources": ["A", "B"]},
 {"id": 1, "term": "design", "type": "kw", "freq": 2836, "cluster": 195, "cls": "TP", "sources": ["A", "B"]},
 {"id": 2, "term": "D9", "type": "cls", "freq": 3717, "cluster": 243, "cls": "D9", "sources": ["C"]}]
```

**三源口径（来源：`meta.json.stages.P1.params` / `.counts`，R2-A 重建后）✅**

| 源 | 内容 | 实测数字（**R2 终值**；括号内为 R1 后旧值） |
|---|---|---|
| **A** | `clusters.json` 400 簇 keywords，归一/去重/停用词后 | 原始去重 **3,345** → 最终 `source_a_kept` **1,647**（R1 后 1,518）（剔零频 **429** + 剔跨词碎片 **765**，R1 后 894） |
| **B** | `index/tfidf.npz` 每卡标题内 TF-IDF top-10 token，经 `build_graph.merge_bigrams(max_len=5, min_ratio=0.25)` 链式合并 | 合并后去重 **224,511**；`df≥5` 21,965 / `df≥8` 13,585 / `df≥10` 10,862；`df≥min_df(12)` 保留 **9,044** → 准入 **4,682**（R1 后 4,435）；剔除中文 **2,575**（其中长词包含率≥0.9 的碎片 **1,563**、`max_df` **464**）、英文质量闸门不过 **1,787** |
| **C** | `cards.jsonl` 的 CLC `cls2` 类目 | **349** |

> **R2-A 修复的可核验证据（F2/F2b）**：`ext_df` 双计数修复后，卡片级包含率上界回到 1.0 ——
> `a_containment_ratio_max = 1.0`、`a_terms_ratio_gt1 = 0`（修复前为 `2.0` / `580`），
> 129 个被误判为「跨词碎片」的 A 源词回归（`source_a_dropped_embedded` 894 → 765）。

**节点规模闸门**：`min_nodes=5000` / `max_nodes=20000`；超限按 `freq × 簇内代表性` 截断。本快照 **5,507** ∈ [5000, 20000]，`truncated=false` ✅。
**截断排序键（R2-A F1/F1b）**：`_score` 已改为 `freq × rep` 的**精确整数值**（≡ `max_cc` = 主导簇卡数）；
修复前按 IEEE754 乘除链计算，与 `max_cc` 可差 1 ulp → 184 个节点 `score ≠ max_cc`、62 处相邻 `(-freq)` 次级键违例。现 `order_equals_sort_maxcc_freq_term = true`。

**停用词表**：**988** 词（`build_graph.STOP_TOKENS` + 本地 `EXTRA_STOPWORDS` + `ENGLISH_STOP_WORDS` + sklearn 停用词），
全表落 `p1-build-report.json.params.stopwords`（`meta.json` 登记为 `stopword_count=988`，不重复存全表）。
**抽检**：50 词分层抽检（高/中/低频），判噪声 2 条（`重大`、`业化`）→ **噪声率 0.04** ✅（门槛 <10%）。
**归一规则**：NFKC + 去空白 + 长度 1–16 + ASCII 小写 + 停用词表；B-only CJK 需在 A 词表或学科词表内，否则剔除。

### 2.2 `topics/edges.csr.npz` — 类型化边（CSR）✅

`np.load` 可直接读取（来源：本次直接加载校验 + `acceptance/topics-p2.sh` 日志）。

| 键 | dtype | 形状（实测，**R2 终值**） | 语义 |
|---|---|---|---|
| `indptr` | **int64** ✅ | `(5508,)` = `(N+1,)` | CSR 行指针。节点 `i` 的**出边区间** = `indices[indptr[i] : indptr[i+1]]`，权重同区间。实测 `indptr[0]=0`、`indptr[-1]=105414`、单调不减 ✅ |
| `indices` | **int32** ✅ | `(105414,)` | 出边目标节点 `id`（实测取值 min 0 / max **5,506**，全部 ∈ [0, N) ✅） |
| `weights` | **float32** ✅ | `(105414,)` | 与 `indices` 一一对应的边权，**已归一到 [0,1]**；实测 min **0.1763** / median 0.2292 / mean 0.3656 / max **1.0** ✅ |
| `types` | **uint8** ✅ | `(105414,)` | **R2-C 新增**：逐边类型位图，与 `indices`/`weights` **行序严格对齐**。见下方「边型位图」 |

**边型位图 `types`（R2-C 实施，方案 a；来源：`meta.json.stages['R2-C'].edge_types` + `audit/r2c/verify_types_r2c.py`）**

| bit | 值 | 含义 |
|---|---|---|
| 0 | `1` | ① 卡级共现（**该位恒置位**，全部边皆有共现证据） |
| 1 | `2` | ② 同簇加成（`c_sc > 0`） |
| 2 | `4` | ③ 层级边（主题 → 众数 `cls2` 类目） |

- **合法值域** `{1, 3, 5, 7}`（去重时同键按 `bitwise_or` 归并）；实测直方图 **`1`×89,643 / `3`×10,620 / `5`×4,358 / `7`×793**。
- ③ 层级边总数 = `types & 4` 的边数 = 4,358 + 793 = **5,151**，与 `meta.json.stages.P2.counts.hierarchical_edges` **精确相符** ✅
  （D1 修复后**零丢失**；修复前登记 4,832 / 实存 4,823）。
- **多重类型边 15,771** 条（`types ∈ {3,7}`）——即「①+②」或「①+②+③」叠加，**旧版仅凭权重无法拆分**，此即位图的增量价值。
- 导出版同步新增 `edges_types.u8.bin`（见 §7）。**向后兼容**：旧消费者只读 `indptr`/`indices`/`weights` 三键即可，行为不变。

- **规模**：`N = 5,507`（= `nodes.json` 节点数）；**`E = 105,414` 条有向边** ✅。
- **有向性**：有向图，CSR 只存**出边**。①②（共现/同簇）**双向各落一条**；③ 层级边**单向**。
- **出度**：每节点按 `排序键 desc → 权重 desc → 目标 id asc` 保留 **top-20**；实测 avg **19.142**、
  median 20、p90 20、**max 20** ✅；出度 0 的孤立节点 **3** 个。
- **权重分布**：min 0.1763 / median 0.2292 / mean 0.3656 / p90 0.8734 / max 1.0；`w≈1` 计 **8,487** 条（**8.05%**）。
- **文件**：主产物 `edges.csr.npz`（`--variant auto` 选中 **`aug`** 口径）；
  另一口径另存 `edges.variant-spec.csr.npz`（`spec`：仅 kw 参与共现，**研究记录，不进发行**）。

**三类边的权重公式（已落盘实现，来源：`topic_edges.py` docstring + 代码 + `meta.json.stages.P2.params`）**

| # | 边型 | 方向 | 权重公式 | 实测（**R2 终值**） |
|---|---|---|---|---|
| ① | 同书共现（主） | **双向** | `w1 = log1p(min(共现书数, cap)) / log1p(cap)`，`cap=50` | distinct 对 **349,680**；共现书数 median 1 / mean 3.309 / max **1,221**；封顶饱和对 **2,302**（**0.66%**）；单例对占比 0.6268 |
| ② | 同簇边（加成） | **双向** | `w2 = 0.3 × log1p(簇内共现数) / log1p(cap)` | 命中对 **10,102**；`--combine sum`（默认）时 `w = min(1, w1+w2)` |
| ③ | 主题 → CLC `cls2` 类目 | **单向** | `w3 = 1.0`（无自环） | 层级边 **5,151** 条（登记 = 实存 ✅）；`kw` 无层级证据仅 **7** 个 ✅ |


**组合方式 `--combine`**：`sum`（默认）→ `w = min(1, w1+w2)`，② 作为同簇**加成**有实际排名影响；
`max` → `w = max(w1,w2)`，**数学上恒等于 w1**（`cnt_sc ≤ cnt` ⟹ `0.3·log1p(cnt_sc) ≤ log1p(cnt)`），② 退化为无效项。
**归一化**：三类公式均已用 `log1p(cap)` 归一到 [0,1]，最终 clamp ≤ 1.0。
**口径细节点**（易踩）：③ 的层级边目标**不是** `nodes.json` 的 `cls` 字段——该字段是一级类目（**无对应节点**），
故实现为「由卡级证据投票取**众数 `cls2` 类目节点**」（`params.b4_target_rule`）。

**两种口径 `--cls-in-cooccurrence`**：`spec` = 卡 top-5 **仅 kw** 参与共现对；`aug` = 额外并入卡的 `cls2` 节点
（避免类目节点成为出度 0 的汇点）。`--variant auto` 按 12 跳覆盖自动选择主口径并落盘，另一口径另存。
当前落盘（`--rank-by assoc --max-out 20 --variant auto`，**R2 终值**）：

| variant | distinct 对 | 权重落盘 | 12 跳覆盖（kw 源点，400 采样） | 12 跳覆盖（全节点源点，**仍是 400 采样**） |
|---|---|---|---|---|
| `spec` | 261,376（kw-kw） | `edges.variant-spec.csr.npz`（98,346 边） | 0.8815 ※ | 0.8450 ※ |
| **`aug`（当前选中）** | 349,680 | **`edges.csr.npz`**（105,414 边） | **0.9246**（R2-C；R1 后 0.9188） | **0.9202**（R2-C；R1 后 0.9218） |

> ※ `spec` 行的两个覆盖值**未随 R2-C 重跑**（R2-C 只重跑了主口径 `aug`），故仍为 R1 前口径的旧读数，**仅供量级参考，不得当作当前值引用**。

> **`--rank-by`（截断排序键，默认 `assoc`）——本模块最关键的参数**
> `assoc` = `共现书数 / √(freq_u · freq_v)`（**当前默认**，权重公式一字未改）；`weight` = 照 §3.2 字面按**权重**排序。
> 排序键只决定 top-20 **保留哪 20 条边**。下表为**调参期实测**（来源：`topics/p2-tuning.md` / `p2-tuning.json`，
> 400 个随机 kw 源点、seed=42、变体固定 aug）——⚠️ **该矩阵是 R1 前、5,187 节点口径下的历史证据，仅用于支撑「选 `assoc` 而非 `weight`」这一决策**；
> 各格数字**不得当作当前读数**（当前终值见上表与 §3.4）：
>
> | 配置（rank_by / max_out） | 平均出度 | 边数 | 12 跳（kw 源点） | 12 跳（全节点源点） | 同簇∪同类目 | 无向闭包 |
> |---|---|---|---|---|---|---|
> | `weight / 20`（§3.2 字面） | 19.138 | 99,268 | 0.7744 | 0.7874 | 0.8429 | 0.9200 |
> | `weight / 30`（handoff 回退方案） | 27.814 | 144,272 | 0.8553 | 0.8670 | — | — |
> | **`assoc / 20`（已选为主口径）** | 19.138 | 99,268 | **0.8972** | **0.9030** | **0.9797** | 0.9200 |
> | `assoc / 30` | 27.814 | 144,272 | 0.9028 | 0.9088 | 0.9845 | 0.9200 |
> | `assoc / 20 + 互惠加成 ×1 / ×3` | 19.138 | 99,268 | 0.8972 | 0.9030 | 0.9797 | 0.9200 |
>
> **根因**：按权重排序会让**高频词互相垄断 20 个槽位**，低频节点被单向吸入枢纽后无路可回；
> 换关联度排序后**平均出度更低**（19.138）却覆盖更高。
> **瓶颈诊断**（同为 R1 前口径）：6 跳覆盖 0.8969 ≈ 12 跳 0.8972 → **瓶颈不是跳数**；无向闭包 0.9200 → 方向不对称只值 2.3pp；
> 出度 20→30 仅 **+0.6pp**；互惠加成实验**无效**（共现边互惠率已达 0.34）。


### 2.3 `topics/card_topics.jsonl` — 卡的 top-5 主题证据链 ✅

**188,512 行** ✅（= `cards.jsonl` 卡数），行序与 `cards.jsonl` 对齐（第 i 行 ↔ 第 i 行）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `mms` | str | 书卡主键（如 `"991001047689704181"`） |
| `topics` | int[] | 该卡的 top-5 主题 `id`（按词权降序），指向 `nodes.json` 的 `id`；**`cls` 节点不占 top-5 名额** |

**实测分布（`meta.json.stages.P2.counts.cards_topic_count_hist`，`acceptance/topics-p2.sh` 复核；R2 终值）**：

| 主题数 | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| 卡数 | **21,607** | **31,456** | **37,907** | **34,090** | **25,595** | **37,857** |

即**空主题卡 21,607 张（11.46%）**；含 `cls2` 的卡 **179,587** 张；主题-卡链接总数 **501,205** 条
（= Σ 各行 `len(topics)`，见导出版清单 `export-sample/v1/topics/manifest.topics.json`）。
（R1 后旧值：空卡 22,573 / 链接 487,933 —— 节点 5,187→5,507 后，可被 top-5 命中的卡增多。）
**词权规则**：`score(card, term) = Σ tfidf(card, token)`，`token ⊆ term`（ASCII 精确 / CJK 相邻 bigram 求和）；平局按节点 id 升序。
**约束**：本文件**只新增**，`cards.jsonl` 本体**未被改写**。

### 2.4 `topics/meta.json` — 多阶段口径登记 ✅

**结构 = 「顶层 P0 遗留键（保持兼容）」+「`stages.<STAGE>` 分段」**，由 `topics_meta.py`（`stages.P0`–`P4`）与
各修复轮的专项登记脚本（`stages['R2-*']` / `stages.P5`）增量维护（读-改-写、`ensure_ascii=False`；
⚠️ **缩进不统一**：`topics_meta.py` 写 `indent=2`，R2 各轮与 R2-D 的专项脚本写 **`indent=1`** —— 现文件为 **`indent=1`**，见 §8-R17）。
**当前 `current_stage="P5"`**（`updated_at` 见 `meta.json`，R2-D 同步时点）✅

**顶层键**

| 键 | 类型 | 说明 |
|---|---|---|
| `stage` | str | **顶层遗留键，必须保持 `"P0"`** —— `acceptance/topics-p0.sh` 断言 `stage == "P0"`，**不得改动** ✅ |
| `baseline` | str | `topics/baseline-p0.txt` |
| `generated_at` / `generator` | str | P0 基线生成时间 / 命令 |
| `data_dir` / `artifacts_dir_actual` | str | 数据目录 / 产物目录（均为 `/home/wzh/go/lib-catalog-data[/topics]`） |
| `baseline_sha256` | str | `baseline-p0.txt` 校验和 ✅ |
| `wall_seconds` | num | 基线复现耗时（实测 **18.2**）✅ |
| `baseline_numbers` | obj | P0 文档图基线全部数字（见 §3.1）✅ |
| `notes` | str[] | P0 口径备注（含「v1 既有文件全程只读」声明）✅ |
| `supplementary` | obj | `--curve-samples 400` 复跑补充（12 跳覆盖 **0.911** / **69s**）✅ |
| `current_stage` / `updated_at` | str | 最近登记阶段/时间（**当前 `P5`**）✅ |
| `notes_meta` | str[] | 多阶段结构说明（**R2-D 起由 8 条重复模板收敛为「1 条结构规范 + 1 条阶段沿革」**）✅ |

> ⚠️ **顶层 `stage` 与 `current_stage` 的双轨语义（必读）**：`stage` 是 **P0 遗留键**，为兼容
> `topics-p{0..5}.sh` 内硬编码的 `stage == "P0"` 断言而**永久冻结**，它**不代表产物当前阶段**。
> 判断真实阶段**一律读 `current_stage`**（现为 `P5`），或直接以 `stages.<STAGE>` 为准。
> 风险：任何只读 `meta["stage"]` 的消费者会把已到 R2 轮的产物误判为 **P0**。
> **R3 待办**：将各验收脚本的断言改指 `stages.P0.stage`（该键已是顶层镜像、语义等价），以解除该冻结。

**`stages.<STAGE>` 分段键**

| 段 | 主要键 | 说明 |
|---|---|---|
| `stages.P0` | `stage` / `baseline` / `baseline_sha256` / `baseline_numbers` / `data_dir` / `artifacts_dir_actual` / `generated_at` / `generator` / `wall_seconds` / `notes` / `supplementary` | 顶层遗留键的**镜像**（首次运行 `topics_meta.py` 时自动迁移；与顶层 11 键**逐字段相等** ✅） |
| `stages.P1` | `generator` / `seconds`(**34.0**) / `params` / `counts` / `freq_stats` / `noise_rate`(**0.04**) / `noise_sample` / `noisy_items` / `artifacts` / `report_file` / **`r2a_refresh`** | P1 口径登记（**已按 R2-A 重建产物刷新**）✅ |
| `stages.P2` | `params`（含 `rank_by=assoc`、`variant=aug`、`b1`–`b5` 公式串）/ `counts` / `edge_stats` / `self_test`（**`hop12_kw_seeds_mean=0.9246`**、**`hop12_all_seeds_mean=0.9257`**）/ `artifacts` / `report_file` / **`tuning_evidence`**（=`topics/p2-tuning.md`）/ **`p2-tuning`** / **`acceptance_scripts`** / **`r1_fix`** / **`r2a_refresh`** | P2 口径登记（含调参证据指针；`p2-tuning` / `tuning_evidence` / `r1_fix` 为 **pre-r2 历史留痕，未重算**）✅ |
| `stages.P3` | `config` / `definitions`（口径定义原文）/ `coverage`（三口径 `mean`/`median`/`pass`/`role` + `denominators` 分母定义）/ `performance` / `connectivity` / `decay` / `artifacts` / `report_file` / **`verdict`**（253 字裁定原文） / **`caliber_freeze`** / **`r2c_rerun_note`** | P3 口径**终裁**（**数值已按 R2-C 重跑刷新**；`pass` 与硬门槛 0.90 逐项自洽）✅ |
| `stages.P4` | `commands` / `diffusion` / `search_expansion` / `guards` / `stub` / `acceptance` / `artifacts` / **`r1_1_fix`** | P4 口径登记（含近词扩展与护栏）✅ |
| **`stages.P5`** | `scope` / `acceptance`（`topics-p5.sh` 28 断言）/ `deliverables`（docs / drafts / export-sample）/ `export`（件数 / 字节数 / 内外层 manifest 指针 / 同源校验）/ `final_values`（**终值快照**）/ `artifacts` / `interface_proposal` / **`r2d_sync`** | **交付与发行决策**：文档定稿 + 导出版（**只生成不发布**）+ 验收脚本固化 ✅ **（R2-D 补登）** |
| **`stages['R2-A']`** | `scope` / `source_audits` / `verification_script` / `fixes`（F1/F1b、F2/F2b、D1 逐条 before→after）/ `before_after` / `downstream_impact` / `backups` / `open_issues` / `artifacts` | R2 **数据层**修复与重建（节点 5,187→5,507）✅ |
| **`stages['R2-B']`** | `tool_md5` / `backup` / `data_generation` / `fixes`（大小写归一 / `search` 排序 / 证据取样）/ `regression` / `relevance_rerun`（10 查询逐条）/ `audit_cross_ref` | R2 **检索层**（P4）修复 ✅ |
| **`stages['R2-C']`** | `scope` / `data_snapshot`（含 3 项 sha256）/ `report_rerun` / `before_after` / `export_rebuild`（E1/E2/E5/E8/E10）/ `edge_types`（位图定义 + 直方图）/ `edge_types_verification` / `artifacts` / **`not_done`** | R2 **报告重跑 / 导出重建 / 边型数组** ✅ |

**登记器用法**

```bash
cd ~/go/reasonix-scripts/lib-catalog
python3 topics_meta.py --stage P1 --data ~/go/lib-catalog-data --report topics/p1-build-report.json
python3 topics_meta.py --stage P2 --data ~/go/lib-catalog-data --report topics/p2-build-report.json
python3 topics_meta.py --stage P3 --data ~/go/lib-catalog-data --report topics/topics-report.json \
        --extra '{"verdict":"<P3 口径裁定文本>"}'          # 裁定文本经 --extra 注入 stages.P3.verdict
python3 topics_meta.py --stage P4 --data ~/go/lib-catalog-data   # P4 无需 report 文件（口径内建）
python3 topics_meta.py --stage P1 --data ~/go/lib-catalog-data --dry-run   # 只打印不写盘
```

> 设计约束：登记器**不动顶层 `stage`**（保持 `"P0"` 以兼容旧验收脚本），只增量维护
> `stages.<STAGE>` / `current_stage` / `updated_at` / `notes_meta`。`--stage` 可选值：`P0|P1|P2|P3|P4`。
> **各阶段的 report 来源**：P0 = 镜像顶层既有键（首次运行自动迁移）；P1/P2/P3 = 对应构建报告 JSON
> （缺省路径 `<data>/topics/{p1-build-report,p2-build-report,topics-report}.json`，不存在则报错退出）；
> **P4 = 无需 report 文件**（命令面/扩散口径/护栏/存根/近词扩展说明内建于登记器）。
> `--extra` / `--extra-file` 可追加自定义键（JSON 字符串 / JSON 文件，非 dict 载荷以文件名挂载）。
>
> ⚠️ **`P5` 与 `R2-*` 段不在 `topics_meta.py` 的 `--stage` 可选值内**：它们由各轮的专项登记脚本写入
> （`stages['R2-C']` ← `topics/audit/r2c/update_meta_r2c.py`；`stages.P5` ← `topics/audit/meta/update_meta_p5.py`）。
> **R3 待办**：把 `topics_meta.py` 的 `choices` 扩到 `P5|R2-*`（或改为不限定阶段名的通用登记器），
> 以免后续轮次继续旁路登记器。

---

## 3. 复现命令（可直接复制执行）

> 前置：`cd ~/go/reasonix-scripts/lib-catalog`；依赖 `~/go/pylibs`（numpy/scipy/sklearn；脚本自带 `sys.path` 处理）。
> 数据目录以 `--data ~/go/lib-catalog-data` 指定（或环境变量 `LIB_CATALOG_DATA`）。**全程无需网络。**

### 3.1 P0 · 文档图基线 ✅（实测 18.2s）

```bash
python3 graph_report.py --data ~/go/lib-catalog-data 2>&1 | tee ~/go/lib-catalog-data/topics/baseline-p0.txt
# 官方基线输出（topics/baseline-p0.txt）
#   节点: 188,512 | 出度: 10 | 边: 1,885,120 | 互链率: 0.423
#   sim: 均 0.739 / 中位 0.738 / P10 0.635 ；簇: 400
#   12 跳: 覆盖均 0.902 / 中位 0.938
#   连通性: 无向分量 3 个；最大 188,488（99.99%）；簇内单一连通分量 397/400
#   语义衰减: 1 跳 0.730 / 2 跳 0.636 / 3 跳 0.584（随机基线 0.408）
# 补充：--curve-samples 400 复跑 → 12 跳覆盖 0.911（69s），仍在 90.2%±2% 带内
```

### 3.2 P1 · 主题节点构建 ✅（实测 **34.0s → 5,507 节点**；R1 后为 54.3s → 5,187）

```bash
python3 topic_build.py --data ~/go/lib-catalog-data \
        --report topics/p1-build-report.json \
        --sample-out topics/p1-sample50-candidates.txt
# 正式参数即默认值：--top-per-card 10 --min-df 12 --min-df-cjk 15
#                   --en-min-freq 200 --en-min-cls-rep 0.6 --en-min-len 9
#                   --min-nodes 5000 --max-nodes 20000 --seed 42
python3 topics_meta.py --stage P1 --data ~/go/lib-catalog-data --report topics/p1-build-report.json
```

> ✅ **R2-D 已修正**：`topic_build.py` docstring 原写 `--min-df` 默认 **8**，与 argparse 实际默认 **12** 不一致；
> 现已把 docstring 改为 **12**，口径以 argparse 为准的告警解除（`--min-df-cjk` 默认 15 未变）。
> 正式基线与 `p1-build-report.json` 均为 `min_df=12`（见 §8-R5，状态已由 🟡 转 ✅）。

### 3.3 P2 · 构边 ✅（实测 **14.3s → 105,414 条边**；R1 后为 14.0s → 99,268）

```bash
python3 topic_edges.py --data ~/go/lib-catalog-data
# 参数即默认值：--top-per-card 10 --top-k 5 --max-out 20 --cap-count 50
#               --combine sum --cls-in-cooccurrence auto --variant auto
#               --rank-by assoc --seed 42 --coverage-samples 300
# 产出：topics/edges.csr.npz（主口径）、topics/edges.variant-spec.csr.npz（另一口径）、
#       topics/card_topics.jsonl（188,512 行）、topics/p2-build-report.json
python3 topics_meta.py --stage P2 --data ~/go/lib-catalog-data --report topics/p2-build-report.json
```

> ⚠️ **`--rank-by` 默认 `assoc`**（关联度截断排序键，权重公式未改）。**当前 on-disk `edges.csr.npz`
> 由 `--rank-by assoc` 运行产出**；要复现 **§3.2 字面口径**（top-20 按权重截断）请显式加 **`--rank-by weight`**
> （覆盖会掉到 0.7744，见 §2.2 矩阵）。

**冒烟与调参**（建议用 `--out` 写到 `topics/_exp/<tag>/` 以免覆盖主产物）：

```bash
python3 topic_edges.py --data ~/go/lib-catalog-data --limit-cards 5000        # 冒烟：仅前 5,000 卡
python3 topic_edges.py --data ~/go/lib-catalog-data --rank-by weight          # 复现 §3.2 字面口径
python3 topic_edges.py --data ~/go/lib-catalog-data --max-out 30              # 出度 20 → 30（弱杠杆，+0.6pp）
python3 topic_edges.py --data ~/go/lib-catalog-data --cls-in-cooccurrence no  # 强制 spec 口径
python3 topic_edges.py --data ~/go/lib-catalog-data --variant aug             # 强制 aug 口径为主产物
python3 topic_edges.py --data ~/go/lib-catalog-data --coverage-samples 400    # 覆盖自测样本量（读数随样本量变）
python3 topic_edges.py --data ~/go/lib-catalog-data --out topics/_exp/tag-01  # 参数搜索隔离输出目录
```

### 3.4 P3 · 主题图质量报告 ✅

```bash
python3 topics_report.py --data ~/go/lib-catalog-data --samples 400 --hops 12 --seed 42 \
        --json-out ~/go/lib-catalog-data/topics/topics-report.json \
        --txt-out  ~/go/lib-catalog-data/topics/topics-report.txt
python3 topics_meta.py --stage P3 --data ~/go/lib-catalog-data --report topics/topics-report.json
```

参数：`--edges`（默认 `<out>/edges.csr.npz`）/ `--out` / **`--samples 400`** / **`--hops 12`** / **`--seed 42`** /
`--source-type kw|all`（默认 `kw`）/ `--perf-samples 50` / `--random-baseline` / `--max-outdeg 20` /
`--json` / `--json-out PATH` / `--txt-out PATH` / `--mock`。
**只读保证**：仅在显式给出 `--txt-out` / `--json-out` 时才写出报告文件。

**本次实测摘要（`--samples 400 --hops 12 --seed 42`，**R2-C 重跑**，总耗时 5.63s；R1 后为 7.5s）**

| 检测项 | 实测（**R2 终值**） | 判定 |
|---|---|---|
| CSR 规格 | `indptr int64` / `indices int32` / `weights float32` 三项 OK；**另有 `types uint8`**；n=**5,507**、nnz=**105,414** | ✅ |
| 节点 / 边 / 平均出度 | **5,507**（kw **5,158** / cls 349）/ **105,414** / **19.14**；出度 min 0 / 中位 20 / p90 20 / **max 20** | ✅ ≤20 |
| 权重 | min 0.176 / 中位 **0.229** / 均 **0.366** / p90 0.873；`=0` 占 0.00%、`=1` 占 **8.05%**（**8,487** 条） | — |
| **12 跳同簇覆盖 · ① 仅主簇** | R1 前 0.8972 / R1 后 0.9188 → **R2-C 0.9246 / 0.9474** | 🟢 **严格观察项（已过线）** |
| **12 跳覆盖 · ② 主簇∪类目** | R1 前 0.9797 / R1 后 0.9912 → **R2-C 0.9927 / 0.9966** | ✅ **硬门槛 PASS**（≥0.90） |
| **12 跳覆盖 · ③ 无向闭包** | R1 后 0.9200 → **R2-C 0.9286 / 0.9474** | ✅ 方向性诊断列 |
| 连通性 | 无向分量 **4** 个；最大 **5,504**（**99.9455%**）；单点分量 3 | ✅ 正常 |
| 12 跳可达 | 均 **5,480** / 中位 5,480 节点（第 7 跳起饱和） | ✅ |
| 衰减（`w_hop = w_parent × edge_w × 0.86`） | 1 跳均分 **0.3093** / 3 跳 **0.0751**；**第 7 跳起饱和** | 🟡 见下注 |
| **性能（12 跳加权 BFS，50 样本）** | **p50 2.580ms / p95 3.740ms / max 5.94ms** | ✅ **PASS**（门槛 <1s，理想 <300ms） |

> ⚠️ **同一张图，换口径就换结论**（下列三列均为 **R2-C 本次快照**实测，样本 = 400 个随机 `kw` 源点、`pool_size=5158`）：
> ①「仅主簇」= **0.9246**（R1 后 0.9188，R1 前 0.8972）；②「主簇**∪类目**」= **0.9927**（R1 后 0.9912）；③「无向闭包」= **0.9286**；
> **全节点源点（`--source-type all`，仍是 400 采样、`pool_size=5507`）**：① **0.9202** / ② **0.9854**；
> **穷举全量 5,507 源点**（`topics-report-exhaustive.json`）：① **0.9237** / ② **0.9867**。
> ⚠️ **三类抽样互不可比**：「全节点源点」**不是全量统计**，只是把源点池从 kw 扩到全节点、**样本数仍为 400**；
> 且三者与 v1 文档图基线 0.902 **不同图 + 不同抽样口径，不构成同口径对比**。
> **P3 口径终裁（主会话 2026-09-18；数值随 R1/R2-C 重跑刷新，**裁定文本本身未改**）**：
> 硬门槛按 §4-P3 原文读法「主题的簇 = 主簇**或分类**」= ② **0.9927 ≥ 0.90 → PASS**（R1 后 0.9912，R1 前 0.9797），放行 P4；
> ① 仅主簇 **0.9246**（R1 后 0.9188，R1 前 0.8972）作为**严格观察项并列报告，不作门槛**。
> ⚠️ **「① 与 v1 基线 0.902 差 0.28pp」的旧表述已作废**：v1 基线是 **188,512 节点文档图 / 100 簇抽样**的读数，
> 本图是 **5,507 节点主题图 / 400 采样**，**不同图 + 不同抽样口径，不构成同口径对比**（R1 终审④纠偏）。
> 裁定原文见 `meta.json.stages.P3.verdict`；口径冻结记录见 `meta.json.stages.P3.caliber_freeze`；
> `topics-report-allseed.json`（全节点源点，仍是 400 采样）与 `topics-report-exhaustive.json`（穷举 5,507 源点）为补充口径。

> 衰减口径说明（`topics_report.txt` 原文）：`0.86` 是**逐跳因子**，可比量是「有效逐跳因子」= 最优路径平均边权 × 0.86；
> 「平均得分」必然低于纯 `0.86^hop` 理论线（边权均值 **0.3656** < 1 会额外压低曲线），故**比理论线应看该列**。
> 数值容忍定义（`meta.json.stages.P3.caliber_freeze.decay_tolerance`）：`hop1_mean ≥ 0.3`、有效逐跳因子 ∈ [0.3, 0.9]、第 9 跳起无新增视为正常饱和。
> **R2 终值**：hop1 均分 0.3093 / hop3 0.0751，有效逐跳因子在带内 ✅。

### 3.5 P4 · 查询编排 ✅（四子命令）

> **`--data` 是全局选项，必须写在子命令之前**：`python3 topic_graph.py --data <D> <子命令> …`
> （子命令不接受 `--data`；写在后面会得到 exit 2 `unrecognized arguments`）。

```bash
cd ~/go/reasonix-scripts/lib-catalog
D=~/go/lib-catalog-data

# ① search —— 主题检索（词面匹配 × log1p(freq)；不加载书卡，最快）
python3 topic_graph.py --data $D search "机器学习" --top 10
python3 topic_graph.py --data $D search "机器学习 入门" --top 3 --expand-top 6     # 非词表查询 → 近词扩展
python3 topic_graph.py --data $D search "机器学习 入门" --expand no               # 强制关闭扩展
python3 topic_graph.py --data $D search 量子 --json                             # 结构化输出

# ② around —— 加权扩散邻域 + 书证据（card_topics 反查）
python3 topic_graph.py --data $D around 56 --hops 2 --top 12 --evidence 8
python3 topic_graph.py --data $D around --term 量子 --hops 3

# ③ graph —— JSON 子图 {nodes:[{id,term,type,cluster,w}], edges:[{src,dst,w}], stats}
python3 topic_graph.py --data $D graph 65 --hops 2 --json-out /tmp/sub.json

# ④ summarize —— LLM 接口存根（签名固定，待与作者讨论）
python3 topic_graph.py --data $D summarize 56 --hops 2
TOPIC_LLM=mock   python3 topic_graph.py --data $D summarize 56 --hops 2
python3 topic_graph.py --data $D summarize 56 --strict-llm                       # endpoint 未实现时 exit 3
```

| 子命令 | 参数（默认值） | 输出 |
|---|---|---|
| `search <query>` | `--top 10`｜`--expand auto\|no\|yes`｜`--expand-cards 200`｜`--expand-top 10`｜`--json` | 命中主题表（`id/term/type/freq/cluster/cls/src/w`）+ 近词扩展段 |
| `around [topic_id] \| --term T` | `--hops 2`（≤12）｜`--top 12`（每层）｜`--evidence 8`｜`--threshold 0.05`｜`--decay 0.86`｜`--budget 50000`｜`--json` | 分层邻域 `(hop, term, score, via 路径)` + 证据书抽样 |
| `graph [topic_id] \| --term T` | 同 `around`，另 `--json-out PATH` | JSON 子图 + `stats{visited,edges_scanned,elapsed_ms}` |
| `summarize [topic_id] \| --term T` | 同 `graph`，另 `--llm off\|mock\|<endpoint>`｜`--strict-llm` | Markdown 摘要（存根，见 §6） |

**扩散规则**：`w_hop = w_parent × edge_w × 0.86`；初始 `score(seed)=1.0`；每跳取各入边**最大**得分；
`score ≥ --threshold`（默认 0.05）保留；访问预算 `--budget` 默认 50,000 节点；`--hops` 默认 2、**上限 12**。
`0.86` 沿用 §3.4/v1 实测值，可用 `--decay` 覆盖（接口待决 #11）。

**实测样例（来源：`topics/p4-smoke.txt`，15 例）**

| 例 | 命令 | 输出摘要 | 耗时 |
|---|---|---|---|
| ① | `search 机器学习 --top 5` | 命中 2 个主题（`机器` 817 / `学习` 1239） | 1.4ms |
| ② | `search 量子 --top 5` | 命中 1 个（`量子` 415，`src=exact`） | 1.3ms |
| ③ | `search 小说 --top 3` | 命中 4 个（`小说`/`代小说`/`小说月报`…） | 1.1ms |
| ④ | `search design --top 3` | 命中 4 个（`design`/`designing`/`designer`…） | 1.1ms |
| ⑤ | `around 56 --hops 2 --top 4 --evidence 3` | **157** 主题 / 书证据 **59,575** 本 / 扫描边 420 | 192.5ms |
| ⑥ | `around 18 --hops 2 --top 4 --evidence 3` | **206** 主题 / 书证据 **71,755** 本 | 189.8ms |
| ⑦ | `around 1647 --hops 3 --top 4 --evidence 2`（低频 `urtext` freq=13） | **561** 主题 / 扫描边 1,627 | 223.8ms |
| ⑧ | `graph 65 --hops 1 --json-out …` | 节点 **21** / 边 **153** | 187.5ms |
| ⑨ | `graph 56 --hops 2 --json-out …` | 节点 **157** / 边 **1,787** | 195.3ms |
| ⑩ | `summarize 56 --hops 2`（默认 `off`） | 12 行结构化占位文，**确定性**、不触网 | — |
| ⑪–⑬ | 非词表查询 3 例 | 均触发 TF-IDF 近词扩展（见 §4.4） | 434–449ms |
| ⑭–⑮ | 对照：`search 量子`（不触发）/ `--expand no`（关闭） | auto 规则正确 | 1.1 / 1.5ms |

---

## 4. 查询近词扩展（词表未命中时的退化路径）✅

> 交接文档 §4-P4 的「坑位要求项」；**已于 P4 二期补全**（TF-IDF 路径），抽测见 `topics/p4-smoke.txt`。
> 这是 `search` 的核心可用性保障：**查询词不在 `nodes.json` 时不再零命中**。

### 4.1 触发规则

| `--expand` | 行为 |
|---|---|
| **`auto`（默认）** | 查询**本身不是主题词表词**（字面命中里**无整词精确命中**，包含零命中）时**启用**扩展 |
| `yes` | 无论字面是否命中，**总是**启用 |
| `no` | **从不**启用 |

判定实现：`do_expand = (expand == "yes") or (expand == "auto" and best_match < 1.0)`，
其中 `best_match` = 字面命中中的最高匹配分（`match_score`：整词精确 `1.0` / 查询 token 精确 `0.9` /
前缀 `0.8` / 子串 `0.6` / 多 token 覆盖率折算 `0.4+0.4×cov`）。**只有 `1.0` 会抑制扩展**。
对照组实测：`search 量子` → `src=exact`，**不触发**扩展（1.1ms）；`search 量子 科普` → `src=token`，**触发**扩展。

### 4.2 TF-IDF 口径（与 `catalog_vector.Index.q_kw` **同源**）

```
① 词面命中（exact / token / prefix / substr）——已有路径，最快
② 近词扩展（新增）：
   复用 v1 索引 index/{tfidf.npz, vocab.json, idf.npy}（与 catalog_vector.Index.q_kw 同口径）
     · token 计数 × idf 组成查询向量（tokenize 同源，仅保留在 v1 词表内的 token）
     · 查询向量 L2 归一
     · 余弦相似度 = X @ qᵀ（X = 188,512 × |vocab| 的 TF-IDF CSR）
   → 取 top --expand-cards（默认 200）张相关书
   → 聚合这些书的 card_topics top-5 主题：agg[t] = Σ 命中书的余弦分（同书同一主题只累加一次）
   → 取 top --expand-top（默认 10）主题，映射回 nodes.json 节点，src 标注 = tfidf-expand
```

输出字段：`id / term / type / freq / cluster / cls / src="tfidf-expand" / match(=agg) / w(=rel × log1p(freq))`
＋ **`support`（支持书 mms，最多 3 个）/ `n_support_cards`（支持书数）**；`--json` 时另给
`expand{used, mode, cards_scanned, cards_hit}` 与 `expanded_hits` 全量。
**降级**：若 `index/tfidf.npz` 缺失 / tokenize 后无有效 token / 无书目命中，扩展段给出 `reason` 而不报错
（`cards_scanned=0`），**字面结果照常返回**。

### 4.3 `src` 标注取值

| `src` | 含义 | 触发条件 |
|---|---|---|
| `exact` | 整词精确命中 | `match` = 1.0（`term == 归一后查询`） |
| `token` | 查询 token 精确命中 | `match` ≥ 0.9 |
| `prefix` | 前缀命中（双向 `startswith`） | `match` ≥ 0.8 |
| `substr` | 子串命中 / 多 token 覆盖率折算 | 其余 `> 0` |
| **`tfidf-expand`** | **TF-IDF 近词扩展命中** | 由 ② 路径产生 |

> 同一次查询中，`tfidf-expand` 命中若与字面命中**指向同一主题 id**，只保留字面那条（扩展去重）。

### 4.4 实测样例（本次复跑，命令可复制；另见 `p4-smoke.txt` ⑪–⑮、`topics/audit/r2c/runs-acceptance-p4.log`）

```bash
D=~/go/lib-catalog-data
python3 topic_graph.py --data $D search "机器学习 入门" --top 3 --expand-top 6
```

| 查询（归一） | 字面命中 | 扩展命中 | 扩展主题（`src=tfidf-expand`，按 w 降序） | 命中卡 / 扫描卡 |
|---|---|---|---|---|
| `机器学习 入门` → `机器学习入门` | 2（`学习` token / `机器` token） | 4 | `machine` 2.224 · `learning` 1.328 · `python` 0.905 · `算法` 0.797 | 2,882 / 200 |
| `量子 科普` → `量子科普` | 2（`量子` token / `科普` token） | 4 | `力学` 3.105 · `quantum` 2.316 · `mechanics` 0.919 · `哲学` 0.516 | 473 / 200 |
| `人工智能 伦理` → `人工智能伦理` | 1（`智能` token） | 5 | `intelligence` 1.325 · `artificial` 1.220 · `应用` 0.751 · `技术` 0.655 · `ai` 0.453 | 1,577 / 200 |

- 每条命中均带**支持书 mms**（如 `machine` ← `991001143979704181`、`991001536594504181`），可人工核验相关性。
- 三条查询耗时 **434–449ms**（首次加载 `card_topics.jsonl` 与 TF-IDF 索引的开销）。
- **对照**：`search 量子`（词表整词）→ `src=exact`、**不触发扩展**、1.1ms；`--expand no` → 扩展段消失、1.5ms。

---

## 5. 错误码表（P4 查询 CLI `topic_graph.py`）

| 退出码 | 含义 | 触发场景（实测复核） |
|---|---|---|
| **0** | 成功 | 四子命令正常返回；`TOPIC_LLM=<endpoint>` 且**未**加 `--strict-llm` 时也返回 0（回退占位文 + stderr 警告）✅ |
| **1** | 用法/数据缺失（前置条件不满足） | · `--hops` 越界：`--hops 13` → `--hops 需在 1..12（§3.4 上限 12）` ✅<br>· `topic_id` 越界：`around 99999` → `topic_id 越界: 99999（有效范围 0..5186）` ✅<br>· 数据文件缺失：`nodes.json` / `edges.csr.npz` / `card_topics.jsonl` 不存在（提示「先跑 `topic_build.py` / `topic_edges.py`」）✅<br>· 边表 dtype 不符（应为 int64/int32/float32）✅<br>· `--term` 未找到（附相近候选提示）；`around` 既无 `topic_id` 也无 `--term` ✅ |
| **2** | argparse 用法错误 | 未知参数（如 `--badflag`）、`topic_id` 非整数、**把全局 `--data` 写在子命令之后**（→ `unrecognized arguments`）✅ |
| **3** | LLM 通道异常（仅 `--strict-llm`） | `TOPIC_LLM` 为非 `off`/`mock` 的取值（如 `endpoint`）且该模式**尚未实现** → 暴露 exit 3（不加 `--strict-llm` 则为 exit 0 + 回退占位文）✅ |

**`TOPIC_LLM` 取值**：**未设置 = `off`（默认；纯结构化占位，不触网）**｜`mock`（确定性模板文）｜`<endpoint>`（**唯一允许触网的取值，本期未实现**，会 warn 并回退）。
`--llm` 命令行参数优先于环境变量。

> ⚠️ **与草案/交接文档的差异**：`interface-proposal.md` 与 `README-draft.md` 曾写「`mock` 为默认」，
> **实测实现是 `off` 为默认**（`topic_graph.py: TOPIC_LLM_DEFAULT = "off"`，`acceptance/topics-p4.sh` 亦断言
> 「未设 `TOPIC_LLM` 时默认 off」）。交接文档 §3.4「默认返回模板文」的口径未落地——**是否改为 `mock` 默认，列为待讨论点**（§8-R12 / `INTERFACE-PROPOSAL.md` #5）。

---

## 6. LLM 接口签名（存根协议 · **待与作者讨论**）

> ⚠️ **本节为提案，待与作者（wormforce）讨论后定稿**。交接文档 §0.3 明确：**不直接接入 LLM**，
> 社区摘要/查询综合**只留接口**。本模块**不新增 `topic_llm.py` 文件**——存根实现在 `topic_graph.py` 内，
> 函数名与签名已固定：`summarize_topic_region(region: dict) -> str`。
> 以下任何一条都可以在讨论中被推翻。

### 6.1 函数签名

```python
# 实现在 topic_graph.py（P4 已落地为存根；**签名固定**）
def summarize_topic_region(region: dict) -> str:
    """把查询区域（region）渲染为一段人类可读摘要。

    入参 region: 见 6.2 结构（纯数据，无 LLM 依赖）。
    返回: str —— Markdown 纯文本段落（**不返回 JSON**；结构化数据由 graph/around 的 --json 通道给出）。
    约定:
      - 确定性: TOPIC_LLM=off|mock 时同一 region 必须返回同一字符串（禁随机、禁时间戳）。
        实测：同 region 两次输出**逐字节一致**（acceptance/topics-p4.sh）。
      - 不引入外部事实: 只允许使用 region 内的 term/cls/score/证据书字段，
        禁止补充模型自有的领域知识或对书目做推断。
      - 不触网: 除 TOPIC_LLM=<endpoint> 显式指定外不得发起网络请求；
        静态检查确认 topic_graph.py 无 requests/urllib/http/socket/url 调用面。
      - 失败回退: 任何异常 → 回退占位文 + stderr warning，退出码不变
        （--strict-llm 时以退出码 3 表示 LLM 失败）。
    """
```

### 6.2 入参 `region` 的结构（实测键，来源：`topic_graph.make_region`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `seed` | obj | `{"id", "term", "type", "freq", "cluster", "cls"}` —— 查询种子主题（BFS 起点） |
| `hops` | int | 实际扩散跳数（≤12） |
| `decay` | float | 每跳衰减系数（默认 0.86，已为 P3 采用；可用 `--decay` 覆盖） |
| `threshold` | float | 得分阈值（默认 0.05） |
| `layers` | obj[] | 分层邻域，每层 `{"hop": int, "n": int, "nodes": [{"id","term","type","score","path": [str]}]}`，按 `score` 降序 |
| `evidence` | obj[] | 证据书 `{"mms","title","cls","cls2","topics"}`（回查 `card_topics.jsonl`，条数 = `--evidence`） |
| `stats` | obj | `{"visited","edges_scanned","books","books_capped","saturated_budget","elapsed_ms", "weight_min","weight_median","weight_max"}`（供摘要自述规模） |

**占位文实际包含的字段**（`acceptance/topics-p4.sh` 断言）：扩散规则、区域规模（主题数/证据书数）、
权重分布 min/中位/max、层级分布、代表主题、证据书样例。

### 6.3 待与作者讨论（本节相关）

| # | 议题 | 现状 / 倾向 |
|---|---|---|
| 1 | `summarize_topic_region` 的**签名本身** | 当前固定为 `(region: dict) -> str`；是否改为 `(region, *, style=...)`、是否返回结构化 `dict` 而非 `str` → **待决** |
| 2 | `<endpoint>` 的**协议与鉴权** | OpenAI 兼容 `/v1/chat/completions`？本地模型？密钥来源？→ **本期未实现**（`--strict-llm` exit 3 即为此预留） |
| 3 | **隐私边界** | 送外部的字段是否只允许 `term`/`cls`/`score`，**禁止**送 `mms`、书名、卡片正文 → **待决** |
| 4 | **调用预算** | 单查询 token/费用上限、超时、缓存策略（同 region 结果是否落盘复用）→ **待决** |
| 5 | **默认通道** | 实现为 `off` 默认（不渲染）；草案与交接文档 §3.4 曾倾向 `mock` 默认 → **是否改默认值待决** |
| 6 | 失败语义 | 回退占位文后**是否**要以非零退出码暴露（已实现 `--strict-llm` → exit 3）→ **待决是否常开** |

---

## 7. 验收 ✅

```bash
cd ~/go/reasonix-scripts/lib-catalog
bash acceptance/topics-p0.sh 2>&1 | tee ~/go/lib-catalog-data/topics/audit/r2c/runs-acceptance-p0.log
bash acceptance/topics-p1.sh 2>&1 | tee ~/go/lib-catalog-data/topics/audit/r2c/runs-acceptance-p1.log
bash acceptance/topics-p2.sh 2>&1 | tee ~/go/lib-catalog-data/topics/audit/r2c/runs-acceptance-p2.log
bash acceptance/topics-p3.sh 2>&1 | tee ~/go/lib-catalog-data/topics/audit/r2c/runs-acceptance-p3.log
bash acceptance/topics-p4.sh 2>&1 | tee ~/go/lib-catalog-data/topics/audit/r2c/runs-acceptance-p4.log
bash acceptance/topics-p5.sh 2>&1 | tee ~/go/lib-catalog-data/topics/audit/r2c/runs-acceptance-p5.log
```

| 脚本 | 断言要点 | **当前结果**（R2-C 末次复跑 `topics/audit/r2c/runs-acceptance-p*.log`） |
|---|---|---|
| `acceptance/topics-p0.sh` | 基线含 12 跳且覆盖 ∈ [0.882, 0.922]；`meta.json` 合法、顶层 `stage=P0`、`baseline` 指向 `baseline-p0.txt` | ✅ **PASS (pass=8 fail=0)**，覆盖 0.902 |
| `acceptance/topics-p1.sh` | nodes.json 合法 / 规模 ∈[5000,20000] / 7 字段 / id 连续 / term 唯一 / 无 freq=0 / type 仅 kw&cls；与构建报告 7 项计数一致；顶层仍 P0 + `stages.P1` 齐备、噪声率 ≤10% | ✅ **PASS (pass=17 fail=0)** |
| `acceptance/topics-p2.sh` | 边表 CSR/dtype/出度/权重/证据链与 `stages.P2` 一致性；`rank_by=assoc`、`chosen=aug`、自测 12 跳 **0.9246**；**[4b] 边型数组 `types`（5 条断言，R2-C 新增）** | ✅ **PASS (pass=35 fail=0)**（R1 后 30） |
| `acceptance/topics-p3.sh` | 三口径均 hop=12；**硬门槛 ② 0.9927 ≥ 0.9 → PASS**；**① 0.9246 如实并列、未被口径改写**；p50 < 1000ms；连通/衰减/dtype 齐；`stages.P3.verdict` 已登记 | ✅ **PASS (pass=21 fail=0)**（R1 后 21） |
| `acceptance/topics-p4.sh` | 四子命令 exit 0 / 手算扩散 1–2 跳（0.86、0.7396）/ 存根确定性 / 无网络静态检查 / 护栏（exit 1）/ JSON 结构 / 近词扩展 7 项 | ✅ **PASS (pass=38 fail=0)**（R1 后 38） |
| `acceptance/topics-p5.sh` | 交付文档齐 / 导出版自洽（二进制回读 dtype/节点数/边数/证据链/权重还原/manifest 段）/ `stages.P0–P4` 齐备 / 顶层 `stage` 仍 P0 | ✅ **PASS (pass=28 fail=0)**（R1 后 28） |

> **合计 8 + 17 + 35 + 21 + 38 + 28 = 147 项断言全绿、exit 全 0**（R1 后为 142 项，R1 前为 100 项）。
> ⚠️ **`topics/acceptance-p*.log` 是 20:01 的历史快照**（合计 142，P2=30/P3=21/P4=38）；**当前终值以 R2-C 末次复跑为准**。

**附件**：`topics/p2-tuning.md`（调参证据）、`topics/p4-smoke.txt`（P4 15 例抽测）、
`acceptance/topics-p3-smoke.log`（P3 冒烟）、`topics/topics-report.txt|json`（P3 报告）、
`topics/topics-report-allseed.json`（全节点源点口径，仍是 400 采样）、`topics/topics-report-exhaustive.json`（穷举 5,507 源点）。

**P5 发行样例（`--topics-only`，只生成、不发布）✅**

```bash
python3 export_release.py --data ~/go/lib-catalog-data --topics-only --out <out>
```

产物落 `<out>/topics/`（实测 `topics/export-sample/v1/topics/`，**8 个文件**；含外层 `manifest.json` 共 **9 个文件 / 合计 4,255,902 字节**，R2-C 重建）：
`nodes.json`、`edges_indptr.i64.bin`、`edges_indices.i32.bin`、`edges_weights.u8.bin`（**uint8 量化，还原 `w = v/255.0`**）、
**`edges_types.u8.bin`（R2-C 新增：边型位图，与 `edges_indices` 行序对齐）**、
`card_topics_indptr.i32.bin`、`card_topics_ids.i32.bin`、`meta.json`、`manifest.topics.json`（含各文件 sha256 + `snapshot` 段）。
`manifest.json.stats.topics`：`nodes 5507 / edges 105414 / avg_outdeg 19.142 / max_outdeg 20 / cards 188512 / card_topic_links 501205`；
`stats.quant` 登记量化规则与实测误差（`max_abs_err 0.00196 ≤ 1/510`）；`stats.edge_types` 登记位图定义与直方图。
**同源保证（R2-C E1 修复）**：复制前逐项对齐 `stages.P2` 登记值与实测值，结果与源数据 sha256 写入 `manifest.topics.json#snapshot`；`--strict` 不一致即失败。
**默认关闭**（不加 `--topics` 时行为与 v1 完全一致）；**是否进 data-v2 发行由作者决定**。

---

## 8. 已知边界与待确认

| # | 事项 | 状态 |
|---|---|---|
| **R1** | ✅ **已裁定**：P3 硬门槛按 §4-P3 原文「簇 = 主簇**或分类**」= **② 0.9927 PASS**（R2 终值），P4 已放行；**① 仅主簇 0.9246 作为并列严格观察项**。**不调 P2 救 ①**（出度 20→30 破规格且仅 +0.6pp，已证伪）；变体 CSR 留档不进发行 | ✅ 已闭环 |
| **R11** | ✅ **已冻结**：三口径**必须同时报告**（R2 终值 ①0.9246 / ②0.9927 / ③0.9286，**并附抽样口径与源点池**），门槛用 ②；`topics_report.py --samples 400 --hops 12 --seed 42` 为冻结命令，已写入 `acceptance/topics-p3.sh`。§3.2 字面口径（`--rank-by weight`，0.7744）仅作历史对照 | ✅ 已冻结 |
| R2 | ✅ **已闭环**：`stages.P2` 已登记（含 `params`/`counts`/`edge_stats`/`self_test`）；**R2-A/B/C 段亦已登记** | ✅ |
| R3 | ✅ **已闭环**：`acceptance/topics-p{0,1,2,3,4}.sh` 五脚本齐备且全绿；**`topics-p5.sh` 亦已落位** → 六脚本 **147 项全绿** | ✅ |
| R4 | ✅ **已闭环**：`topic_graph.py` 已实现（四子命令 + 近词扩展 + 存根）；**不新增 `topic_llm.py`**，存根在 `topic_graph.py` 内 | ✅ |
| R5 | ✅ **已闭环（R2-D 修）**：`topic_build.py` docstring 的 `--min-df` 默认值原写 8，与 argparse 实际默认 12 不一致；docstring 已改为 **12** | ✅ 已修 |
| R6 | 空主题卡 **21,607 张（11.46%）** 无任何 top-5 主题（标题无命中词），对证据链召回的影响待评估（R1 后为 22,573 / 11.97%） | 🟡 |
| R7 | 主题图无向连通分量 **4 个**，最大 **5,504（99.9455%）**；另有 **3** 个出度 0 的孤立节点（P2/P3 复核一致 ✅） | 🟡 正常 |
| R8 | 共现书数封顶 `cap=50`：实测饱和对 **2,302（0.66%）**，但共现书数 **max 1,221** 远超封顶，热门词间分辨率被压平（`INTERFACE-PROPOSAL.md` #5）（R1 后为 3,878 / 1.17%） | 🟡 待讨论 |
| R9 | 兼容性举证：交接文档 §4-P5 要求「git diff 证明未触碰 v1 文件」，但 `~/go/reasonix-scripts` **不是 git 仓库**。**替代举证**：v1 数据文件 mtime 全部 ≤ 09-18 14:01，topics 施工自 17:27 起 → **施工窗口内 v1 文件零写入**；`meta.json.notes` 亦记录「全程只读」。**R2-C 已在 `manifest.topics.json#snapshot.source_sha256` 登记 `cards.jsonl` 的 sha256**（`9e9dffd2…`），首次给出可对账的内容指纹 | 🟡 部分闭环 |
| R10 | `kw` 节点 `cls` 字段的一级类目（**37** 个）与 `cls` 节点的 `cls2` 类目（**349** 个）共用同一字段名，语义需在 schema 中区分（§2.1 已注明） | 🟡 |
| **R12** | 🟡 **`TOPIC_LLM` 默认值口径分歧**：实现为 **`off` 默认**（不渲染、不触网），草案与交接文档 §3.4 曾写「默认 `mock` / 默认返回模板文」——**需作者确认是否改默认**（`INTERFACE-PROPOSAL.md` §0 已记为事实陈述） | 🟡 待确认 |
| R13 | `--data` 必须写在子命令**之前**（全局选项）；写在后面会 `exit 2` | 🟡 易踩，已在 §3.5 标注 |
| R14 | 衰减系数 `0.86` 实测自 188.5k 文档图；主题图上最优路平均边权 **0.4519**，有效逐跳因子 0.31–0.49 → **0.86 并非主题图的真实逐跳衰减**（`INTERFACE-PROPOSAL.md` #11）；容忍带定义已登记 `stages.P3.caliber_freeze.decay_tolerance` | 🟡 待讨论 |
| **R15** | ✅ **已闭环（R2-D 新增）**：顶层 `stage` 与 `current_stage` 双轨语义已显式声明（§2.4 告警框）；**R3 待办**：验收脚本断言改指 `stages.P0.stage`，并把 `topics_meta.py --stage choices` 扩到 `P5\|R2-*` | ✅ 已登记风险 |
| **R16** | 🟡 **`stages.P2` 内 `p2-tuning` / `tuning_evidence` / `r1_fix` 为 pre-r2 历史留痕，未随 R2-A 重算**（`meta.json.stages.P2.r2a_refresh` 已声明）；引用时须注意其为 5,187 节点口径 | 🟡 已知 |
| **R17** | 🟡 **`meta.json` 缩进不统一**：`topics_meta.py` 写 `indent=2`，R2/R2-D 专项登记脚本写 `indent=1` → 每次跨脚本改动都产生全文件 diff 噪声，掩盖真实变更。**R3 待办**：统一为 `indent=1` 并写进登记器契约 | 🟡 待统一 |
| **R18** | ✅ **已闭环（R2-D）**：`stages.P2` 曾未随 R2-C 回刷（`generated_at` 停在 21:07、`params` 缺 `b5_edgetype_rule`）→ 已按当前 `p2-build-report.json` 回刷，before→after 留痕 `stages.P2.r2d_sync` | ✅ 已修 |
| **R19** | ✅ **已闭环（R2-D）**：导出版**包内 `meta.json` 是打包时点（21:37）快照，不含 `stages.P5`** —— 快照语义本身正确（包内 meta 与包内数据同源，由 `manifest#snapshot` 校验），但「包内自洽 ≠ 最新口径」。**R3 待办**：需要最新口径时用 `export_release.py --topics-only` 重导，或让 manifest 注明「本包 meta 对应活件 sha256」 | 🟡 已知 |
| **R20** | ✅ **已证良性（R2-D）**：两处 mtime 因果倒挂均经复算排除风险 —— ① `edges.csr.npz`(21:35) 晚于 `topics-report.json`(21:29)：R2-C 只**追加** `types.npy`，三数组与 `pre-r2c` 逐字节相同；② `topic_build.py`(21:44) 晚于 `nodes.json`(21:06)：按当前脚本隔离复跑，`nodes.json` **逐字节相同**（证据 `audit/meta/repro-evidence.json`） | ✅ 已证 |


---

## 9. 数字来源索引

| 数字（**R2 终值**） | 来源文件 |
|---|---|
| **5,507 节点 / kw 5,158 / cls 349** / freq 统计 / **397** 簇 / 无 -1 | `topics/nodes.json`（本次复算）、`meta.json.stages.P1.counts`、`topics/audit/r2c/runs-acceptance-p1.log` |
| **105,414 边** / dtype / 出度 **19.142** / 权重分布 min 0.1763·median 0.2292·mean 0.3656 / **w=1 占 8.05%** | `topics/edges.csr.npz`（本次 npz 复算）、`meta.json.stages.P2.edge_stats`、`topics/audit/r2c/runs-acceptance-p2.log` |
| **边型位图** `types` uint8 / 直方图 `{1:89643, 3:10620, 5:4358, 7:793}` / 多重类型 15,771 | `meta.json.stages['R2-C'].edge_types`、`topics/audit/r2c/verify_types_r2c.py` |
| 三类边公式 / `rank_by=assoc` / `variant=aug` / distinct 对 **349,680** / 层级边 **5,151** | `meta.json.stages.P2.params` + `.counts`、`topic_edges.py` |
| 0.7744 / 0.8553 / 0.8972 / 0.9030 / 0.9028 / 0.9797 —— **调参期历史矩阵（R1 前、5,187 节点口径），非当前值** | `topics/p2-tuning.md`、`topics/p2-tuning.json`、`meta.json.stages.P2['p2-tuning']` |
| **①0.9246 ②0.9927 ③0.9286** / 全节点源点 ①0.9202 ②0.9854 / 穷举 ①0.9237 ②0.9867 | `topics/topics-report.json`、`topics/topics-report-allseed.json`、`topics/topics-report-exhaustive.json`、`meta.json.stages.P3.coverage` |
| **p50 2.580ms / p95 3.740ms** / 衰减 hop1 0.3093·hop3 0.0751 / 连通 4–**5,504** | `topics/topics-report.json`、`meta.json.stages.P3.performance|connectivity|decay` |
| P3 裁定文本 / 门槛 / 分母定义 / 衰减容忍 | `meta.json.stages.P3.verdict` + `.caliber_freeze` |
| 188,512 行证据链 / 尺寸分布 / **空卡 21,607** | `topics/card_topics.jsonl`（`wc -l`）、`meta.json.stages.P2.counts`、`topics/audit/r2c/runs-acceptance-p2.log` |
| 近词扩展规则 / 实测样例 / 护栏 / 存根签名 | `topics/p4-smoke.txt`、`topics/p4-relevance.md`、`meta.json.stages.P4`、`topic_graph.py` |
| 退出码 0/1/2/3 | `topic_graph.py` + 本次实测复核、`topics/audit/r2c/runs-acceptance-p4.log` |
| 验收 **8/17/35/21/38/28 = 147 项全绿** | `topics/audit/r2c/runs-acceptance-p{0..5}.log`（**当前终值**；`topics/acceptance-p*.log` 是 20:01/142 项的历史快照） |
| 导出版 **9 文件 / 4,255,902 字节** / card_topic_links **501,205** / 包内 meta 同源 | `topics/export-sample/v1/manifest.json`、`topics/export-sample/v1/topics/manifest.topics.json`（含 `snapshot` 段） |
| P0 基线 0.902 / 0.911（400 簇） | `topics/baseline-p0.txt`、`meta.json.baseline_numbers`、`meta.json.supplementary` |
| R2 三轮 before/after 全表 | `meta.json.stages['R2-A'|'R2-B'|'R2-C']`、`topics/audit/{p1,r2c,relevance}/REPORT.md` |

> ⚠️ **本索引的维护约定（R2-D 新增）**：表中数字**必须可在所引文件中实地复算**；
> 凡属历史快照（调参期矩阵、`acceptance-p*.log`、`pre-r1/pre-r2/pre-r2c` 备份）**必须显式标注口径与时点**，
> 不得与当前终值并列而不加区分。引用本表时请连同「口径 + 时点」一并转述。

---

*本文档为 **P5 定稿版 · R2-D 同步版**（2026-09-18；数字与登记状态已同步到 R2 全轮终值）。
过程稿保留在 `topics/docs-draft/`（`README-draft.md` / `changelog-draft.md` / `interface-proposal.md`），**不删除**。
本次同步的备份为 `topics/README.md.pre-r2d`；逐条同步清单见 `ACCEPTANCE-REPORT.md` §11.4。*
