#!/usr/bin/env python3
"""
재테크 YouTube 채널의 최신 동영상을 분석하여 오늘의 트렌드 리포트를 생성합니다.
ANTHROPIC_API_KEY와 YOUTUBE_API_KEY 환경변수(또는 .env 파일)가 필요합니다.
"""
import json
import os
import sys
import smtplib
import time
import argparse
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
MAX_RETRIES = 3


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


def youtube_get(endpoint, params, retries=MAX_RETRIES):
    url = f"{YOUTUBE_API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (403, 400):
                raise
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


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


def collect_all_videos(api_key, channels, lookback_hours=LOOKBACK_HOURS):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)

    all_data = []
    for ch in channels:
        print(f"  수집 중: {ch['name']} ...", end=" ", flush=True)
        try:
            videos = fetch_channel_videos(ch["channel_id"], api_key)
        except urllib.error.HTTPError as e:
            print(f"오류 {e.code}")
            continue
        except Exception as e:
            print(f"오류: {e}")
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


SYSTEM_PROMPT = """당신은 한국의 재테크 전문 분석가입니다.
YouTube 재테크 채널들의 최신 동영상 데이터를 분석하여 오늘의 투자 트렌드 리포트를 작성합니다.

리포트 작성 원칙:
- 여러 채널에서 공통적으로 다루는 주제를 핵심 트렌드로 파악합니다
- 언급되는 종목, 자산 클래스, 섹터를 정리합니다
- 전반적인 시장 센티먼트(긍정/부정/중립)를 파악합니다
- 재테크 초보자도 이해할 수 있는 명확한 한국어로 작성합니다
- 구체적인 영상 제목과 채널명을 인용하여 근거를 제시합니다
- 과도한 투자 권유나 단정적 예측은 하지 않습니다
- 각 섹션을 충분히 상세하게 작성하여 독자가 시장 상황을 한눈에 파악할 수 있도록 합니다"""


def generate_trend_report(video_summary, today_str):
    client = anthropic.Anthropic()

    user_message = f"""오늘 날짜: {today_str}

다음은 최근 48시간 내 수집된 재테크 YouTube 채널들의 최신 동영상입니다:

{video_summary}

위 데이터를 바탕으로 오늘의 재테크 트렌드 리포트를 아래 형식으로 작성해주세요:

📊 **오늘의 재테크 트렌드 리포트** ({today_str})

1. 🔥 **핵심 트렌드** (오늘 가장 많이 다뤄진 주제 3~5가지)

2. 💰 **주목받는 종목 / 자산** (주식, 부동산, 코인, ETF 등 언급 자산 정리)

3. 📈 **시장 센티먼트** (전반적인 분위기: 강세/약세/혼조, 그 이유)

4. 📺 **채널별 주요 내용** (각 채널이 오늘 집중한 내용 한 줄 요약)

5. ⚠️ **주요 리스크 / 주의사항** (오늘 언급된 위험 요인)

6. 💡 **오늘의 핵심 인사이트** (오늘 꼭 알아야 할 2~3가지 요약)"""

    report_parts = []
    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
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


def save_raw_data(all_data):
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    date_slug = datetime.now().strftime("%Y%m%d")
    raw_path = data_dir / f"raw_{date_slug}.json"
    raw_path.write_text(json.dumps({
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "channels": all_data,
    }, ensure_ascii=False, indent=2))
    return raw_path


def send_email(report, today_str):
    sender = load_env_key("EMAIL_FROM")
    recipient = load_env_key("EMAIL_TO")
    password = load_env_key("EMAIL_APP_PASSWORD")

    if not all([sender, recipient, password]):
        print("이메일 설정이 없어 발송을 건너뜁니다. (.env에 EMAIL_FROM, EMAIL_TO, EMAIL_APP_PASSWORD 추가)")
        return

    html_lines = []
    for line in report.splitlines():
        clean = line.replace("**", "")
        if line.startswith("#"):
            html_lines.append(f"<h3>{clean}</h3>")
        elif line.startswith("-"):
            html_lines.append(f"<li>{clean[1:].strip()}</li>")
        elif line.strip():
            html_lines.append(f"<p>{clean}</p>")
    html_body = "\n".join(html_lines)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 재테크 트렌드 리포트 — {today_str}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(report, "plain", "utf-8"))
    msg.attach(MIMEText(f"<html><body style='font-family:sans-serif;max-width:800px;margin:auto'>{html_body}</body></html>", "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        print(f"이메일 발송 완료 → {recipient}")
    except Exception as e:
        print(f"이메일 발송 실패: {e}")


def main():
    parser = argparse.ArgumentParser(description="재테크 YouTube 일일 트렌드 리포트 생성")
    parser.add_argument("--no-email", action="store_true", help="이메일 발송 건너뜀")
    parser.add_argument("--lookback", type=int, default=LOOKBACK_HOURS, help=f"수집 기간 (시간, 기본값: {LOOKBACK_HOURS})")
    parser.add_argument("--channels", help="특정 채널만 분석 (채널명, 쉼표로 구분)")
    args = parser.parse_args()

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

    if args.channels:
        names = {n.strip() for n in args.channels.split(",")}
        channels = [c for c in channels if c["name"] in names]
        if not channels:
            sys.exit(f"지정한 채널을 찾을 수 없습니다: {args.channels}")

    print(f"YouTube 채널에서 최신 동영상 수집 중... (최근 {args.lookback}시간)")
    all_data = collect_all_videos(youtube_key, channels, lookback_hours=args.lookback)

    if not all_data:
        sys.exit("수집된 동영상이 없습니다. YouTube API 키와 채널 목록을 확인해주세요.")

    total = sum(len(ch["videos"]) for ch in all_data)
    print(f"\n총 {len(all_data)}개 채널, {total}개 동영상 수집 완료")

    raw_path = save_raw_data(all_data)
    print(f"원본 데이터 저장: {raw_path}\n")

    print("=" * 60)
    video_summary = build_video_summary(all_data)
    report = generate_trend_report(video_summary, today_str)
    print("\n" + "=" * 60)

    report_path = save_report(report, today_str)
    print(f"\n리포트 저장 완료: {report_path}")

    if not args.no_email:
        send_email(report, today_str)


if __name__ == "__main__":
    main()
