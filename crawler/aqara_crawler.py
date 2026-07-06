# -*- coding: utf-8 -*-
"""
아카라라이프 뉴스 수집기 (GitHub Actions 매시간 실행)
- 네이버: 공식 검색 API (안정적)  → 원문 + 네이버뉴스(n.news.naver.com) 링크
- 다음:   news 검색 크롤링         → v.daum.net 링크 → (다음뉴스) 태깅
- 네이트: news 검색 크롤링         → news.nate.com 링크 → (네이트뉴스) 태깅
수집 결과를 Apps Script 웹앱(doPost)으로 POST → 구글 시트에 중복제거 후 누적.

필요한 환경변수(GitHub Secrets):
  WEBAPP_URL     Apps Script 웹앱 /exec URL
  WEBAPP_TOKEN   웹앱 TOKEN (config의 Token과 동일)
  NAVER_ID       네이버 개발자 앱 Client ID
  NAVER_SECRET   네이버 개발자 앱 Client Secret
선택:
  KEYWORDS       쉼표구분 키워드 (기본: 아카라라이프,aqara,아카라)
  DAYS           최근 N일 이내만 수집 (기본: 7)
"""
import os, re, sys, json, html, datetime as dt
from email.utils import parsedate_to_datetime
import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

KEYWORDS = [k.strip() for k in os.environ.get("KEYWORDS", "아카라라이프,aqara,아카라").split(",") if k.strip()]
NOISE = ["아카라카"]
DAYS = int(os.environ.get("DAYS", "7"))
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")
WEBAPP_TOKEN = os.environ.get("WEBAPP_TOKEN", "")
NAVER_ID = os.environ.get("NAVER_ID", "")
NAVER_SECRET = os.environ.get("NAVER_SECRET", "")

# 도메인 → 언론사명 (알려진 매체 우선, 없으면 호스트명 폴백)
DOMAIN_PRESS = {
    "heraldcorp.com": "헤럴드경제", "biz.heraldcorp.com": "헤럴드경제",
    "mt.co.kr": "머니투데이", "moneys.co.kr": "머니S",
    "dailysecu.com": "데일리시큐", "beyondpost.co.kr": "비욘드포스트",
    "bizwnews.com": "비즈월드", "dt.co.kr": "디지털타임스",
    "sedaily.com": "서울경제", "hankyung.com": "한국경제",
    "mydaily.co.kr": "마이데일리", "etnews.com": "전자신문",
    "seoul.co.kr": "서울신문", "asiatime.co.kr": "아시아타임즈",
    "itbiz.co.kr": "아이티비즈", "zdnet.co.kr": "지디넷코리아",
    "venturesquare.net": "벤처스퀘어", "thepowernews.co.kr": "더파워",
    "digitaltoday.co.kr": "디지털투데이", "getnews.co.kr": "글로벌경제",
    "enewstoday.co.kr": "이넷뉴스", "newsroad.co.kr": "뉴스로드",
    "m2news.com": "엠투데이", "single-list.com": "싱글리스트",
}
# 네이버뉴스 oid → 언론사명 (원문 도메인 미상 시 보조)
OID_PRESS = {
    "008": "머니투데이", "009": "매일경제", "011": "서울경제", "014": "파이낸셜뉴스",
    "015": "한국경제", "016": "헤럴드경제", "018": "이데일리", "020": "동아일보",
    "023": "조선일보", "025": "중앙일보", "029": "디지털타임스", "030": "전자신문",
    "032": "경향신문", "092": "지디넷코리아", "421": "뉴스1", "001": "연합뉴스",
    "003": "뉴시스", "277": "아시아경제", "469": "한국일보", "011": "서울경제",
}

def clean_title(t):
    if not t:
        return ""
    t = re.sub(r"<[^>]+>", "", t)          # 태그 제거(<b> 등)
    t = html.unescape(t).strip()
    t = re.sub(r"\s*>\s*뉴스.*$", "", t)
    return t.strip()

def host_of(url):
    m = re.match(r"https?://([^/]+)/?", url or "")
    return (m.group(1).lower().replace("www.", "") if m else "")

def press_from_url(url):
    h = host_of(url)
    if h in DOMAIN_PRESS:
        return DOMAIN_PRESS[h]
    # naver 링크면 oid로 추정
    m = re.search(r"n\.news\.naver\.com/(?:mnews/)?article/(\d+)/", url or "")
    if m and m.group(1) in OID_PRESS:
        return OID_PRESS[m.group(1)]
    return h or "(미상)"

def is_relevant(title):
    if not title:
        return False
    low = title.lower()
    if "aqara" not in low and "아카라" not in title:
        return False
    for n in NOISE:
        if n in title:
            return False
    return True

def within_window(d):
    if not d:
        return True   # 날짜 모르면 포함(서버 중복제거가 걸러줌)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=DAYS)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d >= cutoff

def channel_tag(url):
    """URL 도메인으로 포털 채널 판별."""
    h = host_of(url)
    if h.startswith("n.news.naver.com"):
        return "네이버뉴스"
    if h.startswith("news.nate.com"):
        return "네이트뉴스"
    if h.startswith("v.daum.net"):
        return "다음뉴스"
    return ""   # 원문

def mk_row(press, channel, title, link, date_str):
    media = press + ("(%s)" % channel if channel else "")
    return {
        "date": date_str, "media": media, "channel": channel or "원문",
        "title": title, "link": link,
        "category": "", "type": "", "angle": "", "reporter": "", "distributedBy": "",
        "collectedAt": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "review": "자동수집/검수요망",
    }

# ---------------- 네이버 공식 검색 API ----------------
def collect_naver():
    rows = []
    if not (NAVER_ID and NAVER_SECRET):
        print("[naver] NAVER_ID/SECRET 미설정 → 건너뜀")
        return rows
    headers = {"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET}
    for kw in KEYWORDS:
        try:
            r = requests.get("https://openapi.naver.com/v1/search/news.json",
                             params={"query": kw, "display": 100, "sort": "date"},
                             headers=headers, timeout=20)
            if r.status_code != 200:
                print("[naver] %s status=%s %s" % (kw, r.status_code, r.text[:120]))
                continue
            items = r.json().get("items", [])
        except Exception as e:
            print("[naver] %s 오류: %s" % (kw, e)); continue
        for it in items:
            title = clean_title(it.get("title"))
            if not is_relevant(title):
                continue
            try:
                d = parsedate_to_datetime(it.get("pubDate")) if it.get("pubDate") else None
            except Exception:
                d = None
            if not within_window(d):
                continue
            date_str = d.strftime("%Y-%m-%d") if d else ""
            orig = it.get("originallink") or ""
            nav = it.get("link") or ""
            press = press_from_url(orig or nav)
            # 원문 행 (원문 도메인이 있고 naver가 아닌 경우)
            if orig and not host_of(orig).startswith("n.news.naver.com"):
                rows.append(mk_row(press, "", title, orig, date_str))
            # 네이버뉴스 행 (n.news.naver.com 링크가 있으면)
            if nav and host_of(nav).startswith("n.news.naver.com"):
                rows.append(mk_row(press, "네이버뉴스", title, nav, date_str))
    print("[naver] 수집 %d행" % len(rows))
    return rows

# ---------------- 다음 뉴스 검색 크롤링 ----------------
def collect_daum():
    rows = []
    for kw in KEYWORDS:
        try:
            r = requests.get("https://search.daum.net/search",
                             params={"w": "news", "q": kw, "sort": "recency"},
                             headers={"User-Agent": UA}, timeout=20)
            soup = BeautifulSoup(r.text, "lxml")
        except Exception as e:
            print("[daum] %s 오류: %s" % (kw, e)); continue
        anchors = soup.select("a[href*='v.daum.net']")
        seen = set()
        for a in anchors:
            href = a.get("href", "")
            title = clean_title(a.get_text())
            if not href or not title or len(title) < 8:
                continue
            if href in seen:
                continue
            seen.add(href)
            if not is_relevant(title):
                continue
            # 언론사명 추정: 결과 카드 내 press 표기 탐색
            press = ""
            card = a.find_parent(["li", "div"])
            if card:
                pe = card.select_one(".txt_info, .cont_info, .item-title, .tit_g, .press")
                if pe:
                    press = clean_title(pe.get_text())[:20]
            press = press or "다음뉴스"
            rows.append(mk_row(press, "다음뉴스", title, href, ""))
    print("[daum] 수집 %d행" % len(rows))
    return rows

# ---------------- 네이트 뉴스 검색 크롤링 ----------------
def collect_nate():
    rows = []
    for kw in KEYWORDS:
        try:
            r = requests.get("https://news.nate.com/search",
                             params={"q": kw, "sort": "d"},
                             headers={"User-Agent": UA}, timeout=20)
            r.encoding = r.apparent_encoding
            soup = BeautifulSoup(r.text, "lxml")
        except Exception as e:
            print("[nate] %s 오류: %s" % (kw, e)); continue
        anchors = soup.select("a[href*='news.nate.com/view']")
        seen = set()
        for a in anchors:
            href = a.get("href", "")
            if href.startswith("//"):
                href = "https:" + href
            title = clean_title(a.get_text())
            if not href or not title or len(title) < 8:
                continue
            if href in seen:
                continue
            seen.add(href)
            if not is_relevant(title):
                continue
            press = ""
            card = a.find_parent(["li", "div"])
            if card:
                pe = card.select_one(".medium, .press, .txt_press, .info")
                if pe:
                    press = clean_title(pe.get_text())[:20]
            press = press or "네이트뉴스"
            rows.append(mk_row(press, "네이트뉴스", title, href, ""))
    print("[nate] 수집 %d행" % len(rows))
    return rows

def dedupe(rows):
    out, seen = [], set()
    for r in rows:
        key = re.sub(r"[^0-9a-z가-힣]", "", (r["title"] + "|" + r["media"]).lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out

def post_rows(rows):
    if not rows:
        print("전송할 신규 후보 없음"); return
    if not WEBAPP_URL or not WEBAPP_TOKEN:
        print("WEBAPP_URL/TOKEN 미설정 → 전송 생략"); return
    payload = {"token": WEBAPP_TOKEN, "rows": rows}
    try:
        resp = requests.post(WEBAPP_URL, json=payload, timeout=60)
        try:
            j = resp.json()
        except Exception:
            j = {"raw": resp.text[:200]}
        print("전송 결과:", j)
    except Exception as e:
        print("전송 실패:", e); sys.exit(1)

def main():
    all_rows = []
    all_rows += collect_naver()
    all_rows += collect_daum()
    all_rows += collect_nate()
    all_rows = dedupe(all_rows)
    print("총 수집 후보(중복제거): %d행 → 웹앱 전송(서버에서 최종 중복제거)" % len(all_rows))
    post_rows(all_rows)

if __name__ == "__main__":
    main()
