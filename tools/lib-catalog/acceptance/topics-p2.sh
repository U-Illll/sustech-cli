#!/usr/bin/env bash
# topics-p2.sh — P2 验收（主题图边构建）
# 用法: bash acceptance/topics-p2.sh 2>&1 | tee "$HOME/go/lib-catalog-data/topics/acceptance-p2.log"
# 断言:
#   [1] topics/edges.csr.npz 存在、可载入、数组 dtype 钉死（indptr int64 / indices int32 / weights float32）
#   [2] CSR 结构自洽：indptr[0]=0、indptr[-1]=nnz、单调不减、indices ∈ [0,n)、n = nodes.json 条数
#   [3] 权重 ∈ [0,1] 且存在 w=1.0（层级边）
#   [4] 出度：平均 ≤20 且 max ≤20
#   [5] topics/card_topics.jsonl：行数 = 卡数、合法 JSON、topics ≤5、id 合法且不重复
#   [6] p2-build-report.json 与边表一致（edges/nodes）+ 自测字段齐全
#   [7] meta.json stages.P2 段存在（counts/params/edge_stats）
# 可重复运行；全部通过 exit 0，否则 exit 1。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="${LIB_CATALOG_DATA:-$HOME/go/lib-catalog-data}"
TOPICS_DIR="$DATA_DIR/topics"

PASS=0
FAIL=0
ok()  { echo "  [PASS] $*"; PASS=$((PASS + 1)); }
bad() { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }

echo "=== topics P2 acceptance ==="
echo "workdir : $ROOT_DIR"
echo "data-dir: $DATA_DIR"

EDGES="$TOPICS_DIR/edges.csr.npz"
CT="$TOPICS_DIR/card_topics.jsonl"
REPORT="$TOPICS_DIR/p2-build-report.json"
META="$TOPICS_DIR/meta.json"
NODES="$TOPICS_DIR/nodes.json"

# ---- [1]-[4] 边表结构与 dtype ----
echo "[1]-[4] edges.csr.npz / CSR 结构 / 权重 / 出度"
if [ ! -s "$EDGES" ]; then
  bad "边表不存在: $EDGES（先跑 python3 topic_edges.py --data $DATA_DIR）"
else
  ok "边表存在（$(du -h "$EDGES" | cut -f1)）"
  STRUCT="$(python3 - "$EDGES" "$NODES" <<'PY' 2>&1
import json, os, sys
sys.path.insert(0, os.path.expanduser("~/go/pylibs"))   # 与工具链脚本同源的 numpy 环境
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
print("DEG_MAX=%d" % deg.max())
print("DEG_ZERO=%d" % int((deg == 0).sum()))
PY
)"
  echo "$STRUCT" | sed 's/^/    /'
  getv() { printf '%s\n' "$STRUCT" | sed -n "s/^$1=//p" | head -n 1; }

  [ "$(getv DTYPES)" = "int64/int32/float32" ] && ok "dtype 钉死 indptr=int64 / indices=int32 / weights=float32" \
    || bad "dtype 不符（实际 $(getv DTYPES)，必须 int64/int32/float32）"
  [ "$(getv N)" = "$(getv IP_LEN_OK | sed 's/True/1/;s/False/0/')" ] >/dev/null 2>&1 || true
  [ "$(getv IP_LEN_OK)" = "True" ] && ok "indptr 长度 = n+1（n=$(getv N)）" || bad "indptr 长度 ≠ n+1"
  [ "$(getv IP0)" = "0" ] && ok "indptr[0] = 0" || bad "indptr[0] ≠ 0"
  [ "$(getv IPLAST)" = "$(getv NNZ)" ] && ok "indptr[-1] = nnz = $(getv NNZ)" || bad "indptr[-1] ≠ nnz"
  [ "$(getv IP_MONOTONE)" = "True" ] && ok "indptr 单调不减" || bad "indptr 非单调"
  [ "$(getv IDX_RANGE_OK)" = "True" ] && ok "indices ∈ [0, n)" || bad "indices 越界"
  [ "$(getv W_RANGE_OK)" = "True" ] && ok "权重 ∈ [0,1]" || bad "权重越界"
  [ "$(getv W_EQ1)" -gt 0 ] && ok "存在 w=1.0 的层级边（$(getv W_EQ1) 条）" || bad "无 w=1.0 边（层级边缺失？）"
  awk -v m="$(getv DEG_MEAN)" 'BEGIN{exit !(m<=20.000001)}' && ok "平均出度 $(getv DEG_MEAN) ≤ 20" \
    || bad "平均出度 $(getv DEG_MEAN) > 20"
  [ "$(getv DEG_MAX)" -le 20 ] && ok "最大出度 $(getv DEG_MAX) ≤ 20" || bad "最大出度 $(getv DEG_MAX) > 20"
fi

# ---- [4b] 边型数组 types（R2-C / AUDIT-EDGETYPE 方案 a） ----
echo "[4b] edges.csr.npz types 边型 bitmask（uint8）"
if [ -s "$EDGES" ]; then
  TCHK="$(python3 - "$EDGES" <<'PY' 2>&1
import sys, os
sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
import numpy as np
z = np.load(sys.argv[1])
if "types" not in z.files:
    print("HAS_TYPES=False"); raise SystemExit(0)
t = z["types"]; ix = z["indices"]
print("HAS_TYPES=True")
print("T_DTYPE=%s" % t.dtype)
print("T_LEN_OK=%s" % (len(t) == len(ix)))
vals, cnts = np.unique(t, return_counts=True)
print("T_VALS=%s" % ",".join(str(int(v)) for v in vals))
print("T_RANGE_OK=%s" % bool(set(int(v) for v in vals) <= {1, 3, 5, 7}))
print("T_BIT0_ALL=%s" % bool((t & 1).all()))
for v, c in zip(vals, cnts):
    print("T_HIST_%d=%d" % (int(v), int(c)))
PY
)"
  echo "$TCHK" | sed 's/^/    /'
  gett() { printf '%s\n' "$TCHK" | sed -n "s/^$1=//p" | head -n 1; }
  if [ "$(gett HAS_TYPES)" = "True" ]; then
    [ "$(gett T_DTYPE)" = "uint8" ] && ok "types dtype = uint8" || bad "types dtype 非 uint8（$(gett T_DTYPE)）"
    [ "$(gett T_LEN_OK)" = "True" ] && ok "len(types) == nnz" || bad "len(types) ≠ nnz"
    [ "$(gett T_RANGE_OK)" = "True" ] && ok "types ∈ {1,3,5,7}（实测 $(gett T_VALS)）" || bad "types 越界（$(gett T_VALS)）"
    [ "$(gett T_BIT0_ALL)" = "True" ] && ok "bit0（共现）恒置位" || bad "存在 bit0 未置位的边"
    if [ "$(gett T_HIST_5)" != "0" ] || [ "$(gett T_HIST_7)" != "0" ]; then
      ok "存在层级边 bit2（mask5=$(gett T_HIST_5) / mask7=$(gett T_HIST_7)）"
    else
      bad "无 bit2 层级边（层级边缺失？）"
    fi
  else
    bad "边表缺 types 数组（AUDIT-EDGETYPE 方案 a 未落地）"
  fi
fi

# ---- [5] card_topics.jsonl ----
echo "[5] card_topics.jsonl（证据链）"
if [ ! -s "$CT" ]; then
  bad "证据链不存在: $CT"
else
  LINES=$(wc -l < "$CT" | tr -d ' ')
  ok "存在（$LINES 行，$(du -h "$CT" | cut -f1)）"
  CTRES="$(python3 - "$CT" "$NODES" <<'PY' 2>&1
import json, sys
n = len(json.load(open(sys.argv[2], encoding="utf-8")))
tot = bad_json = bad_id = dup = too_many = 0
sizes = {}
with open(sys.argv[1], encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        tot += 1
        try:
            o = json.loads(line)
        except Exception:
            bad_json += 1
            continue
        t = o.get("topics")
        if not isinstance(t, list):
            bad_json += 1
            continue
        sizes[len(t)] = sizes.get(len(t), 0) + 1
        if len(t) > 5:
            too_many += 1
        if len(set(t)) != len(t):
            dup += 1
        if any((not isinstance(x, int)) or x < 0 or x >= n for x in t):
            bad_id += 1
print("TOTAL=%d" % tot)
print("BAD_JSON=%d" % bad_json)
print("BAD_ID=%d" % bad_id)
print("DUP=%d" % dup)
print("TOO_MANY=%d" % too_many)
print("SIZES=%s" % json.dumps({str(k): v for k, v in sorted(sizes.items())}, ensure_ascii=False))
PY
)"
  echo "$CTRES" | sed 's/^/    /'
  getc() { printf '%s\n' "$CTRES" | sed -n "s/^$1=//p" | head -n 1; }
  [ "$(getc BAD_JSON)" = "0" ] && ok "全部行合法 JSON" || bad "$(getc BAD_JSON) 行非法"
  [ "$(getc BAD_ID)" = "0" ] && ok "topics id 全部 ∈ [0,n)" || bad "$(getc BAD_ID) 行 id 越界"
  [ "$(getc DUP)" = "0" ] && ok "卡内 topics 无重复" || bad "$(getc DUP) 行有重复 id"
  [ "$(getc TOO_MANY)" = "0" ] && ok "每题 ≤5 个主题（尺寸分布 $(getc SIZES)）" || bad "$(getc TOO_MANY) 行超过 5 个主题"
fi

# ---- [6] 构建报告一致性 ----
echo "[6] p2-build-report.json"
if [ -s "$REPORT" ]; then
  ok "存在"
  RP="$(python3 - "$REPORT" "$EDGES" "$NODES" <<'PY' 2>&1
import json, os, sys
sys.path.insert(0, os.path.expanduser("~/go/pylibs"))   # 与工具链脚本同源的 numpy 环境
import numpy as np
r = json.load(open(sys.argv[1], encoding="utf-8"))
z = np.load(sys.argv[2])
n = len(json.load(open(sys.argv[3], encoding="utf-8")))
print("R_NODES=%s" % r["counts"]["nodes"])
print("R_EDGES=%s" % r["counts"]["edges_final"])
print("A_NODES=%d" % n)
print("A_EDGES=%d" % len(z["indices"]))
st = r.get("self_test", {})
print("ST_AVG=%s" % st.get("avg_out_degree_le_max"))
print("ST_HOP12=%s" % st.get("hop12_kw_seeds_mean"))
print("CHOSEN=%s" % r["edge_stats"].get("chosen"))
print("RANK_BY=%s" % r["params"].get("rank_by"))
PY
)"
  echo "$RP" | sed 's/^/    /'
  getr() { printf '%s\n' "$RP" | sed -n "s/^$1=//p" | head -n 1; }
  [ "$(getr R_NODES)" = "$(getr A_NODES)" ] && ok "报告 nodes 与 nodes.json 一致（$(getr A_NODES)）" || bad "报告 nodes 不一致"
  [ "$(getr R_EDGES)" = "$(getr A_EDGES)" ] && ok "报告 edges 与边表一致（$(getr A_EDGES)）" || bad "报告 edges 不一致"
  [ "$(getr ST_AVG)" = "True" ] && ok "自测 avg_out_degree ≤ max_out 通过" || bad "自测 avg_out_degree 未通过"
  [ -n "$(getr ST_HOP12)" ] && ok "自测 12 跳覆盖（kw 源点）$(getr ST_HOP12) / 口径 $(getr RANK_BY)" || bad "自测缺少 12 跳覆盖"
  [ -n "$(getr CHOSEN)" ] && ok "口径选择: $(getr CHOSEN)" || bad "缺少变体选择字段"
else
  bad "构建报告缺失: $REPORT"
fi

# ---- [7] meta.json stages.P2 ----
echo "[7] meta.json stages.P2"
if [ -s "$META" ]; then
  MP="$(python3 - "$META" <<'PY' 2>&1
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
p2 = (m.get("stages") or {}).get("P2") or {}
print("P2_EXISTS=%s" % bool(p2))
print("P2_COUNTS=%s" % bool(p2.get("counts")))
print("P2_PARAMS=%s" % bool(p2.get("params")))
print("P2_EDGESTATS=%s" % bool(p2.get("edge_stats")))
print("P2_TOPSTAGE=%s" % m.get("stage"))
PY
)"
  echo "$MP" | sed 's/^/    /'
  getm() { printf '%s\n' "$MP" | sed -n "s/^$1=//p" | head -n 1; }
  [ "$(getm P2_EXISTS)" = "True" ] && ok "stages.P2 段存在" || bad "stages.P2 段缺失"
  [ "$(getm P2_COUNTS)" = "True" ] && ok "stages.P2.counts 存在" || bad "stages.P2.counts 缺失"
  [ "$(getm P2_PARAMS)" = "True" ] && ok "stages.P2.params 存在（口径已登记）" || bad "stages.P2.params 缺失"
  [ "$(getm P2_EDGESTATS)" = "True" ] && ok "stages.P2.edge_stats 存在" || bad "stages.P2.edge_stats 缺失"
  [ "$(getm P2_TOPSTAGE)" = "P0" ] && ok "顶层 stage 仍为 P0（旧验收兼容）" || bad "顶层 stage 被改动"
else
  bad "meta.json 缺失"
fi

# ---- [8] 共现权重独立重算抽验（终审⑤） ----
echo "[8] 共现权重独立重算抽验（从 card_topics.jsonl 反算，≥3 条边）"
if [ -s "$CT" ] && [ -s "$EDGES" ]; then
  WCHK="$(python3 - "$TOPICS_DIR" "$DATA_DIR" <<'PY'
import json, math, os, sys
sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
import numpy as np
T, D = sys.argv[1], sys.argv[2]
nodes = json.load(open(os.path.join(T, "nodes.json"), encoding="utf-8"))
n = len(nodes)
ncl = np.array([int(x["cluster"]) for x in nodes]); ntyp = np.array([x["type"] for x in nodes])
by_term = {x["term"]: x["id"] for x in nodes}
z = np.load(os.path.join(T, "edges.csr.npz")); ip, ix, wt = z["indptr"], z["indices"], z["weights"]
labels = np.load(os.path.join(D, "index", "clusters.npy"))
LOG50 = math.log1p(50)
pairs = []
if "settlement" in by_term and "entanglement" in by_term:
    u0, v0 = by_term["settlement"], by_term["entanglement"]
    pairs.append((min(u0, v0), max(u0, v0), "终审反例 settlement-entanglement"))
seen = {(a, b) for a, b, _t in pairs}
for u in range(n):
    if len(pairs) >= 4:
        break
    for q in range(int(ip[u]), int(ip[u + 1])):
        v = int(ix[q])
        if u < v and ntyp[u] == "kw" and ntyp[v] == "kw" and (u, v) not in seen:
            pairs.append((u, v, "kw-kw 抽样")); seen.add((u, v)); break
hier = None
for u in range(n):
    for q in range(int(ip[u]), int(ip[u + 1])):
        if ntyp[int(ix[q])] == "cls":
            hier = (u, int(ix[q])); break
    if hier:
        break
target = {(a, b) for a, b, _t in pairs}
cnt = {k: 0 for k in target}; cnt_sc = {k: 0 for k in target}
i = 0
with open(os.path.join(T, "card_topics.jsonl"), encoding="utf-8") as f:
    for line in f:
        ts = set(json.loads(line)["topics"]); lab = int(labels[i]); i += 1
        for k in target:
            if k[0] in ts and k[1] in ts:
                cnt[k] += 1
                if ncl[k[0]] == ncl[k[1]] == lab:
                    cnt_sc[k] += 1
mis = 0
for (u, v, tag) in pairs:
    c, cs = cnt[(u, v)], cnt_sc[(u, v)]
    exp = min(1.0, math.log1p(min(c, 50)) / LOG50 + 0.3 * math.log1p(cs) / LOG50)
    got = None
    for q in range(int(ip[u]), int(ip[u + 1])):
        if int(ix[q]) == v:
            got = float(wt[q]); break
    okk = got is not None and abs(got - exp) < 1e-6
    mis += 0 if okk else 1
    print("CHECK %s | %s(id=%d) <-> %s(id=%d) [%s] 共现书数=%d 簇内=%d 期望=%.10f 实存=%s" % (
        "OK" if okk else "MISMATCH", nodes[u]["term"], u, nodes[v]["term"], v, tag, c, cs, exp,
        ("%.10f" % got) if got is not None else "缺边"))
if hier:
    u, v = hier
    got = None
    for q in range(int(ip[u]), int(ip[u + 1])):
        if int(ix[q]) == v:
            got = float(wt[q]); break
    okk = got is not None and abs(got - 1.0) < 1e-6
    mis += 0 if okk else 1
    print("CHECK %s | 层级边 %s(id=%d) -> %s(id=%d,type=cls) 期望=1.0000000000 实存=%s" % (
        "OK" if okk else "MISMATCH", nodes[u]["term"], u, nodes[v]["term"], v, got))
print("MISMATCH_TOTAL=%d" % mis)
print("CARDS_SCANNED=%d" % i)
PY
)"
  echo "$WCHK" | sed 's/^/    /'
  WM="$(printf '%s\n' "$WCHK" | sed -n 's/^MISMATCH_TOTAL=//p' | head -n 1)"
  WC="$(printf '%s\n' "$WCHK" | grep -c '^CHECK OK' || true)"
  [ "$WM" = "0" ] && ok "权重独立重算全部吻合（抽验 $WC 条边，含层级边 w=1.0）" || bad "权重独立重算不一致 $WM 条"
  [ "$WC" -ge 3 ] && ok "抽验边数 $WC ≥ 3" || bad "抽验边数不足（$WC）"
else
  bad "缺少 card_topics.jsonl 或 edges.csr.npz，无法抽验"
fi

# ---- [9] 证据链行数 == cards.jsonl 行数（终审⑤） ----
echo "[9] 证据链行数对齐 cards.jsonl"
NCT=$(wc -l < "$CT" 2>/dev/null | tr -d ' ')
NCD=$(wc -l < "$DATA_DIR/cards.jsonl" 2>/dev/null | tr -d ' ')
if [ "$NCT" = "$NCD" ] && [ "$NCT" = "188512" ]; then
  ok "card_topics.jsonl 行数 == cards.jsonl 行数 == $NCT"
else
  bad "行数不对齐（card_topics=$NCT / cards=$NCD，期望两者均 188512）"
fi

echo "-----------------------------------------"
if [ "$FAIL" -eq 0 ]; then
  echo "TOPICS-P2: PASS (pass=$PASS fail=$FAIL)"
  exit 0
else
  echo "TOPICS-P2: FAIL (pass=$PASS fail=$FAIL)"
  exit 1
fi
