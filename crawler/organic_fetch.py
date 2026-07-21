# -*- coding: utf-8 -*-
"""네이버 뉴스에서 아카라 관련 기사(2021~) 수집 → web/organic_news.json
   대시보드가 구글시트 기사와 제목 기준 중복제거 후, 추가분을 '오가닉'으로 병합한다.
   ※ 네이버 뉴스 API는 쿼리당 최신 1000건까지만 반환(과거는 일부만).
   GitHub Actions 주기 실행. 키: NAVER_ID/NAVER_SECRET."""
import os, re, json, html, time, datetime
import requests

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
H = {"X-Naver-Client-Id": NID, "X-Naver-Client-Secret": NSEC}
DOMAIN = {"mt.co.kr": "머니투데이", "heraldcorp.com": "헤럴드경제", "sedaily.com": "서울경제", "hankyung.com": "한국경제",
          "etnews.com": "전자신문", "mk.co.kr": "매일경제", "dt.co.kr": "디지털타임스", "yna.co.kr": "연합뉴스",
          "asiae.co.kr": "아시아경제", "zdnet.co.kr": "지디넷코리아", "inews24.com": "아이뉴스24", "newsis.com": "뉴시스",
          "edaily.co.kr": "이데일리", "fnnews.com": "파이낸셜뉴스", "chosun.com": "조선일보", "donga.com": "동아일보",
          "joongang.co.kr": "중앙일보", "khan.co.kr": "경향신문", "seoul.co.kr": "서울신문", "kmib.co.kr": "국민일보",
          "segye.com": "세계일보", "munhwa.com": "문화일보", "hankookilbo.com": "한국일보", "newspim.com": "뉴스핌",
          "ajunews.com": "아주경제", "biz.chosun.com": "조선비즈", "kukinews.com": "쿠키뉴스",
          "digitaltoday.co.kr": "디지털투데이", "itdaily.kr": "아이티데일리", "aitimes.com": "AI타임스",
          "businesskorea.co.kr": "비지니스코리아", "beyondpost.co.kr": "비욘드포스트",
          "insightkorea.co.kr": "인사이트코리아"}
QUERIES = ["아카라라이프", "아카라 스마트홈", "아카라 도어락", "아카라코리아", "아카라 매터"]


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def press_of(url):
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    h = m.group(1) if m else ""
    for d, name in DOMAIN.items():
        if h.endswith(d):
            return name
    return h


def main():
    if not NID or not NSEC:
        raise SystemExit("ERROR: NAVER_ID/NAVER_SECRET 미설정")
    seen, items = set(), []
    for q in QUERIES:
        for start in range(1, 1001, 100):
            try:
                r = requests.get("https://openapi.naver.com/v1/search/news.json",
                                 params={"query": q, "display": 100, "sort": "date", "start": start},
                                 headers=H, timeout=15).json()
            except Exception:
                break
            arr = r.get("items") or []
            if not arr:
                break
            for it in arr:
                t = clean(it.get("title"))
                blob = t + " " + clean(it.get("description"))
                if not re.search(r"아카라|aqara", blob, re.I):
                    continue
                dt = ""
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(it.get("pubDate")).strftime("%Y-%m-%d")
                except Exception:
                    pass
                if not dt or dt < "2021-01-01" or dt > "2026-12-31":
                    continue
                k = re.sub(r"[^0-9A-Za-z가-힣]", "", t)
                if not k or k in seen:
                    continue
                seen.add(k)
                link = it.get("originallink") or it.get("link")
                items.append({"기사명": t, "매체": press_of(link), "게재일": dt, "link": link})
            time.sleep(0.2)
        print("  '%s' 누적 %d건" % (q, len(items)))
    items.sort(key=lambda x: x["게재일"], reverse=True)
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    data = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "count": len(items),
            "note": "네이버 뉴스 2021~2026 아카라 관련 수집(제목 중복제거). 대시보드가 시트 기사와 재중복제거 후 추가분을 오가닉으로 병합.",
            "items": items}
    path = os.path.join(os.path.dirname(__file__), "..", "organic_news.json")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("organic_news.json OK — %d건" % len(items))


if __name__ == "__main__":
    main()
