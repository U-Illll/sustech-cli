#!/usr/bin/env bash
# rerun.sh — FINAL-RERUN 全链独立复跑（R1 修复后）
#
# 约束：只读主体产物；所有写入限于 audit/final-rerun/；不覆盖正式产物；不访问网络。
# 用法：bash audit/final-rerun/rerun.sh
#
# 复跑内容：
#   A. 关键产物 sha256 基线记录
#   B. 六份 acceptance（topics-p0..p5.sh）逐项结果 + exit code
#   C. 生成链复跑 → runs/：topics_report 全量（冻结命令）+ topic_graph 抽 3 命令
#   D. 修复前后对比指标实测（pre-r1 备份 vs 当前边表）
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${LIB_CATALOG_DATA:-$HOME/go/lib-catalog-data}"
TOPICS="$DATA_DIR/topics"
TOOLS="$HOME/go/reasonix-scripts/lib-catalog"
ACC="$TOOLS/acceptance"
RUNS="$SCRIPT_DIR/runs"
OUT="$SCRIPT_DIR"

export LIB_CATALOG_DATA="$DATA_DIR"
mkdir -p "$RUNS"

echo "=== FINAL-RERUN 全链独立复跑 ==="
echo "date    : $(date -Iseconds)"
echo "data-dir: $DATA_DIR"
echo "tools   : $TOOLS"
echo

# ---------- A. sha256 基线 ----------
echo "--- A. 关键产物 sha256 ---"
{
  echo "# FINAL-RERUN sha256 基线  $(date -Iseconds)"
  sha256sum \
    "$TOPICS/edges.csr.npz" \
    "$TOPICS/edges.csr.pre-r1.npz" \
    "$TOPICS/edges.variant-spec.csr.npz" \
    "$TOPICS/nodes.json" \
    "$TOPICS/card_topics.jsonl" \
    "$TOPICS/meta.json" \
    "$TOPICS/topics-report.json" \
    "$TOPICS/topics-report-allseed.json" \
    "$TOPICS/topics-report.txt" \
    "$TOPICS/topics-report-exhaustive.json" 2>&1
} | tee "$OUT/sha256-before.txt"

# ---------- B. 六份 acceptance ----------
echo
echo "--- B. 六份 acceptance 复跑 ---"
: > "$OUT/acceptance-summary.txt"
for p in p0 p1 p2 p3 p4 p5; do
  log="$RUNS/acceptance-$p.log"
  bash "$ACC/topics-$p.sh" > "$log" 2>&1
  rc=$?
  pass=$(grep -c '\[PASS\]' "$log"); pass=${pass:-0}
  fail=$(grep -c '\[FAIL\]' "$log"); fail=${fail:-0}
  tail1=$(grep -E "^TOPICS-P[0-9]: (PASS|FAIL)" "$log" | tail -1)
  printf '%s\texit=%s\tpass=%s\tfail=%s\t%s\n' "topics-$p.sh" "$rc" "$pass" "$fail" "$tail1" \
    | tee -a "$OUT/acceptance-summary.txt"
done

# ---------- C. 生成链复跑 ----------
echo
echo "--- C. 生成链复跑（输出至 runs/，不覆盖正式产物）---"

# C1. topics_report 全量（冻结命令：--samples 400 --hops 12 --seed 42）
echo "[C1] topics_report 全量（冻结命令）"
( cd "$TOOLS" && python3 topics_report.py \
    --samples 400 --hops 12 --seed 42 --random-baseline \
    --json-out "$RUNS/topics-report-rerun.json" \
    --txt-out  "$RUNS/topics-report-rerun.txt" ) > "$RUNS/topics_report.log" 2>&1
echo "    exit=$? → runs/topics-report-rerun.json"

# C2. topics_report 穷举口径（source-type all，对比 allseed 正式值）
echo "[C2] topics_report 全节点源点池（--source-type all）"
( cd "$TOOLS" && python3 topics_report.py \
    --samples 400 --hops 12 --seed 42 --source-type all \
    --json-out "$RUNS/topics-report-rerun-all.json" ) > "$RUNS/topics_report_all.log" 2>&1
echo "    exit=$? → runs/topics-report-rerun-all.json"

# C3. topic_graph 抽 3 命令（只读，stdout 落 runs/）
echo "[C3] topic_graph 抽 3 命令"
( cd "$TOOLS" && timeout 120 python3 topic_graph.py around 139 --hops 3 ) \
  > "$RUNS/graph-around-139-h3.txt" 2>&1
echo "    around 139 --hops 3      exit=$? → runs/graph-around-139-h3.txt"
( cd "$TOOLS" && timeout 120 python3 topic_graph.py search "人工智能伦理" --top 5 ) \
  > "$RUNS/graph-search-ai-ethics.txt" 2>&1
echo "    search 人工智能伦理       exit=$? → runs/graph-search-ai-ethics.txt"
( cd "$TOOLS" && timeout 120 python3 topic_graph.py graph 139 --hops 2 --json-out "$RUNS/graph-139-h2.json" ) \
  > "$RUNS/graph-json-139-h2.log" 2>&1
echo "    graph 139 --hops 2       exit=$? → runs/graph-139-h2.json"

# ---------- D. 修复前后对比实测 ----------
echo
echo "--- D. 修复前后对比实测（pre-r1 备份 vs 当前边表）---"
( cd "$TOOLS" && python3 "$SCRIPT_DIR/compare_edges.py" \
    --before "$TOPICS/edges.csr.pre-r1.npz" \
    --after  "$TOPICS/edges.csr.npz" ) 2>&1 | tee "$RUNS/compare_edges.txt"

echo
echo "--- E. 复跑后 sha256 复核（验证主体未被本次复跑改动）---"
{
  echo "# FINAL-RERUN sha256 复核  $(date -Iseconds)"
  sha256sum \
    "$TOPICS/edges.csr.npz" \
    "$TOPICS/meta.json" \
    "$TOPICS/topics-report.json" \
    "$TOPICS/card_topics.jsonl" 2>&1
} | tee "$OUT/sha256-after.txt"

echo
echo "=== FINAL-RERUN 完成；汇总见 acceptance-summary.txt / REPORT.md ==="
