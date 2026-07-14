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
    {"id": "gogetthat", "name": "하다 일상"},
]

# 유튜브 시리즈(재생목록) — 온드미디어 유튜브 하위 성과 분석용
PLAYLISTS = [
    {"key": "lansun", "name": "랜선집들이", "id": "PLspz0DF4fSvufRMB1s3JrgwRPZJX9ZEO5"},
    {"key": "bible", "name": "바이블 교육", "id": "PLspz0DF4fSvu5FTIQLVqeb4nAw7UKxhpM"},
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


IG_ID = "17841461594818226"          # @aqaralife.official 비즈니스 계정 ID
ITOKEN = os.environ.get("INSTA_TOKEN", "")
GRAPH = "https://graph.facebook.com/v21.0"


def fetch_instagram():
    """Instagram Graph API로 팔로워·게시물·최근 미디어 반응 수집. 토큰(INSTA_TOKEN) 없으면 None."""
    if not ITOKEN:
        return None
    try:
        acc = requests.get("%s/%s" % (GRAPH, IG_ID),
                           params={"fields": "username,followers_count,follows_count,media_count",
                                   "access_token": ITOKEN}, timeout=20).json()
        if "error" in acc:
            print("IG API 오류:", acc["error"].get("message"))
            return None
        med = requests.get("%s/%s/media" % (GRAPH, IG_ID),
                           params={"fields": "id,caption,timestamp,media_type,media_url,thumbnail_url,permalink,like_count,comments_count",
                                   "limit": 12, "access_token": ITOKEN}, timeout=20).json()
        recent = []
        for m in med.get("data", []):
            cap = re.sub(r"\s+", " ", (m.get("caption") or "")).strip()[:70]
            # 이미지: 동영상/릴스는 thumbnail_url, 사진은 media_url
            img = m.get("thumbnail_url") or (m.get("media_url") if m.get("media_type") != "VIDEO" else "")
            recent.append({"date": (m.get("timestamp") or "")[:10], "type": m.get("media_type", ""),
                           "caption": cap, "likes": int(m.get("like_count", 0) or 0),
                           "comments": int(m.get("comments_count", 0) or 0),
                           "image": img or "", "permalink": m.get("permalink", "")})
        kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        return {"asOf": kst.strftime("%Y-%m-%d") + " (자동)", "username": acc.get("username"),
                "followers": acc.get("followers_count"), "following": acc.get("follows_count"),
                "posts": acc.get("media_count"), "recent": recent}
    except Exception as e:
        print("IG 수집 실패:", e)
        return None


def fetch_playlists():
    """지정 재생목록별 성과 집계 → [{key,name,url,count,views,likes,comments,avgViews,videos:[...]}]."""
    out = []
    for p in PLAYLISTS:
        try:
            ids, token = [], ""
            while True:
                kw = {"part": "contentDetails", "maxResults": 50, "playlistId": p["id"]}
                if token:
                    kw["pageToken"] = token
                pl = api("playlistItems", **kw)
                for it in pl.get("items", []):
                    vid = it.get("contentDetails", {}).get("videoId")
                    if vid:
                        ids.append(vid)
                token = pl.get("nextPageToken")
                if not token:
                    break
            vids = []
            for i in range(0, len(ids), 50):
                vs = api("videos", part="snippet,statistics", id=",".join(ids[i:i + 50]))
                for it in vs.get("items", []):
                    st = it.get("statistics", {})
                    vids.append({"id": it["id"], "title": it["snippet"]["title"],
                                 "date": it["snippet"]["publishedAt"][:10],
                                 "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                                 "comments": int(st.get("commentCount", 0))})
            vids.sort(key=lambda x: x["date"], reverse=True)
            tv = sum(v["views"] for v in vids)
            out.append({"key": p["key"], "name": p["name"],
                        "url": "https://www.youtube.com/playlist?list=" + p["id"],
                        "count": len(vids), "views": tv, "likes": sum(v["likes"] for v in vids),
                        "comments": sum(v["comments"] for v in vids),
                        "avgViews": round(tv / len(vids)) if vids else 0, "videos": vids})
        except Exception as e:
            print("playlist 실패(%s):" % p["key"], e)
    return out


def build_content_history(uploads_playlist, blog):
    """발행일 기준 월별 콘텐츠 발행량(블로그·영상·인스타) 소급 집계."""
    hist = {}

    def add(ym, field):
        hist.setdefault(ym, {"blog": 0, "youtube": 0, "instagram": 0})[field] += 1

    # YouTube 전체 영상
    try:
        token = ""
        while True:
            kw = {"part": "contentDetails", "maxResults": 50, "playlistId": uploads_playlist}
            if token:
                kw["pageToken"] = token
            pl = api("playlistItems", **kw)
            for it in pl.get("items", []):
                d = it.get("contentDetails", {}).get("videoPublishedAt", "")
                if d:
                    add(d[:7], "youtube")
            token = pl.get("nextPageToken")
            if not token:
                break
    except Exception as e:
        print("content YT 실패:", e)
    # Instagram 전체 게시물
    if ITOKEN:
        try:
            url = "%s/%s/media" % (GRAPH, IG_ID)
            params = {"fields": "timestamp", "limit": 100, "access_token": ITOKEN}
            while url:
                m = requests.get(url, params=params, timeout=20).json()
                if "error" in m:
                    break
                for x in m.get("data", []):
                    t = x.get("timestamp", "")
                    if t:
                        add(t[:7], "instagram")
                url = m.get("paging", {}).get("next")
                params = None
        except Exception as e:
            print("content IG 실패:", e)
    # 블로그
    if blog:
        for bg in blog.get("blogs", []):
            for p in bg.get("recent", []):
                d = p.get("date", "")
                if len(d) >= 7:
                    add(d[:7], "blog")
    months = sorted(hist.keys())
    return [{"month": ym, "blog": hist[ym]["blog"], "youtube": hist[ym]["youtube"],
             "instagram": hist[ym]["instagram"], "total": sum(hist[ym].values())} for ym in months]


def append_history(path, snapshot):
    """날짜별 스냅샷 누적(같은 날은 갱신, 최근 400일 유지)."""
    hist = []
    if os.path.exists(path):
        try:
            hist = json.load(open(path, encoding="utf-8"))
        except Exception:
            hist = []
    if not isinstance(hist, list):
        hist = []
    hist = [h for h in hist if h.get("date") != snapshot["date"]]
    hist.append(snapshot)
    hist.sort(key=lambda x: x.get("date", ""))
    hist = hist[-400:]
    json.dump(hist, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


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

    # instagram: 토큰 있으면 자동 수집, 없거나 실패면 직전 값(수기 포함) 보존
    insta = fetch_instagram()
    if not insta and isinstance(prev.get("instagram"), dict):
        insta = prev["instagram"]
    if not insta:
        insta = {"asOf": "수기 입력 대기", "followers": None, "posts": None, "following": None}

    # blog: 신규 수집 실패/빈값이면 직전 blog 보존(자동 워크플로가 블로그를 지우지 않도록)
    blog = fetch_blog()
    prev_blog = prev.get("blog") if isinstance(prev.get("blog"), dict) else None
    # Actions에서 API 차단→RSS 폴백으로 글 수가 줄어드는 것 방지: 블로그별로 직전보다 적으면 직전 데이터 유지
    if blog and blog.get("blogs") and prev_blog and prev_blog.get("blogs"):
        prevmap = {b.get("id"): b for b in prev_blog["blogs"]}
        merged = []
        for b in blog["blogs"]:
            pb = prevmap.get(b.get("id"))
            if pb and (pb.get("total", 0) > b.get("total", 0) or len(pb.get("recent", [])) > len(b.get("recent", []))):
                print("blog[%s] 직전(%d) > 신규(%d) → 직전 유지" % (b.get("id"), pb.get("total", 0), b.get("total", 0)))
                merged.append(pb)
            else:
                merged.append(b)
        blog = {"blogs": merged, "total": sum(x.get("total", 0) for x in merged),
                "recent30": sum(x.get("recent30", 0) for x in merged)}
    if (not blog or not blog.get("blogs")) and prev_blog and prev_blog.get("blogs"):
        print("blog 신규 수집 실패/빈값 → 직전 owned.json의 blog 보존")
        blog = prev_blog

    # 재생목록(시리즈) 성과: 실패/빈값이면 직전 owned.json의 playlists 보존
    playlists = fetch_playlists()
    prev_pl = (prev.get("youtube") or {}).get("playlists") if isinstance(prev.get("youtube"), dict) else None
    if (not playlists) and prev_pl:
        print("playlists 신규 수집 실패 → 직전 값 보존")
        playlists = prev_pl

    yt = {"channel": channel, "recent": recent}
    if playlists:
        yt["playlists"] = playlists
    data = {
        "generatedAt": kst.strftime("%Y-%m-%d %H:%M"),
        "youtube": yt,
        "instagram": insta,
    }
    if blog:
        data["blog"] = blog
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 일별 추세 스냅샷 누적
    append_history(os.path.join(os.path.dirname(__file__), "..", "owned_history.json"), {
        "date": kst.strftime("%Y-%m-%d"),
        "ytSubs": channel["subs"], "ytViews": channel["views"], "ytVideos": channel["videos"],
        "igFollowers": insta.get("followers"), "igPosts": insta.get("posts"),
        "blogTotal": (blog or {}).get("total"),
    })

    # 콘텐츠 발행 추이(월별 소급) 재생성
    try:
        ch_months = build_content_history(uploads, blog)
        if ch_months:
            json.dump({"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "months": ch_months},
                      open(os.path.join(os.path.dirname(__file__), "..", "content_history.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print("content_history.json OK — %d개월" % len(ch_months))
    except Exception as e:
        print("content_history 실패:", e)
    print("owned.json OK — subs:%d videos:%d yt_recent:%d blogs:%d ig_followers:%s" % (
        channel["subs"], channel["videos"], len(recent),
        len((blog or {}).get("blogs", [])), str(insta.get("followers"))))


if __name__ == "__main__":
    main()
