# AUDIT-GRAPH · topic_graph.py 深审报告

**审计对象（冻结快照）**：`audit/graph/topic_graph.audited.py` — md5 `98563120acaaf8501062d221c22e5c6c`，681 行（= 主线 `/home/wzh/go/reasonix-scripts/lib-catalog/topic_graph.py` 于 2026-09-18 20:00 的副本）。
**审计期漂移**：审计途中主线合入 R1.1（终审⑥证据修复，645→681 行），本报告一律以快照为准；**截至 20:10 实时工具 md5 仍与快照一致**，故下述结论对当前主线直接适用；之后再改动需重跑本套件。
**方法**：内存反例法 —— 自建 11 节点小图 + 小词表/TF-IDF（含环/自环/低权边/孤立点/0 权边/NaN 权重/大写 cls 词/跨词表 ASCII 词），参数矩阵（hops 0/1/2/3/12/13/70 × decay 0/0.5/0.86/1.0/1.1/2.0/负 × threshold 0/0.05/1/2 × budget 0/1/2/4/50k × top/evidence/expand-* 极值）× 图不变式断言；另有 CLI 载荷语义断言与真实数据（5187 节点 / 188,512 卡）量化。
**约束遵守**：只读主体代码（未修改一字节）；产物仅写 `audit/graph/`（合成数据落 `audit/graph/.fixtures/`，用后即删）；无网络访问。
**结论**：R1 ③ 修复有效（0 项不变式违例，真实图 1/2/3/12 跳均无超跳）；但**数据校验、参数校验、扩散分数语义、R1.1 排序键、ASCII 大小写五处仍可复现缺陷**——15 组问题 / 45 条确认点（中危 6、低危 7、信息 2），全部经独立 subagent 对抗复核（13 条 VERIFIED、1 条部分被修正、5 条新增）。

## 一、不变式体检：通过项（约 200 条断言，0 违例）
- 父链无环、终点必为源点；**路径长度 ≡ layer ≤ hops**（hops=0/1/2/3/12/13/70 全通过）；`hops=0` 仅源点且无分层。
- **score ≡ Π(路径边权) × decay^layer**（逐点重算）；子节点 score ≤ 父节点 score；层最大分随跳数单调不增。
- 源点 score=1.0/layer=0；非源点 score ≥ threshold；同跳多父正确取最大分（fixture：节点 3 双路 0.13312 vs 0.11094 → parent=1）。
- region ≤ budget 且 visited == len(score)；预算饱和标志与「确有用例被拒」一致；自环 1→1、回边 4→0 不成环；低权边（0→5, 0.04）永久剪枝。
- CLI：分层覆盖 = visited−1、hops_used == hop == len(path)−1、path[0] = 源点、层号自 1 连续、输出为**严格 JSON**；`diffuse` 两次调用结果全等；`around --json` 除 elapsed_ms 外逐字节可复现。
- 真实数据：CSR 自洽（indptr=5188、indices<5187、w∈[0.176,1.000]、0 个 NaN/0 权）；card_topics 188,512 行 == cards.jsonl 188,512 行、无空行、主题 id ≤ 5186。**→ 现有交付数据不含 F1/F7/F8 那类畸形输入，这些目前是「潜伏」而非「已发作」。**
- 护栏（CLI 层有效）：`--hops 0/13/-1`、`--decay 1.1/0/-0.2`、`--budget 0`、`--threshold 2/-0.1` 全部被拒且提示清晰。
- R1.1 新证据逻辑：证据按 `region_cover_score` 降序、无重复卡、`via_id` 确为该卡在区域内的最高分主题、每主题候选 ≤ per_topic=8、抽样确定性 —— 均通过。

## 二、问题清单（按严重度；`<T>`= 工具路径，快照需 `PYTHONPATH=/home/wzh/go/reasonix-scripts/lib-catalog`，用实时工具则不需要）

### 中危
- **M1 · F1 跨文件一致性零校验：5 类未捕获崩溃 + 1 类静默错值** — `load_edges` 只校验 dtype，不校验 `len(indptr)==len(nodes)+1`、`indices < len(nodes)`、权重有限/∈[0,1]；`nodes.json` 无 schema 校验；`card_topics` 主题 id 无范围校验；`nodes[tid]` 把 **list 下标当 id**（`search` 用 `n["id"]`，两处口径不同 → 乱序即静默取错节点）。
  复现：`python3 audit/graph/reverse_tests.py --only F1`（edges id 越界/indptr 截断/card_topics id 越界 → IndexError；缺字段 → KeyError；nodes 乱序 → seed 取错词；NaN 权重 → 输出含非法 `NaN` 字面量，严格 JSON 解析失败）。
  修复：`load_edges` 加形状+范围+有限性断言，`load_nodes` 建 `id→node` 字典并校验字段与 id 唯一，`load_card_topics` 校验主题 id 范围，`load_titles` 校验存在性与行内容；失败一律走现有 `sys.exit` 友好风格。
- **M2 · F19 ASCII 大小写不对称：349/5187 个节点用本名搜不到（唯一在交付数据上直接发作的问题）** — 查询经 `normalize_term` 转小写，而 `nodes.json` 的大写 cls 码原样存储，`match_score` 逐字符比较 → `search D9` 字面命中 0；`by_term` 用原名做键 → `around --term D9` 直接「未找到」。受害者含 freq 第一的 `TP3`（11,534）与 `I2`/`F2` 等 349 个 cls 节点（`term != normalize_term(term)`）。
  复现：`python3 <T> --data ~/go/lib-catalog-data search D9 --expand no`（0 命中）；`... around --term D9 --hops 1`（exit 1）；合成版 `--only F19`。
  修复：`load_nodes` 同时建 `normalize_term(term)` 键（保留原名做展示），`match_score` 两侧统一归一（或用 `casefold` 比较），并断言 `term == normalize_term(term)`。
- **M3 · F3 参数护栏只活在 CLI：库内直调静默接受越界参数** — `main()` 的 5 条护栏对 `diffuse()`/`make_region()`/`summarize_topic_region()` 无效；`decay>1` 使 score>1（1.21/1.8/4.0），`threshold=-1` 静默等价于放开剪枝；`path_len()` 的 `guard=64` 使 hops>64 时 `hops_used` 失真（**仅库内直调可达，CLI 因 HOPS_MAX=12 不可达 → 属防御性代码的静默失真**）。
  复现：`python3 audit/graph/reverse_tests.py --only F3`（11/11 越界参数静默通过，0 崩溃）。
  修复：护栏下沉为 `validate_params()` 并在 `diffuse()`/`make_region()` 入口调用；`path_len` 的 guard 改为 `len(region["score"])` 或超限告警；docstring 写明 score∈(0,1] 依赖 `w≤1 ∧ decay≤1`。
- **M4 · F4 score ≠ 「≤hops 最优路径分」（首访定型），但文档与排序仍按「最优」口径使用** — R1 (b) 为保 layer≡路径长度而锁定首访分数，代价是分数被系统性低估，而 `build_layers`/`evidence`/`book_count` 都用 score 排序。
  最小反例（3 节点链 0→1→2 即复现）：节点 2「神经网络」1 跳经 0→2(0.3) 得 **0.258**，同预算内 2 跳 0→1→2(0.9·0.8) 可达 **0.5325**（低估 51.6%）。
  真实图（seed=139, decay=.86, thr=.05）：hops=2/3/12 分别低估 5/100/**3392**（区域 251/1352/4841），hops=12 另有 **266** 个可达节点不在 region；最差 id=2589「算法与应用」0.0534 vs 可达 0.6020；分数不足可达值一半的达 1/38/1279 例。独立复核确认：**每条更优路线都是简单路径**（非 walk 侥幸），计数在 1e-9 容差下不变，且 DP 对照公平（每步乘 w·0.86 ≤ 0.86，路径前缀分数 ≥ 末值 ≥ threshold，中间节点均能过 diffuse 自身剪枝）。
  复现：`python3 audit/graph/reverse_tests.py --only S9 --real`。
  修复：① 头 docstring 第 23 行「取各入边的最大值」与本实现（首访定型）矛盾，必须选一个口径并写明；② 若要真最优分，需第二遍「≤hops 最优路径」DP，并明确 layer 仍=最短入区跳（二者不可兼得，须作者裁定）；③ evidence 排序继续走 R1.1 覆盖度，避免依赖被低估的 score。
- **M5 · F11b（R1.1 新引入）展示排序与聚合排序键自相矛盾** — 默认 `--expand-rank agg`，但 `expanded_hits` 按 `w = rel(spec/mx)·log1p(freq)` 排，而 `rel` 是 **spec** 归一 → agg 第一名被排到末位。真实数据「机器学习」agg 序列 `[4.83, 3.71, 3.19, 3.31, 3.03, 2.70, 3.29, 2.17]`（非降序）；「接口技」出现 `原理(14.96)` 排到 `微机原理(8.62)` 之后。最小反例：题 A(agg=10,freq=100) 与题 B(agg=7,freq=1) → w: 0.659 < 0.693，输出 [B,A] 而聚合排名 [A,B]。
  复现：`python3 <T> --data ~/go/lib-catalog-data search 机器学习 --json`；最小反例 `--only F11`。
  修复：`w` 与排序键同源（rank_by=agg 时用 `rel_agg = agg/mxa`），或固定按 agg 排序、spec 只作展示字段。
- **M6 · F5 数值参数无校验：负值泄漏 Python 负切片语义；`--expand-cards` 无下界会反转窗口或崩溃** — `--expand-cards -1` → 不报错但 `cards_scanned=-1`、窗口悄悄放大到 nz−1 张（实测 417 张，R1.1 的 200→50 收紧被整体抵消）；`-5`（nz=3）→ `np.argpartition` 抛 `ValueError` 崩溃；`search --top -1` 丢最后一行；`around --evidence -1` 返回全量候选（实测 1536 条）；`--top 0/-1` 产出「层 n>0 但 nodes=[]」的自相矛盾字段；`--expand-top -1` 静默放大（48 条 vs 9 条）。
  复现：`python3 audit/graph/reverse_tests.py --only F5`（含上述 6 例）。
  修复：argparse 层统一非负校验（top/evidence/expand-cards/expand-top ≥ 0），负值一律拒绝；`--top 0` 明确语义（拒绝或 output_n=0；`--expand-cards 0` 已能优雅返回空扩展）。

### 低危
- **L1 · F9 `--expand auto` 三处口径不一致 + 默认路径代价高** — 头 docstring「查询非词表词时」/ argparse help「无精确/前缀命中时启用」/ 行内注释与实现「无整词精确命中」。故**前缀命中**即触发全量扫描：真实数据「机器学习」auto=**561ms** vs `--expand no`=1.5ms（≈375×；代价=读 188,512 行 card_topics + TF-IDF）；「风险管」569ms；空查询也会先跑完这条退化路径（1.17s vs 0.67s）。复现：`python3 <T> --data ~/go/lib-catalog-data search 机器学习 --json`。修复：统一文案、把判据参数化（`--expand-on exact|prefix|any`），空查询前置短路，JSON 增 `expand.cost_ms`。
- **L2 · F10 空/空白查询静默命中全表** — `normalize_term` 去空白后 q=''，`term.startswith('')` 恒真 → 每词 match=0.8、src=prefix。真实数据 `search " "` 命中 **5187** 个节点、exit 0。复现：`python3 <T> --data ~/go/lib-catalog-data search " " --top 1 --expand no`。修复：`cmd_search` 开头 `if not q: sys.exit("[topic_graph] 查询词为空")`。
- **L3 · F18 `src` 标签由分数档位反推 → 覆盖率命中被误标 prefix** — `src` 用 `m≥0.8 → "prefix"` 反推，而 0.8 也可由 `0.4+0.4·cov` 分支产生：真实数据 `search tp` 唯一命中 `smartphone`（"tp" 既非其前缀、它也不是 "tp" 的前缀）却标 `prefix`；空白查询的全部 5187 行同样标 prefix。复现：`python3 <T> --data ~/go/lib-catalog-data search tp --expand no`。修复：`match_score` 直接返回匹配类型（exact/token/prefix/substr/coverage），别在 CLI 层按分数反推。
- **L4 · F7/F8 证据链数据面脆弱** — ① `cards.jsonl` 缺失 → 未捕获 `FileNotFoundError` traceback（其它 3 个 loader 都是友好退出）；② `cards.jsonl` 含空行 → `load_titles` 对空串 `json.loads` 抛 `JSONDecodeError`；③ `cards.jsonl` **短于** card_topics 时静默降级（证据行 title 为空、exit 0）；④ `card_topics.jsonl` 记录数与 `cards.jsonl` 行数不一致时**主题↔卡片整体静默错配**（少 1 行即把别张书的主题当成本书证据）。复现：`python3 audit/graph/reverse_tests.py --only F7,F8`。修复：载入时校验两文件行数一致 + 空行/短文件显式报错 + 缺文件走友好退出。
- **L5 · F6/F6b/F6d JSON 字段语义** — ① `summarize --json` 的 `mode` 报**请求值**（`http://x`）而文本自称 mock（实际已回退）；② `TOPIC_LLM` 大小写敏感（`MOCK`/`Mock` 走未实现 endpoint 分支 + stderr 警告）；③ `graph` 载荷 `hops` 是请求值而非实际深度、`edges[].w`（原始边权）与 `nodes[].w`（扩散分）同名两义、无 parent/layer 字段 → 消费方无法还原传播路径；④ `graph --json` 是 vestigial no-op；⑤ 文本与 JSON 两个通道都内嵌 elapsed_ms，均非字节稳定（`mock/off 必须确定性` 需按「除统计字段外」理解）。复现：`--only F6`。修复：mode 报实际生效值并加 `requested_mode`；`TOPIC_LLM.strip().lower()`；graph 补 `max_layer`/`hops_used` 与边 `role`（tree/extra）。
- **L6 · F12/F12b 0 分节点穿透阈值与证据打分** — `if s < threshold` 用严格小于，故 `--threshold 0` 时 0 权边把 **0 分节点**放进 region（计入 visited/layers/books，weight_min=0.0）；R1.1 的 `evidence_of` 用 `if sc:` 把 0.0 判为「不在区域」→ 仅由 0 分主题覆盖的卡被静默剔除。真实数据因 min 权重 0.176 不触发。复现：`--only F12`。修复：剪枝条件改 `s <= 0` 即剪（或校验权重 >0），`if sc is not None`。
- **L7 · F16 头 docstring 的 region schema 与实现不符** — 声明 `evidence:[{mms,title,cls,cls2,topics}]`，实现无 `topics` 键（实际 `mms,title,cls,cls2,year,via_topic,via_id,region_cover_score`）；`layers` schema 也漏了实际输出的 `type`/`hops_used`；`graph` 载荷字段未记载。复现：`grep -n 'evidence:\[' <T>`。修复：同步文档或由 schema 生成；把 `region_cover_score` 写进接口草案（LLM 消费方依赖它）。

### 信息级
- **I1 · F14 边权契约未文档化** — 边权 >1 时 score>1（合成 3.0 → weight_max 2.58），破坏 acceptance [6] 的「w∈[0,1]」隐含契约；真实图 max=1.0 故不触发。修复：`load_edges` 断言 `0 ≤ w ≤ 1` 或写明允许上界。
- **I2 · F17 死代码/陷阱** — ① 首排键 `(-w,-match,id)` 被输出前 `lit.sort((-w,id))` 丢弃，**`-match` 次键永不生效**（反例 w 并列 1.2477 时输出 match 顺序 [0.6,0.9]；存活键 (-w,id) 单射 → 对输出零影响，属纯死代码；800 条真实查询扫描 0 例分歧）；② `evidence_of(..., fwd=None)`（签名默认值）静默返回 `[]`；③ `load_card_topics(need_mms=False)` 无调用方；④ `per_topic=8` 硬编码无 CLI 开关。复现：`--only F17`。

## 三、未决问题（需作者/主线裁定）
1. **审计对象漂移**：R1.1 在审计中途改写 `evidence_of`/`tfidf_expand`（并已修掉旧的 `--evidence 0` off-by-one）。结论绑定快照 md5；主线若继续改动请重跑套件并注明新 md5。
2. **M4 语义裁定**：score 是否应为「≤hops 最优路径分」？若是，需第二遍 DP，与 R1 (b)「layer ≡ 路径长度」不可兼得，请指定 evidence/层排序以哪个为准。
3. **M5 排序键**：`w` 与 `--expand-rank` 同源，还是固定 `rank_by=agg` 且 `w=rel_agg·log1p(freq)`？两种自洽，必须选一种写进 README。
4. **M2 大小写策略**：cls 码（D9/TP3）应统一存小写、还是检索时对大写词做等值归一？涉及 `nodes.json` 重建与 `by_term` 口径，建议与 `topic_build.py` 一起定。
5. **CLI 参数语义**：`--top/--evidence/--expand-*` 的 0 与负值，期望「报错」还是「合法空结果」？
6. **证据链行序契约**：`card_topics.jsonl ↔ cards.jsonl` 的按行对应关系目前只存在于约定中；是否加一个 `meta.json` 行数/指纹字段以便启动即校验？
7. **验收接入**：`acceptance/topics-p4.sh` 只覆盖 hops/decay/budget/threshold 护栏与超跳；建议增设 [10] 段接入本反例集（`--only F1,F3,F5,F19` 等），把中危项纳入 CI。

## 四、复跑方式（离线、可重复、不依赖大数据）
```bash
cd ~/go/reasonix-scripts/lib-catalog
python3 ~/go/lib-catalog-data/topics/audit/graph/reverse_tests.py --tool <快照|实时工具> --real   # 全量：0 违例 / 45 确认点
python3 ~/go/lib-catalog-data/topics/audit/graph/reverse_tests.py --only F1,F5,F19               # 单条复现
```
退出码：0 = 跑完且无不变式违例；1 = 有不变式违例（`--strict` 时缺陷未复现也算）；2 = 环境不可用。合成数据落 `audit/graph/.fixtures/`，默认用完即删（`--keep` 保留）。
**独立复核**：另一 subagent 用自建 fixture 逐条复核（脚迹见 `audit/graph/verify-scratch/`）：13 条 VERIFIED、1 条部分 REFUTED（`--expand-cards` 负值首先是「窗口静默反转」而非必然崩溃，本报告已按两种表现改写 M6）、5 条新增缺陷（已并入 M2/L3/L5，另含 `src` 误标 L3 与空查询成本 L1）。
