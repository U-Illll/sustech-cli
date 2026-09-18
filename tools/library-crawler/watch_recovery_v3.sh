#!/bin/bash
# 补抓进度监听 v3p（根级并行版配套）：进程退出时判定 完成/中断；期间记录根进度
LOG=/tmp/library-scrape/recovery-20260916.log
STATUS=/tmp/library-scrape/recovery-status.txt
PROG=/tmp/library-scrape/recovery-progress.json
LAST=""
echo "watch-start-v3p $(date '+%F %T')" >> "$STATUS"
while true; do
  if ! pgrep -f "recovery_crawl_v3" > /dev/null; then
    DONE_N=$(python3 -c "import json;d=json.load(open('$PROG'));print(len(d.get('done',[])))" 2>/dev/null || echo "?")
    if [ "$DONE_N" = "125" ]; then
      echo "DONE $(date '+%F %T') 全部完成（done=125）" >> "$STATUS"
    else
      echo "INTERRUPTED $(date '+%F %T') 进程退出但 done=$DONE_N/125 —— 需要重启续跑！" >> "$STATUS"
    fi
    break
  fi
  N=$(grep -c "→ got=" "$LOG" 2>/dev/null || echo 0)
  if [ "$N" != "$LAST" ]; then
    echo "progress-v3p $(date '+%H:%M:%S') 累计根完成行=$N" >> "$STATUS"
    LAST=$N
  fi
  sleep 60
done
