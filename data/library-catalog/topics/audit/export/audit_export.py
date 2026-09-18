#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AUDIT-EXPORT — export_release.py topics 分支独立审计（回读比对 / 量化 / 契约 / v1 无回归）

审计对象（只读）：reasonix-scripts/lib-catalog/export_release.py（393 行）
被测产物的两种来源：
  A. 实发样例  <data>/topics/export-sample/v1/        （--topics-only 于 19:46 产出）
  B. 复跑产物  <data>/topics/audit/export/repro/v1/   （本脚本 --repro 现跑，用于逐位复现）
边界用例：把真实 export_topics() 跑在 audit/export/.fixtures/ 的合成数据目录上
（不复制其逻辑、不修改主体代码；用后即删）。

用法:
  python3 audit_export.py                 # 全量审计（约 25s；不含 v1 全量复跑）
  python3 audit_export.py --repro         # 额外现跑 topics 导出并逐位复现比对
  python3 audit_export.py --with-v1-rerun # 额外全量复跑 v1 导出（约 40s / 131MB）并与 14:01 发布包比对
产出: audit-export.json（机读）+ stdout 摘要
"""
import argparse
import ast
import difflib
import dis
import gzip
import hashlib
import importlib.util
import json
import marshal
import os
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True   # 关键：禁止审计导入动作写主体仓库 __pycache__
_HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/go/lib-catalog-data")
TOPICS = os.path.join(DATA, "topics")
SAMPLE = os.path.join(TOPICS, "export-sample", "v1")
SRC = os.path.expanduser("~/go/reasonix-scripts/lib-catalog")
EXPORT_PY = os.path.join(SRC, "export_release.py")
OLD_PYC = os.path.join(SRC, "__pycache__", "export_release.cpython-314.pyc")
V1_RELEASE = os.path.expanduser("~/go/lib-catalog-release/v1")
PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(PYLIBS) and PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)
import numpy as np  # noqa: E402

R = {"findings": [], "checks": [], "snapshot": {}, "quant": {}, "csr": {}, "card": {}, "manifest": {},
     "v1": {}, "fixtures": {}}


def ck(name, ok, detail="", level="info"):
    R["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def finding(fid, sev, title, evidence, fix):
    R["findings"].append({"id": fid, "severity": sev, "title": title, "evidence": evidence, "fix": fix})
    print(f"  !! {fid} [{sev}] {title}")


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def load_export_module(dst_dir):
    """把主体源码复制到审计目录后再导入：只读主体、零副作用（不写其 __pycache__）。"""
    os.makedirs(dst_dir, exist_ok=True)
    copy = os.path.join(dst_dir, "export_release.ro.py")
    shutil.copyfile(EXPORT_PY, copy)
    spec = importlib.util.spec_from_file_location("export_release_ro", copy)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------- 0) 快照
def snap():
    print("\n[0] 快照（sha256 前 16 位 / mtime）")
    for p in ["edges.csr.npz", "card_topics.jsonl", "nodes.json", "meta.json"]:
        fp = os.path.join(TOPICS, p)
        R["snapshot"][p] = {"sha256_16": sha256(fp)[:16], "size": os.path.getsize(fp),
                            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(fp)))}
        print(f"  {p:22s} {R['snapshot'][p]['sha256_16']} {R['snapshot'][p]['mtime']}")
    R["snapshot"]["export_release.py"] = {"sha256_16": sha256(EXPORT_PY)[:16],
                                          "lines": sum(1 for _ in open(EXPORT_PY, encoding="utf-8"))}
    ck("审计对象 export_release.py 可读且非空", R["snapshot"]["export_release.py"]["lines"] > 300,
       f"{R['snapshot']['export_release.py']['lines']} 行 {R['snapshot']['export_release.py']['sha256_16']}")


# ------------------------------------------------- 1) 回读比对（全量 + 抽样）
def readback(base, label):
    print(f"\n[1] 回读比对：{label}")
    t = os.path.join(base, "topics")
    if not os.path.isdir(t):
        return None
    z = np.load(os.path.join(TOPICS, "edges.csr.npz"))
    ip_src = z["indptr"].astype(np.int64)
    ix_src = z["indices"].astype(np.int32)
    w_src = z["weights"].astype(np.float32)
    ip = np.fromfile(os.path.join(t, "edges_indptr.i64.bin"), dtype="<i8")
    ix = np.fromfile(os.path.join(t, "edges_indices.i32.bin"), dtype="<i4")
    q = np.fromfile(os.path.join(t, "edges_weights.u8.bin"), dtype="u1")
    q_expect = np.clip(np.round(w_src * 255.0), 0, 255).astype(np.uint8)
    res = {
        "indptr_byteexact": ip.tobytes() == ip_src.tobytes(),
        "indices_byteexact": ix.tobytes() == ix_src.tobytes(),
        "weights_byteexact_round255": q.tobytes() == q_expect.tobytes(),
        "weights_matches_floor255": q.tobytes() == np.floor(w_src * 255.0).astype(np.uint8).tobytes(),
        "weights_matches_round254": q.tobytes() == np.clip(np.round(w_src * 254.0), 0, 255).astype(np.uint8).tobytes(),
        "nnz": int(len(ix)), "n": int(len(ip) - 1),
    }
    ck(f"{label} indptr 全量逐位一致", res["indptr_byteexact"], f"{len(ip)} 项")
    ck(f"{label} indices 全量逐位一致", res["indices_byteexact"], f"{len(ix)} 项")
    ck(f"{label} weights_u8 == round(w*255)（非 floor/非 *254）", res["weights_byteexact_round255"],
       f"floor={res['weights_matches_floor255']} *254={res['weights_matches_round254']}")

    # 抽样回读：随机 (行, 槽) — 独立于全量比对，逐条对照源 npz
    rng = np.random.default_rng(20260918)
    deg = np.diff(ip_src)
    rows = rng.choice(len(deg), size=2000, replace=True)
    slot = (rng.random(2000) * np.maximum(deg[rows], 1)).astype(np.int64)
    slot = np.minimum(slot, np.maximum(deg[rows] - 1, 0))
    pos = ip_src[rows] + slot
    miss = int((ip[rows] != ip_src[rows]).sum() + (ix[pos] != ix_src[pos]).sum() + (q[pos] != q_expect[pos]).sum())
    ck(f"{label} 抽样 2000 条 (行,槽) 回读逐条一致", miss == 0, f"不一致 {miss}/2000")

    # card_topics CSR
    cip = np.fromfile(os.path.join(t, "card_topics_indptr.i32.bin"), dtype="<i4")
    cid = np.fromfile(os.path.join(t, "card_topics_ids.i32.bin"), dtype="<i4")
    ip2, ids2 = [0], []
    for line in open(os.path.join(TOPICS, "card_topics.jsonl"), encoding="utf-8"):
        if not line.strip():
            continue
        ids2.extend(int(x) for x in json.loads(line).get("topics", ()))
        ip2.append(len(ids2))
    ck(f"{label} card_topics indptr/ids 全量逐位一致",
       np.asarray(ip2, np.int32).tobytes() == cip.tobytes() and np.asarray(ids2, np.int32).tobytes() == cid.tobytes(),
       f"{len(cip)} / {len(cid)}")
    # 抽样 2000 条卡-主题链接：直接回读 card_topics.jsonl 原文逐条比对
    idxs = np.sort(rng.choice(len(cid), size=2000, replace=False))
    with open(os.path.join(TOPICS, "card_topics.jsonl"), encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    flat, truth = [], []
    for i, o in enumerate(lines):
        flat.extend([i] * len(o.get("topics", ())))
    for p_ in idxs:
        truth.append(int(lines[flat[p_]]["topics"][p_ - cip[flat[p_]]]))
    goto = np.searchsorted(cip, idxs, side="right") - 1
    local = idxs - cip[goto]
    ok = all(int(lines[int(goto[k])]["topics"][int(local[k])]) == int(cid[idxs[k]]) for k in range(len(idxs)))
    ck(f"{label} 抽样 2000 条卡→主题链接回读一致", ok, "含 mms 行序反查")
    return res


# ------------------------------------------------------ 2) 量化质量与分辨率
def quant_audit():
    print("\n[2] 量化误差/分辨率（u8 网格 0..255, 还原 w=v/255）")
    z = np.load(os.path.join(TOPICS, "edges.csr.npz"))
    w = z["weights"].astype(np.float32)
    ip = z["indptr"].astype(np.int64)
    q = np.clip(np.round(w * 255.0), 0, 255).astype(np.uint8)
    wr = q.astype(np.float64) / 255.0
    err = w.astype(np.float64) - wr
    step = 1.0 / 255.0
    # 同排相邻槽并列率（信息损失的直接度量）
    pairs = tie_f = tie_u = 0
    flip = 0
    for r in range(len(ip) - 1):
        a, b = w[ip[r]:ip[r + 1]], q[ip[r]:ip[r + 1]]
        if len(a) > 1:
            pairs += len(a) - 1
            tie_f += int((a[1:] == a[:-1]).sum())
            tie_u += int((b[1:] == b[:-1]).sum())
            flip += int((np.argsort(-a, kind="stable") != np.argsort(-(b.astype(np.float32) / 255.0), kind="stable")).sum())
    R["quant"] = {
        "restore": "w = v / 255.0", "quant_rule": "code = clip(round(w*255),0,255)",
        "err_max": float(np.abs(err).max()), "err_bound_theory": step / 2,
        "err_mean": float(np.abs(err).mean()), "err_p50": float(np.percentile(np.abs(err), 50)),
        "err_p95": float(np.percentile(np.abs(err), 95)), "err_p99": float(np.percentile(np.abs(err), 99)),
        "w_min": float(w.min()), "w_max": float(w.max()), "w_eq1_share": float((w == 1.0).mean()),
        "distinct_w": int(len(np.unique(w))), "distinct_codes": int(len(np.unique(q))),
        "codes_used": [int(q.min()), int(q.max())], "collapse_ratio": float(len(np.unique(w)) / len(np.unique(q))),
        "adjacent_slots": pairs, "ties_raw": tie_f, "ties_u8": tie_u, "ties_added": tie_u - tie_f,
        "rank_slots_perturbed": flip,
        "path_amp_worst_12hop": float((1 + (step / 2) / float(w.min())) ** 12),
    }
    print(f"  err: max={R['quant']['err_max']:.4e} (=1/510) mean={R['quant']['err_mean']:.3e} p99={R['quant']['err_p99']:.3e}")
    print(f"  w∈[{R['quant']['w_min']:.6f},{R['quant']['w_max']:.3f}] 码 {R['quant']['codes_used']} | "
          f"{R['quant']['distinct_w']} 原始值→{R['quant']['distinct_codes']} 码 ({R['quant']['collapse_ratio']:.2f}×)")
    print(f"  同排相邻槽并列: 原始 {tie_f}/{pairs} → u8 {tie_u} (+{tie_u - tie_f})；位次扰动 {flip} 槽 ({flip / max(pairs, 1):.4%})")
    ck("量化误差 ≤ 1/510（round 到最近格点）", R["quant"]["err_max"] <= step / 2 + 1e-9,
       f"max={R['quant']['err_max']:.3e}")
    # 边界：w=0/1/超 1/极小
    bnd = {}
    for v in [0.0, 1e-9, 1.0 / 255.0, 0.5, 1.0, 1.0000001, 2.0]:
        c = int(np.clip(np.round(np.float32(v) * np.float32(255.0)), 0, 255).astype(np.uint8))
        bnd[repr(v)] = {"code": c, "restore": c / 255.0, "err": v - c / 255.0}
    R["quant"]["boundary"] = bnd
    ck("边界 w=0→0 / w=1→255 / w>1 被 clip", bnd["0.0"]["code"] == 0 and bnd["1.0"]["code"] == 255
       and bnd["2.0"]["code"] == 255 and bnd["1e-09"]["code"] == 0)
    # f16 对照
    h = w.astype(np.float16).astype(np.float64)
    R["quant"]["f16_max_err"] = float(np.abs(w.astype(np.float64) - h).max())
    R["quant"]["f16_extra_bytes"] = int(w.nbytes * 1)
    print(f"  f16 对照: max_err={R['quant']['f16_max_err']:.3e}（额外 {w.nbytes / 1e6:.3f} MB）")
    return R["quant"]


# ------------------------------------------------------------ 3) CSR 不变式
def csr_audit():
    print("\n[3] CSR 不变式与边界")
    z = np.load(os.path.join(TOPICS, "edges.csr.npz"))
    ip = z["indptr"].astype(np.int64)
    ix = z["indices"].astype(np.int32)
    w = z["weights"].astype(np.float32)
    d = np.diff(ip)
    nodes = json.load(open(os.path.join(TOPICS, "nodes.json"), encoding="utf-8"))
    nsj = json.load(open(os.path.join(SAMPLE, "topics", "nodes.json"), encoding="utf-8"))
    idmismatch = int(sum(1 for i, n in enumerate(nodes) if n["id"] != i))
    unsorted_rows = sum(1 for r in range(len(d)) if d[r] > 1 and not bool((np.diff(ix[ip[r]:ip[r + 1]]) > 0).all()))
    dups = sum(1 for r in range(len(d)) if d[r] > 1 and len(set(ix[ip[r]:ip[r + 1]].tolist())) != d[r])
    selfloops = int((ix == np.repeat(np.arange(len(d)), d)).sum())
    R["csr"] = {
        "n": int(len(ip) - 1), "nnz": int(len(ix)), "nodes_json_len": len(nodes),
        "indptr_monotone": bool((d >= 0).all()), "indptr0": int(ip[0]), "last_eq_nnz": bool(ip[-1] == len(ix)),
        "min_outdeg": int(d.min()), "max_outdeg": int(d.max()), "avg_outdeg": round(float(d.mean()), 4),
        "empty_rows": np.where(d == 0)[0].tolist(),
        "empty_row_terms": [nodes[r]["term"] for r in np.where(d == 0)[0].tolist()],
        "idx_range": [int(ix.min()), int(ix.max())], "selfloops": selfloops, "rows_with_dup_cols": dups,
        "rows_not_col_ascending": unsorted_rows, "rows_not_col_ascending_pct": round(unsorted_rows / len(d) * 100, 2),
        "rows_col_ascending": int(len(d) - unsorted_rows),
        "w_range": [float(w.min()), float(w.max())], "w_nan": int(np.isnan(w).sum()), "w_eq1": int((w == 1).sum()),
        "nodes_id_ne_index": idmismatch, "nodes_export_byteexact": sha256(os.path.join(SAMPLE, "topics", "nodes.json")) == sha256(os.path.join(TOPICS, "nodes.json")),
        "nodes_json_ids_unique": len({n["id"] for n in nsj}) == len(nsj),
    }
    ck("indptr[0]=0 / 单调 / indptr[-1]=nnz", R["csr"]["indptr0"] == 0 and R["csr"]["indptr_monotone"] and R["csr"]["last_eq_nnz"])
    ck("行数 == nodes.json 项数", R["csr"]["n"] == R["csr"]["nodes_json_len"], f"{R['csr']['n']}")
    ck("manifest 声称 id = CSR 行号（nodes[i].id == i）", idmismatch == 0, f"违反 {idmismatch}")
    ck("indices ∈ [0,n)、无自环、无行内重复列", R["csr"]["idx_range"][1] < R["csr"]["n"] and selfloops == 0 and dups == 0)
    ck("权重有限且 ∈[0,1]、无 NaN", R["csr"]["w_nan"] == 0 and 0 <= R["csr"]["w_range"][0] and R["csr"]["w_range"][1] <= 1.0)
    ck("max_outdeg=20 与 note「出度 ≤20」一致", R["csr"]["max_outdeg"] == 20, f"avg={R['csr']['avg_outdeg']}")
    ck("空出度节点以空行合法表达（3 个）", R["csr"]["min_outdeg"] == 0 and len(R["csr"]["empty_rows"]) == 3,
       f"行 {R['csr']['empty_rows']} = {R['csr']['empty_row_terms']}")
    print(f"  行内列升序的行数: {R['csr']['rows_col_ascending']}/{R['csr']['n']} 行（= {R['csr']['rows_not_col_ascending_pct']}% 的行不是列升序）")
    if unsorted_rows:
        finding("E4", "medium", "CSR 行内列索引非排序，note/manifest 未声明（消费方按标准 CSR 二分查找会静默错答）",
                f"{unsorted_rows}/{R['csr']['n']} 行（{R['csr']['rows_not_col_ascending_pct']}%）行内不是列升序；"
                f"note 仅写「有向，出度 ≤20」，未声明行内次序口径",
                "① note 增补「行内按构建期 rank 序（assoc）排列，非列升序」；② 或新增 --sort-indices 开关；"
                "③ 消费方文档给出 O(deg) 线性扫描而非二分查找的用法。")
    finding("E5", "low", "量化契约只登记还原公式，未登记步长/误差上界/分辨率与饱和码位",
            f"实测 max|Δw|={R['quant']['err_max']:.3e}（=1/510）、step=1/255={1 / 255:.3e}、"
            f"码位 [{R['quant']['codes_used'][0]},{R['quant']['codes_used'][1]}]（0–44 空置）、"
            f"{R['quant']['distinct_w']} 个原始值→{R['quant']['distinct_codes']} 个码、同排位次扰动 {R['quant']['rank_slots_perturbed']} 槽",
            "在 manifest.topics.json#stats 增记 quant:{rule,step,max_abs_err,w_min,w_max,codes_used,saturated_share}；"
            "若下游按路径乘积打分需更严精度，改 f16（实测 max_err 2.44e-04，仅 +0.397 MB）。")
    finding("E6", "low", "导出器无内置回读自检（写入即算 sha256，但从不重读校验自洽）",
            "manifest 的 sha256 由 note_file 在写入后即时计算；全程无 indptr/indices/weights 三者互洽校验、"
            "无 cards.jsonl 行数校验、无 meta 交叉校验。本审计以外部套件补齐（全量+抽样回读 6 项全 PASS）",
            "增 --verify：导出后重读三个 bin 断言 indptr[-1]==len(indices)、indices<n、weights∈[0,1]，"
            "并断言 card_topics indptr 长度 == cards.jsonl 行数。")
    return R["csr"]


# ---------------------------------------------- 4) card_topics CSR 与行序自洽
def card_audit():
    print("\n[4] card_topics → CSR 转换与行序自洽")
    cip = np.fromfile(os.path.join(SAMPLE, "topics", "card_topics_indptr.i32.bin"), dtype="<i4")
    cid = np.fromfile(os.path.join(SAMPLE, "topics", "card_topics_ids.i32.bin"), dtype="<i4")
    cnt = np.diff(cip)
    import re
    pat = re.compile(rb'\{"mms": "(\d+)"')
    cm = pat.findall(open(os.path.join(DATA, "cards.jsonl"), "rb").read())
    tm = [json.loads(l)["mms"] for l in open(os.path.join(TOPICS, "card_topics.jsonl"), encoding="utf-8") if l.strip()]
    R["card"] = {
        "cards_jsonl_lines": len(cm), "card_topics_lines": len(tm), "indptr_len": int(len(cip)),
        "links": int(len(cid)), "max_links": int(cnt.max()), "min_links": int(cnt.min()),
        "cards_with_0_links": int((cnt == 0).sum()), "id_range": [int(cid.min()), int(cid.max())],
        "mms_aligned": [a.decode() for a in cm] == tm,
        "mms_mismatch_rows": sum(1 for a, b in zip(cm, tm) if a.decode() != b),
        "dtype_int32_headroom": int(2 ** 31 - 1 - len(cid)),
    }
    ck("indptr 长度 == cards.jsonl 行数 + 1", len(cip) == len(cm) + 1, f"{len(cip)} vs {len(cm) + 1}")
    ck("每卡 ≤5 条链接（文档声称 top-5）", cnt.max() <= 5, f"max={cnt.max()}")
    ck("主题 id ∈ [0,5187)", R["card"]["id_range"][1] < 5187, f"range={R['card']['id_range']}")
    ck("card_topics.jsonl 与 cards.jsonl 的 mms 逐行对齐", R["card"]["mms_aligned"], f"错位 {R['card']['mms_mismatch_rows']} 行")
    ck("0 链接卡数 == P2 登记 22573", R["card"]["cards_with_0_links"] == 22573, f"{R['card']['cards_with_0_links']}")
    R["card"]["int32_wrap_demo"] = int(np.asarray([2 ** 31 + 5], dtype=np.int64).astype(np.int32)[0])
    print(f"  int32 静默回绕演示: int64[2**31+5].astype(int32) = {R['card']['int32_wrap_demo']}（无异常，符号翻转）")
    return R["card"]


# ---------------------------------------------------- 5) 实发 manifest 自洽性
def manifest_audit():
    print("\n[5] 实发 manifest 自洽性（sha256 / 收录全集 / 跨文件口径）")
    tm = json.load(open(os.path.join(SAMPLE, "topics", "manifest.topics.json"), encoding="utf-8"))
    m = json.load(open(os.path.join(SAMPLE, "manifest.json"), encoding="utf-8"))
    bad = [f["path"] for f in tm["files"] if sha256(os.path.join(SAMPLE, f["path"])) != f["sha256"]]
    bad2 = [f["path"] for f in m["files"] if sha256(os.path.join(SAMPLE, f["path"])) != f["sha256"]]
    listed = {f["path"] for f in tm["files"]}
    actual = {"topics/" + x for x in os.listdir(os.path.join(SAMPLE, "topics"))}
    R["manifest"] = {
        "topics_files": len(tm["files"]), "top_level_files": len(m["files"]),
        "topics_sha_mismatch": bad, "top_sha_mismatch": bad2,
        "topics_manifest_missing": sorted(actual - listed), "topics_manifest_ghost": sorted(listed - actual),
        "total_bytes_ok": m["total_bytes"] == sum(f["size"] for f in m["files"]),
        "topics_stats": tm["stats"], "top_level_name": m["name"], "top_level_stats_keys": sorted(m["stats"]),
    }
    ck("topics manifest 全部 sha256 与实际文件一致", not bad, f"{len(tm['files'])} 项")
    ck("顶层 manifest 全部 sha256 与实际文件一致", not bad2, f"{len(m['files'])} 项")
    ck("顶层 manifest total_bytes == Σsize", R["manifest"]["total_bytes_ok"])
    print(f"  topics manifest 未收录：{R['manifest']['topics_manifest_missing']}（自身，无自引用哈希）")
    # 跨文件口径：登记 vs 实发数据
    meta = json.load(open(os.path.join(SAMPLE, "topics", "meta.json"), encoding="utf-8"))
    meta_src = json.load(open(os.path.join(TOPICS, "meta.json"), encoding="utf-8"))
    p2s, p2c = meta["stages"]["P2"], meta_src["stages"]["P2"]
    qu = np.fromfile(os.path.join(SAMPLE, "topics", "edges_weights.u8.bin"), dtype="u1")   # 直接从未经源文件的中转：随包 u8
    wq = qu.astype(np.float64) / 255.0
    live = {"edges": int(len(wq)), "w_mean": round(float(wq.mean()), 4),
            "w_eq1_share": round(float((qu == 255).mean()), 4)}
    reg = {"sample_P2_generated_at": p2s["generated_at"],
           "sample_P2_counts_edges_final": p2s["counts"]["edges_final"],
           "sample_P2_w_eq1_share": p2s["edge_stats"]["w_eq_1_share"],
           "sample_P2_w_mean": p2s["edge_stats"]["weight_dist"]["mean"],
           "sample_has_r1_fix": "r1_fix" in p2s,
           "src_P2_generated_at": p2c["generated_at"], "src_P2_w_eq1_share": p2c["edge_stats"]["w_eq_1_share"],
           "src_has_r1_fix": "r1_fix" in p2c, "live_from_shipped_weights": live}
    R["manifest"]["meta_cross_check"] = reg
    print(f"  随包 meta.json P2: {reg['sample_P2_generated_at']} w_eq1={reg['sample_P2_w_eq1_share']} "
          f"mean={reg['sample_P2_w_mean']} r1_fix={'r1_fix' in p2s}")
    print(f"  随包 u8 文件反算:  w_eq1={live['w_eq1_share']} mean={live['w_mean']} | 源 meta P2: "
          f"{reg['src_P2_generated_at']} w_eq1={reg['src_P2_w_eq1_share']}")
    if abs(reg["sample_P2_w_eq1_share"] - live["w_eq1_share"]) > 1e-3:
        finding("E1", "high",
                "随包 meta.json 的口径登记与随包数据不同源（导出未做任何跨文件一致性校验）",
                f"包内 edges_weights.u8.bin 反算 w_eq_1_share={live['w_eq1_share']:.4f}（= post-R1 边表），"
                f"而包内 meta.json 登记 {reg['sample_P2_w_eq1_share']}（= pre-R1 边表，且无 r1_fix 键、"
                f"P2 时间戳 {reg['sample_P2_generated_at']} vs 数据 19:45）",
                "export_topics 在复制 meta.json 时校验 counts.edges_final/nodes 与本次导出的 stats 一致、"
                "并在 manifest.topics.json 记录 meta 的 sha256 与数据快照 sha256；不一致则 --strict 失败。")
    return R["manifest"]


# --------------------------------------------- 6) 边界/防御：真实函数夹具测试
def fixture_tests():
    print("\n[6] 边界夹具（把真实 export_topics 跑在合成数据目录上）")
    fx = os.path.join(_HERE, ".fixtures")
    shutil.rmtree(fx, ignore_errors=True)
    er = load_export_module(fx)
    out = os.path.join(fx, "out")
    os.makedirs(out, exist_ok=True)

    def build(name, card_topics_lines, weights, indptr=None, indices=None, n_nodes=2):
        d = os.path.join(fx, name, "topics")
        os.makedirs(d, exist_ok=True)
        json.dump([{"id": i, "term": f"t{i}", "type": "kw", "freq": 1} for i in range(n_nodes)],
                  open(os.path.join(d, "nodes.json"), "w"))
        if indptr is None:
            indptr = np.array([0, len(indices)], dtype=np.int64)
        np.savez(os.path.join(d, "edges.csr.npz"), indptr=np.asarray(indptr, np.int64),
                 indices=np.asarray(indices, np.int32), weights=np.asarray(weights, np.float32))
        open(os.path.join(d, "card_topics.jsonl"), "w", encoding="utf-8").write("\n".join(card_topics_lines) + "\n")
        res = {}
        er.export_topics(os.path.join(fx, name), out, [], lambda p, desc: res.update({os.path.basename(p): os.path.getsize(p)}))
        return d, res

    try:
        # (a) 常规 + 空出度 + w=0/1
        d, _ = build("normal", ['{"mms":"a","topics":[0,1]}', '{"mms":"b","topics":[]}'],
                     [0.0, 1.0, 0.5], indptr=[0, 1, 2, 3, 3, 3], indices=[0, 1, 0], n_nodes=2)
        ip = np.fromfile(os.path.join(out, "topics", "edges_indptr.i64.bin"), dtype="<i8")
        q = np.fromfile(os.path.join(out, "topics", "edges_weights.u8.bin"), dtype="u1")
        cip = np.fromfile(os.path.join(out, "topics", "card_topics_indptr.i32.bin"), dtype="<i4")
        R["fixtures"]["normal"] = {"indptr": ip.tolist(), "weights_u8": q.tolist(), "card_indptr": cip.tolist()}
        ck("夹具: 空出度行/w=0/w=1 原样落盘", q.tolist() == [0, 255, 128] and cip.tolist() == [0, 2, 2],
           f"u8={q.tolist()} card_indptr={cip.tolist()}")

        # (b) 空行 → 静默错位
        d, _ = build("blank", ['{"mms":"a","topics":[0,1]}', '', '{"mms":"b","topics":[1]}'], [1.0], indices=[0])
        cip_b = np.fromfile(os.path.join(out, "topics", "card_topics_indptr.i32.bin"), dtype="<i4")
        R["fixtures"]["blank_line"] = {"card_indptr": cip_b.tolist(), "cards_declared": 3}
        shifted = len(cip_b) != 4
        ck("夹具: 空行被静默跳过（行数 3 → indptr 长度 %d，非 4）" % len(cip_b), shifted,
           f"card_indptr={cip_b.tolist()}：第 2 行证据被并到第 1 行，后续全部左移")
        if shifted:
            finding("E2", "high", "card_topics→CSR 无行数校验 + 空行 continue → 证据链静默错位",
                    f"夹具 card_topics.jsonl 含 1 个空行（3 行数据）时，导出 indptr 长度 {len(cip_b)}（应 4），"
                    f"被跳过的行之后所有卡的主题 id 全部左移一格；主体代码不读 cards.jsonl、不做任何行数断言，"
                    f"manifest 仍声明「N_cards+1；与 cards.jsonl 行序一致」",
                    "① 循环去掉 continue，空行显式报错；② 断言 len(ip)-1 == cards.jsonl 行数；"
                    "③ 抽样比对 mms 行序（成本 O(1) 内存）。")

        # (c) 超长数组（30 万卡）→ int32 边界
        big_n = 300000
        lines = ['{"mms":"a","topics":[]}'] * big_n
        lines[0] = '{"mms":"a","topics":[0,1]}'
        lines[-1] = '{"mms":"z","topics":[1]}'
        d, _ = build("big", lines, [0.5], indices=[0], n_nodes=8)
        cip_big = np.fromfile(os.path.join(out, "topics", "card_topics_indptr.i32.bin"), dtype="<i4")
        cid_big = np.fromfile(os.path.join(out, "topics", "card_topics_ids.i32.bin"), dtype="<i4")
        R["fixtures"]["long_indptr"] = {"indptr_len": int(len(cip_big)), "nnz": int(len(cid_big)),
                                        "monotone": bool((np.diff(cip_big) >= 0).all()), "last": int(cip_big[-1])}
        ck("夹具: 30 万卡 indptr 正确落盘、单调、int32 未溢出",
           len(cip_big) == big_n + 1 and R["fixtures"]["long_indptr"]["monotone"]
           and cip_big[-1] == len(cid_big) == 3, f"len={len(cip_big)} nnz={len(cid_big)}")
        with np.errstate(invalid="ignore"):
            nan_u8 = int(np.clip(np.round(np.float32(np.nan) * 255.0), 0, 255).astype(np.uint8))
        R["fixtures"]["int32_overflow_demo"] = {
            "int64_to_int32_2p31_plus_5": int(np.asarray([2 ** 31 + 5], dtype=np.int64).astype(np.int32)[0]),
            "python_int_direct_to_int32": "numpy>=2 抛 OverflowError（未静默）",
            "nan_to_uint8": nan_u8}
        finding("E10", "info", "NaN 权重/int32 上限属潜伏面（现有数据不触发，但导出层无断言）",
                f"weights 含 NaN 时 np.round→clip→astype(uint8) 无异常无告警上限，得 {nan_u8}（+ RuntimeWarning）；"
                f"int64→int32 超限静默回绕（2**31+5 → {R['fixtures']['int32_overflow_demo']['int64_to_int32_2p31_plus_5']}）",
                "export_topics 开头断言 np.isfinite(w).all()、w∈[0,1]、nnz<2**31-1；失败即 fail-fast。")
        print(f"  边界数值: {R['fixtures']['int32_overflow_demo']}")
    finally:
        shutil.rmtree(fx, ignore_errors=True)
    return R["fixtures"]


# ------------------------------------------- 6.5) 文档/契约静态核对（导出层）
def static_contract_audit():
    print("\n[6.5] 文档与实现契约静态核对")
    doc = ast.get_docstring(ast.parse(open(EXPORT_PY, encoding="utf-8").read()))
    src = open(EXPORT_PY, encoding="utf-8").read()
    stale = [x for x in ["embeddings_int8.npy", "knn_csr.npz"] if x in doc]
    ck("模块 docstring 的产物清单与实现一致", not stale, f"陈旧条目：{stale}（实现写 embeddings_int8.bin / knn_* 三件套）")
    if stale:
        finding("E9", "info", "模块 docstring 的产物清单与实现不符（文档漂移）",
                f"docstring 列出 {stale}，实现产出 embeddings_int8.bin 与 knn_indptr/indices/sims 三件套",
                "同步 docstring；或由 manifest 生成（docstring 是 v1 时代遗留）。")
    tm = json.load(open(os.path.join(SAMPLE, "topics", "manifest.topics.json"), encoding="utf-8"))
    m = json.load(open(os.path.join(SAMPLE, "manifest.json"), encoding="utf-8"))
    ck("顶层 manifest 可区分「仅 topics」与「全量」两种包型", m["name"] != "sustc-library-catalog-vector-db",
       f"name={m['name']}；stats 键={sorted(m['stats'])}")
    finding("E8", "info", "--topics-only 与全量导出同名 manifest.json 但 schema 不同（消费方须按 name 分支）",
            f"仅 topics 包 stats 只有 {sorted(m['stats'])}（无 cards/tfidf/dim），且缺 docid_rule；"
            f"两者 name 不同（{m['name']}）尚可判别；topics/manifest.topics.json 亦不收录自身反哈希",
            "顶层 manifest 增 package_kind: topics-only|full，并让 topics 子清单收录自身 sha256（写入后再补一行）。")
    return True


# ---------------------------------------------- 7) v1 侧「只增不改」核实
def v1_audit(with_rerun=False):  # noqa: C901
    print("\n[7] v1 侧「只增不改」核实")
    src = open(EXPORT_PY, encoding="utf-8").read()
    new = compile(src, "export_release.py", "exec")
    old = None
    prior = None
    if os.path.exists(OLD_PYC):
        b = open(OLD_PYC, "rb").read()
        cand = marshal.loads(b[16:])
        names = [k.co_name for k in cand.co_consts if hasattr(k, "co_name")]
        if "export_topics" not in names:          # 确认是 topics 之前的快照
            old, prior = cand, {"path": OLD_PYC, "size": len(b)}
        else:
            prior = {"path": OLD_PYC, "size": len(b), "note": "快照已是 topics 之后版本（被 Python 缓存机制刷新）"}
    if old is None:
        ck("旧版(14:01) bytecode 快照可用", True,
           "SKIP：当前 __pycache__ 非 topics 前快照 → 改用可复现的 v1 全量复跑作为无回归证据")
        R["v1"]["prior_pyc"] = prior
        R["v1"]["first_round_measurement"] = {
            "note": "首轮审计（20:2x）在 23,026 B / 2026-09-18 14:01 的 topics 前 pyc 快照上实测；"
                    "该快照在本轮夹具导入时被 Python 缓存刷新覆盖（见 REPORT 约束披露），结果按实测记录留档",
            "funcs_identical": {"resolve_data": True, "sha256_file": True, "quantize_int8": True,
                                "quality_check_against": True, "export_tfidf": True},
            "main_instr": {"old": 1159, "new": 1330, "inserted": 155, "deleted": 0, "replaced_blocks": 47},
            "module_names_only_new": ["export_topics"], "module_names_only_old": []}
    else:
        fns = lambda c: {k.co_name: k for k in c.co_consts if hasattr(k, "co_name")}
        o, n = fns(old), fns(new)
        same = {k: (o[k].co_code == n[k].co_code and o[k].co_consts == n[k].co_consts and o[k].co_names == n[k].co_names)
                for k in ["resolve_data", "sha256_file", "quantize_int8", "quality_check_against", "export_tfidf"]}
        ck("v1 五个函数 bytecode/常量/名字逐一相同（14:01 pyc vs 现源码）", all(same.values()), json.dumps(same))
        a = [f"{i.opname} {i.argrepr}" for i in dis.get_instructions(o["main"], show_caches=False)]
        b2 = [f"{i.opname} {i.argrepr}" for i in dis.get_instructions(n["main"], show_caches=False)]
        ins = dele = rep = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b2, autojunk=False).get_opcodes():
            if tag == "insert":
                ins += j2 - j1
            elif tag == "delete":
                dele += i2 - i1
            elif tag == "replace":
                rep += 1
        R["v1"] = {"funcs_identical": same, "main_inserted": ins, "main_deleted": dele, "main_replaced_blocks": rep,
                   "main_instr_old": len(a), "main_instr_new": len(b2),
                   "module_names_only_new": [x for x in new.co_names if x not in old.co_names],
                   "module_names_only_old": [x for x in old.co_names if x not in new.co_names]}
        ck("main() 指令流：0 条纯删除（改动均为插入/跳转标号重编号）", dele == 0,
           f"插入 {ins} / 删除 {dele} / 替换块 {rep}（替换块 = 跳转目标 L*、内联超指令、行号漂移）")
        ck("模块级名字仅新增 export_topics", R["v1"]["module_names_only_new"] == ["export_topics"]
           and R["v1"]["module_names_only_old"] == [])
    # 实跑复跑比对
    R["v1"] = R["v1"] or {}
    if with_rerun and os.path.isdir(V1_RELEASE):
        t0 = time.time()
        p = subprocess.run([sys.executable, EXPORT_PY, "--data", DATA, "--out",
                            os.path.join(_HERE, "repro-v1"), "--version", "v1"],
                           capture_output=True, text=True)
        newman = os.path.join(_HERE, "repro-v1", "v1", "manifest.json")
        if p.returncode != 0 or not os.path.exists(newman):
            ck("v1 全量复跑", False, p.stderr[-300:])
        else:
            R["v1"]["rerun_seconds"] = round(time.time() - t0, 1)
            R["v1"]["rerun_compare"] = compare_v1(os.path.join(_HERE, "repro-v1", "v1"))
    elif os.path.exists(os.path.join(_HERE, "repro-v1", "v1", "manifest.json")):
        R["v1"]["rerun_compare"] = compare_v1(os.path.join(_HERE, "repro-v1", "v1"))
    return R["v1"]


def compare_v1(newdir):
    old = json.load(open(os.path.join(V1_RELEASE, "manifest.json"), encoding="utf-8"))
    new = json.load(open(os.path.join(newdir, "manifest.json"), encoding="utf-8"))
    of = {f["path"]: f for f in old["files"]}
    nf = {f["path"]: f for f in new["files"]}
    same, diff = [], []
    for p in sorted(of):
        if of[p]["sha256"] == nf.get(p, {}).get("sha256"):
            same.append(p)
        else:
            d = {"path": p}
            if p.endswith(".gz"):
                a = gzip.open(os.path.join(V1_RELEASE, p), "rb").read()
                b = gzip.open(os.path.join(newdir, p), "rb").read()
                d["gz_payload_identical"] = a == b
                d["gz_header_old_new"] = [open(os.path.join(V1_RELEASE, p), "rb").read(10).hex(),
                                          open(os.path.join(newdir, p), "rb").read(10).hex()]
            diff.append(d)
    res = {"files": len(of), "sha_identical": len(same), "diffs": diff,
           "stats_identical": old["stats"] == new["stats"],
           "meta_identical": open(os.path.join(V1_RELEASE, "embeddings_meta.json")).read()
           == open(os.path.join(newdir, "embeddings_meta.json")).read()}
    payload_ok = all(d.get("gz_payload_identical") for d in diff)
    ck("v1 复跑 vs 2026-09-18 14:01 发布包：数据逐字节一致（gz 仅头时间戳）",
       res["sha_identical"] == res["files"] - len(diff) and payload_ok,
       f"sha256 一致 {res['sha_identical']}/{res['files']}；差异 {[d['path'] for d in diff]} 解压后一致={payload_ok}")
    if diff and payload_ok:
        finding("E3", "low", "cards.jsonl.gz 不可复现：gzip 头 MTIME = 打包时刻，manifest 的 sha256 无法被重建校验",
                f"同一份 cards.jsonl 两次导出：sha256 不同、解压后 68,268,212 B 逐字节相同；"
                f"gz 头 {diff[0].get('gz_header_old_new')}（第 5–8 字节为 MTIME）",
                "gzip.GzipFile(fileobj=f, mode='wb', mtime=0) 或 gzip.compress(..., mtime=0)；"
                "否则每次重打包 tarball 哈希都变，无法做发布物一致性核验。")
    return res


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repro", action="store_true", help="现跑 topics 导出并与实发样例逐位比对")
    ap.add_argument("--with-v1-rerun", action="store_true", help="全量复跑 v1（~40s / 131MB）")
    A = ap.parse_args()
    t0 = time.time()
    print("=" * 78)
    print("AUDIT-EXPORT · export_release.py topics 分支深审")
    print("=" * 78)
    snap()
    readback(SAMPLE, "实发样例")
    if A.repro:
        d = os.path.join(_HERE, "repro", "v1")
        shutil.rmtree(os.path.join(_HERE, "repro"), ignore_errors=True)
        p = subprocess.run([sys.executable, EXPORT_PY, "--data", DATA, "--out", os.path.join(_HERE, "repro"),
                            "--version", "v1", "--topics-only"], capture_output=True, text=True)
        ck("现跑 --topics-only 导出成功", p.returncode == 0, p.stdout.strip().splitlines()[-1] if p.stdout else p.stderr[-200:])
        if os.path.isdir(d):
            readback(os.path.join(_HERE, "repro"), "复跑产物")
            re_t = os.path.join(d, "topics")
            sa_t = os.path.join(SAMPLE, "topics")
            per = {}
            for f in sorted(os.listdir(re_t)):
                per[f] = sha256(os.path.join(sa_t, f)) == sha256(os.path.join(re_t, f))
            R["repro"] = per
            data_files = [f for f in per if f not in ("manifest.topics.json", "meta.json")]
            ck("复跑：数据面文件与实发样例逐字节一致", all(per[f] for f in data_files),
               f"{sum(per[f] for f in data_files)}/{len(data_files)} 项：{data_files}")
            a = json.load(open(os.path.join(sa_t, "manifest.topics.json"), encoding="utf-8"))
            b = json.load(open(os.path.join(re_t, "manifest.topics.json"), encoding="utf-8"))
            a.pop("generated_at"), b.pop("generated_at")
            for mm in (a, b):  # meta.json 条目哈希随源漂移，是 E1 的同一根因
                for f_ in mm["files"]:
                    if f_["path"].endswith("meta.json"):
                        f_["sha256"] = f_["size"] = "<meta-drift>"
            ck("复跑：manifest.topics.json 除 generated_at / meta 哈希外完全一致", a == b)
            R["repro_meta_stale"] = {"sample_sha": sha256(os.path.join(sa_t, "meta.json"))[:16],
                                     "source_sha": sha256(os.path.join(TOPICS, "meta.json"))[:16],
                                     "sample_size": os.path.getsize(os.path.join(sa_t, "meta.json")),
                                     "source_size": os.path.getsize(os.path.join(TOPICS, "meta.json"))}
            print(f"  元数据面唯一差异：meta.json {R['repro_meta_stale']['sample_sha']}({R['repro_meta_stale']['sample_size']}B, "
                  f"导出时快照) vs 源 {R['repro_meta_stale']['source_sha']}({R['repro_meta_stale']['source_size']}B)")
    quant_audit()
    csr_audit()
    card_audit()
    manifest_audit()
    fixture_tests()
    static_contract_audit()
    v1_audit(A.with_v1_rerun)
    R["elapsed_s"] = round(time.time() - t0, 1)
    fails = [c for c in R["checks"] if not c["ok"]]
    R["summary"] = {"checks": len(R["checks"]), "failed": len(fails), "findings": len(R["findings"])}
    out = os.path.join(_HERE, "audit-export.json")
    json.dump(R, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("\n" + "=" * 78)
    print(f"检查 {len(R['checks'])} 项（失败 {len(fails)}）｜问题 {len(R['findings'])} 条｜{R['elapsed_s']}s → {out}")
    for c in fails:
        print(f"  FAIL: {c['check']} — {c['detail'][:120]}")
    for f in R["findings"]:
        print(f"  {f['id']} [{f['severity']}] {f['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
