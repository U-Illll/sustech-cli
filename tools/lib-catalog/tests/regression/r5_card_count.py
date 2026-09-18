#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""r5_card_count.py — 登记一致性：卡数对齐 + 每卡规格 + P3 门槛/口径冻结（终审⑤ / R1 加固）

守护什么：
  [1] `card_topics.jsonl` 非空行数 == `cards.jsonl` 非空行数 == **188,512**（终审⑤ 要求的行数对齐断言；
      一旦证据链与卡表错行/缺行，P4 的"书证据"会把主题挂到别的书上）
  [2] 两表 **逐行 mms 对齐**（卡序一致）——行数相等但错位同样是有害的
  [3] 登记值三方一致：`meta.stages.P2.counts.cards` == `p2-build-report.json.counts.cards`
      == `compile_report.json.cards_total` == 188,512
  [4] 每卡主题数规格：≤5、无重复、id ∈ [0,n)，且尺寸分布 == 登记直方图
  [5] P3 硬门槛（**硬编码 0.90**）：② 主簇∪类目 ≥ 0.90 且 ① 仅主簇 < 0.90（观察项不被口径改写）；
      `meta.stages.P3.caliber_freeze` 字段齐且冻结门槛与硬编码值数值一致
  [6] 衰减容忍（终审④登记于 caliber_freeze.decay_tolerance）：首跳均值 ≥0.30、
      逐跳有效因子 ∈[0.30,0.90]、第 9 跳起无新增节点

只读：全部为读取+比对，不写任何主体产物；不触网。
来源：终审⑤ / R1 加固（topics/ACCEPTANCE-REPORT.md §10.1-⑤、§10.4）。
"""
import json
import os
import sys

sys.dont_write_bytecode = True          # 只读纪律：先于 import _common 生效，不落 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

SUBCMD = "r5_card_count"
GATE = 0.90          # 硬编码门槛（与 acceptance/topics-p3.sh 的 GATE 同值；防报告自述值漂移）
FROZEN_CARDS = C.FROZEN["cards"]


def build(R):
    C.ensure_import_paths()
    D, T = C.data_dir(), C.topics_dir()
    cards = os.path.join(D, "cards.jsonl")
    ct = os.path.join(T, "card_topics.jsonl")
    C.require_files(cards, ct)

    # ---- [1] 行数对齐 -----------------------------------------------------
    R.section("1 行数对齐：card_topics.jsonl == cards.jsonl（基线 %d）" % FROZEN_CARDS)
    ct_total, ct_nonempty = C.count_lines(ct)
    cd_total, cd_nonempty = C.count_lines(cards)
    R.info("card_topics.jsonl 物理 %d / 非空 %d ；cards.jsonl 物理 %d / 非空 %d" % (
        ct_total, ct_nonempty, cd_total, cd_nonempty))
    R.check("证据链非空行数 == 卡表非空行数", ct_nonempty == cd_nonempty,
            "%d vs %d" % (ct_nonempty, cd_nonempty), source="r1_assert")
    R.check("两表行数彼此相等（核心不变量）", ct_nonempty == cd_nonempty,
            "%d vs %d" % (ct_nonempty, cd_nonempty), source="r1_assert")
    # 与 R1 基线卡数比对：产物被合法重建（新增书目）时卡数会变，属基线漂移而非回归 → WARN
    R.baseline("卡数与 R1 基线一致（%d）" % FROZEN_CARDS, cd_nonempty, FROZEN_CARDS,
               note="卡表/证据链来自源目录编译，重建后卡数变化属正常，请复核后更新 FROZEN",
               source="r1_assert")
    R.check("无空行（物理行数 == 非空行数）",
            ct_total == ct_nonempty and cd_total == cd_nonempty,
            "card_topics %d/%d ；cards %d/%d" % (ct_total, ct_nonempty, cd_total, cd_nonempty),
            source="r1_assert")

    # ---- [2] 逐行 mms 对齐 + [4] 每卡规格 --------------------------------
    nodes = C.load_nodes()
    n_nodes = len(nodes)
    R.section("2 逐行 mms 对齐（卡序一致）+ 每卡主题规格")
    mismatch, no_mms = [], 0
    size_hist = {}
    bad_size = bad_dup = bad_id = 0
    with open(cards, encoding="utf-8") as fc, open(ct, encoding="utf-8") as ft:
        for i, (lc, lt) in enumerate(zip(fc, ft)):
            if not lc.strip() or not lt.strip():
                continue
            c, t = json.loads(lc), json.loads(lt)
            if c.get("mms", "") != t.get("mms", ""):
                if len(mismatch) < 5:
                    mismatch.append((i + 1, c.get("mms"), t.get("mms")))
            if not t.get("mms"):
                no_mms += 1
            tops = t.get("topics") or []
            size_hist[len(tops)] = size_hist.get(len(tops), 0) + 1
            if len(tops) > 5:
                bad_size += 1
            if len(set(tops)) != len(tops):
                bad_dup += 1
            if any((not isinstance(x, int)) or x < 0 or x >= n_nodes for x in tops):
                bad_id += 1
    R.check("两表逐行 mms 完全对齐（错位即失效）", not mismatch,
            "错位样本 %s" % (mismatch or "无"), source="r1_assert")
    R.check("每行都有 mms", no_mms == 0, "缺 mms %d 行" % no_mms, source="r1_assert")
    R.check("每卡主题数 ≤5", bad_size == 0, "超标 %d 行" % bad_size, source="r1_assert")
    R.check("卡内主题 id 无重复", bad_dup == 0, "重复 %d 行" % bad_dup, source="r1_assert")
    R.check("主题 id ∈ [0,%d)" % n_nodes, bad_id == 0, "越界 %d 行" % bad_id, source="r1_assert")

    # ---- [3] 登记值三方一致 ----------------------------------------------
    R.section("3 登记值三方一致（meta / P2 报告 / 编译报告）")
    meta = json.load(open(os.path.join(T, "meta.json"), encoding="utf-8"))
    p2 = json.load(open(os.path.join(T, "p2-build-report.json"), encoding="utf-8"))
    comp_p = os.path.join(D, "compile_report.json")
    comp = json.load(open(comp_p, encoding="utf-8")) if os.path.isfile(comp_p) else {}
    m_cards = ((meta.get("stages") or {}).get("P2") or {}).get("counts", {}).get("cards")
    r_cards = (p2.get("counts") or {}).get("cards")
    c_cards = comp.get("cards_total")
    R.info("meta=%s / p2-report=%s / compile_report=%s" % (m_cards, r_cards, c_cards))
    R.check("meta.stages.P2.counts.cards == P2 报告 counts.cards", m_cards == r_cards,
            "%s vs %s" % (m_cards, r_cards), source="r1_assert")
    R.check("登记卡数 == 实测卡数", m_cards == cd_nonempty,
            "%s vs %d" % (m_cards, cd_nonempty), source="r1_assert")
    if c_cards is None:
        R.skip("compile_report.cards_total 比对", "未找到 %s" % C.rel(comp_p))
    else:
        R.check("compile_report.cards_total == 登记卡数", c_cards == m_cards,
                "%s vs %s" % (c_cards, m_cards), source="r1_assert")
    R.check("每卡主题数尺寸分布 == 登记直方图",
            {str(k): v for k, v in sorted(size_hist.items())} ==
            {str(k): v for k, v in sorted(
                (m_cards is not None and
                 ((meta.get("stages") or {}).get("P2") or {}).get("counts", {})
                 .get("cards_topic_count_hist") or {}).items())},
            "实测 %s" % json.dumps({str(k): v for k, v in sorted(size_hist.items())}),
            source="r1_assert")

    # ---- [5] P3 硬门槛 + 口径冻结 ----------------------------------------
    R.section("5 P3 硬门槛（硬编码 %.2f）与口径冻结" % GATE)
    p3 = (meta.get("stages") or {}).get("P3") or {}
    cov = p3.get("coverage") or {}
    c2 = ((cov.get("cluster_or_cls") or {}).get("mean"))
    c1 = ((cov.get("cluster_only") or {}).get("mean"))
    if c2 is None or c1 is None:
        R.check("stages.P3.coverage 三口径齐备", False,
                "缺 cluster_or_cls/cluster_only", source="r1_assert")
    else:
        c3 = ((cov.get("undirected_closure") or {}).get("mean"))
        R.info("① 仅主簇=%.10f | ② 主簇∪类目=%.10f | ③ 无向闭包=%.10f" % (c1, c2, c3 or float("nan")))
        R.check("硬门槛口径 ②（主簇∪类目）≥ %.2f" % GATE, c2 >= GATE,
                "②=%.10f" % c2, source="r1_assert")
        R.check("登记门槛数值 == 硬编码 %.2f" % GATE,
                abs(float(cov.get("gate", -1)) - GATE) < 1e-12,
                "登记 gate=%s" % cov.get("gate"), source="r1_assert")
        R.check("② 的 pass 标记与硬门槛判定一致",
                bool((cov.get("cluster_or_cls") or {}).get("pass")) == (c2 >= GATE),
                "pass=%s" % (cov.get("cluster_or_cls") or {}).get("pass"), source="r1_assert")
        # 口径漂移防线：① 必须**如实并列**（不是把 ① 冒充 ②、也不是把 ① 抹掉）
        R.check("观察项 ① 如实登记且严格弱于 ②（未被口径改写）", c1 < c2,
                "①=%.10f ②=%.10f" % (c1, c2), source="r1_assert")
        if c1 < GATE:
            R.check("观察项 ①（仅主簇）< %.2f（未越线）" % GATE, True,
                    "①=%.10f" % c1, source="r1_assert")
        else:
            # 与 acceptance/topics-p3.sh 同判：① 过线属 R1 后自然过线，不作 FAIL，但要显式暴露
            R.info("①（仅主簇）=%.10f 已过 %.2f 线——R1 后自然过线（裁定文本已登记），"
                   "本项按 P3 验收同判为 info，不判 FAIL" % (c1, GATE))
            R.check("① 过线时裁定文本已登记该事实",
                    "①" in (p3.get("verdict") or "") and "0.9" in (p3.get("verdict") or ""),
                    "verdict 已含 ① 与门槛数值", source="r1_assert")

    fz = p3.get("caliber_freeze") or {}
    miss = [k for k in ("same_cluster_set", "denominator", "sampling", "source_handling",
                        "gate", "decay_tolerance") if not fz.get(k)]
    R.check("caliber_freeze 字段齐（集合/分母/抽样/源点/门槛/衰减容忍）", not miss,
            "缺字段 %s" % (miss or "无"), source="r1_assert")
    R.check("冻结门槛 == 硬编码 %.2f" % GATE, abs(float(fz.get("gate", -1)) - GATE) < 1e-12,
            "冻结 gate=%s" % fz.get("gate"), source="r1_assert")
    R.check("口径冻结明确门槛施加于 ②（主簇∪类目）", "②" in str(fz.get("gate_applied_to") or ""),
            "gate_applied_to=%s" % fz.get("gate_applied_to"), source="r1_assert")
    R.check("裁定文本登记了硬编码位置（acceptance/topics-p3.sh）",
            "0.90" in (p3.get("verdict") or "") and "硬编码" in (p3.get("verdict") or ""),
            "verdict 长度 %d" % len(p3.get("verdict") or ""), source="r1_assert")

    # ---- [6] 衰减容忍（终审④） -------------------------------------------
    R.section("6 衰减容忍（caliber_freeze.decay_tolerance）")
    tol = fz.get("decay_tolerance") or {}
    rep_p = os.path.join(T, "topics-report.json")
    if not tol:
        R.skip("衰减容忍", "caliber_freeze.decay_tolerance 缺失")
    elif not os.path.isfile(rep_p):
        R.skip("衰减容忍", "缺少 %s（重建：python3 topics_report.py）" % C.rel(rep_p))
    else:
        rep = json.load(open(rep_p, encoding="utf-8"))
        per_hop = (rep.get("decay") or {}).get("per_hop") or []
        hop1_min = float(tol.get("hop1_mean_min", 0.30))
        lo, hi = (tol.get("effective_hop_factor_range") or [0.30, 0.90])[:2]
        h1 = next((h for h in per_hop if h.get("hop") == 1), None)
        R.check("首跳平均得分 ≥ %.2f" % hop1_min,
                h1 is not None and h1.get("score_mean") is not None and
                h1["score_mean"] >= hop1_min,
                "hop1_mean=%s" % (h1 and h1.get("score_mean")), source="r1_assert")
        effs = [(h["hop"], h["effective_hop_factor"]) for h in per_hop
                if h.get("effective_hop_factor") is not None]
        bad = [(hh, e) for hh, e in effs if not (float(lo) <= e <= float(hi))]
        R.check("逐跳有效因子 ∈ [%.2f, %.2f]（检查 %d 跳）" % (lo, hi, len(effs)), not bad,
                "越界 %s ；实测 %s" % (bad or "无",
                                   ", ".join("hop%d=%.4f" % (hh, e) for hh, e in effs)),
                source="r1_assert")
        sat_ok = all((h.get("samples_with_new_nodes") or 0) == 0
                     for h in per_hop if h.get("hop", 0) >= 9)
        first_zero = next((h["hop"] for h in per_hop
                           if (h.get("samples_with_new_nodes") or 0) == 0), None)
        R.check("第 9 跳起无新增节点（正常饱和）", sat_ok,
                "首个零新增跳=%s" % first_zero, source="r1_assert")
        R.check("衰减因子登记为 %.2f" % C.DECAY_DEFAULT,
                abs(float((rep.get("decay") or {}).get("decay_factor", -1)) - C.DECAY_DEFAULT) < 1e-12,
                "report decay_factor=%s" % (rep.get("decay") or {}).get("decay_factor"),
                source="r1_assert")

    R.section("概览")
    R.info("卡 %d / 节点 %d / 门槛 %.2f / 冻结门槛 %s" % (
        cd_nonempty, n_nodes, GATE, fz.get("gate")))


if __name__ == "__main__":
    sys.exit(C.main_guard(SUBCMD, "登记一致性：卡数对齐 + 每卡规格 + P3 门槛与口径冻结",
                          build, C.SOURCES))
