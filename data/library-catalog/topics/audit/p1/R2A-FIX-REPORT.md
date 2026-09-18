# R2-A · 数据层修复与重建报告（F2/F2b + F1/F1b + D1）

- **范围**：`topic_build.py`（P1）／`topic_edges.py`（P2）／`nodes.json`／`edges.csr.npz`／`meta.json`（v1 数据只读，未触碰）
- **依据**：`topics/audit/p1/REPORT.md`（F1/F1b/F2/F2b）、`topics/audit/num/REPORT.md §4`（D1）
- **验证脚本**：`topics/audit/p1/verify_r2a.py`（全量 60 s，只读主体产物，写 `audit/p1/evidence/r2a-*.json`）
- **备份（修复前）**：`nodes.pre-r2.json`、`edges.csr.pre-r2.npz`(+NOTE)、`card_topics.pre-r2.jsonl`、`p1/p2-build-report.pre-r2.json`、`edges.variant-spec.csr.pre-r2.npz`、`p1-sample50-candidates.pre-r2.txt`

## 1. 修复内容

| ID | 文件 / 位置 | 修法 | 选择理由 |
|---|---|---|---|
| **F2/F2b** | `topic_build.py` Pass 1 与 Pass 1.5 的 `ext_df[e] += 1`（原 L469/L494） | A 源扩展证据与 B-CJK 扩展证据**合并为同一趟、共用同一 `ext_seen`** ⇒ 同卡同一扩展词只计一次 | 直接消除"卡片级比值 >1"的不可能性；不动阈值与公式 |
| **F1/F1b** | `topic_build.py` entries 排序键（原 L652 `score = f * rep`） | `_score` 改为 `freq×rep` 的**精确整数值**（≡ `max(cl_counts)` = 主导簇卡数） | 二选一取「字面语义的精确实现」：`max_cc` 本就是 `freq×rep` 的精确值，精确求值既保住 README/代码语义，又消除 1 ulp 噪声对 `(-freq, term)` 次级键与截断边界的支配；改 README 保留浮点键则噪声问题依旧 |
| **D1** | `topic_edges.py` `topk_csr` 去重键序（原 L124） | 同 `(u,v)` 去重改为**取最大排序键 tie，再取最大权重**，最后取先出现行 | 令层级边保住置顶键 `tie=nfreq×1e9`，实现文档早已声称的"结构边不被截断"；权重公式与截断口径不变 |

## 2. 修复前后对比（全部实测）

| 指标 | pre-r2 | R2-A | Δ |
|---|---|---|---|
| P1 节点 / kw / cls | 5,187 / 4,838 / 349 | **5,507 / 5,158 / 349** | +320 / +320 / 0 |
| 三源分布（A／A+B／B／C） | 403 / 954 / 3,481 / 349 | **476 / 1,010 / 3,672 / 349** | +73 / +56 / +191 / 0 |
| `source_a_kept` / `dropped_embedded` | 1,518 / 894 | **1,647 / 765** | **+129 / −129** |
| `source_b_accepted` / `dropped_cjk_contained` | 4,435 / 1,801 | **4,682 / 1,563** | +247 / −238 |
| `a_containment_ratio_max` / `ratio>1.0 词数` | 2.0000 / 580 | **1.0000 / 0** | 卡片级比值回到 ≤1.0 |
| 排序键（交付顺序 = `sort(-max_cc,-freq,term)`） | 否（2,711/5,187） | **是（5,187/5,187）** | 浮点噪声消除 |
| 边数 / 平均出度 / 孤立点 | 99,268 / 19.138 / 3 | **105,414 / 19.142 / 3** | +6,146 |
| 层级边 登记 / **实存** / 缺 | 4,832 / **4,823** / 9 | **5,151 / 5,151 / 0** | 登记=实存 |
| 12 跳覆盖（kw／全节点） | 0.9188 / 0.9234 | 0.9246 / 0.9257 | +0.006 / +0.002 |
| 耗时 P1 / P2 | 54.3 s / 13.9 s | 34.0 s / 14.7 s | P1 因少一次 ext 累计而变快 |
| sha256 | nodes `9f5437d7…` / edges `509c285a…` | nodes `ba1ff260…` / edges `f938b01b…` | 见 `meta.json#stages['R2-A'].before_after` |

> 节点 id 迁移：5,187 个共有词中 **5,115 个（98.61%）** id 变化（排序键修复的必然结果）；头部前 6 位未变（经济=0 / design=1 / D9=2 / 金融=3 / 经济学=4 / F8=5），P4 文档样例中的 `SRC=0(经济) DST=4(经济学)` 仍成立。

## 3. 验证证据（V1–V5，`verify_r2a.py`）

| 项 | 结果 |
|---|---|
| V1 产物不变量 | 5,507 ∈ [5k,20k]；schema 7 字段 0 违规；id 连续；term 唯一；报告 A1 一致 ✓ |
| V2 F2/F2b | 独立复现：ratio_max **2.0000→1.0000**，>1.0 的词 **580→0**；被误剔词集 **F=129，129/129 已回归 nodes.json**；A 源漏斗 Δ(+129/−129) 与 \|F\| 精确一致 ✓（样本：`精通` 1.357→0.743、`二次` 1.148→0.620、`信集` 1.043→0.667、`国保` 1.171→0.800） |
| V3 F1/F1b | 独立重算：`freq` 不符 **0/5,507**、`cluster` 不符 **0**；交付顺序 == `sort(-max_cc,-freq,term)` ✓ |
| V4 D1 | 独立复算众数 cls2：pre-r2 登记 4,832 / 实存 **4,823**（缺 9，复现 AUDIT-NUM D1）→ r2a 登记 5,151 / 实存 **5,151**（缺 0）✓；`variant-spec` 两版均完整（4,832/4,832 → 5,151/5,151） |
| V4 抽样 | 抽验 3 条普通边（经济-经济学 / 经济-economics / 经济-宏观）权重与 pre-r2 **逐位相同** ✓ |
| V5 D1 隔离实验 | 用**同一份 pre-r2 nodes** + 修复后代码重跑：边数仍 99,268，**共同边权重差异 0**，新增 **9 条 = 9 条缺失层级边（w=1.0）**，消失 9 条 = 各源点被顶替的尾部边（kw→kw 8 条 / kw→cls 1 条）✓ → D1 净效应被精确隔离 |
| 验收脚本 | `topics-p0.sh` 8/8、`topics-p1.sh` 17/17、`topics-p2.sh` 30/30 **PASS**；`topics-p3.sh` 21/21、`topics-p4.sh` 38/38 亦 PASS（结构/护栏类断言） |

## 4. 未决问题（交 R2-B）

1. **P3/P4 登记指标未重算**：`meta.stages.P3`（覆盖率 0.8972 / 门槛 0.9912 / 衰减）与 `stages.P4` 样例、`release_files/*`、`export-sample/*`、manifest 哈希均基于 pre-r2 图，本轮仅标注 stale（验收脚本结构性通过，数值未复核）。
2. **噪声率 0.04 未重判**：`p1-sample50.txt` 为 pre-r2 判定件（10 列，缺数值证据列）；新候选件已按新 id 空间重生于 `p1-sample50-candidates.txt`（pre-r2 版另存 `.pre-r2.txt`），需重新分层抽样判定。
3. **AUDIT-NUM §5 卡集口径**：`freq/cluster/cls` 的确切卡集未落档（cluster 46 / cls 88 节点与出厂证据链不自洽），本轮未处理 —— 它同时喂 ② 同簇加成与 P3 冻结门槛。
4. **AUDIT-P1 其余发现未修**：F18（`source_a_kept` 含 161 个被 entry 段英文门二次过滤的词，无计数器）、F9/F17（英文闸门 OR 退化、114 节点 `cls` 簇级兜底、7,118 张卡无 cls1）、F8（`min_df` 只约束 B 源）。
5. **层级边目标为派生值**：众数 cls2 随卡 top-5 变化而漂移（实测 `经典` TP3→I2），建议在文档中明确其"证据投票派生值"性质，避免被当作稳定登记值。
