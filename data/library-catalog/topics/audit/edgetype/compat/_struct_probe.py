
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
