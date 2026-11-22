#!/bin/bash
# Tam taramayı başlatır. Bot çökerse yeniden başlatır, belli aralıklarla
# veriyi tarifler/ klasörüne aktarıp GitHub'a pushlar.
#   ./calistir.sh                 # tüm kategoriler
#   PUSH_INTERVAL=3600 ./calistir.sh
cd "$(dirname "$0")" || exit 1
LOG=scraper.log
INTERVAL=${PUSH_INTERVAL:-7200}

push() {
  python3 scraper.py --export >> "$LOG" 2>&1 || return
  git add tarifler
  if ! git diff --cached --quiet; then
    git commit -q -m "Veri güncellemesi: $(date '+%Y-%m-%d %H:%M')" \
      -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
    if git push -q origin main >> "$LOG" 2>&1; then
      echo "[$(date)] GitHub'a pushlandı" >> "$LOG"
    else
      echo "[$(date)] push başarısız, sonraki turda tekrar denenecek" >> "$LOG"
    fi
  fi
}

( sleep 1200; push; while true; do sleep "$INTERVAL"; push; done ) &
PUSHER=$!
trap 'kill $PUSHER 2>/dev/null' EXIT

for i in $(seq 1 50); do
  python3 -u scraper.py "$@" >> "$LOG" 2>&1
  code=$?
  [ $code -eq 0 ] || [ $code -eq 130 ] && break
  echo "[$(date)] bot durdu (kod $code), 60 sn sonra yeniden başlıyor ($i/50)" >> "$LOG"
  sleep 60
done
kill $PUSHER 2>/dev/null
push
echo "[$(date)] Tarama tamamlandı." >> "$LOG"
