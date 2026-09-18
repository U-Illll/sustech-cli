# lib-catalog — 图书馆目录「编译 + 双索引 + 语义图谱」(v2)

参考 Agentic-RAG（`memory-map/`）机制，为《南科大图书馆藏书目录》
（南方科技大学图书馆公开检索系统导出）提供四层工具链：

```
桌面导出数据（books.csv / catalog_full.csv / shelf_index.csv / 涵泳特藏_*.jsonl）
   │  compile_cards.py（编译层：分类号解析 + 书架/学科目录）
   ▼
~/go/lib-catalog-data/cards.jsonl        188,512 张书卡（含 cn/cls/cls2）
   │  catalog_vector.py build（双索引层）
   ▼
index/  tfidf.npz + embeddings.npy（bge-small-zh-v1.5, 512 维）
   │  build_graph.py（语义图谱层：kNN 内链 + 语义簇；对齐记忆系统 [[双链]]/主题簇）
   ▼
index/knn_csr.npz + clusters.npy + clusters.json（400 簇目录）
   │  export_release.py（发行层：int8 量化瘦身 → GitHub Release 分发包）
   ▼
~/go/lib-catalog-release/<version>/（纯 .bin + manifest，面向 Node/Python 消费）
```

## 工具与命令

```bash
# 0) 完整性检查（对任意导出目录；全量程序化交叉验证）
python3 check_completeness.py --base "<导出目录>" [--out 报告.txt]

# 1) 编译（默认从桌面当前版读取）
python3 compile_cards.py --src "/mnt/c/Users/汪子恒/Desktop/南科大图书馆藏书目录" \
                         --out ~/go/lib-catalog-data
# 2) 双索引构建（实测 356s：TF-IDF 6s + 语义 encode 348s）
python3 catalog_vector.py build
# 3) 语义图谱（kNN 内链 K=10 + 语义簇 400；实测 223s）
python3 build_graph.py [--k 10] [--clusters 400] [--limit N 冒烟]
# 4) 质量报告（同簇可达率 / 覆盖率 / 大类分布）
python3 graph_report.py [--hops 3]
# 5) 发行包导出
python3 export_release.py [--version v1]

# 检索（LIB_CATALOG_DATA 或 --data 指向数据目录）
python3 catalog_vector.py search "机器学习" --top 10      # 语义
python3 catalog_vector.py kw "三体" --top 10              # 关键词（TF-IDF）
python3 catalog_vector.py hybrid "费曼 物理" --top 5       # 混合
python3 catalog_vector.py get <mms>                       # 书卡全貌（含分类/簇/内链）
python3 catalog_vector.py links <mms>                     # 语义内链展开（top-K 邻居）
python3 catalog_vector.py cluster <mms>|--id N [--samples 20]   # 语义簇
python3 catalog_vector.py clusters --top 30               # 簇目录
python3 catalog_vector.py graph <mms> --depth 2           # 图扩展（BFS）
python3 catalog_vector.py subjects                        # 学科目录
python3 catalog_vector.py shelves [query]                 # 书架查询
python3 catalog_vector.py stats / validate                # 统计 / 校验
```

## 数据产物（~/go/lib-catalog-data/）

| 层 | 文件 | 说明 |
|---|---|---|
| 编译 | `cards.jsonl` | 188,512 卡：mms/title/creator/publisher/year/language/type/hc/loc/cn/cls/cls2/src |
| 编译 | `shelves.json` | 416 书架（含 top 学科画像） |
| 编译 | `subjects.json` | 学科目录：38 标准学科（中图法）+ 10 馆藏代码 |
| 索引 | `index/tfidf.npz` | TF-IDF（词表 338,358 / nnz 3,665,655；标题×2 加权） |
| 索引 | `index/embeddings.npy` | 语义向量 188,512×512（bge-small-zh-v1.5，已归一化） |
| 图谱 | `index/knn_csr.npz` | 语义内链 CSR（每书 top-10 邻居；互链率 ~0.42） |
| 图谱 | `index/clusters.npy` + `clusters.json` | 语义簇归属 + 400 簇目录（关键词/代表书/学科分布） |
| 其他 | `index/{offsets,mms_index,meta,graph_meta}` | 随机访问与元数据 |

## v1 → v2 变更

1. **分类号层**：解析 catalog_full 的 call_number → cn/cls/cls2（支持标准/复分 `B-53`/馆藏代码 `CTC:B`；外文小说区作者码不视为分类）
2. **书架/学科层**：新增 shelves.json / subjects.json
3. **语义图谱层**：build_graph.py 新增（kNN 内链 + 语义簇；对齐记忆系统双链/簇机制）
4. **检索命令**：新增 links / cluster / clusters / graph / subjects / shelves
5. **编码文本修正**：语义向量的编码文本为 title+creator（不含 publisher——避免"出版社簇"污染主题聚类）
6. **发行层**：export_release.py（int8 量化 + 纯 bin 格式，供 sustech-cli 等消费）

## 设计要点（与 memory-map 的对应）

| memory-map | lib-catalog | 说明 |
|---|---|---|
| 44 记忆页 | 188,512 书卡 | 粒度：每本书一卡 |
| `[[双链]]` 图 | 语义内链 kNN（K=10/书） | 每本书指向语义最近邻 |
| 主题簇（逆向/网关/ima） | 语义簇 400（+ 中图法学科） | KMeans on embeddings |
| 同簇可达率验收 | `graph_report.py` | 3 跳可达 ≥90% |
| bge-small-zh 语义 | 同模型 | 512 维；build 时全量编码 |
| 记忆向量 hybrid | `search`/`kw`/`hybrid` | 同上：0.6 语义 + 0.4 关键词 |

## 已知边界

- 零馆藏 1,035 条（video 948/book 85/journal 1/map 1）；83 条涵泳特藏 `src=hy`
- 外文小说区作者排架码（ZOL/AUS2 等）不做分类解析；英语经典读物区代码（ER/OC/VI）保留为馆藏代码
- 语义模型为 512 维中文小模型；换更强模型只需 `build --model` 重建
- 数据源：图书馆公开检索系统（Primo VE）导出，无登录态

---

## v2 → v3 变更记录（topics 主题图）

> **总原则：v3 = 纯增量。** v1/v2 既有文件与既有命令行为**零改动**；全部新增产物落 `~/go/lib-catalog-data/topics/`。
> **完成度**：P0 ✅ / P1 ✅ / P2 ✅（含调参定稿）/ P3 ✅（**硬门槛 PASS**）/ P4 ✅（查询编排 + 近词扩展）/ P5 ✅（文档与导出版）。
> 详版见 `~/go/lib-catalog-data/topics/README.md` 与 `topics/INTERFACE-PROPOSAL.md`。

### 1. 摘要

| 项 | 内容 |
|---|---|
| 版本号 | v2 → **v3**（`v3` 仅指「topics 增量层」，**不等于** data-v2 发行定稿） |
| 一句话 | 新增 `topics/` 子模块：主题节点图（类型化边 + 证据链）+ 多阶段口径登记 + 质量报告 + 查询编排，作为 GraphRAG-lite 的实体-关系显式层 |
| 规模实测 | **5,187** 主题节点（`kw` 4,838 / `cls` 349）、**99,268** 条有向边、**188,512** 行证据链（487,933 条主题-卡链接） |
| 破坏性变更 | **无**（v1 数据文件不改、现有命令不改，新命令只增不改） |

### 1.1 验收结论（随变更记录一并披露）

> **口径铁律**：12 跳覆盖的读数取决于口径，同一份主产物跨 20+ 个百分点，**必须三口径同时报告**：
> **0.7744**（§3.2 字面/`--rank-by weight`）→ **0.8972**（默认 `assoc`·仅主簇，①）→ **0.9030**（全节点源点）→ **0.9797**（「主簇**或分类**」，②）。

| 验收项 | 实测 | 判定 |
|---|---|---|
| **12 跳覆盖 · ② 主簇∪类目（硬门槛，§4-P3 原文读法）** | **0.9797**（中位 0.9883） | ✅ **PASS**（放行 P4 的依据） |
| 12 跳覆盖 · ① 仅主簇（**并列观察项**） | **0.8972**（中位 0.9286） | 🟡 与 v1 基线 0.902 持平（差 0.28pp），**不作门槛** |
| 12 跳覆盖 · ③ 无向闭包（方向性诊断） | 0.9200 | ✅ |
| 对照 · §3.2 字面口径（`--rank-by weight`） | 0.7744 | 🔴 仅作对照，不采用 |
| 对照 · handoff 回退方案（出度 20→30） | 0.8553（`weight/30`） | 🔴 **实测无效**（且破 avg 出度 ≤20 规格） |
| 性能（12 跳加权 BFS 单查询） | p50 **1.986ms** / p95 **2.395ms** | ✅ PASS（门槛 <1s，理想 <300ms） |
| CSR 规格 / 出度 | `indptr` int64 / `indices` int32 / `weights` float32；n=5,187、nnz=99,268；avg 出度 **19.14**、max 20 | ✅ PASS |
| 连通性 | 无向分量 4 个；最大 5,184（**99.94%**） | ✅ 正常 |

**本版最重要的工程发现**：把 top-20 的**截断排序键**从「权重」换成「关联度」`count/√(freq_u·freq_v)`
（**权重公式一字未改**），覆盖从 **0.7744 → 0.8972**；根因是**按权重排序会让高频词互相垄断 20 个槽位**，
低频节点被单向吸入枢纽后无路可回。**handoff §4-P3 写明的回退（出度 20→30）实测无效**（仅到 0.8553）。
瓶颈诊断：6 跳覆盖 0.8969 ≈ 12 跳 0.8972 → **瓶颈不是跳数**；互惠加成实验无效。证据落 `topics/p2-tuning.md`。

### 2. 新增子模块 `topics/` 的约束

- **节点只收主题**：作者、出版社**不入节点**（不做作者/出版社网络）。
- **查询编排 ≤12 跳**加权 BFS：`w_hop = w_parent × edge_w × 0.86`（阈值 0.05，预算 ≤50k 节点）。
- **不直接接 LLM**：只留接口存根 `summarize_topic_region(region) -> str`，**默认 `TOPIC_LLM=off`**（不渲染、不触网）。

### 3. 新脚本

| 脚本 | 阶段 | 状态 | 说明 |
|---|---|---|---|
| `topic_build.py` | P1 | ✅ | 主题节点抽取（A 簇关键词 / B 标题 TF-IDF top-10 / C CLC `cls2` 三源合一）。正式参数 `--min-df 12 --min-df-cjk 15 --min-nodes 5000 --max-nodes 20000`；实测 **54.3s → 5,187 节点** |
| `topic_edges.py` | P2 | ✅ | 构边（三类边 + top-20 截断 + 权重归一 + CSR 落盘 + 双 variant + 内建 12 跳自测）。实测 **14.0s → 99,268 边**。**本版新增 `--rank-by`（默认 `assoc`）——覆盖 0.7744 → 0.8972 的关键改动** |
| `topics_report.py` | P3 | ✅ | 质量报告：基础统计 / **三口径 12 跳覆盖曲线** / 连通性 / 衰减 / 单查询性能计时。支持 `--json`/`--json-out`/`--txt-out`/`--mock`；**CSR dtype 不符即报错退出** |
| `topic_graph.py` | P4 | ✅ **已落地** | 查询编排 CLI：`search/around/graph/summarize`（对齐 `catalog_vector.py` 子命令风格）+ **TF-IDF 近词扩展**（`--expand auto\|no\|yes`）；退出码 0/1/2/3 |
| `topics_meta.py` | 元数据 | ✅ | `topics/meta.json` 多阶段口径登记器（`--stage P0\|P1\|P2\|P3\|P4`）。**不动顶层 `stage`**（保持 `"P0"` 兼容旧验收脚本） |
| `export_release.py` | P5 | ✅ **已扩展** | 新增 `--topics` / `--topics-only`：主题图导出版（**只生成、不发布**），沿用 int8/CSR 瘦身风格（边权 **uint8 量化，`w = v/255.0`**）。**默认关闭**，不加参数时行为与 v1 完全一致 |

> 既有脚本 `build_graph.py` / `graph_report.py` / `catalog_vector.py`：**本次未修改**
> （`topics` 只 import 复用 `catalog_vector.tokenize`、`build_graph.STOP_TOKENS/merge_bigrams`、`topic_build.normalize_term`，属只读依赖）。
> 注：`graph_report.py` 本身**没有 `--json` 参数**，P3 的 JSON 输出由新脚本 `topics_report.py` 提供。

### 4. 新数据文件（`~/go/lib-catalog-data/topics/`）

| 文件 | 内容 / 实测 |
|---|---|
| `nodes.json` | **5,187** 节点，7 字段（`id/term/type/freq/cluster/cls/sources`）；`id` 连续 0..5186、`term` 全量唯一、无 `freq=0`；freq 中位 29 / max 11,534 |
| `edges.csr.npz` | 主口径（`--variant auto` 选中 **`aug`**，`--rank-by assoc`）：**99,268** 条有向边；`indptr` int64 / `indices` int32 / `weights` float32；avg 出度 19.14、max 20；权重 ∈[0.176, 1.0]，`=1` 占 11.38% |
| `edges.variant-spec.csr.npz` | 另一口径（`spec`：仅 kw 参与共现），**研究记录，不进发行** |
| `card_topics.jsonl` | **188,512** 行，每行 `{"mms","topics":[id×≤5]}`；空主题卡 22,573（11.97%）；`cls` 不占 top-5 名额 |
| `meta.json` | 顶层 P0 遗留键 + **`stages.P0`–`stages.P4`** 分段（`stages.P3` 含三口径与裁定 `verdict`、`stages.P4` 含近词扩展与护栏）+ `current_stage="P4"` / `updated_at` / `notes_meta` |
| `README.md` / `INTERFACE-PROPOSAL.md` | P5 定稿文档（schema + 命令 + 近词扩展 + 错误码 + 接口签名） |
| `p2-tuning.md` / `p2-tuning.json` | 调参证据矩阵（6 组配置） |
| `p1-build-report.json` / `p2-build-report.json` | P1/P2 构建报告（含 988 词停用表全表 / `counts` / `edge_stats` / `self_test`） |
| `baseline-p0.txt` / `baseline-p0-curve400.txt` | 文档图基线（12 跳 0.902 / 400 簇复跑 0.911） |
| `p4-smoke.txt` | P4 抽测 15 例（四命令 + 近词扩展 + 对照） |
| `topics-report.{json,txt}` / `topics-report-allseed.json` | P3 报告（三口径 / 性能 / 连通 / 衰减） |
| `export-sample/` | 导出版样例（`--topics-only`，8 文件 / 4,004,106 字节，含 sha256 清单） |
| `acceptance-p{0,1,2,3,4}.log` | 五阶段验收留痕 |
| `docs-draft/` | P5 过程稿（草案三份，**保留不删**） |

### 5. 新增验收脚本（`acceptance/`）—— 五脚本全绿

```bash
cd ~/go/reasonix-scripts/lib-catalog
bash acceptance/topics-p0.sh   # ✅ PASS (pass=8  fail=0)
bash acceptance/topics-p1.sh   # ✅ PASS (pass=17 fail=0)
bash acceptance/topics-p2.sh   # ✅ PASS (pass=27 fail=0)
bash acceptance/topics-p3.sh   # ✅ PASS (pass=18 fail=0)
bash acceptance/topics-p4.sh   # ✅ PASS (pass=30 fail=0)
```

| 脚本 | 断言要点 | 结果 |
|---|---|---|
| `topics-p0.sh` | 基线含 12 跳且覆盖 ∈[0.882, 0.922]；`meta.json` 合法、顶层 `stage=P0` | ✅ 8/0 |
| `topics-p1.sh` | nodes.json schema/规模/id 连续/term 唯一/无 freq=0；与构建报告 7 项计数一致；`stages.P1` 齐备、噪声率 ≤10% | ✅ 17/0 |
| `topics-p2.sh` | 边表 CSR/dtype/出度/权重/证据链与 `stages.P2` 一致；`rank_by=assoc`、`chosen=aug` | ✅ 27/0 |
| `topics-p3.sh` | 三口径均 hop=12；**硬门槛 ②0.9797 ≥0.9 PASS**；**①0.8972 如实并列未被口径改写**；p50 <1s；`verdict` 已登记 | ✅ 18/0 |
| `topics-p4.sh` | 四子命令 exit 0；手算扩散 1–2 跳；存根确定性；无网络静态检查；护栏 exit 1；JSON 结构；近词扩展 7 项 | ✅ 30/0 |

### 6. 兼容性声明

> **v1 文件未改动。** `cards.jsonl`、`index/*`、`clusters.json`、`shelves.json`、`subjects.json`
> 及其对应的 v1/v2 脚本在本版本中全程**只读**；v3 的全部产物落在新增的 `topics/` 子目录。
> 现有命令的**行为与默认值不变**（新命令只增不改）；`topics/meta.json` 顶层 `stage` 字段
> **保持 `"P0"`** 以兼容既有验收脚本 `acceptance/topics-p0.sh` 的断言。

**举证方式（mtime 时序，替代不可用的 git diff）**：`~/go/reasonix-scripts` **不是 git 仓库**
（`git rev-parse --show-toplevel` → `fatal: not a git repository`），故改用文件修改时间：
v1 数据文件最后修改时间全部 **≤ 09-18 14:01**（`cards.jsonl` / `shelves.json` / `subjects.json` 13:21，
`clusters.json` / `index/knn_csr.npz` 13:55），而 topics 施工自 **17:27** 起 —— **施工窗口内 v1 文件零写入**。
`meta.json.notes` 亦记录「v1 既有文件全程只读，未改动」。**建议补做**：v1 数据文件 sha256 快照纳入后续验收对比。

### 7. 升级步骤（v2 → v3）

```bash
cd ~/go/reasonix-scripts/lib-catalog && D=~/go/lib-catalog-data

python3 graph_report.py --data $D 2>&1 | tee $D/topics/baseline-p0.txt     # 1) 基线回归（期望 12 跳 ≈0.902）
python3 topic_build.py --data $D --report topics/p1-build-report.json     # 2) 节点（54.3s → 5,187）
python3 topics_meta.py --stage P1 --data $D --report topics/p1-build-report.json
python3 topic_edges.py --data $D                                          # 3) 构边（14.0s → 99,268）
python3 topics_meta.py --stage P2 --data $D --report topics/p2-build-report.json
python3 topics_report.py --data $D --samples 400 --hops 12 --seed 42 \     # 4) 质量报告（三口径）
        --json-out $D/topics/topics-report.json --txt-out $D/topics/topics-report.txt
python3 topics_meta.py --stage P3 --data $D --report $D/topics/topics-report.json

python3 topic_graph.py --data $D search "机器学习 入门"                     # 5) 查询编排（P4）
python3 topic_graph.py --data $D around 56 --hops 2 --top 12 --evidence 8
python3 topic_graph.py --data $D summarize 56 --hops 2

bash acceptance/topics-p0.sh && bash acceptance/topics-p1.sh && \          # 6) 五阶段验收全绿
bash acceptance/topics-p2.sh && bash acceptance/topics-p3.sh && bash acceptance/topics-p4.sh

python3 export_release.py --data $D --topics-only --out <out>              # 7) 导出版（只生成不发布，可选）
```

**前置依赖**：`~/go/pylibs`（numpy/scipy/sklearn；各脚本已自带 `sys.path` 处理）；**无需网络**。

### 8. 回滚步骤

v3 为纯增量，回滚即「删新增、不还原旧」——**v1 文件从未被改动，无需从备份恢复**。

```bash
rm -rf ~/go/lib-catalog-data/topics                                    # ① 删新增数据产物与文档
cd ~/go/reasonix-scripts/lib-catalog
rm -f topic_build.py topic_edges.py topics_report.py topic_graph.py topics_meta.py   # ② 删新增脚本
rm -f acceptance/topics-p{0,1,2,3,4}.sh
# ③ 若曾用 --topics 导出版，删除对应 <out>/topics/ 与其 manifest.topics.json
python3 graph_report.py --data ~/go/lib-catalog-data 2>&1 | tail -30   # ④ 校验 v1 仍完好（12 跳 ≈0.902）
```

> 兜底备份（已存在，本次未使用）：`~/go/reasonix-scripts/lib-catalog.bak-v1-20260918/`、
> `~/go/lib-catalog-release/v1/`（发行副本 + `lib-catalog-data-v1.tar.gz` ~98 MB）。

### 9. 未完成事项 / 待作者裁决

1. 🟡 **`TOPIC_LLM` 默认值口径分歧**：实现为 **`off` 默认**（不渲染、不触网），草案与 handoff §3.4 曾写「默认 `mock`」——**是否改默认待裁决**。
2. 🟡 **data-v2 发行范围**：topics 是否进 v2 发行、以何版本号发布，**由作者决定**；`--topics` 导出版当前**只生成不发布**。
3. 🟡 **`topic_build.py` docstring 与实际默认值不一致**：docstring 写 `--min-df` 默认 8，argparse 实际 **12**。
4. 🟡 **兼容性举证待补强**：工具链目录非 git 仓库，「git diff 证明」需以 sha256 快照替代或先 `git init`。
5. 🟡 **口径类待讨论**（详见 `topics/INTERFACE-PROPOSAL.md`）：`cls` 双产物是否长期保留、出度上限是否放宽、同簇边 0.3 的定位、共现封顶 50、空主题卡 22,573 张、衰减系数 0.86 可否迁移、LLM 隐私边界与预算。
6. ✅ **已闭环**：P3 门槛口径已裁定（② 0.9797 PASS，① 0.8972 并列观察项）；P4 查询编排与近词扩展已落地；五阶段验收脚本齐备且全绿；导出版分支已实现。
