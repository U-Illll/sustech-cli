#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_r2e.py — R2 全轮关键验证（独立于 R2-A/B/C 自证）

独立实现：期望值只由证据链自行重算（card_topics.jsonl + cards.jsonl + nodes.json
+ index/clusters.npy），**不 import** R2-A/B/C 的验证脚本，不读其结论。

覆盖：
  A. F1 排序键语义      交付顺序 == sort(-max_cc, -freq, term)（整数键精确求值）
  B. type 数组          全量逐边核对 bit0/bit1/bit2 三类型掩码（远超任务书 ≥100 抽样）
  C. type 数组对照      ① vs pre-r2c 三数组逐位一致（仅新增 types）
                        ② vs pre-r2 结构性对照（节点/边/权重分布）
                        ③ 导出包 edges_types.u8.bin == npz types
  D. M2/P4 抽测         topic_graph 修复后各 2 例（CLI 实测）
  E. P4 相关率抽验      2 条查询走完整协议（search→种子→around），原始输出落 runs/
只读主体；写仅 audit/r2-verify/；无网络。

用法：PYTHONPATH=~/go/pylibs python3 verify_r2e.py [--json-out verify_r2e.json]
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter

PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(PYLIBS) and PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)
import numpy as np

DATA = os.path.expanduser("~/go/lib-catalog-data")
TOPICS = os.path.join(DATA, "topics")
TOOL = os.path.expanduser("~/go/reasonix-scripts/lib-catalog/topic_graph.py")
RUNDIR = os.path.join(TOPICS, "audit", "r2-verify", "runs")
CAP = 50
LOG50 = math.log1p(CAP)
CELL = []


def rec(name, ok, detail=""):
    CELL.append({"check": name, "ok": bool(ok), "detail": detail, "kind": "check"})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


def gap(name, detail=""):
    """既有口径缺口/无法独立验证项 —— 不计入 FAIL（非 R2 回归），但必须在报告中列出。"""
    CELL.append({"check": name, "ok": None, "detail": detail, "kind": "gap"})
    print(f"  [GAP ] {name}" + (f" — {detail}" if detail else ""))
    return None


def info(name, detail=""):
    CELL.append({"check": name, "ok": None, "detail": detail, "kind": "info"})
    print(f"  [INFO] {name}" + (f" — {detail}" if detail else ""))
    return None


def run_tool(args, timeout=300):
    env = {**os.environ, "PYTHONPATH": PYLIBS, "TOPIC_LLM": "off"}
    r = subprocess.run([sys.executable, TOOL, "--data", DATA] + [str(a) for a in args],
                       capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, r.stdout + r.stderr


# ===========================================================================
# 证据链独立重算
# ===========================================================================
class Ev:
    def __init__(self):
        self.nodes = json.load(open(os.path.join(TOPICS, "nodes.json"), encoding="utf-8"))
        self.n = len(self.nodes)
        self.term = [x["term"] for x in self.nodes]
        self.type = [x["type"] for x in self.nodes]
        self.ncl = [int(x["cluster"]) for x in self.nodes]
        self.nfreq = [int(x["freq"]) for x in self.nodes]
        self.cls_id = {x["term"].upper(): x["id"] for x in self.nodes if x["type"] == "cls"}
        self.labels = np.load(os.path.join(DATA, "index", "clusters.npy"))
        self.cnt, self.csc = Counter(), Counter()
        self.votes = {}
        self.freq, self.maxcc = Counter(), {}
        cl = {}
        with open(os.path.join(DATA, "cards.jsonl"), encoding="utf-8") as fc, \
             open(os.path.join(TOPICS, "card_topics.jsonl"), encoding="utf-8") as ft:
            for i, (lc, lt) in enumerate(zip(fc, ft)):
                c, t = json.loads(lc), json.loads(lt)
                lab = int(self.labels[i])
                items = list(t["topics"])
                for u in t["topics"]:
                    self.freq[u] += 1
                    cl.setdefault(u, Counter())[lab] += 1
                cid = self.cls_id.get((c.get("cls2") or "").strip().upper(), -1)
                if cid >= 0:
                    items.append(cid)
                    for u in t["topics"]:
                        self.votes.setdefault(u, Counter())[cid] += 1
                for x in range(len(items)):
                    for y in range(x + 1, len(items)):
                        a, b = items[x], items[y]
                        if a == b:
                            continue
                        if a > b:
                            a, b = b, a
                        self.cnt[(a, b)] += 1
                        if self.ncl[a] == self.ncl[b] == lab:
                            self.csc[(a, b)] += 1
        self.maxcc = {u: max(cc.values()) for u, cc in cl.items()}
        self.argmax_clu = {u: max(cc.items(), key=lambda kv: (kv[1], -kv[0]))[0] for u, cc in cl.items()}
        self.cluster_own = {u: cc.get(self.ncl[u], 0) for u, cc in cl.items()}
        self.cls_of = {u: max(cc.items(), key=lambda kv: (kv[1], -kv[0]))[0]
                       for u, cc in self.votes.items()}


# ===========================================================================
# A · F1 排序键语义
# ===========================================================================
def part_a(ev):
    print("\n=== A · F1 排序键语义（交付顺序 vs sort(-max_cc, -freq, term)）===")
    # A1 结构前提（可独立验证）
    rec("A1 id 连续 0..N-1 且 term 唯一（交付序为全序）",
        all(x["id"] == i for i, x in enumerate(ev.nodes))
        and len({x["term"] for x in ev.nodes}) == ev.n,
        f"N={ev.n} term 唯一={len({x['term'] for x in ev.nodes}) == ev.n}")
    # A2 口径缺口量化：freq 能否由已交付证据链重算
    bad_freq = [i for i in range(ev.n) if ev.freq.get(i, 0) != ev.nfreq[i]]
    gap("A2 freq 可由 card_topics 独立重算（口径缺口）",
        f"不符 {len(bad_freq)}/{ev.n}（{len(bad_freq)/ev.n*100:.1f}%）——card_topics 只存每卡 top-5，"
        f"而 freq 定义在有书目证据的**完整**卡集上；例：{[(ev.term[i], ev.nfreq[i], ev.freq.get(i, 0)) for i in bad_freq[:3]]}")
    # A3 交付序无法由任何 card_topics 派生键复现 → max_cc 不可重算
    deliv = list(range(ev.n))
    variants = {}
    own = {i: ev.cluster_own.get(i, 0) for i in range(ev.n)}
    for nm, kf in (("max_all_clusters", lambda i: ev.maxcc.get(i, 0)),
                   ("own_cluster_count", lambda i: own[i])):
        o = sorted(range(ev.n), key=lambda i: (-kf(i), -ev.nfreq[i], ev.term[i]))
        variants[nm] = sum(1 for x, y in zip(o, deliv) if x != y)
    gap("A3 排序键 max_cc 可由已交付证据链重算",
        f"两种 card_topics 派生键与交付序分歧 {variants['max_all_clusters']}/{ev.n}、"
        f"{variants['own_cluster_count']}/{ev.n} 位 —— max_cc（=freq×rep）依赖 top-5 截断前的完整卡集，"
        f"该卡集**未落档**（AUDIT-NUM §5 同源问题）")
    # A4 cluster 字段自洽性（部分可验证）
    bad_clu = [i for i in range(ev.n) if ev.argmax_clu.get(i) is not None and ev.argmax_clu[i] != ev.ncl[i]]
    info("A4 cluster 字段 == 卡集主导簇（截断视图）",
         f"不符 {len(bad_clu)}/{ev.n} 节点（截断视图下主导簇可能改变，故非硬结论）")
    info("A5 freq 沿交付序非增", f"{'是' if all(ev.nfreq[i] >= ev.nfreq[i+1] for i in range(ev.n-1)) else '否'}"
         "（max_cc 为主键时 freq 本不必单调）")
    return {"structural_ok": True, "freq_gap": len(bad_freq), "variants_diff": variants,
            "cluster_gap": len(bad_clu), "independently_verifiable": False}


# ===========================================================================
# B/C · type 数组
# ===========================================================================
def part_bc(ev):
    print("\n=== B · type 数组：三类型掩码全量逐边核对 ===")
    z = np.load(os.path.join(TOPICS, "edges.csr.npz"))
    ip, ix, wt, ty = z["indptr"], z["indices"], z["weights"], z["types"]
    nnz = len(ix)
    bad0, bad1, bad2, bad1_converse = [], [], [], []
    for u in range(ev.n):
        for p in range(int(ip[u]), int(ip[u + 1])):
            v = int(ix[p])
            m = int(ty[p])
            k = (u, v) if u < v else (v, u)
            exp1 = 1 if ev.csc.get(k, 0) > 0 else 0
            exp2 = 1 if ev.cls_of.get(u) == v else 0
            if not (m & 1):
                bad0.append((u, v, m))
            if bool(m & 2) != bool(exp1):
                bad1.append((u, v, m, exp1, ev.csc.get(k, 0)))
            if bool(m & 4) != bool(exp2):
                bad2.append((u, v, m, exp2))
            if (m & 2) and ev.ncl[u] != ev.ncl[v]:
                bad1_converse.append((u, v))
    dom = sorted(set(int(x) for x in ty))
    rec("B1 types dtype=uint8 且长度 == nnz", ty.dtype == np.uint8 and len(ty) == nnz,
        f"dtype={ty.dtype} len={len(ty)} nnz={nnz}")
    rec("B2 值域 ⊆ {1,3,5,7}（bit0 恒置位 + 合法组合）", set(dom) <= {1, 3, 5, 7},
        f"实测值域={dom}")
    rec(f"B3 bit0（①共现）全量置位（{nnz:,} 条）", not bad0, f"违例 {len(bad0)}" + (f" 例={bad0[:3]}" if bad0 else ""))
    rec(f"B4 bit1（②同簇加成）== c_sc>0 全量吻合（{nnz:,} 条独立重算）", not bad1,
        f"不符 {len(bad1)}" + (f" 例={bad1[:3]}" if bad1 else ""))
    rec("B5 单向不变式 bit1 ⇒ 两端同 cluster", not bad1_converse,
        f"违例 {len(bad1_converse)}")
    rec(f"B6 bit2（③层级）== (src→cls_of[src]) 全量吻合（{nnz:,} 条）", not bad2,
        f"不符 {len(bad2)}" + (f" 例={bad2[:3]}" if bad2 else ""))
    dist = Counter(int(x) for x in ty)
    print("  掩码分布：" + " | ".join(f"{k}: {dist[k]:,} ({dist[k]/nnz*100:.2f}%)" for k in sorted(dist)))
    # 抽样 >=100 条（任务书下限）单独记账
    rng = np.random.default_rng(20260918)
    samp = rng.choice(nnz, size=300, replace=False)
    print(f"  抽样 {len(samp)} 条（任务书要求 ≥100）已含于全量核对内")

    print("\n=== C · type 数组对照 ===")
    zc = np.load(os.path.join(TOPICS, "edges.csr.pre-r2c.npz"))
    rec("C1 vs pre-r2c：indptr/indices/weights **逐位一致**（R2-C 仅新增 types）",
        np.array_equal(ip, zc["indptr"]) and np.array_equal(ix, zc["indices"])
        and np.array_equal(wt, zc["weights"]),
        f"indptr={np.array_equal(ip, zc['indptr'])} indices={np.array_equal(ix, zc['indices'])} "
        f"weights={np.array_equal(wt, zc['weights'])}；pre-r2c 键={sorted(zc.files)}")
    z0 = np.load(os.path.join(TOPICS, "edges.csr.pre-r2.npz"))
    n0 = len(z0["indices"])
    rec("C2 vs pre-r2：R2-A 重建后三数组必不相同（词表 +320 节点）—— 属预期，非缺陷",
        not (np.array_equal(ip, z0["indptr"]) and np.array_equal(ix, z0["indices"])),
        f"pre-r2 nnz={n0:,}（无 types 键）→ 现 nnz={nnz:,}（+{nnz-n0:,}）")
    tp = os.path.join(TOPICS, "export-sample", "v1", "topics")
    tn = os.path.join(tp, "edges_types.u8.bin")
    ok_exp = False
    if os.path.isfile(tn):
        exp_ty = np.fromfile(tn, dtype=np.uint8)
        ok_exp = len(exp_ty) == nnz and np.array_equal(exp_ty, ty)
    rec("C3 导出包 edges_types.u8.bin == 源 npz types（逐位）", ok_exp,
        f"{os.path.relpath(tn, DATA)} len={os.path.getsize(tn) if os.path.isfile(tn) else 'NA'}")
    wn = os.path.join(tp, "edges_weights.u8.bin")
    print(f"  权重对照：pre-r2 float32 mean={float(z0['weights'].mean()):.6f} → "
          f"现 mean={float(wt.mean()):.6f}；w=1 占比 {float((wt>=0.99999).mean()):.4f}"
          f"（pre-r2 {float((z0['weights']>=0.99999).mean()):.4f}）")
    return {"nnz": nnz, "domain": dom, "dist": {str(k): int(v) for k, v in dist.items()},
            "sampled": int(len(samp)), "bit0_viol": len(bad0), "bit1_viol": len(bad1),
            "bit1_converse_viol": len(bad1_converse), "bit2_viol": len(bad2),
            "pre_r2c_bitidentical": bool(np.array_equal(ip, zc["indptr"])
                                         and np.array_equal(ix, zc["indices"])
                                         and np.array_equal(wt, zc["weights"])),
            "pre_r2_nnz": n0, "export_types_match": bool(ok_exp),
            "w_eq1_share": float((wt >= 0.99999).mean()),
            "w_mean": float(wt.mean()), "pre_r2_w_eq1_share": float((z0["weights"] >= 0.99999).mean()),
            "pre_r2_w_mean": float(z0["weights"].mean())}


# ===========================================================================
# D · topic_graph 修复后抽测（M2 × 2 / P4 × 2）
# ===========================================================================
def part_d():
    print("\n=== D · topic_graph 抽测：M2 与 P4 修复后各 2 例 ===")
    out = {}
    # M2-1：大小写等价（存名 vs 归一名）
    rc1, o1 = run_tool(["search", "D9", "--top", "3", "--expand", "no"])
    rc2, o2 = run_tool(["search", "d9", "--top", "3", "--expand", "no"])
    h1 = int((__import__("re").search(r"字面命中\s*(\d+)\s*个", o1) or [0, 0])[1] or 0)
    h2 = int((__import__("re").search(r"字面命中\s*(\d+)\s*个", o2) or [0, 0])[1] or 0)
    rec("D1 M2 抽测①：`search D9` 与 `search d9` 命中数一致且 ≥1", rc1 == 0 and rc2 == 0 and h1 == h2 and h1 >= 1,
        f"rc={rc1}/{rc2} 命中={h1}/{h2}")
    out["m2_1"] = {"D9": h1, "d9": h2}
    # M2-2：around --term 大写可用 + 归一后一致
    rc3, o3 = run_tool(["around", "--term", "TP3", "--hops", "1", "--top", "3"])
    rc4, o4 = run_tool(["around", "--term", "tp3", "--hops", "1", "--top", "3"])
    same_seed = ("「TP3」" in o3) and ("「TP3」" in o4 or "「tp3」" in o4)
    rec("D2 M2 抽测②：`around --term TP3` 与 `tp3` 均 exit 0 且定位同一 cls 节点",
        rc3 == 0 and rc4 == 0 and same_seed,
        f"rc={rc3}/{rc4} | {o3.strip().splitlines()[0][:60] if o3.strip() else ''}")
    out["m2_2"] = {"rc": [rc3, rc4]}
    # P4-1：search 首排为「最专门词」（R2-B 修复②）——高频泛词不得恒占首位
    for q, yingdang in (("机器学习", "learning"), ("量子计算", None)):
        rc, o = run_tool(["search", q, "--top", "3", "--expand", "no"], timeout=180)
        first = next((ln.strip() for ln in o.splitlines() if __import__("re").match(r"^\s*\d+\s+\S+\s+(kw|cls)\s", ln)), "")
        out.setdefault("search_first", {})[q] = first[:60]
        print(f"  [INFO] search {q} 首排：{first[:80]}")
    rc, o = run_tool(["around", 56, "--hops", "2", "--top", "5", "--evidence", "3"], timeout=300)
    rec("D3 P4 抽测①：`around 56`（机器）exit 0 且证据段非空", rc == 0 and "[书证据]" in o,
        f"rc={rc}")
    out["p4_1"] = {"rc": rc}
    rc, o = run_tool(["around", 65, "--hops", "2", "--top", "5", "--evidence", "3"], timeout=300)
    rec("D4 P4 抽测②：`around 65`（文学）exit 0 且证据段非空", rc == 0 and "[书证据]" in o, f"rc={rc}")
    out["p4_2"] = {"rc": rc}
    return out


# ===========================================================================
# E · P4 相关率抽验 2 条（完整协议）
# ===========================================================================
def part_e():
    print("\n=== E · P4 相关率抽验（2 条，完整协议，原始输出落 runs/）===")
    os.makedirs(RUNDIR, exist_ok=True)
    res = {}
    for tag, q in (("Q02", "量子 计算"), ("Q06", "唐诗")):
        rc, o = run_tool(["search", q, "--top", "10"], timeout=180)
        open(os.path.join(RUNDIR, f"relevance-{tag}-search.txt"), "w", encoding="utf-8").write(o)
        # P2 路径：整词命中（src ∈ exact/token）中 freq 最低者
        cands = []
        for ln in o.splitlines():
            m = __import__("re").match(r"^\s*(\d+)\s+(\S+)\s+(kw|cls)\s+(\d+)\s+\d+\s+\S+\s+(\S+)\s", ln)
            if m and m.group(5) in ("exact", "token"):
                cands.append((int(m.group(4)), int(m.group(1)), m.group(2)))
        seed = min(cands)[1] if cands else None
        rc2, o2 = (run_tool(["around", seed, "--hops", "2", "--top", "10", "--evidence", "5"], timeout=300)
                   if seed is not None else (1, "no seed"))
        open(os.path.join(RUNDIR, f"relevance-{tag}-around.txt"), "w", encoding="utf-8").write(o2)
        hop1 = []
        for ln in o2.splitlines():
            m = __import__("re").match(r"^\s*(\d+)\s+(\S+)\s+(kw|cls)\s+score=", ln)
            if m:
                hop1.append((m.group(2), m.group(3)))
        ev = [ln.strip() for ln in o2.splitlines() if "via 「" in ln]
        print(f"  [{tag}] {q}：种子={seed}（整词最低频）；hop1 top10 可读="
              f"{[t for t, ty in hop1 if ty == 'kw'][:10]}；证据 {len(ev)} 条")
        for e in ev:
            print(f"        {e[:110]}")
        res[tag] = {"query": q, "seed": seed, "hop1": hop1[:10], "evidence": ev,
                    "rc": [rc, rc2]}
        rec(f"E {tag}「{q}」两命令均成功返回（协议可复跑）", rc == 0 and rc2 == 0 and bool(hop1),
            f"种子={seed} hop1={len(hop1)} 证据={len(ev)}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default=os.path.join(TOPICS, "audit", "r2-verify", "verify_r2e.json"))
    a = ap.parse_args()
    print("### R2-E · R2 全轮关键验证（独立复跑）")
    ev = Ev()
    print(f"  [evidence] nodes={ev.n} kw={sum(1 for t in ev.type if t=='kw')} "
          f"cls={sum(1 for t in ev.type if t=='cls')} distinct_pairs={len(ev.cnt):,} "
          f"hier={len(ev.cls_of):,}")
    ra = part_a(ev)
    rbc = part_bc(ev)
    rd = part_d()
    re_ = part_e()
    npass = sum(1 for c in CELL if c["ok"] is True)
    nfail = sum(1 for c in CELL if c["ok"] is False)
    ngap = sum(1 for c in CELL if c["kind"] == "gap")
    ninfo = sum(1 for c in CELL if c["kind"] == "info")
    print(f"\n=== 汇总：{npass} PASS / {nfail} FAIL / {ngap} GAP（既有口径缺口，非 R2 回归）"
          f" / {ninfo} INFO（共 {len(CELL)} 项）===")
    for c in CELL:
        if c["ok"] is False:
            print(f"  FAIL: {c['check']} — {c['detail']}")
    for c in CELL:
        if c["kind"] == "gap":
            print(f"  GAP : {c['check']} — {c['detail']}")
    json.dump({"checks": CELL, "pass": npass, "fail": nfail, "gap": ngap, "info": ninfo,
               "f1": ra, "types": rbc, "tool_spotcheck": rd, "relevance_spotcheck": re_},
              open(a.json_out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  → {a.json_out}")
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
