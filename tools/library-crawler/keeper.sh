#!/bin/bash
# keeper：进程看护。发现引擎意外死亡且未完成 → 自动重启（setsid 脱离进程组）
LOG=/tmp/library-scrape/keeper.log
log(){ echo "$(date '+%F %T') $1" >> "$LOG"; }
log "keeper started"
sleep 60   # 等待首次稳定

while true; do
  # --- v8 主抓取 ---
  if ! grep -q "全部完成" /tmp/library-scrape/output/scrape.log 2>/dev/null; then
    if ! pgrep -f "scrape\.py" >/dev/null 2>&1; then
      log "v8[scrape.py] 不在且未完成 → 重启"
      cd /tmp/library-scrape && setsid nohup python3 scrape.py >> output/run.log 2>&1 &
      sleep 5
    fi
  fi
  # --- hanyong 补全 ---
  if ! grep -q "=== 完成" /tmp/library-scrape/hanyong_extra.log 2>/dev/null; then
    if ! pgrep -f "hanyong_fill3" >/dev/null 2>&1; then
      log "hanyong[v3] 不在且未完成 → 重启"
      setsid nohup python3 /tmp/hanyong_fill3.py >> /tmp/library-scrape/hanyong_run3.log 2>&1 &
      sleep 5
    fi
  fi
  sleep 180
done
