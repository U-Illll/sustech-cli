#!/usr/bin/env bash
# tests/regression/run_all.sh — 回归集总入口（REGRESSION-SET）
#
# 用法:
#   bash tests/regression/run_all.sh                 # 连跑全部用例并汇总
#   bash tests/regression/run_all.sh --list          # 只列用例
#   bash tests/regression/run_all.sh --only r2,r3    # 按脚本名子串筛选
#   PYTHON=python3.12 bash tests/regression/run_all.sh
#
# 汇总口径：PASS / WARN / FAIL / SKIP 四计数（从各用例的 `RESULT <tag> <verdict> ...` 行解析）
#   * FAIL > 0            → 整体 FAIL，exit 1
#   * FAIL == 0 且 WARN>0 → 整体 PASS（含 WARN），exit 0；WARN = **R2 未纳入修复**的已知缺陷
#                            （R2-E 后仅剩 M6；D1/M2/F2 已升级为硬断言，回归即 FAIL）
#   * 某用例未输出 RESULT 行（崩溃/被杀）→ 记为 FAIL（绝不允许静默通过）
#
# 约束：本脚本只读既有产物；不修改主体代码与验收脚本；不访问网络。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
export LIB_CATALOG_DATA="${LIB_CATALOG_DATA:-$HOME/go/lib-catalog-data}"
export PYTHONDONTWRITEBYTECODE=1          # 只读纪律：不落 __pycache__

CASES=(
  r1_consistency_weight.py
  r2_assoc_order.py
  r3_no_overhop.py
  r4_guards.py
  r5_card_count.py
  r6_known_defects.py
)
DESC=(
  "终审① 共现权重独立重算 + 终审⑤ 断言"
  "终审② assoc 主排序键（内存反例 + 真实图锚点 + 多源点不变式）"
  "终审③ 扩散不超跳（内存反例 + 真实图）"
  "参数护栏与 --budget/--hops/--threshold 语义"
  "卡数对齐 + 每卡规格 + P3 门槛/口径冻结"
  "已知未修缺陷预警 xfail（D1/M2/F2/M6，待 R2）"
)

ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --list)
      echo "回归集用例（$SCRIPT_DIR）："
      for i in "${!CASES[@]}"; do printf "  %-28s %s\n" "${CASES[$i]}" "${DESC[$i]}"; done
      exit 0 ;;
    --only) ONLY="${2:-}"; shift 2 ;;
    --only=*) ONLY="${1#--only=}"; shift ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "未知参数：$1（用 --help 查看用法）" >&2; exit 2 ;;
  esac
done

matched() {
  [ -z "$ONLY" ] && return 0
  local IFS=','
  for pat in $ONLY; do
    case "$1" in *"$pat"*) return 0 ;; esac
  done
  return 1
}

echo "========================================================================="
echo "REGRESSION-SET 回归集总跑"
echo "  用例目录 : $SCRIPT_DIR"
echo "  主体目录 : $LIB_DIR"
echo "  数据目录 : $LIB_CATALOG_DATA"
echo "  解释器   : $PYTHON ($($PYTHON -V 2>&1))"
[ -n "$ONLY" ] && echo "  筛选     : $ONLY"
echo "========================================================================="

T_PASS=0; T_FAIL=0; T_WARN=0; T_SKIP=0; T_CASES=0; T_BAD=0
ROWS=()

for i in "${!CASES[@]}"; do
  f="${CASES[$i]}"
  matched "$f" || continue
  T_CASES=$((T_CASES + 1))
  echo ""
  echo "──── [$T_CASES] $f ── ${DESC[$i]}"
  if [ ! -f "$SCRIPT_DIR/$f" ]; then
    echo "  [FAIL] 脚本缺失：$SCRIPT_DIR/$f"
    ROWS+=("$(printf '%-28s %-6s %5s %5s %5s %5s %6s' "$f" "FAIL" 0 1 0 0 "-")")
    T_FAIL=$((T_FAIL + 1)); T_BAD=$((T_BAD + 1))
    continue
  fi
  LOG="$(mktemp)"
  START=$(date +%s)
  ( cd "$SCRIPT_DIR" && "$PYTHON" "$f" ) 2>&1 | tee "$LOG"
  RC=${PIPESTATUS[0]}
  ELAPSED=$(( $(date +%s) - START ))
  RES="$(grep -m1 '^RESULT ' "$LOG" || true)"
  rm -f "$LOG"

  if [ -z "$RES" ]; then
    echo "  [FAIL] 未输出 RESULT 行（崩溃/超时？exit=$RC）——按 FAIL 计入"
    ROWS+=("$(printf '%-28s %-6s %5s %5s %5s %5s %5ss' "$f" "CRASH" 0 1 0 0 "$ELAPSED")")
    T_FAIL=$((T_FAIL + 1)); T_BAD=$((T_BAD + 1))
    continue
  fi

  VD="$(printf '%s' "$RES" | awk '{print $3}')"
  P="$(printf '%s' "$RES" | sed -n 's/.* pass=\([0-9]*\).*/\1/p')"
  FA="$(printf '%s' "$RES" | sed -n 's/.* fail=\([0-9]*\).*/\1/p')"
  W="$(printf '%s' "$RES" | sed -n 's/.* warn=\([0-9]*\).*/\1/p')"
  S="$(printf '%s' "$RES" | sed -n 's/.* skip=\([0-9]*\).*/\1/p')"
  P=${P:-0}; FA=${FA:-0}; W=${W:-0}; S=${S:-0}
  T_PASS=$((T_PASS + P)); T_FAIL=$((T_FAIL + FA))
  T_WARN=$((T_WARN + W)); T_SKIP=$((T_SKIP + S))
  ROWS+=("$(printf '%-28s %-6s %5s %5s %5s %5s %5ss' "$f" "$VD" "$P" "$FA" "$W" "$S" "$ELAPSED")")
done

echo ""
echo "========================================================================="
echo "回归集汇总（REGRESSION-SET）—— 表头按 ASCII 输出以保证列对齐"
echo "-------------------------------------------------------------------------"
printf '%-28s %-6s %5s %5s %5s %5s %6s\n' "CASE" "VERDICT" "PASS" "FAIL" "WARN" "SKIP" "SEC"
printf '%-28s %-6s %5s %5s %5s %5s %6s\n' "----------------------------" "------" "-----" "-----" "-----" "-----" "------"
for r in "${ROWS[@]}"; do echo "$r"; done
echo "-------------------------------------------------------------------------"
printf '%-28s %-6s %5s %5s %5s %5s\n' "TOTAL ($T_CASES cases)" "P/W/F" "$T_PASS" "$T_FAIL" "$T_WARN" "$T_SKIP"
echo "========================================================================="
if [ "$T_FAIL" -gt 0 ]; then
  echo "REGRESSION-SET: FAIL（fail=$T_FAIL，warn=$T_WARN）"
  exit 1
fi
if [ "$T_WARN" -gt 0 ]; then
  echo "REGRESSION-SET: PASS（warn=$T_WARN —— R2 未纳入修复的已知缺陷预警，不计入 FAIL）"
else
  echo "REGRESSION-SET: PASS（全绿：pass=$T_PASS skip=$T_SKIP）"
fi
exit 0
