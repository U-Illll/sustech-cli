#!/usr/bin/env python3
# compare_edges.py — R1 修复前后边表对比实测（只读）
#
# 用法: python3 compare_edges.py --before <pre-r1.npz> --after <edges.csr.npz>
# 输出: 边数 / 平均出度 / 最大出度 / 权重分布 / 饱和对（w=1.0）统计
# 说明: 边表为合成加权图，权重 = min(1, log1p(共现书数)/log1p(50) + 同簇加成)；
#       本脚本只做统计比对，不推断语义。
import argparse
import json
import os
import sys

# 与 lib-catalog 工具链一致：优先使用仓库自带 pylibs（系统 python 无 numpy）
_PYLIBS = os.path.expanduser("~/go/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)

import numpy as np


def load(path):
    z = np.load(path, allow_pickle=False)
    return z["indptr"], z["indices"], z["weights"]


def stats(path):
    indptr, indices, weights = load(path)
    n = len(indptr) - 1
    nnz = int(indptr[-1])
    outdeg = np.diff(indptr).astype(np.int64)
    w = weights.astype(np.float64)
    return {
        "path": path,
        "nodes": int(n),
        "edges": nnz,
        "avg_outdegree": round(float(outdeg.mean()), 4),
        "max_outdegree": int(outdeg.max()),
        "min_outdegree": int(outdeg.min()),
        "isolated_nodes": int((outdeg == 0).sum()),
        "weight_mean": round(float(w.mean()), 4),
        "weight_median": round(float(np.median(w)), 4),
        "weight_p90": round(float(np.percentile(w, 90)), 4),
        "weight_min": round(float(w.min()), 6),
        "weight_max": round(float(w.max()), 6),
        "w_eq_1_count": int((w >= 1.0 - 1e-9).sum()),
        "w_eq_1_ratio": round(float((w >= 1.0 - 1e-9).mean()), 4),
        "w_ge_0.8_ratio": round(float((w >= 0.8).mean()), 4),
        "w_lt_0.1_ratio": round(float((w < 0.1).mean()), 4),
        "dtype_indptr": str(indptr.dtype),
        "dtype_indices": str(indices.dtype),
        "dtype_weights": str(weights.dtype),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    args = ap.parse_args()

    b = stats(args.before)
    a = stats(args.after)

    keys = [k for k in a if k != "path"]
    print("指标\tR1前\tR1后\t变化")
    for k in keys:
        bv, av = b[k], a[k]
        if isinstance(av, (int, float)) and not isinstance(av, bool):
            d = round(float(av) - float(bv), 6)
        else:
            d = ""
        print(f"{k}\t{bv}\t{av}\t{d}")

    print()
    print("JSON:")
    print(json.dumps({"before": b, "after": a}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
