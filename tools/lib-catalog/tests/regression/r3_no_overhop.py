#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""r3_no_overhop.py — 扩散不超跳（终审③）

守护什么：加权扩散返回的**任何**节点的父链边数必须 ≤ `--hops`，且
`layer[v] ≡ 父链边数 ≡ 真实路径长度`、`score[v] ≡ Π(路径边权) × decay^layer`。
R1 修复前的实现在同一跳内直接读被本跳更新过的 `score[u]`，并允许层内提级改写
parent/layer，于是可返回 **超过 hops 的路径**（终审实测：请求 12 跳返回 13 边）。

用例组成：
  [1] 内存反例图（终审③ 最小复现图：A/B 两条 11 跳链 + 层内边 + 末端节点，
      请求 12 跳）：BUGGY 必须超跳（证明反例有牙）→ FIXED 必须 ≤12 边
  [2] 另三张内存图的不变式：层内提级(low→high 重新入列)、同跳平局、菱形取最大
  [3] 真实图 `around 139 --hops 1/2/3/12`：最深父链 ≤ hops、超跳计数 0、
      layer ≡ path_len、分数一致性（A3-c）逐点复算

只读：`topic_graph.diffuse()` 以 import 方式调用（`sys.dont_write_bytecode=True`，不落 __pycache__）。
来源：终审③（topics/ACCEPTANCE-REPORT.md §10.1-③、§10.2）。
"""
import os
import sys

sys.dont_write_bytecode = True          # 只读纪律：先于 import _common 生效，不落 __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

SUBCMD = "r3_no_overhop"
DECAY, THRESHOLD, BUDGET = C.DECAY_DEFAULT, C.THRESHOLD_DEFAULT, C.BUDGET_DEFAULT
REAL_TERM, REAL_FALLBACK = "machine", 139     # P4 验收与审计 final-rerun 同款源点（term 锚定，抗重建）


# ---------------------------------------------------------------------------
# R1 修复前的 diffuse 实现快照（冻结缺陷，仅用于证明"反例有牙"）
# ---------------------------------------------------------------------------
def diffuse_pre_r1(seed, hops, indptr, indices, weights, decay, threshold, budget):
    """R1 修复③ 之前的实现（同跳读被更新过的 score + 允许层内提级改写 layer/parent）。

    保留它不是为了使用，而是为了让反例**可证伪**：若这段代码不再超跳，
    说明反例图已失效，必须换更狠的反例图，而不是让用例静默通过。
    """
    score = {seed: 1.0}
    parent = {seed: None}
    layer = {seed: 0}
    frontier = [seed]
    visited = 1
    for _h in range(1, hops + 1):
        nxt = []
        for u in frontier:
            su = score[u]                       # ← 缺陷：读的是"本跳可能已被更新"的分数
            for p in range(int(indptr[u]), int(indptr[u + 1])):
                v = int(indices[p])
                sv = su * float(weights[p]) * decay
                if sv < threshold:
                    continue
                if sv > score.get(v, 0.0):      # ← 缺陷：已入区节点可被提级改写
                    if v not in score:
                        visited += 1
                        if visited > budget:
                            return {"score": score, "parent": parent, "layer": layer,
                                    "visited": visited, "saturated": True}
                    score[v] = sv
                    parent[v] = u
                    layer[v] = _h
                    nxt.append(v)
        if not nxt:
            break
        frontier = nxt
    return {"score": score, "parent": parent, "layer": layer,
            "visited": visited, "saturated": False}


def my_path_len(region, x, guard=999):
    """独立实现：父链边数（不依赖主体 path_len，便于两源交叉校验）。"""
    n, cur = 0, region["parent"].get(x)
    while cur is not None and n < guard:
        n += 1
        cur = region["parent"].get(cur)
    return n


def path_weight(region, x, wmap):
    """沿父链累乘边权；缺边返回 None（用于分数一致性断言）。"""
    prod, cur = 1.0, x
    while True:
        p = region["parent"].get(cur)
        if p is None:
            return prod
        w = wmap.get((p, cur))
        if w is None:
            return None
        prod *= w
        cur = p


# ---------------------------------------------------------------------------
# 内存图夹具
# ---------------------------------------------------------------------------
def build_csr(n, edges):
    """纯 Python CSR 构造（diffuse 只要求可索引 + int()/float()）。"""
    ix, wt = [], []
    ip = [0] * (n + 1)
    for u in range(n):
        for a, b, w in edges:
            if a == u:
                ix.append(b)
                wt.append(w)
        ip[u + 1] = len(ix)
    return ip, ix, wt, {(a, b): w for a, b, w in edges}


def fx_ab_chain():
    """终审③ 最小复现图：A/B 两条 11 跳链 + a11→b11 + b11→z（请求 12 跳 → 修复前 13 边）。"""
    nch, a_w, b_w = 11, 1.0, 0.95
    a = list(range(1, 1 + nch))
    b = list(range(1 + nch, 1 + 2 * nch))
    z = 1 + 2 * nch
    E = [(0, a[0], a_w)] + [(a[i], a[i + 1], a_w) for i in range(nch - 1)]
    E += [(0, b[0], b_w)] + [(b[i], b[i + 1], b_w) for i in range(nch - 1)]
    E += [(a[-1], b[-1], 1.0), (b[-1], z, 1.0)]
    return "终审③ A/B 11 跳链反例图", z + 1, E


def fx_promote_reentry():
    """层内提级图：a 在 1 跳以低分入区，2 跳时 b→a 给出更高分（修复前会提级改写 → 链条整体外移）。"""
    tail = list(range(4, 14))          # c=3 → d..l（10 个节点，10 条边）
    E = [(0, 1, 0.10), (0, 2, 1.00), (2, 1, 1.00), (1, 3, 1.00)]
    E += [(tail[i], tail[i + 1], 1.00) for i in range(len(tail) - 1)]
    return "层内提级反例图（low→high 重新入列）", 14, E


def fx_tie_same_hop():
    """同跳平局图：3 由 1 与 2 同分竞争 → 平局按父 id 升序（确定性）。"""
    E = [(0, 1, 0.9), (0, 2, 0.9), (1, 3, 1.0), (2, 3, 1.0), (3, 4, 1.0), (4, 5, 1.0)]
    return "同跳平局图（确定性 tie-break）", 6, E


def fx_diamond_max():
    """菱形图：同跳多父取分数最大者（2 的路径分高于 1）。"""
    E = [(0, 1, 0.5), (0, 2, 1.0), (1, 3, 1.0), (2, 3, 1.0), (3, 4, 1.0), (4, 5, 1.0)]
    return "菱形图（同跳取最大）", 6, E


FIXTURES = [fx_ab_chain, fx_promote_reentry, fx_tie_same_hop, fx_diamond_max]


def check_invariants(R, name, n, edges, hops, teeth_required):
    """对单个夹具 × 单个 hops 断言四条不变式；返回 (buggy_max, fixed_max)。"""
    import topic_graph as tg
    ip, ix, wt, wmap = build_csr(n, edges)
    buggy = diffuse_pre_r1(0, hops, ip, ix, wt, DECAY, THRESHOLD, BUDGET)
    fixed = tg.diffuse(0, hops, ip, ix, wt, DECAY, THRESHOLD, BUDGET)

    buggy_max = max((my_path_len(buggy, v) for v in buggy["score"]), default=0)
    over = sorted(v for v in fixed["score"] if v != 0 and my_path_len(fixed, v) > hops)
    maxp = max((my_path_len(fixed, v) for v in fixed["score"]), default=0)
    tag = "%s @hops=%d" % (name, hops)

    R.check("%s：无超跳（最深父链 %d ≤ %d）" % (tag, maxp, hops), not over,
            "超跳节点 %s" % over[:6], source="ce3")
    bad_layer = [v for v in fixed["layer"]
                 if fixed["layer"][v] != my_path_len(fixed, v)]
    R.check("%s：layer ≡ 父链边数（strict layering）" % tag, not bad_layer,
            "不一致 %s" % [(v, fixed["layer"][v], my_path_len(fixed, v)) for v in bad_layer[:4]],
            source="ce3")
    bad_score = []
    for v in fixed["score"]:
        pw = path_weight(fixed, v, wmap)
        if pw is None:
            bad_score.append((v, "缺边"))
            continue
        exp = pw * (DECAY ** fixed["layer"][v])
        if abs(fixed["score"][v] - exp) > 1e-9:
            bad_score.append((v, fixed["score"][v], exp))
    R.check("%s：score ≡ Π(路径边权)×decay^layer" % tag, not bad_score,
            "偏差 %s" % bad_score[:3], source="ce3")
    R.check("%s：区域节点数 ≤ 预算 %d" % (tag, BUDGET), fixed["visited"] <= BUDGET,
            "visited=%d" % fixed["visited"], source="ce3")
    R.check("%s：主体 path_len 与独立实现一致" % tag,
            all(tg.path_len(v, fixed) == my_path_len(fixed, v) for v in fixed["score"]),
            "两源交叉校验", source="ce3")

    if teeth_required:
        R.check("%s：反例有牙（修复前实现超跳 %d > %d）" % (tag, buggy_max, hops),
                buggy_max > hops, "BUGGY 最深=%d / FIXED 最深=%d" % (buggy_max, maxp),
                source="ce3")
    else:
        R.info("%s：BUGGY 最深=%d / FIXED 最深=%d%s" % (
            tag, buggy_max, maxp, "（BUGGY 亦超跳，反例同样有牙）" if buggy_max > hops else ""))
    return buggy_max, maxp


def build(R):
    C.ensure_import_paths()      # 主体工具链（topic_graph）与 pylibs 必须在 sys.path 上
    R.section("1 终审③ 冻结反例：A/B 11 跳链（请求 12 跳：BUGGY 13 边 / FIXED ≤12 边）")
    name, n, edges = fx_ab_chain()
    buggy_max, fixed_max = check_invariants(R, name, n, edges, C.HOPS_MAX, teeth_required=True)
    R.check("冻结对照：BUGGY=%d / FIXED=%d（终审记录 %d / %d）" % (
        buggy_max, fixed_max, C.FROZEN["ce3_buggy_maxpath"], C.FROZEN["ce3_fixed_maxpath"]),
        buggy_max == C.FROZEN["ce3_buggy_maxpath"] and fixed_max == C.FROZEN["ce3_fixed_maxpath"],
        "实测 BUGGY=%d FIXED=%d" % (buggy_max, fixed_max), source="ce3")

    R.section("2 另三张内存图的不变式（提级 / 平局 / 菱形取最大）")
    for fx in (fx_promote_reentry, fx_tie_same_hop, fx_diamond_max):
        nm, nn, ed = fx()
        for hops in (1, 2, 3, 12):
            check_invariants(R, nm, nn, ed, hops, teeth_required=False)

    # 定向语义断言（比不变式更锐利）
    import topic_graph as tg
    nm, nn, ed = fx_tie_same_hop()
    ip, ix, wt, _wm = build_csr(nn, ed)
    reg = tg.diffuse(0, 2, ip, ix, wt, DECAY, THRESHOLD, BUDGET)
    R.check("同跳平局：parent[3] == 1（父 id 升序 tie-break）", reg["parent"].get(3) == 1,
            "实测 parent[3]=%s" % reg["parent"].get(3), source="ce3")
    nm, nn, ed = fx_diamond_max()
    ip, ix, wt, _wm = build_csr(nn, ed)
    reg = tg.diffuse(0, 2, ip, ix, wt, DECAY, THRESHOLD, BUDGET)
    R.check("菱形取最大：parent[3] == 2（高分路径胜出）", reg["parent"].get(3) == 2,
            "实测 parent[3]=%s" % reg["parent"].get(3), source="ce3")
    nm, nn, ed = fx_promote_reentry()
    ip, ix, wt, _wm = build_csr(nn, ed)
    reg = tg.diffuse(0, 3, ip, ix, wt, DECAY, THRESHOLD, BUDGET)
    R.check("首访定型：a(id=1) 仍属 layer=1 / parent=0（未被 2 跳高分提级）",
            reg["layer"].get(1) == 1 and reg["parent"].get(1) == 0,
            "实测 layer[1]=%s parent[1]=%s" % (reg["layer"].get(1), reg["parent"].get(1)),
            source="ce3")

    # ---- [3] 真实图 ----
    R.section("3 真实图 around 139 hops=1/2/3/12")
    try:
        import topic_graph as tg
        rnodes = C.load_nodes()
        ip, ix, wt = C.load_edges()
    except C.DataMissing as e:
        R.skip("真实图超跳抽验", str(e))
        return
    seed, note = C.resolve_term(rnodes, REAL_TERM, REAL_FALLBACK)
    if seed is None:
        R.skip("真实图超跳抽验", note)
        return
    R.info("真实图源点：%s(id=%d)%s" % (rnodes[seed]["term"], seed,
                                      ("（%s）" % note) if note else ""))
    for hops in (1, 2, 3, C.HOPS_MAX):
        reg = tg.diffuse(seed, hops, ip, ix, wt, DECAY, THRESHOLD, BUDGET)
        wmap = {}
        for u in reg["score"]:
            for q in range(int(ip[u]), int(ip[u + 1])):
                v = int(ix[q])
                if v in reg["score"]:
                    wmap.setdefault((u, v), float(wt[q]))
        maxp = max((my_path_len(reg, v) for v in reg["score"]), default=0)
        over = sum(1 for v in reg["score"] if v != seed and my_path_len(reg, v) > hops)
        bad_layer = sum(1 for v in reg["layer"] if reg["layer"][v] != my_path_len(reg, v))
        bad_score = 0
        worst = 0.0
        for v in reg["score"]:
            pw = path_weight(reg, v, wmap)
            if pw is None:
                bad_score += 1
                continue
            exp = pw * (DECAY ** reg["layer"][v])
            d = abs(reg["score"][v] - exp)
            worst = max(worst, d)
            if d > 1e-9:
                bad_score += 1
        R.info("hops=%-2d 区域=%-5d 最深父链=%d 超跳=%d layer不一致=%d 分数偏差最大=%.2e" % (
            hops, reg["visited"], maxp, over, bad_layer, worst))
        R.check("真实图 hops=%d：最深父链 %d ≤ %d" % (hops, maxp, hops), maxp <= hops,
                "超跳 %d 个" % over, source="ce3")
        R.check("真实图 hops=%d：超跳计数为 0" % hops, over == 0, "over=%d" % over, source="ce3")
        R.check("真实图 hops=%d：layer ≡ 父链边数" % hops, bad_layer == 0,
                "不一致 %d 个" % bad_layer, source="ce3")
        if hops == 3:
            R.check("真实图 hops=3：分数一致性（A3-c，%d 点）" % len(reg["score"]),
                    bad_score == 0, "不一致 %d 个（最大偏差 %.2e）" % (bad_score, worst),
                    source="ce3")


if __name__ == "__main__":
    sys.exit(C.main_guard(SUBCMD, "终审③ 扩散不超跳（内存反例 + 真实图）", build, C.SOURCES))
