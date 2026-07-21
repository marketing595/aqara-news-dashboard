# -*- coding: utf-8 -*-
"""경쟁사 대비 언론 노출량(Share of Voice) → web/compete.json
   네이버 뉴스 검색으로 브랜드별 '올해(YTD) 발행 기사 수'를 최신순 페이지네이션으로 집계.
   ※ 네이버 뉴스 API는 날짜 필터가 없어 최신순으로 올해 기사만 세며, API 상한(1000건) 초과 시 capped.
   ※ 삼성·LG는 종합 대기업 특성상 절대량이 커서 '추세 비교'용 참고 지표.
   GitHub Actions 주기 실행. 키: NAVER_ID/NAVER_SECRET."""
import os, json, datetime
import requests
from email.utils import parsedate_to_datetime

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
H = {"X-Naver-Client-Id": NID, "X-Naver-Client-Secret": NSEC}
URL = "https://openapi.naver.com/v1/search/news.json"

BRANDS = [
    ("아카라", "아카라 스마트홈", True),
    ("삼성 스마트싱스", "삼성 스마트싱스", False),
    ("LG 씽큐", "LG 씽큐", False),
    ("샤오미 스마트홈", "샤오미 스마트홈", False),
    ("애플 홈킷", "애플 홈킷", False),
    ("구글 홈", "구글 홈 스마트홈", False),
]


def total(query):
    try:
        r = requests.get(URL, params={"query": query, "display": 1}, headers=H, timeout=15)
        return int(r.json().get("total", 0))
    except Exception:
        return 0


def ytd_count(query, year):
    """올해 발행 기사 수(최신순 페이지네이션, API 최대 1000건). 1000건 넘게 올해 기사면 capped=True."""
    cnt, capped = 0, False
    for start in range(1, 1001, 100):
        try:
            r = requests.get(URL, params={"query": query, "display": 100, "start": start, "sort": "date"},
                             headers=H, timeout=15)
            items = r.json().get("items", [])
        except Exception:
            break
        if not items:
            break
        older = False
        for it in items:
            try:
                y = parsedate_to_datetime(it.get("pubDate")).year
            except Exception:
                continue
            if y == year:
                cnt += 1
            elif y < year:
                older = True
        if older:
            break
    else:
        capped = True   # 1000건까지 모두 올해 기사 → 상한 도달
    return cnt, capped


def main():
    if not NID or not NSEC:
        raise SystemExit("ERROR: NAVER_ID/NAVER_SECRET 미설정")
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    year = kst.year
    items = []
    for name, q, me in BRANDS:
        ytd, capped = ytd_count(q, year)
        item = {"name": name, "query": q, "ytd": ytd, "capped": capped, "year": year, "total": total(q)}
        if me:
            item["me"] = True
        items.append(item)
    data = {"generatedAt": kst.strftime("%Y-%m-%d"), "year": year, "basis": "ytd", "items": items}
    path = os.path.join(os.path.dirname(__file__), "..", "compete.json")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("compete.json OK (%d YTD):" % year, {i["name"]: (str(i["ytd"]) + ("+" if i["capped"] else "")) for i in items})


if __name__ == "__main__":
    main()
