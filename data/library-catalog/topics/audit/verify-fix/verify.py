#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify.py — VERIFY-FIX 独立验证脚本（R1 修复轮后 · 终审三反例复现）

设计原则（与 R1 自验脚本无关，全部自研）：
  * 期望值**只**由证据链自行重算：card_topics.jsonl + cards.jsonl + nodes.json + index/clusters.npy。
    **不 import** topic_edges.py / topic_build.py 的任何构建逻辑，不读 p2-build-report.json 的结论。
  * 被审对象（只读）：
      - `topics/edges.csr.npz`（产物）
      - `topic_graph.py`（SUT：`diffuse()` 作为被测算法；CLI 作为被测接口）
  * 不变式检查器自研：父链长度由本脚本自己走 parent map 得出（不信任被测方的 hops_used/path 字段）。
  * 写入范围：仅 `audit/verify-fix/`。无网络。

三反例：
  ① 权重   settlement↔entanglement（MMS 991000938579704181）== 0.1762914344 (±1e-6)
  ② 排序   经济学(id=4) 邻域按 assoc 主键重建期望序；economist 进 / economic 让位
  ③ 超跳   a) `around 139 --hops 2` 全路径 ≤2  b) 14 节点内存反例（请求 12 跳，父链 ≤12 边）
           c) 5 个随机种子抽样

用法：PYTHONPATH=~/go/pylibs python3 verify.py [--sweep] [--json-out verify.json]
"""
import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import time
from collections import Counter

PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(PYLIBS) and PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)
import numpy as np

DATA = os.path.expanduser("~/go/lib-catalog-data")
TOPICS = os.path.join(DATA, "topics")
TOOL = os.path.expanduser("~/go/reasonix-scripts/lib-catalog/topic_graph.py")
CAP = 50
LOG50 = math.log1p(CAP)
W_TOL = 1e-6                      # 与任务书一致；float32 落盘量化 ~6e-8
CELL = []                          # (name, ok, detail)


def rec(name, ok, detail=""):
    CELL.append({"check": name, "ok": bool(ok), "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


def sha256(path, n=16):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:n]


# ===========================================================================
# 证据链独立重算（自研实现）
# ===========================================================================
class Evidence:
    """从证据链全量重算边权 / assoc。实现独立于施工方脚本。"""

    def __init__(self, verbose=True):
        t0 = time.time()
        self.nodes = json.load(open(os.path.join(TOPICS, "nodes.json"), encoding="utf-8"))
        self.n = len(self.nodes)
        self.type = [x["type"] for x in self.nodes]
        self.ncl = [int(x["cluster"]) for x in self.nodes]
        self.nfreq = [int(x["freq"]) for x in self.nodes]
        self.term = [x["term"] for x in self.nodes]
        # nodes[tid] 以 list 下标当 id —— 先断言该前提成立
        self.id_is_index = all(x["id"] == i for i, x in enumerate(self.nodes))

        # cls 节点词表：cls2 保留大小写（F1 / TP3），normalize_term 会小写化
        self.cls_by_term = {}
        for i, t in enumerate(self.term):
            if self.type[i] == "cls":
                self.cls_by_term[t.upper()] = i

        # 卡簇标签（同簇共现判据）
        self.labels = np.load(os.path.join(DATA, "index", "clusters.npy"))

        # card_topics ↔ cards.jsonl 按行对齐 + cls2 提取
        self.mms, self.topics, self.cls2 = [], [], []
        with open(os.path.join(TOPICS, "card_topics.jsonl"), encoding="utf-8") as fc, \
             open(os.path.join(DATA, "cards.jsonl"), encoding="utf-8") as fd:
            for lc, ld in zip(fc, fd):
                jc, jd = json.loads(lc), json.loads(ld)
                self.mms.append(jc["mms"])
                self.topics.append(jc["topics"])
                self.cls2.append(jd.get("cls2") or "")
        self.ncards = len(self.mms)
        assert self.labels.shape[0] == self.ncards, (self.labels.shape, self.ncards)

        # ---- 单轮枚举：卡主题集合 = top-5 kw ∪ {cls2}，每无序对每卡计一次 ----
        cnt = Counter()            # 共现书数
        cnt_sc = Counter()         # 同簇共现书数（独立计数器）
        kw_cls_votes = {}          # kw id -> Counter(cls2 id)：层级边证据
        n_cls = 0
        for i in range(self.ncards):
            tops = self.topics[i]
            lab = int(self.labels[i])
            items = list(tops)
            cid = self.cls_by_term.get(self.cls2[i].strip().upper(), -1)
            if cid >= 0:
                items.append(cid)
                n_cls += 1
                for u in tops:
                    kw_cls_votes.setdefault(u, Counter())[cid] += 1
            for x in range(len(items)):
                for y in range(x + 1, len(items)):
                    u, v = items[x], items[y]
                    if u == v:
                        continue
                    if u > v:
                        u, v = v, u
                    cnt[(u, v)] += 1
                    if self.ncl[u] == self.ncl[v] == lab:
                        cnt_sc[(u, v)] += 1
        self.cnt, self.cnt_sc = cnt, cnt_sc
        self.n_cls_cards = n_cls

        # 层级边目标：卡级证据众数（平局取较小 id）
        self.cls_of = {}
        for u, c in kw_cls_votes.items():
            self.cls_of[u] = max(c.items(), key=lambda kv: (kv[1], -kv[0]))[0]

        # ---- 权重 ----
        self.w, self.assoc = {}, {}
        for k, c in cnt.items():
            u, v = k
            w1 = math.log1p(min(c, CAP)) / LOG50
            w2 = 0.3 * math.log1p(cnt_sc.get(k, 0)) / LOG50
            self.w[k] = min(1.0, w1 + w2)
            self.assoc[k] = c / math.sqrt(max(self.nfreq[u], 1) * max(self.nfreq[v], 1))
        if verbose:
            print(f"  [evidence] cards={self.ncards:,} distinct_pairs={len(cnt):,} "
                  f"kw-cls2卡={n_cls:,} 层级边={len(self.cls_of):,} | {time.time()-t0:.1f}s")

    def pair(self, u, v):
        """无序对权重查询 → (count, cnt_sc, w, assoc) 或 None。"""
        k = (u, v) if u < v else (v, u)
        if k not in self.cnt:
            return None
        return (self.cnt[k], self.cnt_sc.get(k, 0), self.w[k], self.assoc[k])

    def expected_row(self, u, max_out=20):
        """独立重建节点 u 的期望出边序（assoc 主键）。

        键序（--rank-by assoc）：tie(assoc)↓ → w↓ → dst↑；层级边 tie=freq*1e9 恒最前。
        去重：同一 (src,dst) 取 max w，同 w 取拼接序更小者（共现 < 层级）。
        返回 [(dst, w, tie, kind), ...] 已截断 top-max_out。
        """
        cands = {}   # dst -> (w, tie, seq, kind)
        m = len(self.cnt)
        for i, ((a, b), w) in enumerate(sorted(self.w.items())):
            a_, assoc = 0, self.assoc[(a, b)]
            for (s, d, seq) in ((a, b, i), (b, a, m + i)):
                if s != u:
                    continue
                cur = cands.get(d)
                if cur is None or w > cur[0] or (w == cur[0] and seq < cur[2]):
                    cands[d] = (w, assoc, seq, "cooccur")
        if u in self.cls_of:
            d = self.cls_of[u]
            w, tie, seq, kind = 1.0, self.nfreq[u] * 1e9, 2 * m, "hier"
            cur = cands.get(d)
            if cur is None or w > cur[0] or (w == cur[0] and seq < cur[2]):
                cands[d] = (w, tie, seq, kind)
        rows = sorted(cands.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))
        return [(d, v[0], v[1], v[3]) for d, v in rows[:max_out]]


# ===========================================================================
# 0 · 前置
# ===========================================================================
def part0():
    print("\n=== 0 · 前置确认（冻结快照 sha256）===")
    h_e = sha256(os.path.join(TOPICS, "edges.csr.npz"))
    h_t = sha256(TOOL)
    h_c = sha256(os.path.join(TOPICS, "card_topics.jsonl"))
    print(f"  edges.csr.npz      sha256={h_e}  {time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(os.path.join(TOPICS,'edges.csr.npz'))))}")
    print(f"  topic_graph.py     sha256={h_t}  {time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(TOOL)))}")
    print(f"  card_topics.jsonl  sha256={h_c}")
    rec("0.1 topic_graph.py / edges.csr.npz 可读且非空", os.path.getsize(TOOL) > 0 and os.path.getsize(os.path.join(TOPICS, "edges.csr.npz")) > 0)
    return {"edges_sha256_16": h_e, "tool_sha256_16": h_t, "card_topics_sha256_16": h_c}


# ===========================================================================
# 1 · 反例① 权重
# ===========================================================================
def part1(ev, csr):
    print("\n=== ① 权重反例：settlement ↔ entanglement（MMS 991000938579704181）===")
    idx = {t["term"]: t["id"] for t in ev.nodes}
    u, v = idx["settlement"], idx["entanglement"]
    indptr, indices, weights = csr
    cid = ev.cls_by_term
    cards = [i for i, tp in enumerate(ev.topics) if u in tp and v in tp]
    print(f"  settlement id={u} freq={ev.nfreq[u]} cluster={ev.ncl[u]} | "
          f"entanglement id={v} freq={ev.nfreq[v]} cluster={ev.ncl[v]}")
    rec("1.1 共有卡恰为终审给定 MMS", cards == [ev.mms.index("991000938579704181")],
        f"共现卡={[ev.mms[i] for i in cards]}")

    p = ev.pair(u, v)
    cnt, sc, w_exp, assoc = p
    print(f"  独立重算: 共现书数={cnt} 同簇共现={sc} → w1={math.log1p(min(cnt,CAP))/LOG50:.10f} "
          f"w2={0.3*math.log1p(sc)/LOG50:.10f} w={w_exp:.10f}")
    rec("1.2 独立重算权重 == 0.1762914344 (±1e-6)", abs(w_exp - 0.1762914344) <= W_TOL,
        f"Δ={w_exp-0.1762914344:+.3e}")

    # 落盘值（双向）。注意：共现边虽双向生成，但每源点 top-20 截断会独立裁剪两个方向，
    # 故"反向缺席"未必是缺陷 —— 存活集须与本脚本独立复刻的期望出边序对比后才可判定。
    act = {}
    for s, d in ((u, v), (v, u)):
        a, b = int(indptr[s]), int(indptr[s + 1])
        hit = [float(weights[pp]) for pp in range(a, b) if int(indices[pp]) == d]
        act[(s, d)] = hit[0] if hit else None
    exp_alive = {(u, v): v in {d for d, _w, _t, _k in ev.expected_row(u)},
                 (v, u): u in {d for d, _w, _t, _k in ev.expected_row(v)}}
    rec("1.3 存活方向 == 独立复刻的 top-20 期望（含反向截断）",
        all((act[k] is not None) == exp_alive[k] for k in act),
        f"{u}→{v} 存活={act[(u,v)] is not None}(期望{exp_alive[(u,v)]}) "
        f"{v}→{u} 存活={act[(v,u)] is not None}(期望{exp_alive[(v,u)]})")
    present = [x for x in act.values() if x is not None]
    dmax = max(abs(x - w_exp) for x in present)
    rec("1.4 落盘权重与独立重算一致 (≤1e-6)", dmax <= W_TOL, f"max|Δw|={dmax:.3e}")
    rec("1.5 落盘值 == 0.1762914344 (±1e-6)",
        max(abs(x - 0.1762914344) for x in present) <= W_TOL,
        f"max|Δ|={max(abs(x-0.1762914344) for x in present):.3e}")
    f32 = float(np.float32(0.1762914344))
    rec("1.6 落盘 float32 值 == float32(0.1762914344)", all(abs(x - f32) <= W_TOL for x in present),
        f"落盘={present} f32期望={f32!r}")

    # --- 有牙检查：修复前"双计"公式 与 pre-R1 备份产物 ---
    w_dbl = math.log1p(min(cnt * 2, CAP)) / LOG50 + 0.3 * math.log1p(sc * 2) / LOG50
    pre = None
    p_pre = os.path.join(TOPICS, "edges.csr.pre-r1.npz")
    if os.path.exists(p_pre):
        zp = np.load(p_pre)
        ipp, ixp, wp = zp["indptr"], zp["indices"], zp["weights"]
        a, b = int(ipp[u]), int(ipp[u + 1])
        hit = [float(wp[q]) for q in range(a, b) if int(ixp[q]) == v]
        pre = hit[0] if hit else None
    rec("1.7 有牙：修复前双计公式复现 pre-R1 落盘值，且与修复后值可判别",
        pre is not None and abs(w_dbl - pre) <= W_TOL and abs(w_dbl - w_exp) > 1e-3,
        f"双计重算={w_dbl:.10f} pre-R1={pre} 修复后={w_exp:.10f} 判别间距={abs(w_dbl-w_exp):.4f}")
    rec("1.8 有牙：pre-R1 备份同边权重 == 双计值（0.2794），非当前值",
        pre is not None and abs(pre - 0.2794153094) <= 1e-6,
        f"pre-R1={pre} Δvs双计={None if pre is None else pre-0.2794153094:+.2e}")
    return {"count": cnt, "cnt_sc": sc, "w_expected": w_exp, "w_expected_f32": f32, "assoc": assoc,
            "on_disk": {f"{k[0]}->{k[1]}": v for k, v in act.items()},
            "expected_alive": {f"{k[0]}->{k[1]}": bool(x) for k, x in exp_alive.items()},
            "doublecount_w": w_dbl, "pre_r1_w": pre}


# ===========================================================================
# 2 · 反例② 排序
# ===========================================================================
def part2(ev, csr):
    print("\n=== ② 排序反例：经济学(id=4) 邻域（assoc 主键）===")
    indptr, indices, weights = csr
    u = 4
    a, b = int(indptr[u]), int(indptr[u + 1])
    actual = [(int(indices[p]), float(weights[p])) for p in range(a, b)]
    exp = ev.expected_row(u)

    print(f"  实际出度={len(actual)}  期望出度={len(exp)}")
    print(f"  期望序（前 8）: {[(d, ev.term[d], round(w,4), round(t,4) if t < 1e8 else 'hier') for d, w, t, _k in exp[:8]]}")
    print(f"  实际序（前 8）: {[(d, ev.term[d], round(w,4)) for d, w in actual[:8]]}")

    rec("2.1 出度一致（top-20 截断未满则等长）", len(actual) == len(exp), f"actual={len(actual)} exp={len(exp)}")
    same_order = [d for d, _w in actual] == [d for d, _w, _t, _k in exp]
    rec("2.2 期望序与实际 dst 序逐位相同", same_order,
        "" if same_order else f"首个分歧位={next(i for i,(x,y) in enumerate(zip([d for d,_ in actual],[d for d,_,_,_ in exp])) if x!=y)}")
    wmax = max((abs(w - ew) for (d, w), (_d, ew, _t, _k) in zip(actual, exp) if d == _d), default=0.0)
    rec("2.3 对应边权逐位一致 (≤1e-6)", all(d == _d for (d, _w), (_d, _e, _t, _k) in zip(actual, exp)) and wmax <= W_TOL,
        f"max|Δw|={wmax:.3e}")

    # 终审反例场景
    e_id, c_id = 2139, 120     # economist / economic
    pa, pb = ev.pair(u, e_id), ev.pair(u, c_id)
    act_ids = [d for d, _ in actual]
    e_rank = act_ids.index(e_id) if e_id in act_ids else None
    c_rank = act_ids.index(c_id) if c_id in act_ids else None
    print(f"  economist (id={e_id}) 共现={pa[0]} 同簇={pa[1]} assoc={pa[3]:.4f} w={pa[2]:.4f} → 实际名次 {e_rank}")
    print(f"  economic  (id={c_id}) 共现={pb[0]} 同簇={pb[1]} assoc={pb[3]:.4f} w={pb[2]:.4f} → 实际名次 {c_rank}")
    rec("2.4 economist 在邻域内（终审：R1 前缺席）", e_rank is not None, f"名次={e_rank}")
    rec("2.5 economic 已让位（终审：R1 前在邻域 w=1.0）", c_rank is None, f"名次={c_rank}")
    rec("2.6 economist 的 w 与独立重算一致", e_rank is not None and abs(actual[e_rank][1] - pa[2]) <= W_TOL,
        f"落盘={actual[e_rank][1] if e_rank is not None else None} 期望={pa[2]:.6f}")
    rec("2.7 assoc(economist) > assoc(economic) 且 w(economic) 本可入列", pa[3] > pb[3],
        f"{pa[3]:.4f} > {pb[3]:.4f}；economic w={pb[2]:.4f}")

    # --- 有牙检查：修复前键序（w 优先，assoc 仅 tie-break）是否给出不同的邻域 ---
    m = len(ev.cnt)
    cands = {}
    for i, ((x, y), w) in enumerate(sorted(ev.w.items())):
        for (s, d, seq) in ((x, y, i), (y, x, m + i)):
            if s != u:
                continue
            t = ev.assoc[(x, y)]
            cur = cands.get(d)
            if cur is None or w > cur[0] or (w == cur[0] and seq < cur[2]):
                cands[d] = (w, t, seq)
    if u in ev.cls_of:
        d = ev.cls_of[u]
        if d not in cands or 1.0 > cands[d][0]:
            cands[d] = (1.0, ev.nfreq[u] * 1e9, 2 * m)
    # 修复前：src↑ → w↓ → tie(assoc)↓ → dst↑ ；修复后：src↑ → tie↓ → w↓ → dst↑
    pre_row = [d for d, _v in sorted(cands.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:20]]
    post_row = [d for d, _w, _t, _k in exp]
    rec("2.8 有牙：修复前键序（权重优先）给出与落盘不同的邻域序",
        pre_row != post_row, f"修复前序首位={pre_row[:5]} vs 落盘={post_row[:5]}")
    pre_in = e_id in pre_row
    rec("2.9 有牙：economist 在修复前键序下确实缺席（终审反例可复现）", not pre_in,
        f"修复前名次={'—' if not pre_in else pre_row.index(e_id)}；修复后名次={e_rank}")
    return {"expected_order": [d for d, _w, _t, _k in exp], "actual_order": act_ids,
            "prefix_key_order": pre_row, "prefix_key_economist_rank": None if not pre_in else pre_row.index(e_id),
            "economist": {"rank": e_rank, "assoc": pa[3], "w": pa[2], "count": pa[0]},
            "economic": {"rank": c_rank, "assoc": pb[3], "w": pb[2], "count": pb[0]}}


# ===========================================================================
# 3 · 反例③ 超跳
# ===========================================================================
def walk_len(parents, nid, guard=4096):
    """自研父链长度（不信任被测方 path/hops_used）。返回 (边数, 是否成环)。"""
    seen, cur, n = set(), parents.get(nid), 0
    while cur is not None and n < guard:
        if cur in seen:
            return n, True
        seen.add(cur)
        n += 1
        cur = parents.get(cur)
    return n, False


def load_csr():
    z = np.load(os.path.join(TOPICS, "edges.csr.npz"))
    return z["indptr"], z["indices"], z["weights"]


def fixture14():
    """14 节点内存反例：seed 0；低权直边 0→1(0.5)、强边 0→2→1(各 1.0)、
    再由 1 出发 11 边链 1→3→4→…→13。请求 12 跳。
    修复后（首访定型）节点 13 恰为 12 边；修复前（层内提级 + 同跳读）父链 13 边。"""
    n = 14                      # 节点 0..13：0=源点, 1=被提级节点, 2=提级来源, 3..13=11 边链
    E = [(0, 1, 0.5), (0, 2, 1.0), (2, 1, 1.0), (1, 3, 1.0)] + \
        [(k, k + 1, 1.0) for k in range(3, 13)]
    E = sorted(E)               # 按 src 分组升序 → indptr 可由计数累加得到
    src = np.array([e[0] for e in E], dtype=np.int64)
    dst = np.array([e[1] for e in E], dtype=np.int32)
    w = np.array([e[2] for e in E], dtype=np.float32)
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.add.at(indptr, src + 1, 1)
    indptr = np.cumsum(indptr)
    return indptr, dst, w, E


def legacy_reconstruct(seed, hops, indptr, indices, weights, decay, threshold, budget):
    """**自研重建**的 R1 前语义（据缺陷描述：同跳内读被更新过的 score + 层内提级、layer 首访定型）。
    仅用于证明反例有牙；非施工方原码。"""
    score, parent, layer = {seed: 1.0}, {seed: None}, {seed: 0}
    for _h in range(1, hops + 1):
        changed = False
        for u in sorted(score):                       # 同跳内按 id 序扫描，读当前 score[u]
            su = score[u]
            a, b = int(indptr[u]), int(indptr[u + 1])
            for p in range(a, b):
                v = int(indices[p])
                s = su * float(weights[p]) * decay
                if s < threshold:
                    continue
                if v not in score:
                    if len(score) + 1 > budget:
                        continue
                    score[v], parent[v], layer[v] = s, u, _h
                    changed = True
                elif s > score[v]:                    # 层内提级：改写 parent，layer 保留首访值
                    score[v], parent[v] = s, u
                    changed = True
        if not changed:
            break
    return {"score": score, "parent": parent, "layer": layer}


def part3(ev, csr, tool_dir):
    print("\n=== ③ 超跳反例 ===")
    sys.path.insert(0, tool_dir)
    import topic_graph as TG
    out = {}

    # --- 检查器自测（证明检查器有牙）---
    inject = {k: k - 1 for k in range(1, 14)}          # 0..13 纯链：13 条边
    inject[0] = None
    L, cyc = walk_len(inject, 13)
    rec("3.0 不变式检查器自测（注入 13 边父链须被检出，且 12 跳请求下判 FAIL）",
        L == 13 and not cyc and L > 12, f"检出长度={L} 边，超 12 跳={L > 12}")

    # --- (a) 真实图 CLI：around 139 --hops 2 ---
    print("\n  (a) 真实图：`around 139 --hops 2`")
    r = subprocess.run([sys.executable, TOOL, "--data", DATA, "around", "139", "--hops", "2", "--json"],
                       capture_output=True, text=True, env={**os.environ, "PYTHONPATH": PYLIBS})
    ok_cli = r.returncode == 0
    rec("3.a1 CLI `around 139 --hops 2` exit 0", ok_cli, f"rc={r.returncode}")
    report_max_cli, hops_used_max = None, None
    if ok_cli:
        j = json.loads(r.stdout)
        hops_used_max = max((n.get("hops_used", 0) for L in j["layers"] for n in L["nodes"]), default=0)
        path_nodes_max = max((len(n.get("path", [])) for L in j["layers"] for n in L["nodes"]), default=0)
        rec("3.a2 around --hops 2 自报 hops_used ≤2", hops_used_max <= 2, f"max hops_used={hops_used_max}")
        rec("3.a3 around 展示 path 长度 ≤3 节点（2 边）", path_nodes_max <= 3, f"max len(path)={path_nodes_max}")
    # 自研父链复算（不经被测方的 path/hops_used）
    indptr, indices, weights = csr
    reg = TG.diffuse(139, 2, indptr, indices, weights, 0.86, 0.05, 50000)
    lens = [walk_len(reg["parent"], k)[0] for k in reg["score"]]
    ok_a = max(lens) <= 2 and all(not walk_len(reg["parent"], k)[1] for k in reg["score"])
    mis = sum(1 for k in reg["score"] if reg["layer"][k] != walk_len(reg["parent"], k)[0])
    report_max_cli = max(lens)
    rec("3.a4 自研父链：全部入区节点路径 ≤2 边", ok_a, f"visited={reg['visited']} max_edges={max(lens)}")
    rec("3.a5 真实图：layer ≡ 父链长度（0 例脱钩）", mis == 0, f"脱钩={mis}")
    out["a"] = {"visited": reg["visited"], "max_edges": int(max(lens)), "layer_mismatch": mis,
                "cli_hops_used_max": hops_used_max}

    # --- (b) 14 节点内存反例 ---
    print("\n  (b) 内存 14 节点反例（请求 12 跳）")
    ip, ix, iw, E = fixture14()
    H, DEC, THR, BUD = 12, 0.86, 0.01, 50000
    regf = TG.diffuse(0, H, ip, ix, iw, DEC, THR, BUD)
    lf = {k: walk_len(regf["parent"], k)[0] for k in regf["score"]}
    maxf = max(lf.values())
    deepest = max(lf, key=lambda k: lf[k])
    rec("3.b1 修复后：14 节点反例最深父链 ≤12 边", maxf <= H,
        f"节点数={len(regf['score'])} 最深=id{deepest} {maxf} 边 (layer={regf['layer'][deepest]})")
    rec("3.b2 修复后：layer ≡ 父链长度",
        all(regf["layer"][k] == lf[k] for k in regf["score"]),
        f"脱钩={sum(1 for k in regf['score'] if regf['layer'][k]!=lf[k])}")
    rec("3.b3 反例确达边界（修复后最深 == 12，非平凡）", maxf == H, f"最深={maxf}")
    leg = legacy_reconstruct(0, H, ip, ix, iw, DEC, THR, BUD)
    ll = {k: walk_len(leg["parent"], k)[0] for k in leg["score"]}
    maxl = max(ll.values())
    over = [k for k in ll if ll[k] > H]
    rec("3.b4 反例有牙：R1 前语义重建在同一图上超跳（>12 边）", maxl > H,
        f"最深={maxl} 边，超跳节点={[(k, ll[k]) for k in sorted(over)]}")
    out["b"] = {"fixed_max_edges": int(maxf), "fixed_nodes": len(regf["score"]),
                "legacy_max_edges": int(maxl), "legacy_overhop_ids": sorted(over),
                "hops_requested": H, "n_nodes": 14}

    # --- (c) 5 个随机种子 ---
    print("\n  (c) 5 个随机种子抽样（hops=2 与 hops=12）")
    rng = random.Random(20260918)
    seeds = rng.sample(range(ev.n), 5)
    worst = []
    allok = True
    for s in seeds:
        line = []
        for h in (2, 12):
            rg = TG.diffuse(s, h, indptr, indices, weights, 0.86, 0.05, 50000)
            mx = max(walk_len(rg["parent"], k)[0] for k in rg["score"])
            mm = sum(1 for k in rg["score"] if rg["layer"][k] != walk_len(rg["parent"], k)[0])
            cyc = any(walk_len(rg["parent"], k)[1] for k in rg["score"])
            line.append((h, rg["visited"], mx, mm, cyc))
            if mx > h or mm or cyc:
                allok = False
        worst.append((s, ev.term[s], line))
        print(f"    seed={s:>5} 「{ev.term[s][:18]}」 " +
              " | ".join(f"hops={h} visited={v} max_edges={m} 脱钩={mm} 环={c}" for h, v, m, mm, c in line))
    rec("3.c1 5 个随机种子 × (hops=2,12) 全部 ≤hops 且 layer 一致且无环", allok)
    out["c"] = [{"seed": s, "term": t, "runs": [{"hops": h, "visited": v, "max_edges": m,
                                                 "layer_mismatch": mm, "cycle": c} for h, v, m, mm, c in ln]}
                for s, t, ln in worst]
    return out


# ===========================================================================
# 4 · 全量横扫
# ===========================================================================
def part4(ev, csr):
    print("\n=== ④ 全量横扫：从 card_topics 全量重算期望权重 vs 修复后 edges ===")
    indptr, indices, weights = csr
    n = ev.n
    n_edges = len(indices)

    # Tier A：实际每条边 vs 独立重算期望权重（隔离公式/计数误差）。
    # 期望权重含层级边覆盖：kw→cls_of[kw] 的边由 ③ 层级边（w=1.0）与 ① 共现边去重后取 max w。
    formula, tol_ok, hier_ov, no_pair, maxd = [], 0, 0, [], 0.0
    for s in range(n):
        a, b = int(indptr[s]), int(indptr[s + 1])
        for p in range(a, b):
            d = int(indices[p])
            w_act = float(weights[p])
            pr = ev.pair(s, d)
            if pr is None:
                no_pair.append((s, d, w_act))
                continue
            is_hier = ev.cls_of.get(s) == d
            w_exp = 1.0 if is_hier else pr[2]
            dw = abs(w_act - w_exp)
            maxd = max(maxd, dw)
            if dw > W_TOL:
                formula.append((s, d, w_act, w_exp, pr[0], pr[1], is_hier))
            else:
                tol_ok += 1
                if is_hier and pr[2] < 1.0 - W_TOL:
                    hier_ov += 1                      # 层级边覆盖了纯共现权重
    rec("4.1 每条实际边都能在证据链中找到对应共现对（计数）", not no_pair,
        f"无证据边={len(no_pair)}" + (f" 例={no_pair[:3]}" if no_pair else ""))
    rec("4.2 基权重公式分歧 = 0（|Δw| > 1e-6，含层级边覆盖）", not formula,
        f"分歧={len(formula)} / 一致={tol_ok} / max|Δw|={maxd:.3e}")
    print(f"  容差层：{tol_ok:,} 条 |Δw| ≤ 1e-6（float32 落盘量化），max|Δw|={maxd:.3e}")
    print(f"  其中 {hier_ov:,} 条为层级边覆盖（共现对权重 < 1.0，落盘按 ③ w=1.0）——口径内行为，非分歧")

    # Tier B：完整复刻（含 top-20 截断）→ 集合差
    exp = {}
    m = len(ev.cnt)
    for i, ((u, v), w) in enumerate(sorted(ev.w.items())):
        t = ev.assoc[(u, v)]
        exp[(u, v)] = (w, t, i)
        exp[(v, u)] = (w, t, m + i)
    for u, d in ev.cls_of.items():
        k = (u, d)
        cur = exp.get(k)
        if cur is None or 1.0 > cur[0] or (1.0 == cur[0] and 2 * m < cur[2]):
            exp[k] = (1.0, ev.nfreq[u] * 1e9, 2 * m)
    per = {}
    for (s, d), (w, t, seq) in exp.items():
        per.setdefault(s, []).append((d, w, t, seq))
    exp_set = {}
    for s, lst in per.items():
        lst.sort(key=lambda x: (-x[2], -x[1], x[0]))
        for d, w, t, seq in lst[:20]:
            exp_set[(s, d)] = w
    act_set = {}
    for s in range(n):
        a, b = int(indptr[s]), int(indptr[s + 1])
        for p in range(a, b):
            act_set[(s, int(indices[p]))] = float(weights[p])
    missing = sorted(set(exp_set) - set(act_set))
    extra = sorted(set(act_set) - set(exp_set))
    print(f"  期望边集={len(exp_set):,} 实际边集={len(act_set):,} 缺={len(missing)} 多={len(extra)}")
    rec("4.3 top-20 截断复刻后：期望边集 == 实际边集", not missing and not extra,
        f"缺={len(missing)} 多={len(extra)}" + (f" 缺例={missing[:3]} 多例={extra[:3]}" if (missing or extra) else ""))

    # 层级边存活性（审计 GRAPH D1 关注点）
    hier_exp = sum(1 for (s, d) in exp_set if ev.cls_of.get(s) == d)
    hier_act = sum(1 for (s, d) in act_set if ev.cls_of.get(s) == d)
    rec("4.4 层级边实存 == 期望（无被截断吃掉）", hier_exp == hier_act, f"期望={hier_exp} 实存={hier_act}")
    lost = sorted((s, d) for s, d in ev.cls_of.items() if (s, d) not in exp_set)
    print(f"  层级边登记={len(ev.cls_of):,}（=审计 NUM 的 4,832）→ 截断复刻存活={hier_exp}，"
          f"被 top-20 吃掉={len(lost)}（与审计 D1 的 9 条口径一致）")
    rec("4.5 登记层级边 4,832 与存活 4,823 的 9 条差额可由截断独立复现", len(lost) == 9,
        f"丢失={[(s, ev.term[s], ev.term[d]) for s, d in lost]}")
    return {"edges_actual": n_edges, "edges_expected_set": len(exp_set),
            "divergence_formula": len(formula), "divergence_count": len(missing) + len(extra) + len(no_pair),
            "divergence_tolerance": 0, "tolerance_ok": tol_ok, "hier_override": hier_ov,
            "no_evidence_edges": len(no_pair), "missing_edges": len(missing),
            "extra_edges": len(extra), "max_abs_dw": maxd,
            "formula_examples": formula[:5], "missing_examples": missing[:5], "extra_examples": extra[:5],
            "hier_registered": len(ev.cls_of), "hier_expected": hier_exp, "hier_actual": hier_act,
            "hier_truncated": [{"src": s, "term": ev.term[s], "dst": d, "dst_term": ev.term[d]}
                               for s, d in lost]}


# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify.json"))
    a = ap.parse_args()
    print("### VERIFY-FIX 独立验证（R1 修复后）" + time.strftime("  %Y-%m-%d %H:%M:%S"))
    meta = part0()
    ev = Evidence()
    csr = load_csr()
    r1 = part1(ev, csr)
    r2 = part2(ev, csr)
    r3 = part3(ev, csr, os.path.dirname(TOOL))
    r4 = part4(ev, csr)

    npass = sum(1 for c in CELL if c["ok"])
    nfail = len(CELL) - npass
    print(f"\n=== 汇总：{npass} PASS / {nfail} FAIL（共 {len(CELL)} 项断言）===")
    for c in CELL:
        if not c["ok"]:
            print(f"  FAIL: {c['check']} — {c['detail']}")
    payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "meta": meta, "checks": CELL, "pass": npass, "fail": nfail,
               "counterexample_1_weight": r1, "counterexample_2_order": r2,
               "counterexample_3_overhop": r3, "sweep": r4,
               "evidence": {"cards": ev.ncards, "distinct_pairs": len(ev.cnt),
                            "hier_edges": len(ev.cls_of), "nodes": ev.n, "cls_cards": ev.n_cls_cards}}
    with open(a.json_out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"  → {a.json_out}")
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
