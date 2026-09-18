#!/usr/bin/env bash
# topics-p1.sh — P1 验收（主题节点构建）
# 用法: bash acceptance/topics-p1.sh 2>&1 | tee "$HOME/go/lib-catalog-data/topics/acceptance-p1.log"
# 断言:
#   [1] topics/nodes.json 存在、合法 JSON、为数组
#   [2] 节点数 ∈ [5000, 20000]
#   [3] 节点 schema 字段齐全（id/term/type/freq/cluster/cls/sources）、id 连续 0..n-1、term 唯一
#   [4] type 同时含 kw 与 cls
#   [5] nodes.json 与 p1-build-report.json 计数/频次统计一致（A1 一致性复核）
#   [6] meta.json 顶层 stage 仍为 P0（兼容旧验收）+ stages.P1 段存在且含 params/counts/noise_rate
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

echo "=== topics P1 acceptance ==="
echo "workdir : $ROOT_DIR"
echo "data-dir: $DATA_DIR"
echo "topics  : $TOPICS_DIR"

NODES="$TOPICS_DIR/nodes.json"
REPORT="$TOPICS_DIR/p1-build-report.json"
META="$TOPICS_DIR/meta.json"

# ---- [1] nodes.json 存在 + 合法 JSON + 数组 ----
echo "[1] nodes.json 存在性与 JSON 合法性"
if [ -s "$NODES" ]; then
  ok "存在且非空（$(du -h "$NODES" | cut -f1)）"
  if python3 -c 'import json,sys; d=json.load(open(sys.argv[1],encoding="utf-8")); assert isinstance(d,list)' "$NODES" 2>/dev/null; then
    ok "合法 JSON 且为数组"
  else
    bad "非法 JSON 或不是数组: $NODES"
  fi
else
  bad "不存在或为空: $NODES"
fi

# ---- [2]-[4] 结构断言（一次 python 调用完成，输出 key=value） ----
echo "[2]-[4] 规模 / schema / type 分布"
STRUCT="$(python3 - "$NODES" <<'PY' 2>&1
import json, sys, collections
p = sys.argv[1]
try:
    nodes = json.load(open(p, encoding="utf-8"))
except Exception as e:
    print("ERROR=%s" % e); raise SystemExit(0)
n = len(nodes)
KEYS = {"id", "term", "type", "freq", "cluster", "cls", "sources"}
bad_schema = [x.get("id") for x in nodes if set(x.keys()) != KEYS]
id_ok = all(x["id"] == i for i, x in enumerate(nodes))
term_uniq = len({x["term"] for x in nodes}) == n
tc = collections.Counter(x["type"] for x in nodes)
freqs = sorted(int(x["freq"]) for x in nodes)
import statistics
print("N=%d" % n)
print("BAD_SCHEMA=%d" % len(bad_schema))
print("ID_OK=%s" % id_ok)
print("TERM_UNIQ=%s" % term_uniq)
print("KW=%d" % tc.get("kw", 0))
print("CLS=%d" % tc.get("cls", 0))
print("TYPES_OTHER=%s" % ",".join(sorted(set(tc) - {"kw", "cls"})))
print("FREQ_MIN=%d" % freqs[0])
print("FREQ_MEDIAN=%d" % int(statistics.median(freqs)))
print("FREQ_MAX=%d" % freqs[-1])
print("FREQ_ZERO=%d" % sum(1 for f in freqs if f == 0))
PY
)"
echo "$STRUCT" | sed 's/^/    /'
getv() { printf '%s\n' "$STRUCT" | sed -n "s/^$1=//p" | head -n 1; }

N="$(getv N)"
if [ -n "$N" ]; then
  if [ "$N" -ge 5000 ] && [ "$N" -le 20000 ]; then
    ok "节点数 $N ∈ [5000, 20000]"
  else
    bad "节点数 $N 超出 [5000, 20000]"
  fi
else
  bad "无法读取节点数（$STRUCT）"
fi

[ "$(getv BAD_SCHEMA)" = "0" ] && ok "schema 字段齐全（7 字段，全量 $N 条抽检）" || bad "有 $(getv BAD_SCHEMA) 条节点字段不齐"
[ "$(getv ID_OK)" = "True" ] && ok "id 连续 0..n-1" || bad "id 非连续"
[ "$(getv TERM_UNIQ)" = "True" ] && ok "term 唯一" || bad "term 存在重复"
[ "$(getv FREQ_ZERO)" = "0" ] && ok "无 freq=0 的孤立节点" || bad "存在 $(getv FREQ_ZERO) 个 freq=0 节点"

KW="$(getv KW)"; CLS="$(getv CLS)"
if [ -n "$KW" ] && [ "$KW" -gt 0 ]; then ok "type 含 kw（$KW）"; else bad "type 缺 kw"; fi
if [ -n "$CLS" ] && [ "$CLS" -gt 0 ]; then ok "type 含 cls（$CLS）"; else bad "type 缺 cls"; fi
[ -z "$(getv TYPES_OTHER)" ] && ok "type 取值仅 kw/cls" || bad "出现意外 type: $(getv TYPES_OTHER)"

# ---- [5] nodes.json ↔ p1-build-report.json 一致性（A1） ----
echo "[5] A1 一致性复核（nodes.json vs p1-build-report.json）"
if [ -s "$REPORT" ]; then
  CONS="$(python3 - "$NODES" "$REPORT" <<'PY' 2>&1
import json, sys, collections, statistics
nodes = json.load(open(sys.argv[1], encoding="utf-8"))
rep = json.load(open(sys.argv[2], encoding="utf-8"))
c = rep["counts"]; fs = rep["freq_stats"]
tc = collections.Counter(x["type"] for x in nodes)
freqs = sorted(int(x["freq"]) for x in nodes)
checks = {
    "counts.nodes": (len(nodes), c["nodes"]),
    "counts.kw": (tc["kw"], c["kw"]),
    "counts.cls": (tc["cls"], c["cls"]),
    "freq.min": (freqs[0], fs["min"]),
    "freq.median": (int(statistics.median(freqs)), fs["median"]),
    "freq.max": (freqs[-1], fs["max"]),
    "freq.p25": (int(statistics.quantiles(freqs, n=4)[0]) if len(freqs) > 3 else freqs[0], fs["p25"]),
}
src = collections.Counter("+".join(x["sources"]) for x in nodes)
checks["counts.sources"] = (dict(src), c["sources"])
for k, (a, b) in checks.items():
    print("CHECK %s %s" % ("OK" if a == b else "MISMATCH", k))
PY
)"
  echo "$CONS" | sed 's/^/    /'
  MIS="$(printf '%s\n' "$CONS" | grep -c 'MISMATCH' || true)"
  if [ "$MIS" = "0" ]; then
    ok "7 项计数/频次统计与构建报告完全一致"
  else
    bad "$MIS 项与构建报告不一致"
  fi
else
  bad "构建报告缺失: $REPORT"
fi

# ---- [6] meta.json 兼容性 + stages.P1 段 ----
echo "[6] meta.json（顶层 P0 兼容 + stages.P1 段）"
if [ -s "$META" ]; then
  if python3 -c 'import json,sys; json.load(open(sys.argv[1],encoding="utf-8"))' "$META" 2>/dev/null; then
    ok "合法 JSON"
    METAINFO="$(python3 - "$META" <<'PY'
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
print("TOP_STAGE=%s" % m.get("stage"))
print("CURRENT_STAGE=%s" % m.get("current_stage"))
p1 = (m.get("stages") or {}).get("P1") or {}
print("P1_EXISTS=%s" % bool(p1))
print("P1_NOISE=%s" % p1.get("noise_rate", ""))
print("P1_NODES=%s" % ((p1.get("counts") or {}).get("nodes", "")))
print("P1_PARAMS_OK=%s" % bool(p1.get("params")))
print("P1_COUNTS_OK=%s" % bool(p1.get("counts")))
PY
)"
    echo "$METAINFO" | sed 's/^/    /'
    getm() { printf '%s\n' "$METAINFO" | sed -n "s/^$1=//p" | head -n 1; }
    [ "$(getm TOP_STAGE)" = "P0" ] && ok "顶层 stage 仍为 P0（旧验收脚本兼容）" || bad "顶层 stage 被改动: $(getm TOP_STAGE)"
    [ "$(getm P1_EXISTS)" = "True" ] && ok "stages.P1 段存在" || bad "stages.P1 段缺失"
    [ "$(getm P1_PARAMS_OK)" = "True" ] && ok "stages.P1.params 存在" || bad "stages.P1.params 缺失"
    [ "$(getm P1_COUNTS_OK)" = "True" ] && ok "stages.P1.counts 存在（nodes=$(getm P1_NODES)）" || bad "stages.P1.counts 缺失"
    NOISE="$(getm P1_NOISE)"
    if [ -n "$NOISE" ] && awk -v v="$NOISE" 'BEGIN{ exit !(v >= 0 && v <= 0.10) }'; then
      ok "P1 噪声率 $NOISE ≤ 10% 门槛"
    else
      bad "P1 噪声率缺失或超门槛: '$NOISE'"
    fi
  else
    bad "非法 JSON: $META"
  fi
else
  bad "不存在或为空: $META"
fi

echo "-----------------------------------------"
if [ "$FAIL" -eq 0 ]; then
  echo "TOPICS-P1: PASS (pass=$PASS fail=$FAIL)"
  exit 0
else
  echo "TOPICS-P1: FAIL (pass=$PASS fail=$FAIL)"
  exit 1
fi
