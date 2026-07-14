# -*- coding: utf-8 -*-
"""파워링크(스마트홈 인테리어) 키워드 합산 검색 트렌드 → web/datalab.json
   네이버 데이터랩 검색어트렌드 API로 100개 키워드(5그룹×20)의 월별 상대 검색관심도를 합산.
   ※ 데이터랩은 절대 검색량이 아닌 상대지수 → '합산 관심도(상대)'로 표기.
   GitHub Actions 주기 실행. 키: NAVER_ID/NAVER_SECRET."""
import os, json, datetime
import requests

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
H = {"X-Naver-Client-Id": NID, "X-Naver-Client-Secret": NSEC, "Content-Type": "application/json"}

# 5그룹 × 20 = 100 키워드 (그룹 내부는 데이터랩이 OR 합산)
GROUPS = [
    ["스마트홈구축", "스마트홈설치", "스마트홈", "스마트홈인테리어", "스마트홈시공", "홈자동화", "홈오토메이션",
     "스마트홈솔루션", "스마트홈시스템", "스마트홈네트워크", "스마트홈리모델링", "스마트홈설계", "스마트홈통합제어",
     "공간자동화", "주거자동화시스템", "스마트홈만들기", "스마트홈추천", "스마트홈서비스", "스마트홈도입", "스마트홈구축방법"],
    ["IOT구축", "홈IOT구축", "IOT인테리어", "IoT설치", "홈IOT", "iot스마트홈구축", "IOT시공", "IOT리모델링",
     "스마트인테리어", "인테리어IOT", "IoT인테리어업체", "IOT오피스시공", "스마트오피스", "스마트오피스구축",
     "조명제어시스템", "스마트스위치시공", "스마트조명시공", "스마트커튼설치", "스마트도어락설치", "IOT시공업체"],
    ["스마트홈인테리어시공", "인테리어스마트홈시공", "스마트홈인테리어견적", "스마트홈견적", "스마트홈시공견적",
     "스마트홈업체", "스마트홈업체추천", "스마트홈설치업체", "스마트홈구축업체", "스마트홈설계업체",
     "인테리어업체스마트홈", "전기시공스마트홈", "스마트홈파트너", "스마트홈시공파트너", "스마트홈B2B",
     "스마트홈사업자몰", "스마트홈외주", "스마트홈공사", "스마트홈시공사", "스마트홈시공문의"],
    ["스마트홈상담", "스마트홈문의", "스마트홈구축문의", "스마트홈상담문의", "스마트홈비용", "스마트홈구축비용",
     "스마트홈설치비용", "iot상담", "스마트홈앱설정", "스마트홈앱연동", "스마트홈연동", "스마트홈연동방법",
     "스마트홈허브추천", "스마트홈브랜드", "스마트홈트렌드", "스마트홈기술교육", "스마트홈교육", "스마트홈자격증",
     "아카라라이프시공", "아카라설치"],
    ["스마트홈인테리어교육", "IOT교육", "인테리어교육", "인테리어배우기", "인테리어기술", "인테리어자격증",
     "집수리교육", "집수리아카데미", "인테리어디자인", "인테리어종류", "구경하는집", "스마트홈구경하는집",
     "25평인테리어", "신혼인테리어", "아파트구경하는집", "리모델링견적", "구옥리모델링", "노후아파트인테리어",
     "침실인테리어", "아기방인테리어"],
]


# 테마별 비교 그룹(각 그룹 내부는 OR 합산되어 하나의 상대지수) — 인테리어 vs 스마트홈
THEME_GROUPS = {
    "인테리어": ["인테리어", "홈인테리어", "셀프인테리어", "집꾸미기", "홈스타일링", "인테리어소품", "아파트인테리어",
              "거실인테리어", "주방인테리어", "침실인테리어", "인테리어시공", "리모델링", "홈데코", "인테리어디자인",
              "구경하는집", "신혼인테리어", "원룸인테리어", "인테리어업체", "인테리어견적", "인테리어트렌드"],
    "스마트홈": ["스마트홈", "스마트조명", "스마트도어락", "스마트스위치", "스마트플러그", "홈캠", "홈오토메이션",
              "스마트커튼", "스마트홈허브", "매터", "스마트가전", "스마트홈기기", "홈네트워크", "스마트홈앱",
              "재실센서", "스마트콘센트", "스마트홈시스템", "월패드", "스마트홈구축", "스마트홈설치"],
}


def fetch_themes(start, end):
    """인테리어·스마트홈 테마 그룹의 월별 상대지수(서로 비교 가능하도록 한 번의 호출로 수집)."""
    body = {"startDate": start, "endDate": end, "timeUnit": "month",
            "keywordGroups": [{"groupName": k, "keywords": v} for k, v in THEME_GROUPS.items()]}
    r = requests.post("https://openapi.naver.com/v1/datalab/search",
                      data=json.dumps(body).encode("utf-8"), headers=H, timeout=30)
    if r.status_code != 200:
        print("테마 데이터랩 오류", r.status_code, r.text[:200])
        return {"dates": [], "series": {}}
    res = r.json().get("results", [])
    dates, series = [], {}
    for g in res:
        series[g["title"]] = [round(float(x["ratio"]), 2) for x in g.get("data", [])]
    if res:
        dates = [x["period"] for x in res[0].get("data", [])]
    return {"dates": dates, "series": series}


def last_complete_month_end(today):
    first = today.replace(day=1)
    prev_end = first - datetime.timedelta(days=1)
    return prev_end


def main():
    if not NID or not NSEC:
        raise SystemExit("ERROR: NAVER_ID/NAVER_SECRET 미설정")
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    end = last_complete_month_end(kst.date())
    body = {
        "startDate": "2022-01-01",
        "endDate": end.strftime("%Y-%m-%d"),
        "timeUnit": "month",
        "keywordGroups": [{"groupName": "G%d" % (i + 1), "keywords": g} for i, g in enumerate(GROUPS)],
    }
    r = requests.post("https://openapi.naver.com/v1/datalab/search",
                      data=json.dumps(body).encode("utf-8"), headers=H, timeout=30)
    if r.status_code != 200:
        raise SystemExit("데이터랩 오류 %s %s" % (r.status_code, r.text[:300]))
    res = r.json().get("results", [])
    # 그룹별 시계열을 기간별 합산
    summed = {}
    for g in res:
        for d in g.get("data", []):
            summed[d["period"]] = summed.get(d["period"], 0) + float(d["ratio"])
    series = [{"date": p, "value": round(summed[p], 2)} for p in sorted(summed.keys())]

    # 인테리어 vs 스마트홈 테마 비교 트렌드
    themes = fetch_themes("2022-01-01", end.strftime("%Y-%m-%d"))

    kw_count = sum(len(g) for g in GROUPS)
    data = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "period": "month",
            "keywordCount": kw_count, "endDate": end.strftime("%Y-%m-%d"),
            "note": "네이버 데이터랩 검색어트렌드 · 100개 파워링크 키워드 합산 상대 관심도(절대 검색량 아님)",
            "series": series,
            "themes": themes,
            "themeKeywords": {k: v for k, v in THEME_GROUPS.items()}}
    path = os.path.join(os.path.dirname(__file__), "..", "datalab.json")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("datalab.json OK — %d개월, 키워드 %d개" % (len(series), kw_count))


if __name__ == "__main__":
    main()
