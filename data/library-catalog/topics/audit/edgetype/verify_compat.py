#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_compat.py — AUDIT-EDGETYPE：方案 a（新增 types u8 键）对现有消费方的兼容性验证

用**真实生产消费方**在**真实全量边表**上做端到端回归，而不是靠"应当兼容"的推断：
  C1 构造 compat/topics/：nodes.json + 4 数组版 edges.csr.npz（全量 99,268 边）
  C2 把 acceptance/topics-p2.sh 的 [1]-[4] 结构断言**逐字**跑在 官方 3 数组版 与 4 数组版 上并比对
  C3 把生产消费方 topics_report.py（P3 质量报告）分别指向两版边表，比对结构化 JSON
  C4 旧读取路径（按显式键取 3 数组）逐字节比对

只读主体；只写 topics/audit/edgetype/。
前置：先跑 proto_type_mask.py 生成 edge_type_mask.mask.npy。

用法：
  PYTHONPATH=~/go/pylibs python3 verify_compat.py
"""
import json
import os
import shutil
import subprocess
import sys

_PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)
import numpy as np

DATA = os.path.expanduser("~/go/lib-catalog-data")
OUT = os.path.join(DATA, "topics")
A = os.path.join(OUT, "audit", "edgetype")
SCRIPTS = os.path.expanduser("~/go/reasonix-scripts/lib-catalog")
OFFICIAL = os.path.join(OUT, "edges.csr.npz")
COMPAT = os.path.join(A, "compat")
CTOPICS = os.path.join(COMPAT, "topics")

# ---- 逐字取自 acceptance/topics-p2.sh 的 [1]-[4] 结构断言 python 块 ----
STRUCT_PROBE = r'''
import json, os, sys
sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
import numpy as np
z = np.load(sys.argv[1])
n = len(json.load(open(sys.argv[2], encoding="utf-8")))
ip, ix, wt = z["indptr"], z["indices"], z["weights"]
print("DTYPES=%s/%s/%s" % (ip.dtype, ix.dtype, wt.dtype))
print("N=%d" % n)
print("NNZ=%d" % len(ix))
print("IP0=%d" % ip[0])
print("IPLAST=%d" % ip[-1])
print("IP_MONOTONE=%s" % bool(np.all(np.diff(ip) >= 0)))
print("IP_LEN_OK=%s" % (len(ip) == n + 1))
print("IDX_RANGE_OK=%s" % bool(ix.min() >= 0 and ix.max() < n))
print("W_RANGE_OK=%s" % bool(wt.min() >= 0.0 and wt.max() <= 1.0 + 1e-6))
print("W_MAX=%.6f" % float(wt.max()))
print("W_EQ1=%d" % int((wt >= 0.99999).sum()))
deg = np.diff(ip)
print("DEG_MEAN=%.4f" % deg.mean())
'''

# 非语义噪声：产物路径 + 墙钟计时（同一份 bit-identical 输入跑两次也不相等）
VOLATILE = {"generated_at", "seconds", "wall_seconds", "edges_source", "artifacts_dir",
            "path", "timings", "elapsed"}
VOLATILE_SUFFIX = ("_ms",)


def strip_volatile(o):
    """只剥离路径与计时字段；其余（dtype_check/n/nnz/出度/权重域/覆盖曲线）必须逐值相等。"""
    if isinstance(o, dict):
        return {k: strip_volatile(v) for k, v in o.items()
                if k not in VOLATILE and not k.endswith(VOLATILE_SUFFIX)}
    if isinstance(o, list):
        return [strip_volatile(x) for x in o]
    if isinstance(o, float):
        return round(o, 9)
    return o


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return p.returncode, p.stdout, p.stderr


def main():
    os.makedirs(CTOPICS, exist_ok=True)
    res = {}
    mask_p = os.path.join(A, "edge_type_mask.mask.npy")
    if not os.path.exists(mask_p):
        raise SystemExit("[ERR] 缺 edge_type_mask.mask.npy，请先跑 proto_type_mask.py")
    mask = np.load(mask_p)
    z = np.load(OFFICIAL)
    indptr, indices, weights = z["indptr"], z["indices"], z["weights"]
    assert len(mask) == len(indices), "掩码长度与 indices 不一致"

    # ---- C1 构造 4 数组版全量边表 ----
    shutil.copyfile(os.path.join(OUT, "nodes.json"), os.path.join(CTOPICS, "nodes.json"))
    typed_p = os.path.join(CTOPICS, "edges.csr.npz")
    np.savez(typed_p,
             indptr=indptr.astype(np.int64), indices=indices.astype(np.int32),
             weights=weights.astype(np.float32), types=mask.astype(np.uint8))
    res["C1_typed_artifact"] = {
        "path": "topics/audit/edgetype/compat/topics/edges.csr.npz",
        "keys": sorted(np.load(typed_p).files), "edges": int(len(indices)),
        "bytes_official": os.path.getsize(OFFICIAL), "bytes_typed": os.path.getsize(typed_p)}
    print(f"[C1] typed={res['C1_typed_artifact']['bytes_typed']}B "
          f"official={res['C1_typed_artifact']['bytes_official']}B", flush=True)

    # ---- C2 生产验收门 [1]-[4] 断言双跑比对 ----
    probe = os.path.join(COMPAT, "_struct_probe.py")
    open(probe, "w", encoding="utf-8").write(STRUCT_PROBE)
    nodes_p = os.path.join(OUT, "nodes.json")
    rc1, o1, e1 = run([sys.executable, probe, OFFICIAL, nodes_p])
    rc2, o2, e2 = run([sys.executable, probe, typed_p, nodes_p])
    res["C2_acceptance_p2_gate"] = {
        "official_rc": rc1, "typed_rc": rc2, "stderr": e2.strip()[:400],
        "identical": (o1 == o2 and rc1 == rc2 == 0),
        "official_output": o1.strip().splitlines(),
        "typed_output": o2.strip().splitlines()}
    print(f"[C2] 验收门双跑一致={res['C2_acceptance_p2_gate']['identical']}", flush=True)

    # ---- C3 生产消费方 topics_report.py 双跑比对 ----
    def report(dirpath, label):
        jp = os.path.join(COMPAT, f"p3-{label}.json")
        rc, o, e = run([sys.executable, os.path.join(SCRIPTS, "topics_report.py"),
                        "--out", dirpath, "--samples", "20", "--perf-samples", "5",
                        "--json", "--json-out", jp], cwd=SCRIPTS)
        if rc != 0 or not os.path.exists(jp):
            return {"rc": rc, "stderr": (e or o)[-600:], "json": None}
        return {"rc": rc, "json": strip_volatile(json.load(open(jp, encoding="utf-8")))}

    r_off = report(OUT, "official")
    r_typ = report(CTOPICS, "typed")
    res["C3_consumer_topics_report"] = {
        "official_rc": r_off["rc"], "typed_rc": r_typ["rc"],
        "both_ok": r_off["rc"] == 0 and r_typ["rc"] == 0,
        "json_identical": bool(r_off["json"] is not None and r_off["json"] == r_typ["json"]),
        "official_stderr": r_off.get("stderr", ""), "typed_stderr": r_typ.get("stderr", "")}
    if r_off["json"] is not None and r_typ["json"] is not None and r_off["json"] != r_typ["json"]:
        diff = [k for k in set(r_off["json"]) | set(r_typ["json"])
                if r_off["json"].get(k) != r_typ["json"].get(k)]
        res["C3_consumer_topics_report"]["differing_top_keys"] = diff
    print(f"[C3] 消费方双跑 rc={r_off['rc']}/{r_typ['rc']} "
          f"json_identical={res['C3_consumer_topics_report']['json_identical']}", flush=True)

    # ---- C4 旧读取路径逐字节比对 ----
    t = np.load(typed_p)
    res["C4_legacy_read_path"] = {
        "indptr_bitwise_equal": bool(np.array_equal(t["indptr"], indptr)),
        "indices_bitwise_equal": bool(np.array_equal(t["indices"], indices)),
        "weights_bitwise_equal": bool(np.array_equal(t["weights"], weights)),
        "extra_key_invisible_to_key_reader": bool(set(np.load(OFFICIAL).files) < set(t.files))}
    res["C4_legacy_read_path"]["pass"] = all(
        res["C4_legacy_read_path"][k] for k in
        ("indptr_bitwise_equal", "indices_bitwise_equal", "weights_bitwise_equal",
         "extra_key_invisible_to_key_reader"))
    print(f"[C4] 旧读取路径 pass={res['C4_legacy_read_path']['pass']}", flush=True)

    res["verdict"] = {
        "additive_types_key_breaks_no_consumer": bool(
            res["C2_acceptance_p2_gate"]["identical"]
            and res["C3_consumer_topics_report"]["both_ok"]
            and res["C3_consumer_topics_report"]["json_identical"]
            and res["C4_legacy_read_path"]["pass"]),
        "readers_requiring_the_key": ["export_release.py → 需**新增** edges_types.u8.bin 导出（当前不导出，属增强非破坏）"]}
    rp = os.path.join(A, "compat-report.json")
    json.dump(res, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[done] verdict={res['verdict']['additive_types_key_breaks_no_consumer']} -> {rp}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
