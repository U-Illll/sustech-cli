# AUDIT-P1 · topic_build.py 实现层深审报告

- **审计对象**：`reasonix-scripts/lib-catalog/topic_build.py` — sha256 `26864b3c…d1307ccb`，36,084 B / 788 行
- **被审产物**：`topics/nodes.json`（sha256 `9f5437d7034bfdaad8d47915777738ea254830d1a37f2039744d9bf501f70460`）、`topics/p1-build-report.json`
- **审计脚本**：`audit/p1/audit_p1.py`（全量独立重算 40 s）｜证据：`audit/p1/evidence/*.json` + `audit/p1/p1-findings.json`
- **只读边界**：主体代码与产物未改动；审计实验写入 `audit/p1/scratch/`（另起 `--out` 目录，未触碰 `topics/`）
- **结论**：结构自测（17 断言）全绿**属实**，但它不覆盖 freq 口径/归属/排序键/漏斗计数语义。独立重算确认 **16 条问题（2 高〔同一根因〕+ 8 中 + 6 低）**；其中 F2/F2b 已造成 129 个 A 源主题词被系统性剔除。

## 0. 判定表

| 维度 | 方法 | 结果 |
|---|---|---|
| 确定性 | PYTHONHASHSEED=0/1 各全量重跑一次 | **PASS**：两次 nodes.json 字节相同，且与交付件 `cmp` 完全一致 → 交付产物可从当前源码+数据复现（源码 mtime 19:03 晚于产物 18:12，但输出中性） |
| 产物不变量 | 自写正则全量校验 | **PASS**：schema 恰 7 字段、id 连续、term 唯一、freq≥1、cluster∈[0,400)、kw 字符集/长度/停用词 0 违规 |
| A1 一致性 | nodes.json ↔ build-report | **PASS**：counts.nodes/kw/cls/sources + freq.min/median/max/p25/p90/zero 全部一致 |
| **freq 独立数卡重算** | 自实现 merge+匹配，全量 5187 节点 | **PASS：0/5187 不符**；50 词分层抽查 50/50 全等 |
| merged word 口径 | 自实现 merge vs 源码函数 | **PASS**：unique 224,511/224,511，df≥12 keep 9,044/9,044，差集为空 |
| **cluster 归属重算** | 卡片级众数（tie 取小 id） | **PASS：0/5187 不符**；20 词样本 20/20 |
| top-M 原语 | 200 卡独立重算 top-M + 幂等性 | **PASS**：0 不符、0 非幂等、0 重复 token |
| 50 词自测件数值列 | 重算 rep/cls_rep/n_clusters | **PASS**：候选件 50 行三列 0 不符；判定件 50 行字段 0 不符 |
| 卡行对齐 | cards.jsonl / indptr / labels | **PASS**：188,512 / 188,512 / 188,512，无静默丢行 |
| 截断路径 | `--max-nodes 3000` 实跑 | **部分**：结果自洽（= 全量顺序前缀），但切点由浮点噪声决定（F15），且基线 `truncated=false` 从未覆盖 |

## 1. 问题清单（严重度分级）

| ID | 级别 | 问题 | 量化证据 |
|---|---|---|---|
| **F2** | **高** | 长词包含率证据 `ext_df` **双计数**：pass1（A 匹配扩展）与 pass1.5（B-CJK 扩展）对同一卡片同一扩展词各 `+1`（L469 / L494），ext_df 可超过卡片数 | 双计数事件 **207,596**；被虚增扩展词 **75,926**；恒等式 `code−union−inter=0` 精确成立 |
| **F2b** | **高** | 由 F2 派生：`containment_ratio` 可 >1.0（卡片级比值不可能 >1），并使 A 源词越过 0.9 被误判为跨词碎片 | ratio>1.0 的词 **580** 个（样本 `司治` 1.607、`朱自` 1.955，去重后为 1.0）；**129** 个 A 源词仅因双计数被剔除，且全部未进 nodes.json |
| **F1** | 中 | 截断排序键 `_score = freq × rep`（L652）**代数退化**：`rep = max_cc/freq`（L558）⇒ `_score ≡ 主导簇卡数`，freq 被约掉；README L93「按 `freq × 簇内代表性` 截断」与实现不等价 | score == max_cc（实数意义） |
| **F1b** | 中 | 交接键实证：交付顺序 **只**能用浮点键 `-freq*(max_cc/freq)` 复现；声明的次级键 `(-freq, term)` 被 1 ulp 浮点噪声压制 | float 键同位 **5187/5187**，整数键 2711/5187，`(-freq,term)` 27/5187；`score≠max_cc` 节点 **184**；最大同分组 **652** 个节点（max_cc=3）；次级键相邻违例 **62** |
| **F3** | 中 | B-only CJK 政策与实现不符：报告 `params.b_cjk_policy` 与 L12 注释称「须在 A 词表或学科词表内，否则剔除」，实现另有未披露第三通路 `b_df≥min_df_cjk 且 包含率<0.9`（L610） | B-only CJK 节点 1361 个，其中 **1351 个**（占全表 26%）无 A/学科词表证据，纯走 df 通路 |
| **F8** | 中 | `--min-df 12` 只约束 B 源；A/C 通路无频次下限，报告却把它呈现为词频闸门 | A-only 403 个（min freq **1**）、C-only 349 个（min freq **1**）→ **752/5187** 节点不受 min_df 约束；英文节点中 25 个 freq<12 且全部 sources=A |
| **F9** | 中 | 英文「质量闸门」是三分量 **OR**（freq≥200 或 cls_rep≥0.6 或 len≥9，L577-580）：低频词天然满足 `cls_rep≈1.0`；`len≥9` 是无条件旁路 | 英文 kw 2,693 个：freq<200 者 2,385、len≥9 者 1,715（该分量为真）；**仅剩 cls_rep 一个分量为真的 785 个**；最小 freq=**3** |
| **F17** | 中 | 114 个 kw 节点的 `cls` 非卡片证据众数，而是 `fallback_cls_for_cluster` 用簇级 `top_subjects[0]` 推断填充；同一缺失数据（7,118 张卡无 cls1）会把 `cls_rep` 算成 1.0，使闸门「分类纯度」分量在缺数据时为真 | 兜底填充 **114** 节点；无 cls1 卡片 **7,118** |
| **F18** | 中 | 报告 `counts.source_a_kept=1518` 高估 A 源实际贡献：161 个过 A 闸门的词在 entry 阶段被英文质量门二次过滤而未入表，漏斗中无对应计数器 | a_keep 复算 1518（与报告一致）、零频 429✅、碎片 894✅，但 a_keep∩nodes.json 仅 **1357**；缺 **161**（全为英文） |
| F6 | 中 | `cls` 字段层级混用：kw 写一级分类（F/TP），cls 节点写自身 cls2（349/349 `cls==term`，L643） | 按 `cls` 聚合会把两级代码混合 |
| F4 | 低 | 归一化口径：报告写「长度1-16」，实现另拒 len==1 ⇒ kw 实为 2..16、cls 为 1..6 | L239 + L247 |
| F5 | 低 | 死代码/不可达分支 7 处，其中 L678 `if n > max_nodes` 告警**永不可达** → 「规模受控」无告警保证；截断 if/else 两分支同一 sort | L347 `single` 恒空、L650 sources 兜底不可达、L604 重复过滤 |
| F7 | 低 | `sources` 语义是「在该源词表中出现」，非「该源通路实际采纳」：L530-531 对全量 a_set 置 A 位（含被 A 剔除、经 B 入表的词） | 含 A 位的节点 1357，A 源独立贡献无法还原 |
| F10 | 低 | cluster 归属并存两套口径（卡片级众数 vs 簇关键词表级众数，量纲=卡数 vs 关键词槽数）；`a_membership` 兜底恒不可达，代码/报告未声明该分歧 | 20 词中 A 词表口径可比 3 个、与卡片级一致 2 个 |
| F15 | 低 | 截断路径自洽但边界由浮点噪声决定；基线 `truncated=false`，该分支从未被验收覆盖 | 切点落在 **333** 个同整数分节点中间 |
| F16 | 低 | 判定件 `p1-sample50.txt` 比生成件少 3 列（cls_rep/rep/n_clusters）→ 噪声率 0.04 的判定依据未随判定件留存，无法在该文件内复核 | 生成件 13 列 / 判定件 10 列，id 集一致 |

## 2. 主要发现的复现

```bash
cd /home/wzh/go/lib-catalog-data/topics/audit/p1
python3 audit_p1.py                    # 40s：S0 静态→S7 自测件复核，落 evidence/*.json + p1-findings.json
bash scratch/run_experiments.sh        # 确定性 ×2 + 截断 ×1，写入 audit/p1/scratch/{d1,d2,trunc}/
```
- **F2/F2b**：`evidence/ext_double_count.json`（`double_count_events`、`ratio_gt1_sample`、`flip_sample`）；机制见 L453-471 与 L481-498 两次 `for e in ext_seen: ext_df[e] += 1`。
- **F1/F1b**：`evidence/order_test.json`（`positions_equal_to_float_score_key=5187` vs `..._maxcc_int_key=2711`）；代数推导 `f*(cc/f)=cc`。
- **F8/F9/F3/F18**：`evidence/boundary.json`、`evidence/ext_double_count.json:a_source_funnel`。
- **F17**：`evidence/cls_level.json` + `boundary.json:en_gate.kw_nodes_with_fallback_filled_cls`。

## 3. 未决问题（本轮未给结论）

1. **F2 修复后的基线漂移未知**：按 card 去重后 129 个 A 源词将回到词表，A 保留集 1518→约 1647、nodes 规模与 P2/P3/P4 全部下游产物（edges/card_topics/meta/manifest）都需重跑并重新冻结哈希。
2. **`freq` 三源量纲不可比**：A=命中标题子串卡数、B=命中 top-10 合并词卡数、C=该 cls2 卡数，共用同一字段；对 `_score`、P2 共现上限与「高频词」判读的影响未量化，是否需要在 schema 层拆分（freq_a/freq_b/freq_c）待定。
3. **F9 闸门收紧的代价未评估**：785 个「仅靠 cls_rep 过闸」的英文词中多少是真噪声、多少是低频专词（如 `periodontal`、`jean-christophe`），需人工判读样本，不宜直接砍。
4. **复合词缺失机制（对应已知限制⑧）**：探针显示 `机器学习`/`人工智能` 的成词 df **= 0**，而其组件 bigram df 分别 339/72/176 与 225/87/353 —— 说明 top-10 预筛 + 链式合并阈值联合导致成词几乎不发生；是否改为「先合并再按卡取 top-M」或提高 top-M，收益/噪声比未评估。
5. **噪声率 0.04 的独立复核**：本轮只验证了判定件的字段与数值列一致性，未重新人工判读 50 词，也未扩大样本给出置信区间。
