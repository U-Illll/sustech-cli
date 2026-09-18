# R2-E · 全链复跑与 R2 全轮验证报告

> **结论**：回归集基线升级完成（**224→237 PASS / 0 FAIL / 10→4 WARN**）；全链复跑 **acceptance 147 项全绿 exit 0**、`topics_report` 独立复跑与正式值**逐位一致**；R2 全轮关键验证 **16 PASS / 0 FAIL**，仅 2 项**既有口径缺口**（非 R2 回归）。
> 执行：dsh VERIFY-FIX 会话（R2-E）｜2026-09-18 21:4x–21:5x｜只读主体与正式产物；写仅 `tests/regression/` 与 `audit/r2-verify/`；无网络。

## 0 冻结快照（开工记录 → 收口核对）

| 产物 | sha256 前 16 位（开工 → 收口） | 说明 |
|---|---|---|
| `topics/nodes.json` | `ba1ff2603ee759b2` → 同 | 5,507 节点（R2-A） |
| `topics/edges.csr.npz` | `afd32610bd9b1adb` → 同 | 105,414 边 + `types` u8（R2-C） |
| `topics/card_topics.jsonl` | `3890295d514f66bd` → 同 | 188,512 行 |
| `topics/topics-report.json` | `d1dd63b7576a9dd3` → 同 | R2-C 重跑 |
| `topics/p2-build-report.json` | `73af4de3c7ffb91e` → 同 | 含 `b5_arrays`/`b5_edgetype_rule` |
| `topics/meta.json` | `9baca57153478057` → **`b52d05f2d03c287b`** | ⚠️ **被并发会话改写**（见下） |

**备份**：`tests/regression/_common.py.pre-r2e`（sha256 `32defc8cafcd39e8` = 改动前原值）。

**并发写入（必须与结论一起读）**：R2-E 窗口内有其他执行体持续改写 `meta.json` / `README.md` / `ACCEPTANCE-REPORT.md`：
`meta.json` 于 **21:37** 被 R2-D 会话写为 88,858 B，又于 **21:58:13** 由 `dsh AUDIT-META 会话（R2-D 任务书）` 追加 `stages.P5` 并置 `current_stage=R2-C → P5`（93,764 B）。
期间我曾读到 `a7b6af86…`（重写瞬间的部分读取）。**影响评估**：本报告依赖的 `meta.json` 字段为
`stages.P2.counts.{hierarchical_edges=5151, kw_without_hier_edge=7, nodes=5507}` —— **在整个漂移过程中始终不变**；
且 `run_all.sh` 与 `verify_r2e.py` 已在**收口状态（`current_stage=P5`）下复跑通过**（§1.3 / §3）。其余 5 件产物全程未变。
**引用前请先复核哈希**。

## 1 回归集基线升级（步骤 1）

**改动**：`_common.py`（FROZEN + 报告器文案）、`r6_known_defects.py`（warn→硬断言）、`run_all.sh`（文案）。

### 1.1 FROZEN 基线与 R2 后数值对齐

| 键 | R1 基线 | **R2 后（现值）** | 处置 |
|---|---|---|---|
| `ce2_assoc_leaves`（economic assoc） | 0.0353 | **0.0316** | 更新（共现 39→35；`ce2_assoc_leaves_r1` 留历史锚点） |
| `d1_registered_hier` / `d1_present_in_artifact` | 4,832 / 4,823 | **5,151 / 5,151** | 更新（登记=实存） |
| `d1_missing` / `d1_missing_pairs` | 9 / 9 对 | **0 / ()** | 更新（R1 清单移入 `d1_r1_missing_pairs` 作有牙性锚点） |
| `d1_pre_r2_missing` | — | **9** | 新增：pre-r2 产物必须仍复现 9 条 |
| `m2_victims` | 349 | **349** | 不变（R2-B 选「检索侧归一」，**未**统一小写存储 → 大写属既定策略） |
| `f2_double_count_events` / `f2_ratio_gt1_terms` | 207,596 / 580 | **0 / 0** | 更新；R1 期值移入 `f2_pre_r1_evidence` |
| `f2_containment_ratio_max` | 2.0 | **1.0** | 新增（卡级比值 >1 的不可能性已消除） |
| `f2_a_kept` / `f2_a_dropped_embedded` | 1,518 / 894 | **1,647 / 765** | 新增（+129 / −129） |
| `f2_a_kept_in_nodes` / `f2_a_set_n` | 1,357 / 2,841 | **1,486 / 2,841** | 新增（1357+129） |
| `types_domain` | — | **(1,3,5,7)** | 新增（R2-C 边型数组值域） |

同时把 `Reporter.baseline()` / `warn_check()` 的文案去掉写死的「R1 基线」「待 R2」（R2 已收口，剩余 WARN 语义是「R2 未纳入修复」）。

### 1.2 已修条目 warn_check → **check 硬断言**（回归即 FAIL）

| 项 | 原 warn_check（R1） | 现硬断言（R2-E） |
|---|---|---|
| **D1** | 1 条「零丢失」+ 1 条 baseline 漂移预警 | **4 条硬断言**：登记==实存 / 零丢失（缺失 0） / 与 R1 的 9 条清单无交集 / **有牙性**：pre-r2 产物独立重算仍须得 9 条（须整组用 pre-r2 的 nodes+card_topics+edges，id 空间不同不可混用） |
| **M2** | 4 条（含 1 条谓词错配：断言「term 已统一小写」，而 R2-B 选的是检索侧归一） | **3 条硬断言**：CLI 抽 6 个高频 cls 码「存名/归一名命中数一致且 ≥1」 / 全量 349 个 cls 码归一键大小写不敏感 / 全量 349 个以本名查询均为**整词精确命中**（+1 条 `around --term D9` 可用） |
| **F2** | 4 条**读过期快照** `ext_double_count.json`（其数值是 R1 期缺陷度量，与现场相反） | **9 条硬断言（全部现场判据）**：A 源漏斗闭合 1647+765+429==2841 / ratio_max ≤1 / ratio>1 == 0 / `source_a_kept`==1647 / `dropped_embedded`==765 / **新增词中 A 源 ==129** / 词表纯增无消失 / A 源集 2841 / **A 源词在表 ==1486**；快照仅作历史锚点 |
| **M6** | 4 条预警 | **保持 warn_check**（R2 轮未纳入修复，实测 4/4 仍复现） |

### 1.3 复跑结果（`bash tests/regression/run_all.sh`）

| 用例 | 升级前 | **升级后** |
|---|---|---|
| r1 / r3 / r4 / r5 | PASS 10 / 83 / 54 / 26，0 warn | 不变 |
| r2_assoc_order | PASS 40 **WARN 1**（assoc 基线漂移） | **PASS 41**，0 warn |
| r6_known_defects | PASS 11 **WARN 9** | **PASS 23 WARN 4**（仅 M6） |
| **合计** | **224 PASS / 0 FAIL / 10 WARN** | **237 PASS / 0 FAIL / 4 WARN** |

PASS **+13**、WARN **−6**、FAIL 0。**三次独立复跑结果完全一致**（确定性），其中末次在 `meta.json` 被并发改为 `current_stage=P5` **之后**重跑，仍为 237/0/4 —— 说明本套件对 `current_stage` 漂移稳健。

## 2 全链复跑（步骤 2）

### 2.1 acceptance P0–P5（原始日志：`audit/r2-verify/runs/acceptance-p*.log`）

| 脚本 | P0 | P1 | P2 | P3 | P4 | P5 | 合计 |
|---|---|---|---|---|---|---|---|
| PASS | 8 | 17 | 35 | 21 | 38 | 28 | **147** |
| FAIL | 0 | 0 | 0 | 0 | 0 | 0 | **0** |
| exit | 0 | 0 | 0 | 0 | 0 | 0 | 全 0 |

与 R2-C 自报（147 项全绿）**逐项吻合**。唯一非 PASS 项为 P3 的 `[INFO]`（见 §4-①）。

### 2.2 `topics_report` 独立复跑（对比 R2-C 正式值）

命令（与 R2-C 冻结口径一致）：`--samples 400 --hops 12 --seed 42 --random-baseline` → `runs/report-rerun-kw400.json`

| 口径 | 我的复跑 | R2-C `meta.stages.R2-C.report_rerun` | 判定 |
|---|---|---|---|
| ① 仅主簇 · 400/kw mean / median | 0.9246404381082953 / 0.9473684210526315 | 同 | ✅ 逐位相同 |
| ② 主簇∪类目（硬门槛） | 0.9927011191897308 / 0.9965576490105463 | 同 | ✅ |
| ③ 无向闭包 | 0.9286324252877824 / 0.9473684210526315 | 同 | ✅ |

**全文档比对**：378 个叶节点，**0 个实质差异**；仅 6 项为易变字段（`generated_at` + 5 项耗时）。`--source-type all` 复跑亦 rc=0。
> 注：我的复跑 p50 **3.19 ms** / p95 7.91 ms 高于正式值 2.58 / 3.74 ms —— 因与 acceptance 六脚本**并发**争用 CPU，非算法回退（门槛 <1000 ms，仍 PASS）。

### 2.3 `topic_graph` 抽测（M2 / P4 修复后各 2 例）

| # | 命令 | 实测 | 判定 |
|---|---|---|---|
| M2-1 | `search D9` vs `search d9` | 均 exit 0，字面命中 **3 / 3**（一致） | PASS |
| M2-2 | `around --term TP3` vs `tp3` | 均 exit 0，同定位 `43 「TP3」(cls, freq=11534)` | PASS |
| P4-1 | `around 56`（机器）`--hops 2 --top 5 --evidence 3` | exit 0，证据段非空 | PASS |
| P4-2 | `around 65`（文学）`--hops 2 --top 5 --evidence 3` | exit 0，证据段非空 | PASS |

## 3 R2 全轮关键验证（步骤 3，独立于 A/B/C 自证）

脚本 `audit/r2-verify/verify_r2e.py`（自研，~10 s，两次复跑结果全等）｜原始值 `verify_r2e.json`。
**方法**：期望值只由证据链（`card_topics.jsonl` + `cards.jsonl` + `nodes.json` + `clusters.npy`）自行重算，**不 import** R2-A/B/C 的验证脚本。

| 项 | 判定 | 关键实测 |
|---|---|---|
| **F2 129 词在表** | ✅ **PASS** | **两条互证路径**：① 新词 320 = 含 A 源 **129** + B 源 191（仅用 `sources` 字段，完全自足）；② A 源候选集 2,841 中在表数 1,357→**1,486**（Δ **+129**）。漏斗闭合 `1647+765+429=2841`；词表**纯增无消失** |
| **F1 排序键语义** | ⚠️ **GAP** | **无法独立验证**：交付序既非 `sort(-max_cc,…)` 的两种 card_topics 派生键（分歧 5,505/5,507、5,503/5,507），`freq` 亦有 1,285/5,507（23.3%）与证据链不符——因 `max_cc = freq×rep` 依赖 **top-5 截断前的完整卡集，该卡集未落档**。属 AUDIT-NUM §5 / R2-A 未决 §3 的既有口径缺口，**非 R2 回归**。可独立验证部分：id 连续、term 唯一（PASS） |
| **D1 层级边 0 缺失** | ✅ **PASS** | 独立重算登记 5,151 == 实存 5,151，**缺失 0**；**有牙性**：pre-r2 产物（nodes+card_topics+edges 整组）独立重算仍得 **9 条**缺失，与 R1 清单一致 |
| **M2 大小写命中一致** | ✅ **PASS** | 全量 **349/349** 个 cls 码：归一键 `norm_key` 对大小写不敏感、以本名查询均为整词精确命中（0 例外）；CLI 抽 6 例命中数逐例相等 |
| **P4 相关率抽验（2 条）** | ✅ **PASS** | 走完整协议（`search` → 整词最低频种子 → `around --hops 2 --top 10 --evidence 5`）。**Q02 量子 计算**：种子 **188/量子**、hop1 同域可读 ≥4/10、证据 **5/5**（量子点激光器/量子光学讲义/纳米量子光学/量子力学的哲学基础/Foundations of quantum mechanics）；**Q06 唐诗**：种子 **552/唐诗**、证据 **5/5**（唐诗选/六朝声律与唐诗体格/唐诗宋词中的风雅与时尚/唐诗的乐园意识/总有诗人解我忧 唐诗心理商谈室）。两条均判 **2（相关）**，与 R2-B 表**逐条逐书吻合** |
| **type 数组（三类型掩码）** | ✅ **PASS** | **全量 105,414 条逐边核对**（远超任务书 ≥100 抽样；另记 300 条随机抽样含于其中）：`bit0` 置位违例 **0**；`bit1 == (c_sc>0)` 不符 **0**；`bit1 ⇒ 两端同 cluster` 违例 **0**；`bit2 == (src→cls_of[src])` 不符 **0**；值域恰为 **{1,3,5,7}**。分布：`1`: 89,643 (85.04%) / `3`: 10,620 (10.07%) / `5`: 4,358 (4.13%) / `7`: 793 (0.75%) |
| **type 数组对照** | ✅ **PASS** | vs **pre-r2c**：`indptr`/`indices`/`weights` **逐位一致**（R2-C 仅新增 `types`，`pre-r2c` 键确为三数组）→ 印证「新增数组未扰动既有三数组」。vs **pre-r2**：三数组**必不相同**（词表 +320 节点、99,268→105,414 边）属预期；权重 `mean` 0.364724→0.365599、`w=1` 占比 0.0807→0.0805（量级不变）。导出包 `export-sample/v1/topics/edges_types.u8.bin` 与源 npz `types` **逐位一致** |

## 4 残余问题

1. **[中·三次确认] P3 `[4]` ① 断言文案过时、实为 `INFO` 不构成 PASS**：注释与 `[4]` 仍写「① < 0.90」，而 R1 后 ①=0.9188、R2-C 后 ①=**0.9246** 均 ≥0.90，落 `info` 分支（"请复核裁定文本"）。即该守卫**当前不校验任何东西**。建议改为区间断言「0.90 ≤ ① < ②」。（R2-C §5-1 已报两次，本次为第三次独立确认）
2. **[中] F1 排序键不可独立验证（口径缺口）**：`freq`/`max_cc` 依赖未落档的完整卡集（本报告量化：`freq` 23.3% 节点不可由证据链复算）。R2-A 的 V3 自证用的是其自身的卡集口径，**第三方无法复现**。建议在 `meta.json#stages.P1` 落档 `freq/rep/max_cc` 的口径定义与卡集指纹。（AUDIT-NUM §5 / R2-A 未决 §3；R2 未处理）
3. **[中] M6 未修**：负值参数仍无下界（回归集 4 条 WARN 全部来自此项）：`--top -1` 产出「层内 20 个主题（显示 top 0）」自相矛盾字段、`--evidence -1` 静默返回 0 条、`--expand-cards -1` 报「-1 张卡命中」、`search --top -1` 丢末行。
4. **[低] F18 未修**：`source_a_kept` 含 161 个被 entry 段英文门二次过滤的词且无计数器（R2-A 未决 §4）；我的复核确认这 161 个仍不在 `nodes.json`（`a_kept_in_nodes` 1,486 = 1,647 − 161）。
5. **[低] R2-C §5 其余项未变**：#2 `topics-report-exhaustive.json` schema 双轨、#3 AUDIT-EXPORT E3/E4、#4 `variant-spec` 的 `types` 未单独验收、#5 穷举口径 ~76 s 未入常规验收。
6. **[信息] 并发写入（影响面已评估）**：`meta.json` 在窗口内被 R2-D/P5 会话改写两次（末次 `current_stage=R2-C→P5`，21:58:13）；本报告依赖的 `stages.P2.counts.*` 三字段全程不变，回归集与 `verify_r2e.py` 已在收口状态复跑通过。`README.md`/`ACCEPTANCE-REPORT.md` 亦被改写（非本会话）。**引用本报告前请先复核 §0 哈希**。

## 5 复跑方式

```bash
cd ~/go/reasonix-scripts/lib-catalog
bash tests/regression/run_all.sh                       # 期望 237 PASS / 0 FAIL / 4 WARN
bash ~/go/lib-catalog-data/topics/audit/r2-verify/run_acceptance.sh   # 六脚本 147 PASS / exit 0
cd ~/go/lib-catalog-data/topics/audit/r2-verify
PYTHONPATH=~/go/pylibs python3 verify_r2e.py           # 16 PASS / 0 FAIL / 2 GAP；exit 0
```
