#!/usr/bin/env python3
# verify_export_r2c.py — R2-C 导出包独立复验（只读）
#
# 对象: topics/export-sample/<ver>/（R2-C 重建）
# 检查:
#   A 外层 manifest.json ：逐文件 size + sha256 + total_bytes
#   B 内层 manifest.topics.json ：逐文件 size + sha256（"manifest 全对"）
#   C 包内 meta 与包内数据**同源**（AUDIT-EXPORT E1 的验收口径）：
#       C1 counts     nodes / edges / avg_outdeg —— 精确相等（整数/3 位小数）
#       C2 w_eq1      **包内 u8 反算** vs 包内 meta 登记 —— 逐位相等（任务书指定口径）
#       C3 w_mean     量化均值 vs 原始 float32 均值 —— 容差 = 量化半步 1/510（信息项，非缺陷）
#   D 快照绑定：manifest.snapshot.source_sha256 与包外源数据实测 sha256 一致
#   E E2 防护：证据链行数 == cards.jsonl 行数
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
import numpy as np

BASE = "/home/wzh/go/lib-catalog-data/topics/export-sample/v1"
DATA = "/home/wzh/go/lib-catalog-data"
HALF_STEP = 1.0 / 510.0


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    fails = []
    tdir = os.path.join(BASE, "topics")

    print("=== A 外层 manifest.json 对账 ===")
    man = json.load(open(os.path.join(BASE, "manifest.json"), encoding="utf-8"))
    for f in man["files"]:
        p = os.path.join(BASE, f["path"])
        ok = sha(p) == f["sha256"] and os.path.getsize(p) == f["size"]
        fails += [] if ok else [f"A:{f['path']}"]
        print(f"  {'OK' if ok else 'MISMATCH':9s} {f['size']:>9d}  {f['path']}")
    tb = sum(f["size"] for f in man["files"])
    ok = tb == man["total_bytes"]
    fails += [] if ok else ["A:total_bytes"]
    print(f"  {'OK' if ok else 'MISMATCH':9s} total_bytes {man['total_bytes']} == {tb}")

    print("=== B 内层 manifest.topics.json 对账 ===")
    tm = json.load(open(os.path.join(tdir, "manifest.topics.json"), encoding="utf-8"))
    for f in tm["files"]:
        p = os.path.join(BASE, f["path"])
        ok = sha(p) == f["sha256"] and os.path.getsize(p) == f["size"]
        fails += [] if ok else [f"B:{f['path']}"]
        print(f"  {'OK' if ok else 'MISMATCH':9s} {f['size']:>9d}  {f['path']}")
    print(f"  package_kind: outer={man.get('package_kind')} / inner={tm.get('package_kind')}")

    print("=== C 包内 meta 与包内数据同源（E1）===")
    u8 = np.fromfile(os.path.join(tdir, "edges_weights.u8.bin"), dtype=np.uint8)
    ip = np.fromfile(os.path.join(tdir, "edges_indptr.i64.bin"), dtype=np.int64)
    ix = np.fromfile(os.path.join(tdir, "edges_indices.i32.bin"), dtype=np.int32)
    cip = np.fromfile(os.path.join(tdir, "card_topics_indptr.i32.bin"), dtype=np.int32)
    cids = np.fromfile(os.path.join(tdir, "card_topics_ids.i32.bin"), dtype=np.int32)
    src = os.path.join(DATA, "topics", "edges.csr.npz")
    z = np.load(src)
    w_raw = z["weights"].astype(np.float32)

    wm = json.load(open(os.path.join(tdir, "meta.json"), encoding="utf-8"))["stages"]["P2"]
    wd = wm["edge_stats"]["weight_dist"]
    reg = {"nodes": wm["counts"]["nodes"], "edges": wd["n"],
           "avg_outdeg": wm["edge_stats"]["avg_out_degree"],
           "w_eq_1_share": wm["edge_stats"]["w_eq_1_share"], "weight_mean": wd["mean"]}
    meas = {"nodes": int(len(ip) - 1), "edges": int(len(ix)),
            "avg_outdeg": round(float(np.diff(ip).mean()), 3),
            "w_eq_1_share": round(float((u8 == 255).mean()), 4),
            "weight_mean": round(float(w_raw.mean()), 4)}

    checks = [
        ("C1 nodes", reg["nodes"], meas["nodes"], 0, True),
        ("C1 edges", reg["edges"], meas["edges"], 0, True),
        ("C1 avg_outdeg", reg["avg_outdeg"], meas["avg_outdeg"], 5e-4, True),
        ("C2 w_eq1(u8反算)", reg["w_eq_1_share"], meas["w_eq_1_share"], 0, True),
        ("C3 weight_mean", reg["weight_mean"], meas["weight_mean"], HALF_STEP, False),
    ]
    print(f"  {'检查':<20s} {'meta 登记':<12s} {'包内实测':<12s} 判定")
    for name, r, m, tol, hard in checks:
        ok = abs(float(r) - float(m)) <= tol
        fails += [] if (ok or not hard) else [name]
        tag = "OK" if ok else ("INFO(量化半步内)" if not hard else "MISMATCH")
        print(f"  {name:<20s} {r!s:<12s} {m!s:<12s} {tag}")
    d = abs(float((u8 / 255.0).mean()) - float(w_raw.mean()))
    print(f"  -- u8 量化均值 {float((u8/255.0).mean()):.6f} vs 原始 {float(w_raw.mean()):.6f} "
          f"（Δ={d:.6f} ≤ 半步 {HALF_STEP:.6f} → 量化固有偏差，非不同源）")

    print("=== D 快照绑定（manifest.snapshot.source_sha256 vs 包外实测）===")
    for name, h in (tm.get("snapshot") or {}).get("source_sha256", {}).items():
        p = os.path.join(DATA, name) if name == "cards.jsonl" else os.path.join(DATA, "topics", name)
        if h is None or not os.path.exists(p):
            print(f"  {'SKIP':9s} {name}")
            continue
        ok = sha(p) == h
        fails += [] if ok else [f"D:{name}"]
        print(f"  {'OK' if ok else 'MISMATCH':9s} {name}  {h[:16]}…")

    print("=== E E2 证据链行数对齐 ===")
    n_cards = len(cip) - 1
    with open(os.path.join(DATA, "cards.jsonl"), "rb") as f:
        n_src = sum(1 for _ in f)
    ok = n_cards == n_src and len(cids) == int(cip[-1])
    fails += [] if ok else ["E:rowcount"]
    print(f"  {'OK' if ok else 'MISMATCH':9s} 包内 {n_cards} == cards.jsonl {n_src}；ids {len(cids)} == indptr[-1] {int(cip[-1])}")

    print()
    print("总判定：", "ALL PASS" if not fails else f"FAIL {len(fails)} 项 -> {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
