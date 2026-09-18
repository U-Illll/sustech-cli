# 工具链 README 变更记录草案 — v2 → v3（新增 topics 主题图子模块）

> **用途**：并入 `~/go/reasonix-scripts/lib-catalog/README.md` 的「v2 → v3 变更」章节。
> **状态**：**草案**。P0–P3 均已落地跑通，**P3 的 12 跳硬门槛判定为 FAIL**（见 §1.1）；P4 未实现。本文按「已完成 / 已落地待验 / 计划中」如实标注，不做未发生的成绩声明。
> **总原则**：**v3 = 纯增量**。v1/v2 既有文件与既有命令行为**零改动**。

---

## 1. 摘要

| 项 | 内容 |
|---|---|
| 版本号 | v2 → **v3**（建议：`v3` 仅指「topics 增量层」，**不等于** data-v2 发行定稿） |
| 一句话 | 新增 `topics/` 子模块：主题节点图（类型化边 + 证据链）+ 多阶段口径登记 + 质量报告，作为 GraphRAG-lite 的实体-关系显式层 |
| 规模实测 | **5,187** 主题节点（`kw` 4,838 / `cls` 349）、**99,268** 条有向边、**188,512** 行证据链 ✅ |
| 破坏性变更 | **无**。v1 数据文件不改、现有命令不改（新命令只增不改） |
| 完成度 | P0 ✅ / P1 ✅ / P2 ✅（含调参定稿）/ **P3 ✅（覆盖 0.8972，卡在门槛线）** / **P4 ⏳ 未实现（待口径拍板放行）** / P5 = 本文档即交付物之一 |

### 1.1 ⚠️ 必须随本变更记录一并披露的验收结论

> 🔄 **口径警告（关键）**：12 跳覆盖的读数**取决于采样口径**，同一份主产物跨 **20+ 个百分点**：
> **0.7744**（§3.2 字面/`--rank-by weight`）→ **0.8972**（`assoc`·kw 源点）→ **0.9030**（`assoc`·全节点源点）→ **0.9797**（§4-P3 原文「主簇**或分类**」）。
> **统一口径前，「达标与否」无法定论**。下表为 2026-09-18 18:51 快照。

| 验收项 | 实测 | 判定 |
|---|---|---|
| **12 跳同簇覆盖（门槛 ≥0.90）** | `topic_edges.py` 自测 P3 口径（kw 源点）：**0.8972**；全节点源点：**0.9030**；`topics_report.py`（400 kw 源点）复核：**0.8972** | 🟡 **边界（差 0.28pp ~ 刚过线）** |
| 同上 · §3.2 字面口径（`--rank-by weight`） | **0.7744** | 🔴 FAIL |
| 同上 · handoff 的回退方案（出度 20→30） | **0.8553**（且 `weight/30` 平均出度升至 27.8） | 🔴 **FAIL —— 该回退方案实测无效** |
| 同上 · §4-P3 原文「簇 = 主簇**或分类**」 | **0.9797** | ✅ PASS |
| 性能（12 跳加权 BFS 单查询） | p50 **1.99ms** / p95 2.49ms / max 2.97ms | ✅ PASS（门槛 <1s，理想 <300ms） |
| CSR 规格（indptr int64 / indices int32 / weights float32） | 三项 OK，n=5,187 / nnz=99,268 | ✅ PASS |
| 平均出度 ≤20 | avg **19.14**，max 20、median 20 | ✅ PASS |
| 连通性 | 无向分量 4 个；最大 5,184（**99.94%**） | ✅ 正常 |

**本版最重要的一条工程发现**：把 top-20 的**截断排序键**从「权重」换成「关联度」`count/√(freq_u·freq_v)`
（**权重公式一字未改**），覆盖从 **0.7744 → 0.8972**；原因是**按权重排序会让高频词互相垄断 20 个槽位**，
低频节点被单向吸入枢纽后无路可回。**handoff §4-P3 写明的回退（出度 20→30）实测无效**（仅到 0.8553）。
瓶颈诊断：6 跳覆盖 0.8969 ≈ 12 跳 0.8972 → **瓶颈不是跳数**；互惠加成无效。详见 `topics/p2-tuning.md`。

**结论**：主题图**功能已跑通、性能大幅富余**，覆盖指标**处于门槛边界**。是否放行 P4 需先冻结验收口径并由作者拍板。

---

## 2. 新增子模块：`topics/`（主题图 · GraphRAG-lite）

- **节点只收主题**：作者、出版社**不入节点**（不做作者/出版社网络）。
- **查询编排 ≤12 跳**加权 BFS（`w_hop = w_parent × edge_w × 0.86`）。
- **不直接接 LLM**：只留接口存根 `summarize_topic_region(region) -> str`，默认 `TOPIC_LLM` 未设置 = 离线 `mock`。
- **产物目录**：`~/go/lib-catalog-data/topics/`（全部新增，**不动** `cards.jsonl` / `index/*` / `clusters.json` / `shelves.json` / `subjects.json`）。

---

## 3. 新脚本

| 脚本 | 阶段 | 状态 | 说明 |
|---|---|---|---|
| `topic_build.py` | P1 | ✅ 已落地 | 主题节点抽取器（A 簇关键词 / B 标题 TF-IDF top-10 / C CLC `cls2` 三源合一）。正式参数：`--top-per-card 10 --min-df 12 --min-df-cjk 15 --min-nodes 5000 --max-nodes 20000 --seed 42`；实测 **54.3s → 5,187 节点** |
| `topics_meta.py` | 元数据 | ✅ 已落地 | `topics/meta.json` 多阶段口径登记器（`--stage P0\|P1\|P2`）。**不动顶层 `stage`**（保持 `"P0"` 以兼容旧验收脚本），只增量维护 `stages.<STAGE>` / `current_stage` / `updated_at` / `notes_meta` |
| `topic_edges.py` | P2 | ✅ 已落地 | 构边（三类边 + top-20 截断 + 权重归一 + CSR 落盘 + 双口径 variant + 内建 12 跳覆盖自测）。实测 **13.6–14.2s → 99,268 边**；关键参数 `--max-out 20 --cap-count 50 --combine sum --cls-in-cooccurrence auto --variant auto --rank-by assoc`。**本版新增 `--rank-by`（截断排序键，默认 `assoc`）——覆盖 0.7744 → 0.8972 的关键改动**，调参证据落 `topics/p2-tuning.md` |
| `topics_report.py` | P3 | ✅ 已落地 | 主题图质量报告：基础统计 / **12 跳覆盖曲线** / 连通性 / 衰减（`DECAY=0.86`）/ **12 跳单查询性能计时**。支持 `--json` / `--json-out` / `--txt-out` / `--mock`；**CSR dtype 不符即报错退出**。实测总耗时 0.8s |
| `topic_graph.py` | P4 | ⏳ **未落地** | 查询编排 CLI：`search` / `around` / `graph` / `summarize`（对齐 `catalog_vector.py` 子命令风格）。**待 12 跳覆盖口径拍板后放行** |
| `topic_llm.py` | 接口存根 | ⏳ **未落地** | `summarize_topic_region()` 存根（默认 `mock`，不触网） |

> 既有脚本 `build_graph.py` / `graph_report.py` / `catalog_vector.py` / `export_release.py`：**本次未修改**
> （`topics` 只 import 复用 `catalog_vector.tokenize`、`build_graph.STOP_TOKENS/_STOP_RE/merge_bigrams`，属只读依赖）。
> 注：`graph_report.py` 本身**没有 `--json` 参数**（实测），P3 的 JSON 输出由新脚本 `topics_report.py` 提供。

---

## 4. 新数据文件（`~/go/lib-catalog-data/topics/`）

| 文件 | 状态 | 内容 / 实测数字 |
|---|---|---|
| `nodes.json` | ✅ | **5,187** 节点，7 字段（`id/term/type/freq/cluster/cls/sources`）；`id` 连续 0..5186、`term` 全量唯一、无 `freq=0`；freq 中位 29 / max 11,534 |
| `edges.csr.npz` | ✅ | 主口径（auto 选中 **`aug`**，`--rank-by assoc` 定稿运行）：**99,268** 条有向边；`indptr` int64 / `indices` int32 / `weights` float32；avg 出度 19.14、max 20；权重 ∈[0.176, 1.0]，`=1` 占 11.38% |
| `edges.variant-spec.csr.npz` | ✅ | 另一口径（`spec`：仅 kw 参与共现）的边表，供对比/回退 |
| `card_topics.jsonl` | ✅ | **188,512** 行，每行 `{"mms","topics":[id×≤5]}`；空主题卡 22,573（11.97%）；`cls` 不占 top-5 名额 |
| `meta.json` | ✅ | 顶层 P0 遗留键 + `stages.P0` / `stages.P1` / **`stages.P2`**（含 `params`/`counts`/`edge_stats`/`self_test`/`tuning_evidence`/`acceptance_scripts`）+ `current_stage="P2"` / `updated_at` / `notes_meta` |
| `p2-tuning.md` | ✅ | **调参证据**（本次最重要的工程发现）：`weight/20` 0.7744 → `assoc/20` 0.8972（权重公式未改）；handoff 的 20→30 回退实测无效（0.8553） |
| `p1-build-report.json` / `p1-build.log` | ✅ | P1 报告（`params` 含 988 个停用词全表 / `counts` / `freq_stats`）与分阶段日志 |
| `p2-build-report.json` / `p2-build.log` | ✅ | P2 报告（`params` / `counts` / `edge_stats` / `variants` / `self_test`）与日志 |
| `p1-sample50.txt` / `p1-sample50-candidates.txt` | ✅ | 50 词分层抽检（高/中/低频 17/17/16），噪声 2/50 → **噪声率 0.04** |
| `baseline-p0.txt` / `baseline-p0-curve400.txt` | ✅ | 文档图基线（12 跳覆盖 0.902 / 400 簇复跑 0.911） |
| `acceptance-p0.log` / `acceptance-p1.log` | ✅ | 阶段验收输出留痕 |

---

## 5. 新增验收脚本（`acceptance/`）

| 脚本 | 状态 | 断言 | 实测 |
|---|---|---|---|
| `topics-p0.sh` | ✅ | 基线含 12 跳且覆盖数 ∈ [0.882, 0.922]；`meta.json` 合法、顶层 `stage=P0`、`baseline` 指向 `baseline-p0.txt` | **PASS (pass=8 fail=0)**，覆盖 0.902 |
| `topics-p1.sh` | ✅ | nodes.json 合法/规模 ∈[5000,20000]/7 字段/id 连续/term 唯一/无 freq=0/type 仅 kw&amp;cls；与构建报告 7 项计数一致；顶层仍 P0 + `stages.P1` 齐备、噪声率 ≤10% | **PASS (pass=17 fail=0)** |
| `topics-p2.sh` | ✅ 已创建 | 边表 CSR/dtype/出度/证据链与 `stages.P2` 一致性 | 待留痕（`topics/acceptance-p2.log` 尚未生成） |
| `topics-p3.sh` | ⏳ 待建 | 建议：断言 12 跳覆盖与门槛判定（**须先冻结口径**）、性能 p95 < 1s、CSR dtype。**按 kw 源点口径当前 0.8972 → 该断言会 FAIL** | — |

执行方式（可重复运行）：

```bash
cd ~/go/reasonix-scripts/lib-catalog
bash acceptance/topics-p0.sh 2>&1 | tee ~/go/lib-catalog-data/topics/acceptance-p0.log
bash acceptance/topics-p1.sh 2>&1 | tee ~/go/lib-catalog-data/topics/acceptance-p1.log
```

---

## 6. 兼容性声明

**声明原文（建议写入 README）**：

> **v1 文件未改动。** `cards.jsonl`、`index/*`、`clusters.json`、`shelves.json`、`subjects.json`
> 及其对应的 v1/v2 脚本在本版本中全程**只读**；v3 的全部产物落在新增的 `topics/` 子目录。
> 现有命令的**行为与默认值不变**（新命令只增不改）；`topics/meta.json` 顶层 `stage` 字段
> **保持 `"P0"`** 以兼容既有验收脚本 `acceptance/topics-p0.sh` 的断言。

**举证现状（⚠️ 需补强）**：

| 方式 | 可用性 |
|---|---|
| `git diff` 证明 | ❌ **当前不可用**——`~/go/reasonix-scripts` **不是 git 仓库**（实测 `git rev-parse --show-toplevel` 报 `fatal: not a git repository`）。交接文档 §4-P5 原计划的「git 内 diff 证明」无法执行 |
| **mtime 时序证据** | ✅ 可用：v1 数据文件最后修改时间全部 **≤ 09-18 14:01**（`cards.jsonl` 13:21 / `clusters.json` 13:55 / `index/knn_csr.npz` 13:55 / `shelves.json` 13:21 / `subjects.json` 13:21），而 topics 施工自 **17:27** 起（`topic_build.py` 18:11、`topic_edges.py` 18:42、`nodes.json` 18:12、`edges.csr.npz` 18:43）——**施工窗口内 v1 文件零写入** |
| `meta.json` 内声明 | ✅ `meta.json.notes` 已记录「v1 既有文件全程只读，未改动」 |
| **建议补做** | 对 v1 数据文件建立 **sha256 快照**并纳入后续每次验收对比；或先 `git init` 再让 P5 用 diff 举证 |

---

## 7. 升级步骤（v2 → v3）

```bash
cd ~/go/reasonix-scripts/lib-catalog

# 1) 复现 v1 文档图基线（回归确认，实测 17s；期望 12 跳覆盖 ≈0.902）
python3 graph_report.py --data ~/go/lib-catalog-data 2>&1 | tee ~/go/lib-catalog-data/topics/baseline-p0.txt

# 2) 重建主题节点（实测 54.3s → 5,187 节点）
python3 topic_build.py --data ~/go/lib-catalog-data \
        --report topics/p1-build-report.json --sample-out topics/p1-sample50-candidates.txt
python3 topics_meta.py --stage P1 --data ~/go/lib-catalog-data --report topics/p1-build-report.json

# 3) 构边（实测 13.6s → 99,268 边；产出 edges.csr.npz + variant + card_topics.jsonl）
python3 topic_edges.py --data ~/go/lib-catalog-data
python3 topics_meta.py --stage P2 --data ~/go/lib-catalog-data --report topics/p2-build-report.json

# 4) 质量报告（实测 0.8s；只读，不落盘）
python3 topics_report.py --data ~/go/lib-catalog-data --samples 400 --seed 42

# 5) 验收（p0/p1 全绿；p2/p3 脚本待建）
bash acceptance/topics-p0.sh
bash acceptance/topics-p1.sh
```

**不达标时的调参回退（当前 12 跳覆盖 FAIL，需走此路径）**：

```bash
python3 topic_edges.py --data ~/go/lib-catalog-data --max-out 30        # 出度 20 → 30（当前已顶格 20）
python3 topic_edges.py --data ~/go/lib-catalog-data --rank-by weight    # 复现 §3.2 字面口径（默认已改为 assoc）
python3 topic_edges.py --data ~/go/lib-catalog-data --out topics/_exp/tag-01   # 参数搜索隔离输出
python3 topic_edges.py --data ~/go/lib-catalog-data --limit-cards 5000  # 冒烟先行
python3 topic_build.py --data ~/go/lib-catalog-data --min-df 8          # 放宽 P1 阈值扩大节点集
python3 topics_report.py --data ~/go/lib-catalog-data --samples 400 --seed 42   # 重测覆盖
```

**前置依赖**：`~/go/pylibs`（numpy/scipy/sklearn；各脚本已自带 `sys.path` 处理）；无需网络。

---

## 8. 回滚步骤

v3 为纯增量，回滚即「删新增、不还原旧」——**v1 文件从未被改动，无需从备份恢复**。

```bash
# ① 删除新增数据产物与文档草案（v1 数据文件不受影响）
rm -rf ~/go/lib-catalog-data/topics

# ② 删除新增脚本（保留既有 build_graph.py / catalog_vector.py / graph_report.py / export_release.py 等）
cd ~/go/reasonix-scripts/lib-catalog
rm -f topic_build.py topics_meta.py topic_edges.py topics_report.py
rm -f topic_graph.py topic_llm.py                      # P4 落地后按此清理
rm -f acceptance/topics-p0.sh acceptance/topics-p1.sh  # 及后续 topics-p{2,3}.sh

# ③ 校验 v1 仍完好（期望：12 跳覆盖 ≈0.902 / 节点 188,512）
python3 graph_report.py --data ~/go/lib-catalog-data 2>&1 | tail -30
```

**兜底备份（已存在，本次未使用）**：`~/go/reasonix-scripts/lib-catalog.bak-v1-20260918/`（v1 工具链快照）、
`~/go/lib-catalog-release/v1/`（发行副本 + `lib-catalog-data-v1.tar.gz` ~98 MB）、`~/go/lib-catalog-data` 内 v1-165k 备份。

---

## 9. 未完成事项（v3 定稿前必须闭环）

1. 🟡 **验收口径未冻结（最高优先级）**：同一份主产物的 12 跳覆盖读数跨 **0.7744 / 0.8972 / 0.9030 / 0.9797**（取决于采样池与"同簇"定义）。
   需先**冻结一个口径**（建议 `topics_report.py --samples 400 --seed 42`，kw 源点）并写进 `acceptance/topics-p3.sh`，再判定是否放行 P4。
2. **P4 未实现**：`topic_graph.py`（`search`/`around`/`graph`/`summarize`）与 `topic_llm.py` 存根均未创建；10 条真实查询抽测与「`summarize` 不触网」举证未做。
3. ✅ **已闭环**：`stages.P2` 已登记（`current_stage="P2"`，18:50:53），含 `tuning_evidence` 与 `acceptance_scripts`。
4. **验收脚本缺口**：`acceptance/topics-p0.sh` / `topics-p1.sh` / `topics-p2.sh` 已就绪；`topics-p3.sh` 未创建。
5. **P5 发行未做**：`export_release.py` 的 topics 导出版分支未实现（P5 要求「只生成、不发布」）；**topics 是否进 data-v2 发行由作者决定**。
6. **`topic_build.py` docstring 与实际默认值不一致**：docstring 写 `--min-df` 默认 8，argparse 实际默认 **12**（正式基线为 12）。
7. **兼容性举证待补**：工具链目录非 git 仓库，交接文档 §4-P5 的「git diff 证明」需以 sha256 快照替代或先 `git init`。
8. **口径类待讨论**（详见 `interface-proposal.md`）：截断排序键 `--rank-by` 该写进 §3.2 的是哪个（`assoc` 实测更优但偏离字面口径）、同簇边 0.3 的定位（`sum` 加成 / `max` 下失效）、共现封顶 50（max 共现书数 2,052，饱和对仅 1.17%）、空主题卡 22,573 张（11.97%）、衰减系数 0.86 可否从文档图迁移。

---

*草案结束。数字来源：`topics/nodes.json`、`topics/meta.json`、`topics/edges.csr.npz`、`topics/edges.variant-spec.csr.npz`、`topics/card_topics.jsonl`、`topics/p1-build-report.json`、`topics/p2-build-report.json`、`topics/p1-build.log`、`topics/p2-build.log`、`topics/p1-sample50.txt`、`topics/baseline-p0.txt`、`topics/acceptance-{p0,p1}.log`、`acceptance/topics-{p0,p1}.sh`、`topics_report.py` 实跑输出、`lib-catalog-release/v1/manifest.json`。*
