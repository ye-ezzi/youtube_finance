#!/usr/bin/env python3
"""
재테크 YouTube 채널의 최신 동영상을 분석하여 오늘의 트렌드 리포트를 생성합니다.
ANTHROPIC_API_KEY는 필수입니다. YOUTUBE_API_KEY가 없으면 웹 검색 모드로 동작합니다.
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


# ---------------------------------------------------------------------------
# 웹 검색 기반 폴백 (YouTube API 키 없을 때)
# ---------------------------------------------------------------------------

def web_search(query):
    """DuckDuckGo HTML 검색으로 상위 결과 제목+URL 반환"""
    params = urllib.parse.urlencode({"q": query, "kl": "kr-kr"})
    url = f"https://html.duckduckgo.com/html/?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    results = []
    import re
    for m in re.finditer(r'class="result__title"[^>]*>.*?href="([^"]+)"[^>]*>([^<]+)<', html, re.S):
        url_found, title = m.group(1), m.group(2).strip()
        results.append({"title": title, "url": url_found})
        if len(results) >= 5:
            break
    return results


def collect_web_market_data(channels):
    """YouTube API 없이 채널명 기반 웹 검색 + 시장 키워드 수집"""
    today = datetime.now().strftime("%Y년 %m월 %d일")
    queries = [
        f"코스피 코스닥 오늘 시황 {today}",
        f"원달러 환율 금리 오늘 {today}",
        f"재테크 ETF 주식 트렌드 {today}",
    ]
    for ch in channels:
        queries.append(f"{ch['name']} 최신 영상 재테크")

    results_text = []
    for q in queries:
        hits = web_search(q)
        if hits:
            results_text.append(f"[검색: {q}]")
            for h in hits:
                results_text.append(f"  - {h['title']}  ({h['url']})")

    return "\n".join(results_text) if results_text else "웹 검색 결과 없음"


# ---------------------------------------------------------------------------
# Claude 리포트 생성
# ---------------------------------------------------------------------------

def generate_trend_report(video_summary, today_str, mode="youtube"):
    client = anthropic.Anthropic()

    system_prompt = """당신은 한국의 재테크 전문 분석가입니다.
수집된 재테크 관련 데이터를 분석하여 오늘의 투자 트렌드 리포트를 작성합니다.

리포트 작성 원칙:
- 여러 채널/소스에서 공통적으로 다루는 주제를 핵심 트렌드로 파악합니다
- 언급되는 종목, 자산 클래스, 섹터를 정리합니다
- 전반적인 시장 센티먼트(긍정/부정/중립)를 파악합니다
- 재테크 초보자도 이해할 수 있는 명확한 한국어로 작성합니다
- 구체적인 수치와 출처를 인용하여 근거를 제시합니다
- 과도한 투자 권유나 단정적 예측은 하지 않습니다"""

    source_label = "YouTube 채널 동영상" if mode == "youtube" else "웹 검색 결과 (YouTube API 미사용)"

    user_message = f"""오늘 날짜: {today_str}
데이터 수집 방식: {source_label}

수집된 재테크 관련 데이터:

{video_summary}

위 데이터를 바탕으로 오늘의 재테크 트렌드 리포트를 아래 형식으로 작성해주세요:

📊 **오늘의 재테크 트렌드 리포트** ({today_str})

1. 🔥 **핵심 트렌드** (오늘 가장 많이 다뤄진 주제 3~5가지)

2. 💰 **주목받는 종목 / 자산**

3. 📈 **시장 센티먼트** (전반적인 분위기: 강세/약세/혼조)

4. 📺 **채널별 주요 내용** (각 채널이 오늘 집중한 내용)

5. 💡 **오늘의 핵심 인사이트** (오늘 꼭 알아야 할 2~3가지)"""

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


def main():
    print("=" * 60)
    print("  재테크 YouTube 일일 트렌드 리포트")
    print("=" * 60)

    today_str = datetime.now().strftime("%Y년 %m월 %d일")
    print(f"  날짜: {today_str}\n")

    anthropic_key = load_env_key("ANTHROPIC_API_KEY")
    if not anthropic_key:
        sys.exit("ANTHROPIC_API_KEY가 없습니다. .env 파일 또는 환경변수를 설정해주세요.")
    os.environ["ANTHROPIC_API_KEY"] = anthropic_key

    channels_file = Path(__file__).parent / "channels.json"
    channels = json.loads(channels_file.read_text())

    youtube_key = load_env_key("YOUTUBE_API_KEY")

    if youtube_key:
        print("YouTube API 키 확인됨 — 채널 동영상 수집 모드")
        print("YouTube 채널에서 최신 동영상 수집 중...")
        all_data = collect_all_videos(youtube_key, channels)

        if not all_data:
            sys.exit("수집된 동영상이 없습니다. YouTube API 키와 채널 목록을 확인해주세요.")

        total = sum(len(ch["videos"]) for ch in all_data)
        print(f"\n총 {len(all_data)}개 채널, {total}개 동영상 수집 완료\n")

        video_summary = build_video_summary(all_data)
        mode = "youtube"
    else:
        print("YouTube API 키 없음 — 웹 검색 폴백 모드로 전환")
        print("시장 데이터 및 채널 키워드 수집 중...\n")
        video_summary = collect_web_market_data(channels)
        mode = "web"

    print("=" * 60)
    report = generate_trend_report(video_summary, today_str, mode)
    print("\n" + "=" * 60)

    report_path = save_report(report, today_str)
    print(f"\n리포트 저장 완료: {report_path}")

    send_email(report, today_str)


if __name__ == "__main__":
    main()
