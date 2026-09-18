# 图书馆主题图（GraphRAG-lite）· 施工路线与交接文档

> 2026-09-18 定稿 ｜ 决策：汪子恒 ｜ 执行方：dsh 集群（opencode go 通道）
> 本文件 = 交接书 + 施工蓝图；执行方按 §4 阶段施工、按 §5 派发与验收。

---

## 0. 指令与约束（决策拍板，不可偏离）

1. **仅"主题"作为节点**：作者、出版社**不计入节点**（不做作者网络/出版社网络）。
2. **查询编排跳数上限 = 12 跳**（依据：2026-09-18 会话已验证"12 跳同簇覆盖 90.2%≥90%"的口径，见 §1.3）。
3. **不直接接入 LLM**：社区摘要/查询综合等 LLM 能力**只留接口**（存根 + 开关），等与作者（wormforce）讨论后再决定是否实接。
4. **执行方式**：由 **dsh 集群（opencode go 通道）**完成，**不在主会话执行**；本文件为交接物。

---

## 1. 背景与现状资产

### 1.1 数据集（v2 当前版，全部已就绪）
- 数据目录：`~/go/lib-catalog-data/`
  - `cards.jsonl`：188,512 卡（mms/title/creator/publisher/year/language/type/hc/loc/cn/cls/cls2/src）
  - `index/tfidf.npz`：TF-IDF（词表 338,358 / nnz 3,665,655；标题×2 加权）
  - `index/embeddings.npy`：bge-small-zh-v1.5，188,512×512（已归一化）
  - `index/knn_csr.npz`：语义内链 kNN 图（K=10/书）
  - `index/clusters.npy` + `clusters.json`：400 语义簇（每簇 keywords/exemplars/top_subjects）
  - `shelves.json`（416 书架）、`subjects.json`（38 学科+10 馆藏码）
- 工具链：`~/go/reasonix-scripts/lib-catalog/`（`catalog_vector.py` / `build_graph.py` / `graph_report.py` / `export_release.py` / `compile_cards.py` / `check_completeness.py`）
- 发行包 v1（已发布 PR #24）：`~/go/lib-catalog-release/v1/`

### 1.2 GraphRAG 差距（上一轮分析结论）
已有 = 检索底座（双索引+文档相似图+文档簇）；缺 = ①实体-关系显式层 ②社区报告 ③多跳查询编排。
**本任务的定位：只做①的"主题版" + ③（12 跳编排），②只留接口。**

### 1.3 已验证的图质量口径（2026-09-18，在 188.5k 文档 kNN 图上）
- **12 跳同簇覆盖 90.2%**（400 簇抽样；3 跳 90% 是"44 页小图"口径，188.5k 规模已归一化为 12 跳）
- 无向连通 99.99% 单分量；397/400 簇内单一分量
- 语义衰减：1/2/3 跳余弦 0.730/0.636/0.584（随机基线 0.408）≈ **每跳衰减系数 ~0.86**
- 工具：`graph_report.py`（支持 1/2/3/5/8/12 跳曲线）

---

## 2. 目标与非目标

### 目标（P5 完成时的状态）
- 主题图：**5k–20k 主题节点 + 类型化边（共现/同簇/层级）+ 主题→书证据链**，产出为**增量文件**（`topics/` 子目录）
- 查询编排：**≤12 跳**加权 BFS（可剪枝），输出"主题邻域 + 证据书"
- 全套**验收通过**：主题图上重验 12 跳覆盖 ≥90%、连通正常、衰减合理、性能达标
- 交付：文件 + README + 命令 + 验收报告（供 PR data-v2 或后续讨论）

### 非目标（明确不做）
- 作者/出版社节点与关系
- LLM 实接（只留 `summarize_topic_region()` 等接口存根）
- 不改动已发布 v1 文件；不改动现有命令行为（新命令只增不改）

---

## 3. 设计规范（数据模型）

### 3.1 主题节点（`topics/nodes.json`）
候选池（三源合一，去重归一）：
- **源 A**：400 簇 keywords 去重（现有 3,345 词）
- **源 B**：TF-IDF 高分词——每卡 top 8-12 词（取 `index/tfidf.npz` + `vocab.json`），全局词频 ≥5 本书保留（阈值可调）
- **源 C**：CLC `cls2` 类目（作为"类目主题"，type=cls）

归一规则：去空白/全半角统一/长度 1–16 字/停用词表（含"丛书""文集"等泛词，可调）。
规模控制：目标 5k–20k；超限时按"频次×簇内代表性"截断（阈值写进 meta）。

节点字段：
```json
{"id": 0, "term": "机器学习", "type": "kw|cls", "freq": 320, "cluster": 17, "cls": "TP", "sources": ["A","B"]}
```

### 3.2 边（`topics/edges.csr.npz`：indptr/indices/weights）
- **① 共现边（主）**：同书两主题共现 → w = log1p(共现书数)（封顶 log1p(50)）
- **② 同簇边**：同簇关键词两两 → w = 0.3 × log1p(簇内共现)（降权）
- **③ 层级边**：主题 → cls 类目（w=1.0，单向）
- 出度控制：每节点保留 **top-20** 边（**排序键：关联度** `共现书数 / √(freq_u·freq_v)`，见下方注）；保证与文档图 K=10 同量级的稀疏性，利于 12 跳 BFS
- 权重归一化到 [0,1] 便于衰减计算

> **注（P2 施工回写，2026-09-18）**：截断排序键由"按权重"改为**关联度 `count/√(freq_u·freq_v)`**（`topic_edges.py --rank-by assoc`，现默认；权重公式一字未改，`--rank-by weight` 可复现字面口径）。
> 实测（400 kw 源点 / seed=42 / 分母=本簇节点数 / 平均出度同为上限内）：按权重 **0.7744** → 按关联度 **0.8972**；而 §4-P3 预留的回退"出度 20→30"按权重仅 **0.8553**（**该回退实测无效**）。
> 根因：按权重排序使高频词互相垄断 20 个槽位，低频节点被单向吸入枢纽后无路可回。完整矩阵见 `topics/p2-tuning.md`。

### 3.3 证据链（`topics/card_topics.jsonl` 或并入扩展）
每卡记录其主题：`{"mms": "...", "topics": [id1, id2, ...]}`（top 5，按词权）
查询输出"主题→证据书"时回查；**不改动 cards.jsonl 本体**。

### 3.4 查询编排（`topic` 命令组，扩 `catalog_vector.py` 或新脚本 `topic_graph.py`）
```
python3 topic_graph.py search "机器学习 入门"         # 种子命中（精确/子串/TF-IDF 扩展）
python3 topic_graph.py around <term> --hops 12        # 加权 BFS（≤12 跳），输出分层邻域
python3 topic_graph.py graph <term> --hops 12 --books # 邻域 + 证据书
python3 topic_graph.py summarize <term>               # LLM 接口：默认 mock（打印结构化区域）
```
- 扩散规则：w_hop = w_parent × edge_w × 0.86（对齐实测衰减）；每跳 top-20 边、权重阈值 0.05、访问预算 ≤50k 节点
- 输出：分层列表（hop, term, score, 路径）+ 证据书 top-k；支持 `--json`
- **LLM 接口存根**：`summarize_topic_region(region) -> str`（默认返回模板文；`TOPIC_LLM=off` 时纯结构化输出）——**接口签名与返回约定写进 README，留待作者讨论**

### 3.5 存储与命名（全部增量，不动既有文件）
```
~/go/lib-catalog-data/topics/
  nodes.json          # 主题节点表
  edges.csr.npz       # CSR 边（含 weights）
  card_topics.jsonl   # 卡的 top-5 主题
  meta.json           # 口径：阈值/规模/统计/衰减系数
```
发行（P5 决定）：`export_release.py` 增 `topics/` 导出分支 → 生成 `topics_*.bin/json` 瘦身格式（沿用 int8/CSR 风格）；**是否进 data-v2 发行由作者讨论后定**。

---

## 4. 施工路线（P0–P5）

> 每阶段独立验收后才进入下一阶段；全部在 dsh 集群执行；主会话只做验收。

### P0 · 对齐与骨架（预计 0.5–1h）
- 步骤：① 跑 `graph_report.py --data ~/go/lib-catalog-data` 复现基线（记录 12 跳/连通/衰减数）② 读工具链 README 与 build_graph.py 复用 `tokenize()` ③ 建 `topics/` 骨架 + acceptance 脚本骨架
- **验收**：基线报告与 §1.3 一致（12 跳覆盖 ≈90.2%±2%）；acceptance 骨架可跑
- 坑：`~/go/pylibs` 的 numpy 环境（脚本已带 sys.path 处理）；直接 `--data` 指向数据目录

### P1 · 主题节点构建（预计 2–4h）
- 步骤：① 实现抽取器（源 A/B/C）② 归一与频控 ③ 节点规模检查（5k–20k，超出调阈值）④ 抽检 50 词（噪声率 <10%）
- 产出：`topics/nodes.json` + 统计片段
- **验收**：节点数达标；抽检噪声率；`nodes.json` schema 与 §3.1 一致
- 坑：标题切词复用 `catalog_vector.tokenize`（与 TF-IDF 同源，避免口径漂移）

### P2 · 边构建（预计 2–4h）
- 步骤：① 共现对计数（遍历 188.5k 卡的 top-5 主题，`defaultdict(Counter)` 或哈希对）② 三类边合成 + top-20 截断 + 权重归一 ③ CSR 落盘
- 产出：`topics/edges.csr.npz`、`topics/card_topics.jsonl`、`meta.json`
- **验收**：平均出度 ≤20；边数/节点数分布合理；热门节点（如"机器学习"）邻域抽检相关
- 坑：内存（188.5k×5 主题对的计数用 dict 即可，勿用稠密矩阵）

### P3 · 图验收（预计 1–2h）
- 步骤：① 扩展 `graph_report.py` 出主题图版：**12 跳覆盖**（主题的"簇"=主簇或分类，抽样 ≥100 种子）、连通性、衰减曲线、出度分布 ② 性能：12 跳单查询 <1s（目标 <300ms）
- **验收（硬门槛）**：**12 跳覆盖 ≥90%**（口径对齐 §1.3）；衰减曲线不劣于 0.86^hop 理论线太多；性能达标
- 坑：主题图规模小于文档图时，如 12 跳覆盖 <90% → 调 P2 出度（20→30）或 P1 阈值后重跑（不达标不进 P4）

### P4 · 查询编排（预计 2–4h）
- 步骤：① 实现 `topic_graph.py`（search/around/graph/summarize）② 剪枝与预算 ③ LLM 接口存根（`TOPIC_LLM=off` 默认）④ 10 条真实查询抽测（"机器学习 入门""量子 科普"等）
- 产出：CLI + 抽测报告
- **验收**：抽测 10 条全部返回"相关邻域+证据书"（人工判定相关率 ≥8/10）；`summarize` 默认 mock 可跑且不触网
- 坑：种子命中（查询词不在节点表时退化为 TF-IDF 近词扩展——必测）

### P5 · 交付与发行决策（预计 1h）
- 步骤：① 写 `topics/README.md`（schema+命令+接口签名）② `export_release.py` 增 topics 导出版（只生成，不发布）③ 汇总验收报告 ④ 更新工具链 README 的 v2→v3 变更记录
- **验收**：文档齐、脚本可复跑（acceptance 全绿）、**未触碰 v1 既有文件**（git 内 diff 证明）
- 交付物清单：`topics/README.md`、验收报告、导出版样例、给作者的"接口协议草案"1 页（LLM 接口约定）

---

## 5. dsh 派发与验收流程

### 5.1 通道与开工检查
- 派发接口：dsh-bridge MCP（`dsh_session_create` → `dsh_prompt` → `dsh_history`/`dsh_sessions` 轮询）
- **开工前必查**：`dsh_status` → 期望 `gateway.active=primary`（= opencode go 通道，`http://127.0.0.1:8791/v1`）、`dshWeb.ok=true`
- 通道说明：网关 primary=opencode go（本地桥 8791）；**backup 仅兜底**（DeepSeek 官方）。若 primary 挂：先修桥，勿降级硬跑
- 会话建议：`agentPreset=minimal`（维护建议值）；工作目录 `~/go/reasonix-scripts/lib-catalog`

### 5.2 任务书模板（五段式，逐阶段派发）
```
【已知】本文件 §1/§3 的资产坐标、口径、设计规范 + 上一阶段产出（附路径）
【目标】<本阶段目标，如 P1：产出 topics/nodes.json，5k-20k 节点>
【死步骤】1) … 2) … 3) …（给到命令/脚本级，不让模型自由发挥）
【约束】不改 v1 文件；不接 LLM；不用网络（除非明说）；产出落 topics/ 目录
【汇报格式】结论三段式：产出物路径 + 关键数字（节点数/噪声率/耗时）+ 未决问题
```

### 5.3 验收协议（主会话执行）
- 每阶段完成后：主会话跑对应 acceptance（P0-P5 各一段 bash/脚本，落 `lib-catalog/acceptance/topics-pN.sh`）
- 验收不过 → 把失败证据回填给 dsh 会话（`dsh_prompt`）要求修复，直至绿
- 记录：每阶段验收输出存 `topics/acceptance-pN.log`

### 5.4 P0 任务书（可直接复制派发）
```
【已知】工作目录 ~/go/reasonix-scripts/lib-catalog；数据 ~/go/lib-catalog-data（188.5k 卡、index/、clusters.json、shelves.json、subjects.json）；基线口径见交接文档 §1.3（12 跳覆盖 90.2%、99.99% 连通、衰减 0.730/0.636/0.584）；工具链 README 在同目录。
【目标】完成 P0 对齐与骨架：① 复现基线图报告 ② 建立 topics/ 目录骨架 ③ acceptance 脚本骨架（acceptance/topics-p0.sh）。
【死步骤】
1) cd ~/go/reasonix-scripts/lib-catalog && python3 graph_report.py --data ~/go/lib-catalog-data 2>&1 | tail -40 > /tmp/p0-baseline.txt；检查其中 12 跳覆盖 ≈90.2%（±2%）
2) mkdir -p ~/go/lib-catalog-data/topics && 写入 topics/meta.json 初值（{"stage":"P0","baseline":"/tmp/p0-baseline.txt"}）
3) 写 acceptance/topics-p0.sh：断言 /tmp/p0-baseline.txt 含 "12" 与覆盖数、topics/ 目录存在
4) 按三段式汇报
【约束】不访问网络；不改动 v1 既有文件（只新增 topics/ 与 acceptance/）；不下结论前先贴数字
【汇报格式】产出物路径 + 关键数字（12 跳覆盖/耗时）+ 未决问题
```

---

## 6. 风险与回退

| 风险 | 缓解 | 回退 |
|---|---|---|
| 主题词噪声多 | 频控+簇内代表性截断+50 词抽检 | 调阈值重跑 P1 |
| 节点规模超限 | 频次阈值/簇代表性双门限 | 目标带 5k–20k，写进 meta 供调 |
| 12 跳覆盖不达标 | P2 调出度（20→30）、P1 调阈值 | **不达标不进 P4**（硬门槛） |
| BFS 性能差 | top-20 剪枝+权重阈值+预算 | 降跳数上限需**回拍板**（≤12 是约束，只许优化算法） |
| 内存/耗时 | dict 计数、分块处理（参考 build_graph.py --block） | 冒烟模式 --limit N 先行 |
| 误触既有数据 | 全部新文件落 topics/；验收含"v1 diff 证明" | `~/go/lib-catalog-data` 有 v1-165k 备份与 release 副本 |

---

## 7. 附录：坐标与命令

- 数据：`~/go/lib-catalog-data/`（cards.jsonl、index/、clusters.json、shelves.json、subjects.json）
- 工具：`~/go/reasonix-scripts/lib-catalog/`（python3 直跑；依赖 `~/go/pylibs`）
- 基线复现：`python3 ~/go/reasonix-scripts/lib-catalog/graph_report.py --data ~/go/lib-catalog-data 2>&1 | tail -30`
- 验收参考：`graph_report.py` 头部注释（1/2/3/5/8/12 跳口径定义）
- 本次决策依据：会话 `20260918-050441…cecebda25d8d4d79` msg#264-315（12 跳 90.2% 验收记录）；
  归档会话 `~/.reasonix-local/archive/20260918-140608.096.jsonl`（图质量讨论）
- 发行现状：v1 已通过 PR #24 提交 `wormforce/sustech-cli`（topics 是否进 v2 待作者讨论）
- dsh 运维：`Desktop/dsh-reasonix体系-操作与运维文档-20260913.md`（重启/巡检/红线）

---
*完 — 交接执行方（dsh 集群）从 §4 P0 开始；任何与约束 1–4 冲突的发现，先停下回拍板。*

---

## 8. 施工结果（P0–P5 执行注记，2026-09-18 收官）

> 本节为**执行方回写**，不修改 §0–§7 原文结构。口径细节以 `topics/meta.json` 的 `stages.P0–P4` 为准，验收全链见 `topics/ACCEPTANCE-REPORT.md`。

| 阶段 | 状态 | 关键结果（实测） | 证据 |
|---|---|---|---|
| P0 对齐与骨架 | ✅ | 基线复现：188,512 节点 / K=10 / 1,885,120 边 / 12 跳同簇覆盖 **0.902** / 连通 3 分量 | `topics/baseline-p0.txt`、`acceptance/topics-p0.sh` PASS 8/0 |
| P1 主题节点 | ✅ | **5,187** 节点（kw 4,838 + cls 349）；top_per_card=10、min_df=12、min_df_cjk=15、停用词 988；抽样噪声 **2/50 = 4%** | `topics/nodes.json`、`p1-build-report.json`、`topics-p1.sh` PASS 17/0 |
| P2 边构建 | ✅ 含 1 处口径回写 | **99,268** 边、平均出度 **19.138**（≤20 规格）、权重 0.176–1.0；distinct 共现对 330,426（kw-kw 245,779）、同簇加成 9,167、层级边（主题→CLC cls2）4,832；`card_topics.jsonl` 188,512 行 | `topics/edges.csr.npz`、`p2-build-report.json`、`p2-tuning.md`、`topics-p2.sh` PASS 27/0 |
| P3 图验收（口径终裁） | ✅ PASS | 12 跳覆盖三口径：①仅主簇 **0.8972**（并列观察项）/ ②主簇∪类目 **0.9797**（**硬门槛口径，§4-P3 原文「主簇或分类」**）/ ③无向闭包 0.9200；单查询 **p50 1.99ms**（门槛 <1s）；连通 4 分量（最大 5184 = 99.94%） | `topics/topics-report.json`、`topics-p3.sh` PASS 18/0；裁定全文见 `meta.json#stages.P3.verdict` |
| P4 查询编排 | ✅ | `topic_graph.py` 四命令 `search/around/graph/summarize`；扩散 `w_hop = w_parent × edge_w × 0.86`（阈值 0.05、预算 50k、hops ≤12）；**近词扩展**（§4-P4 坑位要求项）以 TF-IDF（与 `catalog_vector` 同源）检索相关书→聚合其主题实现；15 例抽测全 exit 0 | `topics/p4-smoke.txt`、`topics-p4.sh` PASS 30/0 |
| P5 交付与发行决策 | ✅ 只生成不发布 | `topics/README.md`、`INTERFACE-PROPOSAL.md`、`ACCEPTANCE-REPORT.md`；`export_release.py --topics-only/--topics` 增 topics 导出版（CSR + uint8，样例 4.00 MB） | `topics/export-sample/v1/`、工具链 `README.md` 的 v2→v3 章节 |

**三处需作者知悉的裁定/偏离**（均在 `meta.json` 留痕，未擅自改规格）：
1. **§3.2 截断排序键**：由"按权重"改为"按关联度"（权重公式未改）——否则 P3 硬门槛不达标（见 §3.2 注）。
2. **§4-P3 门槛口径**：按原文「主题的簇 = 主簇**或分类**」判定 **PASS（0.9797）**；「仅主簇」0.8972 作为严格观察项并列报告，未静默替换口径。
3. **§3.2 层级边目标**：cls 节点词表是 §3.1 源 C 的 **CLC cls2**，而节点表 `cls` 字段为 cls1（无对应节点），故层级边目标按卡级证据投票取**众数 cls2**。

**未决（留给作者/后续）**：topics 是否进 data-v2 发行；出度上限 20 是否放宽（实测为弱杠杆）；共现封顶 50；衰减系数 0.86 源自 v1 文档图；22,573 张卡（12.0%）无 top-5 主题；LLM 接口仍为存根（未接模型）。

### 8.1 R1 / R2 轮结果追加注记（2026-09-18，**只追加，不改 §8 上表原文**）

> ⚠️ **上表（§8）是 19:1x 的 P0–P5 收官快照，其中的数字已被其后两轮修复取代。**
> 本节追加 R1（终审整改）与 R2-A/B/C（审计整改）的终值；**凡与上表冲突，以本节为准**。
> 机读登记：`topics/meta.json#stages['R2-A'|'R2-B'|'R2-C'|'P5']`；逐条证据：`topics/ACCEPTANCE-REPORT.md` §10（R1）与 **§11（R2）**。

| 量 | §8 上表（19:1x） | **R2-C 终值** | 变动原因 |
|---|---|---|---|
| 节点 / kw / cls | 5,187 / 4,838 / 349 | **5,507 / 5,158 / 349** | R2-A 修 F2/F2b（`ext_df` 双计数）、F1/F1b（截断排序键浮点退化） |
| 边 / 平均出度 | 99,268 / 19.138 | **105,414 / 19.142** | 同上 + 节点增加 |
| 层级边（登记/实存） | 4,832 / **4,823（缺 9）** | **5,151 / 5,151（零丢失）** | R2-A 修 **D1**（层级边被 top-20 截断吃掉） |
| 权重 中位 / 均值 | 0.4093 / 0.5187 | **0.2292 / 0.3656** | R1 ①（共现去重）后重算 |
| 12 跳 ①仅主簇 | 0.8972 | **0.9246** | R1+R2 累积改善 |
| 12 跳 ②主簇∪类目（**硬门槛**） | 0.9797 | **0.9927**（≥0.90 **PASS**） | 同上 |
| 12 跳 ③无向闭包 | 0.9200 | **0.9286** | 同上 |
| 单查询 p50 | 1.99 ms | **2.580 ms**（门槛 <1s） | R2-C 重跑（`perf_samples=50`） |
| 最大连通分量 | 5,184（99.94%） | **5,504（99.9455%）** | 节点增加 |
| 空主题卡 | 22,573（12.0%） | **21,607（11.46%）** | 主题池扩大，可命中卡增多 |
| 边型可辨识性 | 仅能靠 `w=1.0` + 目标 `type=cls` **近似**识别③层级边 | **新增 `types` uint8 位图**（`{1,3,5,7}`），三类边**精确可还原** | R2-C 实施 AUDIT-EDGETYPE 方案 a |
| 导出版 | 8 文件 / 4.00 MB | **9 文件 / 4,255,902 B**（+`edges_types.u8.bin`） | R2-C 重建 + 修 AUDIT-EXPORT **E1**（随包 meta 与随包数据同源） |
| 验收断言 | P0–P4 计 100 项（P2 27 / P3 18 / P4 30） | **六脚本 147 项全绿**（P0 8 / P1 17 / **P2 35** / P3 21 / P4 38 / P5 28） | R1 加固 + R2-C 新增 `[4b]` 边型断言 |

**R2-B（检索层，`topic_graph.py`）追加结果**：ASCII 大小写归一（旧代大写 `cls` 码搜不到）；`search` 排序引入特异性 `w_spec=log1p(freq)/√freq`（rank-1 泛词 7/10 → **10/10**）；证据取样改「同簇闸门 + 一跳近邻覆盖度 + 多卷软去重」→ 相关性 **P1 4/10→8/10、P2 5/10→8/10**（≥8/10 达标）。

**§8「未决」清单的更新**：
- 「22,573 张卡（12.0%）无 top-5 主题」→ **21,607 张（11.46%）**，仍未消除（`README.md` §8-R6）。
- 「出度上限 20 / 共现封顶 50 / 衰减 0.86」三项**仍待作者拍板**，未改。
- 「topics 是否进 data-v2 发行」**仍未定**；R2 全程未触碰 v1 发布包 `lib-catalog-release/`（末次改动 14:01）。
- **本轮新增未决**：顶层 `stage` 兼容冻结的解除、`topics_meta.py --stage choices` 扩展、`meta.json` 缩进统一（见 `topics/README.md` §8-R15/R16/R17 与 `ACCEPTANCE-REPORT.md` §11.4「未做（R3 待办）」）。

> **只读约束遵守**：R1/R2 均未改动 v1 既有文件（`cards.jsonl` / `index/*` / `clusters.json` / `shelves.json` / `subjects.json`）；
> R2-C 已把 `cards.jsonl` 的 sha256 登记进 `topics/export-sample/v1/topics/manifest.topics.json#snapshot.source_sha256`，首次给出可对账的内容指纹。
> 本节由 **R2-D 会话**（AUDIT-META，文档与登记同步）追加；备份 `TOPIC-GRAPH-HANDOFF-20260918.md.pre-r2d`。
