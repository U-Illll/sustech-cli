#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit/graph/reverse_tests.py — topic_graph.py 内存反例集（任务书 AUDIT-GRAPH）

方法：不依赖大数据。自建 9 节点小图 + 小词表/TF-IDF，对参数矩阵与边界做系统反例；
      CLI 层断言载荷语义（JSON 字段/报告字段/存根/错误码），库层断言图不变式（无环/路径=跳数/乘积公式/预算）。
约束：只读主体代码（不修改 topic_graph.py）；不访问网络；产物只写本目录。
用法：
  python3 ~/go/lib-catalog-data/topics/audit/graph/reverse_tests.py            # 合成反例（默认）
  python3 ~/go/lib-catalog-data/topics/audit/graph/reverse_tests.py --real      # 追加真实数据回归
  python3 ~/go/lib-catalog-data/topics/audit/graph/reverse_tests.py --only F1,F5
  python3 ~/go/lib-catalog-data/topics/audit/graph/reverse_tests.py --keep      # 保留合成数据目录
退出码：0 = 跑完且无 INVARIANT 违例；1 = 有 INVARIANT 违例（--strict 时缺陷未复现也算）；2 = 环境不可用。
发现编号 F1..F14 与 REPORT.md 一一对应。
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

TOOL_DEFAULT = "/home/wzh/go/reasonix-scripts/lib-catalog/topic_graph.py"
DATA_DEFAULT = os.path.expanduser("~/go/lib-catalog-data")
PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(PYLIBS) and PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)
import numpy as np                                                    # noqa: E402
from scipy import sparse                                              # noqa: E402

# ---------------------------------------------------------------------------
# 迷你图（9 节点）：环 0→1→2→3→4→0 / 自环 1→1 / 低权边 0→5 / 孤立对 7-8
#   反例 1（F4）：节点 2 有两条入路——1 跳 0→2(0.3)=0.258 与 2 跳 0→1→2(0.9·0.8)=0.5325；
#                 首访定型使 region 只留 0.258（低估 51.6%）。
#   反例 2（S1）：同跳双父指向节点 3——1 跳父 1 给 0.13312、2 跳父 2 给 0.11094 → 取最大且 parent=1。
# ---------------------------------------------------------------------------
NODES = [
    {"id": 0, "term": "机器学习", "type": "kw", "freq": 100, "cluster": 1, "cls": "TP", "sources": ["a"]},
    {"id": 1, "term": "深度学习", "type": "kw", "freq": 50, "cluster": 1, "cls": "TP", "sources": ["a"]},
    {"id": 2, "term": "神经网络", "type": "kw", "freq": 40, "cluster": 1, "cls": "TP", "sources": ["a"]},
    {"id": 3, "term": "量子", "type": "kw", "freq": 30, "cluster": 2, "cls": "O4", "sources": ["b"]},
    {"id": 4, "term": "量子力学", "type": "kw", "freq": 20, "cluster": 2, "cls": "O4", "sources": ["b"]},
    {"id": 5, "term": "科学", "type": "kw", "freq": 60, "cluster": 3, "cls": "N", "sources": ["c"]},
    {"id": 6, "term": "科普", "type": "kw", "freq": 25, "cluster": 3, "cls": "N", "sources": ["c"]},
    {"id": 7, "term": "算法", "type": "kw", "freq": 70, "cluster": 1, "cls": "TP", "sources": ["a"]},
    {"id": 8, "term": "tp3", "type": "cls", "freq": 10, "cluster": 4, "cls": "TP3", "sources": ["d"]},
    {"id": 9, "term": "smartphone", "type": "kw", "freq": 15, "cluster": 5, "cls": "TN", "sources": ["e"]},
    {"id": 10, "term": "D9", "type": "cls", "freq": 3717, "cluster": 6, "cls": "D9", "sources": ["C"]},
]
EDGES = [(0, 1, 0.9), (1, 2, 0.8), (0, 2, 0.3), (2, 3, 0.5), (1, 3, 0.2),
         (3, 4, 1.0), (4, 0, 1.0), (1, 1, 1.0), (0, 5, 0.04), (5, 6, 1.0), (7, 8, 0.9)]
CARD_TOPICS = [[0, 1], [0], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6], [7, 8], [8, 0]]
VOCAB = ["机器", "器学", "学习", "入门", "量子", "科普"]
XTAB = [[0, 1], [0, 2], [1, 3], [2, 3], [4, 5], [4], [5], [1], [0, 3], [2]]


def csr(edges, n, indptr_len=None, weights_override=None):
    """建 CSR（同真实产物 dtype：indptr int64 / indices int32 / weights float32）。"""
    row = sorted(edges, key=lambda e: e[0])
    ix, wt, ip = [], [], np.zeros(n + 1, dtype=np.int64)
    for u in range(n):
        for (a, b, w) in row:
            if a == u:
                ix.append(b)
                wt.append(w)
        ip[u + 1] = len(ix)
    ix = np.array(ix, dtype=np.int32)
    wt = np.array(wt, dtype=np.float32) if weights_override is None else weights_override
    if indptr_len is not None:
        ip = ip[:indptr_len]                                          # 故意截断
    return ip, ix, wt


def write_fixture(root, name, edges=None, nodes=None, indptr_len=None, ct_blank=False,
                  ct_override=None, ct_drop_first=False, cards_blank=False, no_cards=False,
                  shuffle_nodes=False, drop_node_field=None, xtab=None,
                  weights_override=None, weight_zero_edge=False, weight_gt1=False):
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, "topics"), exist_ok=True)
    os.makedirs(os.path.join(d, "index"), exist_ok=True)
    edges = list(EDGES if edges is None else edges)
    if weight_zero_edge:
        edges.append((0, 7, 0.0))
    if weight_gt1:
        edges.append((0, 8, 3.0))
    nd = json.loads(json.dumps(NODES if nodes is None else nodes))
    if shuffle_nodes:
        nd = nd[::-1]
    if drop_node_field:
        next(n for n in nd if n["id"] == 3).pop(drop_node_field, None)
    json.dump(nd, open(os.path.join(d, "topics/nodes.json"), "w", encoding="utf-8"), ensure_ascii=False)
    ip, ix, wt = csr(edges, len(nd), indptr_len=indptr_len, weights_override=weights_override)
    np.savez(os.path.join(d, "topics/edges.csr.npz"), indptr=ip, indices=ix, weights=wt)
    cts = CARD_TOPICS if ct_override is None else ct_override
    n_cards = len(cts)
    lines = [""] if ct_blank else []
    for i, ts in enumerate(cts):
        lines.append(json.dumps({"mms": "mms-%03d" % i, "topics": ts}, ensure_ascii=False))
    if ct_drop_first:
        lines = lines[1:]                                             # 记录整体前移 → 主题↔卡片错配
    with open(os.path.join(d, "topics/card_topics.jsonl"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if not no_cards:
        with open(os.path.join(d, "cards.jsonl"), "w", encoding="utf-8") as f:
            for i in range(n_cards):
                if cards_blank and i == 2:
                    f.write("\n")                                     # cards.jsonl 空行 → load_titles 撞空行
                f.write(json.dumps({"mms": "mms-%03d" % i, "title": "title-%03d" % i,
                                    "cls": "TP", "cls2": "TP1", "year": "20%02d" % i},
                                   ensure_ascii=False) + "\n")
    X = sparse.csr_matrix(np.array([[1.0 if [i, j] in (XTAB if xtab is None else xtab) else 0.0
                                     for j in range(len(VOCAB))]
                                    for i in range(n_cards)], dtype=np.float32))
    sparse.save_npz(os.path.join(d, "index/tfidf.npz"), X)
    json.dump(VOCAB, open(os.path.join(d, "index/vocab.json"), "w", encoding="utf-8"))
    np.save(os.path.join(d, "index/idf.npy"), np.ones(len(VOCAB), dtype=np.float32))
    return d


# ---------------------------------------------------------------------------
# 报告器 / 工具调用
# ---------------------------------------------------------------------------
class Rep:
    def __init__(self, only=None):
        self.only = set(only or [])
        self.viol, self.conf, self.norep, self.info = [], [], [], []

    def _on(self, fid):
        return not self.only or any(f in self.only for f in fid.split("/"))

    def inv(self, fid, name, ok, detail="", repro=""):
        if not self._on(fid):
            return
        print(f"  [{'PASS' if ok else 'VIOLATION'}] {fid} {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            self.viol.append((fid, name, detail))
            if repro:
                print(f"          repro: {repro}")

    def defect(self, fid, name, present, detail="", repro=""):
        if not self._on(fid):
            return
        if present:
            print(f"  [CONFIRMED] {fid} {name}" + (f" — {detail}" if detail else ""))
            self.conf.append((fid, name, detail))
            if repro:
                print(f"          repro: {repro}")
        else:
            print(f"  [NOT-REPRODUCED] {fid} {name}" + (f" — {detail}" if detail else ""))
            self.norep.append((fid, name, detail))

    def note(self, fid, msg):
        if self._on(fid):
            self.info.append((fid, msg))
            print(f"  [INFO] {fid} {msg}")


CLI = {"tool": TOOL_DEFAULT, "self": os.path.abspath(__file__)}
DEPS_DIR = os.path.dirname(TOOL_DEFAULT)          # catalog_vector / topic_build 所在目录（快照运行时靠它导入同源依赖）


def cli(*argv, data=None, env=None, timeout=300):
    a = [sys.executable, CLI["tool"]]
    if data:
        a += ["--data", data]
    a += [str(x) for x in argv]
    e = {k: v for k, v in os.environ.items() if k != "TOPIC_LLM"}
    e["PYTHONPATH"] = DEPS_DIR + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    e["PYTHONDONTWRITEBYTECODE"] = "1"                                 # 不在 audit/ 之外落 __pycache__
    if data is None:
        e["LIB_CATALOG_DATA"] = "/nonexistent-data-dir (force explicit fixture)"
    if env:
        e.update(env)
    p = subprocess.run(a, capture_output=True, text=True, timeout=timeout, env=e)
    return p.returncode, p.stdout, p.stderr


def shq(x):
    s = str(x)
    return json.dumps(s, ensure_ascii=False) if (s == "" or " " in s) else s


def repro_cli(data, *argv):
    return f"python3 {CLI['tool']} --data {data} " + " ".join(shq(x) for x in argv)


def repro_self(fid):
    return f"python3 {CLI['self']} --only {fid.split('/')[0]}" + (" --real" if fid.startswith("S8") else "")


def strict_json(text):
    return json.loads(text, parse_constant=lambda c: (_ for _ in ()).throw(ValueError("non-strict JSON: " + c)))


def jtry(text):
    """容错解析：非 JSON 返回 None（避免断言表达式里二次解析崩溃）。"""
    try:
        return strict_json(text)
    except Exception:
        return None


def strip_timing(text):
    """去掉 elapsed_ms 行后比较（统计字段天然非确定，不属缺陷）。"""
    return "\n".join(l for l in text.splitlines() if "elapsed_ms" not in l)


def edge_map(edges):
    m = {}
    for (a, b, w) in edges:
        m[(a, b)] = max(m.get((a, b), 0.0), w)
    return m


def path_len(reg, x, guard=999):
    c, cur = 0, reg["parent"].get(x)
    while cur is not None and c < guard:
        c += 1
        cur = reg["parent"].get(cur)
    return c


def best_within_hops(seed, hops, ip, ix, wt, decay, thr):
    """≤hops 跳的最优路径分（按跳数精确分层的 DP 上界）。"""
    dp, best = {seed: 1.0}, {seed: 1.0}
    for _k in range(1, hops + 1):
        nxt = {}
        for u, su in dp.items():
            for p in range(int(ip[u]), int(ip[u + 1])):
                v, s = int(ix[p]), su * float(wt[p]) * decay
                if s >= thr and s > nxt.get(v, 0.0):
                    nxt[v] = s
        for v, s in nxt.items():
            best[v] = max(best.get(v, 0.0), s)
        dp = nxt
        if not dp:
            break
    return best


def lib_check(R, fid, tag, reg, ip, ix, wt, nodes, emap, hops, decay, thr, budget, repro):
    """库层不变式体检（全精度 score/parent/layer 字典）。"""
    sc, par, lay = reg["score"], reg["parent"], reg["layer"]
    seed = 0 if 0 in sc else next(iter(sc))
    bad_len, bad_prod, cyc, bad_mono = [], [], [], []
    for v in sc:
        if v == seed:
            continue
        chain, node, hops_seen = [v], v, 0
        while True:
            p = par.get(node)
            if p is None:
                break
            chain.append(p)
            node = p
            hops_seen += 1
            if hops_seen > len(sc) + 2:
                cyc.append(v)
                break
        if chain[-1] != seed or len(set(chain)) != len(chain):
            cyc.append(v)
            continue
        n = len(chain) - 1
        if n != lay[v] or n > hops:
            bad_len.append((v, n, lay[v], hops))
        prod = 1.0
        for i in range(len(chain) - 1):
            prod *= emap.get((chain[i + 1], chain[i]), 0.0)
        if abs(prod * decay ** n - sc[v]) > 1e-7:
            bad_prod.append((v, sc[v], prod * decay ** n))
        if sc[v] > sc[chain[1]] + 1e-9:                # 子 > 父 即违例（w≤1、decay≤1）
            bad_mono.append((v, sc[v], sc[chain[1]]))
    R.inv(fid, f"{tag} 区域 ≤ budget", len(sc) <= budget, f"{len(sc)} ≤ {budget}", repro)
    R.inv(fid, f"{tag} visited == region 规模", reg["visited"] == len(sc), f"{reg['visited']} vs {len(sc)}", repro)
    R.inv(fid, f"{tag} 父链无环、终点=源点", not cyc, f"{cyc[:4]}", repro)
    R.inv(fid, f"{tag} 路径长度 == layer ≤ hops", not bad_len, f"{bad_len[:4]}", repro)
    R.inv(fid, f"{tag} score == Π(边权)·decay^layer", not bad_prod, f"{bad_prod[:3]}", repro)
    R.inv(fid, f"{tag} 子节点 score ≤ 父节点 score（单调）", not bad_mono, f"{bad_mono[:3]}", repro)
    R.inv(fid, f"{tag} 源点 score=1.0 layer=0", abs(sc[seed] - 1.0) < 1e-12 and lay[seed] == 0,
          f"score={sc[seed]} layer={lay[seed]}", repro)
    if thr > 0:
        low = [(v, sc[v]) for v in sc if v != seed and sc[v] < thr]
        R.inv(fid, f"{tag} 非源点 score ≥ threshold", not low, f"{low[:3]}", repro)
    # 分层单调（层内最大分随层号不增）
    mx = {}
    for v, h in lay.items():
        mx[h] = max(mx.get(h, -1.0), sc[v])
    hs = sorted(mx)
    R.inv(fid, f"{tag} 层最大分随跳数单调不增",
          all(mx[hs[i]] >= mx[hs[i + 1]] - 1e-12 for i in range(len(hs) - 1)),
          f"{[(h, round(mx[h], 4)) for h in hs]}", repro)


def sec_invariants(R, mini_min):
    print("\n[S1] 图不变式：参数矩阵（库层，hops 0/1/2/3/12/13/70 × decay 边界 × threshold 0/1 × budget 1/2/4/50k）")
    tg = load_tool()
    ip0, ix0, wt0 = csr(EDGES, len(NODES))
    emap = edge_map(EDGES)
    for hops in (0, 1, 2, 3, 12, 13, 70):
        for decay in (0.86, 1.0):
            for thr in (0.05, 0.0, 1.0):
                for budget in (1, 2, 4, 50000):
                    tag = f"hops={hops} decay={decay} thr={thr} budget={budget}"
                    reg = tg.diffuse(0, hops, ip0, ix0, wt0, decay, thr, budget)
                    lib_check(R, "S1", tag, reg, ip0, ix0, wt0, NODES, emap, hops, decay, thr, budget,
                              f"python3 -c \"...tg.diffuse(0,{hops},ip,ix,wt,{decay},{thr},{budget})...\""
                              f" 或 {repro_self('S1')}")
                    if hops == 0:
                        R.inv("S1", f"{tag} hops=0 → 仅源点且无分层", set(reg["score"]) == {0}
                              and tg.build_layers(reg, NODES, 0, 12) == [], "", repro_self("S1"))
    # 同跳双父取最大：节点 3 两路 (1 跳父1: 0.13312) / (2 跳父2: 0.11094)
    reg = tg.diffuse(0, 2, ip0, ix0, wt0, 0.86, 0.05, 50000)
    R.inv("S1", "同跳多父取分数最大者（parent 正确）",
          reg["parent"].get(3) == 1 and abs(reg["score"][3] - 0.9 * 0.86 * 0.2 * 0.86) < 1e-6,
          f"parent={reg['parent'].get(3)} score={reg['score'].get(3):.5f}（期望 parent=1 / 0.13312）",
          repro_self("S1"))
    # 阈值剪枝：0→5 (0.04) 永久不可达
    R.inv("S1", "低于阈值的边不被穿越（5/6 不进区域）",
          all(v not in reg["score"] for v in (5, 6)), f"region={sorted(reg['score'])}", repro_self("S1"))
    # 自环/回边不成环
    reg12 = tg.diffuse(0, 12, ip0, ix0, wt0, 0.86, 0.05, 50000)
    R.inv("S1", "自环 1→1 与回边 4→0 不产生环", tg.path_len(4, reg12) == 3 and 0 in reg12["score"],
          f"path_len(4)={tg.path_len(4, reg12)}", repro_self("S1"))
    # 确定性
    R.inv("S1", "diffuse 确定性（两次调用结果全等）",
          tg.diffuse(0, 3, ip0, ix0, wt0, 0.86, 0.05, 50000) == tg.diffuse(0, 3, ip0, ix0, wt0, 0.86, 0.05, 50000),
          "", repro_self("S1"))
    # CLI 载荷：layers 分区 / hops_used / path / stats / 严格 JSON / 确定性
    argv = ("around", 0, "--hops", 3, "--top", 12, "--evidence", 4, "--json")
    rc, out, err = cli(*argv, data=mini_min)
    if rc != 0:
        R.inv("S1", "CLI around --json exit 0", False, f"rc={rc} err={err.strip()[:100]}", repro_cli(mini_min, *argv))
        return
    reg_j = strict_json(out)
    tot = sum(L["n"] for L in reg_j["layers"])
    R.inv("S1", "CLI 分层覆盖 = visited-1（除源点）", tot == reg_j["stats"]["visited"] - 1,
          f"{tot} vs {reg_j['stats']['visited']-1}", repro_cli(mini_min, *argv))
    R.inv("S1", "CLI 各层 hops_used == hop == len(path)-1", all(
        nd["hops_used"] == L["hop"] == len(nd["path"]) - 1 for L in reg_j["layers"] for nd in L["nodes"]), "",
        repro_cli(mini_min, *argv))
    R.inv("S1", "CLI path 首元素 = 源点", all(
        nd["path"][0] == reg_j["seed"]["term"] for L in reg_j["layers"] for nd in L["nodes"]), "",
        repro_cli(mini_min, *argv))
    R.inv("S1", "CLI 层号从 1 连续（无 hop 0/空洞）",
          [L["hop"] for L in reg_j["layers"]] == list(range(1, len(reg_j["layers"]) + 1)),
          f"{[L['hop'] for L in reg_j['layers']]}", repro_cli(mini_min, *argv))
    R.inv("S1", "CLI 输出为严格 JSON（无 NaN/Infinity）", True, "", "")
    out2 = cli(*argv, data=mini_min)[1]
    R.inv("S1", "CLI around --json 除 elapsed_ms 外两次逐字节一致", strip_timing(out2) == strip_timing(out),
          "", repro_cli(mini_min, *argv))
    R.note("F6c2", f"around --json / summarize --json 的 stats.elapsed_ms 使原始字节不可复现（本次 {'一致' if out2 == out else '不同'}）")


def sec_guards(R, mini):
    print("\n[S2] CLI 护栏 vs 库内无护栏（F3）")
    for bad in (("--decay", "1.1"), ("--decay", "0"), ("--decay", "-0.2"), ("--budget", "0"),
                ("--threshold", "2"), ("--threshold", "-0.1"), ("--hops", "0"), ("--hops", "13"), ("--hops", "-1")):
        argv = ("around", 0, "--hops", 1, bad[0], bad[1]) if bad[0] != "--hops" else ("around", 0, bad[0], bad[1])
        rc, out, err = cli(*argv, data=mini)
        R.inv("S2", f"CLI {bad[0]} {bad[1]} 被拒",
              rc != 0 and ("需在" in out + err or "需 ≥" in out + err), f"rc={rc} {(out+err).strip()[:70]}",
              repro_cli(mini, *argv))
    tg = load_tool()
    ip, ix, wt = csr(EDGES, len(NODES))
    base = dict(hops=3, decay=0.86, threshold=0.05, budget=50000)
    silent, over1, budget_viol, crashers = [], [], [], []
    for name, kw in (("decay=-1", {"decay": -1.0}), ("decay=0", {"decay": 0.0}), ("decay=1.1", {"decay": 1.1}),
                     ("decay=2.0", {"decay": 2.0}), ("threshold=2", {"threshold": 2.0}),
                     ("threshold=-1", {"threshold": -1.0}), ("hops=0", {"hops": 0}), ("hops=13", {"hops": 13}),
                     ("hops=70", {"hops": 70}), ("budget=0", {"budget": 0}), ("budget=-5", {"budget": -5})):
        p = dict(base)
        p.update(kw)
        try:
            reg = tg.diffuse(0, p["hops"], ip, ix, wt, p["decay"], p["threshold"], p["budget"])
        except Exception as e:
            crashers.append((name, type(e).__name__))
            continue
        silent.append(name)
        if max(reg["score"].values()) > 1.0 + 1e-12:
            over1.append((name, round(max(reg["score"].values()), 4)))
        if len(reg["score"]) > p["budget"]:
            budget_viol.append((name, len(reg["score"]), p["budget"]))
    R.defect("F3", "参数护栏只在 CLI main() 里；库内直调静默接受越界参数（decay/hops/budget/threshold）",
             len(silent) >= 8, f"{len(silent)}/11 静默通过：{silent}（崩溃 {crashers}）", repro_self("F3"))
    R.defect("F3b", "decay>1 时扩散分 >1（CLI 拒 1.1，库内接受；w∈[0,1] 契约无文档保证）",
             bool(over1), f"{over1}", repro_self("F3"))
    R.defect("F3c", "budget<1 时库内区域规模 > budget（CLI 拒 0）", bool(budget_viol), f"{budget_viol}", repro_self("F3"))
    # path_len 的 guard=64 静默截断
    n = 80
    ip2, ix2, wt2 = csr([(i, i + 1, 1.0) for i in range(n)], n + 1)
    reg = tg.diffuse(0, 70, ip2, ix2, wt2, 0.86, 0.0, 50000)
    deep = max(reg["score"], key=lambda v: reg["layer"][v])
    R.defect("F3d", "path_len() guard=64 静默截断（hops>64 时 hops_used/layer 字段失真，无告警）",
             tg.path_len(deep, reg) == 64 != reg["layer"][deep],
             f"最深节点 layer={reg['layer'][deep]} 而 path_len={tg.path_len(deep, reg)}", repro_self("F3"))
    # hops 上限 12 仅 CLI 强制
    R.defect("F3e", "HOPS_MAX=12 仅 CLI 强制（库内 hops=70 正常返回）",
             len(tg.diffuse(0, 70, ip2, ix2, wt2, 0.86, 0.0, 50000)["score"]) > 12, "", repro_self("F3"))


def sec_extremes(R, mini):
    print("\n[S3] 极值参数（--top / --evidence / --expand-*）无校验（F2 / F5）")
    for ev in (0, -1):
        argv = ("around", 0, "--hops", 2, "--evidence", ev, "--json")
        rc, out, err = cli(*argv, data=mini)
        n = len(strict_json(out)["evidence"]) if rc == 0 else -1
        if ev == 0:
            R.inv("S3", "--evidence 0 返回 0 条（R1.1 已把判空改为 scored[:k]，旧 off-by-one 已消除）", n == 0,
                  f"evidence 条数={n}", repro_cli(mini, *argv))
        else:
            R.defect("F5d", "--evidence 负数 = 负切片（返回 k-1 条，静默丢尾，无校验）",
                     n > 0, f"--evidence -1 → 实际 {n} 条（应为 0 或报错）", repro_cli(mini, *argv))
    for t in (0, -1):
        argv = ("around", 0, "--hops", 2, "--top", t, "--json")
        rc, out, err = cli(*argv, data=mini)
        if rc != 0:
            R.defect("F5", f"--top {t} 未校验（非 0 退出，无友好提示）", True, f"rc={rc}", repro_cli(mini, *argv))
            continue
        reg = strict_json(out)
        empty = [L["hop"] for L in reg["layers"] if L["n"] > 0 and not L["nodes"]]
        R.defect("F5", f"--top {t} → 层 n>0 但 nodes 空（字段语义不一致，无校验）", bool(empty),
                 f"层 {empty}：n>0 / nodes=[]", repro_cli(mini, *argv))
    rc, out1, _ = cli("search", "量子", "--top", 2, "--expand", "no", data=mini)
    rc, out2, _ = cli("search", "量子", "--top", -1, "--expand", "no", data=mini)
    rows = lambda o: [l for l in o.splitlines() if l.strip() and l.strip()[0].isdigit()]
    R.defect("F5b", "search --top 负数 = Python 负切片（静默丢尾，无校验）",
             bool(rows(out1)) and len(rows(out2)) == len(rows(out1)) - 1,
             f"top=2 → {len(rows(out1))} 行；top=-1 → {len(rows(out2))} 行（丢最后一条）",
             repro_cli(mini, "search", "量子", "--top", -1, "--expand", "no"))
    argv = ("search", "入门", "--expand", "yes", "--expand-cards", 0, "--json")
    rc, out, err = cli(*argv, data=mini)
    R.inv("S3", "--expand-cards 0 优雅处理（空扩展 + reason 不崩）", rc == 0 and strict_json(out)["expand"]["used"] is True,
          f"rc={rc} {(out+err).strip()[:60]}", repro_cli(mini, *argv))
    for t in (0, -1):
        argv = ("search", "入门", "--expand", "yes", "--expand-top", t, "--json")
        rc, out, err = cli(*argv, data=mini)
        R.inv("S3", f"--expand-top {t} 不崩（负值静默负切片）", rc == 0, f"rc={rc} {err.strip()[:60]}",
              repro_cli(mini, *argv))
    # --expand-cards 负值：轻则窗口反转（无崩溃但字段自相矛盾），重则 np.argpartition kth 越界崩溃
    argv = ("search", "入门", "--expand", "yes", "--expand-cards", -1, "--json")
    rc, out, err = cli(*argv, data=mini)
    j = jtry(out)
    inv = rc == 0 and j is not None and j["expand"].get("cards_scanned", 0) < 0
    argv2 = ("search", "入门", "--expand", "yes", "--expand-cards", -5)
    rc2, out2, err2 = cli(*argv2, data=mini)
    crash = rc2 != 0 and "ValueError" in err2
    R.defect("F5c", "--expand-cards 负值无下界：轻则窗口反转（cards_scanned 为负、窗口悄悄变成 |k| 之外的全部）而不报错，重则 np.argpartition kth 越界崩溃",
             inv or crash,
             f"-1 → rc={rc} cards_scanned={j['expand'].get('cards_scanned') if j else '?'}（无崩溃，字段自相矛盾）；"
             f"-5（nz=3）→ rc={rc2} {err2.strip().splitlines()[-1][:60] if err2.strip() else ''}",
             repro_cli(mini, *argv2))


def sec_evidence(R, root, mini):
    print("\n[S4] 证据反查（card_topics / cards.jsonl；F7 / F8 / F12 / F16）")
    tg = load_tool()
    argv = ("around", 0, "--hops", 2, "--evidence", 4, "--json")
    j = strict_json(cli(*argv, data=mini)[1])
    ev = j["evidence"]
    R.inv("S4", "基线 fixture 证据 mms/title 对齐", all(e["mms"][-3:] == e["title"][-3:] for e in ev) and len(ev) == 4,
          f"n={len(ev)} {[(e['mms'], e['title']) for e in ev]}", repro_cli(mini, *argv))
    R.inv("S4", "证据抽样确定性（同参数两次 evidence 全等）",
          strict_json(cli(*argv, data=mini)[1])["evidence"] == ev, "", repro_cli(mini, *argv))
    R.inv("S4", "证据按 region_cover_score 降序（R1.1 覆盖度排序）",
          all(ev[i]["region_cover_score"] >= ev[i + 1]["region_cover_score"] for i in range(len(ev) - 1)), "",
          repro_cli(mini, *argv))
    R.inv("S4", "证据无重复卡", len({e["mms"] for e in ev}) == len(ev), "", repro_cli(mini, *argv))
    fwd = [json.loads(l)["topics"] for l in open(os.path.join(mini, "topics/card_topics.jsonl"), encoding="utf-8")
           if l.strip()]
    scored = tg.diffuse(0, 2, *csr(EDGES, len(NODES)), 0.86, 0.05, 50000)["score"]
    R.inv("S4", "每张证据卡确实含其 via_id 主题，且 via_id 是该卡在区域内的最高分主题（平局取卡内先后）",
          all(int(e["mms"][-3:]) < len(fwd) and e["via_id"] in fwd[int(e["mms"][-3:])]
              and e["via_id"] == max([t for t in fwd[int(e["mms"][-3:])] if t in scored], key=lambda t: scored[t])
              for e in ev),
          f"{[(e['mms'], e['via_id'], fwd[int(e['mms'][-3:])]) for e in ev]}", repro_cli(mini, *argv))
    per = {}
    for e in ev:
        per[e["via_id"]] = per.get(e["via_id"], 0) + 1
    R.inv("S4", "每主题候选 ≤ per_topic=8 张（硬编码，无 CLI 开关）", all(v <= 8 for v in per.values()), f"{per}",
          repro_cli(mini, *argv))
    # 头部 docstring 声明的 evidence schema 与实现不符
    R.defect("F16", "头部 docstring 声明 evidence:[{mms,title,cls,cls2,topics}]，实现无 topics 字段（改出 via_topic/via_id/region_cover_score/year）",
             bool(ev) and "topics" not in ev[0] and {"via_id", "via_topic", "region_cover_score"} <= set(ev[0]),
             f"实际字段={sorted(ev[0])}", "grep -n 'evidence:\\[' <tool>")
    # card_topics 记录数 < cards.jsonl 行数 → 主题↔卡片静默错配（无跨文件一致性校验）
    shift = write_fixture(root, "ctshift", ct_drop_first=True)
    rc, out, err = cli(*argv, data=shift)
    mis = []
    if rc == 0:
        evs = strict_json(out)["evidence"]
        recs = [json.loads(l)["mms"] for l in open(os.path.join(shift, "topics/card_topics.jsonl"),
                                                   encoding="utf-8") if l.strip()]
        rec_at = lambda i: recs[i] if i < len(recs) else "<该行无 card_topics 记录>"
        mis = [(e["mms"], rec_at(int(e["mms"][-3:]))) for e in evs if rec_at(int(e["mms"][-3:])) != e["mms"]]
    R.defect("F8", "card_topics.jsonl 与 cards.jsonl 无一致性校验：记录少 1 行时主题↔卡片整体错配（静默）",
             rc == 0 and bool(mis),
             f"报告 mms-i 实际取到 card_topics 记录 {mis[0][1] if mis else '?'}（错配 {len(mis)} 条）"
             f"——把别张书的主题当成该书证据", repro_cli(shift, *argv))
    # card_topics 内空行不破坏对齐（索引按非空行计数）——反证「空行错位」不是真实风险
    blank = write_fixture(root, "blankline", ct_blank=True)
    rc, out, err = cli(*argv, data=blank)
    evb = strict_json(out)["evidence"] if rc == 0 else []
    R.inv("S4", "card_topics 内空行不影响对齐（按非空记录计数）",
          rc == 0 and all(e["mms"][-3:] == e["title"][-3:] for e in evb) and len(evb) == 4,
          f"rc={rc} n={len(evb)}", repro_cli(blank, *argv))
    # cards.jsonl 内空行 → load_titles 撞空行 json.loads("") 崩溃
    cb = write_fixture(root, "cardsblank", cards_blank=True)
    rc, out, err = cli(*argv, data=cb)
    R.defect("F8b", "cards.jsonl 存在空行 → load_titles 对空串 json.loads 崩溃（无行内容校验）",
             rc != 0 and ("JSONDecodeError" in err or "Expecting value" in err),
             f"rc={rc} last={err.strip().splitlines()[-1][:70] if err.strip() else ''}", repro_cli(cb, *argv))
    # cards.jsonl 缺失 → 未捕获 FileNotFoundError
    nocards = write_fixture(root, "nocards", no_cards=True)
    argv2 = ("around", 0, "--hops", 2, "--evidence", 2)
    rc, out, err = cli(*argv2, data=nocards)
    R.defect("F7", "cards.jsonl 缺失 → 未捕获 FileNotFoundError（其它 loader 均 sys.exit 友好提示）",
             rc == 1 and "Traceback" in err and "FileNotFoundError" in err,
             f"rc={rc} last={err.strip().splitlines()[-1][:70] if err.strip() else ''}", repro_cli(nocards, *argv2))
    # card_topics 主题 id 越界（近词扩展聚合后 nodes[id]）
    oob = write_fixture(root, "ctid_oob", ct_override=[[99]] * 10)
    argv3 = ("search", "入门", "--expand", "yes", "--expand-top", 5)
    rc, out, err = cli(*argv3, data=oob)
    R.defect("F7b", "card_topics 主题 id 越界 → nodes[id] IndexError（无 id < len(nodes) 校验）",
             rc != 0 and "IndexError" in err,
             f"rc={rc} last={err.strip().splitlines()[-1][:70] if err.strip() else ''}", repro_cli(oob, *argv3))
    # F12 交叉：阈值 0 时 0 分主题被 evidence_of 的 `if sc:` 当成「不在区域」
    zw = write_fixture(root, "zeroweight", weight_zero_edge=True)
    argvz = ("around", 0, "--hops", 2, "--threshold", 0, "--evidence", 8, "--json")
    rc, out, err = cli(*argvz, data=zw)
    jz = jtry(out)
    if jz:
        zero_topics = [t for t in (7, 8) if t in {nd["id"] for L in jz["layers"] for nd in L["nodes"]}]
        zero_in_ev = [e["via_id"] for e in jz["evidence"] if e["via_id"] in (7, 8)]
        R.defect("F12b", "evidence_of 用 `if sc:`（0.0 视为假）→ 仅由 0 分主题覆盖的卡被静默剔除（R1.1 引入的 falsy-zero）",
                 bool(zero_topics) and not zero_in_ev,
                 f"区域含 0 分主题 {zero_topics}（card_topics 中 id=7/8 有卡），但证据里没有任何 via_id ∈ {zero_topics}",
                 repro_cli(zw, *argvz))



def sec_stub(R, mini):
    print("\n[S5] 存根（TOPIC_LLM 各档）/ JSON 字段语义 / 错误码（F6）")
    rc0, o0, e0 = cli("summarize", 0, "--hops", 2, data=mini)
    R.inv("S5", "默认 TOPIC_LLM=off：exit 0 / 占位文 / stderr 干净",
          rc0 == 0 and "off" in o0 and not e0.strip(), f"rc={rc0} stderr={e0.strip()[:50]}",
          repro_cli(mini, "summarize", 0, "--hops", 2))
    R.inv("S5", "off 模式确定性（两次逐字节一致）", o0 == cli("summarize", 0, "--hops", 2, data=mini)[1], "",
          repro_cli(mini, "summarize", 0, "--hops", 2))
    rc, om, em = cli("summarize", 0, "--hops", 2, data=mini, env={"TOPIC_LLM": "mock"})
    R.inv("S5", "TOPIC_LLM=mock → 模板文 / exit 0 / 无警告", rc == 0 and "mock" in om and not em.strip(),
          f"rc={rc}", "TOPIC_LLM=mock " + repro_cli(mini, "summarize", 0, "--hops", 2))
    for mode in ("http://example.invalid", "MOCK", "Mock", "off "):
        rc, o, e = cli("summarize", 0, "--hops", 2, data=mini, env={"TOPIC_LLM": mode})
        R.note("F6c", f"TOPIC_LLM={mode!r} → rc={rc} 警告={'有' if 'WARN' in e else '无'} head={o.splitlines()[2][:20] if o else ''}")
    rc, oe, ee = cli("summarize", 0, "--hops", 2, data=mini, env={"TOPIC_LLM": "http://example.invalid"})
    R.inv("S5", "未实现模式：警告 + 回退 mock + exit 0（不触网）",
          rc == 0 and "WARN" in ee and "mock" in oe, f"rc={rc}", "TOPIC_LLM=http://example.invalid "
          + repro_cli(mini, "summarize", 0, "--hops", 2))
    rc, oj, ej = cli("summarize", 0, "--hops", 2, "--json", data=mini, env={"TOPIC_LLM": "http://example.invalid"})
    j = strict_json(oj)
    R.defect("F6", "summarize --json 的 mode 字段报「请求模式」而非实际模式（文本自称 mock）",
             j["mode"] == "http://example.invalid" and "mock" in j["text"],
             f"mode={j['mode']} / text 首行={j['text'].splitlines()[2][:26]}", "TOPIC_LLM=http://example.invalid "
             + repro_cli(mini, "summarize", 0, "--hops", 2, "--json"))
    rc, ou, eu = cli("summarize", 0, "--hops", 2, data=mini, env={"TOPIC_LLM": "MOCK"})
    R.defect("F6b", "TOPIC_LLM 大小写敏感：'MOCK' 走 endpoint 分支 → stderr 警告 + 静默回退（无归一化）",
             rc == 0 and "WARN" in eu, f"rc={rc} stderr={eu.strip()[:60]}",
             "TOPIC_LLM=MOCK " + repro_cli(mini, "summarize", 0, "--hops", 2))
    rc, os_, es = cli("summarize", 0, "--hops", 2, "--strict-llm", data=mini, env={"TOPIC_LLM": "http://x"})
    R.inv("S5", "--strict-llm + 未实现模式 → exit 3 且无 stdout", rc == 3 and not os_.strip(), f"rc={rc}",
          "TOPIC_LLM=http://x " + repro_cli(mini, "summarize", 0, "--hops", 2, "--strict-llm"))
    j1 = jtry(cli("summarize", 0, "--hops", 2, "--json", data=mini)[1])
    R.inv("S5", "summarize --json 的 region_stats 含天然非确定的 elapsed_ms（文本通道不含 → 文本可复现、JSON 不可）",
          bool(j1) and "elapsed_ms" in j1["region_stats"] and "elapsed_ms" not in j1["text"],
          f"JSON 字段={sorted(j1['region_stats']) if j1 else None}", repro_cli(mini, "summarize", 0, "--hops", 2, "--json"))
    argv = ("graph", 0, "--hops", 1, "--json")
    rc, og, eg = cli(*argv, data=mini)
    g = strict_json(og) if rc == 0 else {}
    R.inv("S5", "graph 默认即打印 JSON（--json 参数被静默忽略，不报错）",
          rc == 0 and og.strip().startswith("{") and "layers" not in g, f"rc={rc}", repro_cli(mini, *argv))
    R.defect("F6d", "graph JSON 语义：hops 是请求值而非实际深度；edges[].w 是原始边权而 nodes[].w 是扩散分；无 parent/layer 字段",
             rc == 0 and set(g) == {"seed", "hops", "threshold", "decay", "nodes", "edges", "stats"}
             and g["hops"] == 1 and True,
             f"载荷字段={sorted(g)}；hops={g.get('hops')}（实际深度不可从载荷推出）；"
             f"edges[0].w={g['edges'][0]['w'] if g.get('edges') else None} ∈ 原始边权域",
             repro_cli(mini, *argv))


def sec_search(R, mini, root):
    print("\n[S6] search 排序/匹配/扩展语义（F9 / F10 / F11）")
    j = strict_json(cli("search", "量子", "--json", "--top", 5, data=mini)[1])
    R.inv("S6", "literal_total = 未截断字面命中数（量子 exact + 量子力学 prefix = 2）", j["literal_total"] == 2,
          f"{j['literal_total']}", repro_cli(mini, "search", "量子", "--json"))
    R.inv("S6", "src 档位与 match 一致（exact≥1.0 / prefix≥0.8 / substr）",
          all((h["src"] == "exact") == (h["match"] >= 1.0) for h in j["literal_hits"]), "",
          repro_cli(mini, "search", "量子", "--json"))
    R.inv("S6", "字面命中按 (-w, -match, id) 首排后按 (-w, id) 输出（match 次键被丢弃，仅 w 相同时可见）",
          all(j["literal_hits"][i]["w"] >= j["literal_hits"][i + 1]["w"] for i in range(len(j["literal_hits"]) - 1)), "",
          repro_cli(mini, "search", "量子", "--json"))
    R.inv("S6", "精确整词命中抑制扩展（auto）", strict_json(cli("search", "量子", "--json", data=mini)[1])["expand"]["used"] is False,
          "", repro_cli(mini, "search", "量子", "--json"))
    j2 = strict_json(cli("search", "tp", "--json", data=mini)[1])
    pref = [h for h in j2["literal_hits"] if h["src"] == "prefix"]
    R.defect("F9", "--expand auto 在「前缀命中」时仍触发扩展（argparse help 文案为「无精确/前缀命中时启用」，与实现/行内注释互相矛盾）",
             bool(pref) and j2["expand"]["used"] is True,
             f"前缀命中 {[(h['term'], h['match']) for h in pref]}，expand.used={j2['expand']['used']}",
             repro_cli(mini, "search", "tp", "--json"))
    # N4（独立复核补充）：src 由分数档位反推 → 覆盖率命中的 0.8 被标成 prefix
    R.defect("F18", "src 标签由分数档位反推，覆盖率分支（0.4+0.4·cov）的命中被误标为 prefix（term 既非前缀也非被前缀）",
             any(h["src"] == "prefix" and not h["term"].startswith(j2["normalized"])
                 and not j2["normalized"].startswith(h["term"]) for h in j2["literal_hits"]),
             f"query='tp' → {[(h['term'], h['src'], h['match']) for h in j2['literal_hits']]}"
             f"（smartphone 不含前缀关系，仅 0.4+0.4×cov 命中却标 prefix）",
             repro_cli(mini, "search", "tp", "--json", "--expand", "no"))
    # N1（独立复核补充）：纯 ASCII 词归一为小写，而 nodes 里存大写 → 该词自名不可检索
    argv = ("search", "D9", "--expand", "no", "--json")
    jd = strict_json(cli(*argv, data=mini)[1])
    argv2 = ("around", "--term", "D9", "--hops", 1)
    rc2, out2, err2 = cli(*argv2, data=mini)
    has_d9 = any(n["term"] == "D9" for n in NODES)
    R.defect("F19", "纯 ASCII 词归一为小写、而 nodes.json 存大写（真实数据 349/5187 个 cls 码）→ 用其本名检索/查询均失败",
             has_d9 and jd["literal_total"] == 0 and rc2 != 0,
             f"search D9 → 字面命中 {jd['literal_total']} 个；around --term D9 → rc={rc2} {(out2+err2).strip()[:60]}",
             repro_cli(mini, "search", "D9", "--expand", "no"))
    for bad in ("", " ", "  \t"):
        j3 = strict_json(cli("search", bad, "--json", "--expand", "no", data=mini)[1])
        R.defect("F10", f"空/空白查询 {bad!r} 静默命中全部节点（term.startswith('') 恒真，match=0.8）",
                 j3["literal_total"] == len(NODES) and all(h["match"] == 0.8 for h in j3["literal_hits"]),
                 f"literal_total={j3['literal_total']}（全部 {len(NODES)} 节点，src=prefix，w=0.8·log1p(freq)）",
                 repro_cli(mini, "search", bad, "--top", 1, "--expand", "no"))
    j4 = strict_json(cli("search", "入门", "--json", "--expand", "yes", data=mini)[1])
    if j4["expanded_hits"]:
        e = j4["expanded_hits"][0]
        R.defect("F11", "扩展项 match = 原始 TF-IDF 聚合分（非匹配档位 1.0/0.9/0.8/0.6），w 与字面 w 不同量纲共用一列",
                 e["match"] not in (1.0, 0.9, 0.8, 0.6), f"扩展项 match={e['match']}", repro_cli(mini, "search", "入门", "--json", "--expand", "yes"))
        R.note("F11b", f"mini 图未触发顺序反转（agg={[h['match'] for h in j4['expanded_hits']]}，w={[h['w'] for h in j4['expanded_hits']]}）；专用反例见 specflip")
    else:
        R.defect("F11", "扩展项未产出（fixture 问题）", False, "expanded_hits 为空", repro_self("F11"))
    # F11b 专用反例：agg 排名第一的项被 w=rel(spec/mx)·log1p(freq) 排到末位
    #   题 A（freq=100）出现在 10 张命中卡 → agg=10、spec=agg/√freq=1.0
    #   题 B（freq=1）  出现在  7 张命中卡 → agg=7 、spec=7.0（mx）
    #   → rel: A=1/7=0.143、B=1.0；w: A=0.143·log1p(100)=0.659 < B=1.0·log1p(1)=0.693
    #   → 默认 rank_by=agg 时聚合排名 [A,B]，而展示排序 exp_sorted 变成 [B,A]（自相矛盾）
    flip = write_fixture(root, "specflip",
                         nodes=[{"id": 0, "term": "机器学习", "type": "kw", "freq": 100, "cluster": 1,
                                 "cls": "TP", "sources": ["a"]},
                                {"id": 1, "term": "学", "type": "kw", "freq": 1, "cluster": 1,
                                 "cls": "TP", "sources": ["a"]}],
                         edges=[], ct_override=[[0]] * 10 + [[1]] * 7,
                         xtab=[[i, 3] for i in range(17)])
    argv = ("search", "入门", "--expand", "yes", "--expand-top", 5, "--json")
    rc, out, err = cli(*argv, data=flip)
    jf = jtry(out)
    eh = (jf or {}).get("expanded_hits", [])
    R.defect("F11b", "R1.1：展示顺序按 w=rel(spec/mx)·log1p(freq) 排，而默认聚合排序键是 agg → 展示顺序与聚合排名自相矛盾",
             rc == 0 and len(eh) == 2 and eh[0]["match"] < eh[1]["match"],
             f"expanded_hits 的 agg 序列={[h['match'] for h in eh]}（非降序）、w 序列={[h['w'] for h in eh]}（降序）"
             f"；agg 排名第一（agg=10.0）的项被排到末位", repro_cli(flip, *argv))


def sec_consistency(R, root):
    print("\n[S7] 跨文件一致性 / 隐式假设 / 极值数据（F1 / F12 / F14）")
    oob = write_fixture(root, "edge_oob", edges=EDGES + [(0, 99, 1.0)])
    argv = ("around", 0, "--hops", 1)
    rc, out, err = cli(*argv, data=oob)
    R.defect("F1", "edges 引用越界节点 id → nodes[id] IndexError（无 indices<len(nodes) 校验）",
             rc != 0 and "IndexError" in err,
             f"rc={rc} last={err.strip().splitlines()[-1][:70] if err.strip() else ''}", repro_cli(oob, *argv))
    short = write_fixture(root, "indptr_short", indptr_len=len(NODES))
    argv = ("around", len(NODES) - 1, "--hops", 1)
    rc, out, err = cli(*argv, data=short)
    R.defect("F1c", "indptr 长度 ≠ len(nodes)+1 → IndexError（无 CSR 形状校验）", rc != 0 and "IndexError" in err,
             f"rc={rc} last={err.strip().splitlines()[-1][:70] if err.strip() else ''}", repro_cli(short, *argv))
    sh = write_fixture(root, "shuffled", shuffle_nodes=True)
    argv = ("around", 0, "--hops", 1, "--json")
    rc, out, err = cli(*argv, data=sh)
    jsh = jtry(out)
    term0 = next(n["term"] for n in NODES if n["id"] == 0)
    R.defect("F1d", "nodes.json 顺序 ≠ id 时 nodes[tid] 静默取错节点（隐式假设 list 下标 == id；search 用 n['id'] 不受影响）",
             rc == 0 and jsh is not None and jsh["seed"]["term"] != term0,
             f"seed.term={jsh['seed']['term'] if jsh else None}，id=0 实际 term={term0}", repro_cli(sh, *argv))
    miss = write_fixture(root, "missing_field", drop_node_field="cls")
    argv = ("search", "量子", "--expand", "no")
    rc, out, err = cli(*argv, data=miss)
    R.defect("F1e", "节点缺字段（cls）→ KeyError 崩溃（nodes.json schema 无校验，且 search 与 around 崩溃点不同）",
             rc != 0 and "KeyError" in err,
             f"rc={rc} last={err.strip().splitlines()[-1][:70] if err.strip() else ''}", repro_cli(miss, *argv))
    ip, ix, wt = csr(EDGES, len(NODES))
    wtn = np.array(wt, dtype=np.float32)
    wtn[0] = np.nan
    nan = write_fixture(root, "nanw", weights_override=wtn)
    argv = ("around", 0, "--hops", 1, "--json")
    rc, out, err = cli(*argv, data=nan)
    ok_strict = True
    try:
        strict_json(out)
    except Exception:
        ok_strict = False
    R.defect("F1f", "NaN 边权穿过滤网（`s < threshold` 对 NaN 为 False）→ 输出非严格 JSON（NaN 字面量）",
             rc == 0 and not ok_strict, f"rc={rc} strict={'ok' if ok_strict else 'FAIL'}", repro_cli(nan, *argv))
    gt1 = write_fixture(root, "wgt1", weight_gt1=True)
    argv = ("around", 0, "--hops", 1, "--json")
    rc, out, err = cli(*argv, data=gt1)
    jg = jtry(out)
    R.defect("F14", "边权 >1 → 扩散分 >1（score ≤ 1 / w ∈ [0,1] 契约无文档保证；真实图 max=1.0 故当前不触发）",
             jg is not None and jg["stats"]["weight_max"] > 1.0,
             f"weight_max={jg['stats']['weight_max'] if jg else None}（合成边权 3.0）", repro_cli(gt1, *argv))
    zw = write_fixture(root, "zeroweight", weight_zero_edge=True)
    argv = ("around", 0, "--hops", 2, "--threshold", 0, "--json")
    rc, out, err = cli(*argv, data=zw)
    j = jtry(out)
    lo = [nd["id"] for L in (j or {}).get("layers", []) for nd in L["nodes"] if nd["score"] == 0.0]
    R.defect("F12", "--threshold 0 时 0 权边使 0 分节点入区（`s < threshold` 严格小于；0 分节点计入 visited/layers/evidence/books）",
             bool(j) and bool(lo) and j["stats"]["weight_min"] == 0.0,
             f"0 分节点 {lo}，weight_min={(j or {}).get('stats', {}).get('weight_min')}", repro_cli(zw, *argv))


def sec_traps(R, root):
    print("\n[S8] 代码陷阱 / 死代码（F17）")
    tg = load_tool()
    # (i) cmd_search 首排 (-w,-match,id) 被 lit.sort((-w,id)) 覆盖 → -match 次键永不生效
    #     造 w 精确并列：0.9·log1p(3) == 0.6·log1p(7) == 1.2477；match 高者 id 更大
    tie = write_fixture(root, "tiebreak",
                        nodes=[{"id": 0, "term": "学", "type": "kw", "freq": 7, "cluster": 1, "cls": "TP",
                                "sources": ["a"]},
                               {"id": 1, "term": "量子", "type": "kw", "freq": 3, "cluster": 1, "cls": "TP",
                                "sources": ["a"]}],
                        edges=[], ct_override=[[0], [1]])
    argv = ("search", "量子计算学", "--json", "--expand", "no")
    rc, out, err = cli(*argv, data=tie)
    j = jtry(out)
    hs = (j or {}).get("literal_hits", [])
    R.defect("F17i", "cmd_search 首排键 (-w,-match,id) 被输出前的 lit.sort((-w,id)) 丢弃 → -match 次键是死代码",
             rc == 0 and len(hs) == 2 and hs[0]["w"] == hs[1]["w"] and hs[0]["match"] < hs[1]["match"],
             f"w 并列 {[h['w'] for h in hs]} 但输出顺序 match={[h['match'] for h in hs]}（高匹配项被排到后面；"
             f"若 -match 生效应为 {sorted([h['match'] for h in hs], reverse=True)}）", repro_cli(tie, *argv))
    # (ii) evidence_of(fwd=None) 静默返回空证据
    reg = {"score": {0: 1.0, 1: 0.5}, "parent": {0: None, 1: 0}, "layer": {0: 0, 1: 1}}
    nodes = [{"term": "a"}, {"term": "b"}]
    empty = tg.evidence_of(None, reg, nodes, {0: [0], 1: [1]}, ["m1", "m2"], 5)
    R.defect("F17ii", "evidence_of(..., fwd=None)（签名默认值）静默返回 [] 而非报错/回退——未来调用方会静默丢证据",
             empty == [], f"fwd=None → 返回 {empty}（同参数传 fwd=[[0],[1]] 则返回 2 条）", repro_self("F17"))
    # (iii) load_card_topics(need_mms=False) 无调用方 / per_topic 硬编码
    src = open(CLI["tool"], encoding="utf-8").read()
    R.note("F17iii", f"need_mms=False 分支在源码中无调用方：{src.count('need_mms=False')} 处")
    R.note("F17iv", f"per_topic 硬编码为 evidence_of 默认参数（源码 'per_topic=8' 出现 {src.count('per_topic=8')} 次），无 CLI 开关")
    R.note("F17v", "graph --json 参数被静默忽略（cmd_graph 从不读 args.json）；头 docstring 未记载 R1.1 新增的 --expand-rank")


def sec_real(R):
    print("\n[S9] 真实数据回归（--real）")
    D = DATA_DEFAULT
    tg = load_tool()
    if DEPS_DIR not in sys.path:
        sys.path.insert(0, DEPS_DIR)
    try:
        nodes, _ = tg.load_nodes(D)
        ip, ix, wt = tg.load_edges(D)
    except SystemExit as e:
        R.note("S8", f"跳过：{e}")
        return
    R.inv("S8", "CSR 与 nodes 自洽（indptr=N+1、indices<N、w∈[0,1]、无 NaN）",
          len(ip) == len(nodes) + 1 and int(ix.max()) < len(nodes) and float(wt.min()) >= 0.0
          and float(wt.max()) <= 1.0 and not np.isnan(wt).any(),
          f"N={len(nodes)} indptr={len(ip)} idxMax={int(ix.max())} "
          f"w∈[{float(wt.min()):.3f},{float(wt.max()):.3f}]", repro_self("S8"))
    for hops in (1, 2, 3, 12):
        reg = tg.diffuse(139, hops, ip, ix, wt, 0.86, 0.05, 50000)
        over = [v for v in reg["score"] if v != 139 and tg.path_len(v, reg) > hops]
        R.inv("S8", f"真实图 seed=139 hops={hops} 无超跳（R1 修复③回归）",
              not over and max((tg.path_len(v, reg) for v in reg["score"]), default=0) <= hops,
              f"maxpath={max((tg.path_len(v, reg) for v in reg['score']), default=0)} over={len(over)}",
              "bash acceptance/topics-p4.sh [8]")
    for H in (2, 3, 12):
        reg = tg.diffuse(139, H, ip, ix, wt, 0.86, 0.05, 50000)
        best = best_within_hops(139, H, ip, ix, wt, 0.86, 0.05)
        lower = [v for v in reg["score"] if best.get(v, 0.0) - reg["score"][v] > 1e-9]
        missing = set(best) - set(reg["score"])
        worst = max(lower, key=lambda v: best[v] / max(reg["score"][v], 1e-12)) if lower else None
        R.defect("F4/real", f"真实图 hops={H}：首访定型使 {len(lower)} 个节点分数低于 ≤{H} 跳可达最优，"
                            f"另有 {len(missing)} 个最优可达节点不在 region",
                 bool(lower),
                 f"region={len(reg['score'])}/5187 低估={len(lower)} 缺失={len(missing)}"
                 + (f"；最差 id={worst}「{nodes[worst]['term']}」score={reg['score'][worst]:.4f} "
                    f"vs 可达 {best[worst]:.4f}" if worst is not None else ""), repro_self("S8"))
    argv = ("search", " ", "--top", 1, "--expand", "no")
    rc, out, err = cli(*argv, data=D)
    R.defect("F10/real", "真实数据：空白查询返回全部 5187 个节点（exit 0，无输入校验）",
             "字面命中 5187 个" in out, f"首行={out.splitlines()[0][:70] if out else ''}", repro_cli(D, *argv))
    # N1：大写 cls 词自名不可检索（真实数据）
    from topic_build import normalize_term as _nt                        # 同源归一（DEPS_DIR 已在 sys.path）
    bad_terms = [n for n in nodes if n["term"] != _nt(n["term"])]
    argv = ("search", "D9", "--expand", "no", "--json")
    rc, out, err = cli(*argv, data=D)
    jd = jtry(out)
    argv2 = ("around", "--term", "D9", "--hops", 1)
    rc2, out2, err2 = cli(*argv2, data=D)
    R.defect("F19", f"真实数据：{len(bad_terms)}/{len(nodes)} 个节点（全为大写 cls 码）用其本名检索/查询均失败"
                    f"（term != normalize_term(term)，含 freq 第一的 TP3）",
             len(bad_terms) > 0 and (jd or {}).get("literal_total") == 0 and rc2 != 0,
             f"search D9 → 字面命中 {(jd or {}).get('literal_total')}；around --term D9 → rc={rc2}；"
             f"freq 最高者为 {max(bad_terms, key=lambda n: n['freq'])['term']}", repro_cli(D, "search", "D9", "--expand", "no"))
    # N4：src 误标（真实数据）
    argv = ("search", "tp", "--expand", "no", "--json")
    jt = jtry(cli(*argv, data=D)[1])
    mis_src = [h for h in (jt or {}).get("literal_hits", [])
               if h["src"] == "prefix" and not h["term"].startswith((jt or {}).get("normalized", ""))
               and not (jt or {}).get("normalized", "").startswith(h["term"])]
    R.defect("F18", "真实数据：src 由分数档位反推 → 覆盖率命中的 0.8 被标为 prefix（如 smartphone 之于 tp）",
             bool(mis_src), f"{[(h['term'], h['src'], h['match']) for h in mis_src][:3]}", repro_cli(D, "search", "tp", "--expand", "no"))
    for q in ("tp", "机器学习"):
        argv = ("search", q, "--json")
        rc, out, err = cli(*argv, data=D)
        j = strict_json(out)
        pref = [h for h in j["literal_hits"] if h["src"] == "prefix"]
        R.defect("F9/real", f"真实数据查询「{q}」：字面命中 {j['literal_total']} 条（前缀 {len(pref)}）仍触发近词扩展",
                 j["expand"]["used"] is True,
                 f"expand={j['expand']} expanded={len(j['expanded_hits'])} elapsed_ms={j['elapsed_ms']}",
                 repro_cli(D, *argv))
        t_no = strict_json(cli("search", q, "--json", "--expand", "no", data=D)[1])["elapsed_ms"]
        R.note("F9/real", f"「{q}」auto={j['elapsed_ms']}ms vs --expand no={t_no}ms（差值 = 读 188,512 行 card_topics + TF-IDF 乘法）")
        if j["expanded_hits"]:
            aggs = [h["match"] for h in j["expanded_hits"]]
            R.defect("F11b/real", f"真实数据「{q}」：默认 rank_by=agg，但展示顺序按 w=rel(spec/mx)·log1p(freq) 排",
                     aggs != sorted(aggs, reverse=True),
                     f"expanded_hits 的 agg 序列={aggs}（应降序）；w 序列={[h['w'] for h in j['expanded_hits']]}"
                     f"；rank_key={j['expand'].get('rank_key')}", repro_cli(D, "search", q, "--json"))
            R.inv("S8", f"真实数据「{q}」扩展项含 R1.1 新字段 spec/rel_agg",
                  {"spec", "rel_agg"} <= set(j["expanded_hits"][0]), f"{sorted(j['expanded_hits'][0])}",
                  repro_cli(D, "search", q, "--json"))


def load_tool():
    if not os.path.exists(CLI["tool"]):
        print(f"环境不可用：找不到 {CLI['tool']}", file=sys.stderr)
        sys.exit(2)
    d = os.path.dirname(os.path.abspath(CLI["tool"]))
    for p in (PYLIBS, d, DEPS_DIR):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location("topic_graph_audit", CLI["tool"])
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    ap = argparse.ArgumentParser(description="topic_graph.py 内存反例集")
    ap.add_argument("--tool", default=os.environ.get("TOPIC_GRAPH_TOOL", TOOL_DEFAULT))
    ap.add_argument("--only", default=None, help="只跑指定发现 id（逗号分隔，如 F1,F5,S8）")
    ap.add_argument("--real", action="store_true", help="追加真实数据回归（S8）")
    ap.add_argument("--keep", action="store_true", help="保留合成数据目录")
    ap.add_argument("--strict", action="store_true", help="缺陷未复现时也返回非 0")
    a = ap.parse_args()
    sys.dont_write_bytecode = True
    CLI["tool"] = os.path.abspath(os.path.expanduser(a.tool))
    R = Rep(only=(a.only.split(",") if a.only else None))
    fixbase = os.path.join(os.path.dirname(CLI["self"]), ".fixtures")   # 合成数据只落在 audit/graph/ 内
    os.makedirs(fixbase, exist_ok=True)
    for stale in os.listdir(fixbase):                                # 清理上次被中断的 run-*（如 SIGTERM）
        if stale.startswith("run-"):
            shutil.rmtree(os.path.join(fixbase, stale), ignore_errors=True)
    root = tempfile.mkdtemp(prefix="run-", dir=fixbase)
    print(f"=== AUDIT-GRAPH 内存反例集 ===\ntool={CLI['tool']}\nfixtures={root}")
    try:
        mini = write_fixture(root, "mini")
        sec_invariants(R, mini)
        sec_guards(R, mini)
        sec_extremes(R, mini)
        sec_evidence(R, root, mini)
        sec_stub(R, mini)
        sec_search(R, mini, root)
        sec_consistency(R, root)
        sec_traps(R, root)
        if a.real:
            sec_real(R)
    finally:
        if a.keep:
            print(f"[fixtures 保留] {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
            try:
                os.rmdir(fixbase)                                     # 空目录顺手清掉
            except OSError:
                pass
    print("\n=== 汇总 ===")
    print(f"INVARIANT 违例 : {len(R.viol)}")
    for v in R.viol:
        print(f"  x {v[0]} {v[1]} — {v[2]}")
    print(f"缺陷确认       : {len(R.conf)}")
    for c in R.conf:
        print(f"  * {c[0]} {c[1]}")
    print(f"缺陷未复现     : {len(R.norep)}")
    for n in R.norep:
        print(f"  ? {n[0]} {n[1]} — {n[2]}")
    print(f"备注           : {len(R.info)}")
    bad = bool(R.viol) or (a.strict and bool(R.norep))
    print(f"AUDIT-GRAPH: {'FAIL' if bad else 'OK'}（invariant 违例 {len(R.viol)} / 缺陷确认 {len(R.conf)}）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
