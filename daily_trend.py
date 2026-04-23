#!/usr/bin/env python3
"""
재테크 YouTube 채널의 최신 동영상 + 실시간 시장 데이터를 분석하여
오늘의 트렌드 리포트를 생성합니다.
ANTHROPIC_API_KEY와 YOUTUBE_API_KEY 환경변수(또는 .env 파일)가 필요합니다.
"""
import json
import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error

import anthropic

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
LOOKBACK_HOURS = 48

# Yahoo Finance 심볼 목록
MARKET_SYMBOLS = {
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
    "S&P500": "^GSPC",
    "NASDAQ": "^IXIC",
    "다우존스": "^DJI",
    "USD/KRW": "USDKRW=X",
    "금(Gold)": "GC=F",
    "WTI원유": "CL=F",
}

CRYPTO_NAMES = {
    "bitcoin": "비트코인",
    "ethereum": "이더리움",
    "ripple": "리플",
}


# ──────────────────────────────────────────────
# 환경변수 / .env 로더
# ──────────────────────────────────────────────

def load_env_key(var_name):
    key = os.getenv(var_name)
    if not key:
        env_file = Path(__file__).parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith(f"{var_name}="):
                    key = line.split("=", 1)[1].strip()
                    break
    return key


# ──────────────────────────────────────────────
# YouTube 데이터 수집
# ──────────────────────────────────────────────

def youtube_get(endpoint, params):
    url = f"{YOUTUBE_API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def fetch_channel_videos(channel_id, api_key, max_results=10):
    data = youtube_get("search", {
        "channelId": channel_id,
        "part": "snippet",
        "order": "date",
        "type": "video",
        "maxResults": max_results,
        "key": api_key,
    })
    items = data.get("items", [])
    if not items:
        return []

    video_ids = ",".join(i["id"]["videoId"] for i in items)
    details = youtube_get("videos", {
        "id": video_ids,
        "part": "snippet,statistics,contentDetails",
        "key": api_key,
    })

    videos = []
    for v in details.get("items", []):
        snippet = v["snippet"]
        stats = v.get("statistics", {})
        videos.append({
            "video_id": v["id"],
            "title": snippet["title"],
            "published_at": snippet["publishedAt"],
            "description": snippet["description"][:400],
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "view_count": int(stats.get("viewCount", 0)),
            "like_count": int(stats.get("likeCount", 0)),
            "comment_count": int(stats.get("commentCount", 0)),
        })
    return videos


def collect_all_videos(api_key, channels):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)

    all_data = []
    for ch in channels:
        print(f"  수집 중: {ch['name']} ...", end=" ", flush=True)
        try:
            videos = fetch_channel_videos(ch["channel_id"], api_key)
        except urllib.error.HTTPError as e:
            print(f"오류 {e.code}")
            continue

        recent = [
            v for v in videos
            if datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")) >= cutoff
        ]
        if not recent and videos:
            recent = videos[:3]

        if recent:
            all_data.append({
                "channel_name": ch["name"],
                "channel_url": ch.get("url", ""),
                "videos": recent,
            })
            print(f"{len(recent)}개 동영상")
        else:
            print("동영상 없음")

    return all_data


def build_video_summary(all_data):
    lines = []
    for ch_data in all_data:
        lines.append(f"\n## {ch_data['channel_name']}")
        for v in ch_data["videos"]:
            pub_dt = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
            pub_kst = pub_dt + timedelta(hours=9)
            pub_str = pub_kst.strftime("%m/%d %H:%M KST")
            lines.append(f"- [{pub_str}] {v['title']}")
            lines.append(f"  조회수: {v['view_count']:,} | 좋아요: {v['like_count']:,} | 댓글: {v['comment_count']:,}")
            lines.append(f"  링크: {v['url']}")
            if v["description"].strip():
                desc = v["description"][:300].strip().replace("\n", " ")
                lines.append(f"  설명: {desc}")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# 실시간 시장 데이터 수집
# ──────────────────────────────────────────────

def _http_get_json(url, timeout=10):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FinanceBot/1.0)",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def fetch_market_data():
    """Yahoo Finance v8 API로 주요 지수/환율 데이터 수집."""
    results = {}
    for name, symbol in MARKET_SYMBOLS.items():
        try:
            encoded = urllib.parse.quote(symbol)
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
                f"?interval=1d&range=5d"
            )
            data = _http_get_json(url)
            meta = data["chart"]["result"][0]["meta"]

            current = meta.get("regularMarketPrice") or meta.get("price", 0)
            prev_close = meta.get("chartPreviousClose") or meta.get("previousClose", 0)

            if prev_close and prev_close != 0:
                change = current - prev_close
                change_pct = (change / prev_close) * 100
            else:
                change = change_pct = 0

            results[name] = {
                "current": current,
                "prev_close": prev_close,
                "change": change,
                "change_pct": change_pct,
                "currency": meta.get("currency", ""),
            }
        except Exception as e:
            results[name] = {"error": str(e)}

    return results


def fetch_crypto_data():
    """CoinGecko API로 암호화폐 가격 수집 (API 키 불필요)."""
    ids = ",".join(CRYPTO_NAMES.keys())
    url = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids}&vs_currencies=usd,krw&include_24hr_change=true"
    )
    try:
        return _http_get_json(url)
    except Exception as e:
        return {"error": str(e)}


def build_market_summary(market_data, crypto_data):
    """시장 데이터를 리포트용 문자열로 변환."""
    lines = ["## 📊 실시간 시장 데이터"]

    lines.append("\n### 주요 지수 / 환율")
    for name, info in market_data.items():
        if "error" in info:
            lines.append(f"- {name}: 수집 실패 ({info['error'][:60]})")
            continue
        cur = info["current"]
        pct = info["change_pct"]
        arrow = "▲" if pct >= 0 else "▼"
        sign = "+" if pct >= 0 else ""
        currency = info.get("currency", "")

        if "KRW" in name or "KRW" in currency:
            lines.append(f"- {name}: {cur:,.2f} {arrow} {sign}{pct:.2f}%")
        elif name in ("KOSPI", "KOSDAQ"):
            lines.append(f"- {name}: {cur:,.2f} {arrow} {sign}{pct:.2f}%")
        else:
            lines.append(f"- {name}: {cur:,.2f} {currency} {arrow} {sign}{pct:.2f}%")

    if "error" not in crypto_data:
        lines.append("\n### 암호화폐")
        for coin_id, kr_name in CRYPTO_NAMES.items():
            info = crypto_data.get(coin_id)
            if not info:
                continue
            usd = info.get("usd", 0)
            krw = info.get("krw", 0)
            chg = info.get("usd_24h_change", 0) or 0
            arrow = "▲" if chg >= 0 else "▼"
            sign = "+" if chg >= 0 else ""
            lines.append(f"- {kr_name}(BTC): ${usd:,.0f} / ₩{krw:,.0f} {arrow} {sign}{chg:.2f}% (24h)")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# Claude 리포트 생성
# ──────────────────────────────────────────────

def generate_trend_report(video_summary, market_summary, today_str):
    client = anthropic.Anthropic()

    system_prompt = """당신은 한국의 재테크 전문 분석가입니다.
YouTube 재테크 채널들의 최신 동영상 데이터와 실시간 시장 데이터를 종합하여
오늘의 투자 트렌드 리포트를 작성합니다.

리포트 작성 원칙:
- 실시간 시장 수치와 YouTube 채널 콘텐츠를 연결하여 분석합니다
- 여러 채널에서 공통적으로 다루는 주제를 핵심 트렌드로 파악합니다
- 언급되는 종목, 자산 클래스, 섹터를 정리합니다
- 전반적인 시장 센티먼트(긍정/부정/중립)를 수치 근거와 함께 파악합니다
- 재테크 초보자도 이해할 수 있는 명확한 한국어로 작성합니다
- 구체적인 영상 제목과 채널명을 인용하여 근거를 제시합니다
- 과도한 투자 권유나 단정적 예측은 하지 않습니다"""

    user_message = f"""오늘 날짜: {today_str}

{market_summary}

---

다음은 최근 48시간 내 수집된 재테크 YouTube 채널들의 최신 동영상입니다:

{video_summary}

---

위 시장 데이터와 YouTube 콘텐츠를 바탕으로 오늘의 재테크 트렌드 리포트를 아래 형식으로 작성해주세요:

📊 **오늘의 재테크 트렌드 리포트** ({today_str})

1. 📈 **오늘의 시장 요약** (주요 지수 흐름과 특이 사항)

2. 🔥 **핵심 트렌드** (오늘 YouTube에서 가장 많이 다뤄진 주제 3~5가지)

3. 💰 **주목받는 종목 / 자산** (시장 수치와 연결하여 설명)

4. 🌡️ **시장 센티먼트** (강세/약세/혼조 — 수치 근거 포함)

5. 📺 **채널별 주요 내용** (각 채널이 오늘 집중한 내용)

6. 💡 **오늘의 핵심 인사이트** (오늘 꼭 알아야 할 2~3가지)

7. ⚠️ **주의사항** (리스크 요인 또는 놓치면 안 되는 이슈)"""

    report_parts = []
    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=[{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            report_parts.append(text)

    return "".join(report_parts)


# ──────────────────────────────────────────────
# 저장 / 이메일
# ──────────────────────────────────────────────

def save_report(report, market_summary, today_str):
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    date_slug = datetime.now().strftime("%Y%m%d")
    report_path = reports_dir / f"trend_{date_slug}.md"
    content = (
        f"# 재테크 트렌드 리포트 — {today_str}\n\n"
        f"{market_summary}\n\n---\n\n"
        f"{report}\n"
    )
    report_path.write_text(content, encoding="utf-8")
    return report_path


def send_email(report, today_str):
    sender = load_env_key("EMAIL_FROM")
    recipient = load_env_key("EMAIL_TO")
    password = load_env_key("EMAIL_APP_PASSWORD")

    if not all([sender, recipient, password]):
        print("이메일 설정이 없어 발송을 건너뜁니다. (.env에 EMAIL_FROM, EMAIL_TO, EMAIL_APP_PASSWORD 추가)")
        return

    html_body = "<br>".join(
        f"<b>{line}</b>" if line.startswith("#") else line
        for line in report.replace("**", "").splitlines()
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 재테크 트렌드 리포트 — {today_str}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(report, "plain", "utf-8"))
    msg.attach(MIMEText(f"<pre style='font-family:sans-serif'>{html_body}</pre>", "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
    print(f"이메일 발송 완료 → {recipient}")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  재테크 YouTube 일일 트렌드 리포트")
    print("=" * 60)

    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    print(f"  날짜: {today_str}\n")

    youtube_key = load_env_key("YOUTUBE_API_KEY")
    if not youtube_key:
        sys.exit("YOUTUBE_API_KEY가 없습니다. .env 파일 또는 환경변수를 설정해주세요.")

    anthropic_key = load_env_key("ANTHROPIC_API_KEY")
    if not anthropic_key:
        sys.exit("ANTHROPIC_API_KEY가 없습니다. .env 파일 또는 환경변수를 설정해주세요.")
    os.environ["ANTHROPIC_API_KEY"] = anthropic_key

    channels_file = Path(__file__).parent / "channels.json"
    channels = json.loads(channels_file.read_text())

    # ① 실시간 시장 데이터 수집
    print("실시간 시장 데이터 수집 중...")
    market_data = fetch_market_data()
    crypto_data = fetch_crypto_data()
    market_summary = build_market_summary(market_data, crypto_data)
    print(market_summary)
    print()

    # ② YouTube 채널 데이터 수집
    print("YouTube 채널에서 최신 동영상 수집 중...")
    all_data = collect_all_videos(youtube_key, channels)

    if not all_data:
        sys.exit("수집된 동영상이 없습니다. YouTube API 키와 채널 목록을 확인해주세요.")

    total = sum(len(ch["videos"]) for ch in all_data)
    print(f"\n총 {len(all_data)}개 채널, {total}개 동영상 수집 완료\n")

    # ③ Claude로 트렌드 리포트 생성
    print("=" * 60)
    video_summary = build_video_summary(all_data)
    report = generate_trend_report(video_summary, market_summary, today_str)
    print("\n" + "=" * 60)

    # ④ 저장 및 이메일 발송
    report_path = save_report(report, market_summary, today_str)
    print(f"\n리포트 저장 완료: {report_path}")

    send_email(report, today_str)


if __name__ == "__main__":
    main()
