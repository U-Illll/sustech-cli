#!/usr/bin/env bash
# topics-p4.sh — P4 验收（主题图查询编排 topic_graph.py）
# 用法: bash acceptance/topics-p4.sh 2>&1 | tee "$HOME/go/lib-catalog-data/topics/acceptance-p4.log"
# 断言:
#   [1] 四子命令可用且 exit 0：search / around / graph / summarize
#   [2] 扩散规则正确性（手算样例）：单边源→邻 w = 1.0 × edge_w × 0.86，且 2 跳为连乘 ×0.86²
#   [3] summarize 存根：返回非空、且确定性（同 region 两次输出逐字节相同）
#   [4] 默认不触网：脚本内无 requests/urllib/http/socket/urlopen/curl/wget 等调用面
#   [5] 参数护栏：--hops > 12 被拒；topic_id 越界被拒
#   [6] graph --json-out 结构自洽（nodes/edges/stats；边端点均在节点集合内）
# 可重复运行；全部通过 exit 0，否则 exit 1。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="${LIB_CATALOG_DATA:-$HOME/go/lib-catalog-data}"
TOOL="$ROOT_DIR/topic_graph.py"
TMP="${TMPDIR:-/tmp}"

PASS=0
FAIL=0
ok()   { echo "  [PASS] $*"; PASS=$((PASS + 1)); }
bad()  { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }
info() { echo "  [INFO] $*"; }

echo "=== topics P4 acceptance ==="
echo "workdir : $ROOT_DIR"
echo "data-dir: $DATA_DIR"
echo "tool    : $TOOL"

if [ ! -f "$TOOL" ]; then
  echo "  [FAIL] 找不到 $TOOL"; echo "TOPICS-P4: FAIL (pass=0 fail=1)"; exit 1
fi

run_tool() { (cd "$ROOT_DIR" && timeout 120 python3 "$TOOL" "$@" 2>&1); }

# ---- [1] 四子命令 ----
echo "[1] 四子命令可用性"
OUT_S="$(run_tool search 机器学习 --top 5)"; RC_S=$?
if [ "$RC_S" -eq 0 ] && printf '%s' "$OUT_S" | grep -q "\[search\]"; then
  ok "search exit 0（$(printf '%s\n' "$OUT_S" | sed -n '1p')）"
else
  bad "search 失败（exit=$RC_S）"
fi
[ -n "$OUT_S" ] && printf '%s' "$OUT_S" | grep -qE "^\s*[0-9]+\s+" && ok "search 有命中主题行" || bad "search 无命中行"

OUT_A="$(run_tool around 56 --hops 2 --top 4 --evidence 2)"; RC_A=$?
if [ "$RC_A" -eq 0 ] && printf '%s' "$OUT_A" | grep -q "规则: w_hop"; then
  ok "around exit 0（$(printf '%s\n' "$OUT_A" | sed -n '3p')"
else
  bad "around 失败（exit=$RC_A）"
fi
printf '%s' "$OUT_A" | grep -q "\[书证据\]" && ok "around 含 card_topics 反查书证据" || bad "around 缺书证据段"

JSON_G="$TMP/tg-accept-graph.json"
OUT_G="$(run_tool graph 65 --hops 1 --json-out "$JSON_G")"; RC_G=$?
if [ "$RC_G" -eq 0 ] && [ -s "$JSON_G" ]; then
  ok "graph exit 0（$(printf '%s\n' "$OUT_G" | sed -n '1p')）"
else
  bad "graph 失败（exit=$RC_G / json 未生成）"
fi

OUT_U="$(run_tool summarize 56 --hops 2)"; RC_U=$?
if [ "$RC_U" -eq 0 ] && [ -n "$OUT_U" ]; then
  ok "summarize exit 0（$(printf '%s\n' "$OUT_U" | sed -n '3p')）"
else
  bad "summarize 失败（exit=$RC_U）"
fi

# ---- [2] 扩散规则手算样例 ----
echo "[2] 扩散规则正确性（手算：w = 1.0 × edge_w × 0.86^hop）"
CALC="$(cd "$ROOT_DIR" && python3 - "$TOOL" <<'PY' 2>&1
import os, sys
sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[1])))
import numpy as np
import topic_graph as tg
D = os.environ.get("LIB_CATALOG_DATA") or os.path.expanduser("~/go/lib-catalog-data")
nodes, _ = tg.load_nodes(D)
ip, ix, wt = tg.load_edges(D)
# 找一条权重大于 0.1 的出边做手算样例
u = v = None
for i in range(len(nodes)):
    a, b = int(ip[i]), int(ip[i + 1])
    for p in range(a, b):
        if float(wt[p]) > 0.1 and int(ix[p]) != i:
            u, v, ew = i, int(ix[p]), float(wt[p]); break
    if u is not None:
        break
reg = tg.diffuse(u, 1, ip, ix, wt, 0.86, 0.05, 50000)
exp1, got1 = 1.0 * ew * 0.86, reg["score"].get(v)
# 2 跳：从 v 再走一条 >0.1 的出边；x 必须既不是源点、也不在源点 1 跳邻域内（否则会被 1 跳更优分数覆盖）
u_neigh = set(int(ix[p]) for p in range(int(ip[u]), int(ip[u + 1])))
a, b = int(ip[v]), int(ip[v + 1])
w2 = None
for p in range(a, b):
    xc = int(ix[p])
    if float(wt[p]) > 0.1 and xc != v and xc != u and xc not in u_neigh:
        x, ew2 = xc, float(wt[p]); w2 = ew2; break
reg2 = tg.diffuse(u, 2, ip, ix, wt, 0.86, 0.05, 50000)
exp2 = exp1 * w2 * 0.86 if w2 is not None else None
got2 = reg2["score"].get(x) if w2 is not None else None
print("SRC=%d(%s) DST=%d(%s)" % (u, nodes[u]["term"], v, nodes[v]["term"]))
print("EDGE_W=%.6f" % ew)
print("HOP1_EXPECTED=%.6f" % exp1)
print("HOP1_GOT=%.6f" % (got1 if got1 is not None else -1))
print("HOP1_MATCH=%s" % (got1 is not None and abs(got1 - exp1) < 1e-9))
if w2 is not None:
    print("HOP2_VIA=%d(%s) EDGE_W2=%.6f" % (x, nodes[x]["term"], w2))
    print("HOP2_EXPECTED=%.6f" % exp2)
    print("HOP2_GOT=%.6f" % (got2 if got2 is not None else -1))
    print("HOP2_MATCH=%s" % (got2 is not None and abs(got2 - exp2) < 1e-9))
else:
    print("HOP2_MATCH=n/a")
print("SEED_SCORE=%.6f" % reg2["score"].get(u, -1))
PY
)"
echo "$CALC" | sed 's/^/    /'
getc() { printf '%s\n' "$CALC" | sed -n "s/^$1=//p" | head -n 1; }
[ "$(getc HOP1_MATCH)" = "True" ] && ok "1 跳手算吻合（w=$(getc HOP1_GOT) = 1.0 × $(getc EDGE_W) × 0.86）" \
  || bad "1 跳手算不吻合（expected $(getc HOP1_EXPECTED) vs got $(getc HOP1_GOT)）"
case "$(getc HOP2_MATCH)" in
  True) ok "2 跳手算吻合（连乘 ×0.86² = $(getc HOP2_GOT)）" ;;
  n/a)  info "2 跳样例不可用（该节点无 >0.1 出边）" ;;
  *)    bad "2 跳手算不吻合（expected $(getc HOP2_EXPECTED) vs got $(getc HOP2_GOT)）" ;;
esac
[ "$(getc SEED_SCORE)" = "1.000000" ] && ok "源点得分恒为 1.0" || bad "源点得分异常（$(getc SEED_SCORE)）"

# ---- [3] 存根确定性与非空 ----
echo "[3] summarize 存根（非空 + 确定性 + 默认不触网）"
U1="$(run_tool summarize 56 --hops 1)"; U2="$(run_tool summarize 56 --hops 1)"
[ -n "$U1" ] && ok "返回非空（$(printf '%s' "$U1" | wc -l | tr -d ' ') 行）" || bad "返回为空"
[ "$U1" = "$U2" ] && ok "同 region 两次输出逐字节一致（确定性）" || bad "输出不确定（含随机/时间戳？）"
printf '%s' "$U1" | grep -q "区域规模" && printf '%s' "$U1" | grep -q "权重分布" \
  && ok "占位文含区域统计（主题数/书数/权重分布/代表主题）" || bad "占位文缺统计字段"
printf '%s' "$U1" | grep -q "待与作者讨论" && ok "接口注释标注「待与作者讨论」" || bad "缺接口待议标注"
DEFMODE="$(cd "$ROOT_DIR" && env -u TOPIC_LLM python3 "$TOOL" summarize 56 --hops 1 2>&1 | sed -n '3p')"
printf '%s' "$DEFMODE" | grep -q "off" && ok "未设 TOPIC_LLM 时默认 off（纯结构化占位，不触网）" || bad "默认模式非 off：'$DEFMODE'"

# ---- [4] 无网络调用面 ----
echo "[4] 无网络调用（静态检查）"
NET="$(grep -nE "import (requests|urllib|httpx|aiohttp|socket|http)|urlopen|requests\.|https?://|curl |wget " "$TOOL" || true)"
if [ -z "$NET" ]; then ok "topic_graph.py 无网络调用面（requests/urllib/http/socket/url 全部缺失）"; else bad "发现网络调用面：$NET"; fi
NET2="$(grep -nE "import (requests|urllib|httpx|aiohttp|socket|http)|urlopen|requests\.|https?://" "$ROOT_DIR/topic_edges.py" "$ROOT_DIR/topics_report.py" || true)"
[ -z "$NET2" ] && ok "P2/P3 脚本同样无网络调用面" || bad "P2/P3 脚本含网络调用面：$NET2"

# ---- [5] 参数护栏 ----
echo "[5] 参数护栏"
OUT_H="$(run_tool around 56 --hops 13 2>&1)"; RC_H=$?
[ "$RC_H" -ne 0 ] && printf '%s' "$OUT_H" | grep -q "1\.\.12" && ok "--hops 13 被拒（exit=$RC_H）" || bad "--hops 13 未被拒（exit=$RC_H）"
OUT_B="$(run_tool around 99999 --hops 1 2>&1)"; RC_B=$?
[ "$RC_B" -ne 0 ] && printf '%s' "$OUT_B" | grep -q "越界" && ok "topic_id 越界被拒（exit=$RC_B）" || bad "topic_id 越界未被拒（exit=$RC_B）"

# ---- [6] graph JSON 结构 ----
echo "[6] graph --json-out 结构"
GJ="$(python3 - "$JSON_G" <<'PY' 2>&1
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
ns = d.get("nodes") or []; es = d.get("edges") or []
ids = {n["id"] for n in ns}
bad_ep = [e for e in es if e["src"] not in ids or e["dst"] not in ids]
ok_keys = all(set(("id", "term", "type", "cluster", "w")) <= set(n) for n in ns)
print("N=%d" % len(ns))
print("E=%d" % len(es))
print("KEYS_OK=%s" % ok_keys)
print("ENDPOINTS_OK=%s" % (len(bad_ep) == 0))
print("SEED_IN=%s" % (d["seed"]["id"] in ids))
print("W_RANGE_OK=%s" % all(0.0 <= n["w"] <= 1.0 for n in ns))
print("STATS_OK=%s" % bool(d.get("stats")))
PY
)"
echo "$GJ" | sed 's/^/    /'
getg() { printf '%s\n' "$GJ" | sed -n "s/^$1=//p" | head -n 1; }
[ "$(getg KEYS_OK)" = "True" ] && ok "nodes 字段齐（id/term/type/cluster/w）" || bad "nodes 字段缺失"
[ "$(getg ENDPOINTS_OK)" = "True" ] && ok "边端点均落在节点集合内（$(getg N) 节点 / $(getg E) 边）" || bad "存在悬空边端点"
[ "$(getg SEED_IN)" = "True" ] && ok "种子节点在子图内" || bad "种子节点不在子图内"
[ "$(getg W_RANGE_OK)" = "True" ] && ok "扩散权重 ∈ [0,1]" || bad "扩散权重越界"
[ "$(getg STATS_OK)" = "True" ] && ok "含 stats（visited/edges_scanned/elapsed_ms）" || bad "缺 stats"

# ---- [7] 近词扩展（非词表查询退化路径 ②） ----
echo "[7] search 近词扩展（TF-IDF → 聚合书的主题）"
EX1="$(run_tool search "机器学习 入门" --top 3 --expand-top 6)"; RCX1=$?
if [ "$RCX1" -eq 0 ] && printf '%s' "$EX1" | grep -q "\[近词扩展\]" && printf '%s' "$EX1" | grep -q "tfidf-expand"; then
  ok "非词表查询「机器学习 入门」触发扩展并返回 tfidf-expand 主题"
else
  bad "扩展未触发或返回异常（exit=$RCX1）"
fi
NEX1="$(printf '%s' "$EX1" | grep -c "tfidf-expand")"
[ "$NEX1" -ge 1 ] && ok "扩展命中 $NEX1 条（含支持书 mms）" || bad "扩展命中数为 0"
EX2="$(run_tool search "量子 科普" --top 3)"
printf '%s' "$EX2" | grep -q "tfidf-expand" && ok "非词表查询「量子 科普」同样触发扩展" || bad "「量子 科普」未触发扩展"
EX3="$(run_tool search 量子 --top 3)"
if printf '%s' "$EX3" | grep -q "tfidf-expand"; then
  bad "词表内整词命中仍触发扩展（auto 规则应抑制）"
else
  ok "对照：词表内整词「量子」不触发扩展（auto 规则正确）"
fi
EX4="$(run_tool search "机器学习 入门" --top 3 --expand no)"
printf '%s' "$EX4" | grep -q "tfidf-expand" && bad "--expand no 未能关闭扩展" || ok "对照：--expand no 关闭扩展"
EXJ="$(run_tool search "机器学习 入门" --top 2 --json)"
printf '%s' "$EXJ" | grep -q "expanded_hits" && ok "--json 输出含 expanded_hits/expand 段" || bad "--json 缺扩展字段"
printf '%s' "$EXJ" | grep -qE "\"src\": \"(exact|token|prefix|substr)\"" && ok "--json 字面命中标注 src（exact/token/prefix/substr）" \
  || info "--json 字面命中 src 标注未检出（可能是空结果）"

# ---- [8] 超跳回归（终审③）：内存反例 + 真实图路径长度 ----
echo "[8] 扩散超跳回归（内存反例 + around 路径长度）"
HOPCHK="$(cd "$ROOT_DIR" && python3 - "$TOOL" <<'PY'
import os, sys
sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[1])))
import numpy as np
import topic_graph as tg

def plen(reg, x):
    c, cur = 0, reg["parent"].get(x)
    while cur is not None and c < 99:
        c += 1; cur = reg["parent"].get(cur)
    return c

def build(nch=11, a_w=1.0, b_w=0.95):
    """A/B 两条 11 跳链 + 层内边 a11->b11 + b11->z（终审超跳场景的最小复现图）。"""
    a = list(range(1, 1 + nch)); b = list(range(1 + nch, 1 + 2 * nch)); z = 1 + 2 * nch
    E = [(0, a[0], a_w)] + [(a[i], a[i + 1], a_w) for i in range(nch - 1)]
    E += [(0, b[0], b_w)] + [(b[i], b[i + 1], b_w) for i in range(nch - 1)]
    E += [(a[-1], b[-1], 1.0), (b[-1], z, 1.0)]
    N = z + 1; ix, wt = [], []; ip = np.zeros(N + 1, dtype=np.int64)
    for u in range(N):
        for (s_, d_, w_) in E:
            if s_ == u:
                ix.append(d_); wt.append(w_)
        ip[u + 1] = len(ix)
    return ip, np.array(ix, dtype=np.int32), np.array(wt, dtype=np.float32), z

def diffuse_buggy(seed, hops, indptr, indices, weights, decay=0.86, threshold=0.05):
    """R1 修复前的实现（层内直接读 score[u]）——回归测试的"反例有牙"证明。"""
    score = {seed: 1.0}; parent = {seed: None}; frontier = [seed]
    for _h in range(1, hops + 1):
        nxt = []
        for u in frontier:
            su = score[u]
            for q in range(int(indptr[u]), int(indptr[u + 1])):
                v = int(indices[q]); sv = su * float(weights[q]) * decay
                if sv < threshold:
                    continue
                if sv > score.get(v, 0.0):
                    score[v] = sv; parent[v] = u; nxt.append(v)
        if not nxt:
            break
        frontier = nxt
    return {"score": score, "parent": parent}

ip, ix, wt, z = build()
buggy = diffuse_buggy(0, 12, ip, ix, wt)
fixed = tg.diffuse(0, 12, ip, ix, wt, 0.86, 0.05, 50000)
buggy_max = max((plen(buggy, x) for x in buggy["score"]), default=0)
fixed_max = max((plen(fixed, x) for x in fixed["score"]), default=0)
print("COUNTEREXAMPLE_BUGGY_MAXPATH=%d" % buggy_max)
print("COUNTEREXAMPLE_FIXED_MAXPATH=%d" % fixed_max)
print("COUNTEREXAMPLE_HAS_TEETH=%s" % (buggy_max > 12))
D = os.environ.get("LIB_CATALOG_DATA") or os.path.expanduser("~/go/lib-catalog-data")
indptr, indices, weights = tg.load_edges(D)
for hops in (1, 2, 3, 12):
    reg = tg.diffuse(139, hops, indptr, indices, weights, 0.86, 0.05, 50000)
    mx = max((plen(reg, x) for x in reg["score"]), default=0)
    over = sum(1 for x in reg["score"] if x != 139 and plen(reg, x) > hops)
    print("REAL_HOPS_%d maxpath=%d over=%d" % (hops, mx, over))
PY
)"
  echo "$HOPCHK" | sed 's/^/    /'
  geth() { printf '%s\n' "$HOPCHK" | sed -n "s/^$1=//p" | head -n 1; }
  [ "$(geth COUNTEREXAMPLE_HAS_TEETH)" = "True" ] && ok "反例有效（修复前实现返回 $(geth COUNTEREXAMPLE_BUGGY_MAXPATH) 边 > 12 跳）" \
    || bad "反例失效：修复前实现未超跳（无法证明回归有效）"
  [ "$(geth COUNTEREXAMPLE_FIXED_MAXPATH)" -le 12 ] && ok "修复后反例图最深路径 $(geth COUNTEREXAMPLE_FIXED_MAXPATH) 边 ≤ 12" \
    || bad "修复后反例图仍超跳（$(geth COUNTEREXAMPLE_FIXED_MAXPATH) 边）"
  REAL_OK=1
  for h in 1 2 3 12; do
    ln="$(printf '%s\n' "$HOPCHK" | grep "^REAL_HOPS_${h} " || true)"
    mp="$(printf '%s' "$ln" | sed -n 's/.*maxpath=\([0-9]*\).*/\1/p')"
    ov="$(printf '%s' "$ln" | sed -n 's/.*over=\([0-9]*\).*/\1/p')"
    if [ -z "$mp" ] || [ -z "$ov" ] || [ "$mp" -gt "$h" ] || [ "$ov" != "0" ]; then REAL_OK=0; fi
  done
  [ "$REAL_OK" = "1" ] && ok "真实图 around 139 hops=1/2/3/12 全部无超跳（最深父链 ≤ hops）" || bad "真实图存在超跳"

# ---- [9] 护栏（终审⑦）：decay/budget/threshold 越界拒绝 ----
echo "[9] 护栏：--decay ∈ (0,1]、--budget ≥1、--threshold ∈ [0,1]"
for bad_arg in "--decay 1.5" "--decay 0" "--decay -0.2" "--budget 0" "--threshold 2"; do
  OUT_GUARD="$(run_tool around 56 --hops 1 $bad_arg 2>&1)"; RC_GUARD=$?
  if [ "$RC_GUARD" -ne 0 ] && printf '%s' "$OUT_GUARD" | grep -qE "需在|需 ≥"; then
    ok "拒绝 $bad_arg（exit=$RC_GUARD）"
  else
    bad "未拒绝 $bad_arg（exit=$RC_GUARD）"
  fi
done

echo "-----------------------------------------"
if [ "$FAIL" -eq 0 ]; then
  echo "TOPICS-P4: PASS (pass=$PASS fail=$FAIL)"
  exit 0
else
  echo "TOPICS-P4: FAIL (pass=$PASS fail=$FAIL)"
  exit 1
fi
