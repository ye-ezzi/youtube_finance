#!/usr/bin/env bash
# 재테크 일일 트렌드 리포트 — 매일 자동 실행 설정
# 사용법: bash setup_cron.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(which python3)"
LOG_DIR="$SCRIPT_DIR/logs"
CRON_TIME="${CRON_TIME:-30 8}"   # 기본값: 매일 오전 8시 30분

mkdir -p "$LOG_DIR"

# .env 파일 존재 여부 확인
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  .env 파일이 없습니다. 먼저 생성해주세요."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    cat <<EOF
.env 파일 예시 ($SCRIPT_DIR/.env):

YOUTUBE_API_KEY=AIza...
ANTHROPIC_API_KEY=sk-ant-...

# 이메일 발송 (선택 사항, Gmail 앱 비밀번호 필요)
EMAIL_FROM=your@gmail.com
EMAIL_TO=recipient@gmail.com
EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
EOF
    exit 1
fi

CRON_JOB="$CRON_TIME * * * $PYTHON $SCRIPT_DIR/daily_trend.py >> $LOG_DIR/daily_trend.log 2>&1"

# 기존 동일 항목 제거 후 재등록
( crontab -l 2>/dev/null | grep -v "daily_trend.py" ; echo "$CRON_JOB" ) | crontab -

echo "✅ cron 등록 완료!"
echo "   실행 시각: 매일 $(echo $CRON_TIME | awk '{print $2}')시 $(echo $CRON_TIME | awk '{print $1}')분"
echo "   로그 위치: $LOG_DIR/daily_trend.log"
echo ""
echo "현재 등록된 cron 목록:"
crontab -l | grep daily_trend.py
