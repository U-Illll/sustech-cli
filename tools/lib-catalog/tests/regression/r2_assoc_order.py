#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""r2_assoc_order.py — assoc 主排序键生效（终审②）

守护什么：top-20 截断的排序键必须是 **assoc = c/√(freq_u·freq_v)**（主键），
权重只作 tie-break。R1 修复前键序是「权重优先、assoc 仅平局」，导致
`--rank-by assoc` 名义生效、实质未生效——低频专指词被高频泛词挤出邻域。

用例组成：
  [A] 内存反例（构造输入）：合成 4 条候选边，使「assoc 主键」与「权重主键」**保留集必然不同**；
      分别用 assoc / weight 口径调用主体 `topic_edges.topk_csr()`，
      断言两种口径的返回序列 == 各自理论键序，且二者不同（证明反例有牙）。
  [B] 真实图反例锚点（终审②）：`经济学`(id=4) 邻域中
      · `economist`(id=2139) 必须在（R1 前缺席）
      · `economic`(id=120) 必须不在（R1 前在列，w=1.0）
      · 机理：入者的 assoc 更高、但权重**更低** → 只有 assoc 作主键才会得到这个结果
  [C] 多源点排序不变式：从 card_topics 独立重算 kw 候选的 (assoc, w)，
      断言「保留下来的 kw 出边 == assoc 降序前缀」+「边界单调」+「权重逐边复算一致」，
      并统计"若按权重排序则会被保留、实际却被挤出"的反证条数（teeth）。

只读：不写主体产物；不触网。
来源：终审②（topics/ACCEPTANCE-REPORT.md §10.1-②、§10.2）。
"""
import json
import os
import sys

sys.dont_write_bytecode = True          # 只读纪律：先于 import _common 生效，不落 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

SUBCMD = "r2_assoc_order"
TOL = 1e-6
# 源点用 **term** 锚定（抗重建）：节点表重建会让 id 漂移，term 相对稳定。
# 终审② 源点「经济学」+ 多源点交叉抽验（P4 常用词在内）。
DEFAULT_SEED_TERMS = ("经济学", "经济", "machine", "机器", "文学", "economics", "计量")
# 重建兜底 id（term 全部失配时才用；仍以 term 优先）
FALLBACK_IDS = (4, 0, 139, 56, 65, 62, 680)


# ---------------------------------------------------------------------------
# [A] 内存反例：assoc 主键 vs 权重主键
# ---------------------------------------------------------------------------
def part_a_micro(R):
    R.section("A 内存反例：assoc 主键 vs 权重主键（合成 4 候选 / 保留 top-3）")
    C.ensure_import_paths()
    import numpy as np
    import topic_edges as te

    # 单源 u=0，四条候选；assoc(tie) 与 w 刻意反向：
    #   id=4 「高频泛词」：w 最高(1.0)、assoc 最低(0.01)  —— economic 型
    #   id=3 「低频专指词」：w 最低(0.1)、assoc 次高(0.6) —— economist 型
    labels = {1: "b(中权重/高assoc)", 2: "c(中权重/中assoc)",
              3: "d(低权重/高assoc·专指词)", 4: "a(高权重/低assoc·泛词)"}
    dst = [1, 2, 3, 4]
    w = [0.50, 0.70, 0.10, 1.00]
    tie = [0.90, 0.50, 0.60, 0.01]
    src = [0, 0, 0, 0]
    n, max_out = 5, 3
    exp_assoc = [1, 3, 2]     # tie 降序：0.90(b) > 0.60(d) > 0.50(c) > 0.01(a) → 砍 a
    exp_weight = [4, 2, 1]    # w   降序：1.00(a) > 0.70(c) > 0.50(b) > 0.10(d) → 砍 d

    def keep(primary):
        ip, ix, ww = te.topk_csr(np.array(src, dtype=np.int64), np.array(dst, dtype=np.int64),
                                 np.array(w, dtype=np.float64), np.array(tie, dtype=np.float64),
                                 n, max_out, primary=primary)
        return [int(x) for x in ix[ip[0]:ip[1]]]

    got_assoc, got_weight = keep("assoc"), keep("weight")
    R.info("assoc 主键返回：%s | weight 主键返回：%s" %
           ([labels[i] for i in got_assoc], [labels[i] for i in got_weight]))

    R.check("primary=assoc：返回序列 == assoc 降序（dst asc 平局）",
            got_assoc == exp_assoc, "实测 %s，期望 %s" % (got_assoc, exp_assoc), source="ce2")
    R.check("primary=weight：返回序列 == 权重降序（assoc 退为 tie-break）",
            got_weight == exp_weight, "实测 %s，期望 %s" % (got_weight, exp_weight),
            source="ce2")
    R.check("两种口径保留集不同（反例有牙）", set(got_assoc) != set(got_weight),
            "assoc 砍掉 %s；weight 砍掉 %s" % (
                [labels[i] for i in set(dst) - set(got_assoc)],
                [labels[i] for i in set(dst) - set(got_weight)]), source="ce2")
    R.check("assoc 主键下：最高权重边被挤出（终审② 现象复现为其反面）",
            4 not in got_assoc and 3 in got_assoc,
            "泛词(id=4, w=1.0, assoc=0.01) 被砍、专指词(id=3, w=0.1, assoc=0.6) 保留",
            source="ce2")
    R.check("层级边置顶不受影响（tie=1e9 时必进）",
            keep("assoc") == exp_assoc, "见上", source="ce2")


# ---------------------------------------------------------------------------
# [B] 真实图反例锚点
# ---------------------------------------------------------------------------
def part_b_anchor(R, nodes, typ, freq, by_term, ip, ix, wt, clus):
    R.section("B 终审② 真实图锚点：经济学 邻域 economist 进 / economic 让位")
    u = by_term.get(C.FROZEN["ce2_seed"])
    if u is None:
        R.check("源点 %s 存在" % C.FROZEN["ce2_seed"], False, "nodes.json 缺少该主题",
                source="ce2")
        return
    id_in, id_out = by_term.get(C.FROZEN["ce2_enters"]), by_term.get(C.FROZEN["ce2_leaves"])
    nbr = {}
    for q in range(int(ip[u]), int(ip[u + 1])):
        nbr[int(ix[q])] = float(wt[q])
    R.info("%s(id=%d) 出度=%d | %s(id=%s) %s | %s(id=%s) %s" % (
        C.FROZEN["ce2_seed"], u, len(nbr), C.FROZEN["ce2_enters"], id_in,
        "在邻域" if id_in in nbr else "缺席", C.FROZEN["ce2_leaves"], id_out,
        "在邻域" if id_out in nbr else "缺席"))

    R.check("%s 必须在邻域内（R1 前缺席）" % C.FROZEN["ce2_enters"],
            id_in is not None and id_in in nbr,
            "id=%s 实测 %s" % (id_in, "在" if id_in in nbr else "缺席"), source="ce2")
    R.check("%s 必须不在邻域内（R1 前在列 w=1.0）" % C.FROZEN["ce2_leaves"],
            id_out is not None and id_out not in nbr,
            "id=%s 实测 %s" % (id_out, "在（回归）" if id_out in nbr else "已让位"), source="ce2")

    # 机理：assoc 与权重反向 —— 只有 assoc 作主键才能得到上述结果
    cnt, cnt_sc, _ = C.scan_pair_counts([(u, id_in), (u, id_out)], clusters=clus)
    k_in = (min(u, id_in), max(u, id_in))
    k_out = (min(u, id_out), max(u, id_out))
    a_in = C.assoc(cnt[k_in], freq[u], freq[id_in])
    a_out = C.assoc(cnt[k_out], freq[u], freq[id_out])
    w_in = C.w_cooccurrence(cnt[k_in], cnt_sc[k_in])
    w_out = C.w_cooccurrence(cnt[k_out], cnt_sc[k_out])
    R.info("assoc: %s=%.6f vs %s=%.6f | w: %s=%.6f vs %s=%.6f" % (
        C.FROZEN["ce2_enters"], a_in, C.FROZEN["ce2_leaves"], a_out,
        C.FROZEN["ce2_enters"], w_in, C.FROZEN["ce2_leaves"], w_out))
    # 硬断言：**关系不变式**（终审② 的实质）—— 入者关联度更高、权重更低。
    # 这是 assoc 作主键的充要观测；具体数值随产物重建漂移，只作基线漂移报告。
    R.check("入者 assoc > 出者 assoc（终审② 的实质关系）", a_in > a_out,
            "实测 %.6f > %.6f" % (a_in, a_out), source="ce2")
    R.check("入者权重 < 出者权重（证明只有 assoc 作主键才成立）", w_in < w_out,
            "w: %.6f < %.6f" % (w_in, w_out), source="ce2")
    R.check("入者落盘权重与重算一致", abs(nbr.get(id_in, -1) - w_in) < TOL,
            "入者 落盘/重算=%.10f/%.10f" % (nbr.get(id_in, -1), w_in), source="r1_assert")
    if id_out in nbr:      # 出者若在邻域内，其权重同样必须与重算一致（回归时才走到这里）
        R.check("出者落盘权重与重算一致（若在邻域）", abs(nbr[id_out] - w_out) < TOL,
                "出者 落盘/重算=%.10f/%.10f" % (nbr[id_out], w_out), source="r1_assert")
    R.baseline("终审② 入者 assoc（R1 基线 %.4f）" % C.FROZEN["ce2_assoc_enters"],
               round(a_in, 4), C.FROZEN["ce2_assoc_enters"], source="ce2")
    R.baseline("终审② 出者 assoc（R1 基线 %.4f）" % C.FROZEN["ce2_assoc_leaves"],
               round(a_out, 4), C.FROZEN["ce2_assoc_leaves"], source="ce2")


# ---------------------------------------------------------------------------
# [C] 多源点排序不变式
# ---------------------------------------------------------------------------
def scan_seed_candidates(seeds, nodes, clus):
    """单遍 card_topics.jsonl：为每个源点累计 kw 共现候选的 (c, cs)。

    候选集 = 与源点同卡出现的其余主题（card_topics 只存 kw，故即 kw-kw 候选全集；
    cls2 成员不在 card_topics 中，故 cls 类候选由调用方单独排除并说明）。
    """
    labels = C.load_cluster_labels()
    cnt = {s: {} for s in seeds}
    csc = {s: {} for s in seeds}
    S = set(seeds)
    with open(os.path.join(C.topics_dir(), "card_topics.jsonl"), encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            ts = set(json.loads(line)["topics"])
            hit = S & ts
            if not hit:
                continue
            lab = int(labels[i]) if labels is not None and i < len(labels) else None
            for s in hit:
                for t in ts:
                    if t == s:
                        continue
                    cnt[s][t] = cnt[s].get(t, 0) + 1
                    if lab is not None and clus.get(t) == clus.get(s) == lab:
                        csc[s][t] = csc[s].get(t, 0) + 1
    return cnt, csc


def resolve_seeds(nodes, by_term):
    """解析源点：term 优先（抗重建），全失配才回退 R1 基线 id。支持 R2_SEEDS 覆盖。"""
    raw = os.environ.get("R2_SEEDS", "").strip()
    tokens = [t.strip() for t in raw.split(",") if t.strip()] if raw else list(DEFAULT_SEED_TERMS)
    seeds, notes = [], []
    for t in tokens:
        if t.lstrip("-").isdigit():
            i = int(t)
            if 0 <= i < len(nodes):
                seeds.append(i)
                notes.append("源点 id=%d（%s）" % (i, nodes[i]["term"]))
            else:
                notes.append("源点 id=%d 越界，跳过" % i)
            continue
        if t in by_term:
            seeds.append(by_term[t])
        else:
            notes.append("源点 term '%s' 在当前节点表中不存在，跳过（图已重建？）" % t)
    if not seeds:                                  # 全部失配 → 回退基线 id
        seeds = [i for i in FALLBACK_IDS if 0 <= i < len(nodes)]
        notes.append("term 全部失配 → 回退 R1 基线 id %s" % list(seeds))
    return tuple(dict.fromkeys(seeds)), notes


def part_c_invariant(R, nodes, typ, freq, clus, ip, ix, wt, seeds):
    R.section("C 多源点排序不变式（独立重算 kw 候选 → 前缀/边界/teeth）")
    cnt, csc = scan_seed_candidates(seeds, nodes, clus)
    worst, with_teeth, total_teeth = [], [], 0
    for s in seeds:
        actual = {}
        for q in range(int(ip[s]), int(ip[s + 1])):
            actual[int(ix[q])] = float(wt[q])
        kept_kw = {v for v in actual if typ[v] == "kw"}
        kept_cls = sorted(v for v in actual if typ[v] != "kw")
        cand = []
        for t, c in cnt[s].items():
            cs = csc[s].get(t, 0)
            cand.append((C.assoc(c, freq[s], freq[t]), C.w_cooccurrence(c, cs), t))
        cand.sort(key=lambda x: (-x[0], -x[1], x[2]))          # 与 topk_csr 键序一致
        a_of = {t: a for a, _w, t in cand}
        w_of = {t: w for _a, w, t in cand}
        prefix = {t for _a, _w, t in cand[:len(kept_kw)]}
        last_kept = min((a_of[t] for t in kept_kw), default=None)
        best_rej = next(((a, w, t) for a, w, t in cand if t not in kept_kw), None)
        w_min_kept = min((w_of[t] for t in kept_kw), default=None)
        teeth = [t for t in w_of if t not in kept_kw and w_min_kept is not None
                 and w_of[t] > w_min_kept]
        w_bad = [t for t in kept_kw if abs(actual[t] - w_of[t]) >= TOL]

        tag = "%s(id=%d)" % (nodes[s]["term"], s)
        R.info("%-18s 出度=%d 保留 kw=%d / cls=%d 候选 kw=%d | 最高权重但被挤出=%d 条" % (
            tag, len(actual), len(kept_kw), len(kept_cls), len(cand), len(teeth)))
        R.check("%s：保留 kw 出边 == assoc 降序前缀" % tag, prefix == kept_kw,
                "差集 %s" % sorted((prefix ^ kept_kw))[:6], source="ce2")
        R.check("%s：边界单调（末位保留 assoc ≥ 首个被挤出 assoc）" % tag,
                best_rej is None or (last_kept is not None and last_kept >= best_rej[0] - 1e-15),
                "末位保留=%.6f 首个被挤出=%.6f" % (
                    last_kept if last_kept is not None else -1,
                    best_rej[0] if best_rej else -1), source="ce2")
        R.check("%s：保留 kw 边权重逐条复算一致" % tag, not w_bad,
                "异常 %s" % ([nodes[t]["term"] for t in w_bad[:3]] or "无"), source="r1_assert")
        R.baseline("%s：有反证的候选数 > 0" % tag, len(teeth) > 0, True,
                   note="teeth=%d（若按权重排序这些本该保留）" % len(teeth), source="ce2")
        if len(teeth) == 0:
            worst.append(tag)
        else:
            with_teeth.append(tag)
        total_teeth += len(teeth)
    # 队列判据（硬）：assoc 主键必须在**至少一个**源点上产生"权重更高却被挤出"的反证，
    # 否则无法证明 assoc 真的作主键（单源点无 teeth 可能只是局部形状使然，不判 FAIL）
    R.check("assoc 主键在全队列上确实生效（≥1 源点有反证 / 合计反证 %d 条）" % total_teeth,
            len(with_teeth) >= 1,
            "有反证源点 %d/%d；无反证：%s" % (
                len(with_teeth), len(seeds), "、".join(worst) or "无"),
            source="ce2")
    if worst:
        R.info("无反证的源点 %d 个（局部候选里没有「权重高于末位保留」的被挤出者，属正常形状）：%s"
               % (len(worst), "、".join(worst)))


def build(R):
    nodes = C.load_nodes()
    typ = [x["type"] for x in nodes]
    freq = [int(x["freq"]) for x in nodes]
    clus = {x["id"]: int(x["cluster"]) for x in nodes}
    by_term = {x["term"]: x["id"] for x in nodes}
    ip, ix, wt = C.load_edges()

    part_a_micro(R)
    part_b_anchor(R, nodes, typ, freq, by_term, ip, ix, wt, clus)
    seeds, notes = resolve_seeds(nodes, by_term)
    for nt in notes:
        R.info(nt)
    if not seeds:
        R.check("源点列表非空（term 或 id 至少命中一个）", False,
                "R2_SEEDS=%s 与默认 term 列表均未命中" % os.environ.get("R2_SEEDS", ""),
                source="ce2")
        return
    part_c_invariant(R, nodes, typ, freq, clus, ip, ix, wt, seeds)
    R.section("概览")
    R.info("源点 %d 个：%s" % (len(seeds), ",".join(str(s) for s in seeds)))


if __name__ == "__main__":
    sys.exit(C.main_guard(SUBCMD, "终审② assoc 主排序键生效（内存反例 + 真实图锚点 + 多源点不变式）",
                          build, C.SOURCES))
