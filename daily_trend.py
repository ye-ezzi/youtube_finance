#!/usr/bin/env python3
"""
재테크 관련 정보를 수집하여 매일 오늘의 트렌드 리포트를 생성합니다.
  - YouTube 재테크 채널 영상 분석
  - 주요 시장 지수 (KOSPI, KOSDAQ, S&P500, NASDAQ, USD/KRW, 금, WTI)
  - 국내 금융 뉴스 헤드라인 (한국경제, 이데일리, 머니투데이)

ANTHROPIC_API_KEY와 YOUTUBE_API_KEY 환경변수(또는 .env 파일)가 필요합니다.
"""
import json
import os
import sys
import smtplib
import xml.etree.ElementTree as ET
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

MARKET_SYMBOLS = {
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
    "S&P500": "^GSPC",
    "NASDAQ": "^IXIC",
    "USD/KRW": "KRW=X",
    "금(Gold)": "GC=F",
    "WTI유가": "CL=F",
}

NEWS_RSS_FEEDS = [
    {"name": "한국경제", "url": "https://www.hankyung.com/rss/finance"},
    {"name": "이데일리", "url": "https://rss.edaily.co.kr/edaily/section/economy.xml"},
    {"name": "머니투데이", "url": "https://rss.mt.co.kr/rss/money.xml"},
]


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


# ── YouTube ────────────────────────────────────────────────────────────────────

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


# ── 시장 지수 ─────────────────────────────────────────────────────────────────

def fetch_market_data():
    """Yahoo Finance에서 주요 시장 지수를 가져옵니다 (인증 불필요)."""
    results = {}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; finance-trend-bot/1.0)"}

    for name, symbol in MARKET_SYMBOLS.items():
        encoded = urllib.parse.quote(symbol)
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
            f"?interval=1d&range=2d"
        )
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice", 0)
            prev = meta.get("previousClose", meta.get("chartPreviousClose", price))
            change = price - prev
            pct = (change / prev * 100) if prev else 0
            currency = meta.get("currency", "")
            results[name] = {
                "price": price,
                "prev_close": prev,
                "change": change,
                "change_pct": pct,
                "currency": currency,
            }
        except Exception as e:
            results[name] = {"error": str(e)}

    return results


def format_market_summary(market_data):
    lines = []
    for name, d in market_data.items():
        if "error" in d:
            lines.append(f"- {name}: 데이터 조회 실패 ({d['error'][:60]})")
            continue
        sign = "+" if d["change"] >= 0 else ""
        arrow = "▲" if d["change"] >= 0 else "▼"
        price = d["price"]
        pct = d["change_pct"]
        if name == "USD/KRW":
            lines.append(f"- {name}: {price:,.2f}원  {arrow} {sign}{pct:.2f}%")
        elif name in ("금(Gold)", "WTI유가"):
            lines.append(f"- {name}: ${price:,.2f}  {arrow} {sign}{pct:.2f}%")
        else:
            lines.append(f"- {name}: {price:,.2f}  {arrow} {sign}{pct:.2f}%")
    return "\n".join(lines)


# ── 금융 뉴스 RSS ─────────────────────────────────────────────────────────────

def fetch_rss_headlines(feed_url, max_items=8):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; finance-trend-bot/1.0)"}
    req = urllib.request.Request(feed_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
    except Exception:
        return []

    headlines = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # RSS 2.0
    for item in root.findall(".//item")[:max_items]:
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        if title_el is not None and title_el.text:
            headlines.append({
                "title": title_el.text.strip(),
                "link": link_el.text.strip() if link_el is not None and link_el.text else "",
                "pub": pub_el.text.strip() if pub_el is not None and pub_el.text else "",
            })

    # Atom 형식 대응
    if not headlines:
        for entry in root.findall("atom:entry", ns)[:max_items]:
            title_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            if title_el is not None and title_el.text:
                headlines.append({
                    "title": title_el.text.strip(),
                    "link": link_el.get("href", "") if link_el is not None else "",
                    "pub": "",
                })

    return headlines


def collect_news_headlines():
    all_news = []
    for feed in NEWS_RSS_FEEDS:
        print(f"  뉴스 수집: {feed['name']} ...", end=" ", flush=True)
        items = fetch_rss_headlines(feed["url"])
        if items:
            all_news.append({"source": feed["name"], "items": items})
            print(f"{len(items)}건")
        else:
            print("실패 또는 없음")
    return all_news


def format_news_summary(all_news):
    lines = []
    for src in all_news:
        lines.append(f"\n### {src['source']}")
        for it in src["items"]:
            lines.append(f"- {it['title']}")
            if it["link"]:
                lines.append(f"  {it['link']}")
    return "\n".join(lines)


# ── Claude 분석 리포트 ────────────────────────────────────────────────────────

def generate_trend_report(video_summary, market_summary, news_summary, today_str):
    client = anthropic.Anthropic()

    system_prompt = """당신은 한국의 재테크 전문 분석가입니다.
YouTube 재테크 채널 영상, 주요 시장 지수 데이터, 국내 금융 뉴스를 종합 분석하여
오늘의 투자 트렌드 리포트를 작성합니다.

리포트 작성 원칙:
- 시장 지수 데이터와 뉴스, YouTube 채널을 교차 분석하여 핵심 트렌드를 파악합니다
- 언급되는 종목, 자산 클래스, 섹터를 정리합니다
- 전반적인 시장 센티먼트(강세/약세/혼조)를 수치 근거와 함께 서술합니다
- 재테크 초보자도 이해할 수 있는 명확한 한국어로 작성합니다
- 구체적인 수치, 영상 제목, 채널명, 뉴스 출처를 인용하여 근거를 제시합니다
- 과도한 투자 권유나 단정적 예측은 하지 않습니다"""

    user_message = f"""오늘 날짜: {today_str}

━━━━━━━━━━━ 📊 시장 지수 ━━━━━━━━━━━
{market_summary}

━━━━━━━━━━━ 📰 오늘의 금융 뉴스 ━━━━━━━━━━━
{news_summary if news_summary else "뉴스 데이터를 가져오지 못했습니다."}

━━━━━━━━━━━ 📺 YouTube 재테크 채널 ━━━━━━━━━━━
{video_summary if video_summary else "YouTube 데이터를 가져오지 못했습니다."}

위 데이터를 바탕으로 오늘의 재테크 트렌드 리포트를 아래 형식으로 작성해주세요:

📊 **오늘의 재테크 트렌드 리포트** ({today_str})

1. 📈 **시장 요약** (KOSPI·KOSDAQ·해외 지수 흐름, 환율·원자재 동향)

2. 🔥 **오늘의 핵심 테마** (뉴스 + YouTube에서 공통으로 부각된 주제 3~5가지)

3. 💰 **주목받는 종목 / 자산 / 섹터**

4. 📰 **뉴스 하이라이트** (오늘 주목할 주요 기사 3~5건 요약)

5. 📺 **채널별 주요 내용** (각 YouTube 채널이 집중한 내용)

6. 💡 **오늘의 핵심 인사이트** (꼭 알아야 할 2~3가지 takeaway)

7. ⚠️ **리스크 요인** (현재 주의해야 할 변수나 불확실성)"""

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


# ── 저장 / 이메일 ─────────────────────────────────────────────────────────────

def save_report(report, today_str):
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    date_slug = datetime.now().strftime("%Y%m%d")
    report_path = reports_dir / f"trend_{date_slug}.md"
    report_path.write_text(f"# 재테크 트렌드 리포트 — {today_str}\n\n{report}\n", encoding="utf-8")
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


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  재테크 일일 트렌드 리포트")
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

    # 1. 시장 지수 수집
    print("시장 지수 데이터 수집 중...")
    market_data = fetch_market_data()
    market_summary = format_market_summary(market_data)
    print(market_summary)
    print()

    # 2. 금융 뉴스 수집
    print("금융 뉴스 헤드라인 수집 중...")
    all_news = collect_news_headlines()
    news_summary = format_news_summary(all_news)
    print()

    # 3. YouTube 채널 수집
    print("YouTube 채널에서 최신 동영상 수집 중...")
    all_data = collect_all_videos(youtube_key, channels)
    video_summary = build_video_summary(all_data) if all_data else ""

    total = sum(len(ch["videos"]) for ch in all_data) if all_data else 0
    print(f"\n총 {len(all_data)}개 채널, {total}개 동영상 수집 완료\n")

    # 4. Claude 분석 리포트 생성
    print("=" * 60)
    print("Claude AI 분석 리포트 생성 중...\n")
    report = generate_trend_report(video_summary, market_summary, news_summary, today_str)
    print("\n" + "=" * 60)

    # 5. 저장 및 이메일 발송
    report_path = save_report(report, today_str)
    print(f"\n리포트 저장 완료: {report_path}")

    send_email(report, today_str)


if __name__ == "__main__":
    main()
