# -*- coding: utf-8 -*-
"""자사 온드미디어(YouTube @aqaralife) 지표 자동 수집 → web/owned.json
   채널 통계(구독자·총조회·영상수) + 최근 업로드 12개(조회·좋아요·댓글).
   Instagram은 정책상 자동수집 불가 → 기존 owned.json의 instagram 블록을 보존(수기 관리).
   GitHub Actions 매일 실행. 키: YT_API_KEY."""
import os, json, datetime
import requests

KEY = os.environ.get("YT_API_KEY", "")
HANDLE = "aqaralife"
BASE = "https://www.googleapis.com/youtube/v3/"


def api(path, **params):
    params["key"] = KEY
    r = requests.get(BASE + path, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def main():
    if not KEY:
        raise SystemExit("ERROR: YT_API_KEY 미설정")

    ch = api("channels", part="snippet,statistics,contentDetails", forHandle=HANDLE)["items"][0]
    stats = ch["statistics"]
    channel = {
        "title": ch["snippet"]["title"],
        "subs": int(stats.get("subscriberCount", 0)),
        "views": int(stats.get("viewCount", 0)),
        "videos": int(stats.get("videoCount", 0)),
    }
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]

    # 최근 업로드 12개 videoId 수집
    pl = api("playlistItems", part="contentDetails", maxResults=12, playlistId=uploads)
    ids = [it["contentDetails"]["videoId"] for it in pl.get("items", [])]
    recent = []
    if ids:
        vs = api("videos", part="snippet,statistics", id=",".join(ids))
        for it in vs.get("items", []):
            st = it.get("statistics", {})
            recent.append({
                "id": it["id"],
                "title": it["snippet"]["title"],
                "date": it["snippet"]["publishedAt"][:10],
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
            })
        # 게시일 최신순 정렬
        recent.sort(key=lambda x: x["date"], reverse=True)

    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    path = os.path.join(os.path.dirname(__file__), "..", "owned.json")

    # 기존 instagram(수기) 블록 보존
    insta = {"asOf": "수기 입력 대기", "followers": None, "posts": None, "following": None}
    if os.path.exists(path):
        try:
            prev = json.load(open(path, encoding="utf-8"))
            if isinstance(prev.get("instagram"), dict):
                insta = prev["instagram"]
        except Exception:
            pass

    data = {
        "generatedAt": kst.strftime("%Y-%m-%d %H:%M"),
        "youtube": {"channel": channel, "recent": recent},
        "instagram": insta,
    }
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("owned.json OK — subs:%d views:%d videos:%d recent:%d" % (
        channel["subs"], channel["views"], channel["videos"], len(recent)))


if __name__ == "__main__":
    main()
