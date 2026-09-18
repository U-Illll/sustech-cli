# AUDIT-META · meta 登记链 / 哈希链 / 引用一致性 审计报告

> 🟢 **R2-D 收口状态（2026-09-18 22:0x）**：本报告的 ❌14 / ⚠️20 已经 R1–R2 三轮修复 + R2-D 文档同步**全部处置**。
> 复跑 `python3 audit_meta.py --data /home/wzh/go/lib-catalog-data` → **✅87 / ⚠️4 / ❌0**。
> 剩余 4 项 ⚠️ 均为**已登记的设计性残留**（顶层 `stage` 双轨冻结 ×2、一处不可补全的历史哈希缩写、包内 meta 快照语义），
> 已登记为 R3 待办。逐项收口证据见 `ACCEPTANCE-REPORT.md` **§11**（含 §11.5 三项新发现 N1–N3 与 §11.6 四项残留）。
> 审计器本轮亦升级：README 承诺键改为**动态解析**、哈希扫描**区分历史沿革表**、因果倒挂可**证良性**
> （三数组逐字节比对 / 隔离复跑比对，见 `repro-evidence.json`）。

- 脚本：`topics/audit/meta/audit_meta.py`（**只读**：不 import / 不 exec / 不改动任何被审对象，仅 `json.load` + `hashlib`）｜产物：`audit-results.json`、`snapshot.json`
- 复跑：`python3 topics/audit/meta/audit_meta.py --data /home/wzh/go/lib-catalog-data`（~4s，确定性）
- 审计时点快照（sha256 前 16 位）：`meta.json` **c907c84126874cb3**@20:01:04 ｜ `ACCEPTANCE-REPORT.md` 65152 B@20:01:04 ｜ `README.md` 47164 B@19:55:23 ｜ `edges.csr.npz` 509c285aac82b9a1 ｜ `card_topics.jsonl` 19:45:24 ｜ `p2-build-report.json` 19:45:26
- 覆盖量：**✅66 ⚠️20 ❌14**（断言 115 项 = A 深审 54 / B 哈希 29 / C 引用 18 / D 因果 14；B 轴另执行 **47 次 sha256 实地重算**）

## 0 结论摘要

| 轴 | 结论 | 关键数字 |
|---|---|---|
| A `meta.json` 登记链 | **数值可信、结构可信；末端缺失 + 文档承诺失真** | 五段契约键 **11/8/10/12/10 全齐**；与 P1/P2/P3 报告逐项比对 **0 漂移**（params 12+25、counts 20+16、edge_stats 11、self_test 5、P3 全部派生值）；但 **stages 无 P5 段**、README 承诺 3 个键不存在 |
| B 哈希链 | **包内自洽；报告登记表已过期，链在时间轴上断裂** | 报告 31 项 → **26 逐字节一致 / 5 漂移**；导出 manifest **8/8 哈希+size 双一致**，`total_bytes` 4,004,106 求和相符；`baseline_sha256` 一致 |
| C 文档互引 | **定稿文档引的是 R1 前快照，与产物现值为两套数** | README §9 **5 处数字 + 断言计数全为 R1 前值**；ACCEPTANCE-REPORT §0/§7 与 §10 自相矛盾（30/30 vs 142） |
| D 时间线因果 | **产物链正确；1 处脚本-产物错配** | 产物因果链 **8/8 成立**（`card_topics`→`edges` +2.5s、`edges`→P3 +49.1s、`edges`→README +596.8s 等）；脚本先于产物 **3 条中 2 条成立**，`topic_build.py` 晚于 `nodes.json` **−3064.6s** |

## 1 ✅ 通过项（要点）

- **A2 双写未漂移**：顶层 11 个 P0 遗留键与 `stages.P0` **逐字段相等**（镜像设计实现无误）。
- **A3 契约完整**：P0–P4 五段必填键 11/8/10/12/10 **全齐**；每段 `stage` 自指正确。扩展键：P1 4 个、P2 4 个（含 `r1_fix`）、P3 1 个（`caliber_freeze`）、P4 1 个（`r1_1_fix`）。
- **A5 登记值 = 报告值（0 漂移）**：P1 `params`12/`counts`20；P2 `params`25/`counts`16/`edge_stats`11/`self_test`5；P3 `config`7/`definitions`7 + `coverage` 4 值 + `performance` 2 值 + `connectivity` 3 值 + `decay` 3 值；`generated_at` 与 `seconds` 亦逐段同刻同值。
- **A5/A6 裁定自洽**：三口径 `pass` 与硬门槛 0.90 逐项复算自洽（①0.9188 ②0.9912 ③0.9200）；`current_stage="P4"` 既是 `stages` 成员、又确为 `generated_at` 最新段，且与 `updated_at`/文件 mtime 三者同刻。
- **A9 指针可达**：各段 `report_file` / `tuning_evidence` / `artifacts` 逐项实存。
- **B2 导出包**：`manifest.json` **8/8** 项 sha256+size 双一致，`total_bytes` 4,004,106 = 逐文件求和；内层 `manifest.topics.json` **7/7** 自洽；`nodes 5187 / edges 99268` 与 P1/P2 登记一致。
- **B3**：`baseline-p0.txt` 复算 = `stages.P0.baseline_sha256`（`ff2a32ad0076…`）。
- **D 因果**：`card_topics.jsonl` → `edges.csr.npz`（+2.5s）→ `topics-report.json`（+49.1s）→ 导出包（+17.9s）→ `README.md`（+596.8s）全序成立（**8/8**）；`topic_edges.py`@19:42:22 → `edges.csr.npz`@19:45:26（+184.2s）成立，R1 修复后确有重建；`topics_report.py` → `topics-report.json` 亦成立。

## 2 ❌ 不通过项（14）

| # | 轴 | 项 | 证据 / 期望 vs 实际 |
|---|---|---|---|
| D1 | A7 | **登记链止于 P4，无 `stages.P5`** | P5 已实际交付（`docs-draft/` 3 件、`export-sample` 8 文件、`INTERFACE-PROPOSAL.md`），且 `acceptance/topics-p5.sh` 实存、**28 断言 PASS**；但 `stages` 只有 P0–P4 → 读者会认为流程未到交付 |
| D2 | A4 | README §2.4 承诺 `stages.P2.p3_gate_note` | 该键在 `meta.json` 中**不存在** |
| D3 | A4 | README §2.4 承诺 `stages.P4.gate_note` / `p5_note` | 两键均**不存在**（P4 实际扩展键只有 `r1_1_fix`） |
| D4 | C1 | README §2.4 登记 `updated_at` | README `2026-09-18T19:13:59+0800` vs 实际 `20:01:04+0800` |
| D5 | C2 | README §2.4 引 `self_test` | README `0.8972 / 0.9030`（R1 前）vs 报告 `0.9188 / 0.9234`（R1 后） |
| D6 | C3 | README §9 验收断言数 | README `8/17/27/18/30` vs `acceptance-p*.log` 实测 `8/17/30/21/38/28`（=142） |
| D7 | C4 | README §9 `w=1 占 11.38%` | vs `p2-build-report.edge_stats.w_eq_1_share = 0.0807`（8.07%） |
| D8 | C5 | README §9 `p50 1.986ms / p95 2.395ms` | vs `topics-report.performance` `2.6229 / 3.3051`（`perf_samples=50`）—— 无对应产物可对账 |
| D9 | C5 | ACCEPTANCE-REPORT「p50 更正为 1.986ms」 | 与上同一问题：最终 `topics-report.json` 为 2.6229ms |
| D10 | C6 | README 阶段表 P2 实测耗时 14.0s | vs `p2-build-report.seconds = 13.9` |
| D11 | C7b | README §9 索引错引 `topics/manifest.topics.json` | 该路径不存在；实际 `topics/export-sample/v1/topics/manifest.topics.json`（同文第 174 行引用正确 → **文档内自相矛盾**） |
| D12 | C9 | ACCEPTANCE-REPORT **内部**断言计数矛盾 | §0.2 / §7.1 仍写 P4「**30/30** 全过」，§10.7 写「六脚本 **142** 项全绿（P4 38）」；`acceptance-p4.log` 实测 `pass=38` |
| D13 | D2 | `topic_build.py` 无法解释 `nodes.json` | 脚本 mtime 19:03:18 **晚于**产物 18:12:14（−3064.6s）→ 现存版本无法逐字节复现 `nodes.json`；该改动在报告 §5.5 已登记为授权改动，但**产物不可再生的风险未被声明** |

## 3 ⚠️ 风险项（20 条归并为 7 类）

| # | 轴 | 风险 | 说明 |
|---|---|---|---|
| W1 | A7 | **顶层 `stage="P0"` 与 `current_stage="P4"` 双轨** | `stage` 为兼容 `topics-p0.sh` 的 `stage=="P0"` 断言而永久冻结；6 处 acceptance 脚本把该值硬编码。任何只读 `meta["stage"]` 的消费者（含未来集成方）会把已到 P4/P5 的产物判为 **P0**，且元数据**无法自我描述真实阶段** |
| W2 | A5/C10 | **P2 产物登记漏项** | `topics/edges.variant-spec.csr.npz`（780,286 B）实存、`p2-build-report.artifacts.variant_other` 指向它，但 `meta.stages.P2.artifacts` 未登记；另 `report.artifacts` 是 dict(3)、`meta` 是 list(4)，**类型与构成均不同** |
| W3 | B1 | **5 项哈希漂移**（报告 §0.1 版本快照已过期） | 全部为实现侧脚本：`topic_edges.py`(29102→30226 B)、`topic_graph.py`(30873→36356 B)、`topics-p2.sh`(8750→12735 B)、`topics-p3.sh`(7706→9383 B)、`topics-p4.sh`(11006→15490 B)。§0.1 取证于 ~19:2x，其后 R1/R1.1 再次改动，而 §10 追加时**未回刷 §0.1 表** |
| W4 | B0 | 4 处**缩写哈希不可机器校验** | `26864b3c…d1307ccb`、`ebd46be0…f456de2`、`f9d93523…9e1cb6`、`ff2a32ad…f2fa06` —— 人工可读但断掉自动复算 |
| W5 | B4 | **导出包内 `meta.json` 是历史快照** | 冻结 72,830 B@19:46:33 ≠ 活件 79,503 B@20:01:04；manifest 全绿只证明「**包内自洽**」，不证明「包内 = 最新口径」 |
| W6 | D4 | 报告与 meta **同秒先后落盘** | `ACCEPTANCE-REPORT.md`@20:01:04.154 → `meta.json`@20:01:04.185（+0.031s）：报告 §10 引用 meta 登记值，却**先于** meta 最终写入 → 其「已核对」在时序上不可能用到最终版 |
| W7 | A8 | `notes_meta` 信息密度低 | 8 条中 7 条仅「（日期 追加 Px）」不同，模板正文完全重复 |

## 4 哈希链明细（B 轴）

| 组 | 项数 | 一致 | 漂移 | 备注 |
|---|---|---|---|---|
| ACCEPTANCE-REPORT 表格登记（§0.1 / §5.2 / §5.3 / §5.5） | 31 | **26** | **5** | 漂移全为实现侧脚本，见 W3 |
| 导出 `manifest.json`（8 文件） | 8 | **8** | 0 | sha256 + size 双一致；`total_bytes` 相符 |
| 导出内层 `manifest.topics.json` | 7 | **7** | 0 | — |
| `meta.baseline_sha256` | 1 | **1** | 0 | 逐字节一致 |
| **合计实地重算** | **47** | **42** | **5** | ≥30 项要求已满足 |

- **未触碰举证部分完全成立**：21 个 v1 数据/既有脚本（§5.2 16 项 + §5.3 5 项）**sha256 与 mtime 全部一致**，最大 mtime 13:57:56 ≤ 14:01 → 「v1 全程只读」结论**由哈希链支撑，可信**。
- **漂移的语义**：不是篡改，而是**登记表未随修复轮回刷**。R1/R1.1 属计划内修复，`meta.stages.P2.r1_fix` / `P4.r1_1_fix` 有完整记录；缺的是把 §0.1 的版本快照推到 20:01 的新基线。

## 5 改进建议

1. **补 `stages.P5` 段（最高优先）**：登记交付物清单（`docs-draft/` 3 件、`export-sample` 8 文件、`README.md`、`INTERFACE-PROPOSAL.md`）、`topics-p5.sh` 的 28 断言结果、导出包 `generated_at` 与 `total_bytes`，并把 `current_stage` 推到 `"P5"`。
2. **拆分 `stage` 语义，解除兼容冻结**：新增 `schema_version` 与 `stage_semantics: "legacy-p0-pin"`，或让 `topics-p0.sh` 改断言 `stages.P0.stage == "P0"`（该键已是顶层镜像、语义等价）—— 从而允许顶层 `stage` 反映真实阶段。**这是当前最大的元数据可信度风险**。
3. **建立「一产物一登记」+ 回刷闭环**：每次修复轮结束时自动重跑哈希登记表（§0.1）与引用数字（README §9 / ACCEPTANCE-REPORT），并写 `registry_updated_at`；对漂移项显式标注「登记时点 → 现值」。本次 5 项漂移与 9 项引用矛盾**全部**可由该闭环消除。
4. **README §9 数字来源索引改为「机器生成」**：本次 ❌ 中有 6 项（D5–D10）源自该表人工维护；应从 `p2-build-report.json` / `topics-report.json` / `acceptance-p*.log` 直接生成。
5. **登记表一律写全 64 位 sha256**，禁用 `xxxxxxxx…xxxxxxxx` 缩写。
6. **导出包内嵌 `registry_ref`**：写明「本包口径登记对应活件 meta.json 的 sha256 = …」，使「包内自洽」升级为「包内 ↔ 活件」可对账。
7. **补登记 `edges.variant-spec.csr.npz`**，并统一 `artifacts` 的 schema（建议一律 `{role: path}` dict，meta 与 report 同构）。
8. **`notes_meta` 降噪**：只保留一条结构说明 + 每次改动追加**变更内容**而非重复模板。
9. **声明不可再生产物**：对 `nodes.json` 这类「脚本后续被改、产物无法逐字节复现」的条目，在 `stages.P1` 加 `reproducible: false` + 理由。

## 6 未决问题

1. **`p50 1.986 / 2.395 ms` 的出处不明**：README 与 ACCEPTANCE-REPORT 均引用，但仓库内**无对应产物**（唯一 P3 性能产物为 `perf_samples=50` 的 2.6229/3.3051ms）。是更早一次测量的遗留，还是另有未落盘的运行？（影响 D8/D9 的定性：笔误 vs 无凭据数字）
2. **`stages.P4.generated_at = 20:01:04` 的语义**：该值同时是 `meta.updated_at` 与 `ACCEPTANCE-REPORT.md` 的 mtime。P4 的**内容**在 19:13 已完成、19:16 改动脚本、19:59 再次改动；20:01 应是 R1.1 的**重登记**时点。是否应把「首次完成」与「最后重登记」分成两个字段（`completed_at` / `updated_at`）？
3. **`topic_graph.py` 19:59:48 的改动未纳入任何验收**：其晚于 README(19:55) 与 P4 证据文件，`stages.P4.r1_1_fix` 记录了内容变更但**无对应复跑日志**（`acceptance-p4.log` 早于该改动）。P4 的 38/38 是否对最终脚本版本成立，需一次复跑确认。
4. **P5 无独立审计**：本报告只审到 P5 的**存在性**；`README.md`(607 行) 与 `INTERFACE-PROPOSAL.md`(100 行) 的内容质量、与 `docs-draft/` 草案的差异，超出本次任务书范围，仍属未审区（接受报告 §7 亦自认）。
5. **`meta.json` 未登记 v1 数据文件哈希清单**（接受报告 §5.1 已指出）：本轮的 21 项 v1 哈希是**首次独立计算**，无「施工前登记值」可比对，故「v1 未触碰」的强度依赖 mtime 而非哈希对账。
