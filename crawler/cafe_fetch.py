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
]


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


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

    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    data = {"ok": True, "generatedAt": kst.strftime("%Y-%m-%d %H:%M"),
            "count": len(out), "posts": out}
    path = os.path.join(os.path.dirname(__file__), "..", "cafe.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    # 일별 언급량 스냅샷 누적(같은 날은 갱신, 최근 400일)
    cafes_cnt = {c["name"]: sum(1 for p in out if p["cafe"] == c["name"]) for c in CAFES}
    maxno = {c["name"]: max([p["no"] for p in out if p["cafe"] == c["name"]] or [0]) for c in CAFES}
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
