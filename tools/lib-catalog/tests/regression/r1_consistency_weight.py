#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""r1_consistency_weight.py — 共现权重独立重算（终审① / 终审⑤）

守护什么：`edges.csr.npz` 里 kw-kw 共现边的权重，必须能由 `card_topics.jsonl`
**独立反算**出来——公式 w = log1p(min(c,50))/log1p(50) + 0.3·log1p(cs)/log1p(50)（clamp ≤1）。
一旦有人重新引入"共现重复计数"（终审①：spec 循环 + aug 循环各写一次），
`settlement ↔ entanglement` 的 c 会从 1 变 2、权重从 0.1762914360 回到 **0.2794153094**，
本用例立即 FAIL。

用例组成：
  [1] 终审① 冻结反例：settlement(id=168) ↔ entanglement(id=4232)
      · 权重 == 0.1762914344（float64 口径）/ 落盘 0.1762914360（float32）
      · R1 前错值 0.2794153094 必须不再出现（"反例有牙"）
      · 共现卡数 c == 1，且命中卡 mms == 991000938579704181
  [2] 确定性抽样的另外 2 条 kw-kw 边（饱和边 + 中值边）逐边重算比对（共 3 条）
  [3] 层级边（主题→cls2）权重恒为 1.0（结构边，不参与共现公式）

只读：不写任何主体产物；不触网。
来源：终审① 与 终审⑤，见 README.md「来源引用」。
"""
import os
import sys

sys.dont_write_bytecode = True          # 只读纪律：先于 import _common 生效，不落 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

TOL = 1e-6          # float32 落盘容差（与 P2 验收同口径）
SUBCMD = "r1_consistency_weight"


def pick_sample_edges(nodes, typ, ip, ix, wt):
    """确定性抽样 2 条 kw-kw 共现边：优先"权重饱和边"与"中值边"。

    规则（可复现）：判据按优先级依次尝试（饱和边 → 中值边 → 非平凡边 → 任意 kw-kw 边），
    **每个判据贡献 1 条**：按源点 id ↑、CSR 内出边顺序扫描取首个满足条件者；
    某判据全图无命中则顺延下一判据（避免"数据形态变化导致用例失效"）。
    """
    criteria = [("饱和边(w≥0.9999)", lambda w: w >= 0.9999),
                ("中值边(0.6≤w≤0.9)", lambda w: 0.6 <= w <= 0.9),
                ("非平凡边(0<w<1)", lambda w: 0.0 < w < 1.0),
                ("任意 kw-kw 边", lambda w: True)]
    banned = {frozenset(C.FROZEN["ce1_pair"])}
    picked, used = [], set()
    for label, pred in criteria:
        if len(picked) >= 2:
            break
        for u in range(len(nodes)):
            if typ[u] != "kw" or u in used:
                continue
            hit = None
            for q in range(int(ip[u]), int(ip[u + 1])):
                v = int(ix[q])
                if v == u or typ[v] != "kw" or v in used:
                    continue
                if frozenset((u, v)) in banned:
                    continue
                if pred(float(wt[q])):
                    hit = (u, v, label)
                    break
            if hit:
                picked.append(hit)
                used.update((hit[0], hit[1]))
                break
    return picked


def build(R):
    nodes = C.load_nodes()
    typ = [x["type"] for x in nodes]
    freq = [int(x["freq"]) for x in nodes]
    by_term = {x["term"]: x["id"] for x in nodes}
    clus = {x["id"]: int(x["cluster"]) for x in nodes}
    ip, ix, wt = C.load_edges()
    n = len(nodes)

    def stored(u, v):
        hit = None
        for q in range(int(ip[u]), int(ip[u + 1])):
            if int(ix[q]) == v:
                hit = float(wt[q])
        return hit

    # ---- [1] 终审① 冻结反例 -------------------------------------------------
    R.section("1 终审① 反例：settlement ↔ entanglement 权重独立重算")
    term_u, term_v = C.FROZEN["ce1_pair"]
    if term_u not in by_term or term_v not in by_term:
        R.skip("终审① 反例（%s ↔ %s）" % (term_u, term_v),
               "nodes.json 已重建且不再含该主题 —— 反例顶点消失，需人工确认后改写 FROZEN")
    else:
        u, v = by_term[term_u], by_term[term_v]
        R.info("顶点：%s(id=%d) ↔ %s(id=%d) | freq=%d/%d" % (
            term_u, u, term_v, v, freq[u], freq[v]))

        cnt, cnt_sc, hits = C.scan_pair_counts([(u, v)], mms_of=True, clusters=clus)
        key = (u, v) if u < v else (v, u)
        c, cs = cnt[key], (cnt_sc[key] if cnt_sc is not None else 0)
        exp64 = C.w_cooccurrence(c, cs)
        got = stored(key[0], key[1])

        # 硬断言①：该对确实在 card_topics 中共现（重算有意义的前提）
        R.check("反例对在 card_topics 中共现（c ≥ 1）", c >= 1, "实测 c=%d" % c, source="ce1")
        # 硬断言②：**公式恒等** —— 落盘权重必须等于按"去重后的共现书数"重算的值。
        # 终审① 的双计数若复现，落盘值会等于 w(2c[, 2cs])，与本式不符 → 立刻 FAIL。
        probe = ""
        if c and abs(exp64 - C.w_cooccurrence(2 * c, cs)) > 1e-6:
            if got is not None and (abs(got - C.w_cooccurrence(2 * c, cs)) < TOL or
                                    abs(got - C.w_cooccurrence(2 * c, 2 * cs)) < TOL):
                probe = "；落盘值命中 w(2c) 双计数特征 —— 终审① 回归"
        R.check("落盘权重 == 独立重算（c=%d / cs=%d，容差 %g）" % (c, cs, TOL),
                got is not None and abs(got - exp64) < TOL,
                "落盘=%s 重算=%.10f%s" % ("缺边" if got is None else "%.10f" % got, exp64, probe),
                source="r1_assert")
        # 基线漂移（非 FAIL）：c / cs / 权重 / 命中卡 与 R1 基线比对，产物重建时如实报 WARN
        R.baseline("终审① 反例共现书数 c", c, C.FROZEN["ce1_c"],
                   note="R1 基线该对仅 1 本书共现（MMS %s）" % C.FROZEN["ce1_mms"], source="ce1")
        R.baseline("终审① 反例重算权重", round(exp64, 10), C.FROZEN["ce1_weight_fixed"],
                   note="float64 重算值", source="ce1")
        if c == C.FROZEN["ce1_c"]:
            R.check("命中卡 mms == %s" % C.FROZEN["ce1_mms"],
                    hits[key] == [C.FROZEN["ce1_mms"]],
                    "实测命中卡=%s" % (hits[key] or "无"), source="ce1")
        else:
            R.info("命中卡 %s（c=%d，非单卡场景，跳过单卡号断言）" % (hits[key][:3], c))
        if got is not None and abs(got - C.FROZEN["ce1_weight_pre_r1"]) < 1e-6:
            R.check("R1 前双计数错值 %.10f 未复现" % C.FROZEN["ce1_weight_pre_r1"], False,
                    "落盘值恰为终审① 双计数错值", source="ce1")
        else:
            R.check("R1 前双计数错值 %.10f 未复现" % C.FROZEN["ce1_weight_pre_r1"], True,
                    "落盘=%s" % ("缺边" if got is None else "%.10f" % got), source="ce1")

    # ---- [2] 另抽 2 条 kw-kw 边 --------------------------------------------
    R.section("2 抽样 2 条 kw-kw 共现边（确定性扫描）")
    picked = pick_sample_edges(nodes, typ, ip, ix, wt)
    R.check("抽到 ≥1 条可重算的 kw-kw 共现边（含饱和/中值判据）", len(picked) >= 1,
            "抽到 %d 条：%s" % (len(picked),
                             "；".join("%s↔%s[%s]" % (nodes[u]["term"], nodes[v]["term"], l)
                                       for u, v, l in picked) or "无"),
            source="r1_assert")
    if len(picked) < 2:
        R.info("仅抽到 %d 条（图已重建，判据命中面变窄）" % len(picked))
    pairs = [(u, v) for u, v, _ in picked]
    cnt, cnt_sc, _ = C.scan_pair_counts(pairs, clusters=clus)
    for u, v, label in picked:
        key = (u, v) if u < v else (v, u)
        c, cs = cnt[key], (cnt_sc[key] if cnt_sc is not None else 0)
        exp = C.w_cooccurrence(c, cs)
        got = stored(key[0], key[1])
        R.check("%s：%s(%d)↔%s(%d) 权重一致" %
                (label, nodes[key[0]]["term"], key[0], nodes[key[1]]["term"], key[1]),
                got is not None and abs(got - exp) < TOL,
                "c=%d cs=%d 重算=%.10f 落盘=%s" % (
                    c, cs, exp, "缺边" if got is None else "%.10f" % got),
                source="r1_assert")
    R.info("抽样判据：%s" % "；".join("%s→%s" % (nodes[u]["term"], nodes[v]["term"]) + "[" + l + "]"
                                     for u, v, l in picked))

    # ---- [3] 层级边权重恒为 1.0 -------------------------------------------
    R.section("3 层级边（主题→cls2）权重恒定")
    hier = []
    for u in range(n):
        if typ[u] != "kw":
            continue
        for q in range(int(ip[u]), int(ip[u + 1])):
            v = int(ix[q])
            if typ[v] == "cls" and float(wt[q]) >= 0.9999:
                hier.append((u, v))
                break
        if len(hier) >= 20:
            break
    if not hier:
        R.check("存在层级边（主题→cls 类目节点）", False, "未找到任何 kw→cls 出边",
                source="r1_assert")
    else:
        bad = [(u, v, stored(u, v)) for u, v in hier if abs(stored(u, v) - 1.0) > TOL]
        R.check("抽验 %d 条层级边权重均 == 1.0" % len(hier), not bad,
                "异常：%s" % (bad[:3] or "无"), source="r1_assert")
        R.info("样本：%s" % "、".join("%s→%s" % (nodes[u]["term"], nodes[v]["term"])
                                     for u, v in hier[:5]))

    # ---- 概览 -------------------------------------------------------------
    R.section("概览")
    R.info("节点 %d / 边 %d / 抽样重算 %d 条（含终审① 反例）" %
           (n, len(ix), len(picked) + (1 if term_u in by_term else 0)))


if __name__ == "__main__":
    sys.exit(C.main_guard(SUBCMD, "终审① 共现权重独立重算（从 card_topics 反算）",
                          build, C.SOURCES))
