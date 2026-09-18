# R2-C · 报告重跑 / 导出重建 / 边型数组实施

> 执行：dsh FINAL-RERUN 会话 ｜ 2026-09-18 21:2x–21:3x ｜ 基线：**R2-A 新数据**（5,507 节点 / 105,414 边）
> 约束遵守：**备份先行**（报告 4 份 + `export-sample/v1` + 边表 2 份 + `meta.json` 全部 `*.pre-r2c`）；**v1 发布包只读**（`lib-catalog-release/` 最后修改仍为 14:01，未触碰）；**未访问网络**；改动仅限 topics 链与工具链。
> 机读产物：`audit/r2c/{verify_export_r2c.py, verify_types_r2c.py, update_meta_r2c.py, runs-acceptance-p*.log}`

---

## 0 结论

| 交付项 | 结果 |
|---|---|
| ① 质量报告重跑（新数据） | ✅ 三口径全部**上升**，硬门槛 ②=0.9927 PASS；已刷新 `topics-report.json/txt` + allseed + 穷举 |
| ② 导出重建（修 AUDIT-EXPORT E1） | ✅ **包内 meta 与包内数据同源**：u8 反算 `w_eq1=0.0805` == meta 登记 `0.0805`；manifest 内外层 8/8+7/7 全对 |
| ③ 边型数组（AUDIT-EDGETYPE 方案 a） | ✅ `types` uint8 已入 npz 并随包导出；**三数组与 R2-A 逐位一致**；独立重算 86,846 条 kw-kw 边 **0 不符** |
| ④ meta.json | ✅ `stages.P3` 按重跑结果刷新 + 追加 `stages.R2-C`；`current_stage=R2-C` |
| ⑤ 回归 | ✅ 六份 acceptance **147 项全绿 exit 0**（P2 30→35，新增 `[4b]` 边型断言） |

## 1 三口径新数字（R2-C 重跑 vs R1 后）

命令（冻结）：`topics_report.py --data <D> --samples 400 --hops 12 --seed 42 --random-baseline`

| 口径 | R1 后（5,187 节点） | **R2-C 新（5,507 节点）** | Δ |
|---|---|---|---|
| ① 仅主簇 · 400/kw mean | 0.918799 | **0.924640** | **+0.005842** |
| ① 仅主簇 · 400/kw median | 0.941176 | **0.947368** | +0.006192 |
| ② 主簇∪类目 · 400/kw mean（**硬门槛**） | 0.991155 | **0.992701** | **+0.001546** |
| ② 主簇∪类目 · 400/kw median | 0.996303 | **0.996558** | +0.000255 |
| ③ 无向闭包 · 400/kw mean | 0.920040 | **0.928632** | **+0.008592** |
| ① 仅主簇 · 400/全节点源点 | 0.921789 | **0.920226** | −0.001564 |
| ② 主簇∪类目 · 400/全节点源点 | 0.984083 | **0.985445** | +0.001363 |
| ① 仅主簇 · **穷举全量**（5,507 源点） | 0.919449（5,187） | **0.923707** | +0.004258 |
| ② 主簇∪类目 · **穷举全量** | 0.985561（5,187） | **0.986745** | +0.001184 |

配套：p50 **2.580 ms** / p95 3.740 ms（门槛 <1000 ms，PASS）；最大分量 5,504（99.9455%）；衰减 hop1 0.309305 / hop3 0.075060（有效逐跳因子仍在容忍带）。
**判定：节点 +320 后图更连通，三口径同向改善；唯一微降是「全节点源点 ①」−0.16pp（新增 129 个回归词的簇内分母变大所致，属口径效应非质量回退）。**

## 2 导出重建与验证（AUDIT-EXPORT E1 根因修复）

**根因**：`export_topics()` 用 `shutil.copyfile` 原样复制 `topics/meta.json`，零校验、零快照绑定；而 meta 是**多阶段滚动登记**（`stages.P2` 反映"最后一次 P2 重跑"而非"本次导出所用边表"）→ 包内 meta 与包内数据可不同源（实测 u8 反算 0.0807 vs 登记 0.1138）。

**修复（`export_release.py` topics 分支）**：
- **E1**：复制前把 `stages.P2` 登记值与实测值逐项对齐（`nodes`/`edges`/`cards` 精确；`avg_out_degree`/`weight_mean`/`w_eq_1_share` 容差），比对结果 + 源数据 sha256 写入 `manifest.topics.json#snapshot`；新增 `--strict`，不一致即失败，否则**大声告警绝不静默**。
- **E2**：证据链空行由 `continue` 改为**报错**，并断言 `card_topics.jsonl` 行数 == `cards.jsonl` 行数。
- **E5**：`stats.quant` 登记 rule/step/max_abs_err/w_min/w_max/codes_used/saturated_share。
- **E8**：manifest 增 `package_kind`。**E10**：量化前显式拒绝 NaN/越界权重与 int32 溢出。

**验证结果**（`verify_export_r2c.py`，exit 0）：

| 检查 | 结果 |
|---|---|
| 外层 `manifest.json` | **8/8** 文件 sha256+size 一致；`total_bytes` 4,255,902 一致 |
| 内层 `manifest.topics.json` | **7/7** 文件 sha256+size 一致 |
| **包内 meta 与包内数据同源** | `nodes 5507=5507` / `edges 105414=105414` / `avg_outdeg 19.142=19.142` / **`w_eq1` u8 反算 `0.0805` == meta 登记 `0.0805`** / `weight_mean 0.3656=0.3656` |
| 快照绑定 | `snapshot.source_sha256` 5 项与包外源数据实测一致 |
| E2 行数 | 包内 188,512 == `cards.jsonl` 188,512；ids 501,205 == indptr[-1] |
| 包内 types | `edges_types.u8.bin` 与源 npz `types` **逐位一致** |

> 注：u8 **量化均值** 0.365497 与原始 float32 实测均值 0.365599 差 0.000102 ≤ 量化半步 1/510 —— 属量化固有偏差，**非不同源**（同源判定用 meta 登记的原始权重均值，u8 反算仅用于 `w_eq1` 这一任务书指定口径）。

## 3 边型数组（方案 a）统计与验证

**实现**：`topic_edges.py` — `build()` 构造与 `src/dst` 平行的 `tmask`；`topk_csr()` 增 `tmask` 入参，**去重阶段对同键 `bitwise_or` 归并**（§4.4），两个 `np.savez` 增 `types=`；`gextype` 规则同步登记进 `p2-build-report.params.b5_arrays/b5_edgetype_rule`。

**落盘统计**（`edges.csr.npz#types`，uint8，len == nnz）：

| mask | 组成 | 边数 | 占比 |
|---:|---|---:|---:|
| 1 | ① 卡级共现 | 89,643 | 85.04% |
| 3 | ① + ② 同簇加成 | 10,620 | 10.07% |
| 5 | ① + ③ 层级 | 4,358 | 4.13% |
| 7 | ① + ② + ③ | 793 | 0.75% |

多型边 **15,771**（14.96%）；bit0 恒置位；值域恰为 `{1,3,5,7}`（与 PROPOSAL §4.1 契约一致）。

**验证**（`verify_types_r2c.py`，exit 0）：

| 检查 | 结果 |
|---|---|
| **与 R2-A 逐位一致** | `indptr`/`indices`/`weights` **BIT-IDENTICAL**（同种子确定性，仅新增 `types` 键） |
| **kw-kw 边全量独立重算** | 86,846 条：`bit0` 不符 **0**、`bit1` 不符 **0**、误置 `bit2` **0**（源：`card_topics.jsonl` + `index/clusters.npy`，独立实现） |
| cls 端点边不变式 | 18,568 条：`bit0` 必置位违例 **0**；`bit1 ⇒ 两端同 cluster` 违例 **0** |
| bit2 层级边 | 5,151 条：目标全 cls / 源全 kw / w 全 1.0 / **每源点至多 1 条** / **有 cls 邻点的源点均有且仅有 1 条** / 计数 == 构建日志声明 5,151 |
| 抽验 | 抽样 **300** 条，覆盖 `{1,3,5,7}` 四类 |
| 固化为验收 | `acceptance/topics-p2.sh` 新增 `[4b]`（5 条断言）→ P2 30 → **35**，实跑全绿 |

> **验证过程中的一次自我纠错（留档）**：首版独立脚本假设 `bit1 ⇔ 两端同 cluster`，得 116/320 不符 —— 排查确认是**脚本建模错误**：`card_topics.jsonl` 只存 top-5 kw（cls 不占名额，§b1_cls_policy），cls2 不在其中；且 `c_sc` 还要求**该卡的簇标签** `lab == ncl[u]`，非仅节点同簇。故正确断言是**单向**的 `bit1 ⇒ 同 cluster`（实测违例 0）。该纠错同时印证 PROPOSAL §2.2「重建不自足」的判断。

## 4 meta.json 与回归

- **`stages.P3` 刷新**：原为 R1 后旧值（19:46），已按本轮重跑报告覆盖数值段（三口径/p50-p95/连通/衰减/穷举与全节点口径），`verdict`/`caliber_freeze` 原文保留，并加 `r2c_rerun_note`。**此举同时消除一处 E1 型隐患**：若不刷新，包内 meta 的 P3 段会再次与包内报告不同源。
- **追加 `stages.R2-C`**：含 `data_snapshot`（含 `edges.csr.npz` 等 sha256）、`report_rerun`、`before_after`（R1 后 vs R2-C 逐项）、`export_rebuild`（E1/E2/E5/E8/E10 修复与验证）、`edge_types` + `edge_types_verification`、`artifacts`、`backups`、`not_done`。`current_stage=R2-C`。
- **回归**：六份 acceptance 全跑 → **P0 8 / P1 17 / P2 35 / P3 21 / P4 38 / P5 28 = 147 项 PASS，FAIL 0，exit 全 0**。

## 5 残余问题

1. **[中·复现] P3 `[4]` ① 断言文案仍过时**：`topics-p3.sh` 注释与 `[4]` 仍写「① < 0.90」，R1 后 ①=0.9188、R2-C 后 ①=**0.9246** 均 ≥0.90，实际走 `info` 分支（"请复核裁定文本"）不再计 PASS —— **这是 FINAL-RERUN 已报问题在 R2-C 的二次确认**，建议改为区间断言「0.90 ≤ ① < ②」。
2. **[低] `topics-report-exhaustive.json` schema 不一致**：该文件原为 4 字段紧凑汇总，`topics_report.py` 直出的是完整报告。本轮已按**原紧凑 schema** 回写（保接口兼容），完整版另存 `audit/r2c/topics-report-exhaustive-full.json`。建议在 README 明确该文件由何命令产生。
3. **[低] AUDIT-EXPORT E3/E4 未改**：E3（gzip MTIME 导致全量 v1 包 tarball 不可复现）仅影响全量导出路径，本轮未动；E4（行内列索引非列升序）仅在导出 note 中增补声明，未加 `--sort-indices`。
4. **[信息] `edges.variant-spec.csr.npz` 同步获得 `types`**：变体边表与主边表走同一 `build()`，口径一致；未单独验收。
5. **[信息] 穷举口径耗时**：5,507 源点全量约 **76 s**（400 采样约 6 s），已足够快，但未纳入常规验收脚本。
