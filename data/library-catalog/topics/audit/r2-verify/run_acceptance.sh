#!/usr/bin/env bash
# run_acceptance.sh — R2-E 全链复跑：acceptance P0-P5（只读主体；stdout/exit 落 runs/）
# 用法: bash audit/r2-verify/run_acceptance.sh
set -u
cd /home/wzh/go/reasonix-scripts/lib-catalog
R=/home/wzh/go/lib-catalog-data/topics/audit/r2-verify/runs
mkdir -p "$R"
for n in 0 1 2 3 4 5; do
  s="acceptance/topics-p${n}.sh"
  { bash "$s"; echo "EXIT_CODE=$?"; } > "$R/acceptance-p${n}.log" 2>&1
  printf 'P%s rc=%s  PASS_lines=%s FAIL_lines=%s\n' "$n" \
    "$(grep -o 'EXIT_CODE=[0-9]*' "$R/acceptance-p${n}.log" | cut -d= -f2)" \
    "$(grep -c '\[PASS\]' "$R/acceptance-p${n}.log")" \
    "$(grep -c '\[FAIL\]' "$R/acceptance-p${n}.log")"
done
echo "ACCEPTANCE_DONE"
