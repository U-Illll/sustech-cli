# AUDIT-REPRO · 复现性审计报告（"声称可复现"逐条实跑核对）

- 范围：只读主体与文档（`topics/README.md`、`topics/meta.json`、`topics/ACCEPTANCE-REPORT.md`、`acceptance/*.sh`、`~/go/reasonix-scripts/lib-catalog/*.py`）；重跑输出全部写 `audit/repro/runs/`，**未覆盖任何正式产物**。
- 方法：① 收集声称命令 ② 核对 argparse 实际默认值/路径可执行性 ③ 关键命令实跑并与正式产物逐字节/逐字段比对。
- 产物快照（sha256 前 16 位，审计期间均未变动）：`nodes.json` 9f5437d7034bfdaa ｜ `edges.csr.npz` 509c285aac82b9a1 ｜ `card_topics.jsonl` 161a6ab87dc8328e ｜ `topics-report.json` 7e5936b929392786 ｜ `baseline-p0.txt` ff2a32ad00761499 ｜ `p1-build-report.json` bf324e092353b6c8 ｜ `p2-build-report.json` a08effc03d605263
- 重跑证据：`runs/official-hashes.txt`、`runs/rerun-hashes.txt`、`runs/p0-baseline.txt`、`runs/p1/`、`runs/p3/`、`runs/p4-*.txt`、`runs/acceptance-p{3,4}.rerun.log`

## 0 结论摘要

| 项 | 结论 |
|---|---|
| 五条主命令实跑 | P0 ✅ 逐字节一致；P1 核心 ✅ 哈希一致；P2 ⚠️ 默认值与正式运行不符；P3 ✅ 数值一致（照抄命令少一列）；P4 ✅ 四子命令 exit 0 且确定性 |
| 声称命令**照抄**可执行性 | **2 条照抄直接失败**：P1 `--report` 相对路径崩溃、P2 `--out` 隔离目录缺 `nodes.json` |
| 随机种子 | 脚本层 ✅ 全部 `--seed 42` + `default_rng`；登记层 ⚠️ P0/P1 未把 seed 写进 `meta.json` |
| 依赖版本 | ❌ 全链零版本记录；sklearn 缺失会**静默**改变 P1 节点集（停用词 988→672，-32%） |
| 文档数字 vs 现行产物 | ⚠️ P3 性能数字（1.986ms）与验收计数（30/18）均非现行产物值 |

## 1 复现性矩阵（命令 × 判定 × 证据）

| # | 声称命令（README 出处） | 判定 | 证据 |
|---|---|---|---|
| C1 | §3.1 `graph_report.py --data ~/go/lib-catalog-data` | ✅ 可复现 | 重跑 stdout 与 `baseline-p0.txt` 除 `[耗时]` 行外**逐字节一致**；本轮 25.15s（README 称 18.2s）|
| C2 | §3.2 `topic_build.py … --report topics/p1-build-report.json --sample-out topics/p1-sample50-candidates.txt` | ❌ **照抄即崩（且破坏性）** | 文档前置 CWD `~/go/reasonix-scripts/lib-catalog` 下**无 `topics/` 目录**，`topic_build.py:745` 写报告**不做 makedirs** → `FileNotFoundError`（实测 `open('topics/probe.json','w')` 即报错）。更严重：`nodes.json` 在 **682 行先写**（覆盖正式产物）后才于 745 行崩溃 |
| C2b | §3.2 同一命令（仅输出改到 `runs/p1/`）| ✅ 可复现 | `nodes.json` sha256 **9f5437d7… 与正式产物完全相同**；`params/counts/freq_stats/noise_rate/noisy_items` 五项逐字段一致；5,187 节点；39.7s（README 称 54.3s）|
| C3 | §3.3 `topic_edges.py --data ~/go/lib-catalog-data` | ⚠️ 部分 | README 注"参数即默认值 `--coverage-samples 300`"，但 `p2-build-report.json#params` 与 `meta.json#stages.P2.params` 均记 **400** → 照抄（默认 300）得不同覆盖读数与不同报告 |
| C3b | §3.3 `topic_edges.py … --out topics/_exp/tag-01`（"隔离输出目录"）| ❌ 不可复现 | `topic_edges.py:221` 从 `<out>/nodes.json` **读入** → `FileNotFoundError: runs/p2-smoke/nodes.json`，exit=1。`--out` 同时是输入目录 |
| C4 | §3.4 冻结命令（含 `--random-baseline`，依 `meta.json#stages.P3.config`）| ✅ 可复现 | `topics-report.txt` 与正式产物除耗时外逐字节一致；覆盖 ① **0.9187989336293301** 与正式值完全相同；连通 4/5,184/3 相同 |
| C5 | §3.4 **照抄** README 命令（无 `--random-baseline`）| ⚠️ 部分 | exit 0 且核心数值相同，但 `config.random_baseline=false` vs 正式 `true` → 衰减表**整列"随机游走基线"消失**，产物不逐字节等价 |
| C6 | §3.5 `search/around/graph/summarize` 四子命令 | ✅ 可复现 | 全部 exit 0；`graph` JSON 自洽（268 节点/1,855 边/**悬空端点 0**，w∈[0.059,1.0]）；`search` 两次重跑除耗时外一致 |
| C7 | §3.5 `summarize 56 --strict-llm  # endpoint 未实现时 exit 3` | ❌ 文档不符 | 照抄（`TOPIC_LLM` 未设=off）实测 **exit 0**；仅显式给 endpoint 才 exit 3：`TOPIC_LLM=http://127.0.0.1:9999/v1 … --strict-llm` → exit 3 |
| C8 | §5 错误码表 `--hops 13` / `around 99999` / `--data` 置于子命令后 | ✅ 可复现 | 实测 exit **1 / 1 / 2**，与表及消息文本一致 |
| C9 | §7 `bash acceptance/topics-p4.sh`（称 pass=**30**）| ⚠️ 通过但计数过期 | 重跑 **PASS (pass=38 fail=0)**；`topics-p3.sh` 同理：声称 **18**，实测 **21** |

## 2 不可复现清单 + 锁定方案

| 编号 | 缺陷 | 影响 | 锁定方案（建议） |
|---|---|---|---|
| U1 | §3.2 `--report`/`--sample-out` 用**相对路径**，与文档前置 CWD 不匹配 | 照抄崩在最后一步，且崩溃前已覆盖正式 `nodes.json` | 立即：README 改绝对路径 `--report $D/topics/…`；根治：`topic_build.py:745` 前补 `os.makedirs(os.path.dirname(p) or ".", exist_ok=True)`（照抄 `topics_report.py:798` 已有写法），并把报告写在主产物**之前** |
| U2 | P2 `--coverage-samples` 文档默认 300 / 正式运行 400 | 报告不可逐字节复现 | README 显式写 `--coverage-samples 400`；`meta.json` 增记 `argv_raw` 原文 |
| U3 | P2 `--out` 被文档描述为"输出目录" | 隔离实验命令直接失败 | README 注明"`--out` 为**输入/输出同目录**，须先以同一 `--out` 跑 P1"；脚本加前置检查与可读报错 |
| U4 | §3.4 冻结命令漏 `--random-baseline` | 产物少一整列 | README 补该 flag（以 `meta.json` 已记的 `random_baseline:true` 为准）|
| U5 | `--strict-llm` 的 exit 3 前提未写明 | 照抄见 exit 0，误判护栏失效 | 注释改为 `TOPIC_LLM=<endpoint> … --strict-llm  # 未实现 endpoint → exit 3` |
| U6 | 性能数字 `p50 1.986/2.395/2.67ms` 归属错误 | §1/§3.4/§9 均归给现行 `topics-report.json`，该文件实为 **2.6229/3.3051/4.3385**；1.986 实际来自 `export-sample/v1/topics/meta.json` | 数字改注 `export-sample` 副本；现行值以 `meta.json#stages.P3.performance` 为准；性能项统一标注"机器相关，不承诺复现" |
| U7 | 验收计数过期（称 30/18，实测 38/21）| 复核者误以为漏跑 | README 计数改为引用"脚本自报 pass 数"，或附脚本 sha256 |
| U8 | P0/P1 的 seed 未登记进 `meta.json` | 换 seed 即不可复现却无据可查（P0 覆盖曲线用 200 随机源点 + 100 簇抽样；P1 `--sample-out` 用 rng）| `stages.P0/P1.params` 增 `seed` 字段 |
| U9 | 依赖版本零记录 | sklearn 缺失时 `topic_build.py:45` 静默 `_SK_STOP=set()`，停用词 988→**672（-316，-32%）**、无告警 → P1 节点集静默改变 | `meta.json` 增 `env{python,numpy,scipy,sklearn}` 实测量；sklearn 导入失败改为显式 `WARN`，或对 988 词表做 allow-list 校验 |
| U10 | `--expand-cards` 文档称默认 **200**（README 360/415 行），argparse 实为 **50** | 近词扩展广度差 4 倍 | 文档改 50，或实现默认改 200——二者取一，勿两存 |

## 3 随机种子管理

- 脚本层 ✅：`graph_report.py` / `topic_build.py` / `topic_edges.py` / `topics_report.py` 均有 `--seed`（默认 42）且统一 `np.random.default_rng(seed)`；`topic_graph.py` **无随机性**（确定性 BFS），已由两次重跑逐字节比对证实。
- 登记层 ⚠️：`stages.P2.params.seed=42`、`stages.P3.config.seed=42` 有记；**P0 / P1 无 seed 字段**（U8）。
- 结论：现有产物**因默认值恰好为 42** 而可复现；显式换 seed 则无文档可依据。纯确定性环节（P3 覆盖/连通、P4 检索）无 seed 依赖 ✅。

## 4 依赖版本 / 环境变量默认值

- 版本：本机实测 Python **3.14.4**、numpy **2.5.2**、scipy **1.18.0**、sklearn **1.9.0**（经 `~/go/pylibs`）。**meta/README 均未记录**。注：裸 `python3` 无 numpy（`ModuleNotFoundError`），所有命令能跑**仅因脚本硬编码 `sys.path.insert(0, ~/go/pylibs)`**；该目录缺失时 P0–P4 全数不可执行，而 README 仅称"依赖 `~/go/pylibs`"（U9）。
- 数据目录：5 个脚本均硬编码 `DATA_DEFAULT = os.path.expanduser("~/go/lib-catalog-data")`；`--data` 与 `LIB_CATALOG_DATA` 覆盖逻辑一致，README 表述准确 ✅（换机器/换用户即失效，建议并入 U9 的 env 块）。
- `TOPIC_LLM` 默认 `off`（`topic_graph.py:69`）与 README §6 一致 ✅；`--decay 0.86` / `--threshold 0.05` / `--budget 50000` 默认值与 README §3.5 表一致 ✅。
- `graph_report.py --curve-samples` 默认 **100**，§3.1 命令未给该参数 → 与正式基线口径相符；`meta.json#supplementary` 已如实注明"400 簇为补充复跑"✅（全链路唯一被主动登记的口径差异）。

## 5 未决问题

1. §3.2 正式 `p1-build-report.json` 的真实 CWD 无法从产物反推（`meta.json.generator` 未含 `--report`）；仅能证明"按 README 的 CWD 必崩"（U1）。
2. `p2-build-report.json` 的 `coverage_samples=400` 是否确由 `--coverage-samples 400` 显式传入，未以全量 P2 验证（全量 P2 会覆盖正式 `edges.csr.npz`/`card_topics.jsonl`，只读约束下未执行）→ 建议下轮以 `--out` 指向副本补跑。
3. 性能类数字（p50/p95/max、wall 秒）本质机器相关：本轮 P0 25.15s vs 登记 18.2s；P3 p95 4.68ms vs 登记 3.31ms。是否在 README 统一标注"性能不承诺复现"待拍板。
4. `acceptance/topics-p2.sh`、`topics-p5.sh` 未重跑（p2 依赖正式产物断言、p5 依赖 `export-sample` 一致性），其声称计数同样存在 U7 风险，待补测。
