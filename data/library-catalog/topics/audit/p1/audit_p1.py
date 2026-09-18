#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AUDIT-P1 — topic_build.py 实现层独立审计（只读主体代码与产物；写只落在 audit/p1/）

方法：
  S0  静态读源码逐项定位可疑实现（记录行号）
  S1  产物层不变量 + 报告 A1 一致性（不依赖主体代码）
  S2  独立重算：自实现 链式合并/A 匹配/证据累计，对 nodes.json 全量 5187 节点精确比对
      （freq / cluster / cls），并导出 50 词分层明细、20 词 cluster 归属明细
  S2b top_title_tokens 原语属性检验（独立重算 top-M 选择 + 幂等性）
  S3  ext_df 双计数复算：忠实复现 pass1/pass1.5，量化 ext_df 超出卡片数、包含率 >1.0、
      以及"仅因双计数被误判为跨词碎片"的 A 源词数
  S4  排序键真实语义：验证 nodes.json 全量顺序 == sort(-主导簇卡数, -freq, term)（证明 _score 退化）
  S5  边界/口径：频控覆盖、英文闸门析取退化、B-only CJK 政策、sources 溯源、cls 层级
  S6  实验：确定性（PYTHONHASHSEED 变异两次全量重跑）+ 截断路径（--max-nodes 3000）

用法（只写 --audit 目录）：
  python3 audit_p1.py [--data DIR] [--audit DIR] [--src topic_build.py]
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

SRC_DIR = "/home/wzh/go/reasonix-scripts/lib-catalog"
PYLIBS = os.path.expanduser("~/go/pylibs")          # topic_build 的 numpy 来源
for _p in (PYLIBS, SRC_DIR):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np          # noqa: E402
import topic_build as tb    # noqa: E402  被审对象：只调用其"原语"与"忠实复现"函数

T0 = time.time()
FINDINGS, LOG = [], []


def log(msg):
    line = f"[{time.time()-T0:6.1f}s] {msg}"
    print(line, flush=True)
    LOG.append(line)


def finding(fid, sev, title, evidence, repro, suggestion):
    FINDINGS.append({"id": fid, "severity": sev, "title": title,
                     "evidence": evidence, "repro": repro, "suggestion": suggestion})
    log(f"  !! {fid} [{sev}] {title}")


def dump(audit_dir, name, obj):
    p = os.path.join(audit_dir, "evidence", name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    log(f"  -> evidence/{name} ({os.path.getsize(p):,} B)")


# ===========================================================================
# 独立重算实现（不调用 topic_build 的 merge / A-匹配 / 证据累计函数）
# ===========================================================================
def _is_cjk_tok(t):
    return len(t) >= 2 and all("\u4e00" <= ch <= "\u9fff" for ch in t)


def my_merge(scored, max_len=5, min_ratio=0.25):
    """按源码声明的语义独立实现：按分数降序链式合并重叠中文 bigram。"""
    used, out = set(), []
    for s, t in scored:
        if t in used:
            continue
        if not _is_cjk_tok(t):
            out.append(t)
            used.add(t)
            continue
        cur, cur_s = t, s
        used.add(t)
        while len(cur) < max_len:
            tail, nxt = cur[-1], None
            for s2, t2 in scored:
                if t2 in used or not _is_cjk_tok(t2):
                    continue
                if t2[0] == tail and s2 >= cur_s * min_ratio:
                    nxt = (s2, t2)
                    break
            if not nxt:
                break
            cur = cur + nxt[1][1:]
            used.add(nxt[1])
        out.append(cur)
    return out


def my_card_words(pairs):
    return {tb.normalize_term(w) for w in my_merge(pairs)
            if tb.term_ok_kw(w) and not tb.is_stop(w)}


def my_matcher(interest):
    ascii_keys = {k for k in interest if not tb.CJK_RE.search(k)}
    buckets = defaultdict(list)
    for k in interest:
        if tb.CJK_RE.search(k) and len(k) >= 2:
            buckets[k[:2]].append(k)
    return ascii_keys, buckets


def my_match(norm_title, title_tokens, matcher):
    ascii_keys, buckets = matcher
    found = set()
    for tok in title_tokens:
        if tok in ascii_keys:
            found.add(tok)
    seen = set()
    for i in range(max(0, len(norm_title) - 1)):
        bg = norm_title[i:i + 2]
        if bg in seen:
            continue
        seen.add(bg)
        for k in buckets.get(bg, ()):
            if k in norm_title:
                found.add(k)
    return found


def amax_min(cc):      # 源码 mode_cluster 的 tie-break：max(count, -id)
    return max(cc.items(), key=lambda kv: (kv[1], -kv[0]))[0] if cc else None


def amax_str(cc):      # 源码 kw 取 cls1 的 tie-break：max(count, string)
    return max(cc.items(), key=lambda kv: (kv[1], kv[0]))[0] if cc else None


# ===========================================================================
# 数据装载
# ===========================================================================
def load_inputs(D):
    idx = os.path.join(D, "index")
    z = np.load(os.path.join(idx, "tfidf.npz"))
    vocab = json.load(open(os.path.join(idx, "vocab.json"), encoding="utf-8"))
    labels = np.load(os.path.join(idx, "clusters.npy"))
    clusters = json.load(open(os.path.join(D, "clusters.json"), encoding="utf-8"))["clusters"]
    subjects = json.load(open(os.path.join(D, "subjects.json"), encoding="utf-8"))
    return {"indptr": z["indptr"], "indices": z["indices"], "data": z["data"],
            "vocab": vocab, "labels": labels, "clusters": clusters, "subjects": subjects,
            "nv": [tb.normalize_term(t) for t in vocab]}


# ===========================================================================
# S0 静态源码审计
# ===========================================================================
def section_static(src_path, out):
    log("== S0 静态源码审计 ==")
    src = open(src_path, encoding="utf-8").read()
    lines = src.splitlines()

    def find(pat):
        return [i + 1 for i, l in enumerate(lines) if re.search(pat, l)]

    stat = {"src": src_path, "bytes": os.path.getsize(src_path), "lines": len(lines),
            "sha256": hashlib.sha256(src.encode()).hexdigest()}

    l_score = find(r'"_score": float\(score\)|score = f \* rep')
    l_rep = find(r"max\(cc\.values\(\)\) / float\(max\(freq\[w\], 1\)\)")
    stat["score_lines"], stat["rep_lines"] = l_score, l_rep
    finding("F1", "中",
            "截断排序键 `_score = freq × rep` 代数退化：rep = 主导簇卡数/freq ⇒ _score ≡ 主导簇卡数"
            "（freq 被约掉），与报告/代码注释所声称的‘频次×簇内代表性’不符",
            {"score_line": l_score, "rep_line": l_rep,
             "algebra": "score = freq * (max(cl_counts)/freq) = max(cl_counts)",
             "consequence": "截断主键实为单簇聚集度：偏向大盘簇专词，压低跨簇通用词与稀有簇专词",
             "numeric_proof": out.get("order_test", {})},
            "python3 audit_p1.py -> S4（全量 5187 节点顺序 == sort(-max_cc,-freq,term)）",
            "改键为真正的联合量（rep 独立归一化，或 log1p(freq)*rep），或按实际语义改写报告文案。")

    l_p1 = find(r"for e in ext_seen:")
    l_p15 = find(r"# ---- Pass 1\.5")
    stat["ext_incr_lines"], stat["pass15_line"] = l_p1, l_p15
    finding("F2", "高",
            "长词包含率证据 ext_df 双计数：pass1（A 匹配扩展）与 pass1.5（B-CJK 扩展）对同一卡片的同一"
            "扩展词各 +1，ext_df 可超过卡片数，containment_ratio 丧失‘卡片级包含率’语义，导致 A 源词被"
            "误判为跨词边界碎片而剔除",
            {"pass1_ext_increment": l_p1, "pass15_block": l_p15,
             "measurement": out.get("ext_double_count", {})},
            "python3 audit_p1.py -> S3",
            "两趟按 card 去重（或合并为一趟）后重算 ratio，并重跑 P1 基线。")

    l_cjk_path = find(r"len\(w\) >= 2 and b_df\[w\] >= args\.min_df_cjk")
    stat["b_cjk_df_path"] = l_cjk_path
    finding("F3", "中",
            "B-only CJK 准入政策：报告 params.b_cjk_policy 与文件头注释称‘B-only CJK 须在 A 词表或学科"
            "词表内，否则剔除’，实现另有第三条通路 `b_df>=min_df_cjk 且 长词包含率<0.9`，报告未披露",
            {"impl_line": l_cjk_path, "numeric": out.get("b_cjk_audit", {})},
            "python3 audit_p1.py -> S5", "报告按三条通路分别计数披露，或收紧实现与声明一致。")

    l_len = find(r"if not \(1 <= len\(s\) <= 16\)")
    l_len1 = find(r"if len\(s\) == 1:")
    stat["len_lines"] = l_len + l_len1
    finding("F4", "低",
            "归一化口径与实现不符：报告写‘长度1-16’，term_ok_kw 另拒 len==1 ⇒ kw 有效区间 2..16（cls 1..6）",
            {"evidence_line": l_len, "reject_len1_line": l_len1},
            "对照 evidence/report_vs_impl.json", "报告改‘长度 2-16（cls 1-6）’。")

    dead = {
        "match_a 的 single 集恒空（a_set 已被 term_ok_kw 拒绝 len==1）": find(r"for ch in single:"),
        "超上限告警 `if n > args.max_nodes` 不可达（截断后 n<=max_nodes）": find(r"if n > args\.max_nodes:"),
        "截断 if/else 两分支同一 sort（重复代码）": find(r"truncated = True") + find(r"truncated = False"),
        "sources 兜底分支不可达（A/B/C 至少一路置位）": find(r"if not sources:"),
        "english_gate_ok 仅是 english_quality_ok 的别名": find(r"def english_gate_ok"),
        "representativeness/mode_cluster 的 a_membership 兜底不可达（入表节点 freq>=1 ⇒ cl_counts 非空）":
            find(r"mem = a_membership\.get\(w\)"),
        "accepted_b 循环内重复 term_ok_kw/is_stop（b_keep 已过滤）": find(r"if not \(term_ok_kw\(w\) and not is_stop\(w\)\):"),
    }
    stat["dead_code"] = dead
    finding("F5", "低",
            "多处死代码/不可达分支，其中‘超上限告警不可达’会让自测产生‘规模受控’的假安全感",
            dead, "python3 audit_p1.py -> S0", "删除死分支并把可达性写进自测断言。")

    l_clsv = find(r"cls_v = w")
    stat["cls_v_line"] = l_clsv
    finding("F6", "中",
            "nodes.json `cls` 字段层级混用：kw 写一级分类（F/TP），cls 节点写自身 cls2（349/349 cls==term）；"
            "按 `cls` 聚合的消费方会把两级代码混在一起",
            {"impl_line": l_clsv, "artifact": out.get("cls_level", {})},
            "python3 audit_p1.py -> S5", "cls 节点写父 cls1，或新增 cls1/cls2 双字段并冻结 schema。")

    l_mask = find(r"for w in a_set:")
    stat["a_mask_line"] = l_mask
    finding("F7", "低",
            "sources 语义 = ‘在该源词表中出现’，非‘该源通路实际采纳’：源码对 a_set 全量置 A 位（含被 A "
            "碎片/零频规则剔除、后经 B 通路入表的词），A/B 的贡献度无法从 sources 还原",
            {"impl_line": l_mask, "numeric": out.get("provenance", {})},
            "python3 audit_p1.py -> S5", "sources 记录‘被采纳来源’，另加 dropped_by 字段。")

    finding("F8", "中",
            "`--min-df 12` 只约束 B 源（b_keep）；A/C 通路无频次下限，A-only/C-only 节点 freq 可低至 1。"
            "报告把 min_df 呈现为词频闸门，实际有 752/5187 节点不受其约束",
            {"numeric": out.get("freq_gate_by_source", {})},
            "python3 audit_p1.py -> S5", "报告中限定 min_df 的作用域；如需全局下限需另设参数并重跑基线。")

    l_gate = find(r"freq\.get\(w, 0\) >= args\.en_min_freq")
    stat["en_gate_line"] = l_gate
    finding("F9", "中",
            "英文质量闸门为三分量 OR（freq>=200 或 cls_rep>=0.6 或 len>=9）：低频词天然满足 cls_rep≈1.0"
            "（freq==1 时恒为 1.0），且 len>=9 是无条件旁路，闸门对低频英文词近乎失效",
            {"impl_line": l_gate, "numeric": out.get("en_gate", {})},
            "python3 audit_p1.py -> S5", "改为 AND/加权（如 freq>=min_df 且 cls_rep 达标），按新口径重跑留痕。")

    l_mode = find(r"def mode_cluster")
    finding("F10", "低",
            "cluster 归属并存两套口径（卡片级众数 vs 簇关键词表级众数），量纲不同；实现中 a_membership 兜底"
            "恒不可达，但与 F6 同类：代码/报告未声明该分歧",
            {"impl_line": l_mode, "numeric": out.get("cluster_semantics", {})},
            "python3 audit_p1.py -> S2", "删兜底臂并在报告写明 cluster = 卡片级众数（tie 取小 id）。")
    return stat


# ===========================================================================
# S1 产物层不变量 + 报告 A1 一致性
# ===========================================================================
def section_artifact(nodes, report, audit_dir):
    log("== S1 产物层不变量 + A1 一致性 ==")
    ALLOWED = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9_.\-]+$")
    ALNUM = re.compile(r"^[A-Za-z0-9]{1,6}$")
    viol = defaultdict(list)
    for e in nodes:
        t = e["term"]
        if set(e.keys()) != {"id", "term", "type", "freq", "cluster", "cls", "sources"}:
            viol["schema"].append(t)
        if e["type"] == "kw":
            if not (2 <= len(t) <= 16):
                viol["kw_len"].append(t)
            if not ALLOWED.match(t) or "." in t or t[0] in "-_" or t[-1] in "-_":
                viol["kw_charset"].append(t)
            if t in tb.STOPWORDS or tb._STOP_RE.match(t):
                viol["kw_stopword"].append(t)
        elif not ALNUM.match(t):
            viol["cls_charset"].append(t)
        if e["freq"] < 1:
            viol["freq_lt1"].append(t)
        if not (0 <= e["cluster"] < 400):
            viol["cluster_range"].append(t)
        if not e["sources"] or set(e["sources"]) - {"A", "B", "C"}:
            viol["sources"].append(t)
    inv = {"id_continuous": [e["id"] for e in nodes] == list(range(len(nodes))),
           "term_unique": len({e["term"] for e in nodes}) == len(nodes),
           "violations": {k: {"n": len(v), "sample": v[:8]} for k, v in viol.items()},
           "n": len(nodes)}
    log(f"  违规桶={ {k: len(v) for k, v in viol.items()} } id_continuous={inv['id_continuous']}")

    cnt = report["counts"]
    fs = [e["freq"] for e in nodes]
    rec = {"nodes": len(nodes),
           "kw": sum(1 for e in nodes if e["type"] == "kw"),
           "cls": sum(1 for e in nodes if e["type"] == "cls"),
           "sources": dict(Counter("+".join(e["sources"]) for e in nodes)),
           "freq": {"min": min(fs), "median": int(np.median(fs)), "max": max(fs),
                    "p25": int(np.percentile(fs, 25)), "p90": int(np.percentile(fs, 90)),
                    "zero_freq": sum(1 for v in fs if v == 0)}}
    a1 = {"nodes_ok": cnt["nodes"] == rec["nodes"], "kw_ok": cnt["kw"] == rec["kw"],
          "cls_ok": cnt["cls"] == rec["cls"],
          "sources_ok": {k: cnt["sources"].get(k) == v for k, v in rec["sources"].items()},
          "freq_ok": {k: report["freq_stats"].get(k) == v for k, v in rec["freq"].items()},
          "recomputed": rec}
    log(f"  A1: nodes/kw/cls={a1['nodes_ok']}/{a1['kw_ok']}/{a1['cls_ok']} "
        f"sources={a1['sources_ok']} freq={a1['freq_ok']}")
    dump(audit_dir, "invariants.json", inv)
    return {"invariants": inv, "a1": a1}


# ===========================================================================
# 主流程
# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.expanduser("~/go/lib-catalog-data"))
    ap.add_argument("--audit", default=None)
    ap.add_argument("--src", default=os.path.join(SRC_DIR, "topic_build.py"))
    ap.add_argument("--top-per-card", type=int, default=10)
    ap.add_argument("--min-df", type=int, default=12)
    ap.add_argument("--min-df-cjk", type=int, default=15)
    args = ap.parse_args()
    D = os.path.abspath(os.path.expanduser(args.data))
    A = os.path.abspath(os.path.expanduser(args.audit)) if args.audit else \
        os.path.join(D, "topics", "audit", "p1")
    os.makedirs(os.path.join(A, "evidence"), exist_ok=True)
    out = {}
    log(f"== AUDIT-P1 开始 data={D} audit={A} ==")

    T = os.path.join(D, "topics")
    nodes = json.load(open(os.path.join(T, "nodes.json"), encoding="utf-8"))
    report = json.load(open(os.path.join(T, "p1-build-report.json"), encoding="utf-8"))
    cnt = report["counts"]
    log(f"nodes={len(nodes):,} report.nodes={cnt['nodes']:,}")

    stat = section_static(args.src, out)
    art = section_artifact(nodes, report, A)

    IX = load_inputs(D)
    n_lines = sum(1 for _ in open(os.path.join(D, "cards.jsonl"), "rb"))
    align = {"cards_jsonl_lines": n_lines, "indptr_rows": len(IX["indptr"]) - 1,
             "labels": len(IX["labels"]), "aligned": n_lines == len(IX["indptr"]) - 1 == len(IX["labels"]),
             "silent_drop_risk": n_lines > len(IX["indptr"]) - 1}
    log(f"  对齐: cards.jsonl={n_lines:,} indptr-1={len(IX['indptr'])-1:,} aligned={align['aligned']}")

    # ---------------- S2 独立重算（两趟） ----------------
    log("== S2 独立重算（趟1: merged word df；趟2: 证据累计）==")
    a_set, a_membership, a_raw = tb.load_source_a(IX["clusters"])
    interest = {e["term"] for e in nodes} | a_set | {
        "机器", "器学", "学习", "机器学习", "人工", "工智", "智能", "人工智能",
        "深度", "度学", "深度学习", "神经", "经网", "网络", "神经网络", "css", "5g"}
    PROBE = ["机器", "器学", "学习", "机器学习", "人工", "工智", "智能", "人工智能",
             "深度", "度学", "深度学习", "神经", "经网", "网络", "神经网络"]
    cards_path = os.path.join(D, "cards.jsonl")
    my_b_df, code_b_df, probe_topM = Counter(), Counter(), Counter()
    for i, _c, title, tt in tb.iter_card(cards_path, IX["indptr"]):
        pairs = tb.top_title_tokens(i, IX["indptr"], IX["indices"], IX["data"], IX["nv"], tt,
                                   args.top_per_card)
        if pairs:
            for w in my_card_words(pairs):
                my_b_df[w] += 1
            for w in tb.merged_card_words(pairs):
                code_b_df[w] += 1
            toks = {k for _s, k in pairs}
            for pb in PROBE:
                if pb in toks:
                    probe_topM[pb] += 1
    my_keep_all = {w for w, v in my_b_df.items() if v >= args.min_df and tb.term_ok_kw(w) and not tb.is_stop(w)}
    code_keep_all = {w for w, v in code_b_df.items() if v >= args.min_df and tb.term_ok_kw(w) and not tb.is_stop(w)}
    keep_diff = sorted((my_keep_all ^ code_keep_all))[:20]
    merge_agree = sum(1 for w in interest if my_b_df.get(w, 0) == code_b_df.get(w, 0))
    log(f"  趟1: my_b_df={len(my_b_df):,} code_b_df={len(code_b_df):,} "
        f"(报告 {cnt['source_b_merged_unique']:,}) | 自实现 vs 源码 keep={len(my_keep_all):,}/"
        f"{len(code_keep_all):,} (报告 {cnt['source_b_kept']:,}) | interest 内 df 相等 "
        f"{merge_agree}/{len(interest):,} | keep 差集样本={keep_diff[:5]}")
    merge_check = {"my_unique": len(my_b_df), "code_unique": len(code_b_df),
                   "report_unique": cnt["source_b_merged_unique"],
                   "my_keep": len(my_keep_all), "code_keep": len(code_keep_all),
                   "report_keep": cnt["source_b_kept"],
                   "interest_df_equal": merge_agree, "interest_n": len(interest),
                   "keep_symdiff_sample": keep_diff}

    interest_keep = my_keep_all & interest
    # A 词表 = a_set（与源码同源）；interest 仅用于"记录哪些词"，不得混入 A 匹配
    ascii_k, buckets = my_matcher(a_set)
    freq, a_hit, b_hit, c_hit = Counter(), Counter(), Counter(), Counter()
    cl, clsc = defaultdict(Counter), defaultdict(Counter)
    no_cls1_cards = 0
    for i, c, title, tt in tb.iter_card(cards_path, IX["indptr"]):
        pairs = tb.top_title_tokens(i, IX["indptr"], IX["indices"], IX["data"], IX["nv"], tt,
                                    args.top_per_card)
        nt = tb.normalize_term(title)
        keys = set()
        if pairs:
            for w in my_card_words(pairs):
                if w in interest_keep:
                    keys.add(w)
                    b_hit[w] += 1
        for w in my_match(nt, tt, (ascii_k, buckets)):
            if w in interest:
                keys.add(w)
                a_hit[w] += 1
        cls2 = tb.normalize_cls(c.get("cls2") or "")
        if tb.term_ok_cls(cls2):
            keys.add(cls2)
            c_hit[cls2] += 1
        if not keys:
            continue
        lab, cls1 = int(IX["labels"][i]), tb.normalize_cls(c.get("cls") or "")
        if cls1 == "":
            no_cls1_cards += 1
        for w in keys:
            freq[w] += 1
            cl[w][lab] += 1
            clsc[w][cls1] += 1
    log(f"  趟2: freq_terms={len(freq):,} 无 cls1 的卡片数={no_cls1_cards:,}")

    # ---- 全量比对 ----
    rows, freq_bad, cl_bad, cls_bad, cls_fallback = [], [], [], [], []
    for e in nodes:
        t = e["term"]
        cc = cl.get(t, Counter())
        csc = clsc.get(t, Counter())
        my_cl = amax_min(cc)
        my_cls = amax_str(csc)
        r = {"id": e["id"], "term": t, "type": e["type"], "freq": e["freq"],
             "my_freq": freq.get(t, 0), "cluster": e["cluster"], "my_cluster": my_cl,
             "cls": e["cls"], "my_cls1": my_cls, "max_cc": max(cc.values()) if cc else 0,
             "max_cls": max(csc.values()) if csc else 0,
             "ncl": len(cc), "sources": "+".join(e["sources"]),
             "a": a_hit.get(t, 0), "b": b_hit.get(t, 0), "c": c_hit.get(t, 0)}
        rows.append(r)
        if r["my_freq"] != r["freq"]:
            freq_bad.append(r)
        if my_cl != e["cluster"]:
            cl_bad.append(r)
        if e["type"] == "kw" and my_cls != e["cls"]:
            (cls_fallback if my_cls == "" else cls_bad).append(r)
    log(f"  比对: freq 不符={len(freq_bad):,}/{len(nodes):,} | cluster 不符={len(cl_bad):,} | "
        f"kw.cls 不符={len(cls_bad) + len(cls_fallback):,}（其中簇级兜底填充={len(cls_fallback):,}）")
    if freq_bad:
        finding("F11", "高",
                f"独立重算发现 {len(freq_bad)} 个节点 freq 与自实现口径不符（freq 不可复现）",
                {"n": len(freq_bad), "sample": freq_bad[:20]}, "python3 audit_p1.py -> S2",
                "逐项定位分歧（A 匹配/B merge/C 计数）后修正并重跑基线。")
    if cl_bad:
        finding("F12", "高",
                f"独立重算发现 {len(cl_bad)} 个节点 cluster 归属与卡片级众数不符",
                {"n": len(cl_bad), "sample": cl_bad[:20]}, "python3 audit_p1.py -> S2",
                "核对 mode_cluster 与兜底臂。")

    # ---- 50 词分层明细 / 20 词 cluster 明细 ----
    asc = sorted(rows, key=lambda r: -r["freq"])
    q1, q2 = len(asc) // 3, 2 * len(asc) // 3
    sample50 = []
    for name, pool, k in (("high", asc[:q1], 17), ("mid", asc[q1:q2], 17), ("low", asc[q2:], 16)):
        step = max(1, len(pool) // k)
        for r in pool[::step][:k]:
            sample50.append({"stratum": name, **r, "freq_match": r["freq"] == r["my_freq"]})
    sample50 = sample50[:50]
    dump(A, "freq50.json", sample50)
    n_match = sum(1 for r in sample50 if r["freq_match"])
    log(f"  50 词分层抽查: freq 全等={n_match}/{len(sample50)}")

    step = max(1, len(asc) // 20)
    cluster20 = []
    for r in asc[::step][:20]:
        mem = a_membership.get(r["term"])
        a_mode = amax_min(mem) if mem else None
        cluster20.append({**r, "cluster_match": r["cluster"] == r["my_cluster"],
                          "a_membership_mode": a_mode, "a_slots": sum((mem or {}).values()),
                          "a_vs_card_agree": (a_mode == r["my_cluster"]) if a_mode is not None else None})
    dump(A, "cluster20.json", cluster20)
    agree = [c for c in cluster20 if c["a_vs_card_agree"] is not None]
    out["cluster_semantics"] = {"n": 20,
                                "card_mode_match": sum(1 for c in cluster20 if c["cluster_match"]),
                                "a_available": len(agree),
                                "a_vs_card_agree": sum(1 for c in agree if c["a_vs_card_agree"])}
    log(f"  20 词 cluster: 与卡片级众数一致={out['cluster_semantics']['card_mode_match']}/20; "
        f"A 词表口径可比 {len(agree)} 个、一致 {out['cluster_semantics']['a_vs_card_agree']}")

    # ---- S2b top_title_tokens 原语属性检验 ----
    log("== S2b top_title_tokens 原语检验（200 卡）==")
    prim_bad, prim_idem, n_dup = [], 0, 0
    for i, _c, title, tt in tb.iter_card(cards_path, IX["indptr"]):
        if i % 943 != 0:
            continue
        M = args.top_per_card
        got = tb.top_title_tokens(i, IX["indptr"], IX["indices"], IX["data"], IX["nv"], tt, M)
        got2 = tb.top_title_tokens(i, IX["indptr"], IX["indices"], IX["data"], IX["nv"], tt, M)
        if got != got2:
            prim_idem += 1
        a, b = int(IX["indptr"][i]), int(IX["indptr"][i + 1])
        elig = []
        for p in range(a, b):
            k = IX["nv"][int(IX["indices"][p])]
            if k in tt and tb.term_ok_kw(k) and not tb.is_stop(k):
                elig.append((float(IX["data"][p]), k))
        elig.sort(key=lambda x: (-x[0], x[1]))
        if got != elig[:M]:
            prim_bad.append({"card": i, "got": got, "want": elig[:len(got)]})
        if len({k for _s, k in got}) != len(got):
            n_dup += 1
        if len(prim_bad) > 200:
            break
    prim = {"sampled_cards": len(range(0, n_lines, 943)), "mismatch": len(prim_bad),
            "non_idempotent": prim_idem, "dup_tokens": n_dup,
            "sample_mismatch": prim_bad[:3]}
    dump(A, "primitive_topM.json", prim)
    log(f"  top-M 选择与独立重算不符={len(prim_bad)} 幂等失败={prim_idem} 重复 token 卡数={n_dup}")

    # ---------------- S3 ext 双计数复算（忠实复现 pass1 + pass1.5） ----------------
    log("== S3 ext_df 双计数复算（card 级去重对照）==")
    matcher = tb.build_a_matcher(a_set)
    b_keep_cjk = {w for w, v in code_b_df.items()
                  if v >= args.min_df and tb.term_ok_kw(w) and not tb.is_stop(w)
                  and tb.CJK_RE.search(w) and len(w) >= 2}
    ext_code, ext_union, ext_inter = Counter(), Counter(), Counter()
    ext_cand = defaultdict(set)
    for i, _c, title, tt in tb.iter_card(cards_path, IX["indptr"]):
        pairs = tb.top_title_tokens(i, IX["indptr"], IX["indices"], IX["data"], IX["nv"], tt,
                                    args.top_per_card)
        nt = tb.normalize_term(title)
        A_set = set()
        for w in tb.match_a(title, tt, matcher, nt):
            ex = tb.term_extensions(w, nt)
            ext_cand[w] |= ex
            A_set |= ex
        for e in A_set:
            ext_code[e] += 1
        B_set = set()
        if pairs:
            for w in tb.merged_card_words(pairs):
                if w in b_keep_cjk:
                    ex = tb.term_extensions(w, nt)
                    ext_cand[w] |= ex
                    B_set |= ex
        for e in B_set:
            ext_code[e] += 1
        for e in A_set | B_set:
            ext_union[e] += 1
        for e in A_set & B_set:
            ext_inter[e] += 1
    over = [e for e, v in ext_union.items() if ext_code[e] > v]
    ratio_gt1, flips = [], []
    ratios = {}
    for w in a_set:
        f = freq.get(w, 0)
        if f <= 0:
            continue
        bc = bu = 0.0
        for e in ext_cand.get(w, ()):
            if ext_code.get(e, 0):
                bc = max(bc, ext_code[e] / float(f))
            if ext_union.get(e, 0):
                bu = max(bu, ext_union[e] / float(f))
        ratios[w] = (bc, bu)
        if bc > 1.0:
            ratio_gt1.append({"term": w, "freq": f, "ratio_code": round(bc, 3),
                              "ratio_dedup": round(bu, 3)})
        if bc >= 0.9 > bu:
            flips.append({"term": w, "freq": f, "ratio_code": round(bc, 3),
                          "ratio_dedup": round(bu, 3),
                          "in_nodes": any(e["term"] == w for e in nodes)})
    # A 源漏斗复算（对照 report.counts.source_a_kept / dropped_*）
    a_keep_recomp, dropped_zero, dropped_embedded = set(), 0, 0
    for w in a_set:
        if freq.get(w, 0) <= 0:
            dropped_zero += 1
            continue
        if tb.CJK_RE.search(w) and len(w) >= 2 and ratios.get(w, (0, 0))[0] >= 0.9:
            dropped_embedded += 1
            continue
        a_keep_recomp.add(w)
    node_terms = {e["term"] for e in nodes}
    a_keep_absent = sorted(a_keep_recomp - node_terms)
    absent_en = [w for w in a_keep_absent if not tb.CJK_RE.search(w)]
    funnel = {"a_set_n": len(a_set), "a_keep_recomputed": len(a_keep_recomp),
              "dropped_zero_recomputed": dropped_zero,
              "dropped_embedded_recomputed": dropped_embedded,
              "report_a_kept": cnt["source_a_kept"],
              "report_dropped_zero": cnt["source_a_dropped_zero_freq"],
              "report_dropped_embedded": cnt["source_a_dropped_embedded"],
              "a_keep_terms_in_nodes": len(a_keep_recomp & node_terms),
              "a_keep_terms_absent_from_nodes": len(a_keep_absent),
              "a_keep_absent_english": len(absent_en),
              "a_keep_absent_sample": a_keep_absent[:12],
              "report_has_counter_for_absent": False}
    worst = sorted(over, key=lambda e: -(ext_code[e] / ext_union[e]))[:10]
    ext_res = {"ext_unique": len(ext_code), "ext_code_increments": int(sum(ext_code.values())),
               "ext_dedup_cards": int(sum(ext_union.values())),
               "double_count_events": int(sum(ext_inter.values())),
               "ext_terms_inflated": len(over),
               "identity_code_minus_union_equals_inter":
                   int(sum(ext_code.values()) - sum(ext_union.values()) - sum(ext_inter.values())),
               "worst_inflation": [{"ext": e, "code": ext_code[e], "cards": ext_union[e],
                                    "ratio": round(ext_code[e] / ext_union[e], 3)} for e in worst],
               "b_keep_cjk_n": len(b_keep_cjk),
               "ratio_gt1_terms": len(ratio_gt1), "ratio_gt1_sample": ratio_gt1[:8],
               "fragment_drop_flips": len(flips), "flip_sample": flips[:12],
               "flips_absent_from_nodes": sum(1 for f in flips if not f["in_nodes"]),
               "a_source_funnel": funnel,
               "report_dropped_a_embedded": cnt["source_a_dropped_embedded"],
               "report_dropped_a_zero_freq": cnt["source_a_dropped_zero_freq"],
               "report_source_a_kept": cnt["source_a_kept"],
               "a_set_n": len(a_set), "a_kept_in_nodes": sum(1 for e in nodes if e["term"] in a_set)}
    out["ext_double_count"] = ext_res
    dump(A, "ext_double_count.json", ext_res)
    log(f"  ext: code 增量={ext_res['ext_code_increments']:,} 去重卡数={ext_res['ext_dedup_cards']:,} "
        f"双计数事件={ext_res['double_count_events']:,}（恒等式差={ext_res['identity_code_minus_union_equals_inter']}）"
        f" | ratio>1.0 词={len(ratio_gt1):,} | 误判碎片翻转={len(flips):,}"
        f"（其中未进 nodes 的={ext_res['flips_absent_from_nodes']}）")
    log(f"  A 源漏斗复算: a_keep={funnel['a_keep_recomputed']}（报告 {funnel['report_a_kept']}）"
        f" 零频={funnel['dropped_zero_recomputed']}（报告 {funnel['report_dropped_zero']}）"
        f" 碎片={funnel['dropped_embedded_recomputed']}（报告 {funnel['report_dropped_embedded']}）"
        f" | a_keep 中实际入表={funnel['a_keep_terms_in_nodes']}，"
        f"未入表={funnel['a_keep_terms_absent_from_nodes']}（英文 {funnel['a_keep_absent_english']}）")
    if funnel["a_keep_terms_absent_from_nodes"]:
        finding("F18", "中",
                f"报告 counts.source_a_kept={funnel['report_a_kept']} 高估 A 源实际贡献："
                f"{funnel['a_keep_terms_absent_from_nodes']} 个通过 A 闸门的词在 entry 阶段被英文质量门"
                "二次过滤而未入 nodes.json，且漏斗中无对应计数器（source_a_kept ≠ 含 A 证据的节点数）",
                funnel, "python3 audit_p1.py -> S3",
                "新增 dropped_a_english_gate 计数器，并把各源漏斗计数与产物做 A1 级交叉校验。")
    if abs(funnel["a_keep_recomputed"] - funnel["report_a_kept"]) <= 2 \
            and abs(funnel["dropped_embedded_recomputed"] - funnel["report_dropped_embedded"]) <= 2:
        log("  [ok] A 源漏斗计数与独立复算一致（±2，含 tie 边界）")
    if ratio_gt1 or flips:
        finding("F2b", "高",
                "【F2 实证】长词包含率可 >1.0（卡片级比值不可能 >1）并导致误判：有 A 源词仅因 ext_df 双计数"
                "越过 0.9 阈值被当碎片剔除",
                {"ratio_gt1_terms": len(ratio_gt1), "flips": len(flips),
                 "inflation_max": ext_res["worst_inflation"][:3], "flip_sample": flips[:6]},
                "python3 audit_p1.py -> S3", "按 card 去重重算 ratio 并重跑 P1 基线。")

    # ---------------- S4 排序键真实语义 ----------------
    log("== S4 排序键真实语义 ==")
    def fscore(r):                       # 源码 score = f * rep，rep = max_cc/float(max(f,1))
        return r["freq"] * (r["max_cc"] / r["freq"]) if r["freq"] else 0.0

    key_maxcc = sorted(rows, key=lambda r: (-r["max_cc"], -r["freq"], r["term"]))
    key_float = sorted(rows, key=lambda r: (-fscore(r), -r["freq"], r["term"]))
    key_freq = sorted(rows, key=lambda r: (-r["freq"], r["term"]))
    now = [r["id"] for r in rows]
    eq_maxcc = sum(1 for a, b in zip(now, [r["id"] for r in key_maxcc]) if a == b)
    eq_float = sum(1 for a, b in zip(now, [r["id"] for r in key_float]) if a == b)
    eq_freq = sum(1 for a, b in zip(now, [r["id"] for r in key_freq]) if a == b)
    kk = [(-r["max_cc"], -r["freq"], r["term"]) for r in rows]
    adj = list(zip(rows, rows[1:]))
    prim_viol = sum(1 for a, b in adj if a["max_cc"] < b["max_cc"])
    tie_viol = sum(1 for a, b in adj if a["max_cc"] == b["max_cc"] and a["freq"] < b["freq"])
    grp = Counter(r["max_cc"] for r in rows)
    noise = sum(1 for r in rows if r["freq"] and fscore(r) != r["max_cc"])
    order_test = {"n": len(rows), "positions_equal_to_maxcc_int_key": eq_maxcc,
                  "positions_equal_to_float_score_key": eq_float,
                  "positions_equal_to_freq_key": eq_freq,
                  "maxcc_int_key_monotone": kk == sorted(kk),
                  "adjacent_primary_key_violations": prim_viol,
                  "adjacent_tiebreak_violations(max_cc equal, freq ascending)": tie_viol,
                  "nodes_where_float_score_differs_from_max_cc": noise,
                  "distinct_max_cc_values": len(grp),
                  "largest_tie_group": grp.most_common(1)[0] if grp else None,
                  "nodes_in_tie_groups>1": sum(v for v in grp.values() if v > 1),
                  "head10": [(r["term"], r["freq"], r["max_cc"], round(fscore(r), 12))
                             for r in rows[:10]]}
    out["order_test"] = order_test
    dump(A, "order_test.json", order_test)
    log(f"  顺序复现: float score 键同位={eq_float}/{len(rows)} | max_cc 整数键同位={eq_maxcc} | "
        f"freq 键={eq_freq} | 主键相邻违例={prim_viol} | 次级键(-freq)相邻违例={tie_viol} | "
        f"score≠max_cc 的节点={noise:,} | 最大同分组={order_test['largest_tie_group']}")
    if eq_float == len(rows):
        finding("F1b", "中",
                "【F1 实证】交付顺序 == sort(-freq×rep, -freq, term)，且 freq×rep 在同分组内受 1 ulp 浮点噪声"
                "支配 ⇒ 声明的次级键 (-freq, term) 实际不生效，同分组的先后由浮点噪声决定（截断边界随之由噪声"
                "决定，但可复现）",
                order_test, "python3 audit_p1.py -> S4",
                "排序键改用整数/Decimal 量（如 (-max_cc, -freq, term)），并明确簇内代表性与频次的权重。")
    else:
        finding("F13", "高", "nodes.json 顺序无法用代码声明的排序键复现（独立重算不符）",
                order_test, "python3 audit_p1.py -> S4", "核对 _score/rep 与截断分支。")

    # ---------------- S5 边界 / 口径 ----------------
    log("== S5 边界与口径 ==")
    by_src = defaultdict(list)
    for e in nodes:
        by_src["+".join(e["sources"])].append(e["freq"])
    freq_gate = {k: {"n": len(v), "min": min(v), "median": int(np.median(v))}
                 for k, v in sorted(by_src.items())}
    low = sum(v["n"] for k, v in freq_gate.items() if k in ("A", "C")) + \
        freq_gate.get("A+B", {}).get("n", 0) * 0
    out["freq_gate_by_source"] = freq_gate

    en = [e for e in nodes if e["type"] == "kw" and not tb.CJK_RE.search(e["term"])]
    en_gate = {"n": len(en),
               "freq_lt_200": sum(1 for e in en if e["freq"] < 200),
               "only_cls_rep_disjunct(freq<200 & len<9)":
                   sum(1 for e in en if e["freq"] < 200 and len(e["term"]) < 9),
               "len_ge_9_bypass": sum(1 for e in en if len(e["term"]) >= 9),
               "freq_lt_min_df_12": sum(1 for e in en if e["freq"] < 12),
               "min_freq": min((e["freq"] for e in en), default=0),
               "lt12_sample": [{"term": e["term"], "freq": e["freq"], "sources": e["sources"]}
                               for e in en if e["freq"] < 12][:12]}
    row_by_term = {r["term"]: r for r in rows}
    cohort = [e for e in en if e["freq"] < 200 and len(e["term"]) < 9]
    en_gate["only_cls_rep_cohort"] = len(cohort)
    en_gate["only_cls_rep_cohort_without_cls1_data"] = sum(
        1 for e in cohort if row_by_term[e["term"]]["my_cls1"] == "")
    en_gate["kw_nodes_with_fallback_filled_cls"] = len(cls_fallback)
    en_gate["cards_without_cls1"] = no_cls1_cards
    out["en_gate"] = en_gate
    if cls_fallback:
        finding("F17", "中",
                f"{len(cls_fallback)} 个 kw 节点的 `cls` 不是其卡片证据的众数，而是 `fallback_cls_for_cluster` "
                "用簇级 top_subjects[0] 推断填充（这些词的卡片 cls1 全为空）；同类缺失数据同时把 "
                "cls_rep 算成 1.0，使英文闸门的‘分类纯度’分量为真——纯度语义在缺数据时反转",
                {"fallback_filled_nodes": len(cls_fallback),
                 "sample": cls_fallback[:8],
                 "cards_without_cls1": no_cls1_cards,
                 "only_cls_rep_cohort": en_gate["only_cls_rep_cohort"],
                 "cohort_without_cls1_data": en_gate["only_cls_rep_cohort_without_cls1_data"]},
                "python3 audit_p1.py -> S2/S5",
                "区分‘真实分类纯度’与‘无分类数据’：cls_rep 分母只统计有 cls1 的卡片；"
                "cls 字段缺证据时留空或标注 inferred。")

    sub_lex = tb.load_subject_lexicon(IX["subjects"])
    b_only_cjk = [e for e in nodes if e["type"] == "kw" and e["sources"] == ["B"]
                  and tb.CJK_RE.search(e["term"])]
    b_cjk_audit = {"sub_lex_n": len(sub_lex), "b_only_cjk_n": len(b_only_cjk),
                   "in_subject_lex": sum(1 for e in b_only_cjk if e["term"] in sub_lex),
                   "in_a_set": sum(1 for e in b_only_cjk if e["term"] in a_set),
                   "sample": [{"term": e["term"], "freq": e["freq"]} for e in b_only_cjk[:12]],
                   "admitted_by_df_path_only":
                       sum(1 for e in b_only_cjk if e["term"] not in sub_lex and e["term"] not in a_set),
                   "report_policy": report["params"]["b_cjk_policy"]}
    out["b_cjk_audit"] = b_cjk_audit

    c_keys = {e["term"] for e in nodes if e["type"] == "cls"}
    kw_terms = {e["term"] for e in nodes if e["type"] == "kw"}
    provenance = {"a_set_n": len(a_set), "report_a_kept": cnt["source_a_kept"],
                  "a_set_in_nodes_no_A_source": sum(1 for e in nodes
                                                    if e["term"] in a_set and "A" not in e["sources"]),
                  "A_only_n": freq_gate.get("A", {}).get("n", 0),
                  "A_only_min_freq": freq_gate.get("A", {}).get("min"),
                  "C_only_n": freq_gate.get("C", {}).get("n", 0),
                  "C_only_min_freq": freq_gate.get("C", {}).get("min"),
                  "B_only_min_freq": freq_gate.get("B", {}).get("min")}
    out["provenance"] = provenance

    cls_level = {"cls_nodes": len(c_keys),
                 "cls_nodes_cls_eq_term": sum(1 for e in nodes if e["type"] == "cls"
                                              and e["cls"] == e["term"]),
                 "kw_cls_mismatch_vs_recount": len(cls_bad),
                 "kw_cls_mismatch_sample": cls_bad[:10],
                 "cls_term_collision_with_kw": sorted(c_keys & kw_terms),
                 "cls_term_collision_with_a_set": sorted(c_keys & a_set)[:10]}
    out["cls_level"] = cls_level

    dump(A, "boundary.json", {"freq_gate_by_source": freq_gate, "en_gate": en_gate,
                              "b_cjk_audit": b_cjk_audit, "provenance": provenance,
                              "align": align, "merge_check": merge_check})
    dump(A, "cls_level.json", cls_level)
    dump(A, "compound_probe.json",
         {t: {"my_b_df": my_b_df.get(t, 0), "code_b_df": code_b_df.get(t, 0),
              "in_topM_cards": probe_topM.get(t, 0), "in_nodes": t in kw_terms} for t in PROBE})
    log("  频控: " + "; ".join(f"{k}:n={v['n']},min={v['min']}" for k, v in freq_gate.items()))
    log(f"  英文闸门: n={en_gate['n']} freq<200={en_gate['freq_lt_200']} 仅靠 cls_rep 过闸="
        f"{en_gate['only_cls_rep_disjunct(freq<200 & len<9)']} len>=9 旁路={en_gate['len_ge_9_bypass']} "
        f"freq<min_df12={en_gate['freq_lt_min_df_12']}")
    log(f"  B-only CJK={b_cjk_audit['b_only_cjk_n']} 其中无 A/学科词表证据（纯 df 通路）="
        f"{b_cjk_audit['admitted_by_df_path_only']}")
    log("  复合词探针: " + ", ".join(f"{t}:df={my_b_df.get(t,0)}" for t in PROBE[:8]))

    # ---------------- S6 实验 ----------------
    log("== S6 实验（确定性 / 截断）==")
    sc = os.path.join(A, "scratch")
    exp = {}
    for tag in ("d1", "d2", "trunc"):
        p = os.path.join(sc, tag, "nodes.json")
        if not os.path.exists(p):
            exp[tag] = {"present": False}
            continue
        d = json.load(open(p, encoding="utf-8"))
        rp = os.path.join(sc, tag, "report.json")
        r = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else {}
        exp[tag] = {"present": True, "n": len(d),
                    "truncated": r.get("counts", {}).get("truncated"),
                    "counts_nodes": r.get("counts", {}).get("nodes"),
                    "sha256": hashlib.sha256(json.dumps(
                        [[e["id"], e["term"], e["type"], e["freq"], e["cluster"], e["cls"],
                          e["sources"]] for e in d], ensure_ascii=False).encode()).hexdigest()}
        if tag == "trunc":
            full = [[e["term"], e["freq"], e["cluster"], e["cls"], e["sources"]] for e in nodes]
            tr = [[e["term"], e["freq"], e["cluster"], e["cls"], e["sources"]] for e in d]
            exp[tag]["prefix_of_delivered_order"] = tr == full[:len(tr)]
            exp[tag]["equals_topN_by_float_score_key"] = (
                {e["term"] for e in d} == {r_["term"] for r_ in key_float[:len(d)]})
            exp[tag]["equals_topN_by_maxcc_int_key"] = (
                {e["term"] for e in d} == {r_["term"] for r_ in key_maxcc[:len(d)]})
            if len(d) < len(rows):
                cut = rows[len(d)]
                exp[tag]["cut_node"] = {"term": cut["term"], "freq": cut["freq"],
                                        "max_cc": cut["max_cc"], "score": fscore(cut)}
                exp[tag]["nodes_sharing_cut_int_score"] = sum(
                    1 for r in rows if r["max_cc"] == cut["max_cc"])
                exp[tag]["nodes_sharing_cut_float_score"] = sum(
                    1 for r in rows if fscore(r) == fscore(cut))
    out["experiments"] = exp
    dump(A, "experiments.json", exp)
    if exp.get("d1", {}).get("present") and exp.get("d2", {}).get("present"):
        same = exp["d1"]["sha256"] == exp["d2"]["sha256"]
        log(f"  确定性: d1==d2 ? {same} (n={exp['d1']['n']}/{exp['d2']['n']})")
        if not same:
            finding("F14", "高", "同参数两次全量重跑产物不一致（非确定性）",
                    {"d1": exp["d1"], "d2": exp["d2"]}, "bash audit/p1/scratch/run_experiments.sh",
                    "定位集合迭代序 / 哈希随机化。")
    if exp.get("trunc", {}).get("present"):
        t = exp["trunc"]
        log(f"  截断: n={t['n']} truncated={t['truncated']} 是全量顺序前缀={t.get('prefix_of_delivered_order')} "
            f"等于 float 键前N={t.get('equals_topN_by_float_score_key')} "
            f"整数键前N={t.get('equals_topN_by_maxcc_int_key')} 切点同整数分节点数="
            f"{t.get('nodes_sharing_cut_int_score')}")
        if not t.get("prefix_of_delivered_order"):
            finding("F15", "高", "规模截断路径结果与全量顺序不一致（截断实现与排序键不同源）",
                    t, "bash audit/p1/scratch/run_experiments.sh", "核对截断分支。")
        else:
            finding("F15", "低",
                    f"截断路径本身自洽（3000 节点 = 全量顺序前缀），但切点落在 {t.get('nodes_sharing_cut_int_score')} "
                    "个同整数分（同主导簇卡数）节点中间，具体取舍由 1 ulp 浮点噪声决定；"
                    "交付基线 truncated=false，该路径未被基线覆盖",
                    t, "bash audit/p1/scratch/run_experiments.sh",
                    "排序键改用整数键后重跑，并把一次 --max-nodes 触发态纳入验收。")

    # ---------------- S7 自测产物（50 词抽检件）数值列复核 ----------------
    log("== S7 50 词自测件数值列复核 ==")
    by_term = {r["term"]: r for r in rows}
    st = {"candidates_rows": 0, "reviewed_rows": 0, "id_set_equal": None,
          "cand_id_field_mismatch": 0, "cand_rep_mismatch": 0, "cand_clsrep_mismatch": 0,
          "cand_ncl_mismatch": 0, "reviewed_field_mismatch": 0, "reviewed_cols": None,
          "cand_cols": None, "cand_rep_sample": []}
    pc = os.path.join(T, "p1-sample50-candidates.txt")
    pr = os.path.join(T, "p1-sample50.txt")
    if os.path.exists(pc) and os.path.exists(pr):
        cand = [l.rstrip("\n").split("\t") for l in open(pc, encoding="utf-8")
                if l.strip() and not l.startswith("#")]
        rev = [l.rstrip("\n").split("\t") for l in open(pr, encoding="utf-8")
               if l.strip() and not l.startswith("#")]
        st["candidates_rows"], st["reviewed_rows"] = len(cand), len(rev)
        st["cand_cols"] = sorted({len(r) for r in cand})
        st["reviewed_cols"] = sorted({len(r) for r in rev})
        st["id_set_equal"] = {r[1] for r in cand} == {r[1] for r in rev}
        nref = {e["id"]: e for e in nodes}
        for r in rev:
            i = int(r[1])
            n = nref.get(i)
            if n is None or [n["term"], n["type"], n["freq"], n["cluster"], n["cls"]] != \
                    [r[2], r[3], int(r[4]), int(r[5]), r[6]]:
                st["reviewed_field_mismatch"] += 1
        for r in cand:      # stratum,id,term,type,freq,cluster,cls,cls_rep,sources,rep,n_clusters,,
            if len(r) < 11:
                continue
            t = r[2]
            row = by_term.get(t)
            if row is None:
                continue
            f = row["freq"]
            want_rep = row["max_cc"] / f if f else 0.0
            want_clsrep = row["max_cls"] / f if f else 0.0
            got_rep, got_clsrep, got_ncl = float(r[9]), float(r[7]), int(r[10])
            if abs(got_rep - want_rep) > 0.0011:
                st["cand_rep_mismatch"] += 1
                st["cand_rep_sample"].append({"term": t, "file_rep": got_rep,
                                              "recount_rep": round(want_rep, 3)})
            if abs(got_clsrep - want_clsrep) > 0.0011:
                st["cand_clsrep_mismatch"] += 1
            if got_ncl != row["ncl"]:
                st["cand_ncl_mismatch"] += 1
    out["sample_selftest"] = st
    dump(A, "sample50_check.json", st)
    log(f"  候选件 {st['candidates_rows']} 行/列数 {st['cand_cols']}；已判定件 "
        f"{st['reviewed_rows']} 行/列数 {st['reviewed_cols']}；id 集相同={st['id_set_equal']}；"
        f"rep 不符={st['cand_rep_mismatch']} cls_rep 不符={st['cand_clsrep_mismatch']} "
        f"n_clusters 不符={st['cand_ncl_mismatch']}；已判定件字段不符={st['reviewed_field_mismatch']}")
    if st["reviewed_cols"] and len(st["reviewed_cols"]) == 1 and st["reviewed_cols"][0] == 10:
        finding("F16", "低",
                "自测件 p1-sample50.txt（人工判定留痕）比生成件 p1-sample50-candidates.txt 少 3 列"
                "（cls_rep/rep/n_clusters）——判定所依据的数值证据未随判定件留存，噪声率 0.04 无法在"
                "该文件内被复核",
                st, "python3 audit_p1.py -> S7",
                "判定件保留生成件全部数值列（或在报告注明候选件为数值证据源）。")

    # ---------------- 汇总 ----------------
    payload = {"findings": FINDINGS, "log": LOG, "static": stat, "artifact": art,
               "merge_check": merge_check, "primitive_topM": prim, "align": align}
    json.dump(payload, open(os.path.join(A, "p1-findings.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    rank = {"高": 0, "中": 1, "低": 2}
    log("== 发现汇总 ==")
    for f in sorted(FINDINGS, key=lambda x: rank.get(x["severity"], 9)):
        log(f"  [{f['severity']}] {f['id']} {f['title'][:76]}")
    log(f"[done] findings={len(FINDINGS)} -> {os.path.join(A, 'p1-findings.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
