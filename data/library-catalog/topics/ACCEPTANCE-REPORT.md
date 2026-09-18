# 图书馆主题图（GraphRAG-lite）· 全链验收报告

> **复跑取证时间**：2026-09-18 19:17:48（+0800）｜**取证方式**：验收工程师亲手复跑 P0–P4 全部验收脚本 + 实读全部产物文件
> **工具链**：`/home/wzh/go/reasonix-scripts/lib-catalog/`｜**数据**：`/home/wzh/go/lib-catalog-data/`
> **报告口径**：所有数字均来自本轮实跑输出或实读文件；凡未验证项均显式标注。
>
> 🔴 **R2-D 同步声明（2026-09-18 22:0x，先读）**：本报告原为 **19:2x 取证快照**（R1 前口径）。
> 经 R1（终审整改）、R2-A/B/C（审计整改）三轮后，**产物已重建**：**5,507 节点 / 105,414 边**（原 5,187 / 99,268）。
> 本次同步做了四件事：
> ① **§0.1 脚本版本表对齐到当前磁盘现值**（原 6 项已过期，现 10 项零漂移）；
> ② **统一断言计数**：§0.2 / §7.1 的 P4「30/30」与 §10.7 的「142」不再并存，**终值 147 项**（见 §11.3）；
> ③ **「全节点」类表述改准**：一律标注「**仍是 400 采样**」并给出 `pool_size`；
> ④ **新增 §11 R1/R2 修复记录**，汇总三轮 before→after 与本次同步清单。
> **读法**：§1–§9 正文中的数字若标有「R2 终值」以该值为准；未标注者按 **19:2x 快照**读，**不得当作当前值**。
>
> ⚠️ **数据形态声明（终审⑦；R2-C 后已更新）**：主题图是**合成加权图**——边权由「同书共现书数」经 `log1p` 归一而来；
> ①共现与②同簇加成已合并为同一 `weights`（`w=min(1, w1+w2)`）。
> **R2-C 起新增逐边类型位图 `types`（uint8，`{1,3,5,7}`）**，可精确还原三类边来源；
> 旧的「`w=1.0` 且目标 `type=cls`」判据**降级为近似兜底**，不再是等价判据。
>
> ⚠️ **R1 修复轮（终审整改）**：本文档 §1–§8 的原始数字为 **R1 修复前**快照；R1 后的权威数字见 **§10**，
> 凡本节约定的口径/数字与 §10 冲突，以 §10 为准。R1 轮未修改任何既有文件（含 `acceptance/*.sh`、`meta.json`、验收日志）。
> ⚠️ **R2 修复轮（审计整改）**：R2-A/B/C 三轮**已改动**数据与工具链（授权范围内），权威数字见 **§11**；§10 的 142 项计数亦已被 §11.3 的 147 项取代。


---

## 0. 取证快照与方法（先读）

### 0.1 复跑时钉住的脚本版本（sha256）

**R2-D 更新（2026-09-18 22:0x）**：本表原为 **19:2x 取证时点**的快照，其中 6 项在 R1/R2 修复轮中被再次改动而**未回刷**，
导致「报告登记值」与「磁盘现值」不一致（AUDIT-META §2 B1 发现，5 项漂移）。
**现将全表对齐到 R2-D 同步时点的磁盘现值，10 项全部可实地复算、零漂移**；19:2x 的历史值保留在下方「版本沿革」。

| 脚本 | sha256（**R2-D 同步时点**） | mtime | 字节 |
|---|---|---|---|
| `acceptance/topics-p0.sh` | `730475f0b351dbae62c9a1a6d81d282f53f92e5784463ceced7fc9bc748f100e` | 17:32:20 | 3,152 |
| `acceptance/topics-p1.sh` | `82737d263bae6b6c5612e6e95164c6de834e70b01c0e9efa06823fcbad7b34ce` | 18:40:30 | 7,197 |
| `acceptance/topics-p2.sh` | `198086287f340ee6f38c9eedbca5ef6c8ca436d8a873abb6cb388b15055e6fbc` | 21:37:06 | 14,469 |
| `acceptance/topics-p3.sh` | `822856e60ddf1832681ed9fa80ce76c6f89c6034de8ab06c575b2715209d664c` | 19:56:00 | 9,383 |
| `acceptance/topics-p4.sh` | `fb7fca2bbf1a41d99ae0f98644c94636828344e037646cf16d16358fd6bd8821` | 19:56:00 | 15,490 |
| `acceptance/topics-p5.sh` | `a0a92b588a62f68f9a7c038e330dc0b9c57b6a93186b97ebd162afec819e3672` | 19:22:19 | 7,521 |
| `topic_build.py`（P1） | `1f0da80e8d9a3fbbdeb48e29fc66ffe7e58ec7941a1196881728d37a352ed8e2` | 21:44:23 | 39,054 |
| `topic_edges.py`（P2） | `d0ce2228b51862d2d6706d1ed61c352c64e667217b9c06f2b63ca2b7f26c7549` | 21:34:26 | 33,515 |
| `topics_report.py`（P3） | `980b9f6502367507f6b2c11f9e95668a85360f16b162a3406bc4b920492e55f9` | 18:52:50 | 40,980 |
| `topic_graph.py`（P4） | `39e04d9bae7f5fd2bc729a7fbcd918baceabc29b2a69abec97815bb648bfd4ce` | 21:15:15 | 45,738 |

**版本沿革（仅列已变动项；格式 `19:2x 登记值 → 现值`）**

| 脚本 | 19:2x 登记 sha256 | 19:2x mtime / 字节 | 变动原因 |
|---|---|---|---|
| `acceptance/topics-p2.sh` | `0fde19931fba9c6a870c06d10ce5e2effdb76c22131f279d174c1d8bc50f16ce` | 18:51:38 / 8,750 | R1 加固 + **R2-C 新增 `[4b]` 边型断言（30→35 项）** |
| `acceptance/topics-p3.sh` | `e7d12b8ecbff93e13153326cf576c78c1d3a57c9003cb1f0fa80fd62b99fa429` | 19:04:10 / 7,706 | R1 断言加固（21 项） |
| `acceptance/topics-p4.sh` | `ee3ee21741dee32152ea173a3870d468e7178a5f3eceb34b421c867f417c9ea9` | 19:14:31 / 11,006 | R1.1 护栏 + 断言加固（38 项） |
| `acceptance/topics-p5.sh` | *（原表无此行）* | — | 19:22:19 落位（28 项），**R2-D 补入本表** |
| `topic_build.py` | `26864b3c926181584109a914bd7ecb2df2c1b8bae56ef948a86b081db1307ccb` | 19:03:18 / 36,084 | **R2-A** F1/F1b + F2/F2b 修复；**R2-D** docstring `--min-df` 8→12 |
| `topic_edges.py` | `7372e2e8fe48ccab5be7ae349241bb1bef263b5ab4e8bd62bac94e030bea8e5e` | 18:49:22 / 29,102 | **R2-A** D1 修复 + **R2-C** `types` 位图落盘 |
| `topic_graph.py` | `f9d93523c10c68ec6638845cb2a1395e877926489f04974879a3b9f8ae9e1cb6` | 19:16:05 / 30,873 | **R2-B** 大小写归一 / `search` 排序 / 证据取样修复 |

> ⚠️ **复跑时必须重新快照**：上表是**同步时点**的值，不构成"冻结版本"。
> 但凡引用本报告 §1／§6 的**验收数字**，都须同时声明所用的脚本版本；
> `topics/audit/meta/audit_meta.py` 可一键重算本表并列出漂移项。

### 0.2 ⚠️ 取证期间发现"工具链正在被并发改动"（重要，影响证据时效）

复跑过程中实测到施工方（主会话／P5 阶段）**在同一时间窗内仍在改动工具链与产物**，故本报告证据必须按时间戳读：

| 观测时刻 | 事件 | 证据 |
|---|---|---|
| 19:13:42 | `topic_graph.py` = 30,255 字节（sha256 `ebd46be0…f456de2`，**原版已被覆盖，缩写无法补全**）—— 本轮首次 P4 复跑用的就是这一版 | 首次 `ls` 输出 |
| 19:13:59 | `meta.json` 追加 `stages.P4`（`updated_at=2026-09-18T19:13:59+0800`） | `meta.json` |
| 19:14:24 | `p4-smoke.txt` 落盘 | `ls` |
| 19:15:30 | `export_release.py` 由 12,990 字节（原 mtime **14:01**）→ 18,957 字节，追加 `export_topics()` / `--topics` / `--topics-only` | 两次 `ls` 对比 |
| 19:15:35 | `topics/export-sample/v1/topics/` 首次出现（7 文件 + manifest） | 两次 `ls` 对比 |
| **19:16:05** | `topic_graph.py` 再次改动 = 30,873 字节（sha256 `f9d93523c10c68ec6638845cb2a1395e877926489f04974879a3b9f8ae9e1cb6`） | 复跑前快照 |
| **19:17:48** | 本报告 §6 的五个脚本统一复跑（一次完成，结论落 §6） | §6 |
| **19:18:16** | `topics/INTERFACE-PROPOSAL.md` 首次出现（10,045 B）—— §7.1 曾记为"缺失"的 P5 交付物开始落位 | 两次 `ls` 对比 |
| **19:19:26** | `topics/README.md` 首次出现（45,248 B）—— 同上 | 两次 `ls` 对比 |
| **19:19:33** | 本报告落盘 | 本文件 |

**处置**：本报告 §1／§6 的五个验收结论，全部取 **19:17:48 那次统一复跑** 的结果，对应上表 `topic_graph.py` 的 19:16:05 版本；
`topic_graph.py` 的两个版本哈希均已记录，便于事后对账。**未发现改版导致验收结果变化**。
> ⚠️ **R2-D 更正（断言计数）**：此处原写「P4 仍然 **30/30** 全过」。该数字是 **19:17:48 时点**的 P4 断言数，**已过期**。
> **当前终值为 P4 = 38 项**；六脚本合计由 19:1x 的 **100 项** → R1 后 **142 项** → R2-C 后 **147 项**，
> 全绿 exit 0（见 §10.7 与本报告 §11.3）。§0 与 §7.1 的旧计数已按此更正，**全文不再保留未加标注的 "30/30"**。

⚠️ **快照时效声明**：本报告对 P5 交付物的"实存性"判定以 **19:17:48 快照** 为准。19:18–19:19 期间施工方补落了 `INTERFACE-PROPOSAL.md` 与 `README.md`，故 §1 P5 行、§2.6、§7.1、§8-5 中凡涉及"README 缺失"的表述，**应在读取时按本节时间线更正为"已于 19:19:26 落位"**；截至本报告定稿（19:19:33），**`acceptance/topics-p5.sh` 仍不存在**（已再次 `ls` 确认，见 §7.1 首行）。

### 0.3 环境事实（影响举证方式）

1. **工具链目录不是 git 仓库**：`git -C /home/wzh/go/reasonix-scripts/lib-catalog rev-parse --show-toplevel` → `fatal: not a git repository`；上一级 `reasonix-scripts/` 与数据目录 `lib-catalog-data/` 同样均非 git 仓库。
   → 交接文档 §4-P5 规定的举证方式「**未触碰 v1 既有文件（git 内 diff 证明）**」**在本机不可执行**；本报告改用 **sha256 + mtime** 举证（§5）。
2. **数据目录当前为读写挂载**：`findmnt -T /home/wzh/go/lib-catalog-data` → `/home/wzh/go  /dev/sdd[/home/wzh/go]  ext4  rw,...`。
   但 P0 施工首日记录显示当时该目录为**只读**（`topics/notes-first-attempt-20260918.txt`：`mkdir: Read-only file system`；`findmnt` 显示 `ro`；无 `CAP_SYS_ADMIN` 无法 remount）。这也是 `acceptance/topics-p0.sh` 内置"data-dir 无产物则回退 workdir"分支的由来。当前复跑走的是 **data-dir 分支**（输出首行 `topics  : /home/wzh/go/lib-catalog-data/topics (data-dir)`）。
   → 工具链目录下**已无常驻 `topics/` 副本**（`ls .../lib-catalog/topics` → No such file or directory），全机仅 `lib-catalog-data/topics` 一处，不存在产物分叉。

---

## 1. 总览表（P0–P5）

> ⚠️ **本表是 19:1x–19:2x 的取证快照（R1 前口径），其中的节点数/边数/覆盖/断言计数均已被 R2 取代。**
> **当前终值请读 §11.2**（5,507 节点 / 105,414 边 / ①0.9246 ②0.9927 ③0.9286 / 147 项断言全绿）。
> 下表保留原样以维持取证溯源；引用任何一行前请先对照 §11.2。

| 阶段 | 验收脚本 | 复跑命令（前缀统一为 `cd /home/wzh/go/reasonix-scripts/lib-catalog && `） | 结果 | 关键数字 | 证据文件指针 |
|---|---|---|---|---|---|
| **P0** 对齐基线 | `acceptance/topics-p0.sh` | `bash acceptance/topics-p0.sh` | **PASS (pass=8 fail=0)** exit=0 | 12 跳覆盖 **0.902**（中位 0.938）∈ 验收带 [0.882, 0.922]；基线 23 行 | `topics/baseline-p0.txt`、`topics/baseline-p0-curve400.txt`、`topics/meta.json`(stages.P0)、`topics/acceptance-p0.log`、`topics/notes-first-attempt-20260918.txt` |
| **P1** 主题节点 | `acceptance/topics-p1.sh` | `bash acceptance/topics-p1.sh` | **PASS (pass=17 fail=0)** exit=0 | 节点 **5,187**（kw 4,838 / cls 349）；freq min/中位/max = 1/29/11534；噪声率 **0.04**（2/50）；id 连续、term 唯一 | `topics/nodes.json`、`topics/p1-build-report.json`、`topics/p1-sample50.txt`、`topics/meta.json`(stages.P1)、`topics/acceptance-p1.log` |
| **P2** 边构建 | `acceptance/topics-p2.sh` | `bash acceptance/topics-p2.sh` | **PASS (pass=27 fail=0)** exit=0 | 边 **99,268**；平均出度 **19.1378**／max 20／出度 0 节点 3；w ∈ [**0.1763, 1.0**]，w=1.0 共 11,294（11.38%）；卡 188,512 行、卡内 ≤5 主题、0 非法 | `topics/edges.csr.npz`、`topics/card_topics.jsonl`、`topics/p2-build-report.json`、`topics/p2-tuning.md`／`p2-tuning.json`、`topics/p2-self-test.txt`、`topics/meta.json`(stages.P2)、`topics/acceptance-p2.log` |
| **P3** 图验收与口径终裁 | `acceptance/topics-p3.sh` | `bash acceptance/topics-p3.sh` | **PASS (pass=18 fail=0)** exit=0 | 三口径 12 跳：① **0.8972**／② **0.9797**／③ **0.9200**（中位 0.9286/0.9883/0.9412，400 样本 seed=42）；p50 **1.986 ms**（门槛 <1 s）；连通 **4** 分量／最大 **5,184（99.94%）** | `topics/topics-report.json`、`topics/topics-report.txt`、`topics/topics-report-allseed.json`、`topics/meta.json`(stages.P3，含 verdict 全文)、`topics/acceptance-p3.log`、`acceptance/topics-p3-smoke.log` |
| **P4** 查询编排 | `acceptance/topics-p4.sh` | `bash acceptance/topics-p4.sh` | **PASS (pass=30 fail=0)** exit=0（脚本总 wall 12.7 s） | 四子命令 exit 0；扩散手算 1 跳 0.860000／2 跳 0.739600 精确吻合；存根确定性一致；无网络调用面；护栏 `--hops 13`／越界 id 均 exit 1 | `topics/p4-smoke.txt`、`topics/meta.json`(stages.P4)、`topics/acceptance-p4.log`、`topic_graph.py` |
| **P5** 交付与发行决策 | **无**（`acceptance/` 下不存在 `topics-p5.sh`；19:19:33 复查仍无） | 无脚本可跑 | **未覆盖（无验收脚本）** | 交付物实存：`docs-draft/`(3 件)、`export-sample/v1/topics/`(7 文件，manifest 自洽；本轮交叉验算通过)；`topics/README.md`(45,248 B) 与 `topics/INTERFACE-PROPOSAL.md`(10,045 B) 于 **19:18–19:19 落位**；**仍缺 P5 验收脚本** | `topics/docs-draft/README-draft.md`、`changelog-draft.md`、`interface-proposal.md`、`topics/README.md`、`topics/INTERFACE-PROPOSAL.md`、`topics/export-sample/v1/topics/manifest.topics.json`、`export_release.py` |

**合计**：已复跑 5 个脚本，**pass=100 / fail=0，exit 全 0**。P5 因无脚本，未纳入"全绿"计数。

---

## 2. 逐阶段小节

### 2.1 P0 · 对齐与骨架

**做了什么**：跑 `graph_report.py --data ~/go/lib-catalog-data` 复现 v1 文档图基线 → 落 `baseline-p0.txt`；建 `topics/` 骨架与 `meta.json` 初值；写 `acceptance/topics-p0.sh`。

**验收口径**（脚本 8 条断言）：① baseline 存在非空；② 含"12 跳"行且覆盖数可解析；③ 覆盖数 ∈ [0.882, 0.922]（= 90.2%±2%）；④ `meta.json` 存在、合法 JSON、`stage=="P0"`、`baseline` 指向 `baseline-p0.txt`。

**实测数字**：
- `baseline-p0.txt`（23 行）12 跳行原文：`12 跳: 覆盖均 0.902 / 中位 0.938` → 落在验收带内；与交接文档 §1.3「12 跳同簇覆盖 90.2%」**完全吻合**。
- 基线其他数字：节点 188,512／出度 10／边 1,885,120／互链率 0.423；无向分量 3，最大 188,488（99.99%）；簇内单一连通分量 397/400；衰减 1/2/3 跳 0.730/0.636/0.584（随机基线 0.408）；耗时 17 s。
- **补充 400 簇口径复跑**（`baseline-p0-curve400.txt`）：12 跳覆盖均 **0.911**、中位 0.940，仍在带内（耗时 69 s）。这一条解释了 §1.3 的"400 抽样"与脚本默认 100 抽样的差异，口径已登记进 `stages.P0.notes`。
- **基线完整性自证**：`stages.P0.baseline_sha256 = ff2a32ad00761499e328ad46803ed8796b4da65c53fc72fecc7877b763f2fa06`；本轮独立重算 `baseline-p0.txt` 的 sha256 **与该登记值逐字节一致**。

**证据文件**：`topics/baseline-p0.txt`、`baseline-p0.start`、`baseline-p0-curve400.txt`、`baseline-p0-curve400.start`、`meta.json`(stages.P0)、`acceptance-p0.log`、`notes-first-attempt-20260918.txt`。

**已知限制**：① 正式基线走脚本 argparse 默认 100 抽样（报 `0.902`），§1.3 的 400 抽样口径由 supplement 单独复跑（`0.911`）补齐，两者都在带内但**不是同一个抽样**，引用时勿混用；② P0 当期数据目录为只读挂载，产物实际落工具链工作目录后迁移，路径解析依赖脚本的 data-dir/workdir 双分支（当前已统一到 data-dir）。

### 2.2 P1 · 主题节点构建

**做了什么**：`topic_build.py` 三源合一抽主题词（A=400 簇 keywords／B=TF-IDF 高分词，top 10/卡 + bigram 合并／C=CLC `cls2` 类目），做 NFKC 归一、长度 1–16、988 条停用词、频控与英文质量门，产出 `nodes.json`；再对 50 词分层抽检噪声率。

**验收口径**（脚本 17 条断言）：`nodes.json` 合法数组；节点数 ∈ [5000, 20000]；schema 恰好 7 字段（id/term/type/freq/cluster/cls/sources）；id 连续 0..n-1；term 全量唯一；无 freq=0 孤立节点；type 仅 kw/cls 且两者均非空；**A1 一致性**（8 项计数/频次统计与构建报告逐项比对）；`meta.json` 顶层 `stage` 仍为 `P0`（旧脚本兼容）+ `stages.P1` 含 params/counts/noise_rate，噪声率 ≤10%。

**实测数字**：
- 节点 **5,187** = kw **4,838** + cls **349**，落在目标带 5k–20k 内（未截断：`truncated=false`）。
- 三源贡献：`A+B` 954／`B` 3,481／`A` 403／`C` 349；A 源原始 3,345 去重、保留 1,518（剔零频 429／被包含碎片 894）；B 源合并后 224,511 去重 → df≥10 得 10,862 → 收 4,435（剔 CJK 2,822／CJK 被包含 1,801／CJK 超 df 464／英文质量门 1,787）。
- 频次：min 1／p25 17／**中位 29**／p75 78／p90 267／max 11,534；freq=0 为 0。
- 噪声率 **0.04**（50 词分层抽检：高频 17／中频 17／低频 16，判噪声 2 条：`重大`（泛形容词）、`业化`（跨词残片））→ 远低于 10% 门槛。
- A1 一致性 8/8 CHECK OK（`counts.nodes/kw/cls/sources`、`freq.min/median/max/p25`）。

**证据文件**：`topics/nodes.json`、`p1-build-report.json`（+ 迭代留痕 `p1-build-report-v2.json`、`p1-build-report-min15.json`、`p1-build.log`、`p1-build-v2.log`、`p1-build-min15.log`）、`p1-sample50.txt`、`p1-sample50-candidates.txt`、`p1-diag300*.txt`、`p1-scan*.txt`、`meta.json`(stages.P1)、`acceptance-p1.log`。

**已知限制**：① 噪声率是**人工判定**的 50 词样本（脚本只做结构断言），样本量小、判定主观，2/50 的置信区间宽；② 词表内**未见"机器学习"这类高频复合词**（详见 §7-⑧）；③ 英文质量门（min_freq 200／min_len 9／min_cls_rep 0.6）为经验阈值，剔了 1,787 个英文候选，未做敏感性分析。

### 2.3 P2 · 边构建

**做了什么**：遍历 188,512 卡 top-5 主题统计共现对，合成三类边（① 同书共现 `w1=log1p(min(共现书数,50))/log1p(50)`；② 同簇加成 `w2=0.3×log1p(簇内共现)/log1p(50)`，sum 口径；③ 主题→`cls2` 层级边 w=1.0 单向），按**关联度** `count/√(freq_u·freq_v)` 排序做 top-20 截断，落 CSR；并跑 6 组调参矩阵（`p2-tuning.md`）。

**验收口径**（脚本 27 条断言）：dtype 钉死 `int64/int32/float32`；CSR 结构自洽（`indptr[0]=0`、`indptr[-1]=nnz`、单调不减、`indices∈[0,n)`、长度 n+1）；权重 ∈[0,1] 且存在 w=1.0（层级边）；**平均出度 ≤20 且 max ≤20**；`card_topics.jsonl` 行数=卡数、全合法 JSON、id 合法不重复、每卡 ≤5；构建报告与边表 nodes/edges 一致 + 自测字段齐；`meta.json` 有 `stages.P2`。

**实测数字**：
- 边 **99,268**；n=5,187；**平均出度 19.1378**（≤20 ✓），中位 20／p90 20／**max 20**；出度 0 的孤立节点 **3**。
- 权重：min **0.1763**／中位 0.4093／均值 0.5187／max **1.000000**；w=1.0 共 11,294 条（11.38%，层级边饱和共现）。
  > ⚠️ **R2 终值（R2-C 重建后）**：min **0.1763**／中位 **0.2292**／均值 **0.3656**／p90 0.8734／max **1.0**；`w=1.0` 共 **8,487** 条（**8.05%**）。上行数字为 **R1 后**历史值。
- 边型构成：共现对 330,426（其中 kw-kw 245,779，占最终边 74.38%）／同簇加成命中 9,167（**新增对 0**）／层级边 4,832（6 个 kw 无层级边）。
  > ⚠️ **R2 终值**：distinct 对 **349,680**（kw-kw **261,376**）／同簇命中 **10,102**／层级边 **5,151**（**7** 个 kw 无层级边，**登记 = 实存、零丢失**）。上行数字为 R1 后历史值。
- 共现计数：中位 2／均值 5.307／max 2,052；**饱和对（≥cap 50）3,878 = 1.17%**；单次共现对占 13.22%。
  > ⚠️ **R2 终值**：中位 **1**／均值 **3.309**／max **1,221**；**饱和对 2,302 = 0.66%**；单例对占 **62.68%**。上行数字为 R1 后历史值。
- 证据链 `card_topics.jsonl`：**188,512 行**、BAD_JSON=0／BAD_ID=0／DUP=0／TOO_MANY=0；尺寸分布 `{0:22573, 1:32886, 2:38925, 3:34190, 4:25063, 5:34875}`。
  > ⚠️ **R2 终值分布**：`{0:21607, 1:31456, 2:37907, 3:34090, 4:25595, 5:37857}`（空卡 **21,607 = 11.46%**；链接总数 **501,205**）。上行分布为 R1 后历史值。
- 自测（**R2-C 终值**）：`avg_out_degree_le_max=true`；12 跳覆盖（**400 采样 / kw 源点 / `pool_size=5158`**）**0.9246**、
  **全节点源点（仍是 400 采样 / `pool_size=5507`，非全量）0.9202**、同簇∪类目 **0.9927**、无向闭包 **0.9286**；
  **穷举全部 5,507 源点：① 0.9237 / ② 0.9867**（`topics-report-exhaustive.json`）；连通 4 分量／最大 **5,504（99.9455%）**。
  - （R1 后同列数字为 0.9188 / 0.9218 / 0.9912 / 0.9200，kw 池 4,838 / 全节点池 5,187，穷举 ①0.9194 / ②0.9856；R1 前为 0.8972 / 0.9030 / 0.9797，见 §10 对照表）

- 热门节点邻域抽检成立：`TP3`(cls,freq 11534)→security/software/计算机/web/computer/linux/computing/windows；`中国`(kw,10379)→中国文化/china/中国民族/文化/chinese/文学/发展；`I2`(cls,8849)→文学/小说/散文/演义/红楼梦/唐诗。
- 调参矩阵（`p2-tuning.md`，变体固定 aug）：
  > ⚠️ 下表为 **R1 修复前**的调参矩阵（`p2-tuning.json`，未随 R1 重算）；R1 后主产物数字见 §10。

  | 配置 | 平均出度 | 边数 | 12 跳(kw,400 采样) | 12 跳(全节点,400 采样) | 同簇∪类目 |
  |---|---|---|---|---|---|
  | weight/20（§3.2 字面） | 19.138 | 99,268 | 0.7744 | 0.7874 | 0.8429 |
  | weight/30（handoff 回退） | 27.814 | 144,272 | 0.8553 | 0.8670 | — |
  | **assoc/20（主产物）** | **19.138** | **99,268** | **0.8972** | **0.9030** | **0.9797** |
  | assoc/30 | 27.814 | 144,272 | 0.9028 | 0.9088 | 0.9845 |
  | assoc/20+mutual1/3 | 19.138 | 99,268 | 0.8972 | 0.9030 | 0.9797 |
  → 结论：**只换排序键（权重→关联度）即从 0.7744 提到 0.8972，且平均出度更低**；handoff 写的"出度 20→30"回退只到 0.8553，**实测无效**（详见 §7-③）。

**证据文件**：`topics/edges.csr.npz`、`topics/edges.variant-spec.csr.npz`（变体留档）、`card_topics.jsonl`、`p2-build-report.json`、`p2-self-test.txt`、`p2-tuning.md`／`p2-tuning.json`／`p2-tuning.log`／`p2-tuning-*.json`（6 组）、`meta.json`(stages.P2)、`acceptance-p2.log`。

**已知限制**：① 共现封顶 50 使 1.17% 的饱和对权重并列 1.0，失去区分度；② 同簇加成在 sum 口径下是"加成项"、在 max 口径下恒被共现边支配（`b3_new_pairs=0`）；③ 「平均出度 ≤20」规格与 P3 回退方案（20→30）天然冲突（§7-③）；④ 排序键从 weight 改为 assoc 属**施工期口径再选择**，虽权重公式未动，但已使"§3.2 字面口径"不再等于主产物，文档引用时需注明 `--rank-by`。

### 2.4 P3 · 图验收与口径终裁

**做了什么**：`topics_report.py` 对主题图做四项体检——12 跳同簇覆盖（400 随机 kw 源点，seed=42，三口径并列）、连通性、衰减曲线、单查询性能；再由 `topics_meta.py` 把三口径数字与**裁定全文**登记进 `meta.json` 的 `stages.P3`。

**验收口径**（脚本 18 条断言）：报告合法且 `stage=P3`；三口径覆盖数字齐备且均 hop=12；**硬门槛取 ②（主簇∪类目）≥0.90**；**①（仅主簇）必须并列存在且 <0.90，禁止被口径改写**；性能 p50 <1000 ms；连通/衰减/CSR dtype 字段齐；`meta.json` `stages.P3` 含三口径 + `verdict` + 性能 + report 指针。

**实测数字**：见 §3 专节（三口径、衰减、连通、性能全量）。

**证据文件**：`topics/topics-report.json`、`topics-report.txt`、`topics-report-allseed.json`（全 5,187 节点源点口径）、`meta.json`(stages.P3)、`acceptance-p3.log`、`acceptance/topics-p3-smoke.log`。

**已知限制**：① 报告文本层仍打印 `[门槛 ≥0.90: FAIL]`（该行按 ① 口径输出），与"硬门槛取 ② → PASS"的裁定并存，**易误读**，以 `stages.P3.verdict` 为准；② P3 报告生成于 18:53，早于 P4（19:13），其 `definition`/`csr_spec` 快照不含 P4 内容（正常，阶段产物按阶段冻结）；③ 覆盖率对分母口径极端敏感（同一张图 0.7744→0.9797），**任何跨报告引用必须带口径标签**。

### 2.5 P4 · 查询编排

**做了什么**：`topic_graph.py` 实现四命令 `search / around / graph / summarize`，≤12 跳加权 BFS（`w_hop = w_parent × edge_w × 0.86`，阈值 0.05，预算 ≤50k 节点），输出分层邻域 + `card_topics` 反查书证据；`summarize` 为 **LLM 接口存根**（默认 `TOPIC_LLM=off`，不触网、确定性）。

**验收口径**（脚本 30 条断言）：四子命令 exit 0；**扩散手算吻合**（1 跳 `1.0×edge_w×0.86`、2 跳连乘 `×0.86²`、源点恒 1.0）；存根非空 + 两次逐字节一致 + 含区域统计 + 标注"待与作者讨论" + 默认 off；**无网络调用面**（静态检查 `topic_graph.py` 与 P2/P3 脚本）；护栏（`--hops 13` 拒、越界 topic_id 拒）；`--json-out` 结构自洽（无悬空端点、种子在子图内、w∈[0,1]、含 stats）；**近词扩展**（非词表查询触发 TF-IDF 扩展、词表内整词不触发、`--expand no` 可关）。

**实测数字**：
- `SRC=0(经济) DST=4(经济学)`，`EDGE_W=1.000000` → 1 跳 `HOP1_GOT=0.860000 = 1.0×1.0×0.86` ✓；2 跳经 `923(econometrics)` `EDGE_W2=1.000000` → `HOP2_GOT=0.739600 = 0.86²` ✓；`SEED_SCORE=1.000000` ✓。**扩散规则实现与设计式精确一致（<1e-9）**。
- 存根：12 行输出、两次复跑逐字节相同、含"扩散规则/区域规模/权重分布/层级/代表主题/证据书样例"、默认 off。
- 护栏：`--hops 13` → exit 1（提示 `1..12`）；`topic_id=99999` → exit 1（提示越界）。
- `graph 65 --hops 1 --json-out`：21 节点 / 153 边，KEYS_OK／ENDPOINTS_OK／SEED_IN／W_RANGE_OK／STATS_OK 全 True。
- 近词扩展抽测：`机器学习 入门` → 字面命中 2 + 扩展 8（200 卡命中 1,811 卡）；`量子 科普` 同样触发；对照 `量子`（词表整词）**不触发**；`--expand no` 关闭成功；`--json` 含 `expanded_hits`。
- 逐例 wall / 内部耗时（`p4-smoke.txt`，14 例）：命令 wall **0.61–1.11 s**；扩散/图内部 `elapsed_ms` **187.5–223.8 ms**（187.5/189.8/192.5/195.3/223.8）。本轮复跑对应值 203.8/205.5 ms（机器负载略高）。

**证据文件**：`topics/p4-smoke.txt`（10 例抽测 + 4 例对照，含命令原文与耗时）、`meta.json`(stages.P4)、`acceptance-p4.log`、`topic_graph.py`、`topics/docs-draft/interface-proposal.md`。

**已知限制**：① **"人工判定相关率 ≥8/10"这一条无法自动断言**——`p4-smoke.txt` 记录的是输出与耗时，相关性判定为人工结论，脚本未覆盖；② `summarize` 是存根，**未接任何模型**；③ 近词扩展依赖 v1 TF-IDF 索引（§7-⑦）；④ 抽取的 10 条查询以中英文常见主题为主，长尾/错别字/多语言查询未抽测；⑤ P4 二期才补上"近词扩展"，`docs-draft/` 两件文档仍写着"P4 ⏳ 未实现"（§7 不一致清单）。

### 2.6 P5 · 交付与发行决策

**做了什么**（状态为"进行中"）：写 topics README 草案、接口协议草案、工具链 README 变更记录草案；`export_release.py` 增加 topics 导出版分支（只生成、不发布）；生成导出版样例；汇总验收报告（即本文件）。

**验收口径**：交接文档 §4-P5 要求「文档齐、脚本可复跑（acceptance 全绿）、未触碰 v1 既有文件（git 内 diff 证明）」。**注意：`acceptance/` 下不存在 `topics-p5.sh`，P5 无验收脚本可跑**，故本节结论为"人工实读核验"，不是脚本结论。

**实测数字/状态**：
- 文档草案实存 3 件：`docs-draft/README-draft.md`（30,314 B，18:53）、`docs-draft/interface-proposal.md`（8,433 B，18:55）、`docs-draft/changelog-draft.md`（15,978 B，18:56）。
- **`topics/README.md` 落位状态（两阶段）**：19:17 快照时**不存在**（`ls` → No such file or directory），当时 P5 清单里的正式 README 只有 `docs-draft/` 草案；**19:19:26 施工方补落 `topics/README.md`（45,248 B）**，同时 19:18:16 落 `topics/INTERFACE-PROPOSAL.md`（10,045 B）。⚠️ 这两件新增文件**未经任何验收脚本校验**（P5 无脚本，见下），本轮只做了"存在性 + 字节数"确认，**未审其内容与 `docs-draft/` 草案的一致性**。
- 导出版：`export_release.py` 的 `export_topics()` 产出 `nodes.json` + `edges_indptr.i64.bin` + `edges_indices.i32.bin` + `edges_weights.u8.bin`（uint8 量化，还原式 `w = v/255`）+ `card_topics_indptr.i32.bin` + `card_topics_ids.i32.bin` + `meta.json` + `manifest.topics.json`（含逐文件 sha256）。
- 样例实存于 `topics/export-sample/v1/topics/`（生成于 **19:15:35**，7 文件 + manifest），规模 3.9 MB。**本轮独立交叉验算全部通过**：
  - `edges_indices.i32.bin` 397,072 B ÷ 4 = **99,268** = nnz ✓
  - `edges_weights.u8.bin` 99,268 B = nnz ✓
  - `card_topics_indptr.i32.bin` 754,052 B ÷ 4 = **188,513** = 卡数+1 ✓
  - `card_topics_ids.i32.bin` 1,951,732 B ÷ 4 = **487,933** 卡-主题链接 = 由尺寸分布 `1×32886+2×38925+3×34190+4×25063+5×34875` 独立推导值 ✓
  - manifest 声明 `nodes 5187 / edges 99268 / avg_outdeg 19.138 / max_outdeg 20 / cards 188512`，与 P1/P2 产物一致 ✓
- **发行决策未定**：`lib-catalog-release/` 仍只有 `v1/`（mtime 14:01）与 `lib-catalog-data-v1.tar.gz`（98 MB），**无 v2；topics 是否进 data-v2 发行仍待作者讨论**（§7-⑪）。

**证据文件**：`topics/docs-draft/*`、`topics/export-sample/v1/topics/*`、`export_release.py`（`--topics` / `--topics-only`）、本报告。

**已知限制**：① 无 `topics-p5.sh`，P5 无自动化验收门槛；② `topics/README.md` 与"工具链 README v3 变更记录"仍为草案，未并入正式 README；③ 导出版样例已生成但**未发布**，且样例目录是施工期间（19:15:35）生成、未经任何验收脚本校验（本轮为人工交叉验算）；④ `docs-draft/interface-proposal.md` 的默认模式写"`mock`（默认）"，与实际实现"未设 `TOPIC_LLM` 即 `off`"**矛盾**（§7 不一致清单）。

---

## 3. P3 口径终裁（专节）

### 3.1 三口径数字（400 样本，seed=42，source_type=kw，hop=12）

数据来源：`topics/topics-report.json`（`coverage.final` / `final_union` / `final_undirected`）、`topics/topics-report.txt`（三口径对照表）、`topics/meta.json` 的 `stages.P3.coverage`。三处数值一致，本轮已逐项复核。

| 口径 | 定义（分母） | 12 跳覆盖 **均** | 12 跳覆盖 **中位** | `pass` 字段 | 角色 |
|---|---|---|---|---|---|
| **①仅主簇**（有向） | \|可达 ∩ {cluster==c}\| / \|{cluster==c}\| | 0.8972 → 0.9188 → **0.9246** | 0.9286 → 0.9412 → **0.9474** | `false` → `true` | **R2-C 终值**；**与 v1 文档图 0.902 属「不同图 + 不同抽样口径」，非同口径对比**（不作为对比结论） |
| **②主簇∪类目**（有向） | \|可达 ∩ ({cluster==c} ∪ {cls==C})\| / \|{cluster==c} ∪ {cls==C}\| | 0.9797 → 0.9912 → **0.9927** | 0.9883 → 0.9963 → **0.9966** | `true` | **硬门槛口径**（§4-P3 原文「主题的簇 = 主簇或分类」） |
| **③无向闭包** | 同簇分母，可达域换成无向连通闭包 | 0.9200 → **0.9286** | 0.9412 → **0.9474** | `true` | 方向性诊断列 |

> 列内三值依次为：**R1 前 → R1 后 → R2-C 终值**（R2-C 基于 R2-A 新数据：**5,507 节点 / 105,414 边**）。

精确值（`topics-report.json`，**R2-C**）：① `0.9246404381082953`（中位 `0.9473684210526315`）／② `0.9927011191897308`（中位 `0.9965576490105463`）／③ `0.9286324252877824`（中位 `0.9473684210526315`）；
`gate = 0.9`；`samples = 400`；`source_type = kw`；**`pool_size = 5158`（kw 源点池）**。
（R1 后精确值 ① `0.9187989336293301`／② `0.9911547523415218`／③ `0.9200401344574874`，池 4,838。）

逐跳曲线（kw 源点，均值，**R2-C**）：① …→第 7 跳起饱和于 **0.9246**；② …→**0.9927**（第 12 跳）；③ 第 4 跳即达 **0.9286**。
（R1 后曲线：① 第 6 跳 0.8969 ≈ 12 跳 0.8972 的历史读法见 §10.2；逐跳明细以 `topics-report.json` 的 `coverage.per_hop` 为准。）

### 3.2 裁定（`meta.json` → `stages.P3.verdict`，全文原样引用）

> P3 口径终裁（主会话 2026-09-18，R1 后更新）：硬门槛按 §4-P3 原文读法「主题的簇 = 主簇或分类」= ②（主簇∪类目）→ 判定 PASS，放行 P4；①（仅主簇）作为并列严格观察项，**R1 修复后已自然过线（400 采样 0.9188 / 穷举 5,187 源点 0.9194）**；① 与 v1 文档图的 0.902 **属不同图、不同抽样口径，不构成同口径对比**；不调 P2 去救 ①：出度 20→30 会破「平均出度 ≤20」规格且实测收益仅 +0.6pp（已证伪）；变体 CSR（`edges.variant-spec.csr.npz`）保留在数据目录作研究记录，不进发行。

配套登记字段：`stages.P3.generated_at = 2026-09-18T18:53:07+0800`、`report_file = topics/topics-report.json`、`config = {samples:400, hops:12, seed:42, source_type:kw, perf_samples:50, max_outdeg:20, random_baseline:true}`、`coverage.cluster_only.role = "严格观察项（与 v1 基线 0.902 基本持平）"`、`coverage.cluster_or_cls.role = "硬门槛口径（§4-P3 原文「主簇或分类」）"`。

### 3.3 验收脚本对裁定的固化方式（防口径漂移）

`acceptance/topics-p3.sh` 不"事后合理化"，而是**把裁定写成可复跑断言**：

1. 断言 ②（`final_union.coverage_mean`）≥ gate（读 `coverage.gate`，缺省 0.90）→ `[PASS] 硬门槛口径 ②（主簇∪类目，§4-P3 原文）= 0.9796500966591521 ≥ 0.9 → PASS`；
2. 断言 ① **必须 < 0.90** → `[PASS] 严格观察项 ①（仅主簇）= 0.897210909202034 < 0.90，如实并列未被口径改写（与 v1 基线 0.902 基本持平）`。
   → 意味着：**若日后有人把 ① 悄悄"修"到 ≥0.90 却又不同步更新裁定文本，脚本会由 PASS 转为走 `info` 分支提示复核**；反过来，若有人试图把门槛偷偷从 ② 换回 ①，断言 1 会直接 FAIL。这是本阶段最有价值的一条防漂移设计。
3. `stages.P3` 必须同时含三口径数字 + `verdict` 非空 + 性能字段 + report 指针，缺一即 FAIL。

### 3.4 补充口径（非门槛，独立证据）

`topics-report-allseed.json`：**仍是 400 采样**，但把源点池从 kw（`pool_size=5158`）扩到**全节点（`pool_size=5507`）**（`dropped_no_cluster=0`）。
**R2-C 终值**：① **0.9202**（中位 0.9428）／② **0.9854**（中位 0.9959）／③ **0.9247**（中位 0.9444）（R1 后为 0.9218 / 0.9841 / 0.9232，池 5,187）；
**穷举全量 5,507 源点**（`topics-report-exhaustive.json`）：① **0.9237** ／② **0.9867**（R1 后穷举 ① 0.9194；R1 前 ① 0.8992）。
⚠️ **不要把「全节点源点」读作「全量统计」**——它**仍是 400 个源点的抽样**，只是把**源点池**从 kw 节点（5,158）扩到全部节点（5,507）。
**三个口径的「源点池 / 样本数」必须成对声明**：kw×400、全节点×400、穷举×5507（唯一全量口径）。
→ 该列说明：**不同抽样口径（kw 源点 vs 全节点源点 vs 穷举全量）的读数不可混比**；R2-C 三口径均过 0.90（0.9246 / 0.9202 / 0.9237），R1 后亦均过线（0.9188 / 0.9218 / 0.9194），R1 前则分别卡在 0.8972 / 0.9030 / 0.8992。
「与 v1 文档图 0.902 差 0.28pp」的说法已作废：那是**不同图 + 不同抽样口径**（v1 = 188,512 节点文档图 / 100 簇抽样），**非同口径对比**。

---

## 4. 性能与结构结论

| 指标 | 实测 | 门槛/基线 | 判定 |
|---|---|---|---|
| P3 12 跳加权 BFS 单查询 p50 | **1.986 ms**（p95 2.395 ms，max 2.67 ms）〔R2-C 终值 **2.580 / 3.740 / 5.94 ms**，见 §11.2〕 | <1 s（理想 <300 ms） | ✅ 富余约 500× |
| P3 报告整体耗时 | 7.5 s（400 样本 × 三口径 × 12 跳） | — | ✅ |
| P4 命令 wall（逐例，`p4-smoke.txt`） | **0.61–1.11 s** | — | ✅ |
| P4 扩散/图内部 `elapsed_ms` | **187.5–223.8 ms**（本轮复跑 203.8/205.5 ms） | — | ✅ |
| P4 验收脚本总 wall | **12.7 s**（含 22 次 Python 进程冷启 + 存根双跑） | — | ✅ |
| 节点规模 | **5,187**（kw 4,838 / cls 349） | 目标带 5k–20k | ✅ |
| 边 / 平均出度 / max 出度 | **99,268** / **19.1378** / **20** | 平均 ≤20 | ✅ |
| 边权范围 | **[0.1763, 1.0]**，w=1.0 占 11.38% | 归一 ∈[0,1] | ✅ |
| CSR dtype | `int64 / int32 / float32`（n+1=5,188 / nnz 99,268） | 钉死 | ✅ |
| 连通性 | **4 分量**，最大 **5,184 = 99.94%**（0.9994216310005783），单点分量 3 | v1 为 3 分量/99.99% | ✅ 正常 |
| 衰减（1/3 跳均分） | **0.3058 / 0.0781**（R1 后；R1 前 0.4427 / 0.2401）；有效逐跳因子 = 最优路径平均边权 × 0.86 | 理论线 0.86^hop | ✅ 见下注（含**数值容忍定义**） |
| 衰减系数 | **0.86**（`DECAY_DEFAULT`，`--decay` 可覆盖） | 源自 v1 文档图实测 | ⚠️ 见 §7-⑥ |
| 平均边权 | 全局 0.5187 / 最优路径上 0.5304 | — | ℹ️ |

**衰减容忍定义（终审④要求，已同步登记 `meta.json#stages.P3.caliber_freeze.decay_tolerance`）**：① 首跳平均得分 ≥ **0.30**；② 逐跳**有效因子**（= 最优路径平均边权 × 0.86）落在 **[0.30, 0.90]**；③ 第 9 跳起无新增节点视为正常饱和；④ 实测值不要求贴合 `0.86^hop` 理论线——该线假设边权恒为 1，本图边权均值 0.3647<1，故「平均得分」系统性低于理论线，比较只能看「有效逐跳因子」列。实测（R1 后）：首跳 0.3058 ✅、有效因子 0.306/0.397/0.364 ✅、第 9 跳饱和 ✅。

**衰减读法**（`topics-report.txt` 原文要点）：0.86 是**逐跳因子**，可比量是"有效逐跳因子 = 最优路径平均边权 × 0.86"（首跳 0.4427）；平均得分是 `edge_w × 0.86` 的连乘，因边权均值 0.5148 < 1 会额外压低曲线，故"平均得分"必然低于纯 `0.86^hop` 理论线 —— **比理论线应看"有效逐跳因子"列**。第 9 跳起已无新增节点（12 跳预算远超实际需要，深跳饱和）。随机游走基线 0.4531/0.3158/0.2313（1/2/3 跳），实测略低于基线之上/附近，衰减形态合理。

**结构性结论**：① 覆盖率在**第 6 跳即饱和**（0.8969 ≈ 12 跳 0.8972）→ **瓶颈不是跳数**；② 无向闭包 ③ 0.9200 仅比 ① 0.8972 高 2.3pp → **方向不对称不是主因**；③ 出度 20→30 仅 **+0.6pp**（0.8972→0.9028）→ **出度也不是主因**；④ 残余缺口主要是**孤立/弱连通簇**（4 分量、3 个出度 0 节点）；⑤ 因此"12 跳 ≤12"约束与性能均无压力，真正决定达标读数的是**分母口径**（§3）。

---

## 5. v1 未触碰证明（sha256 + mtime）

### 5.1 举证方式说明

工具链目录、`reasonix-scripts/`、`lib-catalog-data/` **三者均非 git 仓库**（`git rev-parse --show-toplevel` 全部返回 `fatal: not a git repository`），故交接文档 §4-P5 要求的"git diff 证明"**在本机不可执行**。本轮改用 **sha256（内容指纹）+ mtime（时间指纹）** 双证据：

- **时间判据**：主题图施工起点 = 交接文档 `TOPIC-GRAPH-HANDOFF-20260918.md` 定稿 **2026-09-18 17:27**；首个施工产物 `topics/baseline-p0.start` **17:31**；首个数据产物 `topics/nodes.json` **18:12**。故"未触碰"的 mtime 割线取 **2026-09-18 14:01**（v1 发行包 `lib-catalog-release/v1` 与 `export_release.py` 原始 mtime）。
- **内容判据**：对每个文件独立重算 sha256，作为事后比对的锚点（本报告即为首份独立快照）。
- **主会话对账**：`meta.json`（`stages.P0.notes`）记录施工方结论"**v1 既有文件（cards.jsonl / index/* / clusters.json / shelves.json / subjects.json）全程只读，未改动**"；主会话另登记了基线文件的哈希 `baseline_sha256 = ff2a32ad00761499e328ad46803ed8796b4da65c53fc72fecc7877b763f2fa06`，**本轮已独立重算该文件并与其逐字节一致**（§2.1）。
  ⚠️ 说明：`meta.json` **未登记 v1 数据文件本身的 sha256 清单**，故上表 v1 哈希是**本轮首次独立计算**、无可比对的"施工前登记值"；内容一致性的强证据来自 mtime 全部早于施工起点，而非与某份既有哈希对账。此点如实标注，不作过度声明。

### 5.2 v1 数据文件（只读，禁止改动）—— 16 个

| 文件 | sha256 | mtime | 字节 |
|---|---|---|---|
| `cards.jsonl` | `9e9dffd2cf237b2ab7db24444154881b89d7afd352df171c64a28b8e7093fcfd` | 2026-09-18 13:21:24 | 68,268,212 |
| `clusters.json` | `7a28d434a2625a6a680580d1ad6358e282dcebbaf2438991044f9b6c06fa966c` | 2026-09-18 13:55:06 | 214,022 |
| `shelves.json` | `a9c70efcb6e421415a7584d1d59517bc6298579790e69fea974ed3e4d680b16f` | 2026-09-18 13:21:24 | 91,203 |
| `subjects.json` | `5920acf22678d672fced518dace1b05e531c4c668e26e8666d648ee79d432059` | 2026-09-18 13:21:24 | 15,255 |
| `compile_report.json` | `7144fa75daf5cec40a2d284754c08ddb215daedf59e9ef06f23d0c393868c2b4` | 2026-09-18 13:21:24 | 443 |
| `index/embeddings.npy` | `2bc123416f2673007dc54452f51205800fdf7171ea5ddb99a05dea43f318e2f5` | 2026-09-18 13:40:46 | 386,072,704 |
| `index/tfidf.npz` | `c62aa8af6ec08516372e26ded792adb51ef04be46df589d702f4c5d359fc855d` | 2026-09-18 13:34:56 | 19,712,358 |
| `index/knn_csr.npz` | `579b7561ee8d05de86c5f6bcde27ff17de1401ce760ec43db8ec1645aafc59c1` | 2026-09-18 13:55:06 | 6,854,780 |
| `index/mms_index.json` | `d9355d7342f4495397483443aaaa737af039ee7851072b4a12edb751f2b4aa31` | 2026-09-18 13:34:56 | 5,544,250 |
| `index/vocab.json` | `aeb86587d95d8b53a538e6df9c86cd6340c51c4c3833e6e44c6d9872c2024c6b` | 2026-09-18 13:34:56 | 3,539,087 |
| `index/offsets.npy` | `06f669651e27c22119791cd9c402e96a95fef100a6bd22d7e7e8464231b911c4` | 2026-09-18 13:34:56 | 1,508,224 |
| `index/idf.npy` | `a48dc40d8a78710d1c01953665494f40f60ac993c453b6b191a8139e73ac0973` | 2026-09-18 13:34:56 | 1,353,560 |
| `index/cluster_centroids.npy` | `bd850385a8e7e32755df602e2ed4fa722cd0caaa3c3d723044d32646a09890be` | 2026-09-18 13:55:06 | 819,328 |
| `index/clusters.npy` | `f54fe2b5f65ca772c15a26835f72abeb713c951ca97fe754563b1879a3ac0ed7` | 2026-09-18 13:55:06 | 754,176 |
| `index/graph_meta.json` | `9dc9ca221c202ec9c78afcc71eed9ce4fd68ce2e8789b1547b629d40d76022de` | 2026-09-18 13:55:06 | 235 |
| `index/meta.json` | `c6a1b122b65944ea29f5b348ca78cbe2812f64807a12159a037247fc70826375` | 2026-09-18 13:40:46 | 168 |

### 5.3 工具链既有脚本（v1/v2 期，本项目不应改动）—— 5 个

| 脚本 | sha256 | mtime | 字节 |
|---|---|---|---|
| `build_graph.py` | `4749f526e33b784bcda176e73ea96b6c06a61ef1b420b901a693368cb458e49e` | 2026-09-18 13:49:08 | 11,953 |
| `catalog_vector.py` | `b41e2da26ad5b98f18471e2ff1434d162b635e9b90aee4124dce769388b57327` | 2026-09-18 13:34:47 | 28,353 |
| `graph_report.py` | `c2e91e343436c3f1188ebcf698fc3486dc54583cba91392e54de27d376959724` | 2026-09-18 13:57:56 | 5,760 |
| `compile_cards.py` | `4551856dd079923b6ad84b7685350f15a08c38a2647b58d57295d9b693d17b78` | 2026-09-18 13:31:49 | 14,759 |
| `check_completeness.py` | `2a2163ed52a90f5fa91d454b8b81f78108e8d63d5365cc45b8dfb69d1c6aa31f` | **2026-09-16 16:46:38** | 12,475 |

### 5.4 结论

- **全部 21 个 v1 文件/脚本的 mtime 均 ≤ 2026-09-18 14:01** ✓；实测**最大 mtime = 13:57:56**（`graph_report.py`），比 14:01 割线还早 3 分钟，比主题图施工起点（交接文档 17:27 / 首产物 17:31）**早约 3.5 小时**。
- 未发现任何 v1 数据文件在施工期（17:27 之后）被改写：mtime 分布集中在 13:21–13:57，`index/*` 全部 13:34–13:55，`check_completeness.py` 甚至在 09-16。
- P0 施工记录另有一层旁证：当期数据目录为**只读挂载**（`mkdir: Read-only file system`），物理上不可能写入（§0.3）。

### 5.5 单列说明：本轮授权改动（**不计入"未触碰"清单**）

按任务书，以下文件属 **P5 授权改动**，与"未触碰"判定无关，单列如下：

| 文件 | 变更前 | 19:2x 取证时点 | **R2-D 同步时点（当前）** | 说明 |
|---|---|---|---|---|
| `export_release.py` | mtime **14:01**，12,990 B（v1 期版本） | 19:15:30，18,957 B，sha256 `a45b57c6b16e5f53ccd046e0fd032633cbb44ae03066bdc75e3dcce9c877360a` | **21:31:10，25,596 B**，sha256 `221831679c9a0e16eaa858aa90ccb24715e8fe4d3889d4a05e85c78e0aa38c81` | 追加 `export_topics()` 与 `--topics`／`--topics-only`（只生成、不发布）——**P5 计划内改动**；**R2-C 又修 AUDIT-EXPORT E1/E2/E5/E8/E10**（随包 meta 同源绑定、`--strict`、量化登记、`package_kind`、NaN/越界拒绝）。⚠️ 因它是 v1 期文件且原 mtime=14:01，**不可再用"mtime ≤14:01"作其未触碰判据**，已按授权改动单列 |
| `topic_build.py` | — | 19:03:18，36,084 B，sha256 `26864b3c926181584109a914bd7ecb2df2c1b8bae56ef948a86b081db1307ccb` | **21:44:23，39,054 B**，sha256 `1f0da80e8d9a3fbbdeb48e29fc66ffe7e58ec7941a1196881728d37a352ed8e2` | P1 工具在施工期内的后续微调；**R2-A** 修 F1/F1b + F2/F2b；**R2-D** 修 docstring `--min-df` 默认值。**产物可复现**：按当前版本在隔离目录复跑 `nodes.json` **逐字节相同**（见 §11.5） |
| `topic_graph.py` | 30,255 B @19:13:42 | 30,873 B @**19:16:05**，sha256 `f9d93523c10c68ec6638845cb2a1395e877926489f04974879a3b9f8ae9e1cb6` | **21:15:15，45,738 B**，sha256 `39e04d9bae7f5fd2bc729a7fbcd918baceabc29b2a69abec97815bb648bfd4ce` | P4 工具，**取证期间被再次改动**（§0.2）；**R2-B** 修大小写归一 / `search` 排序 / 证据取样 |
| `topic_edges.py` | — | 18:49:22，29,102 B，sha256 `7372e2e8fe48ccab5be7ae349241bb1bef263b5ab4e8bd62bac94e030bea8e5e` | **21:34:26，33,515 B**，sha256 `d0ce2228b51862d2d6706d1ed61c352c64e667217b9c06f2b63ca2b7f26c7549` | **R2-A** 修 D1（层级边截断丢失）；**R2-C** 落盘 `types` 位图 |
| `topics_report.py` / `topics_meta.py` | — | 18:52:50（40,980 B） / 19:13:59（13,011 B） | **未变**（`980b9f6502367507f6b2c11f9e95668a85360f16b162a3406bc4b920492e55f9` / 未变） | 本项目新增工具 |
| `acceptance/topics-p0..p5.sh` | — | p0 17:32 / p1 18:40 / p2 18:51 / p3 19:04 / p4 19:14 | **p2 21:37 / p3 19:56 / p4 19:56 / p5 19:22 落位** | 本项目新增验收脚本；**R2-C 为 p2 增 `[4b]` 边型断言**。**注意**：`topics-p5.sh` 在 19:2x 取证时尚不存在（见 §0.2 时间线），现已落位并 28 项全绿 |

> **哈希链自查**：本表 + §0.1 合并后，ACCEPTANCE-REPORT 内**所有完整 64 位 sha256 均可实地复算、零漂移**（可用 `topics/audit/meta/audit_meta.py` 一键核验）。
> 仅 §0.2 的 `topic_graph.py` 历史版本 `ebd46be0…f456de2` 因原版已被覆盖而**无法补全**——该处保留缩写并标注"原版已不可得"。

> 注：`lib-catalog-release/v1/` 与 `lib-catalog-data-v1.tar.gz` 的 mtime 仍为 **14:01**，未被 P5 改动（发行包未重建）。

---

## 6. 复跑取证（命令 + 末行结论，原样抄录）

**统一前置**：`cd /home/wzh/go/reasonix-scripts/lib-catalog`　｜　**复跑时刻**：2026-09-18 19:17:48　｜　**方式**：前前台直跑（非后台、非并发），逐个串行。

| # | 命令（原样） | 脚本自报末行（原样） | exit | wall |
|---|---|---|---|---|
| 1 | `bash acceptance/topics-p0.sh` | `TOPICS-P0: PASS (pass=8 fail=0)` | 0 | 0.0 s |
| 2 | `bash acceptance/topics-p1.sh` | `TOPICS-P1: PASS (pass=17 fail=0)` | 0 | 0.1 s |
| 3 | `bash acceptance/topics-p2.sh` | `TOPICS-P2: PASS (pass=27 fail=0)` | 0 | 0.6 s |
| 4 | `bash acceptance/topics-p3.sh` | `TOPICS-P3: PASS (pass=18 fail=0)` | 0 | 0.1 s |
| 5 | `bash acceptance/topics-p4.sh` | `TOPICS-P4: PASS (pass=30 fail=0)` | 0 | 12.7 s |

**合计：pass=100 / fail=0，五脚本 exit 全 0；无 FAIL，无需分析失败原因。**
（`acceptance/` 下无 `topics-p5.sh`，故 P5 无第 6 条可跑命令 —— 这不是 FAIL，是**验收覆盖缺口**，见 §2.6 与 §7。）

### 6.1 与历史归档日志的一致性核对

- 5 份归档日志 `topics/acceptance-p0..p4.log` 的末行与本轮复跑**完全一致**（`PASS (pass=8/17/27/18/30 fail=0)`）。
- 对 `topics-p4.sh` 做了**逐字节 diff** 复核：与 `acceptance-p4.log` 相比**仅 3 行耗时数字不同**（`436.2ms→506.9ms`、`202.1ms→230.8ms`、`201.2ms→198.4ms`），**全部 PASS/FAIL 断言行与所有结构数字完全一致** → 判定 P4 验收**结构可重现**，时间抖动属机器负载噪声。

### 6.2 本轮实证的其他关键数字（复跑输出摘录）

- **P0**：`[PASS] 含 12 跳口径: 12 跳: 覆盖均 0.902 / 中位 0.938`；`[PASS] 12 跳覆盖 0.902 ∈ 90.2%±2% 验收带 [0.882, 0.922]`。
- **P1**：`N=5187 / BAD_SCHEMA=0 / ID_OK=True / TERM_UNIQ=True / KW=4838 / CLS=349 / FREQ_MIN=1 / FREQ_MEDIAN=29 / FREQ_MAX=11534 / FREQ_ZERO=0`；A1 一致性 8/8 `CHECK OK`；`P1_NOISE=0.04`。
- **P2**：`DTYPES=int64/int32/float32`；`NNZ=99268`；`W_MAX=1.000000`；`W_EQ1=11294`；`DEG_MEAN=19.1378`；`DEG_MAX=20`；`DEG_ZERO=3`；`TOTAL=188512 / BAD_JSON=0 / BAD_ID=0 / DUP=0 / TOO_MANY=0`；`ST_HOP12=0.8972 / CHOSEN=aug / RANK_BY=assoc`。
- **P3**：`C1=0.897210909202034 (med 0.9285714285714286, pass False)`；`C2=0.9796500966591521 (med 0.9883040935672515, pass True)`；`C3=0.9200401344574874`；`GATE=0.9`；`P50=1.986000996112125`／`P95=2.3947439007315547`；`COMPONENTS=4`／`LARGEST=5184`；`DECAY_HOP1=0.44269060865044596`／`DECAY_N=12`；`CSR_IP/IX/W=int64/int32/float32`；`SAMPLES=400`／`SOURCE_TYPE=kw`；`P3_VERDICT=True`／`P3_TS=2026-09-18T18:53:07+0800`。
- **P4**：`SRC=0(经济) DST=4(经济学) EDGE_W=1.000000 HOP1_GOT=0.860000 HOP2_GOT=0.739600 SEED_SCORE=1.000000`（`HOP1_MATCH/HOP2_MATCH=True`）；四子命令 exit 0；`--hops 13`、越界 id 均 exit 1；`graph 65 --hops 1` → 21 节点/153 边，`ENDPOINTS_OK=True`。

---

## 7. 已知限制与未决问题清单

来源阶段标注；影响面按"是否影响验收结论"分级。

| # | 限制/未决 | 来源阶段 | 实测证据 | 影响 |
|---|---|---|---|---|
| ① | **22,573 张卡（12.0%）无 top-5 主题** | P2 | `card_topics.jsonl` 尺寸分布 `0: 22573`（= 188512 的 **11.97%**）；`p2-self-test.txt` 明确 "无主题的卡 22573（12.0%）" | 这部分书在 `around/graph --books` 证据链中**永久不可达**；对"主题→证据书"召回是硬缺口。成因：卡 top-5 主题按词权取自 5,187 词表，短题录/纯西文/低 TF-IDF 卡落空 |
| ② | **12 跳同簇覆盖（仅主簇口径）曾卡在 0.90 下方** | P3 | R1 前 400 采样 0.8972（穷举 0.8992）；**R1 后 400 采样 0.9188 / 穷举 0.9194，已过线** | 该口径仍是**并列观察项**（硬门槛取 ② 主簇∪类目）；对外汇报须同时给出**抽样口径与源点池**，且不得与 v1 文档图数字作同口径对比 |
| ③ | **出度上限 20 与 P3 回退方案（20→30）规格冲突** | P2/P3 | `p2-tuning.md`：`assoc/30` 平均出度 **27.814**（破"平均 ≤20"规格），12 跳 ① 仅 0.8972→**0.9028（+0.6pp）**；`weight/30` = 0.8553 仍不达标 | handoff §4-P3 明文写的回退手段**实测无效且违规格**；已证伪并在 verdict 中登记。后果：①口径无廉价救法，只能改口径或接受观察项定位 |
| ④ | **共现封顶 50（`cap_count=50`）** | P2 | `cooccur_saturated_pairs=3878`，`cooccur_saturated_share=**0.0117**`（1.17%）达到权重上界 1.0；`cooccur_count_dist.max=2052` | 1.17% 的强关联对**权重并列饱和**、失去区分度（2052 次共现与 50 次同权）；top-20 截断时这些对靠 `assoc` 排序键才分得开 |
| ⑤ | **同簇边在 max 口径下恒被 ① 支配** | P2 | `params.b3_new_pairs=0`，`b3_note`："同簇对必然已有共现边（cnt_sc>0 ⟹ cnt>0）；sum 口径下 ② 为加成项，**max 口径下 ② 恒被 ① 支配而失效**"；同簇加成命中 9,167 条 | 三类边设计中的 ②**不是独立边型**，仅在 sum 合成下起加权作用；改 `--combine max` 会让 ② 完全失效（口径不稳健） |
| ⑥ | **衰减系数 0.86 源自 v1 文档图（非主题图实测拟合）** | P3/P4 | `topic_graph.py: DECAY_DEFAULT = 0.86` 注释"沿用 §3.4/v1 实测值"；`stages.P4.diffusion.note` 同；主题图实测**有效逐跳因子**首跳仅 **0.3058**（R1 前 0.4427；因边权均值 0.3647<1） | 0.86 是**外部搬来的常数**，未在主题图上重新拟合；主题图得分曲线**必然低于** `0.86^hop` 理论线，两个量不可混比。`--decay` 可覆盖但无推荐值（`interface-proposal` 亦列为待决） |
| ⑦ | **`search` 近词扩展依赖 v1 TF-IDF 索引；索引缺失即退化** | P4 | `tfidf_expand()` 开头检查 `index/{tfidf.npz,vocab.json,idf.npy}`，缺失即 `return [], {"reason": "index/tfidf.npz 缺失（v1 索引未构建）"}` | 词表命中（exact/token/prefix/substr）不依赖索引，**可用**；但"非词表查询"这条退化路径**完全失效**（无报错、静默少结果）。跨发行/索引重建场景需回归测试 |
| ⑧ | **主题表未收录"机器学习"这类高频复合词** | P1 | `nodes.json` 实查：`机器学习=False`、`人工智能=False`、`深度学习=False`、`神经网络=False`（而 `量子=True`）；`search 机器学习` 只命中 `机器`+`学习` 两个字面片段（`p4-smoke.txt` 例①） | 词表以"高频单 token/bigram"为主，**领域复合术语缺失**，查询需依赖子串/近词扩展兜底；对 `graph/around` 的种子定位精度有实质影响 |
| ⑨ | **LLM 接口仅存根、未接模型** | P4/P5 | `summarize` 输出首行 `【off：纯结构化占位输出（未调用任何模型）】`；`stages.P4.stub.signature = summarize_topic_region(region: dict) -> str`；验收 4 条静态断言确认无网络调用面 | 社区摘要/查询综合能力**未实现**；`interface-proposal.md` 已把签名与硬约束（默认不触网、mock 确定性、不得引入 region 外事实）写成草案**待作者拍板** |
| ⑩ | **工具链目录不是 git 仓库 → 无法用 git diff 举证** | P0/P5 | `git -C /home/wzh/go/reasonix-scripts/lib-catalog rev-parse --show-toplevel` → `fatal: not a git repository`（数据目录同上） | handoff §4-P5 指定的验收方式"**git 内 diff 证明**"**不可执行**；本报告以 sha256+mtime 替代（§5）。副作用：日后任何"未触碰"主张都缺版本控制层证据，只能靠哈希台账（而 `meta.json` 并未登记 v1 文件哈希清单） |
| ⑪ | **topics 是否进 data-v2 发行未决** | P5 | `lib-catalog-release/` 仅有 `v1/`(mtime 14:01) 与 `lib-catalog-data-v1.tar.gz`(98 MB)，**无 v2**；`stages.P4.p5_note` 与 `interface-proposal.md` §3.2 均标注"由您决定" | 交付物暂以数据目录内增量层形式存在；发行编号、瘦身格式是否采纳 uint8 量化、证据链是否随发行（~2.7 MB）均未定 |

### 7.1 附：本轮发现的**文档/实现不一致**（超出任务清单，但属"如实记录"）

| 不一致 | 证据 | 性质 |
|---|---|---|
| `docs-draft/README-draft.md`（18:53）与 `changelog-draft.md`（18:56）仍写 **"P4 ⏳ 未实现（待口径拍板放行）"**，且 README 图例把 `topic_graph.py` 标为 ⏳ | 两文档原文 + `stages.P4`／`p4-smoke.txt` 均证明 **P4 已于 19:13 完成并通过验收**（19:17:48 时点 P4 为 30 项断言；**R2-C 后为 38 项**，见 §11.3） | 文档为 18:5x 快照，**滞后于实现**；若直接作为 P5 交付物会被误读 |
| `interface-proposal.md` 的 `TOPIC_LLM` 表写 **"`mock`（默认）"**，而实现为 **未设即 `off`** | 文档 §1 表格 vs `stages.P4.guards.llm_default="TOPIC_LLM 未设置 = off"` + 验收断言 `未设 TOPIC_LLM 时默认 off` PASS | **规格与实现相反**；该文档是"给作者的协议草案"，此条必须先改 |
| 同一文档里的性能数字 **p50 1.49ms / p95 1.98ms**，与 P3 报告 **1.986 / 2.395 ms** 不一致 | 文档 §2 对照表 vs `topics-report.json` `performance` | 草案引用的是**更早一次**运行值，未同步 |
| P3 文本报告仍打印 `12 跳最终覆盖率: 均 0.8972 / 中位 0.9286 [门槛 ≥0.90: FAIL]` | `topics-report.txt`（该行按 ① 口径输出） | 与"硬门槛取 ② → PASS"的裁定**并存**，单看报告文本会误判为 FAIL；**以 `stages.P3.verdict` 为准** |
| **无 `acceptance/topics-p5.sh`**（19:19:33 复查仍无） | `ls acceptance/` 实测 = p0/p1/p2/p3/p4 + `topics-p3-smoke.log`，无 p5 | P5 **验收覆盖未闭合**；交接文档"acceptance 全绿"在 P5 段无法自动验证 |
| `topics/README.md`（19:19:26，45,248 B）与 `topics/INTERFACE-PROPOSAL.md`（19:18:16，10,045 B）为**取证后新增** | 两次 `ls` 对比（§0.2 时间线） | 落位及时，但**未经任何脚本校验**；本轮只确认存在性与字节数，未审内容，且**未核它们是否已修正 §7.1 前两条不一致**（P4 滞后表述、`TOPIC_LLM` 默认值矛盾） |

---

## 8. 验收结论

1. **P0–P4 五个验收脚本本轮亲手复跑，全部 PASS，pass=100 / fail=0，exit 全 0；无 FAIL，故无失败原因需分析。**
2. **P3 口径终裁成立且被脚本固化**：硬门槛 ②（主簇∪类目）**0.9797 ≥ 0.90 → PASS**；①（仅主簇）**0.8972 < 0.90** 如实并列、未被改写；③（无向闭包）0.9200 作诊断。三口径数字在 `topics-report.json`、`topics-report.txt`、`meta.json(stages.P3)` 三处一致。
3. **性能与结构达标且有富余**：p50 1.986 ms（门槛 <1 s；R2-C 终值 **2.580 ms**）；P4 命令 wall 0.61–1.11 s、扩散内部 187.5–223.8 ms；连通 4 分量／最大 5,184（99.94%；R2-C 终值 **5,504 / 99.9455%**）；边 99,268（R2-C 终值 **105,414**）、平均出度 19.1378、max 20、权重 [0.1763, 1.0]。
4. **v1 未触碰**：21 个 v1 文件/脚本 mtime 全部 ≤ 14:01（实测最大 13:57:56），sha256 已独立留档；工具链非 git 仓库，故以 sha256+mtime 举证；`export_release.py`／`topic_build.py`／`topic_graph.py` 属 P5 授权改动，已单列（§5.5）。
5. **两处必须提请注意的"软失败"**（不是脚本 FAIL，但影响交付完整性）：
   - **P5 无验收脚本**（`acceptance/topics-p5.sh` 在 19:19:33 复查仍不存在）→ 交接文档 §4-P5 的"acceptance 全绿"**在 P5 段无法被自动验证**；这是本次全链验收**唯一的覆盖缺口**；
   - **P5 文档的滞后与自相矛盾尚未证实已修正**：`docs-draft/` 三件文档存在**可证伪的滞后与矛盾**（§7.1，其中 `TOPIC_LLM` 默认值一项为规格/实现相反、P4 被标为"未实现"）；`topics/README.md` 与 `topics/INTERFACE-PROPOSAL.md` 虽已于 19:18–19:19 落位，但**未经任何校验**，本轮未核其内容是否已消化上述矛盾。
6. **残余风险集中在"口径依赖"而非"图质量"**：6 跳即饱和、无向闭包仅 +2.3pp、出度 20→30 仅 +0.6pp 三条独立证据共同表明——**12 跳覆盖读数主要由分母口径决定（0.7744→0.9797）**，工程优化空间已基本用尽；下一步应做的是**把口径与发行决策拍板**，而非继续调参。

---

*本报告由验收工程师写入，是**本轮验收动作新增的唯一文件**；除此之外，验收工程师未创建、未修改、未删除任何文件。目录内其他新增物（`topics/README.md`、`topics/INTERFACE-PROPOSAL.md`、`topics/export-sample/`）与 `export_release.py`／`topic_graph.py` 的改动**均由施工方（主会话）在 19:15–19:19 期间并发完成**，不属本轮验收动作，本报告仅作观测记录（见 §0.2、§5.5）。（P4 验收脚本自身会写 `/tmp/tg-accept-graph.json`，属脚本既有行为，位于临时目录。）*

---

## 9. 施工方补记（19:22，回应 §8 的两处软失败）

> 本节由**施工方（主会话）**在本报告落盘后追加，原报告正文（§0–§8）一字未改，便于对账。

**1. 覆盖缺口已闭合：新增 `acceptance/topics-p5.sh`**（`/home/wzh/go/reasonix-scripts/lib-catalog/acceptance/topics-p5.sh`）
- 断言 6 组 28 项：①三份交付文档存在非空；②`topics/README.md` 要素齐（四类产物 schema / 四条命令 / dtype / 近词扩展 / LLM 签名 / 错误码 / 验收清单）；③工具链 README 含「v2 → v3 变更记录」章节；④交接文档 §3.2 已回写 `--rank-by assoc`、文末含「## 8. 施工结果」、原 §3/§7 结构未破坏；⑤`export-sample` 自洽（二进制回读 dtype/节点数/边数/证据链 CSR/权重还原误差 ≤1/255/manifest 段）；⑥`meta.json` 的 `stages.P0–P4` 齐备且顶层 `stage` 仍为 P0。
- **结果：`TOPICS-P5: PASS (pass=28 fail=0)`，exit 0**，日志 `topics/acceptance-p5.log`。
- 关键实测：回读 dtype `int64/int32/uint8`；节点 5,187 = indptr−1；边 99,268；证据链 188,512 卡 / 487,933 链接；**uint8 权重还原误差 max 0.001959 ≤ 1/255**；manifest 8 文件 / 4,004,106 字节。

**2. 文档滞后与矛盾已核**：`docs-draft/`（过程稿，保留不动）中的滞后表述**未进入**定稿 —— `topics/README.md`(597 行) 与 `topics/INTERFACE-PROPOSAL.md`(100 行) 均已按最终实现改写（P4 标为已实现；`TOPIC_LLM` **默认 off** 已改正并列入待裁决项；p50 更正为 1.986ms、可达均 5042）。定稿内容由 §9.1 的 P5 验收脚本做基础要素校验（非全文审校）。

**3. 全链最终复跑（19:21:50，施工方执行，六脚本）**

| 命令 | 结果 | exit |
|---|---|---|
| `bash acceptance/topics-p0.sh` | `TOPICS-P0: PASS (pass=8 fail=0)` | 0 |
| `bash acceptance/topics-p1.sh` | `TOPICS-P1: PASS (pass=17 fail=0)` | 0 |
| `bash acceptance/topics-p2.sh` | `TOPICS-P2: PASS (pass=27 fail=0)` | 0 |
| `bash acceptance/topics-p3.sh` | `TOPICS-P3: PASS (pass=18 fail=0)` | 0 |
| `bash acceptance/topics-p4.sh` | `TOPICS-P4: PASS (pass=30 fail=0)` | 0 |
| `bash acceptance/topics-p5.sh` | `TOPICS-P5: PASS (pass=28 fail=0)` | 0 |

合计 **pass=128 / fail=0**；六个脚本均幂等可复跑，日志分别落 `topics/acceptance-p0..p5.log`。

**4. 仍留待拍板（未做改动）**：`TOPIC_LLM` 默认值 off vs mock（handoff §3.4 原文写"默认返回模板文"，当前实现为 off）；topics 是否进 data-v2 发行；出度上限 20 是否放宽；共现封顶 50；衰减系数 0.86 的可迁移性；22,573 张空主题卡的补抽取策略；LLM 接口的隐私与预算边界。

---

## 10. R1 修复记录（gpt6astra 终审整改）

> 独立终审裁决"不通过"，直接阻断三项 + 配套四项。本节为**施工方 R1 轮整改记录**，数字全部来自 R1 后实跑；旧数字一律标注"R1 前"。
> 修复前边表已备份：`topics/edges.csr.pre-r1.npz`（+ `edges.csr.pre-r1.npz.NOTE.txt`），供新旧对账，**不进发行**。

### 10.1 七项修复对照

| # | 缺陷（终审） | 影响 | 修复 | 复现/自验证据 |
|---|---|---|---|---|
| ① | **共现重复计数**：kw-kw 对在 spec 循环与 aug 循环各写一次 | 共现书数翻倍、权重整体偏高、饱和对偏多 | 合并为**单轮枚举**（卡主题集合 = top-5 kw ∪ {cls2}），每无序对每卡只计一次；同簇计数器独立计数、不叠加 | `settlement↔entanglement`（MMS 991000938579704181）权重 **0.2794153094 → 0.1762914360**（= log1p(1)/log1p(50)，float64 值 0.1762914344；与 `card_topics.jsonl` 独立重算一致）；原始对实例 1,753,477 → **1,112,854**，同簇原始 96,874 → **60,185**；distinct 对不变（330,426） |
| ② | **assoc 排序键未生效**：`topk_csr` 的 `np.lexsort` 实为「权重优先」，assoc 仅作平局 tie-break | `--rank-by assoc` 名义生效、实质未生效；低频节点仍被高频词挤出 top-20 | 键序改为 **`src↑ → 关联度↓ → 权重↓ → dst↑`**（权重退为 tie-break）；`--rank-by weight` 保持字面口径可复现 | **终审反例复现并修正**：`经济学`(id=4) 邻域中 **economist**（assoc **0.0578**，共现 10）**R1 前缺席 → R1 后进入（w=0.7775）**；**economic**（assoc **0.0353**，共现 39）**R1 前在邻域（w=1.0）→ R1 后让位**（两词 assoc 与终审给出的数值一致） |
| ③ | **扩散超跳**：`diffuse()` 同跳内读取被更新过的 `score[u]`；层内提级使后代层号失真 | 可返回超过 `--hops` 的路径（父链边数 > hops） | 改为 **层快照传播 + 首访定型（strict layering）**：第 h 跳只读第 h-1 跳结束分数；节点一旦入区不再改写 layer/parent；同跳多父取分数最大（平局按 id） | 内存反例（A/B 两条 11 跳链 + 层内边 + 末端节点，请求 12 跳）：**R1 前返回 13 边路径 → R1 后最深 12 边**；真实图 `around 139 --hops 1/2/3/12` 最深父链 **1/2/3/7 边**，超跳 **0**，`layer≠路径长` **0**；分数一致性抽验（hops=3，960 节点）最大偏差 **1.11e-16** |
| ④ | **报告表述失真** | "全节点"被误读为全量；"与 v1 差 0.28pp"把不同图/不同抽样当同口径；"衰减合理"无量化定义 | 本文档 §1–§9 相关段落已逐条改写；新增**穷举全量**口径；衰减给出**数值容忍定义** | 见 §10.3；容忍定义同步登记 `meta.json#stages.P3.caliber_freeze.decay_tolerance` |
| ⑤ | **验收断言不足** | 权重/行数/门槛/超跳/护栏无断言 → 缺陷可静默回归 | P2 增「共现权重独立重算抽验（5 条边）+ `card_topics.jsonl` 行数 == `cards.jsonl` 行数 == 188,512」；P3 增「门槛**硬编码** 0.90 + 口径冻结记录断言」；P4 增「超跳内存反例回归 + `--decay/--budget/--threshold` 越界拒绝」 | P2 由 27 → **30** 断言、P3 由 18 → 20、P4 由 30 → 39（含 5 条护栏）；六脚本全绿见 §11 |
| ⑥ | **P4 相关性无闭环** | 查询质量只有"能跑通"，无逐例相关性判定 | 新增 10 条真实查询逐例评分表（四命令全覆盖） | `topics/p4-relevance.md` |
| ⑦ | **护栏与文档缺失** | `--decay` 可为任意值；`--budget` 语义含糊；数据形态（合成加权图、无逐边类型）未声明 | 护栏：`--decay ∈ (0,1]`、`--budget ≥1`、`--threshold ∈ [0,1]`，越界 **exit 1**；文档：README 与本文档**声明合成加权图、未存逐边类型** | 护栏断言 5 条（P4 §9）；数据形态声明见本文档头部与 `topics/README.md` |

### 10.2 新旧数字对照（R1 前 → R1 后）

| 指标 | R1 前 | R1 后 | 说明 |
|---|---|---|---|
| 边数 / 平均出度 / 最大出度 | 99,268 / 19.138 / 20 | **99,268 / 19.138 / 20** | 不变（截断口径未动） |
| 权重 均值 / 中位 / w=1 占比 | 0.5187 / 0.4093 / 11.4% | **0.3647 / 0.2292 / 8.1%** | 计数去重后整体下移 |
| 共现封顶饱和对 | 3,878（1.17%） | **2,253（0.70%）** | 同上 |
| 12 跳覆盖 ① 仅主簇（400 采样 / kw 源点） | 0.8972（0.9286） | **0.9188（0.9412）** | 首次自然过 0.90 |
| 12 跳覆盖 ② 主簇∪类目（400 采样 / kw 源点） | 0.9797（0.9883） | **0.9912（0.9963）** | 硬门槛口径 |
| 12 跳覆盖 ①（400 采样 / 全节点源点） | 0.9030 | **0.9218** | 仍是 **400 采样**，非全量 |
| 12 跳覆盖 ① **穷举 5,187 源点** | **0.8992** | **0.9194** | 新增口径（`topics-report-exhaustive.json`） |
| 12 跳覆盖 ② 穷举 5,187 源点 | —— | **0.9856** | 同上 |
| 单查询 p50 / p95（12 跳） | 1.986 / 2.395 ms | **2.623 / 3.305 ms** | 仍远优于 <1s 门槛（图更连通、区域更大） |
| 连通分量 / 最大分量 | 4 / 5,184（99.94%） | **4 / 5,184（99.94%）** | 不变 |
| 衰减 1 跳 / 3 跳均分 | 0.4427 / 0.2401 | **0.3058 / 0.0781** | 边权均值下降所致；有效因子 0.306/0.397/0.364 仍在容忍带内 |
| 扩散超跳（反例图，请求 12 跳） | **13 边** | **12 边** | 不变式：父链边数 ≡ layer ≤ hops |
| `经济学` 邻域 economist / economic | 缺席 / 在（w=1.0） | **在（w=0.7775） / 让位** | 终审反例 |

### 10.3 表述纠偏清单（终审④）

1. **"全节点"→"400 采样 / `pool_size=5187`"**：`topics-report-allseed.json` 是**源点池扩到全节点、样本数仍为 400**，**不是全量统计**；本文档相应段落已改写，并**并列如实附上穷举全量 ① = 0.9194（R1 后）/ 0.8992（R1 前）**。
2. **"与 v1 差 0.28pp"作废**：v1 是**文档图（188,512 节点、K=10）**、主题图是**另一张图**，且抽样口径不同（v1 基线为 1 源点/簇的 400 簇抽样）→ 明确标注为**非同口径对比**，仅作定性参考。
3. **"衰减合理"→数值容忍定义**：首跳均分 ≥ 0.30；有效逐跳因子 ∈ [0.30, 0.90]；第 9 跳起饱和视为正常；不得与 `0.86^hop` 理论线直接比（该线假设边权恒 1，本图边权均值 0.3647）。实测全部落在容忍带内（见 §10.2 末行与 §4）。
4. **数据形态声明**：本图为**合成加权图**，边权由共现书数经 `log1p` 归一，**未存逐边类型**；①共现与②同簇加成已合并为同一权重（`w=min(1, w1+w2)`），仅③层级边可由 `w=1.0` 且目标 `type=cls` 识别。

### 10.4 新增验收断言（终审⑤，R1 后）

- **P2**（30 条断言）：`[8]` 共现权重**独立重算抽验**——从 `card_topics.jsonl` 反算「共现书数 + 簇内共现」，与落盘权重逐位比对（含终审反例对，共 5 条边；浮点容差 1e-6）；`[9]` `card_topics.jsonl` 行数 == `cards.jsonl` 行数 == **188,512**。
- **P3**（20 条断言）：门槛 **硬编码 0.90**（报告自述值仅作一致性核对，防止改报告即改门槛）；新增 `[8]` **口径冻结记录**断言（`meta.json#stages.P3.caliber_freeze`：集合定义 / 抽样规则 / 源点处理 / 门槛 / 分母 五字段齐备）。
- **P4**（39 条断言）：新增 `[8]` **超跳回归**（内存反例断言"修复前实现必须超跳"以证明反例有牙 + 修复后 ≤ hops + 真实图 hops=1/2/3/12 无超跳）；`[9]` **护栏** 5 条（`--decay 1.5/0/-0.2`、`--budget 0`、`--threshold 2` 均须 exit≠0 且给出范围提示）。

### 10.5 仍留待作者拍板（R1 未改）

`TOPIC_LLM` 默认值 off vs mock（handoff §3.4 原文写"默认返回模板文"）；topics 是否进 data-v2 发行；出度上限 20 是否放宽；共现封顶 50；衰减系数 0.86 的可迁移性（本图未重新拟合）；22,573 张空主题卡（12.0%）的补抽取策略；LLM 接口的隐私与预算边界。

### 10.6 R1.1 追加修复（相关性闭环的机理修复，终审⑥收口）

终审⑥要求"相关性闭环"，R1 首轮评测（`topics/p4-relevance.md`）给出 **7/10**（未达 ≥8），并定位两条机理。R1.1 就机理做了**代码级修复**并用**同一口径**复测为 **10/10**：

| 修复 | 原实现 | 缺陷实例 | 修复 | 复测 |
|---|---|---|---|---|
| 近词扩展**聚合窗口** | 取 top-**200** 张 TF-IDF 卡后按 `agg` 聚合 | `人工智能伦理` 的正解主题 `ethics` 排第 **13** → 意图限定词「伦理」在 top-10 中丢失 | 窗口 **200 → 50**（聚合只发生在最相关的卡上） | `ethics` 第 13 → **第 1**；该例 B → **A** |
| 证据书**取样口径** | 每主题取 `card_topics` **前 8 张卡（卡序）** | `around 56` 混入《跟毛泽东学习幽默智慧》（`via 「学习」`）→ 离题 1/3，降档 B | 按**对区域的加权覆盖度** `Σ region_score(卡的主题)` 排序（平局按行号） | 6/6 证据书全部同域；`around 18` 证据由 6/6 `cls=A` 变为 B2/C9/D6/F1/B2/J6 多域；#5/#10 B → **A** |

**否证记录**：曾尝试「专指度归一 `agg/√freq`」（与 §3.2 边表 assoc 同源思想）—— 实测把 `神经网络` 查询的低频同形词 `神经病学`/`neurology` 顶到第 2–3 名（**回归**），故**不采用**，仅保留为 `--expand-rank spec` 选项并标注风险。

**当前相关性**：**10/10 相关**（R1 前 7/10；判定标准 S1–S5 未放宽，原 §1/§2 判定保留）；仍存限制：复合词未入词表、cls 裸分类号稀释可读性（`around 18` 占 37.5%）、`around/summarize` 的"书证据 N 本"是区域并集。

### 10.7 R1/R1.1 后的验收结论

六脚本 **P0 8 / P1 17 / P2 30 / P3 21 / P4 38 / P5 28 = 142 项断言全绿，exit 全 0**（R1 前为 100 项；新增 42 项集中在 ⑤ 断言加固：权重独立重算、行数对齐、门槛硬编码、口径冻结、超跳回归、护栏）。回归复跑记录见 `topics/acceptance-p0..p5.log`。

> ⚠️ **R2-D 更正**：上表 142 项是 **R1 后**的计数。**R2-C 又为 `acceptance/topics-p2.sh` 新增 `[4b]` 边型断言（30 → 35）**，
> 故**当前终值为 P0 8 / P1 17 / P2 35 / P3 21 / P4 38 / P5 28 = 147 项全绿**，
> 末次复跑记录见 `topics/audit/r2c/runs-acceptance-p{0..5}.log`（详见 §11.3）。
> `topics/acceptance-p*.log` 是 20:01 的 142 项历史快照，**引用时须注明时点**。

---

## 11. R2 修复记录与 R2-D 文档同步（2026-09-18，审计整改）

> 本章由 **R2-D 会话**（AUDIT-META）编写：汇总 R2-A/B/C 三轮的终值与本轮文档/登记同步清单。
> 机读登记：`meta.json#stages['R2-A'|'R2-B'|'R2-C']` 与 **`stages.P5`**（本轮补登）。
> 逐轮原始报告：`topics/audit/p1/R2A-FIX-REPORT.md`、`topics/audit/relevance/REPORT.md`、`topics/audit/r2c/REPORT.md`。

### 11.1 三轮做了什么（来源：`stages.R2-*`）

| 轮次 | 层 | 修复项 | 关键 before → after |
|---|---|---|---|
| **R2-A** | 数据 | **F2/F2b** `ext_df` 双计数（A 源扩展证据与 B-CJK 证据两趟各 +1） | 卡片级包含率上界 `2.0 → 1.0`；`ratio>1` 词数 `580 → 0`；A 源保留 `1,518 → 1,647`（**129 个误剔词回归**） |
| | | **F1/F1b** 截断排序键浮点退化（`freq*rep` 按 IEEE754 乘除链） | `score≠max_cc` 节点 `184 → 0`；排序键 ≡ `max_cc`（精确整数）；`id` 重排 98.61% 但 **head6 未变** |
| | | **D1** 层级边被 top-20 截断吃掉 | 层级边 登记 4,832 / 实存 **4,823 → 5,151 / 5,151**（**缺 9 → 0**） |
| **R2-B** | 检索 | ASCII 大小写归一（查询侧 × 词表侧） | 旧代 349/5187 个大写 `cls` 码不可搜 → `D9`/`d9` 同结果且 rank-1 为整词 |
| | | `search` 排序引入特异性 `w_spec=log1p(freq)/√freq` | rank-1 泛词 `7/10 → 10/10` 为最专门词 |
| | | 证据取样改「同簇闸门 + 一跳近邻覆盖度 + 多卷软去重」 | 相关性 **P1 4/10 → 8/10、P2 5/10 → 8/10**（严格口径，达标线 ≥8） |
| **R2-C** | 报告/导出 | 质量报告重跑（新数据） | 三口径 ①0.9188→**0.9246** ②0.9912→**0.9927** ③0.9200→**0.9286** |
| | | 导出版重建（修 AUDIT-EXPORT **E1** 随包 meta 与随包数据不同源） | u8 反算 `w_eq1` 0.0807(错) → **0.0805 == 登记值**；`manifest.topics.json#snapshot` 绑定源数据 sha256；新增 `--strict` |
| | | 边型数组（AUDIT-EDGETYPE 方案 a） | `types` uint8 入 npz 并随包导出；三数组与 R2-A **逐位一致**；86,846 条 kw-kw 边独立重算 **0 不符** |

### 11.2 R2 终值一览（**当前权威数字**；替代 §1–§9 的 19:2x 快照）

| 量 | R1 后 | **R2-C 终值** | 说明 |
|---|---|---|---|
| 节点 / kw / cls | 5,187 / 4,838 / 349 | **5,507 / 5,158 / 349** | 簇取值数 396 → **397** |
| 边 / 平均出度 | 99,268 / 19.138 | **105,414 / 19.142** | 出度 max 20、中位 20 不变；孤立节点 3 |
| 权重 min/中位/均 | 0.1763 / 0.2292 / 0.3647 | **0.1763 / 0.2292 / 0.3656** | `w=1` 占比 8.07% → **8.05%**（8,487 条） |
| 层级边（登记 = 实存） | 4,832 / 4,823 ❌ | **5,151 / 5,151** ✅ | D1 修复 |
| distinct 对（aug） | 330,426 | **349,680** | kw-kw 245,779 → **261,376** |
| 空主题卡 / 卡-主题链接 | 22,573 / 487,933 | **21,607 (11.46%) / 501,205** | cards 恒为 188,512 |
| 三口径（400 采样/kw/`pool=5158`） | 0.9188 / 0.9912 / 0.9200 | **0.9246 / 0.9927 / 0.9286** | 门槛 ② ≥ 0.90 → **PASS** |
| 全节点源点（**仍 400 采样**/`pool=5507`） | 0.9218 / 0.9841 / 0.9232 | **0.9202 / 0.9854 / 0.9247** | ① 微降 −0.16pp，属口径效应 |
| 穷举全量（**5,507** 源点） | 0.9194 / 0.9856 | **0.9237 / 0.9867** | 唯一全量口径 |
| p50 / p95 | 2.623ms / 3.305ms | **2.580ms / 3.740ms** | 门槛 <1000ms → PASS |
| 最大分量 | 5,184 (99.9422%) | **5,504 (99.9455%)** | 分量数 4 不变 |
| 衰减 hop1 / hop3 | 0.3058 / 0.0781 | **0.3093 / 0.0751** | 有效逐跳因子在容忍带内 |
| 验收断言 | 142 项 | **147 项**（P2 30→35） | 六脚本全绿 exit 0 |
| 导出版 | 8 文件 / 4,004,106 B | **9 文件（+`edges_types.u8.bin`）/ 4,255,902 B** | 内外层 manifest 全对 + 同源校验 |
| v1 未触碰 | 21 项 sha256+mtime | **不变**（`cards.jsonl` sha256 `9e9dffd2cf237b2ab7db24444154881b89d7afd352df171c64a28b8e7093fcfd` 已登记进 `manifest#snapshot`） | v1 只读约束 **R2 全程遵守** |

### 11.3 验收断言计数统一（本次收口项之一）

**矛盾**：§0.2 与 §7.1 曾写 P4「**30/30** 全过」（19:17:48 时点），§10.7 写「六脚本 **142** 项」——两个数字并存且未标注时点。

**统一到当前终值**：

| 阶段 | 19:1x | R1 后 | **R2-C 终值** | 末次复跑日志 |
|---|---|---|---|---|
| P0 | 8 | 8 | **8** | `topics/audit/r2c/runs-acceptance-p0.log` |
| P1 | 17 | 17 | **17** | `…-p1.log` |
| P2 | 27 | 30 | **35**（R2-C 新增 `[4b]` 边型断言 5 条） | `…-p2.log` |
| P3 | 18 | 21 | **21** | `…-p3.log` |
| P4 | 30 | 38 | **38** | `…-p4.log` |
| P5 | — | 28 | **28** | `…-p5.log` |
| **合计** | **100** | **142** | **147（全绿 / exit 0）** | — |

> `topics/acceptance-p*.log`（20:01）是 **142 项**的历史快照，**保留不删**，引用时须注明时点。

### 11.4 R2-D 本次同步清单（只动文档/登记；`acceptance/*.sh` 未改）

| # | 文件 | 动作 | 备份 |
|---|---|---|---|
| 1 | `topics/meta.json` | **补 `stages.P5` 段**（交付物/导出版指针/**终值快照**/`r2d_sync`/`verification`）；`current_stage` `R2-C → P5`；`notes_meta` 由 8 条重复模板收敛为「1 条结构规范 + 1 条阶段沿革」；**回刷 `stages.P2`**（见 §11.5-N1）；`stages.P2.artifacts` 补登 variant 产物；核对 `stages.R2-A/B/C` 齐备 ✅ | `meta.json.pre-r2d` |
| 2 | `topics/ACCEPTANCE-REPORT.md` | 顶部加 R2-D 同步声明；**§0.1 脚本版本表对齐现值 + 版本沿革表**；§0.2 更正 30/30；§1/§2.3/§3.1/§3.4 补 R2 终值；「全节点」表述改准；**新增本章 §11** | `ACCEPTANCE-REPORT.md.pre-r2d` |
| 3 | `topics/README.md` | §9 数字来源索引更新到终值 + 加维护约定；**§2.4 修复 3 个不存在的承诺键**（`p2.p3_gate_note`、`p4.gate_note`、`p4.p5_note`）并补 `stages.P5`/`R2-*` 行与双轨语义告警；**§2.2 补 `types` 位图 schema**；阶段表/§3/§7/§8 同步终值；对照表述统一为「不同图 + 不同抽样口径，非同口径对比」 | `README.md.pre-r2d` |
| 4 | `topic_build.py` | docstring `--min-df` 默认 **8 → 12**（与 argparse 一致，闭环 §8-R5） | —（单行改动，已记录 sha256） |
| 5 | `TOPIC-GRAPH-HANDOFF-20260918.md` | §8 追加「R1/R2 轮结果」注记（**只追加，不改原文**） | `…HANDOFF-20260918.md.pre-r2d` |
| 6 | 审计产物 | `topics/audit/meta/`：`audit_meta.py`（只读审计器，已升级为**动态核对 README 承诺键 / 区分历史沿革行 / 识别良性因果倒挂**）、`update_meta_p5.py`（P5 登记器，幂等）、`repro-evidence.json`（N3 复算证据）、`scratch-p1/`（N3 隔离复跑产物）、`REPORT.md` 与 `audit-results.json`/`snapshot.json` | — |

### 11.5 本轮额外发现与处置（R2-D 审计复跑所得）

同步过程中用 `topics/audit/meta/audit_meta.py`（只读）复跑全链，**新发现 3 项并已处置**：

| # | 发现 | 性质 | 处置 |
|---|---|---|---|
| **N1** | **`stages.P2` 未随 R2-C 回刷**：`generated_at` 仍为 21:07（R2-A 时点）而 `p2-build-report.json` 为 21:35；`seconds` 14.7≠14.3；`params` 缺 R2-C 新增的 `b5_edgetype_rule` | ❌ **真·登记滞后**（R2-C 只刷了 `stages.P3`） | 已按当前报告回刷 `stages.P2`，before→after 留痕于 `stages.P2.r2d_sync`。`counts`/`edge_stats`/`self_test` 三项经比对**数值未变** |
| **N2** | **`edges.csr.npz`(21:35) 晚于 `topics-report.json`(21:29)** —— 表面上是「P3 读数早于其输入」的因果倒挂 | ✅ **已证良性** | R2-C 对 npz 只**追加** `types.npy`；`indptr`/`indices`/`weights` 三成员与 `edges.csr.pre-r2c.npz` **逐字节 sha256 相同** → 21:29 的 P3 读数对本次数据仍有效。证据：三成员哈希逐一比对（`indptr 0fd4de748953…`、`indices 8432f94e9d1b…`、`weights 52dad46c8da7…`） |
| **N3** | **`topic_build.py`(21:44) 晚于 `nodes.json`(21:06)** —— 现存脚本「无法解释」产物 | ✅ **已证良性** | 按当前脚本在隔离目录 `topics/audit/meta/scratch-p1/` 复跑 → `nodes.json` 与线上**逐字节相同**（`ba1ff2603ee759b2…`）；`p1-build-report.json` 仅 `generated_at`/`nodes_path`/`out_dir` 三个运行元数据字段不同。错配由 R2-D 的 **docstring 单行改动**（`--min-df` 8→12，+6 B）造成，非语义改动。证据落 `topics/audit/meta/repro-evidence.json` |

**哈希链收口结果**（`audit_meta.py` 复跑）：ACCEPTANCE-REPORT 内完整 64 位 sha256 **全部可实地复算、零漂移**；
导出版 manifest 内外层 **9/9 + 8/8** 一致、`total_bytes` 相符；`baseline_sha256` 一致。
仅 §0.2 的 `topic_graph.py` 历史版本 `ebd46be0…f456de2` 因原版被覆盖而无法补全（已标注）。
**汇总：✅87 / ⚠️4 / ❌0**（4 项 warn 均为已登记的设计性残留，见下）。

### 11.6 仍留 4 项 ⚠️（设计性残留，已登记不静默）

| # | 残留 | 说明 | 归属 |
|---|---|---|---|
| W1 | 顶层 `stage="P0"` 与 `current_stage="P5"` 双轨 | 兼容冻结；已在 README §2.4 与 `meta.notes_meta` 显式声明 | R3：断言改指 `stages.P0.stage` |
| W2 | 6 处 acceptance 断言硬编码 `stage == "P0"` | 同上 | R3（同上） |
| W3 | §0.2 一处历史哈希缩写无法补全 | 原版已被覆盖，属不可逆取证损失 | 保留标注 |
| W4 | 包内 `meta.json` 是打包时点快照（不含 `stages.P5`） | 快照语义正确，但「包内自洽 ≠ 最新口径」 | R3：重新导出或注明对应活件 sha256 |

**未做（R3 待办，登记不执行）**：
① 各 `acceptance/topics-p*.sh` 的**断言加固清单**保留在 `topics/audit/acc` 作 backlog（本轮**未动 acceptance 脚本**）；
② 顶层 `stage` 兼容冻结的解除（把断言改指 `stages.P0.stage`）；
③ `topics_meta.py --stage choices` 扩到 `P5|R2-*`（避免后续轮次继续旁路登记器）；
④ `AUDIT-EXPORT E3/E4` 与 `AUDIT-EDGETYPE §4.4` 残留项（见 `stages['R2-C'].not_done`）。

---

## 12. 独立复审（gpt6astra · **有条件通过**）

> **复审性质**：**增量复审**（复用既有会话，不重跑全链），出具日期 **2026-09-18**。
> **裁决**：**有条件通过 —— 原七项阻断均已闭合；仍有负值参数、证据可复算性和发布快照残留。**
> **通过条件（本交付必须遵守）**：交付时**明确保留限制清单**（§12.2），
> 且 **不得宣称「相关性全通过」或「WARN 已清零」**。
> 复审自身引用的独立复跑证据：`topics/audit/r2-verify/REPORT.md`（R2-E 全链复跑）、
> `topics/audit/r2-verify/verify_r2e.json`（16 PASS / 0 FAIL / 2 GAP）、
> 回归集 `reasonix-scripts/lib-catalog/tests/regression/`。

### 12.1 七项阻断：FIXED（复审确认）

| # | 原阻断项 | 裁决 | 复审独立复算证据 |
|---|---|---|---|
| ① | 共现重复计数（kw-kw 对每卡计两次） | ✅ **FIXED** | `source_a_kept` 1,518→**1,647**、`dropped_embedded` 894→**765**、**129 个误剔词回归**；漏斗闭合 `1647+765+429=2841`；卡片级包含率上界 **2.0→1.0**、`ratio>1` 词数 **580→0** |
| ② | `--rank-by assoc` 名义生效实质未生效 | ✅ **FIXED** | 回归 `r2_assoc_order` **PASS 41 / 0 WARN**（含内存反例「有牙性」+ 真实图锚点 + 7 源点不变式）；`assoc/20` 与 `weight/20` 保留集差 60,898 槽 |
| ③ | 扩散超跳（层内提级） | ✅ **FIXED** | 回归 `r3_no_overhop` **PASS 83**：内置缺陷实现快照仍返回 13 边 > 12（反例有牙），修复后 ≤12；`layer ≡ 父链边数` |
| ④ | 「全节点」表述被误读为全量统计 | ✅ **FIXED** | README/本报告均改为「**仍是 400 采样** + `pool_size`」三口径并列；新增穷举全量口径（5,507 源点，唯一全量） |
| ⑤ | 回归断言缺失（权重/行数/门槛/超跳/护栏） | ✅ **FIXED** | `acceptance` 六脚本 **147 项全绿 exit 0**；独立回归集 **237 PASS / 0 FAIL / 4 WARN** |
| ⑥ | 相关性闭环未成立 | ✅ **FIXED** | 十条链路 **8/10**（达标线 ≥8/10，严格口径）；`P1 4→8`、`P2 5→8`（受控对照：同数据 + 修复前 `topic_graph.py` 复现 4/10、5/10） |
| ⑦ | 边型不可辨识 / 护栏 / 文档滞后 | ✅ **FIXED** | `types` uint8 位图**全量 105,414 条逐边核对**：`bit0` 违例 0、`bit1 == (c_sc>0)` 不符 0、`bit1 ⇒ 同 cluster` 违例 0、`bit2 == (src→cls_of[src])` 不符 0，值域恰为 **{1,3,5,7}**；护栏 13 组越界值均拒绝；文档已按 R2 终值同步（§11） |

**复审独立复算的关键数字**（非引用自报，均由复审方从证据链重算）：

| 量 | 复审复算值 | 与自报一致性 |
|---|---|---|
| 节点数 | **5,507**（`id` 连续 0..5,506、`term` 全量唯一） | ✅ |
| 边数 | **105,414** | ✅ |
| 边型位图 `types` | dtype **uint8**、len == nnz、值域 **{1,3,5,7}**、分布 `1`:89,643 / `3`:10,620 / `5`:4,358 / `7`:793 | ✅ |
| 层级边 | 登记 **5,151** == 实存 **5,151**，**缺失 0**；有牙性：pre-r2 产物整组重算仍得 **9** 条缺失 | ✅ |
| 验收 P2 | **`pass=35 fail=0`** | ✅ |
| 回归集 | **237 PASS / 0 FAIL / 4 WARN / 0 SKIP** | ✅ |
| 十条相关链路 | **8/10**（严格口径） | ✅ |
| vs `pre-r2c` 三数组 | `indptr`/`indices`/`weights` **逐位一致**（R2-C 仅新增 `types`） | ✅ |
| 导出包 `edges_types.u8.bin` | 与源 npz `types` **逐位一致** | ✅ |

### 12.2 ⚠️ **保留限制清单（原文落档，逐条）** —— 交付时必须随件保留

> **声明句（必须原样随交付物保留）**：
> **本交付不得宣称「相关性全通过」，也不得宣称「WARN 已清零」。**

| # | 限制项 | 严重度 | 事实与影响 |
|---|---|---|---|
| **L1** | **M6 负值参数未拒绝**（回归集 **4 条 WARN 全部来自此项**） | 中 | `--top -1` 产出「层内 20 个主题（显示 top 0）」**自相矛盾字段**；`--evidence -1` **静默返回 0 条**；`--expand-cards -1` 报「**-1 张卡命中**」；`search --top -1` **丢末行**（静默截断）。**R2 轮未纳入修复**，为已知未修缺陷 |
| **L2** | **P1 证据可复算缺口**（`freq` / `max_cc` 的卡集未落档） | 中 | 复审独立重算：`freq` 与 `card_topics` 派生值 **不符 1,285/5,507（23.3%）**；排序键 `max_cc` 的两种 `card_topics` 派生键与交付序分歧 **5,505/5,507、5,503/5,507** 位。根因：`max_cc = freq×rep` 依赖 **top-5 截断前的完整卡集，该卡集未落档** → **第三方无法独立复现 P1 的 `freq`/排序键**（AUDIT-NUM §5 / R2-A 未决 §3）。复审对其余 P1 项（`id` 连续、`term` 唯一）判 PASS |
| **L3** | **相关性 8/10 系「同域」口径，不解释为完整查询意图满足率** | 中 | 达标口径 = 「邻域 hop1 top10 同域 ≥4/10 **且** 证据面 5 张书证直接相关 ≥3/5」。**未达标两条**：**Q07「数据结构 算法」证据面 1/5**（唯一真 CS-DS 书已进首位，余 4 本含查询词「算法」但属数学建模，审计判定不直接相关；宽口径 5/5 → 9/10）；**Q10「城市规划」证据面 2/5**（「规划」多义：城乡/生涯/战略/经济同节点；城乡规划书已升至首位）。**该 8/10 只证明「同域相关性达标」，不等于「用户查询意图被完整满足」** |
| **L4** | **`audit/acc` 断言加固清单仍为 backlog** | 低 | H 类加固项未并入 `acceptance/*.sh`（本轮**未动验收脚本**）；清单保留在 `topics/audit/acc/REPORT.md` |
| **L5** | **登记双轨（`stage="P0"` / `current_stage="P5"`）与包内 meta 快照** | 低 | ① 顶层 `stage` 为 P0 兼容冻结，**不代表真实阶段**（须读 `current_stage`）；6 处 acceptance 断言硬编码该值；② 导出版包内 `meta.json` 是**打包时点（21:37）快照**，**不含 `stages.P5`** → 「包内自洽 ≠ 最新口径」 |
| **L6** | **其他未关审计项**（F18 等） | 低 | **F18**：`source_a_kept` 含 **161** 个被 entry 段英文门二次过滤但**无计数器**的词（R2-A 未决 §4；复审确认这 161 个仍不在 `nodes.json`，`1,486 = 1,647 − 161`）；**R2-C §5 其余项**：#2 `topics-report-exhaustive.json` schema 双轨、#3 AUDIT-EXPORT E3/E4、#4 `variant-spec` 的 `types` 未单独验收、#5 穷举口径 ~76s 未入常规验收 |
| **L7** | **P3 `[4]` ① 断言文案过时，当前不校验任何东西** | 中 | `acceptance/topics-p3.sh` `[4]` 仍写「① < 0.90」，而 ①=**0.9246** ≥ 0.90 → 落 `info` 分支。**该守卫当前为空转**（三次独立确认：R2-C §5-1 两次 + 本次）。建议改区间断言「0.90 ≤ ① < ②」——**属 R3 待办，本轮未改脚本** |
| **L8** | **复审窗口内存在并发写入** | 信息 | `meta.json` / `README.md` / `ACCEPTANCE-REPORT.md` 在复审窗口内被 R2-D/P5 会话改写；复审依赖的 `stages.P2.counts.*` 三字段全程不变，回归集与验证脚本已在收口状态复跑通过。**引用前请先复核哈希** |

### 12.3 交付声明（随件保留）

1. **本交付不得宣称「相关性全通过」** —— 相关性为 **8/10（同域口径）**，Q07 1/5、Q10 2/5 两条未达标（见 L3）。
2. **本交付不得宣称「WARN 已清零」** —— 回归集现存 **4 条 WARN**（全部为 M6 负值参数，见 L1）；
   `audit/r2-verify` 另有 **2 项 GAP**（`freq` 可复算性、`max_cc` 排序键可复算性，见 L2）。
3. **「有条件通过」的条件 = 上述限制清单（L1–L8）随交付物保留**，不得以「已全绿」概括。
4. **可复现命令**（复审方给出）：
   ```bash
   cd ~/go/reasonix-scripts/lib-catalog
   bash tests/regression/run_all.sh                                    # 期望 237 PASS / 0 FAIL / 4 WARN
   bash ~/go/lib-catalog-data/topics/audit/r2-verify/run_acceptance.sh # 六脚本 147 PASS / exit 0
   cd ~/go/lib-catalog-data/topics/audit/r2-verify
   PYTHONPATH=~/go/pylibs python3 verify_r2e.py                        # 16 PASS / 0 FAIL / 2 GAP；exit 0
   ```
5. **本 §12 为 R2-F 落档**，内容源自 gpt6astra 复审裁决与 `audit/r2-verify/REPORT.md`；
   备份 `topics/ACCEPTANCE-REPORT.md.pre-r2f`。本任务**只落档，未修改任何脚本或产物**。
