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
BASE = "https://www.googleapis.com/youtube/v3/"
BLOG_API = "https://blog.naver.com/PostTitleListAsync.naver"

# 관리 블로그 목록 (공식 + 협업/체험단 블로그)
BLOGS = [
    {"id": "aqaralife", "name": "아카라라이프 (공식)"},
    {"id": "sksmsehfehfdl", "name": "수니집 일상기록"},
    {"id": "untorn", "name": "미니멀라이프"},
]


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


BLOG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def _blog_via_api(bid):
    posts, page, total = [], 1, 0
    hdr = dict(BLOG_HEADERS, Referer="https://blog.naver.com/%s" % bid)
    while page <= 60:
        r = requests.get(BLOG_API, timeout=20, headers=hdr,
                         params={"blogId": bid, "viewdate": "", "currentPage": page,
                                 "categoryNo": "", "parentCategoryNo": "", "countPerPage": 30})
        txt = r.text.strip().lstrip("﻿")
        j = json.loads(txt)
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
                          "link": "https://blog.naver.com/%s/%s" % (bid, logno)})
        if total and page * 30 >= total:
            break
        page += 1
    return posts, total


def _blog_via_rss(bid):
    """API 차단 시 폴백: RSS(최근 ~50개)."""
    import xml.etree.ElementTree as ET
    r = requests.get("https://rss.blog.naver.com/%s.xml" % bid, timeout=20, headers=BLOG_HEADERS)
    root = ET.fromstring(r.content)
    ch = root.find("channel")
    posts = []
    mon = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
           "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
    for it in ch.findall("item"):
        t = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        m = re.search(r"(\d{2}) (\w{3}) (\d{4})", it.findtext("pubDate") or "")
        date = "%s-%s-%s" % (m.group(3), mon.get(m.group(2), "01"), m.group(1)) if m else ""
        if t and link:
            posts.append({"title": t, "date": date, "link": link})
    return posts, len(posts)


def _one_blog(bid):
    posts, total = [], 0
    try:
        posts, total = _blog_via_api(bid)
    except Exception as e:
        print("blog API 실패(%s):" % bid, e)
    if not posts:
        try:
            posts, total = _blog_via_rss(bid)
            print("blog RSS 폴백(%s):" % bid, len(posts))
        except Exception as e:
            print("blog RSS 실패(%s):" % bid, e)
    posts.sort(key=lambda x: x["date"], reverse=True)
    return posts, (total or len(posts))


def fetch_blog():
    """관리 블로그 여러 개의 전체 글 수집 → {blogs:[...], total, recent30}. 조회수는 정책상 비공개."""
    cutoff = (datetime.datetime.utcnow() + datetime.timedelta(hours=9) - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    blogs = []
    for b in BLOGS:
        posts, total = _one_blog(b["id"])
        if not posts and total == 0:
            print("blog 건너뜀(글없음):", b["id"])
            continue
        r30 = sum(1 for p in posts if p["date"] >= cutoff)
        blogs.append({"id": b["id"], "name": b["name"], "url": "https://blog.naver.com/%s" % b["id"],
                      "total": total, "recent30": r30, "recent": posts})
    if not blogs:
        return None
    return {"blogs": blogs,
            "total": sum(x["total"] for x in blogs),
            "recent30": sum(x["recent30"] for x in blogs)}


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

    # 직전 owned.json 로드 (instagram 수기·blog 백업 보존용)
    prev = {}
    if os.path.exists(path):
        try:
            prev = json.load(open(path, encoding="utf-8"))
        except Exception:
            prev = {}

    # instagram(수기) 블록 보존
    insta = {"asOf": "수기 입력 대기", "followers": None, "posts": None, "following": None}
    if isinstance(prev.get("instagram"), dict):
        insta = prev["instagram"]

    # blog: 신규 수집 실패/빈값이면 직전 blog 보존(자동 워크플로가 블로그를 지우지 않도록)
    blog = fetch_blog()
    if (not blog or not blog.get("blogs")) and isinstance(prev.get("blog"), dict) and prev["blog"].get("blogs"):
        print("blog 신규 수집 실패/빈값 → 직전 owned.json의 blog 보존")
        blog = prev["blog"]

    data = {
        "generatedAt": kst.strftime("%Y-%m-%d %H:%M"),
        "youtube": {"channel": channel, "recent": recent},
        "instagram": insta,
    }
    if blog:
        data["blog"] = blog
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("owned.json OK — subs:%d views:%d videos:%d recent:%d blog:%d" % (
        channel["subs"], channel["views"], channel["videos"], len(recent),
        len((blog or {}).get("recent", []))))


if __name__ == "__main__":
    main()
