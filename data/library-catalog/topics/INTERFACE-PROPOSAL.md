# 接口协议定稿 — 图书馆主题图（GraphRAG-lite）

**呈**：wormforce ｜ **自**：lib-catalog 工具链施工方 ｜ **日期**：2026-09-18（P5 定稿）
**状态**：**已定稿**。§0 的两项门槛口径**已由主会话裁定为事实**；§1–§3 为实现现状；§4 保留待讨论点并逐条标注状态。
**一句话**：在 v1 文档图之上加一层「主题图」（**5,187** 主题节点 + **99,268** 条类型化边 + 证据链），
查询走 ≤12 跳加权 BFS；**LLM 只留接口存根，默认 `TOPIC_LLM=off` 不触网**。

---

## 0. 已裁定（原待决 #1/#2 —— 不再是问题，改为事实陈述）

| 原待决 | **裁定（主会话 2026-09-18）** |
|---|---|
| **#1 12 跳覆盖 0.8972 差 0.28pp——放行 P4 还是继续调？** | **已放行 P4**。硬门槛采用 §4-P3 原文读法「主题的簇 = 主簇**或分类**」= ② **0.9797 ≥ 0.90 → PASS**；**继续调参的选项被否决**——出度 20→30 会破「平均出度 ≤20」规格且实测收益仅 +0.6pp（**已证伪**） |
| **#2 用哪个口径当验收标准？** | **硬门槛 = ②「主簇∪类目」0.9797（PASS）**；**① 「仅主簇」0.8972 作为并列观察项如实报告、不作门槛**（与 v1 文档图基线 0.902 基本持平，差 0.28pp）；③「无向闭包」0.9200 作方向性诊断列。**三口径必须同时报告**，禁止只报一个 |

- 裁定原文落 `lib-catalog-data/topics/meta.json` → `stages.P3.verdict`；冻结命令 `topics_report.py --samples 400 --hops 12 --seed 42`，
  断言已写入 `acceptance/topics-p3.sh`（**PASS 18/0**）。
- **其余口径的处置**：§3.2 字面口径（`--rank-by weight`，**0.7744**）降为对照实验；变体 CSR
  （`edges.variant-spec.csr.npz`，`spec` 口径）保留在数据目录作研究记录，**不进发行**。

---

## 1. LLM 接口约定（实现现状）

```python
# 实现在 topic_graph.py 内（P4 已落地为存根，签名固定）；**不新增 topic_llm.py**
def summarize_topic_region(region: dict) -> str: ...
```

| 项 | 约定 |
|---|---|
| 入参 `region` | `seed{id,term,type,freq,cluster,cls}` / `hops` / `decay` / `threshold` / `layers[{hop,n,nodes[{id,term,type,score,path}]}]` / `evidence[{mms,title,cls,cls2,topics}]` / `stats{visited,edges_scanned,books,books_capped,saturated_budget,elapsed_ms,weight_min/median/max}` |
| 返回 | `str`（Markdown 段落）。**不返回 JSON**——结构化数据由 `graph --json` / `around --json` 通道给出，职责分离 |
| 环境变量 | **`TOPIC_LLM` 未设置 = `off`（默认；纯结构化占位，不触网）**｜`mock`（确定性模板文）｜`<endpoint>`（唯一允许触网的取值，**本期未实现**）。`--llm` 参数优先于环境变量 |
| 硬约束 | ① **默认不触网**（静态检查确认无 `requests/urllib/http/socket/url` 调用面）；② `off`/`mock` 必须**确定性**（实测同 region 两次输出逐字节一致）；③ **不得引入 region 之外的事实**（禁模型自有领域知识、禁对书目做推断） |
| 失败回退 | 任何异常 → 回退占位文 + stderr warning，退出码不变；`--strict-llm` 时以 **exit 3** 暴露（实测：`TOPIC_LLM=endpoint` + `--strict-llm` → 3；不加则为 0） |

> ⚠️ **一处口径分歧请您确认**：草案与 handoff §3.4 写「默认 `mock` / 默认返回模板文」，
> **实现为 `off` 默认**（`topic_graph.py: TOPIC_LLM_DEFAULT = "off"`，验收脚本亦断言默认 `off`）。
> **是否改为 `mock` 默认**，见 §4 #5。

---

## 2. 数据形态对照（v1 文档图 vs 主题图，均为实测）

| 维度 | v1 文档图 ✅（已发布） | 主题图 ✅（P0–P4 全绿） |
|---|---|---|
| 节点 | **188,512** 本书卡 | **5,187** 主题（`kw` 4,838 + `cls` 349） |
| 节点键 | `mms` | `id` 连续 0..5186（`term` 全量唯一） |
| 边 | `index/knn_csr.npz`，K=10，**1,885,120** 边，互链率 0.423 | `topics/edges.csr.npz`：`indptr` int64 / `indices` int32 / `weights` float32，**E=99,268**，**有向、出度 ≤20（实测 avg 19.14 / max 20）**，权重 ∈[0.176, 1.0] |
| 边型 | 单一（kNN 语义相似） | **三类**：① 同书共现（双向）`w1=log1p(min(共现书数,50))/log1p(50)`｜② 同簇加成（双向）`w2=0.3×log1p(簇内共现)/log1p(50)`，`w=min(1,w1+w2)`｜③ 主题→CLC `cls2` 类目（**单向**）`w=1.0`。截断排序键默认 `--rank-by assoc`（关联度），非权重 |
| 簇 | 400 语义簇 | 复用同一 400 簇（`cluster` 字段；实际用到 **396** 个） |
| 证据链 | 卡 ↔ 自身 | 新增 `topics/card_topics.jsonl`：**188,512** 行 `{"mms","topics":[id×≤5]}`（**不改 `cards.jsonl`**）；空主题卡 22,573（11.97%）；主题-卡链接 **487,933** 条 |
| 结构 | 扁平（无类型、无层级） | 带类型 + 层级（`kw → cls2`，层级边 **4,832** 条），LLM 摘要的天然输入 |
| 查询 | `catalog_vector.py search/kw/hybrid/links/graph` | ✅ `topic_graph.py search/around/graph/summarize`（**已实现**），≤12 跳 |
| **12 跳验收口径** | 覆盖 **0.902**（中位 0.938）✅ | **硬门槛 ② 0.9797 ✅ PASS**（并列观察项 ① 0.8972；③ 无向闭包 0.9200） |
| 性能 | 基线复现 18.2s | 12 跳单查询 **p50 1.986ms / p95 2.395ms** ✅（门槛 <1s，理想 <300ms） |
| 连通性 | 无向分量 3 个；最大 188,488（99.99%） | 无向分量 **4** 个；最大 5,184（**99.94%**） |

---

## 3. 集成点（现状）

1. **发行层 `export_release.py`**：✅ **已实现 topics 分支** —— `--topics`（随包附带）/ `--topics-only`（仅主题图），
   **只生成、不发布**。产物落 `<out>/topics/`：`nodes.json`、`edges_{indptr.i64,indices.i32,weights.u8}.bin`
   （**uint8 量化，还原 `w = v/255.0`**）、`card_topics_{indptr.i32,ids.i32}.bin`、`meta.json`、`manifest.topics.json`（含 sha256）。
   实测样例：`topics/export-sample/v1/topics/` = **8 文件 / 4,004,106 字节**。**默认关闭**，不加 `--topics` 时行为与 v1 完全一致。
2. **data-v2 发行**：`~/go/lib-catalog-release/v1/`（含 `lib-catalog-data-v1.tar.gz`，~98 MB）已发布；
   **topics 是否进 v2、以何版本号发布，由您决定** 🟡。
3. **v1 兼容**：新文件全部落 `~/go/lib-catalog-data/topics/`；v1 数据文件与现有命令行为**不变**（新命令只增不改）。
   举证方式：`~/go/reasonix-scripts` 非 git 仓库 → 以 **mtime 时序**替代（v1 文件全部 ≤ 09-18 14:01，施工自 17:27 起，窗口内零写入）。

---

## 4. 待讨论点清单（🟡 = 仍待您裁决；✅ = 已闭环）

| # | 议题 | 状态 / 现状 |
|---|---|---|
| 1 | 12 跳覆盖放行 P4 还是继续调 | ✅ **已裁定**（见 §0）：按「主簇或分类」口径 0.9797 PASS 放行；回退方案已证伪 |
| 2 | 用哪个口径当验收标准 | ✅ **已裁定**（见 §0）：门槛用 ②0.9797；①0.8972 并列观察项；三口径同时报告 |
| 3 | **`cls` 是否参与共现** | 🟡 已实现为开关：`spec`（仅 kw）/ `aug`（并入 cls2），`auto` 选了 `aug` 并落主产物；`spec` 另存。**要不要长期保留双产物？** |
| 4 | **出度上限 20 是否放宽到 30** | 🟡 实测：`weight/30` → 0.8553（仍不达标）、`assoc/30` → 0.9028（刚过线）；代价 avg 出度 19.14 → **27.81**、边数 99,268 → 144,272。**结论：出度是弱杠杆，排序键才是强杠杆**——是否仍要求放宽？ |
| 5 | **`TOPIC_LLM` 默认值（`off` vs `mock`）** | 🟡 **新提出**：实现为 `off` 默认，handoff §3.4 曾写「默认返回模板文」。**是否改默认？** |
| 6 | **共现封顶 50 是否合理** | 🟡 饱和对仅 3,878（**1.17%**），但共现书数 **max 2,052**（远超封顶）→ 热门词间分辨率被压平；备选：提高封顶或改分位归一 |
| 7 | **同簇边 0.3 的定位** | 🟡 同簇对**必然已有共现边**（`cnt_sc>0 ⟹ cnt>0`），故 `sum` 口径下 ② 只是加成、`max` 口径下 ② **恒被①支配而失效**（代码已注明）。→ **② 该不该保留？** |
| 8 | **截断排序键 `--rank-by`** | 🟡 新增 `assoc`（**现默认**）vs `weight`（§3.2 字面）。**权重公式一字未改，覆盖 0.7744 → 0.8972**（avg 出度反而更低）。**§3.2 是否应把它写成正式口径？** |
| 9 | **证据链是否改变 v1 发行格式** | 🟡 现为独立 `manifest.topics.json` + `--topics` 可选分支；是否需并入 v1 `manifest.json` 主条目 |
| 10 | **门槛口径与规模归一化** | 🟡 覆盖被「非本簇但可达」节点稀释（12 跳可达均 **5,042/5,187**）。建议：改「同簇可达率 + 精度」双指标，或按图规模归一化跳数 |
| 11 | **LLM 调用预算与隐私边界** | 🟡 送外部的字段是否限 `term/cls/score`（禁 `mms`、书名、卡片正文）；token/费用上限、超时、结果缓存是否落盘 |
| 12 | **衰减系数 0.86 是否可迁移** | 🟡 0.86 实测自 188.5k 文档图；主题图上最优路平均边权 0.51→0.36，有效逐跳因子 0.44→0.31 → **0.86 并非主题图的真实逐跳衰减**（可用 `--decay` 覆盖） |
| 13 | **词形与空卡** | 🟡 `term` 归一含「纯 ASCII 转小写」（`design`）与长度 1–16；CLC 类目保留大小写（`TP3`）。另有 **22,573 张卡（11.97%）** 无任何 top-5 主题，是否需补抽取策略 |

**建议的最小决策集**：#5（LLM 默认值，1 行改动）+ #3/#4（双产物与出度上限是否长期保留）+ #11（LLM 边界）+ 集成点 2（topics 是否进 data-v2）。
其余可留待真实查询流量数据出来后再定。

---

*定稿依据：`topics/meta.json`（`stages.P0`–`stages.P4`，含 `stages.P3.verdict` 裁定原文）、`topics/p2-tuning.md`、`topics/topics-report.{json,txt}`、
`topics/p4-smoke.txt`、`topics/acceptance-p{0,1,2,3,4}.log`、`topics/export-sample/v1/manifest.json`。过程稿保留于 `topics/docs-draft/`。*
