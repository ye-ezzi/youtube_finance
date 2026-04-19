#!/usr/bin/env python3
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.parse
import urllib.error

API_BASE = "https://www.googleapis.com/youtube/v3"


def load_api_key():
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        env_file = Path(__file__).parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("YOUTUBE_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        sys.exit("YOUTUBE_API_KEY not found in environment or .env file")
    return key


def api_get(endpoint, params):
    url = f"{API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def fetch_latest_videos(channel_id, api_key, max_results=10):
    data = api_get("search", {
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
    details = api_get("videos", {
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
            "description": snippet["description"][:300],
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "thumbnail": snippet["thumbnails"].get("high", {}).get("url"),
            "view_count": int(stats.get("viewCount", 0)),
            "like_count": int(stats.get("likeCount", 0)),
            "comment_count": int(stats.get("commentCount", 0)),
            "duration": v["contentDetails"]["duration"],
        })
    return videos


def run(target_channel_id=None):
    api_key = load_api_key()
    channels_file = Path(__file__).parent / "channels.json"
    channels = json.loads(channels_file.read_text())

    if target_channel_id:
        channels = [c for c in channels if c["channel_id"] == target_channel_id]
        if not channels:
            sys.exit(f"Channel ID not found: {target_channel_id}")

    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)

    summary = []
    fetched_at = datetime.now(timezone.utc).isoformat()

    for ch in channels:
        name = ch["name"]
        cid = ch["channel_id"]
        print(f"Fetching: {name} ({cid}) ...", end=" ", flush=True)

        try:
            videos = fetch_latest_videos(cid, api_key)
        except urllib.error.HTTPError as e:
            print(f"ERROR {e.code}")
            continue

        result = {
            "channel": ch,
            "fetched_at": fetched_at,
            "videos": videos,
        }
        out_path = data_dir / f"{cid}_latest.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"{len(videos)} videos saved → {out_path.name}")

        if videos:
            summary.append({
                "channel_name": name,
                "channel_id": cid,
                "latest_video": videos[0]["title"],
                "latest_published_at": videos[0]["published_at"],
                "video_count": len(videos),
            })

    summary_path = data_dir / "summary.json"
    summary_path.write_text(json.dumps({
        "fetched_at": fetched_at,
        "channels": summary,
    }, ensure_ascii=False, indent=2))
    print(f"\n✓ Summary saved → {summary_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch latest YouTube videos from subscribed channels")
    parser.add_argument("--channel", help="Fetch only this channel ID")
    args = parser.parse_args()
    run(args.channel)
