# -*- coding: utf-8 -*-
"""자사 온드미디어(YouTube @aqaralife) 지표 자동 수집 → web/owned.json
   채널 통계(구독자·총조회·영상수) + 최근 업로드 12개(조회·좋아요·댓글).
   Instagram은 정책상 자동수집 불가 → 기존 owned.json의 instagram 블록을 보존(수기 관리).
   GitHub Actions 매일 실행. 키: YT_API_KEY."""
import os, json, re, html, datetime
from urllib.parse import unquote_plus
import requests

KEY = os.environ.get("YT_API_KEY", "")
HANDLE = "aqaralife"
BLOG_ID = "aqaralife"
BASE = "https://www.googleapis.com/youtube/v3/"
BLOG_API = "https://blog.naver.com/PostTitleListAsync.naver"


def _bdate(s):
    """네이버 블로그 addDate('2026. 6. 26.' 또는 '21시간 전') → YYYY-MM-DD."""
    s = (s or "").strip()
    m = re.match(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.", s)
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    if "일 전" in s:
        d = int(re.search(r"(\d+)\s*일", s).group(1))
        return (kst - datetime.timedelta(days=d)).strftime("%Y-%m-%d")
    if any(k in s for k in ("시간 전", "분 전", "초 전", "방금")):
        return kst.strftime("%Y-%m-%d")
    return ""


def fetch_blog():
    """네이버 블로그 목록 API → 전체 글(제목·발행일·링크). 조회수는 정책상 비공개."""
    try:
        posts, page, total = [], 1, None
        while page <= 60:
            r = requests.get(BLOG_API, timeout=20, headers={"User-Agent": "Mozilla/5.0"},
                             params={"blogId": BLOG_ID, "viewdate": "", "currentPage": page,
                                     "categoryNo": "", "parentCategoryNo": "", "countPerPage": 30})
            j = r.json()
            total = int(j.get("totalCount", 0) or 0)
            lst = j.get("postList", []) or []
            if not lst:
                break
            for it in lst:
                logno = (it.get("logNo") or "").strip()
                if not logno:
                    continue
                title = html.unescape(unquote_plus(it.get("title", "")).replace("+", " ")).strip()
                posts.append({"title": title, "date": _bdate(it.get("addDate", "")),
                              "link": "https://blog.naver.com/%s/%s" % (BLOG_ID, logno)})
            if total and page * 30 >= total:
                break
            page += 1
        posts.sort(key=lambda x: x["date"], reverse=True)
        cutoff = (datetime.datetime.utcnow() + datetime.timedelta(hours=9) - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        recent30 = sum(1 for p in posts if p["date"] >= cutoff)
        return {"url": "https://blog.naver.com/aqaralife", "title": "아카라라이프 블로그",
                "total": total or len(posts), "totalRecent": len(posts), "recent30": recent30, "recent": posts}
    except Exception as e:
        print("blog API 실패:", e)
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
