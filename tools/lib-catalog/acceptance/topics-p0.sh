#!/usr/bin/env bash
# topics-p0.sh — P0 验收（对齐与骨架）
# 用法: bash acceptance/topics-p0.sh
# 断言: ① baseline-p0.txt 存在且含 "12 跳" 与覆盖数（并校验 90.2%±2%）
#       ② topics/meta.json 为合法 JSON（含 stage=P0 / baseline 字段）
# 可重复运行；全部通过 exit 0，否则 exit 1。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="${LIB_CATALOG_DATA:-$HOME/go/lib-catalog-data}"

PASS=0
FAIL=0
ok()  { echo "  [PASS] $*"; PASS=$((PASS + 1)); }
bad() { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }

echo "=== topics P0 acceptance ==="
echo "workdir : $ROOT_DIR"
echo "data-dir: $DATA_DIR"

# 产物目录解析：优先 data-dir/topics；仅当其中完全没有 P0 产物时才回退 workdir/topics
if [ -f "$DATA_DIR/topics/baseline-p0.txt" ] || [ -f "$DATA_DIR/topics/meta.json" ]; then
  TOPICS_DIR="$DATA_DIR/topics"
  echo "topics  : $TOPICS_DIR (data-dir)"
else
  TOPICS_DIR="$ROOT_DIR/topics"
  echo "topics  : $TOPICS_DIR (workdir 回退：data-dir/topics 无 P0 产物)"
fi

BASELINE="$TOPICS_DIR/baseline-p0.txt"
META="$TOPICS_DIR/meta.json"

# ---- 断言 ① baseline 存在、含 12 跳、覆盖数可解析 ----
echo "[1] baseline-p0.txt"
if [ -s "$BASELINE" ]; then
  ok "存在且非空（$(wc -l < "$BASELINE" | tr -d ' ') 行）"
else
  bad "不存在或为空: $BASELINE"
fi

HOP12_LINE=""
if [ -s "$BASELINE" ]; then
  HOP12_LINE="$(grep -E '12[[:space:]]*跳' "$BASELINE" | head -n 1)"
fi
if [ -n "$HOP12_LINE" ]; then
  ok "含 12 跳口径: $(printf '%s\n' "$HOP12_LINE" | sed 's/^[[:space:]]*//')"
else
  bad 'baseline 未含 "12 跳" 行'
fi

COV="$(printf '%s\n' "$HOP12_LINE" | grep -oE '[0-9]+\.[0-9]+' | head -n 1)"
if [ -n "$COV" ]; then
  ok "12 跳覆盖数可解析: $COV"
  if awk -v v="$COV" 'BEGIN{ exit !(v >= 0.882 && v <= 0.922) }'; then
    ok "12 跳覆盖 $COV ∈ 90.2%±2% 验收带 [0.882, 0.922]"
  else
    bad "12 跳覆盖 $COV 超出验收带 [0.882, 0.922]"
  fi
else
  bad "未能从 baseline 解析 12 跳覆盖数"
fi

# ---- 断言 ② meta.json 存在且为合法 JSON ----
echo "[2] meta.json"
if [ -s "$META" ]; then
  ok "存在且非空"
  if python3 -c 'import json, sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$META" 2>/dev/null; then
    ok "合法 JSON"
    META_INFO="$(python3 -c 'import json, sys; d = json.load(open(sys.argv[1], encoding="utf-8")); print("%s\t%s" % (d.get("stage", ""), d.get("baseline", "")))' "$META")"
    STAGE="${META_INFO%%$'\t'*}"
    BASE_FIELD="${META_INFO#*$'\t'}"
    [ "$STAGE" = "P0" ] && ok "stage=P0" || bad "stage 字段应为 P0（实际: '$STAGE'）"
    case "$BASE_FIELD" in
      *baseline-p0.txt) ok "baseline 字段: $BASE_FIELD" ;;
      *) bad "baseline 字段未指向 baseline-p0.txt（实际: '$BASE_FIELD'）" ;;
    esac
  else
    bad "非法 JSON: $META"
  fi
else
  bad "不存在或为空: $META"
fi

echo "-----------------------------------------"
if [ "$FAIL" -eq 0 ]; then
  echo "TOPICS-P0: PASS (pass=$PASS fail=$FAIL)"
  exit 0
else
  echo "TOPICS-P0: FAIL (pass=$PASS fail=$FAIL)"
  exit 1
fi
