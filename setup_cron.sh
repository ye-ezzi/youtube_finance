#!/usr/bin/env bash
# 재테크 트렌드 리포트 일일 자동화 설정 스크립트

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$(which python3)"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/daily_trend.log"
ENV_FILE="$SCRIPT_DIR/.env"

# 기본 실행 시간: 매일 오전 9시 KST (= UTC 00:00)
CRON_HOUR="${CRON_HOUR:-0}"
CRON_MIN="${CRON_MIN:-0}"

echo "======================================================"
echo "  📊 재테크 트렌드 리포트 일일 자동화 설정"
echo "======================================================"
echo ""

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"

# .env 파일 확인
if [ ! -f "$ENV_FILE" ]; then
    echo "⚠️  .env 파일이 없습니다. 아래 내용으로 생성해주세요:"
    echo ""
    echo "  cat > $ENV_FILE << 'EOF'"
    echo "  YOUTUBE_API_KEY=여기에_YouTube_API_키_입력"
    echo "  ANTHROPIC_API_KEY=여기에_Anthropic_API_키_입력"
    echo "  EMAIL_FROM=발송자_gmail@gmail.com       # 선택사항"
    echo "  EMAIL_TO=수신자@example.com             # 선택사항"
    echo "  EMAIL_APP_PASSWORD=Gmail_앱_비밀번호    # 선택사항"
    echo "  EOF"
    echo ""
fi

# 크론 작업 항목 구성
# 환경변수를 .env에서 불러오고 실행, 결과를 로그에 기록
CRON_CMD="$CRON_MIN $CRON_HOUR * * * cd $SCRIPT_DIR && $PYTHON_BIN $SCRIPT_DIR/daily_trend.py >> $LOG_FILE 2>&1"

echo "설정 정보:"
echo "  스크립트: $SCRIPT_DIR/daily_trend.py"
echo "  Python:   $PYTHON_BIN"
echo "  로그:     $LOG_FILE"
echo "  실행 시간: 매일 $(printf '%02d:%02d' $CRON_HOUR $CRON_MIN) UTC (KST +9시간)"
echo ""

# 기존 크론 작업 확인
if crontab -l 2>/dev/null | grep -qF "daily_trend.py"; then
    echo "✅ 크론 작업이 이미 등록되어 있습니다:"
    crontab -l | grep "daily_trend.py"
    echo ""
    read -r -p "기존 항목을 교체하시겠습니까? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        # 기존 항목 제거 후 재등록
        (crontab -l 2>/dev/null | grep -v "daily_trend.py"; echo "$CRON_CMD") | crontab -
        echo "✅ 크론 작업 업데이트 완료"
    else
        echo "변경 없이 종료합니다."
        exit 0
    fi
else
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo "✅ 크론 작업 등록 완료!"
fi

echo ""
echo "등록된 크론 작업:"
crontab -l | grep "daily_trend.py"
echo ""
echo "────────────────────────────────────────────────────"
echo "🚀 지금 즉시 실행:"
echo "   python3 $SCRIPT_DIR/daily_trend.py"
echo ""
echo "📋 크론 작업 목록 확인:"
echo "   crontab -l"
echo ""
echo "📊 실시간 로그 확인:"
echo "   tail -f $LOG_FILE"
echo "────────────────────────────────────────────────────"
