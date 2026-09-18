# tests/regression — 回归测试集（REGRESSION-SET）

> 把**终审三例 + R1 加固断言 + 审计已确认的未修缺陷**固化成可重复执行的回归资产。
> 写域：`reasonix-scripts/lib-catalog/tests/regression/`（独立新目录）。
> **不修改主体代码与验收脚本**；对现有产物**只读**；**不访问网络**。

---

## 1. 它解决什么问题

终审（gpt6astra）第 ⑤ 条裁决：*"权重/行数/门槛/超跳/护栏无断言 → 缺陷可静默回归"*。
R1 轮把断言加进了 `acceptance/topics-p2..p4.sh`，但那批断言**耦合在验收脚本内部**：
只跑一次全绿、失败时定位成本高、且没有"反例有牙"的自证机制。

> **当前状态（R2 收口）**：**237 PASS / 0 FAIL / 4 WARN / 0 SKIP**；退出码 0。
> R2-E 已把 D1/M2/F2 三条升级为硬断言，**仅剩 M6 负值参数 4 条 WARN**（R2 未纳入修复）。
> 完整口径、WARN 构成与**结论边界声明**见 **§7**；独立复审对「不得宣称 WARN 已清零」的要求见
> `topics/ACCEPTANCE-REPORT.md` **§12**。

本目录把反例**逐条抽成独立脚本**，每条都满足：

| 要求 | 做法 |
|---|---|
| 构造输入 → 运行 → 断言期望 | 内存小图 / 合成候选 / 从 `card_topics.jsonl` 独立反算 |
| 失败时清晰报错 | 打印实测值、期望值、**诊断线索**（如"落盘值命中 w(2c) 双计数特征"） |
| 反例必须"有牙" | 内置**R1 修复前的实现快照**，断言它在反例图上仍然失败（否则反例图失效，必须换更狠的图） |
| 每条断言可溯源 | 输出与 README 都带"来源: 终审①/审计 M2…"引用 |
| 已知未修缺陷不阻塞 | WARN 模式（xfail）：缺陷在 → WARN；缺陷修好 → 自动 PASS 并提示升级为硬断言 |

---

## 2. 用法

```bash
cd reasonix-scripts/lib-catalog

bash tests/regression/run_all.sh              # 连跑全部并汇总（PASS/FAIL/WARN/SKIP）
bash tests/regression/run_all.sh --list       # 只列用例
bash tests/regression/run_all.sh --only r2    # 按脚本名子串筛选（逗号分隔可多选）

python3 tests/regression/r3_no_overhop.py     # 单条用例也可直接跑（exit 0/1）
R2_SEEDS=经济学,机器 python3 tests/regression/r2_assoc_order.py   # 自定义源点（term 或 id）
PYTHON=python3.12 bash tests/regression/run_all.sh                # 换解释器
```

* 数据目录：`$LIB_CATALOG_DATA`（默认 `~/go/lib-catalog-data`）
* 退出码：`FAIL > 0 → 1`；否则 `0`（**WARN 不影响退出码**）
* 每条用例最后一行是机读结果：`RESULT <tag> <PASS|WARN|FAIL> pass=N fail=N warn=N skip=N`
* 某用例崩溃/被杀（无 `RESULT` 行）→ `run_all.sh` 记 `CRASH` 并按 **FAIL** 计入

### 判定语义

| 判定 | 含义 | 影响退出码 |
|---|---|---|
| `PASS` | 受守护的行为成立 | 否 |
| `WARN` | **已知未修缺陷仍在**（标注发现来源；R2 收口后剩余项即「R2 未纳入修复」），或**基线漂移**（产物被重建） | 否 |
| `FAIL` | 受守护的行为被破坏 → 必须处理 | **是** |
| `SKIP` | 前置产物缺失/顶点消失，无法判定（不冒充通过） | 否 |

---

## 3. 用例清单：每个用例"守护什么"

| 脚本 | 它守护什么（一行） | PASS | WARN | 来源 |
|---|---|---|---|---|
| `r1_consistency_weight.py` | kw-kw 共现边权重必须能由 `card_topics.jsonl` **独立反算**出来（终审① 双计数若复现，落盘值会等于 `w(2c)` → 立即 FAIL） | 10 | 0 | 终审① / ⑤ |
| `r2_assoc_order.py` | top-20 截断的**主排序键必须是 assoc**（关联度），权重只作 tie-break；"经济学"邻域 economist 进 / economic 让位 | 41 | 0 | 终审② |
| `r3_no_overhop.py` | 扩散返回的任何节点**父链边数 ≤ hops**，且 `layer ≡ 路径长度`、`score ≡ Π边权 × decay^layer` | 83 | 0 | 终审③ |
| `r4_guards.py` | 四个数值参数**越界即拒**、边界值**必须接受**、`--budget` 语义（region 含源点 ≤ budget） | 54 | 0 | 终审⑤ / R1 加固 |
| `r5_card_count.py` | `card_topics.jsonl` 与 `cards.jsonl` **行数相等且逐行 mms 对齐**；P3 门槛 0.90 硬编码 + 口径冻结 | 26 | 0 | 终审⑤ / R1 加固 |
| `r6_known_defects.py` | D1 / M2 / F2 已升为**硬断言**（回归即 FAIL）；**仅剩 M6 负值参数为预警**——只报 WARN，不判 FAIL | 23 | 4 | 审计报告 |

> 计数会随产物重建与缺陷修复而变动（`warn_check` 命中修复后转 PASS）；上表为 **R2-E/R2-F 收口口径**的实跑规模（合计 **237 PASS / 0 FAIL / 4 WARN**，见 §7）。

### 3.1 `r1_consistency_weight.py` — 终审① 共现权重独立重算

守护：**权重公式的恒等性**。`w = log1p(min(c,50))/log1p(50) + 0.3·log1p(cs)/log1p(50)`（clamp ≤1），
其中 `c` = 同卡共现书数（卡 top-5 kw ∪ {卡 cls2}）、`cs` = 其中"卡簇标签 == cluster(u) == cluster(v)"的书数。

* **[1] 终审① 冻结反例** `settlement ↔ entanglement`（R1 基线 `c=1`，命中卡 `MMS 991000938579704181`）：
  * 硬：该对在 `card_topics` 中共现；**落盘权重 == 独立重算值**（容差 1e-6）
  * 硬：R1 前双计数错值 `0.2794153094` 未复现；失败时自动点名"命中 `w(2c)` 双计数特征"
  * 基线漂移：`c`、重算权重与 R1 基线比对（不一致 → WARN，提示复核 `FROZEN`）
* **[2] 抽样 2 条 kw-kw 边**（确定性扫描：饱和边 `w≥0.9999` + 中值边 `0.6≤w≤0.9`）逐边复算
* **[3] 层级边（主题→cls2）权重恒为 1.0**（结构边不参与共现公式）

### 3.2 `r2_assoc_order.py` — 终审② assoc 主排序键生效

守护：`topk_csr` 的键序必须是 `src↑ → assoc↓ → w↓ → dst↑`（assoc **作主键**）。

* **[A] 内存反例**：合成 4 条候选，使两口径**保留集必然不同**——
  `primary=assoc` 砍掉"最高权重低关联度"的泛词、留下"低权重高关联度"的专指词；
  `primary=weight`（= R1 修复前的等效口径）结论相反 → 反例有牙
* **[B] 真实图锚点**：`经济学` 邻域 `economist` 必须在（R1 前缺席）、`economic` 必须不在（R1 前在列 w=1.0）；
  并断言**关系不变式**：入者 assoc 更高**且**权重更低（只有 assoc 作主键才成立）
* **[C] 多源点不变式**（7 个 term 锚定源点，抗重建）：保留的 kw 出边 == assoc 降序**前缀**、
  边界单调（末位保留 assoc ≥ 首个被挤出）、权重逐条复算一致、并统计"权重更高却被挤出"的反证条数

### 3.3 `r3_no_overhop.py` — 终审③ 扩散不超跳

守护：`diffuse()` 的三条不变式——层快照传播、首访定型（strict layering）、同跳多父取最大。

* **[1] 终审③ 冻结反例图**（A/B 两条 11 跳链 + `a11→b11` + `b11→z`，请求 12 跳）：
  内置 `diffuse_pre_r1()` **缺陷实现快照**，断言它仍返回 **13 边 > 12**（反例有牙）；
  修复后必须 **≤ 12 边**
* **[2] 另三张内存图**（层内提级 / 同跳平局 / 菱形取最大）× hops ∈ {1,2,3,12}：
  断言 `无超跳` + `layer ≡ 父链边数` + `score ≡ Π边权×decay^layer` + `region ≤ budget`，
  并做"主体 `path_len` vs 独立实现"两源交叉校验；另加三条定向语义断言（tie-break 取小 id、取最大分、首访不定型）
* **[3] 真实图**（源点 `machine`，term 锚定）hops ∈ {1,2,3,12}：最深父链 ≤ hops、超跳 0、
  `layer ≡ path_len`、分数一致性（hops=3 全区域逐点）

### 3.4 `r4_guards.py` — 参数护栏与语义

守护：`--hops ∈ 1..12`、`--decay ∈ (0,1]`、`--budget ≥ 1`、`--threshold ∈ [0,1]`、`topic_id` 越界。

* **[1] 越界拒绝**：13 组非法值 → 必须非零退出**且**给出范围提示；**[1b]** 三个扩散子命令
  （`around`/`graph`/`summarize`）**都要拦**（防止护栏被挪进单个子命令）
* **[2] 边界值必须接受**：`--decay 1.0` / `--hops 12` / `--budget 50000` / `--threshold 0|1` → exit 0
* **[3] `--budget` 语义**：`visited == 出参节点数 == budget`（饱和时）、`saturated_budget=True`、
  **源点必在区内**（`budget=1` → 恰好只剩源点，证明"预算含源点"）
* **[4] hops/threshold 单调语义**：`visited` 随 hops 单调不减；`threshold=1` → 只剩源点

### 3.5 `r5_card_count.py` — 登记一致性（卡数 / 每卡规格 / P3 门槛与口径冻结）

守护：证据链与卡表的**一一对应**，以及**口径冻结**不被悄悄改写。

* **[1] 行数对齐**：`card_topics.jsonl` 非空行数 == `cards.jsonl` 非空行数（终审⑤ 的 188,512 作为基线漂移项）
* **[2] 逐行 mms 对齐**（行数相等但**错位**同样有害）+ 每卡主题数 ≤5 / 无重复 / id ∈ [0,n)
* **[3] 登记值三方一致**：`meta.stages.P2.counts.cards` == `p2-build-report.json` == `compile_report.json` == 实测；
  每卡主题数**尺寸分布** == 登记直方图
* **[4] P3 硬门槛**：门槛 **0.90 硬编码**（与 `acceptance/topics-p3.sh` 同值）、② 主簇∪类目 ≥ 0.90、
  ① 仅主簇**如实并列**且严格弱于 ②（不被口径改写）、`pass` 标记与判定一致
* **[5] 口径冻结**：`caliber_freeze` 字段齐（集合/分母/抽样/源点/门槛/衰减容忍）、冻结门槛 == 0.90、
  明确门槛施加于 ②、裁定文本登记了硬编码位置
* **[6] 衰减容忍（终审④）**：首跳均值 ≥ 0.30、逐跳有效因子 ∈ [0.30, 0.90]、第 9 跳起无新增节点、
  `decay_factor == 0.86`

### 3.6 `r6_known_defects.py` — 已知未修缺陷预警（xfail；R2 后仅剩 M6）

**本文件不判 FAIL**：缺陷在 → WARN + 来源引用；缺陷修好 → PASS + 提示升级为硬断言。
每条都先做**证据自洽**硬校验，保证 WARN 结论不是建立在算错的证据上。

> **R2 收口后的状态（R2-E 升级）**：**[1] D1 / [2] M2 / [3] F2 已全部升为 `check()` 硬断言**
> （合计 12 条硬断言，含 D1 的 pre-r2「有牙性」复现、M2 的 349 个 cls 码全量核对、F2 的 9 条现场判据）。
> **只有 [4] M6 保持 `warn_check`** —— R2 轮未纳入修复，实测 **4/4 仍复现**，构成回归集当前**全部 4 条 WARN**。

* **[1] D1 层级边截断丢失** —— 独立重算 k 层级边投票（与 `audit/num/audit_num.py` 同口径：
  卡 top-5 kw 对"卡 cls2"投票、众数、平局取小 id），断言
  `重算期望边数 == meta 登记 hierarchical_edges`、`无投票 kw 数 == 登记 kw_without_hier_edge`；
  若仍有缺失，逐条验证机理（同键同权重 `w≥1.0` + 源点出度已满 20 → 去重平局吃掉"置顶"排序键）
* **[2] M2 ASCII 大小写不对称** —— 三条**用户可见症状**（`search D9` 字面命中、`around --term D9`、
  `search tp3`）+ 一条**潜在不一致**（`term != term.lower()` 的 cls 节点数）
* **[3] F2 P1 `ext_df` 双计数** —— 证据自洽（`ratio == code/cards`、`ratio_code>1 且 ratio_dedup≤1`）
  + **现场判据**（被误剔的 flip 样本词是否已回到当前 `nodes.json`）+ 三条证据快照预警；
  另做**证据新鲜度**判定：若快照结论与当前产物相反 → 标注"证据过期，待重跑 P1 证据"
* **[4] M6 数值参数负值无下界** —— `--top -1`（层非空却显示 0 条的自相矛盾字段）、
  `--evidence -1`、`--expand-cards -1`（报告 `-1 张卡命中`）、`search --top -1`（静默截断）

---

## 4. 来源引用

| 标记 | 出处 |
|---|---|
| 终审① ② ③ ⑤ | `lib-catalog-data/topics/ACCEPTANCE-REPORT.md` §10.1（缺陷表）、§10.2（数字对照）、§10.4（新增验收断言） |
| 终审④ | 同上 §10.2「衰减容忍定义」；`meta.stages.P3.caliber_freeze.decay_tolerance` |
| R1 加固 | 同上 §10.4；`acceptance/topics-p2.sh`[8][9]、`topics-p3.sh`[3][8]、`topics-p4.sh`[8][9] |
| **R2 收口 / 独立复审** | 同上 **§11**（R1/R2 修复记录与终值）、**§12**（独立复审 gpt6astra · 有条件通过 + 保留限制清单 L1–L8）；`meta.stages['R2-A'\|'R2-B'\|'R2-C'\|'P5']` |
| D1 | `lib-catalog-data/topics/audit/num/REPORT.md` §4；`audit/edgetype/PROPOSAL.md` §1.5；`audit/verify-fix/REPORT.md` |
| M2 / M6 | `lib-catalog-data/topics/audit/graph/REPORT.md`（M2·F19 / M6·F5）；**M6 未修**见 §12.2-L1 |
| F2 | `lib-catalog-data/topics/audit/p1/REPORT.md`（F2 / F2b）+ `audit/p1/evidence/ext_double_count.json`（**R1 期快照，仅作历史锚点**；现用现场判据） |
| F18 / R2-C §5 残留 | `ACCEPTANCE-REPORT.md` §12.2-L6；`meta.stages['R2-A'].open_issues`、`stages['R2-C'].not_done` |
| R2-E 全链复跑 | `lib-catalog-data/topics/audit/r2-verify/REPORT.md`、`audit/r2-verify/verify_r2e.json` |

---

## 5. 设计约束（为什么这样写）

1. **硬断言只建立在"不变量 / 公式恒等 / 跨表一致"上。**
   数据相关的数字（某对共现书数、assoc 数值、层级边总数、卡数）会因**产物重建**而合法漂移；
   把它们写成硬等值断言会制造**假红**。这些数字统一走 `Reporter.baseline()`：
   与 R1 基线一致 → PASS；不一致 → **WARN（基线漂移）**并提示复核后更新 `_common.py` 的 `FROZEN`。
   > 这条纪律不是理论洁癖：施工期间另一路 R2 轮重建了产物
   > （节点 5,187 → **5,507**、边 99,268 → **105,414**、`settlement` id 168 → **171**），
   > 早先版本的硬等值断言当场变红——而**代码其实没坏**。
   > R2 收口后 `_common.py` 的 `FROZEN` 已按现值对齐（R1 期值保留为 `*_r1` / `*_pre_r1` 历史锚点）。
2. **反例顶点 / 源点用 `term` 锚定，不用 id。** 节点表重建会让 id 漂移（`计量` 从 id 680 迁到 717），
   term 相对稳定；term 失配时回退 R1 基线 id 并打印说明；两者皆无 → `SKIP`（不冒充通过）。
3. **`sys.dont_write_bytecode = True` 前置于 `import _common`**，配合 `run_all.sh` 的
   `PYTHONDONTWRITEBYTECODE=1`，保证连 `__pycache__` 都不落进主体目录（"对现有产物只读"）。
4. **不触网**：子进程一律注入 `TOPIC_LLM=off`；`r6` 的 `search` 用例带 `--expand no`
   （避免走 TF-IDF 扩展路径），全部只用本地文件。
5. **崩溃即 FAIL**：`main_guard()` 兜底捕获异常 → FAIL + 打印栈；`run_all.sh` 对缺 `RESULT` 行的用例记 `CRASH`。
   回归集绝不允许"崩溃即通过"。

---

## 6. 维护指引

* **新增用例**：复制 `r*.py` 骨架 → 在 `_common.Reporter` 上写 `check()`（硬）/ `warn_check()`（预警）
  → 把脚本名加进 `run_all.sh` 的 `CASES`/`DESC` 数组 → 在本 README §3 表里补"守护什么"与来源。
* **缺陷修好后**：把对应 `warn_check()` 改成 `check()`（用例会在修复时打印"可升级为硬断言"提示）。
* **基线漂移后**：按 WARN 提示复核，确认是合法重建 → 更新 `_common.py` 的 `FROZEN` 参考值与本节数字。
* **不要**在回归集里调用 `topic_edges.py`/`topic_build.py` 的重建路径（会写主体产物）；
  回归集只读既有产物 + 调用 `topic_graph.py` 的查询面。

---

## 7. 当前状态（**R2 收口口径**，2026-09-18 22:0x）

```
TOTAL (6 cases)   PASS=237  FAIL=0  WARN=4  SKIP=0      # 约 43s（r4 约占 27s、r6 约占 13s）
r1 PASS 10/0/0 | r2 PASS 41/0/0 | r3 PASS 83/0/0 | r4 PASS 54/0/0 | r5 PASS 26/0/0 | r6 WARN 23/0/4
```

复跑方式：`cd ~/go/reasonix-scripts/lib-catalog && bash tests/regression/run_all.sh`
（退出码 **0** —— WARN 不影响退出码；判定 `REGRESSION-SET: PASS`）。

### 7.1 WARN 构成（**4 条，全部来自 M6 负值参数**）

| 类别 | 条数 | 明细 |
|---|---|---|
| **负值参数无下界（M6）** | **4** | `--top -1`（层内 20 个主题却显示 top 0 的**自相矛盾字段**）/ `--evidence -1`（**静默返回 0 条**）/ `--expand-cards -1`（报「**-1 张卡命中**」）/ `search --top -1`（**丢末行**，静默截断） |

**R2 轮未纳入 M6 修复** —— 这 4 条 WARN 是**已知未修缺陷的如实预警**，不是失败。
缺陷修好后，对应 `warn_check()` 会自动转 PASS 并提示升级为硬断言（见 §6）。

### 7.2 R1 → R2 的基线升级（本目录已完成）

| 用例 | R1 口径 | **R2 收口** | 变化 |
|---|---|---|---|
| r1_consistency_weight | PASS 10 / WARN 0 | PASS **10** / WARN 0 | 不变 |
| r2_assoc_order | PASS 40 / **WARN 1**（assoc 基线漂移） | PASS **41** / WARN 0 | `ce2_assoc_leaves` 0.0353→**0.0316**（共现 39→35），WARN 消除 |
| r3_no_overhop | PASS 83 / WARN 0 | PASS **83** / WARN 0 | 不变 |
| r4_guards | PASS 54 / WARN 0 | PASS **54** / WARN 0 | 不变 |
| r5_card_count | PASS 26 / WARN 0 | PASS **26** / WARN 0 | 不变 |
| r6_known_defects | PASS 11 / **WARN 9** | PASS **23** / WARN **4** | D1/M2/F2 升硬断言（+12 PASS），仅 M6 留 WARN（−5） |
| **合计** | **224 PASS / 0 FAIL / 10 WARN** | **237 PASS / 0 FAIL / 4 WARN** | **PASS +13 ｜ WARN −6 ｜ FAIL 0** |

**升级内容**（R2-E 实施，`_common.py` + `r6_known_defects.py` + `run_all.sh`）：

* **D1 层级边** → 4 条硬断言：登记==实存（**5,151==5,151**）/ 零丢失 / 与 R1 的 9 条清单**无交集** /
  **有牙性**：pre-r2 产物整组独立重算**仍须得 9 条**缺失（id 空间不同，不可混用节点表）。
* **M2 大小写** → 3 条硬断言：CLI 抽 6 个高频 cls 码「存名/归一名命中数一致且 ≥1」/
  全量 **349** 个 cls 码归一键大小写不敏感 / 全量 349 个以本名查询均为**整词精确命中**（+1 条 `around --term D9` 可用）。
  > 原 R1 版有一条**谓词错配**断言（要求 `term` 已统一小写），而 R2-B 选的是**检索侧归一**、
  > **未**统一小写存储 → 大写 `cls` 码属**既定策略**，该断言已按实际方案改写（`m2_victims` 仍为 349）。
* **F2 `ext_df` 双计数** → 9 条**现场判据**硬断言（原先 4 条读的是**已过期快照**
  `audit/p1/evidence/ext_double_count.json`，其数值是 R1 期缺陷度量、与现场相反）：
  A 源漏斗闭合 `1647+765+429==2841` / `ratio_max ≤ 1` / `ratio>1 == 0` / `source_a_kept==1647` /
  `dropped_embedded==765` / **新增词中 A 源 ==129** / 词表**纯增无消失** / A 源集 2841 / A 源词在表 ==1486。
* **FROZEN 基线对齐现值**：`d1_registered_hier` 4,832→**5,151**、`f2_double_count_events` 207,596→**0**、
  `f2_ratio_gt1_terms` 580→**0**、新增 `types_domain=(1,3,5,7)` 等；R1 期值全部保留为 `*_r1` / `*_pre_r1` 历史锚点。
* **报告器文案**：去掉写死的「R1 基线」「待 R2」措辞（R2 已收口，剩余 WARN 语义为「R2 未纳入修复」）。

> 备份：`_common.py.pre-r2e`（改动前原值 sha256 `32defc8cafcd39e8`）。
> 逐项证据与三次复跑记录：`lib-catalog-data/topics/audit/r2-verify/REPORT.md`。

### 7.3 ⚠️ 交付声明（本回归集的结论边界）

1. **不得宣称「WARN 已清零」** —— 现存 **4 条 WARN**（全部为 M6 负值参数，见 §7.1）。
2. **`PASS` 只表示「受守护的不变量成立」**，**不**表示数据质量或查询相关性整体达标
   （相关性的独立结论见 `topics/ACCEPTANCE-REPORT.md` §12：**8/10 同域口径**，Q07/Q10 未达标）。
3. **本目录不覆盖 P1 的 `freq`/排序键可复算性** —— 该口径依赖**未落档的完整卡集**，属既有缺口
   （见 `topics/ACCEPTANCE-REPORT.md` §12.2-L2），回归集**不冒充覆盖**。
4. **`SKIP` 不冒充通过** —— 前置产物缺失/顶点消失时报 SKIP 并计入报告。
