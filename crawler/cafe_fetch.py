# -*- coding: utf-8 -*-
"""네이버 카페 아카라 모니터링 → web/cafe.json
   ① 아카라 스마트홈(cafe.naver.com/aqara): 자사 공식 카페 전체
   ② 모두의 스마트홈(cafe.naver.com/stsmarthome): '아카라/AQARA' 언급 글만
   GitHub Actions 매시간 실행 → 커밋 → Vercel 자동 반영."""
import os, re, json, html, datetime
import requests

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
H = {"X-Naver-Client-Id": NID, "X-Naver-Client-Secret": NSEC}
REQ = re.compile(r"아카라|aqara", re.I)

AQARA_KWS = ("아카라,아카라라이프,아카라 도어락,아카라 허브,아카라 카메라,아카라 센서,아카라 재실센서,아카라 스위치,"
             "아카라 조명,아카라 커튼,아카라 전동커튼,아카라 앱,아카라 홈킷,아카라 구글홈,아카라 스마트싱스,아카라 매터,"
             "아카라 온습도,아카라 콘센트,아카라 모션센서,아카라 초인종,아카라 도어벨,아카라 후기,아카라 설치,아카라 연동,"
             "아카라 오류,아카라 스마트홈,아카라 스마트전구,아카라 스마트플러그,아카라 무선스위치,아카라 자동화,아카라 알리,"
             "아카라 직구,아카라 펌웨어,아카라 g2h,아카라 fp2,아카라 fp1,아카라 e1,아카라 g3,아카라 g4,아카라 t1,아카라 h2,"
             "아카라 w100,아카라 b1,M100,M200,M3,M2,M1S,FP300,FP310,FP2,FP1,L100,K100,P100,U200,U100,N100,G100,G400,G4,G5,"
             "G2H,W100,T1S,RF447,매직패드,스마트싱스 아카라,홈킷 아카라,매터 아카라,알리 아카라,잇섭 아카라").split(",")
STS_KWS = ("아카라,aqara,aqaralife,aqara 스마트홈,아카라 도어락,아카라 허브,아카라 재실센서,아카라 커튼,아카라 도어벨,"
           "아카라 카메라,아카라 스위치,아카라 조명,아카라 fp2,아카라 fp300,아카라 m3,아카라 w100,아카라 온습도").split(",")

CAFES = [
    {"url": "aqara", "name": "아카라 스마트홈", "require": False, "pages": (1, 101, 201, 301, 401, 501, 601, 701), "kws": AQARA_KWS, "cap": 3000},
    {"url": "stsmarthome", "name": "모두의 스마트홈", "require": True, "pages": (1, 101, 201, 301), "kws": STS_KWS, "cap": 800},
    {"url": "overseer", "name": "셀프인테리어 마이홈", "require": True, "pages": (1, 101, 201, 301), "kws": STS_KWS, "cap": 500},
    {"url": "appleiphone", "name": "아사모(애플)", "require": True, "pages": (1, 101, 201), "kws": STS_KWS, "cap": 400},
    {"url": "pcarpenter", "name": "박목수의 열린견적서", "require": True, "pages": (1, 101), "kws": STS_KWS, "cap": 200},
]


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


CLIEN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CLIEN_QUERIES = ["아카라", "aqara", "아카라 도어락", "아카라 허브"]


def fetch_clien():
    """클리앙(네이버 아님) 검색 파싱 → 아카라 언급글. 실패 시 빈 리스트."""
    seen, posts = set(), []
    for q in CLIEN_QUERIES:
        for p in range(0, 5):
            try:
                r = requests.get("https://www.clien.net/service/search",
                                 params={"q": q, "sort": "recency", "p": p},
                                 headers={"User-Agent": CLIEN_UA, "Accept-Language": "ko-KR,ko;q=0.9"}, timeout=20)
                txt = r.text
            except Exception:
                break
            items = re.findall(r'(?s)<a([^>]*data-role="list-title-text"[^>]*)>(.*?)</a>', txt)
            if not items:
                break
            hit = 0
            for attrs, inner in items:
                title = html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
                m = re.search(r'href="(/service/board/[^"?]+)', attrs)
                if not m:
                    continue
                href = m.group(1)
                link = "https://www.clien.net" + href
                if link in seen or not REQ.search(title):
                    continue
                hit += 1
                seen.add(link)
                mid = re.search(r"/(\d+)$", href)
                mb = re.search(r"/service/board/([^/]+)/", href)
                posts.append({"no": int(mid.group(1)) if mid else 0, "title": title,
                              "desc": "클리앙 · " + (mb.group(1) if mb else ""), "link": link, "cafe": "클리앙"})
            if hit == 0 and p > 0:
                break
    posts.sort(key=lambda x: x["no"], reverse=True)
    return posts


def main():
    out = []
    for cafe in CAFES:
        seen, posts = {}, []
        for q in cafe["kws"]:
            for start in cafe["pages"]:
                try:
                    r = requests.get("https://openapi.naver.com/v1/search/cafearticle.json",
                                     params={"display": 100, "start": start, "sort": "date", "query": q}, headers=H, timeout=15)
                    items = r.json().get("items", [])
                except Exception:
                    break
                if not items:
                    break
                hit = 0
                for it in items:
                    if cafe["url"] not in (it.get("cafeurl") or ""):
                        continue
                    hit += 1
                    link = it.get("link", "")
                    if not link or link in seen:
                        continue
                    title, desc = clean(it.get("title")), clean(it.get("description"))
                    if cafe["require"] and not REQ.search(title + " " + desc):
                        continue
                    seen[link] = True
                    m = re.search(r"/(\d+)(?:[?#]|$)", link)
                    posts.append({"no": int(m.group(1)) if m else 0, "title": title,
                                  "desc": desc, "link": link, "cafe": cafe["name"]})
                if hit == 0 and start > 1:
                    break
        posts.sort(key=lambda x: x["no"], reverse=True)
        out += posts[:cafe["cap"]]

    path = os.path.join(os.path.dirname(__file__), "..", "cafe.json")
    # 클리앙(네이버 아님) — 실패/차단 시 직전 cafe.json의 클리앙 글 보존
    clien = []
    try:
        clien = fetch_clien()
    except Exception as e:
        print("clien 실패:", e)
    if not clien and os.path.exists(path):
        try:
            prev = json.load(open(path, encoding="utf-8"))
            clien = [p for p in prev.get("posts", []) if p.get("cafe") == "클리앙"]
            print("clien 신규 수집 실패 → 직전 클리앙 글 보존:", len(clien))
        except Exception:
            pass
    out += clien

    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    data = {"ok": True, "generatedAt": kst.strftime("%Y-%m-%d %H:%M"),
            "count": len(out), "posts": out}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    # 일별 언급량 스냅샷 누적(같은 날은 갱신, 최근 400일)
    names = []
    for p in out:
        if p["cafe"] not in names:
            names.append(p["cafe"])
    cafes_cnt = {n: sum(1 for p in out if p["cafe"] == n) for n in names}
    maxno = {n: max([p["no"] for p in out if p["cafe"] == n] or [0]) for n in names}
    hpath = os.path.join(os.path.dirname(__file__), "..", "cafe_history.json")
    hist = []
    if os.path.exists(hpath):
        try:
            hist = json.load(open(hpath, encoding="utf-8"))
        except Exception:
            hist = []
    if not isinstance(hist, list):
        hist = []
    day = kst.strftime("%Y-%m-%d")
    hist = [h for h in hist if h.get("date") != day]
    hist.append({"date": day, "total": len(out), "cafes": cafes_cnt, "maxNo": maxno})
    hist.sort(key=lambda x: x.get("date", ""))
    hist = hist[-400:]
    json.dump(hist, open(hpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", len(out), "posts", cafes_cnt)


if __name__ == "__main__":
    main()
