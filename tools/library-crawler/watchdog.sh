#!/bin/bash
# watchdog v2：v8 完成 + 涵泳 round2 收尾 → 自动 process + 交付到桌面
LOG=/tmp/library-scrape/watchdog.log
echo "$(date '+%F %T') watchdog v2 started" >> "$LOG"

while true; do
  V8=0
  if grep -q "全部完成" /tmp/library-scrape/output/scrape.log 2>/dev/null \
     && ! pgrep -f "library-scrape/scrape.py" >/dev/null 2>&1; then
    V8=1
  fi
  echo "$(date '+%F %T') V8=$V8" >> "$LOG"
  if [ "$V8" = "1" ]; then
    # 等涵泳 v4 收尾（最多 40 分钟；v3 已完成）
    for i in $(seq 1 40); do
      if grep -q "=== 完成" /tmp/library-scrape/hanyong_extra2.log 2>/dev/null; then
        echo "$(date '+%F %T') hanyong v4 done" >> "$LOG"
        break
      fi
      if ! pgrep -f "hanyong_fill4" >/dev/null 2>&1; then
        echo "$(date '+%F %T') hanyong v4 not running" >> "$LOG"
        break
      fi
      sleep 60
    done
    cd /tmp/library-scrape || exit 1
    echo "$(date '+%F %T') running process.py" >> "$LOG"
    python3 process.py > process_final.log 2>&1
    DEST="/mnt/c/Users/汪子恒/Desktop/南科大图书馆藏书目录"
    mkdir -p "$DEST"
    cp final/catalog_full.csv final/books.csv final/shelf_index.csv final/sustc_library.db final/README.md final/report.txt "$DEST/" 2>> "$LOG"
    cp hanyong_partial.jsonl "$DEST/涵泳特藏_直取.jsonl" 2>> "$LOG"
    [ -f hanyong_extra.jsonl ] && cp hanyong_extra.jsonl "$DEST/涵泳特藏_穷举补全.jsonl" 2>> "$LOG"
    [ -f hanyong_extra2.jsonl ] && cp hanyong_extra2.jsonl "$DEST/涵泳特藏_穷举补全2.jsonl" 2>> "$LOG"
    cp output/scrape.log "$DEST/抓取日志.txt" 2>> "$LOG"
    echo "$(date '+%F %T') DELIVERED" >> "$LOG"
    break
  fi
  sleep 120
done
