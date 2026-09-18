#!/usr/bin/env bash
# topics-p3.sh — P3 验收（主题图质量报告 / 口径终裁）
# 用法: bash acceptance/topics-p3.sh 2>&1 | tee "$HOME/go/lib-catalog-data/topics/acceptance-p3.log"
# 断言:
#   [1] topics/topics-report.json 存在、合法 JSON、stage=P3
#   [2] 三口径 12 跳覆盖数字齐备（主簇 / 主簇∪类目 / 无向闭包），hop=12
#   [3] 硬门槛：②（主簇∪类目）mean ≥ 0.90（§4-P3 原文「主题的簇 = 主簇或分类」）→ PASS
#   [4] ①（仅主簇）作为严格观察项并列存在且 < 0.90 不被静默改成达标（防口径漂移）
#   [5] 性能 p50_ms < 1000（门槛 <1s）
#   [6] 连通/衰减/CSR dtype 字段齐备
#   [7] meta.json stages.P3 段存在（含裁定向量与三口径数字）
# 可重复运行；全部通过 exit 0，否则 exit 1。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="${LIB_CATALOG_DATA:-$HOME/go/lib-catalog-data}"
TOPICS_DIR="$DATA_DIR/topics"

PASS=0
FAIL=0
ok()   { echo "  [PASS] $*"; PASS=$((PASS + 1)); }
bad()  { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }
info() { echo "  [INFO] $*"; }

echo "=== topics P3 acceptance ==="
echo "workdir : $ROOT_DIR"
echo "data-dir: $DATA_DIR"

REPORT="$TOPICS_DIR/topics-report.json"
META="$TOPICS_DIR/meta.json"

# ---- [1]-[6] 报告主体 ----
echo "[1]-[6] topics-report.json（三口径 / 门槛 / 性能 / 连通 / 衰减 / dtype）"
if [ ! -s "$REPORT" ]; then
  bad "报告不存在: $REPORT（先跑 python3 topics_report.py --data $DATA_DIR --samples 400 --hops 12 --seed 42 --json-out $REPORT）"
else
  ok "报告存在（$(du -h "$REPORT" | cut -f1)）"
  RES="$(python3 - "$REPORT" <<'PY' 2>&1
import json, sys
try:
    r = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as e:
    print("ERROR=%s" % e); raise SystemExit(0)
cov = r.get("coverage") or {}
f, fu, fud = cov.get("final") or {}, cov.get("final_union") or {}, cov.get("final_undirected") or {}
perf = r.get("performance") or {}
cns = r.get("connectivity") or {}
dec = r.get("decay") or {}
csr = r.get("csr") or {}
g = lambda d, k: d.get(k, "")
print("STAGE=%s" % r.get("stage"))
print("HOP1=%s" % f.get("hop"))
print("HOP2=%s" % fu.get("hop"))
print("HOP3=%s" % fud.get("hop"))
print("C1=%s" % g(f, "coverage_mean"))
print("C1_MED=%s" % g(f, "coverage_median"))
print("C1_PASS=%s" % g(f, "pass"))
print("C2=%s" % g(fu, "coverage_mean"))
print("C2_MED=%s" % g(fu, "coverage_median"))
print("C2_PASS=%s" % g(fu, "pass"))
print("C3=%s" % g(fud, "coverage_mean"))
print("C3_PASS=%s" % g(fud, "pass"))
print("GATE=%s" % g(f, "gate"))
print("P50=%s" % g(perf, "p50_ms"))
print("P95=%s" % g(perf, "p95_ms"))
print("PERF_PASS=%s" % g(perf, "pass"))
print("COMPONENTS=%s" % g(cns, "components"))
print("LARGEST=%s" % g(cns, "largest_component"))
print("DECAY_HOP1=%s" % g(dec, "hop1_mean"))
print("DECAY_N=%s" % len(dec.get("per_hop") or []))
print("CSR_IP=%s" % g(csr, "indptr_dtype"))
print("CSR_IX=%s" % g(csr, "indices_dtype"))
print("CSR_W=%s" % g(csr, "weights_dtype"))
print("CSR_NNZ=%s" % g(csr, "nnz"))
print("SAMPLES=%s" % (cov.get("samples", "")))
print("SOURCE_TYPE=%s" % (cov.get("source_type", "")))
PY
)"
  echo "$RES" | sed 's/^/    /'
  getv() { printf '%s\n' "$RES" | sed -n "s/^$1=//p" | head -n 1; }

  [ "$(getv STAGE)" = "P3" ] && ok "stage=P3" || bad "stage 应为 P3（实际 '$(getv STAGE)'）"

  # 三口径数字齐备
  for pair in "C1:①仅主簇" "C2:②主簇∪类目" "C3:③无向闭包"; do
    k="${pair%%:*}"; name="${pair#*:}"
    v="$(getv $k)"
    if [ -n "$v" ]; then ok "$name 12 跳覆盖 = $v"; else bad "$name 覆盖数字缺失"; fi
  done
  [ "$(getv HOP1)" = "12" ] && [ "$(getv HOP2)" = "12" ] && [ "$(getv HOP3)" = "12" ] \
    && ok "三口径均为 hop=12" || bad "口径 hop 不齐（$(getv HOP1)/$(getv HOP2)/$(getv HOP3)）"

  # 硬门槛 ② + 观察项 ①
  # 终审⑤：门槛必须**硬编码**在验收脚本里，不依赖报告自述值（报告值仅作一致性核对）
  GATE=0.90
  RG="$(getv GATE)"
  if [ -n "$RG" ] && awk -v a="$RG" -v b="$GATE" 'BEGIN{exit !(a+0 == b+0)}'; then
    ok "报告自述门槛 $RG 与脚本硬编码 $GATE 一致"
  else
    bad "报告自述门槛 '$RG' 与脚本硬编码 $GATE 不一致（口径漂移风险）"
  fi
  if awk -v v="$(getv C2)" -v g="$GATE" 'BEGIN{exit !(v+0 >= g+0)}'; then
    ok "硬门槛口径 ②（主簇∪类目，§4-P3 原文）= $(getv C2) ≥ $GATE → PASS"
  else
    bad "硬门槛口径 ② = $(getv C2) < $GATE → 未达标"
  fi
  if awk -v v="$(getv C1)" 'BEGIN{exit !(v+0 < 0.90)}'; then
    ok "严格观察项 ①（仅主簇）= $(getv C1) < 0.90，如实并列未被口径改写（与 v1 基线 0.902 基本持平）"
  else
    info "①（仅主簇）当前 $(getv C1)：若 ≥0.90 说明图已变化，请复核裁定文本"
  fi

  # 性能
  if awk -v v="$(getv P50)" 'BEGIN{exit !(v+0 < 1000)}'; then
    ok "12 跳单查询 p50 = $(getv P50) ms < 1000ms（p95 $(getv P95) ms）"
  else
    bad "p50 = $(getv P50) ms 未达标（<1000ms）"
  fi

  # 连通 / 衰减 / dtype
  [ -n "$(getv COMPONENTS)" ] && [ -n "$(getv LARGEST)" ] && ok "连通字段齐（分量 $(getv COMPONENTS) 个 / 最大 $(getv LARGEST)）" || bad "连通字段缺失"
  [ "$(getv DECAY_N)" = "12" ] && ok "衰减曲线 12 跳齐（1 跳均分 $(getv DECAY_HOP1)）" || bad "衰减曲线不足 12 跳（$(getv DECAY_N)）"
  if [ "$(getv CSR_IP)" = "int64" ] && [ "$(getv CSR_IX)" = "int32" ] && [ "$(getv CSR_W)" = "float32" ]; then
    ok "CSR dtype 复核 int64/int32/float32（nnz $(getv CSR_NNZ)）"
  else
    bad "CSR dtype 不符（$(getv CSR_IP)/$(getv CSR_IX)/$(getv CSR_W)）"
  fi
  info "抽样口径：$(getv SAMPLES) 样本 / source_type=$(getv SOURCE_TYPE)"

  # 补充证据（不参与判定）：全源点报告
  if [ -s "$TOPICS_DIR/topics-report-allseed.json" ]; then
    info "补充：topics-report-allseed.json 存在（全节点源点口径）"
  else
    info "补充：无 topics-report-allseed.json（可选）"
  fi
fi

# ---- [7] meta.json stages.P3 ----
echo "[7] meta.json stages.P3"
if [ -s "$META" ]; then
  MP="$(python3 - "$META" <<'PY' 2>&1
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
p3 = (m.get("stages") or {}).get("P3") or {}
cov = p3.get("coverage") or {}
print("P3_EXISTS=%s" % bool(p3))
print("P3_C1=%s" % ((cov.get("cluster_only") or {}).get("mean", "")))
print("P3_C2=%s" % ((cov.get("cluster_or_cls") or {}).get("mean", "")))
print("P3_C3=%s" % ((cov.get("undirected_closure") or {}).get("mean", "")))
print("P3_VERDICT=%s" % bool(p3.get("verdict")))
print("P3_PERF=%s" % bool(p3.get("performance")))
print("P3_REPORT=%s" % (p3.get("report_file", "")))
print("P3_TS=%s" % (p3.get("generated_at", "")))
print("P3_CUR=%s" % m.get("current_stage", ""))
print("TOP_STAGE=%s" % m.get("stage", ""))
PY
)"
  echo "$MP" | sed 's/^/    /'
  getm() { printf '%s\n' "$MP" | sed -n "s/^$1=//p" | head -n 1; }
  [ "$(getm P3_EXISTS)" = "True" ] && ok "stages.P3 段存在" || bad "stages.P3 段缺失"
  [ -n "$(getm P3_C1)" ] && [ -n "$(getm P3_C2)" ] && [ -n "$(getm P3_C3)" ] \
    && ok "三口径数字已登记（①$(getm P3_C1) / ②$(getm P3_C2) / ③$(getm P3_C3)）" || bad "三口径数字登记不全"
  [ "$(getm P3_VERDICT)" = "True" ] && ok "裁定文本已登记（verdict）" || bad "缺少裁定文本 verdict"
  [ "$(getm P3_PERF)" = "True" ] && ok "性能字段已登记" || bad "缺少性能字段"
  case "$(getm P3_REPORT)" in
    *topics-report.json) ok "report 指针：$(getm P3_REPORT)（generated_at $(getm P3_TS)）" ;;
    *) bad "report 指针异常：'$(getm P3_REPORT)'" ;;
  esac
  [ "$(getm TOP_STAGE)" = "P0" ] && ok "顶层 stage 仍为 P0（旧验收兼容）" || bad "顶层 stage 被改动"
else
  bad "meta.json 缺失"
fi

# ---- [8] 口径冻结记录（终审⑤） ----
echo "[8] 口径冻结记录（集合定义 / 抽样规则 / 源点处理）"
FRZ="$(python3 - "$META" <<'PY'
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
fz = ((m.get("stages") or {}).get("P3") or {}).get("caliber_freeze") or {}
need = ("same_cluster_set", "sampling", "source_handling", "gate", "denominator")
print("FREEZE_EXISTS=%s" % bool(fz))
print("MISSING=%s" % ",".join(k for k in need if k not in fz))
print("GATE=%s" % fz.get("gate", ""))
print("SAMPLING=%s" % str(fz.get("sampling", ""))[:90])
print("SOURCE=%s" % str(fz.get("source_handling", ""))[:90])
print("DENOM=%s" % str(fz.get("denominator", ""))[:90])
PY
)"
  echo "$FRZ" | sed 's/^/    /'
  getf() { printf '%s\n' "$FRZ" | sed -n "s/^$1=//p" | head -n 1; }
  [ "$(getf FREEZE_EXISTS)" = "True" ] && ok "meta.stages.P3.caliber_freeze 已登记" || bad "缺少口径冻结记录 caliber_freeze"
  [ -z "$(getf MISSING)" ] && ok "冻结记录字段齐（集合/抽样/源点/门槛/分母）" || bad "冻结记录缺字段：$(getf MISSING)"
  GATE_FZ="$(getf GATE)"
  if [ -n "$GATE_FZ" ] && awk -v a="$GATE_FZ" 'BEGIN{exit !(a+0 == 0.90)}'; then
    ok "冻结门槛 = $GATE_FZ（与脚本硬编码 0.90 数值一致）"
  else
    bad "冻结门槛异常：'$GATE_FZ'"
  fi

echo "-----------------------------------------"
if [ "$FAIL" -eq 0 ]; then
  echo "TOPICS-P3: PASS (pass=$PASS fail=$FAIL)"
  exit 0
else
  echo "TOPICS-P3: FAIL (pass=$PASS fail=$FAIL)"
  exit 1
fi
