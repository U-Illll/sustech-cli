#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topic_graph.py — 图书馆主题图查询编排（GraphRAG-lite · P4）

在 v1 文档图之外新增的「主题图」层上做查询（只读，不动 v1 文件）：
  数据: <data>/topics/nodes.json         5,187 主题节点（kw 4,838 + cls 349）
        <data>/topics/edges.csr.npz      CSR 有向边（indptr int64 / indices int32 / weights float32，出度 ≤20）
        <data>/topics/card_topics.jsonl  证据链：每卡 top-5 主题（188,512 行）
        <data>/card_topics 反查用 cards.jsonl 只按需抽样标题（不对全量做 JSON 解析）

子命令:
  search  "查询词"                 主题检索：词面匹配（exact/token/prefix/substr）× 特异性词权排序（不加载书卡，最快）
                                   排序键 = ①匹配档位 ②w_spec = log1p(freq)/√freq（低频专指优先）③freq/id
                                   + 退化路径 ② 近词扩展（--expand auto 默认）：查询非词表词时，
                                     用 v1 TF-IDF 索引检索相关书 → 聚合其 top-5 主题 → 映射回主题节点
                                     （口径与 catalog_vector.Index.q_kw 同源；输出 src=tfidf-expand）
  around  <topic_id>               加权扩散：w_hop = w_parent × edge_w × 0.86，阈值 0.05，预算 ≤50k 节点
                                   → 分层邻域 + 书证据（种子/近邻锚定 × 同簇一致 × 特异性 × 软去重）
  graph   <topic_id>               JSON 子图 {nodes:[{id,term,type,cluster,w}], edges:[{src,dst,w}]}
  summarize <topic_id>             LLM 接口存根：summarize_topic_region(region) -> str

R2-B 修复（对齐 AUDIT-GRAPH M2 + relevance 审计 §6-1/§6-2）:
  ① **ASCII 大小写归一**（M2）：查询侧与词表侧统一走 norm_key()（= normalize_term，同源）。
     旧实现逐字符比较 → nodes.json 的 349 个大写 cls 码（D9/TP3/I2…）用本名搜不到。
  ② **search 种子排序引入特异性**：旧词权 match × log1p(freq) 使高频泛词恒占首位
     （审计实测 7/10 查询 rank-1 是泛词），端到端相关率被拖到 P1 4/10、P2 5/10。
     现按 匹配档位 → w_spec=log1p(freq)/√freq → freq/id 排序，rank-1 落在最专门的那个词上。
  ③ **证据层相关性优先**：旧口径按「区域加权覆盖度」取样，泛词覆盖多的卡恒占首位
     （实测 around 184 证据 3/5 为土建《结构力学》；规划查询证据 5/5 离题）。
     现按 同簇闸门（种子 cluster）+ 一跳近邻覆盖度 取样，并对同名多卷做软去重。
     详见 evidence_of() 文档；调参常量 R2B_CLUSTER_W / R2B_ANCHOR_HOPS。

扩散规则（对齐交接文档 §3.4 / §3.2）:
  * 初始 score(seed)=1.0；每跳 score(v) = score(u) × edge_w(u→v) × 0.86（有向出边，取各入边的最大值）
  * 只保留 score ≥ --threshold（默认 0.05，与 §3.4 一致）；访问预算 --budget（默认 50,000 节点）
  * --hops 默认 2、上限 12（§3.4 的 12 跳预算远超本图所需：实测第 5-6 跳即覆盖全图 94%）

LLM 接口（签名固定，实现为存根；**待与作者讨论**，见 topics/docs-draft/interface-proposal.md）:
  def summarize_topic_region(region: dict) -> str
  * region 结构（R2-B 同步为实际实现，AUDIT-GRAPH F16）:
      {seed:{id,term,type,freq,cluster,cls}, hops, decay, threshold,
       layers:[{hop,n, nodes:[{id,term,type,score,path,hops_used}]}],
       evidence:[{mms,title,cls,cls2,year,via_topic,via_id,min_hop,tier,region_cover_score,call,loc}],
       stats:{visited,edges_scanned,books,books_capped,saturated_budget,elapsed_ms,
              weight_min,weight_median,weight_max}}
  * 环境变量 TOPIC_LLM: off（默认；纯结构化占位文，不调用任何模型）| mock（确定性模板文）|<endpoint>
  * 硬约束: 默认不触网；mock/off 必须确定性（同 region 同输出，无随机/时间戳）；不得引入 region 之外的事实
  * 失败回退: 任何异常 → 回退占位文 + stderr 警告；--strict-llm 时以 exit 3 暴露

数据目录: $LIB_CATALOG_DATA 或 ~/go/lib-catalog-data
用法示例:
  python3 topic_graph.py search "机器学习" --top 10
  python3 topic_graph.py search "机器学习 入门" --top 3 --expand-top 6   # 非词表查询 → 触发近词扩展
  python3 topic_graph.py search "量子 科普" --expand no                  # 强制关闭扩展（对照）
  python3 topic_graph.py around 123 --hops 2 --top 12 --evidence 8
  python3 topic_graph.py graph 123 --hops 2 --json-out /tmp/sub.json
  python3 topic_graph.py summarize 123 --hops 2
"""
import argparse
import json
import math
import os
import re
import sys
import time
from heapq import nlargest

_PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)
import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from catalog_vector import tokenize                     # 同源分词，禁止另写
from topic_build import normalize_term                   # 同源归一
import book_labels as BL                                 # 书标编号/位置接入（labels.db，2026-09-20）

DATA_DEFAULT = os.path.expanduser("~/go/lib-catalog-data")
DECAY_DEFAULT = 0.86
THRESHOLD_DEFAULT = 0.05
BUDGET_DEFAULT = 50000
HOPS_MAX = 12
TOPIC_LLM_DEFAULT = "off"

# --- R2-B 调参（修复①②③共用的特异性/锚定参数）--------------------------------
R2B_CLUSTER_W = 2.0        # 证据锚点与种子同 cluster（同义项/同域）时的加权
R2B_ANCHOR_HOPS = 1        # 证据锚点允许的最大跳数（0=种子本身，1=一跳近邻）


def norm_key(term):
    """查询/词表统一键（R2-B 修复①）。

    M2 缺陷：nodes.json 存大写 cls 码（D9/TP3…），查询侧经 normalize_term 转小写，
    旧实现逐字符比较 → 349/5187 个节点用本名搜不到（含 freq 第一的 TP3）。
    现查询侧与词表侧一律经本函数归一（= topic_build.normalize_term，同源，禁另写）。
    """
    return normalize_term(term)


def term_spec(freq):
    """特异性因子 1/√freq（freq = 该主题的书目证据数，即词表文档频率）。

    与 R1.1 近词扩展排序的 agg/√freq 同源。R2-B 起用于 search 词权（w_spec）：
    抑制「高频泛词恒占首位」（relevance 审计实测 7/10 查询 rank-1 是泛词）。
    注意：证据层**不用**本因子 —— 证据要的是「覆盖几个核心主题」而非「含一个稀有词」，
    实测乘 1/√freq 会把《深度工作》《章鱼的心灵》这类长尾误抽进证据（见 evidence_of ③）。
    """
    return 1.0 / math.sqrt(max(int(freq), 1))


def series_key(title):
    """多卷/丛书归并键（R2-B 证据软去重）：去英文副题、去卷册序号与空白。

    动机（relevance 审计 §6-1）：证据常被同一套多卷书挤满（世界佛教通史×5、结构力学×3、
    20 世纪马克思主义发展史×3），多样性为零。仅按原题精确匹配无法归并（卷号写在题名内）。
    """
    t = (title or "").split("=")[0]                     # 去「= English subtitle」
    t = re.sub(r"第?\s*[0-9０-９一二三四五六七八九十百]+\s*[卷册部辑篇集]", "", t)
    return re.sub(r"\s+", "", t)


def resolve_data(args):
    d = (getattr(args, "data", None) or os.environ.get("LIB_CATALOG_DATA") or DATA_DEFAULT)
    return os.path.abspath(os.path.expanduser(d))


def topics_dir(D):
    return os.path.join(D, "topics")


# ---------------------------------------------------------------------------
# 载入
# ---------------------------------------------------------------------------
def load_nodes(D):
    """读节点表 → (nodes[list]，by_term{归一键: id})。

    R2-B 修复①：by_term 改用归一键（norm_key），使大写 cls 码（D9/TP3）也能被
    `--term` 命中；归一后同形的多个节点取 freq 高者（保证确定性）。
    """
    p = os.path.join(topics_dir(D), "nodes.json")
    if not os.path.exists(p):
        sys.exit(f"[topic_graph] 找不到 {p}；先跑 python3 topic_build.py --data {D}")
    nodes = json.load(open(p, encoding="utf-8"))
    by_term = {}
    for n in nodes:
        k = norm_key(n["term"])
        if k not in by_term or int(n["freq"]) > int(nodes[by_term[k]]["freq"]):
            by_term[k] = n["id"]
    return nodes, by_term


def load_edges(D):
    p = os.path.join(topics_dir(D), "edges.csr.npz")
    if not os.path.exists(p):
        sys.exit(f"[topic_graph] 找不到 {p}；先跑 python3 topic_edges.py --data {D}")
    z = np.load(p)
    indptr, indices, weights = z["indptr"], z["indices"], z["weights"]
    if indptr.dtype != np.int64 or indices.dtype != np.int32 or weights.dtype != np.float32:
        sys.exit("[topic_graph] 边表 dtype 不符（应为 indptr int64 / indices int32 / weights float32）")
    return indptr, indices, weights


def load_card_topics(D, need_mms=True, need_forward=False):
    """读证据链 → (card_mms[line], topic_cards{id:[line,...]}[, card_topics[line]])
    need_forward=True 时额外返回每卡的主题列表（近词扩展聚合用）。"""
    p = os.path.join(topics_dir(D), "card_topics.jsonl")
    if not os.path.exists(p):
        sys.exit(f"[topic_graph] 找不到 {p}；先跑 python3 topic_edges.py --data {D}")
    mms_list, topic_cards, fwd = [], {}, ([] if need_forward else None)
    with open(p, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            idx = len(mms_list)
            mms_list.append(o.get("mms", "") if need_mms else "")
            ts = [int(t) for t in o.get("topics", ())]
            if need_forward:
                fwd.append(ts)
            for t in ts:
                topic_cards.setdefault(t, []).append(idx)
    return (mms_list, topic_cards, fwd) if need_forward else (mms_list, topic_cards)


def load_titles(D, want_lines):
    """只为需要的行号解析 cards.jsonl（其余行只做行计数），避免 68MB 全量 JSON 解析。"""
    if not want_lines:
        return {}
    p = os.path.join(D, "cards.jsonl")
    out, want = {}, set(want_lines)
    with open(p, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i in want:
                c = json.loads(line)
                out[i] = {"title": (c.get("title") or "").replace("$$Q", " "),
                          "cls": c.get("cls") or "", "cls2": c.get("cls2") or "",
                          "year": c.get("year") or ""}
                if len(out) == len(want):
                    break
    return out


# ---------------------------------------------------------------------------
# 近词扩展（非词表查询的退化路径 ②）：书目 TF-IDF 检索 → 聚合命中书的主题
# ---------------------------------------------------------------------------
def tfidf_expand(D, query, mms_list, card_topics_fwd, nodes, top_cards=50, top_topics=10, rank_by="agg"):
    """查询词不在主题词表时的退化路径：用 v1 的 TF-IDF 索引（catalog_vector 同源）检索相关书目，
    再聚合这些书的 top-5 主题 → 映射回主题节点。返回 [(topic_id, agg, cards[line,...]), ...]。
    口径：与 catalog_vector.Index.q_kw 完全一致（token 计数 × idf、查询向量 L2 归一、X @ q^T 余弦）。"""
    from collections import Counter
    from scipy import sparse
    idx_dir = os.path.join(D, "index")
    xp, vp, ip_ = (os.path.join(idx_dir, f) for f in ("tfidf.npz", "vocab.json", "idf.npy"))
    if not (os.path.exists(xp) and os.path.exists(vp) and os.path.exists(ip_)):
        return [], {"reason": "index/tfidf.npz 缺失（v1 索引未构建）"}
    X = sparse.load_npz(xp)
    vocab = {t: i for i, t in enumerate(json.load(open(vp, encoding="utf-8")))}
    idf = np.load(ip_)
    cnt = Counter(t for t in tokenize(query) if t in vocab)
    if not cnt:
        return [], {"reason": "查询词未命中 v1 词表（tokenize 后无有效 token）"}
    js = np.fromiter((vocab[t] for t in cnt), dtype=np.int32, count=len(cnt))
    vs = np.fromiter((float(idf[vocab[t]]) * w for t, w in cnt.items()), dtype=np.float32, count=len(cnt))
    q = sparse.coo_matrix((vs, (np.zeros(len(js), dtype=np.int32), js)), shape=(1, X.shape[1])).tocsr()
    nrm = float(np.sqrt(np.asarray(q.multiply(q).sum()).ravel()[0]))
    if nrm > 0:
        q = q / nrm
    scores = np.asarray((X @ q.T).todense()).ravel()
    nz = np.flatnonzero(scores)
    if nz.size == 0:
        return [], {"reason": "无书目命中（该词在 188,512 张卡里无 TF-IDF 证据）"}
    k = min(top_cards, nz.size)
    top = nz[np.argpartition(-scores[nz], k - 1)[:k]]
    top = top[np.argsort(-scores[top], kind="stable")]
    agg, sup = {}, {}
    for i in top:
        s_i = float(scores[i])
        for t in card_topics_fwd[i]:
            agg[t] = agg.get(t, 0.0) + s_i
            sup.setdefault(t, []).append(int(i))
    # R1.1 修复（终审⑥相关性闭环）：两条——
    # (1) 排序键保持 **agg 主序**（证据强度），专指度 agg/√freq 仅作输出字段（--expand-rank spec 可切换）：
    #     实测纯专指度归一会把「神经网络」查询的低频同形词 神经病学(freq=26)/neurology(freq=44) 顶到第 2-3 名（回归）。
    # (2) **收紧聚合窗口**：默认 top_cards 由 200 降到 50——聚合应发生在"最相关的 50 张卡"上，
    #     否则泛化书目稀释意图限定词。实测（同一排序键）：
    #       人工智能伦理: top_cards=30/50 → ethics 排名 2；=100 → 7；=200 → 13（原缺陷）
    #       神经网络    : top_cards=30/50/100 → 神经病学/neurology 不在前 8；=200 → 第 7（原缺陷）
    scored = [(t, a, a / math.sqrt(max(int(nodes[t]["freq"]), 1))) for t, a in agg.items()]
    key = (lambda r: (-r[2], -r[1], r[0])) if rank_by == "spec" else (lambda r: (-r[1], -r[2], r[0]))
    ranked = sorted(scored, key=key)[:top_topics]
    mx = max((r[2] for r in ranked), default=1.0)
    mxa = max((r[1] for r in ranked), default=1.0)
    return [{"id": t, "agg": a, "spec": s, "rel": s / mx if mx else 0.0, "rel_agg": a / mxa if mxa else 0.0,
             "cards": sup.get(t, [])[:3], "n_cards": len(sup.get(t, []))} for t, a, s in ranked], \
           {"cards_scanned": int(k), "cards_hit": int(nz.size),
            "rank_key": ("agg/√freq（专指度，R1.1 可选）" if rank_by == "spec" else "agg（证据强度，R1.1 默认）"),
            "window_note": "聚合窗口默认 50 张最相关卡（R1.1：200→50，避免泛化书稀释意图限定词）"}


# ---------------------------------------------------------------------------
# search：词面匹配 × 词频权重
# ---------------------------------------------------------------------------
def match_score(term, q, q_tokens):
    """词面匹配分：整词精确 1.0 / 查询 token 精确 0.9 / 前缀 0.8 / 子串 0.6；多 token 按覆盖率折算。"""
    if term == q:
        return 1.0
    if q_tokens and term in q_tokens:
        return 0.9
    s = 0.0
    if term.startswith(q) or q.startswith(term):
        s = 0.8
    elif q in term or term in q:
        s = 0.6
    if q_tokens:
        hit = sum(1 for t in q_tokens if t in term)
        cov = hit / float(len(q_tokens))
        if hit and cov >= 0.5:
            s = max(s, 0.4 + 0.4 * cov)
    return s


def cmd_search(args):
    D = resolve_data(args)
    nodes, _by_term = load_nodes(D)
    q = normalize_term(args.query)
    q_tokens = [normalize_term(t) for t in tokenize(args.query)]
    t0 = time.time()
    hits = []
    for n in nodes:
        nterm = norm_key(n["term"])                        # R2-B 修复①：词表侧与查询侧同口径
        m = match_score(nterm, q, q_tokens)
        if m <= 0:
            continue
        src = ("exact" if m >= 1.0 else "token" if m >= 0.9 else
               "prefix" if m >= 0.8 else "substr")
        # R2-B 修复②：排序三键（见下方 hits.sort）——
        #   ① 匹配档位（exact > token > prefix > substr）严格优先：否则长尾专指词会越级压掉整词命中
        #      （实测旧口径下 search "D9" 的首位是 TD9，而 D9 本体排在后面）；
        #   ② 特异性词权 w_spec = log1p(freq) × spec(freq)，spec = 1/√freq（见 term_spec）：
        #      抑制「高频泛词恒排首位」——审计实测旧口径 7/10 查询 rank-1 是泛词
        #      （学习>机器、计算>量子、中国>文学、数据>结构>算法、哲学>佛教、城市>规划、learning>deep），
        #      使 search→around 的默认种子落在查询里最专门的那个词上；
        #   ③ freq 降序、id 升序（确定性）。
        w_spec = math.log1p(max(int(n["freq"]), 0)) * term_spec(n["freq"])
        hits.append({"id": n["id"], "term": n["term"], "type": n["type"], "freq": n["freq"],
                     "cluster": n["cluster"], "cls": n["cls"], "sources": n["sources"],
                     "src": src, "match": round(m, 3), "w": round(m * w_spec, 4),
                     "w_spec": round(w_spec, 4)})
    hits.sort(key=lambda h: (-h["match"], -h["w_spec"], -h["freq"], h["id"]))
    lit_n = len(hits)
    best_match = max((h["match"] for h in hits), default=0.0)

    # 退化路径判定：no=从不；yes=总是；auto=查询本身不是主题词表词（无整词精确命中，含零命中）
    do_expand = args.expand == "yes" or (args.expand == "auto" and best_match < 1.0)
    exp_info, exp_hits = {}, []
    if do_expand:
        mms_list, _tc, fwd = load_card_topics(D, need_mms=True, need_forward=True)
        exp_hits, exp_info = tfidf_expand(D, args.query, mms_list, fwd, nodes,
                                          top_cards=args.expand_cards, top_topics=args.expand_top,
                                          rank_by=args.expand_rank)
        have = {h["id"] for h in hits}
        for e in exp_hits:
            if e["id"] in have:
                continue
            n = nodes[e["id"]]
            hits.append({"id": e["id"], "term": n["term"], "type": n["type"], "freq": n["freq"],
                         "cluster": n["cluster"], "cls": n["cls"], "sources": n["sources"],
                         "src": "tfidf-expand", "match": round(e["agg"], 6),
                         # 扩展项词权同口径乘 spec，使 w 列与字面命中可比（R2-B 修复②）
                         "w": round(e["rel"] * math.log1p(max(int(n["freq"]), 0)) * term_spec(n["freq"]), 4),
                         "spec": round(e.get("spec", 0.0), 6), "rel_agg": round(e.get("rel_agg", 0.0), 6),
                         "support": [mms_list[i] for i in e["cards"]], "n_support_cards": e["n_cards"]})
        exp_hits = [h for h in hits if h["src"] == "tfidf-expand"]

    lit = [h for h in hits if h["src"] != "tfidf-expand"]
    # R2-B：输出排序与首排同键（修复 AUDIT-GRAPH F17i 的「次键被丢弃」漂移），扩展项单独按 w 排
    lit.sort(key=lambda h: (-h["match"], -h["w_spec"], -h["freq"], h["id"]))
    exp_sorted = sorted(exp_hits, key=lambda h: (-h["w"], h["id"]))
    ms = (time.time() - t0) * 1000

    if args.json:
        print(json.dumps({"query": args.query, "normalized": q,
                          "literal_hits": lit[: args.top], "literal_total": lit_n,
                          "expand": {"used": bool(do_expand), "mode": args.expand, **exp_info},
                          "expanded_hits": exp_sorted[: args.expand_top],
                          "elapsed_ms": round(ms, 2)}, ensure_ascii=False, indent=1))
        return 0

    print(f"[search] query='{args.query}' → 归一 '{q}' | 字面命中 {lit_n} 个"
          + (f" | 近词扩展 {len(exp_sorted)} 个（{exp_info.get('cards_scanned', 0)} 张卡命中 "
             f"{exp_info.get('cards_hit', 0)} 张{('，' + exp_info['reason']) if exp_info.get('reason') else ''}）"
             if do_expand else "")
          + f" | {ms:.1f}ms")
    print(f"{'id':>6} {'term':<24} {'type':<4} {'freq':>7} {'cluster':>8} {'cls':<5} {'src':<13} {'w':>9}")
    for h in lit[: args.top]:
        print(f"{h['id']:>6} {h['term'][:23]:<24} {h['type']:<4} {h['freq']:>7} {h['cluster']:>8} "
              f"{str(h['cls'])[:4]:<5} {h['src']:<13} {h['w']:>9.3f}")
    if not lit:
        print("  （字面零命中）")
    if do_expand:
        print(f"\n[近词扩展] TF-IDF 检索相关书目 → 聚合书的 top-5 主题（退化路径 ②；源: catalog_vector 同源 TF-IDF）")
        if not exp_sorted:
            print(f"  （扩展亦无结果：{exp_info.get('reason', '未知')}）")
        for h in exp_sorted[: args.expand_top]:
            sup = "、".join(h.get("support", [])[:2])
            print(f"{h['id']:>6} {h['term'][:23]:<24} {h['type']:<4} {h['freq']:>7} {h['cluster']:>8} "
                  f"{str(h['cls'])[:4]:<5} {'tfidf-expand':<13} {h['w']:>9.3f}"
                  + (f"   支持书: {sup}" if sup else ""))
    if not lit and not exp_sorted:
        print("  （换同义词，或用 `topic_graph.py search <词> --top 50` 看更多候选）")
    return 0


# ---------------------------------------------------------------------------
# 加权扩散（around / graph / summarize 共用）
# ---------------------------------------------------------------------------
def diffuse(seed, hops, indptr, indices, weights, decay, threshold, budget):
    """加权扩散：w_hop = w_parent × edge_w × 0.86（阈值 + 预算剪枝）。

    R1 修复③（终审"扩散超跳"）——三条不变式（缺一不可）：
      (a) **层快照传播**：第 h 跳只读「第 h-1 跳结束」的分数（prev），
          修复前直接读 score[u]，而 u 若在本跳被其他节点更新过，其出边会拿到 h 跳分数再外扩 → 路径超跳；
      (b) **首访定型（strict layering）**：一个节点一旦入区，其 layer/parent **不再改写**。
          否则层内提级会让已生成后代节点的层号与真实父链长度脱钩（实测真实图 hops=3 时 12 例不一致）；
      (c) **同跳候选按分数取最大**：同一跳内多个父节点指向同一新节点时取分数最高者（平局按 id 升序，保证确定性）。
    由 (a)+(b) 得：对任意入区节点，父链边数 ≡ layer ≡ 其真实路径长度 ≤ hops；
    score ≡ Π(路径边权) × 0.86^layer（A3-c 逐点校验）。
    预算语义：region 节点数（含源点）≤ budget；visited 含源点。"""
    score = {seed: 1.0}
    parent = {seed: None}
    layer = {seed: 0}
    frontier = [seed]
    visited, scanned, saturated = 1, 0, False
    for h in range(1, hops + 1):
        prev = {u: score[u] for u in frontier}        # (a) 层快照
        cand = {}                                     # (c) 本跳候选：v → (score, parent)
        for u in frontier:
            su = prev[u]
            a, b = int(indptr[u]), int(indptr[u + 1])
            for p in range(a, b):
                scanned += 1
                v = int(indices[p])
                if v in score:                        # (b) 首访定型：已入区节点不再改写
                    continue
                s = su * float(weights[p]) * decay
                if s < threshold:
                    continue
                cur = cand.get(v)
                if cur is None or s > cur[0] or (s == cur[0] and u < cur[1]):
                    cand[v] = (s, u)
        if not cand:
            break
        nxt = []
        for v in sorted(cand, key=lambda x: (-cand[x][0], x)):   # 确定性顺序：分数降序 → id 升序
            if visited + 1 > budget:                  # 预算：region ≤ budget（含源点）
                saturated = True
                break
            s, u = cand[v]
            score[v] = s
            parent[v] = u
            layer[v] = h                              # layer = 真实路径长度（≤ hops）
            visited += 1
            nxt.append(v)
        if saturated or not nxt:
            break
        frontier = nxt
    return {"score": score, "parent": parent, "layer": layer,
            "visited": visited, "edges_scanned": scanned, "saturated": saturated}


def build_layers(region, nodes, hops, top_per_layer):
    by_layer = {}
    for nid, h in region["layer"].items():
        by_layer.setdefault(h, []).append(nid)
    layers = []
    for h in sorted(by_layer):
        ids = by_layer[h]
        if h == 0:
            continue
        keep = nlargest(top_per_layer, ids, key=lambda i: (region["score"][i], -i))
        keep.sort(key=lambda i: (-region["score"][i], i))
        layers.append({"hop": h, "n": len(ids), "nodes": [
            {"id": i, "term": nodes[i]["term"], "type": nodes[i]["type"],
             "score": round(region["score"][i], 6), "path": path_of(i, region, nodes, hops),
             "hops_used": path_len(i, region)}
            for i in keep]})
    return layers


def path_of(nid, region, nodes, max_hops=None):
    """回溯最优路径（term 列表）。max_hops 给出时按跳数上限裁剪（防御性：R1 修复③后不应再触发）。"""
    out, cur, guard = [], nid, 0
    limit = 24 if max_hops is None else max_hops + 1
    while cur is not None and guard < limit:
        out.append(nodes[cur]["term"])
        cur = region["parent"].get(cur)
        guard += 1
    return list(reversed(out))


def path_len(nid, region, max_hops=64):
    """父链边数（= 真实路径长度）。"""
    n, cur, guard = 0, region["parent"].get(nid), 0
    while cur is not None and guard < max_hops:
        n += 1
        cur = region["parent"].get(cur)
        guard += 1
    return n


def evidence_of(D, region, nodes, topic_cards, card_mms, k, per_topic=8, fwd=None, seed=None):
    """证据书抽样：**种子/近邻锚定 × 同簇一致 × 特异性**（R2-B 修复③；对齐 relevance 审计 §6-1）。

    旧口径（R1.1）：按「卡对区域的加权覆盖度 Σ region_score(t)」排序 —— 泛词覆盖多的卡恒占首位。
      实测代价（audit/relevance/REPORT.md §4 主因①，直接造成 5 条降档）：
        `around 184`（量子）证据 3/5 是土建《结构力学》；`规划` 查询证据 5/5 离题（生涯/战略/国民规划）。
    R2-B 改为「同簇闸门 + 近邻覆盖度」四步（全程确定性）：
      ① **近邻锚定**：只有「种子（layer 0）+ R2B_ANCHOR_HOPS 跳近邻」的主题可作锚点 ——
         二跳以外的泛化主题（世纪/现代/发展/小说/力学…）不再贡献分数；
      ② **同簇闸门（主序）**：卡内锚点若含与种子同 cluster（同义项/同域）的主题 → 进第 0 档；
         否则进第 1 档；两档皆无 → 第 2 档（仅区域主题，兜底）。这一档抑制多义词跨义取样：
         真实数据实测 `量子` 的同簇主题只有「量子」本身（力学/quantum/mechanics 均在别簇），
         故土建《结构力学》被降到第 1 档；`规划` 与「城市/城乡」同簇，故城乡规划书升到第 0 档。
      ③ **近邻覆盖度（次序）**：同档内按 Σ_{一跳内锚点} score(t) × (同簇 ? R2B_CLUSTER_W : 1) 降序 ——
         覆盖越多核心主题的卡越前（《TensorFlow深度学习》胜《深度工作》，后者只有 deep 一词）；
         刻意**不乘特异性**：证据面要的是「覆盖几个核心主题」而非「含一个稀有词」，
         实测乘 1/√freq 会把《深度工作》《章鱼的心灵》《声乐曲选集》这类长尾误抽进证据。
      ④ **软去重**：同名多卷先各留一册，候选不足 k 时再按分数补齐（世界佛教通史 ×5 → 1 册 + 补齐）。
    排序键 = (同簇档↑, 卡内最小跳数↑, 覆盖度↓, 行号↑)；锚定卡不足 k 时用旧覆盖度口径补齐（不空返回）。
    字段：via_topic/via_id = 该卡覆盖度最高的锚点主题；region_cover_score = 近邻覆盖度（名字保持兼容）；
          min_hop = 卡内锚点最小跳数（0=种子直达）；tier = 同簇档（0=同簇 / 1=近邻 / 2=兜底）。
    注意：`fwd`（card_topics 正排）为必需参数 —— 缺省会静默返回空证据（AUDIT-GRAPH F17ii 待重构为 fail-fast）。
    """
    seed_clu = nodes[seed].get("cluster") if (seed is not None and 0 <= seed < len(nodes)) else None
    order = sorted(region["score"], key=lambda i: (-region["score"][i], i))
    cand, seen = {}, set()
    for nid in order:
        for line in topic_cards.get(nid, ())[:per_topic]:
            if line not in seen:
                seen.add(line)
                cand[line] = None
    rows, fallback = [], []
    for line in cand:
        ts = fwd[line] if fwd is not None and line < len(fwd) else None
        if ts is None:
            continue
        cov_all, minlyr, near, has_clu = 0.0, None, [], False
        for t in ts:
            sc = region["score"].get(t)
            if sc is None:                        # 注意用 is None：0.0 分主题同样入区（--threshold 0）
                continue
            cov_all += sc
            lyr = region["layer"].get(t, 99)
            minlyr = lyr if minlyr is None else min(minlyr, lyr)
            if lyr > R2B_ANCHOR_HOPS:
                continue
            near.append(t)
            if seed_clu is not None and nodes[t].get("cluster") == seed_clu:
                has_clu = True
        if minlyr is None:
            continue
        if not near:                              # 兜底档：仅二跳以外主题 → 仍按旧覆盖度参与补齐
            fallback.append((minlyr, cov_all, line, None))
            continue
        tier = 0 if has_clu else 1
        rel = sum(region["score"][t] * (R2B_CLUSTER_W if (seed_clu is not None
                                                          and nodes[t].get("cluster") == seed_clu) else 1.0)
                  for t in near)
        anchor = max(near, key=lambda t: (region["score"][t], -t))
        rows.append((tier, minlyr, -rel, line, anchor, rel))
    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    fallback.sort(key=lambda r: (-r[1], r[2]))
    pool = rows[: max(k * 4, 20)]
    if len(pool) < k:                             # 锚定候选不足 → 旧口径补齐（保持可用性）
        pool = pool + [(-1, f[0], -f[1], f[2], None, f[1]) for f in fallback[: max(k * 4, 20)]]
    titles = load_titles(D, [r[3] for r in pool])
    picked, seen_title, dups = [], set(), []
    for row in pool:                              # 软去重：同名/同套多卷先各留一册
        ti = series_key(titles.get(row[3], {}).get("title"))
        if ti and ti in seen_title:
            dups.append(row)
            continue
        seen_title.add(ti)
        picked.append(row)
        if len(picked) >= k:
            break
    for row in dups + [r for r in rows + [(-1, f[0], -f[1], f[2], None, f[1]) for f in fallback]
                       if r not in picked]:   # 不足 k → 同卷/余量补齐
        if len(picked) >= k:
            break
        if all(row[3] != p[3] for p in picked):
            picked.append(row)
    ev = []
    for tier, _lyr, _neg, line, nid, rel in picked[:k]:
        info = titles.get(line, {})
        if nid is None:                           # 兜底卡：取区域内最高分主题作 via
            ts = [t for t in (fwd[line] if fwd is not None and line < len(fwd) else ())
                  if t in region["score"]]
            nid = max(ts, key=lambda t: (region["score"][t], -t)) if ts else None
            if nid is None:
                continue
        ev.append({"mms": card_mms[line] if line < len(card_mms) else "",
                   "title": info.get("title", ""), "cls": info.get("cls", ""),
                   "cls2": info.get("cls2", ""), "year": info.get("year", ""),
                   "via_topic": nodes[nid]["term"], "via_id": nid,
                   "min_hop": region["layer"].get(nid, 0), "tier": tier,
                   "region_cover_score": round(rel, 4)})
    # 书标编号 / 位置接入（2026-09-20）：mms → (loc, call) 概览（labels.db）
    if ev:
        _labs = BL.query_labels(D, [e["mms"] for e in ev])
        for e in ev:
            _loc, _call = BL.brief(_labs.get(e["mms"], []))
            e["call"] = _call
            e["loc"] = _loc
    return ev


def book_count(region, topic_cards, cap_nodes=3000):
    """region 覆盖的去重书数（>cap_nodes 时只统计分数最高的 cap_nodes 个主题，返回 capped=True）。"""
    order = sorted(region["score"], key=lambda i: (-region["score"][i], i))
    capped = len(order) > cap_nodes
    s = set()
    for nid in order[:cap_nodes]:
        s.update(topic_cards.get(nid, ()))
    return len(s), capped


def prepare(args):
    D = resolve_data(args)
    nodes, by_term = load_nodes(D)
    if args.topic_id is not None:
        tid = args.topic_id
        if tid < 0 or tid >= len(nodes):
            sys.exit(f"[topic_graph] topic_id 越界: {tid}（有效范围 0..{len(nodes)-1}）")
    else:
        t = normalize_term(args.term)
        if t not in by_term:
            cand = [n for n in nodes if t in n["term"]]
            cand.sort(key=lambda n: (-n["freq"], n["id"]))
            hint = "、".join(f"{n['id']}:{n['term']}" for n in cand[:5]) or "（无）"
            sys.exit(f"[topic_graph] 未找到主题 '{args.term}'（归一 '{t}'）；相近候选: {hint}")
        tid = by_term[t]
    indptr, indices, weights = load_edges(D)
    return D, nodes, tid, (indptr, indices, weights)


def make_region(args, D, nodes, tid, csr, want_evidence=True):
    indptr, indices, weights = csr
    t0 = time.time()
    reg = diffuse(tid, args.hops, indptr, indices, weights,
                  args.decay, args.threshold, args.budget)
    layers = build_layers(reg, nodes, args.hops, args.top)
    mms_list, topic_cards, fwd = load_card_topics(D, need_forward=True)
    ev = (evidence_of(D, reg, nodes, topic_cards, mms_list, args.evidence, fwd=fwd, seed=tid)
          if want_evidence else [])
    nb, capped = book_count(reg, topic_cards)
    ms = (time.time() - t0) * 1000
    region = {
        "seed": {"id": tid, "term": nodes[tid]["term"], "type": nodes[tid]["type"],
                 "freq": nodes[tid]["freq"], "cluster": nodes[tid]["cluster"], "cls": nodes[tid]["cls"]},
        "hops": args.hops, "decay": args.decay, "threshold": args.threshold,
        "layers": layers, "evidence": ev,
        "stats": {"visited": reg["visited"], "edges_scanned": reg["edges_scanned"],
                  "books": nb, "books_capped": capped, "saturated_budget": reg["saturated"],
                  "elapsed_ms": round(ms, 2),
                  "weight_min": round(min(reg["score"].values()), 6) if reg["score"] else 0.0,
                  "weight_median": round(float(np.median(list(reg["score"].values()))), 6) if reg["score"] else 0.0,
                  "weight_max": round(max(reg["score"].values()), 6) if reg["score"] else 0.0},
    }
    return region, topic_cards, reg


# ---------------------------------------------------------------------------
# around
# ---------------------------------------------------------------------------
def cmd_around(args):
    D, nodes, tid, csr = prepare(args)
    region, _tc, _raw = make_region(args, D, nodes, tid, csr)
    if args.json:
        print(json.dumps(region, ensure_ascii=False, indent=1))
        return 0
    st = region["stats"]
    print(f"=== around {tid} 「{region['seed']['term']}」 ({region['seed']['type']}, freq={region['seed']['freq']}, "
          f"cluster={region['seed']['cluster']}, cls={region['seed']['cls']}) ===")
    print(f"规则: w_hop = w_parent × edge_w × {region['decay']} | 阈值 {region['threshold']} | hops ≤{region['hops']}")
    print(f"区域: {st['visited']} 主题 / 书证据 {st['books']}{'(上限截断)' if st['books_capped'] else ''} 本 / "
          f"扫描边 {st['edges_scanned']} / 权重 {st['weight_min']:.3f}~{st['weight_max']:.3f}(中位 {st['weight_median']:.3f}) / "
          f"{st['elapsed_ms']:.1f}ms{' | ⚠预算饱和' if st['saturated_budget'] else ''}")
    for L in region["layers"]:
        print(f"\n[hop {L['hop']}] {L['n']} 个主题（显示 top {len(L['nodes'])}）")
        for nd in L["nodes"]:
            p = " → ".join(nd["path"][:-1][-3:]) if len(nd["path"]) > 1 else ""
            print(f"  {nd['id']:>5} {nd['term'][:22]:<23} {nd['type']:<4} score={nd['score']:.4f}"
                  + (f"   via {p}" if p else ""))
    if region["evidence"]:
        print(f"\n[书证据] 抽 {len(region['evidence'])} 张卡（card_topics 反查）")
        for e in region["evidence"]:
            seg = f"  {e['mms']}  {e['title'][:44]:<46} cls={e['cls']}/{e['cls2']}"
            if e.get("call"):
                seg += f"  [{e['call']}]"
            if e.get("loc"):
                seg += f"  @ {e['loc']}"
            seg += f"  via 「{e['via_topic']}」"
            print(seg)
    return 0


# ---------------------------------------------------------------------------
# graph（JSON 子图）
# ---------------------------------------------------------------------------
def cmd_graph(args):
    D, nodes, tid, csr = prepare(args)
    indptr, indices, weights = csr
    region, _tc, raw = make_region(args, D, nodes, tid, csr, want_evidence=False)
    ids = set(raw["score"])
    out_nodes = [{"id": i, "term": nodes[i]["term"], "type": nodes[i]["type"],
                  "cluster": nodes[i]["cluster"], "cls": nodes[i]["cls"],
                  "w": round(raw["score"][i], 6)} for i in
                 sorted(ids, key=lambda i: (-raw["score"][i], i))]
    edges = []
    for u in sorted(ids):
        a, b = int(indptr[u]), int(indptr[u + 1])
        for p in range(a, b):
            v = int(indices[p])
            if v in ids:
                edges.append({"src": u, "dst": v, "w": round(float(weights[p]), 6)})
    payload = {"seed": region["seed"], "hops": args.hops, "threshold": args.threshold,
               "decay": args.decay, "nodes": out_nodes, "edges": edges, "stats": region["stats"]}
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if args.json_out:
        with open(os.path.abspath(os.path.expanduser(args.json_out)), "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"[graph] seed={tid}「{nodes[tid]['term']}」 节点 {len(out_nodes)} / 边 {len(edges)} / "
              f"{region['stats']['elapsed_ms']:.1f}ms → {args.json_out}")
    else:
        print(text)
    return 0


# ---------------------------------------------------------------------------
# summarize：LLM 接口存根（签名固定；待与作者讨论）
# ---------------------------------------------------------------------------
def summarize_topic_region(region, mode=None, strict=False):
    """【接口存根 · 签名固定 · 待与作者讨论】

    def summarize_topic_region(region: dict) -> str
      region = make_region() 产出的扩散域（seed/hops/decay/threshold/layers/evidence/stats）
      返回 Markdown 文本；**不返回 JSON**（结构化数据走 `graph --json` / `around --json` 通道）
    环境变量 TOPIC_LLM: off（默认，纯结构化占位）| mock（确定性模板文）| <endpoint>（唯一允许触网的取值）
    硬约束：默认不触网；off/mock 确定性（同 region 同输出）；不得引入 region 之外的事实。
    """
    mode = (mode or os.environ.get("TOPIC_LLM") or TOPIC_LLM_DEFAULT).strip()
    if mode not in ("off", "mock"):
        # endpoint 模式尚未实现：按接口草案「失败回退」回退占位文，退出码不变
        sys.stderr.write(f"[topic_graph] WARN: TOPIC_LLM='{mode}' 尚未实现（本期只交付存根），"
                         f"已回退占位文；--strict-llm 可暴露该状态\n")
        if strict:
            return None
        mode = "mock"
    seed, st = region["seed"], region["stats"]
    lay = region["layers"]
    top_terms = [n["term"] for n in (lay[0]["nodes"][:5] if lay else [])]
    if len(lay) > 1:
        top_terms += [n["term"] for n in lay[1]["nodes"][:3]]
    head = "【off：纯结构化占位输出（未调用任何模型）】" if mode == "off" else "【mock：确定性模板文（未调用任何模型）】"
    lines = [
        f"### 主题区域摘要（存根）· {seed['term']}（id={seed['id']}, {seed['type']}, freq={seed['freq']}）",
        "",
        head,
        "",
        f"- **扩散规则**：w_hop = w_parent × edge_w × {region['decay']}，阈值 {region['threshold']}，hops={region['hops']}",
        f"- **区域规模**：{st['visited']} 个主题 / 证据书 {st['books']} 本"
        + ("（书数按 top-3000 主题截断统计）" if st["books_capped"] else ""),
        f"- **权重分布**：min {st['weight_min']:.4f} / 中位 {st['weight_median']:.4f} / max {st['weight_max']:.4f}",
        f"- **层级**：" + "；".join(f"hop{l['hop']} {l['n']} 个" for l in lay) if lay else "- **层级**：（无扩散）",
        f"- **代表主题**：" + ("、".join(top_terms) if top_terms else "（无）"),
    ]
    if region["evidence"]:
        lines.append(f"- **证据书样例**：" + "；".join(
            f"《{e['title']}》({e['mms']})" for e in region["evidence"][:3]))
    lines += ["", "> 本段由 `summarize_topic_region(region) -> str` 存根生成：**签名固定、待与作者讨论**；",
              "> 默认 `TOPIC_LLM=off` 不触网，结构化数据请用 `graph --json` / `around --json`。"]
    return "\n".join(lines)


def cmd_summarize(args):
    D, nodes, tid, csr = prepare(args)
    region, _tc, _raw = make_region(args, D, nodes, tid, csr)
    text = summarize_topic_region(region, mode=args.llm, strict=args.strict_llm)
    if text is None:
        sys.stderr.write("[topic_graph] --strict-llm：TOPIC_LLM 非 off/mock 且未实现，exit 3\n")
        return 3
    if args.json:
        print(json.dumps({"seed": region["seed"], "mode": (args.llm or os.environ.get("TOPIC_LLM")
                         or TOPIC_LLM_DEFAULT), "text": text, "region_stats": region["stats"]},
                         ensure_ascii=False, indent=1))
    else:
        print(text)
    return 0


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="图书馆主题图查询编排（GraphRAG-lite · P4）")
    ap.add_argument("--data", default=None, help="数据目录（默认 $LIB_CATALOG_DATA 或 ~/go/lib-catalog-data）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="主题检索（词面匹配 × 词频权重）")
    s.add_argument("query")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--expand", choices=["auto", "no", "yes"], default="auto",
                   help="近词扩展（非词表查询退化路径 ②）：auto=字面零命中或无精确/前缀命中时启用（默认）")
    s.add_argument("--expand-cards", type=int, default=50,
                   help="扩展时聚合的相关书目数（R1.1：默认 200→50，聚合应发生在最相关的卡上）")
    s.add_argument("--expand-rank", choices=["agg", "spec"], default="agg",
                   help="扩展排序键：agg=证据强度（默认）；spec=专指度 agg/√freq（低频词更靠前，实测有同形词回归风险）")
    s.add_argument("--expand-top", type=int, default=10, help="扩展返回的主题数")
    s.add_argument("--json", action="store_true")

    for name, helptext in (("around", "加权扩散邻域 + 书证据"), ("graph", "JSON 子图"),
                           ("summarize", "LLM 接口存根摘要")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("topic_id", nargs="?", type=int, default=None, help="主题 id（与 --term 二选一）")
        p.add_argument("--term", default=None, help="按词查（默认用 topic_id）")
        p.add_argument("--hops", type=int, default=2)
        p.add_argument("--top", type=int, default=12, help="每层显示/保留的主题数")
        p.add_argument("--evidence", type=int, default=8, help="书证据抽样条数")
        p.add_argument("--threshold", type=float, default=THRESHOLD_DEFAULT)
        p.add_argument("--decay", type=float, default=DECAY_DEFAULT)
        p.add_argument("--budget", type=int, default=BUDGET_DEFAULT)
        p.add_argument("--json", action="store_true")
        if name == "graph":
            p.add_argument("--json-out", default=None)
        if name == "summarize":
            p.add_argument("--llm", default=None, help="off|mock|<endpoint>（默认取 $TOPIC_LLM，未设为 off）")
            p.add_argument("--strict-llm", action="store_true")

    args = ap.parse_args()
    if args.cmd != "search":
        if args.hops < 1 or args.hops > HOPS_MAX:
            sys.exit(f"[topic_graph] --hops 需在 1..{HOPS_MAX}（§3.4 上限 12）")
        if args.topic_id is None and not args.term:
            sys.exit("[topic_graph] 需要 topic_id 或 --term")
        if not (0.0 < args.decay <= 1.0):                      # R1 护栏：衰减系数必须 ∈ (0,1]
            sys.exit(f"[topic_graph] --decay 需在 (0,1] 区间（实际 {args.decay}）")
        if args.budget < 1:                                    # R1 护栏：预算至少容纳源点
            sys.exit(f"[topic_graph] --budget 需 ≥1（visited 含源点；实际 {args.budget}）")
        if not (0.0 <= args.threshold <= 1.0):
            sys.exit(f"[topic_graph] --threshold 需在 [0,1]（实际 {args.threshold}）")
    if args.cmd == "search":
        return cmd_search(args)
    if args.cmd == "around":
        return cmd_around(args)
    if args.cmd == "graph":
        return cmd_graph(args)
    if args.cmd == "summarize":
        return cmd_summarize(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
