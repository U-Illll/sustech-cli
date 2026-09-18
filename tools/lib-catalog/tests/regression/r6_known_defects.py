#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""r6_known_defects.py — 已修缺陷的**硬断言回归**（R2-E 升级）

R2-E 变更：本文件原为 xfail 预警用例（D1/M2/F2/M6 四项皆 warn_check）。
R2-A/R2-B 修复后，前三项按 `_common.py#FROZEN` 的 R2 后基线**升级为 check() 硬断言**——
缺陷一旦回归即判 FAIL、阻断回归集：

  已升级为硬断言（R2-A/R2-B 已修）：
  [1] D1  层级边被同键去重平局吃掉（R1：登记 4,832 / 实存 4,823 / 缺 9）→ R2-A 修复：缺 **0**
          含**有牙性对照**：在 `edges.csr.pre-r2.npz` + `nodes.pre-r2.json` 上独立重算仍须得 9 条缺失
  [2] M2  ASCII 大小写不对称（R1：349 个 cls 码用本名搜不到）→ R2-B 修复：检索侧 norm_key 等值归一
          硬断言 = 「存名 / 归一名查询命中同一节点」（**非**「统一小写存储」——那是未采纳的另一方案）
  [3] F2  P1 ext_df 双计数（R1：207,596 事件 / 580 词 ratio>1 / 129 词被误剔）→ R2-A 修复：0 / 0 / 全回归
          硬断言 = 漏斗闭合 + ratio 不可能性消除 + **129 词在表**（两条互证路径：sources 字段 / A 源集）

  仍为预警（R2 未纳入修复，保持 xfail 不阻断）：
  [4] M6  数值参数负值无下界 → --top/-1、--evidence -1、--expand-cards -1、search --top -1

只读：不修改主体代码与验收脚本；审计产物只读；不触网。
"""
import json
import os
import re
import sys
from collections import Counter

sys.dont_write_bytecode = True          # 只读纪律：先于 import _common 生效，不落 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

SUBCMD = "r6_known_defects"
TODO = "R2 未纳入修复"                  # M6 专用：R2 轮未修，保持 xfail
MAX_OUT = C.MAX_OUT


# ---------------------------------------------------------------------------
# [1] D1：层级边零丢失（R2-A 已修 → 硬断言）
# ---------------------------------------------------------------------------
def _hier_and_present(nodes, edges_path, card_topics_path, cards_path):
    """独立重算层级边（卡 top-5 kw 对「卡 cls2」投票，众数、平局取小 id）与产物实存集。

    返回 (hier, present, missing, mms_mismatch, no_vote_ids)。
    口径与 audit/num/audit_num.py 一致；本函数为**自研实现**，不依赖施工方脚本。
    """
    C.ensure_import_paths()                 # pylibs 须在 sys.path 上（与 _common 的 loader 同约定）
    import numpy as np
    cls2id = {x["term"].upper(): x["id"] for x in nodes if x["type"] == "cls"}
    typ = {x["id"]: x["type"] for x in nodes}
    votes, mms_mismatch = {}, 0
    with open(cards_path, encoding="utf-8") as fc, open(card_topics_path, encoding="utf-8") as ft:
        for lc, lt in zip(fc, ft):
            c, t = json.loads(lc), json.loads(lt)
            if c.get("mms", "") != t.get("mms", ""):
                mms_mismatch += 1
            cid = cls2id.get((c.get("cls2") or "").strip().upper(), -1)
            if cid < 0:
                continue
            for u in t["topics"]:
                votes.setdefault(u, Counter())[cid] += 1
    hier = {u: max(cc.items(), key=lambda kv: (kv[1], -kv[0]))[0] for u, cc in votes.items()}
    z = np.load(edges_path)
    ip, ix = z["indptr"], z["indices"]
    present = set()
    for u in range(len(ip) - 1):
        for q in range(int(ip[u]), int(ip[u + 1])):
            present.add((u, int(ix[q])))
    missing = sorted((u, v) for u, v in hier.items() if (u, v) not in present)
    no_vote = [u for u in range(len(nodes)) if typ.get(u) == "kw" and u not in hier]
    return hier, present, missing, mms_mismatch, no_vote


def part_d1(R, nodes):
    R.section("1 D1 层级边零丢失（R2-A 已修 → 硬断言）")
    T, D = C.topics_dir(), C.data_dir()
    cards_p = os.path.join(D, "cards.jsonl")
    ct_p = os.path.join(T, "card_topics.jsonl")
    try:
        C.require_files(cards_p, ct_p)
    except C.DataMissing as e:
        R.skip("D1 独立重算", str(e))
        return
    hier, present, missing, mms_mismatch, no_vote = _hier_and_present(
        nodes, os.path.join(T, "edges.csr.npz"), ct_p, cards_p)

    meta = json.load(open(os.path.join(T, "meta.json"), encoding="utf-8"))
    p2c = ((meta.get("stages") or {}).get("P2") or {}).get("counts") or {}
    R.info("独立重算：期望层级边 %d / 产物实存 %d / 缺失 %d" % (
        len(hier), len(hier) - len(missing), len(missing)))
    R.info("登记值：hierarchical_edges=%s、kw_without_hier_edge=%s" % (
        p2c.get("hierarchical_edges"), p2c.get("kw_without_hier_edge")))

    # ---- 支撑事实 ----
    R.check("卡表与证据链无 mms 错位（重算前提）", mms_mismatch == 0,
            "错位 %d 行" % mms_mismatch, source="d1")
    R.check("独立重算的期望层级边 == meta 登记 hierarchical_edges（%s）"
            % p2c.get("hierarchical_edges"),
            len(hier) == p2c.get("hierarchical_edges"),
            "重算 %d / 登记 %s" % (len(hier), p2c.get("hierarchical_edges")), source="d1")
    R.check("独立重算的「无投票 kw」数 == meta 登记 kw_without_hier_edge（%s）"
            % p2c.get("kw_without_hier_edge"),
            len(no_vote) == p2c.get("kw_without_hier_edge"),
            "重算 %d：%s" % (len(no_vote), [nodes[u]["term"] for u in no_vote]), source="d1")

    # ---- R2-E 硬断言①：登记 == 实存（登记值不得再是"含被截断边"的虚数）----
    R.check("**D1 登记层级边 == 产物实存**（实存 %d）" % (len(hier) - len(missing)),
            len(hier) - len(missing) == p2c.get("hierarchical_edges"),
            "实存 %d / 登记 %s（R1 时二者差 9）" % (
                len(hier) - len(missing), p2c.get("hierarchical_edges")), source="d1")
    # ---- R2-E 硬断言②：零缺失 ----
    R.check("**D1 层级边零丢失**（R2-A 已修：缺失 %d 条）" % len(missing), len(missing) == 0,
            "仍有 %d 条结构边被 top-20 截断吃掉：%s" % (
                len(missing),
                [(nodes[u]["term"], nodes[v]["term"]) for u, v in missing[:9]] or "无"),
            source="d1")
    R.baseline("D1 期望层级边数（R2 后基线 %d；R1 基线 %d）"
               % (C.FROZEN["d1_registered_hier"], C.FROZEN["d1_registered_hier_r1"]),
               len(hier), C.FROZEN["d1_registered_hier"],
               note="R2-A 重建词表后层级边自然增长（4,832→5,151）", source="d1")
    got = {(nodes[u]["term"], nodes[v]["term"]) for u, v in missing}
    r1bad = {tuple(p) for p in C.FROZEN["d1_r1_missing_pairs"]}
    R.check("D1 R1 的 9 条缺失清单已全部回归（当前缺失集与 R1 清单无交集）", not (r1bad & got),
            "R1 缺陷清单中仍缺失：%s" % (sorted(r1bad & got) or "无"), source="d1")

    # ---- R2-E 硬断言③：有牙性对照 —— pre-r2 产物上必须仍能复现 9 条缺失 ----
    # 注意：pre-r2 的**节点 id 空间**与当前不同（5,187 vs 5,507 且 98.6% id 迁移），
    # 故必须整组使用 pre-r2 备份（nodes + card_topics + edges）自洽重算，不可与当前 card_topics 混用。
    pre_e = os.path.join(T, "edges.csr.pre-r2.npz")
    pre_n = os.path.join(T, "nodes.pre-r2.json")
    pre_ct = os.path.join(T, "card_topics.pre-r2.jsonl")
    if os.path.isfile(pre_e) and os.path.isfile(pre_n) and os.path.isfile(pre_ct):
        pn = json.load(open(pre_n, encoding="utf-8"))
        _h, _p, pmiss, _mm, _nv = _hier_and_present(pn, pre_e, pre_ct, cards_p)
        R.check("有牙性：pre-r2 产物独立重算仍得 %d 条缺失（断言非空转）"
                % C.FROZEN["d1_pre_r2_missing"],
                len(pmiss) == C.FROZEN["d1_pre_r2_missing"],
                "pre-r2 缺失 %d 条：%s" % (
                    len(pmiss), sorted({(pn[u]["term"], pn[v]["term"]) for u, v in pmiss})[:9]),
                source="d1")
    else:
        R.info("pre-r2 备份不全（%s / %s / %s）→ 跳过有牙性对照"
               % (C.rel(pre_e), C.rel(pre_n), C.rel(pre_ct)))


# ---------------------------------------------------------------------------
# [2] M2：大小写检索一致性（R2-B 已修 → 硬断言）
# ---------------------------------------------------------------------------
def part_m2(R, nodes):
    R.section("2 M2 大小写检索一致性（R2-B 已修 → 硬断言）")
    victims = [x for x in nodes if x["term"] != x["term"].lower()]
    R.info("大写 cls 码 = %d 个；样本 %s" % (
        len(victims),
        "、".join("%s(freq=%d)" % (x["term"], x["freq"])
                  for x in sorted(victims, key=lambda y: -y["freq"])[:5])))
    R.baseline("M2 大写 cls 码数（R2 后基线 %d）" % C.FROZEN["m2_victims"],
               len(victims), C.FROZEN["m2_victims"],
               note="R2-B 选定「检索时等值归一」而非「统一小写存储」，故仍为大写属**既定策略**，非缺陷",
               source="m2")

    # ---- 硬断言①：CLI 端 存名 / 归一名 命中数一致（高频受害者抽样）----
    sample = sorted(victims, key=lambda y: -y["freq"])[:6]
    bad = []
    for x in sample:
        up, lo = x["term"], x["term"].lower()
        rc1, o1 = C.run_tool(["search", up, "--top", "3", "--expand", "no"], timeout=180)
        rc2, o2 = C.run_tool(["search", lo, "--top", "3", "--expand", "no"], timeout=180)
        m1 = re.search(r"字面命中\s*(\d+)\s*个", o1)
        m2 = re.search(r"字面命中\s*(\d+)\s*个", o2)
        n1 = int(m1.group(1)) if m1 else 0
        n2 = int(m2.group(1)) if m2 else 0
        if not (rc1 == 0 and rc2 == 0 and n1 >= 1 and n1 == n2):
            bad.append((up, rc1, n1, rc2, n2))
    R.check("**M2 `search` 存名与大写/小写查询字面命中数一致**（抽 %d 个高频 cls 码）" % len(sample),
            not bad, "不一致：%s" % (bad or "无（存名=归一名，命中数逐例相等）"), source="m2")

    # ---- 硬断言②：全量 cls 码 —— 归一键对大小写不敏感 + 自查询为整词精确命中 ----
    try:
        C.ensure_import_paths()
        import topic_graph as TG
        mismatch_key, no_exact = [], []
        for x in victims:
            if TG.norm_key(x["term"]) != TG.norm_key(x["term"].lower()):
                mismatch_key.append(x["term"])
            q = TG.normalize_term(x["term"])
            if TG.match_score(TG.norm_key(x["term"]), q,
                              [TG.normalize_term(t) for t in TG.tokenize(x["term"])]) < 1.0:
                no_exact.append(x["term"])
        R.check("**M2 全量 %d 个 cls 码：归一键对大小写不敏感**" % len(victims),
                not mismatch_key, "失败：%s" % (mismatch_key[:8] or "无"), source="m2")
        R.check("**M2 全量 %d 个 cls 码：以本名为查询均为整词精确命中**"
                "（R1 缺陷症状 `search D9` → 0 命中）" % len(victims),
                not no_exact, "未精确命中：%s" % (no_exact[:8] or "无"), source="m2")
    except Exception as e:                     # 导入/调用失败不得静默
        R.check("M2 全量归一键检查可运行（import topic_graph）", False,
                "异常：%r" % (e,), source="m2")

    # ---- 硬断言③：`around --term <大写>` 可用（R1 缺陷症状 exit 1「未找到」）----
    rc3, o3 = C.run_tool(["around", "--term", "D9", "--hops", "1"], timeout=180)
    R.check("**M2 `around --term D9` 可用**（R1 前 exit 1）", rc3 == 0,
            "exit=%s | %s" % (rc3, (o3.strip().splitlines() or [""])[0][:70]), source="m2")


# ---------------------------------------------------------------------------
# [3] F2：ext_df 双计数（R2-A 已修 → 硬断言）
# ---------------------------------------------------------------------------
def part_f2(R, nodes):
    R.section("3 F2 P1 ext_df 双计数（R2-A 已修 → 硬断言）")
    T = C.topics_dir()
    rep_p = os.path.join(T, "p1-build-report.json")
    try:
        C.require_files(rep_p)
    except C.DataMissing as e:
        R.skip("F2 现场判据", str(e))
        return
    cnt = (json.load(open(rep_p, encoding="utf-8")) or {}).get("counts") or {}
    R.info("现场 P1 报告 %s：source_a_kept=%s dropped_embedded=%s ratio_max=%s ratio_gt1=%s" % (
        C.rel(rep_p), cnt.get("source_a_kept"), cnt.get("source_a_dropped_embedded"),
        cnt.get("a_containment_ratio_max"), cnt.get("a_terms_ratio_gt1")))

    # ---- 硬断言①：A 源漏斗闭合（算术恒等：任何词表重建后都必须成立）----
    funnel = (int(cnt.get("source_a_kept") or 0)
              + int(cnt.get("source_a_dropped_embedded") or 0)
              + int(cnt.get("source_a_dropped_zero_freq") or 0))
    R.check("**F2 A 源漏斗闭合**：kept + dropped_embedded + dropped_zero == a_set_n（%d）"
            % C.FROZEN["f2_a_set_n"], funnel == C.FROZEN["f2_a_set_n"],
            "%s + %s + %s = %d" % (cnt.get("source_a_kept"), cnt.get("source_a_dropped_embedded"),
                                   cnt.get("source_a_dropped_zero_freq"), funnel), source="f2")
    # ---- 硬断言②：卡级比值 >1 的不可能性已消除 ----
    R.check("**F2 containment_ratio 恒 ≤ 1**（R2 后 max=%s）"
            % cnt.get("a_containment_ratio_max"),
            float(cnt.get("a_containment_ratio_max") or 9) <= 1.0,
            "实测 ratio_max=%s（R1 前 2.0 —— 卡级比值 >1 数学上不可能）"
            % cnt.get("a_containment_ratio_max"), source="f2")
    R.check("**F2 ratio>1 的词数 == %d**" % C.FROZEN["f2_ratio_gt1_terms"],
            int(cnt.get("a_terms_ratio_gt1") if cnt.get("a_terms_ratio_gt1") is not None else -1)
            == C.FROZEN["f2_ratio_gt1_terms"],
            "实测 %s 个（R1 证据快照 580）" % cnt.get("a_terms_ratio_gt1"), source="f2")
    R.check("**F2 source_a_kept == %d**（R1 前 1518，+129 为被误剔词回归）"
            % C.FROZEN["f2_a_kept"],
            int(cnt.get("source_a_kept") or 0) == C.FROZEN["f2_a_kept"],
            "实测 %s" % cnt.get("source_a_kept"), source="f2")
    R.check("**F2 source_a_dropped_embedded == %d**（R1 前 894，−129）"
            % C.FROZEN["f2_a_dropped_embedded"],
            int(cnt.get("source_a_dropped_embedded") or 0) == C.FROZEN["f2_a_dropped_embedded"],
            "实测 %s" % cnt.get("source_a_dropped_embedded"), source="f2")

    # ---- 硬断言③：129 词在表（路径 A：pre/post nodes.json 的 sources 字段；完全自足）----
    pre_p = os.path.join(T, "nodes.pre-r2.json")
    if os.path.isfile(pre_p):
        pre_t = {x["term"] for x in json.load(open(pre_p, encoding="utf-8"))}
        post = {x["term"]: x for x in nodes}
        new = [t for t in post if t not in pre_t]
        new_a = [t for t in new if "A" in (post[t].get("sources") or [])]
        gone = sorted(pre_t - set(post))
        R.check("**F2 新增词中 A 源词数 == %d**（= R1 被双计数误剔的 A 源词数）"
                % C.FROZEN["f2_flips"], len(new_a) == C.FROZEN["f2_flips"],
                "新增 %d 词，其中含 A 源 %d、B 源 %d；消失词 %d"
                % (len(new), len(new_a), len(new) - len(new_a), len(gone)), source="f2")
        R.check("F2 词表重建为**纯增**（无词消失）", not gone,
                "消失：%s" % (gone[:8] or "无"), source="f2")
    else:
        R.info("pre-r2 nodes 缺失（%s）→ 跳过路径 A 复核" % C.rel(pre_p))

    # ---- 硬断言④：129 词在表（路径 B：A 源候选集成员数 pre→post 恰 +129，与路径 A 互证）----
    try:
        C.ensure_import_paths()
        from topic_build import load_source_a
        a_set, _m, _raw = load_source_a(json.load(
            open(os.path.join(C.data_dir(), "clusters.json"), encoding="utf-8"))["clusters"])
        R.check("F2 A 源候选集大小 == %d（与审计证据快照一致）" % C.FROZEN["f2_a_set_n"],
                len(a_set) == C.FROZEN["f2_a_set_n"], "实测 %d" % len(a_set), source="f2")
        now = sum(1 for t in a_set if t in {x["term"] for x in nodes})
        R.check("**F2 A 源词在表数 == %d**（R1 前 1357，+129）" % C.FROZEN["f2_a_kept_in_nodes"],
                now == C.FROZEN["f2_a_kept_in_nodes"],
                "实测 %d（与路径 A 的 +129 互证）" % now, source="f2")
    except Exception as e:
        R.check("F2 A 源集复核可运行（import topic_build）", False,
                "异常：%r" % (e,), source="f2")

    # ---- 证据快照：**只作历史锚点**展示，不再据其判 PASS/WARN（R2-E 变更）----
    ev_p = os.path.join(T, "audit", "p1", "evidence", "ext_double_count.json")
    if os.path.isfile(ev_p):
        ev = json.load(open(ev_p, encoding="utf-8"))
        pe = C.FROZEN["f2_pre_r1_evidence"]
        R.check("F2 R1 证据快照仍留档且 == R1 锚点（证明修复确有对照基线）",
                int(ev.get("double_count_events") or 0) == pe["double_count_events"]
                and int(ev.get("ratio_gt1_terms") or 0) == pe["ratio_gt1_terms"]
                and int(ev.get("fragment_drop_flips") or 0) == pe["flips"],
                "快照 double_count=%s ratio_gt1=%s flips=%s（R1 期缺陷度量，**非**现场值）" % (
                    ev.get("double_count_events"), ev.get("ratio_gt1_terms"),
                    ev.get("fragment_drop_flips")), source="f2")


# ---------------------------------------------------------------------------
# [4] M6：负数参数无下界（**R2 未纳入修复，保持 xfail 预警**）
# ---------------------------------------------------------------------------
def part_m6(R):
    R.section("4 M6 数值参数负值无下界（R2 未纳入修复 → 仍为预警）")
    rc, out = C.run_tool(["around", 56, "--hops", "1", "--top", "-1"], timeout=240)
    mtop = re.search(r"\[hop \d+\]\s*(\d+)\s*个主题（显示 top (-?\d+)）", out)
    shown = int(mtop.group(2)) if mtop else None
    n_in_layer = int(mtop.group(1)) if mtop else None
    fixed_top = rc != 0 or (shown is not None and shown >= 1)
    R.warn_check("M6 `--top -1` 被拒绝或不产出矛盾字段", fixed_top,
                 "exit=%s，「层内 %s 个主题（显示 top %s）」——层非空而显示 0 条（自相矛盾字段）" % (
                     rc, n_in_layer, shown), source="m6", todo=TODO)

    rc_e, out_e = C.run_tool(["around", 56, "--hops", "1", "--evidence", "-1"], timeout=240)
    n_ev = len(re.findall(r"via 「", out_e))
    R.warn_check("M6 `--evidence -1` 被拒绝或按默认量返回（1..8 条）",
                 rc_e != 0 or 1 <= n_ev <= 8,
                 "exit=%s 返回证据 %d 条 —— 负值既未被拒绝、也未按默认量返回"
                 "（R1 基线表现为反向放大到全量；现表现为静默返回空）" % (rc_e, n_ev),
                 source="m6", todo=TODO)

    rc_c, out_c = C.run_tool(["search", "机器学习", "--expand", "yes", "--top", "3",
                              "--expand-cards", "-1"], timeout=240)
    m = re.search(r"近词扩展\s*\d+\s*个（(-?\d+)\s*张卡命中", out_c)
    scanned = int(m.group(1)) if m else None
    R.warn_check("M6 `--expand-cards -1` 被拒绝（扫描窗口不反转）",
                 rc_c != 0 or (scanned is not None and scanned >= 1),
                 "exit=%s 报告「%s 张卡命中」（负值把窗口静默放大，R1.1 的 200→50 收紧被抵消）" % (
                     rc_c, scanned), source="m6", todo=TODO)

    rc_s, out_s = C.run_tool(["search", "机器学习", "--top", "-1", "--expand", "no"], timeout=180)
    rows = len(re.findall(r"^\s*\d+\s+\S+\s+(kw|cls)\s", out_s, re.M))
    R.warn_check("M6 `search --top -1` 被拒绝（或不再静默截断到 1 行）",
                 rc_s != 0 or rows >= 2,
                 "exit=%s 输出命中行 %d 行（`--top -1` 会丢掉最后一行结果）" % (rc_s, rows),
                 source="m6", todo=TODO)


def build(R):
    nodes = C.load_nodes()
    part_d1(R, nodes)
    part_m2(R, nodes)
    part_f2(R, nodes)
    part_m6(R)


if __name__ == "__main__":
    sys.exit(C.main_guard(SUBCMD, "已修缺陷硬断言回归 + M6 预警（R2-E 升级）", build, C.SOURCES))
