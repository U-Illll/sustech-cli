# AUDIT-EXPORT · export_release.py topics 分支深审（导出层：量化/回读/自洽）

- **审计对象（只读）**：`reasonix-scripts/lib-catalog/export_release.py` — 393 行 / sha256 `a45b57c6b16e5f53`（20:1x 时点）
- **审计脚本**：`audit/export/audit_export.py`（复跑：`cd topics/audit/export && PYTHONPATH=~/go/pylibs python3 audit_export.py --repro [--with-v1-rerun]`）｜机读产物 `audit-export.json`（34 项检查 / 9 条问题；唯一 FAIL = E9 检出项本身）
- **数据快照（审计期未变动）**：`edges.csr.npz` `509c285aac82b9a1`(19:45:26)｜`card_topics.jsonl` `161a6ab87dc8328e`(19:45:24)｜`nodes.json` `9f5437d7034bfdaa`｜`meta.json` `c907c84126874cb3`(20:01:04)
- **被测实发物**：`topics/export-sample/v1/`（19:46 由 `--topics-only` 产出）｜**复现物**：`audit/export/repro/v1/` 与 `audit/export/repro-v1/v1/`（后者 131 MB，可删）
- **方法**：全量逐位回读 + 2000 条抽样逐条回读（含 mms 行序反查）+ 真实 `export_topics()` 合成夹具 + v1 全量复跑对照 14:01 发布包
- **约束披露（如实记录）**：① 主体源码未改一字节；② **首轮把主体源码当模块导入做夹具时，Python 的 pyc 缓存机制刷新了 `__pycache__/export_release.cpython-314.pyc`（23,026 B → 32,042 B，该 14:01 快照已不可复得）**；bytecode 级比对结论以首轮实测记录留档（§5），artifact 级结论不受影响且可复跑。脚本已加 `sys.dont_write_bytecode=True` 并改为从副本导入，杜绝再犯；③ 只写 `audit/export/`，无网络访问。

## 0 结论摘要

| 维度 | 结论 | 关键数字 |
|---|---|---|
| bit 级回读 | ✅ 全量一致 | indptr 5,188 / indices 99,268 / weights 99,268 逐字节等于源 npz；抽样 2000 (行,槽) 差异 0 |
| card_topics→CSR | ✅ 转换正确 | indptr 188,513 / ids 487,933 全量逐位一致；抽样 2000 条（含 mms 反查）一致；每卡 ≤5 ✓ |
| 量化选择 | ✅ 合理（**round**，非 floor/非 ×254） | `code=clip(round(w*255),0,255)`；max\|Δw\|=1.959e-03=**1/510**；w∈[0.1763,1.0]→码 45..255 |
| CSR 不变式 | ✅ 全部成立 | indptr 单调、`indptr[-1]==nnz`、indices<n、无自环/行内重复列、无 NaN、max_outdeg=20 ✓ |
| 复现性 | ✅ 数据面逐字节复现 | 现跑 6/6 数据文件与实发样例同哈希；manifest 仅差 generated_at + meta 哈希 |
| manifest 自洽 | ✅ 7+8 项 sha256 全对 | `total_bytes` 准确；仅"自身未自收录"（信息级） |
| v1 侧影响 | ✅ 只增不改（两级证据） | 复跑 **19/20** sha256 与 14:01 发布包逐位一致，第 20 项解压后 68,268,212 B 相同 |
| 跨文件口径 | ❌ **随包 meta.json 与随包数据不同源** | 包内 u8 反算 `w_eq1=0.0807`，包内 meta 登记 `0.1138`（pre-R1） |
| 防御性 | ❌ 2 条高危静默路径 | 空行错位、无行数/一致性断言（现有数据未触发） |

## 1 已通过的验证（可复跑，全部 PASS）

- **回读**：三类 bin 与源 npz 全量逐字节一致；2000 条随机 (行,槽) 抽样逐条对照源 npz 差异 0；2000 条卡→主题链接逐条回读 `card_topics.jsonl` 原文（含 mms 行序反查）一致。
- **契约校验**：`nodes.json[i].id == i` 违反 0（故 manifest 的「id = CSR 行号」成立）；行数 5,187 == nodes 项数；`max_outdeg=20` 与 note「出度 ≤20」一致；avg 19.1378 == manifest 声明。
- **card_topics 行序**：`card_topics.jsonl` 与 `cards.jsonl` 的 mms 逐行对齐（188,512/188,512，错位 0）；0 链接卡 22,573 == P2 登记；主题 id ∈[0,5186]。
- **边界**：空出度节点 3 个（行 2686`Z3`/3922`TG`/5088`沪甬风俗画`）以空行合法表达；`w=0→0`、`w=1→255`、`w>1` 被 clip；30 万卡超长 indptr 单调且 int32 未溢出。
- **量化实测**：296 个原始权重值 → 112 个码（2.64× 坍缩），同排相邻槽并列 39,347→39,373（量化仅新增 26），同排位次扰动 155/94,084 槽 = **0.16%**。
- **v1 只增不改**：`--topics-only` 在任何 v1 动作前 `return`；`--topics` 只向 `files` 追加且全部落在 `topics/` 子目录，不触碰任何 v1 产物文件。

## 2 问题清单（E1–E10）

- **E1 · 高｜随包 `meta.json` 的口径登记与随包数据不同源（包内自相矛盾）**｜复现：包内 `edges_weights.u8.bin` 反算 `w_eq1=0.0807 / w̄=0.3646`（= post-R1 边表），而包内 `meta.json#stages.P2` 登记 `0.1138 / 0.5187`、`pairs_aug_raw=1,753,477`（pre-R1，无 `r1_fix` 键，时间戳 18:50:24 vs 数据 19:45）。`export_topics` 复制 meta 时零校验、零快照绑定 → **建议**：复制前断言 `counts.edges_final==stats.edges`、`counts.nodes==stats.nodes`，并把 meta 的 sha256 与数据快照 sha256 一并写进 `manifest.topics.json`；不一致时 `--strict` 失败。
- **E2 · 高｜card_topics→CSR 无行数校验 + 空行 `continue` → 证据链静默错位**｜复现：夹具 `card_topics.jsonl` 3 行（含 1 空行）→ 导出 indptr 长度 3（应 4），第 2 行证据被并入第 1 行，其后所有卡左移一格；主体代码从不读 `cards.jsonl`、不做行数断言，manifest 仍声称「N_cards+1；与 cards.jsonl 行序一致」。**建议**：空行显式报错（删 `continue`）+ 断言 `len(ip)-1 == cards.jsonl 行数` + 抽样核对 mms 行序。
- **E3 · 低｜`cards.jsonl.gz` 不可复现**：gzip 头 MTIME = 打包时刻 → manifest 的 sha256 无法被重建核验，tarball 每次哈希都变（实测同源两跑 sha 不同、解压后 68,268,212 B 相同，头字节 `1f8b0808c0d3ac6a` vs `1f8b0808a82cad6a`）。**建议**：`gzip.GzipFile(fileobj=f, mode="wb", mtime=0)`。
- **E4 · 中｜CSR 行内列索引非排序，note/manifest 未声明**：5,139/5,187 行（99.07%）不是列升序，note 仅写「有向，出度 ≤20」。消费方若按标准 CSR 做二分查找会静默错答。**建议**：note 增补「行内按构建期 rank（assoc）序，非列升序」或加 `--sort-indices`，并在接口文档给 O(deg) 线性扫描用法。
- **E5 · 低｜量化契约未登记误差上界/分辨率**：仅登记 `w = v/255.0`，未记 step(1/255)、max_err(1/510)、码位空置（0–44）、饱和占比 8.07%。**建议**：`stats` 增记 `quant:{rule,step,max_abs_err,w_min,w_max,codes_used,saturated_share}`；若下游按路径乘积打分需更严精度，改 f16（实测 max_err 2.44e-04，仅 +0.397 MB = 发行包 0.3%；u8 在 12 跳最坏放大 1.142×）。
- **E6 · 低｜导出器无内置回读自检**：sha256 在写入后即时计算，但全程不重读校验 `indptr[-1]==len(indices)`、`indices<n`、`weights∈[0,1]`、行数一致。**建议**：加 `--verify` 自检开关（本审计以外部套件补齐）。
- **E8 · 信息｜`--topics-only` 与全量导出同名 `manifest.json` 但 schema 不同**（仅 topics 包 `stats` 只有 `topics`、无 `docid_rule`；靠 `name` 判别）；`topics/manifest.topics.json` 不收录自身反哈希。**建议**：加 `package_kind`，子清单写入后补自身 sha256。
- **E9 · 信息｜模块 docstring 产物清单与实现不符**（写 `embeddings_int8.npy`/`knn_csr.npz`，实产 `embeddings_int8.bin` 与 `knn_indptr/indices/sims` 三件套）——v1 时代遗留文档漂移。
- **E10 · 信息｜潜伏面**：weights 含 NaN 时 `round→clip→astype(uint8)` 不抛错、结果未定义（实测得 0，仅 RuntimeWarning）；int64→int32 超限静默回绕（`2**31+5 → -2147483643`）。现有数据不触发（w 有限且 ∈[0.176,1.0]，nnz 4.87e5 ≪ 2^31-1）。**建议**：导出入口加 `np.isfinite(w).all()`、`0≤w≤1`、`nnz<2**31-1` 断言。

## 3 未决问题（需作者/主线裁定）

1. **E1 的处置边界**：meta.json 是"多阶段滚动登记"（P0–P5 逐段追加），其 `stages.P2` 反映的是**最后一次 P2 重跑**而非**本次导出所用的边表**。是改导出器（强校验/失败），还是改 meta 语义（每阶段带 `artifact_sha256` 绑定），需作者定。
2. **E4 口径**：行内次序是否属于对外契约？若 sustech-cli 只做 `indptr` 切片则无需排序；若有外部消费方按标准 CSR 二分查找，应在接口草案里显式声明并考虑重新导出。
3. **u8 vs f16**：发行包 131 MB 中权重仅占 99 KB，f16 的 +397 KB（+0.3%）换取 8× 精度与"免量化语义"——是否值得为路径乘积打分口径升级，需下游（topic_graph 的 score 语义，见 AUDIT-GRAPH M4）一并裁定。
4. **14:01 pyc 快照已失效**：若需重跑 bytecode 级"只增不改"比对，请提供该 pyc 或 v1-only 版源码副本；当前以 artifact 级复跑（19/20 sha256）作为可复现证据。
