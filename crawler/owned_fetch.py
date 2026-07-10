# -*- coding: utf-8 -*-
"""자사 온드미디어(YouTube @aqaralife) 지표 자동 수집 → web/owned.json
   채널 통계(구독자·총조회·영상수) + 최근 업로드 12개(조회·좋아요·댓글).
   Instagram은 정책상 자동수집 불가 → 기존 owned.json의 instagram 블록을 보존(수기 관리).
   GitHub Actions 매일 실행. 키: YT_API_KEY."""
import os, json, re, html, datetime
import xml.etree.ElementTree as ET
import requests

KEY = os.environ.get("YT_API_KEY", "")
HANDLE = "aqaralife"
BASE = "https://www.googleapis.com/youtube/v3/"
BLOG_RSS = "https://rss.blog.naver.com/aqaralife.xml"


def fetch_blog():
    """네이버 블로그 RSS → 최근 글 목록(제목·발행일·링크). 조회수는 비공개라 미포함."""
    try:
        r = requests.get(BLOG_RSS, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
        ch = root.find("channel")
        title = (ch.findtext("title") or "아카라라이프 블로그").strip()
        posts = []
        for it in ch.findall("item"):
            t = html.unescape((it.findtext("title") or "").strip())
            link = (it.findtext("link") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            date = ""
            m = re.search(r"(\d{2}) (\w{3}) (\d{4})", pub)
            if m:
                mon = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
                       "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}.get(m.group(2), "01")
                date = "%s-%s-%s" % (m.group(3), mon, m.group(1))
            if t and link:
                posts.append({"title": t, "date": date, "link": link})
        posts.sort(key=lambda x: x["date"], reverse=True)
        # 최근 30일 발행 수
        cutoff = (datetime.datetime.utcnow() + datetime.timedelta(hours=9) - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        recent30 = sum(1 for p in posts if p["date"] >= cutoff)
        return {"url": "https://blog.naver.com/aqaralife", "title": title,
                "totalRecent": len(posts), "recent30": recent30, "recent": posts[:15]}
    except Exception as e:
        print("blog RSS 실패:", e)
        return None


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

    blog = fetch_blog()
    data = {
        "generatedAt": kst.strftime("%Y-%m-%d %H:%M"),
        "youtube": {"channel": channel, "recent": recent},
        "instagram": insta,
    }
    if blog:
        data["blog"] = blog
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("owned.json OK — subs:%d views:%d videos:%d recent:%d" % (
        channel["subs"], channel["views"], channel["videos"], len(recent)))


if __name__ == "__main__":
    main()
