# -*- coding: utf-8 -*-
"""경쟁사 대비 언론 노출량(Share of Voice) → web/compete.json
   네이버 뉴스 검색 total(누적 노출량, 브랜드/스마트홈 맥락)로 브랜드별 노출량 비교.
   ※ 삼성·LG는 종합 대기업 특성상 절대량이 커서 '추세 비교'용 참고 지표.
   GitHub Actions 주기 실행. 키: NAVER_ID/NAVER_SECRET."""
import os, json, datetime
import requests

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
H = {"X-Naver-Client-Id": NID, "X-Naver-Client-Secret": NSEC}

# (표시명, 검색어, 자사여부)
BRANDS = [
    ("아카라", "아카라 스마트홈", True),
    ("삼성 스마트싱스", "삼성 스마트싱스", False),
    ("LG 씽큐", "LG 씽큐", False),
    ("샤오미 스마트홈", "샤오미 스마트홈", False),
    ("애플 홈킷", "애플 홈킷", False),
    ("구글 홈", "구글 홈 스마트홈", False),
]


def total(query):
    r = requests.get("https://openapi.naver.com/v1/search/news.json",
                     params={"query": query, "display": 1}, headers=H, timeout=15)
    return int(r.json().get("total", 0))


def main():
    if not NID or not NSEC:
        raise SystemExit("ERROR: NAVER_ID/NAVER_SECRET 미설정")
    items = []
    for name, q, me in BRANDS:
        try:
            t = total(q)
        except Exception as e:
            print("실패:", name, e)
            t = 0
        item = {"name": name, "query": q, "total": t}
        if me:
            item["me"] = True
        items.append(item)
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    data = {"generatedAt": kst.strftime("%Y-%m-%d"), "items": items}
    path = os.path.join(os.path.dirname(__file__), "..", "compete.json")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("compete.json OK:", {i["name"]: i["total"] for i in items})


if __name__ == "__main__":
    main()
