#!/usr/bin/env bash
# topics-p5.sh — P5 验收（交付与发行决策；只生成不发布）
# 用法: bash acceptance/topics-p5.sh 2>&1 | tee "$HOME/go/lib-catalog-data/topics/acceptance-p5.log"
# 断言:
#   [1] 三份交付文档存在且非空（topics/README.md、topics/INTERFACE-PROPOSAL.md、topics/ACCEPTANCE-REPORT.md）
#   [2] topics/README.md 覆盖要素：四类产物 schema / 四条命令 / 错误码表 / LLM 接口签名 / 近词扩展
#   [3] 工具链 README.md 含「v2 → v3 变更记录」章节（纯追加，未破坏原章节）
#   [4] 交接文档：§3.2 含 --rank-by assoc 回写；含新增「施工结果」节
#   [5] export-sample 自洽（只生成不发布）：manifest/二进制回读/dtype/计数/权重还原误差 ≤ 1/255
#   [6] meta.json stages.P0–P4 齐备
# 可重复运行；全部通过 exit 0，否则 exit 1。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="${LIB_CATALOG_DATA:-$HOME/go/lib-catalog-data}"
TOPICS_DIR="$DATA_DIR/topics"
SAMPLE="${SAMPLE_DIR:-$TOPICS_DIR/export-sample/v1}"

PASS=0
FAIL=0
ok()   { echo "  [PASS] $*"; PASS=$((PASS + 1)); }
bad()  { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }
info() { echo "  [INFO] $*"; }

echo "=== topics P5 acceptance ==="
echo "workdir : $ROOT_DIR"
echo "data-dir: $DATA_DIR"

# ---- [1] 交付文档 ----
echo "[1] 交付文档（三份）"
for f in "$TOPICS_DIR/README.md" "$TOPICS_DIR/INTERFACE-PROPOSAL.md" "$TOPICS_DIR/ACCEPTANCE-REPORT.md"; do
  if [ -s "$f" ]; then ok "$(basename "$f") 存在（$(wc -l < "$f" | tr -d ' ') 行 / $(du -h "$f" | cut -f1)）"; else bad "缺失或为空: $f"; fi
done

# ---- [2] README 要素 ----
echo "[2] topics/README.md 覆盖要素"
README="$TOPICS_DIR/README.md"
check_kw() { if grep -q -- "$2" "$README" 2>/dev/null; then ok "$1"; else bad "README 缺要素：$1（关键字 '$2'）"; fi; }
check_kw "四类产物 schema（nodes.json / edges.csr.npz / card_topics.jsonl / meta.json）" "edges.csr.npz"
check_kw "CSR dtype 说明（int64/int32/float32）" "float32"
check_kw "P1 命令 topic_build.py" "topic_build.py"
check_kw "P2 命令 topic_edges.py" "topic_edges.py"
check_kw "P3 命令 topics_report.py" "topics_report.py"
check_kw "P4 命令 topic_graph.py" "topic_graph.py"
check_kw "近词扩展（tfidf-expand）" "tfidf-expand"
check_kw "LLM 接口签名 summarize_topic_region" "summarize_topic_region"
check_kw "错误码表（exit 3 / --strict-llm）" "strict-llm"
check_kw "验收脚本清单" "topics-p4.sh"

# ---- [3] 工具链 README 变更记录 ----
echo "[3] 工具链 README.md 的 v2→v3 变更记录"
TR="$ROOT_DIR/README.md"
if grep -qE "v2 *→ *v3|v2->v3" "$TR" 2>/dev/null; then
  ok "含「v2 → v3 变更记录」章节（追加后 $(wc -l < "$TR" | tr -d ' ') 行）"
else
  bad "工具链 README 未含 v2→v3 变更记录章节"
fi
grep -q "topics" "$TR" && ok "变更记录含 topics 子模块条目" || bad "变更记录缺 topics 条目"

# ---- [4] 交接文档回写 ----
echo "[4] 交接文档回写（§3.2 + 施工结果节）"
HD="$ROOT_DIR/TOPIC-GRAPH-HANDOFF-20260918.md"
grep -q -- "--rank-by assoc" "$HD" && ok "§3.2 已回写 --rank-by assoc 排序键口径" || bad "§3.2 未回写 assoc 口径"
grep -qE "^## 8\. 施工结果" "$HD" && ok "文末已追加「## 8. 施工结果」节" || bad "缺施工结果节"
grep -qE "^## 3\. 设计规范" "$HD" && grep -qE "^## 7\. 附录" "$HD" && ok "原文既有结构（§3/§7）未破坏" || bad "原文结构被破坏"

# ---- [5] export-sample 自洽（只生成不发布） ----
echo "[5] export-sample 自洽性（$SAMPLE）"
if [ ! -d "$SAMPLE" ]; then
  bad "样例目录不存在: $SAMPLE（生成: python3 export_release.py --topics-only --out $TOPICS_DIR/export-sample --version v1）"
else
  ok "样例目录存在"
  RES="$(python3 - "$SAMPLE" "$TOPICS_DIR" "$DATA_DIR" <<'PY' 2>&1
import json, os, sys
sys.path.insert(0, os.path.expanduser("~/go/pylibs"))
import numpy as np
sample, topics_dir, D = sys.argv[1], sys.argv[2], sys.argv[3]
t = os.path.join(sample, "topics")
ip = np.fromfile(os.path.join(t, "edges_indptr.i64.bin"), dtype=np.int64)
ix = np.fromfile(os.path.join(t, "edges_indices.i32.bin"), dtype=np.int32)
wu = np.fromfile(os.path.join(t, "edges_weights.u8.bin"), dtype=np.uint8)
cip = np.fromfile(os.path.join(t, "card_topics_indptr.i32.bin"), dtype=np.int32)
cid = np.fromfile(os.path.join(t, "card_topics_ids.i32.bin"), dtype=np.int32)
nodes = json.load(open(os.path.join(t, "nodes.json"), encoding="utf-8"))
z = np.load(os.path.join(topics_dir, "edges.csr.npz"))
man = json.load(open(os.path.join(sample, "manifest.json"), encoding="utf-8"))
err = np.abs(wu.astype(np.float32) / 255.0 - z["weights"])
ncards = sum(1 for _ in open(os.path.join(topics_dir, "card_topics.jsonl"), encoding="utf-8"))
print("DTYPES=%s/%s/%s" % (ip.dtype, ix.dtype, wu.dtype))
print("NODES_OK=%s" % (len(nodes) == len(ip) - 1))
print("EDGES_OK=%s" % (len(ix) == len(z["indices"]) and len(wu) == len(ix)))
print("IPTR_OK=%s" % (int(ip[0]) == 0 and int(ip[-1]) == len(ix)))
print("CARDS_OK=%s" % (len(cip) - 1 == ncards and int(cip[-1]) == len(cid)))
print("W_ERR=%.6f" % float(err.max()))
print("W_ERR_OK=%s" % bool(err.max() <= 1.0 / 255 + 1e-6))
print("MANIFEST_OK=%s" % ("topics" in (man.get("stats") or {})))
print("MANIFEST_FILES=%d" % len(man.get("files") or []))
print("TOTAL_BYTES=%d" % man.get("total_bytes", 0))
PY
)"
  echo "$RES" | sed 's/^/    /'
  getv() { printf '%s\n' "$RES" | sed -n "s/^$1=//p" | head -n 1; }
  [ "$(getv DTYPES)" = "int64/int32/uint8" ] && ok "二进制回读 dtype 正确（int64/int32/uint8）" || bad "dtype 异常（$(getv DTYPES)）"
  [ "$(getv NODES_OK)" = "True" ] && ok "节点数 = indptr-1（$(getv NODES_OK)）" || bad "节点数与 indptr 不一致"
  [ "$(getv EDGES_OK)" = "True" ] && ok "边数与源边表一致" || bad "边数与源不一致"
  [ "$(getv IPTR_OK)" = "True" ] && ok "CSR indptr 首 0 尾 nnz" || bad "CSR indptr 异常"
  [ "$(getv CARDS_OK)" = "True" ] && ok "证据链 CSR 与 card_topics.jsonl 行数/链接数一致" || bad "证据链 CSR 不一致"
  [ "$(getv W_ERR_OK)" = "True" ] && ok "uint8 权重还原误差 $(getv W_ERR) ≤ 1/255" || bad "权重还原误差超界：$(getv W_ERR)"
  [ "$(getv MANIFEST_OK)" = "True" ] && ok "manifest.json 含 topics 段（$(getv MANIFEST_FILES) 个文件 / $(getv TOTAL_BYTES) 字节）" || bad "manifest 缺 topics 段"
fi
info "只生成不发布：样例落 topics/export-sample/，未写入 ~/go/lib-catalog-release/"

# ---- [6] meta 阶段齐备 ----
echo "[6] meta.json stages 齐备"
MP="$(python3 - "$TOPICS_DIR/meta.json" <<'PY' 2>&1
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
st = m.get("stages") or {}
print("STAGES=%s" % ",".join(sorted(st)))
print("MISSING=%s" % ",".join(s for s in ("P0", "P1", "P2", "P3", "P4") if s not in st))
print("CURRENT=%s" % m.get("current_stage"))
print("TOP_STAGE=%s" % m.get("stage"))
PY
)"
echo "$MP" | sed 's/^/    /'
getm() { printf '%s\n' "$MP" | sed -n "s/^$1=//p" | head -n 1; }
[ -z "$(getm MISSING)" ] && ok "stages.P0–P4 五段齐备" || bad "缺阶段：$(getm MISSING)"
[ "$(getm TOP_STAGE)" = "P0" ] && ok "顶层 stage 仍为 P0（旧验收兼容）" || bad "顶层 stage 被改动"

echo "-----------------------------------------"
if [ "$FAIL" -eq 0 ]; then
  echo "TOPICS-P5: PASS (pass=$PASS fail=$FAIL)"
  exit 0
else
  echo "TOPICS-P5: FAIL (pass=$PASS fail=$FAIL)"
  exit 1
fi
