#!/usr/bin/env bash
# 재테크 트렌드 리포트 일일 자동 실행 설정
# 사용법: ./setup_daily.sh [HH:MM]
# 예시:  ./setup_daily.sh 08:30   → 매일 오전 8시 30분 실행 (기본값)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_TIME="${1:-08:30}"
HOUR=$(echo "$RUN_TIME" | cut -d: -f1)
MINUTE=$(echo "$RUN_TIME" | cut -d: -f2)
LOG_FILE="$SCRIPT_DIR/cron.log"

PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
if [ -z "$PYTHON" ]; then
    echo "❌ Python을 찾을 수 없습니다. Python 3를 설치해주세요."
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "⚠️  .env 파일이 없습니다. 아래 항목을 .env에 추가해주세요:"
    echo ""
    echo "  YOUTUBE_API_KEY=your_youtube_api_key"
    echo "  ANTHROPIC_API_KEY=your_anthropic_api_key"
    echo ""
    echo "  # 이메일 발송 (선택)"
    echo "  EMAIL_FROM=your_gmail@gmail.com"
    echo "  EMAIL_TO=recipient@example.com"
    echo "  EMAIL_APP_PASSWORD=gmail_app_password"
    echo ""
fi

# 기존 크론 항목 제거 후 새로 등록
CRON_ENTRY="$MINUTE $HOUR * * * cd \"$SCRIPT_DIR\" && $PYTHON daily_trend.py >> \"$LOG_FILE\" 2>&1"
(crontab -l 2>/dev/null | grep -v "daily_trend.py" || true; echo "$CRON_ENTRY") | crontab -

echo "✅ 일일 재테크 트렌드 리포트 크론 설정 완료"
echo ""
echo "   ⏰ 실행 시간 : 매일 ${HOUR}:${MINUTE} (서버 로컬 시간)"
echo "   📂 스크립트  : $SCRIPT_DIR/daily_trend.py"
echo "   📄 로그 파일 : $LOG_FILE"
echo "   📊 리포트 위치: $SCRIPT_DIR/reports/trend_YYYYMMDD.md"
echo ""
echo "─────────────────────────────────────────"
echo "  지금 바로 실행하려면:"
echo "    $PYTHON $SCRIPT_DIR/daily_trend.py"
echo ""
echo "  크론 설정 확인:"
echo "    crontab -l"
echo ""
echo "  크론 제거:"
echo "    crontab -l | grep -v daily_trend.py | crontab -"
echo "─────────────────────────────────────────"
