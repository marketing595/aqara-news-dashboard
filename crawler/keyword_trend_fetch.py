# -*- coding: utf-8 -*-
"""개별 키워드 검색 관심도 트렌드 → web/keywords_trend.json
   네이버 데이터랩 검색어트렌드 API(월간). 키워드마다 개별 그룹으로 조회하되,
   '스마트홈' 앵커를 매 배치에 넣어 교차 정규화 → 키워드 간 비교 가능한 관심도(vol) 산출.
   latest/mom(전월대비)/yoy(전년대비) + 정규화 시계열. 카테고리 태그 포함.
   GitHub Actions 실행. 키: NAVER_ID/NAVER_SECRET."""
import os, json, datetime, time, hmac, hashlib, base64
import requests

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
H = {"X-Naver-Client-Id": NID, "X-Naver-Client-Secret": NSEC, "Content-Type": "application/json"}
API = "https://openapi.naver.com/v1/datalab/search"
ANCHOR = "스마트홈"
SOURCE = "https://datalab.naver.com/keyword/trendSearch.naver"

# 네이버 검색광고 키워드도구 API — 실제 월간 검색수(PC+모바일). 키 없으면 건너뜀.
SA_KEY = os.environ.get("SEARCHAD_API_KEY", "")
SA_SEC = os.environ.get("SEARCHAD_SECRET", "")
SA_CID = os.environ.get("SEARCHAD_CUSTOMER_ID", "")
SA_BASE = "https://api.searchad.naver.com"


def _sa_num(x):
    if isinstance(x, (int, float)):
        return int(x)
    s = str(x).replace("<", "").replace(",", "").strip()
    try:
        return int(s)
    except Exception:
        return 0


def searchad_volumes(keywords):
    """검색광고 키워드도구로 키워드별 월간 검색수(PC+모바일) 조회. 키 없으면 {}."""
    if not (SA_KEY and SA_SEC and SA_CID):
        print("SEARCHAD 키 미설정 — 쿼리량 수집 생략(데이터랩 관심도만)")
        return {}
    path = "/keywordstool"
    out = {}
    norm = lambda s: (s or "").replace(" ", "").upper()
    for kw in keywords:
        ts = str(int(time.time() * 1000))
        msg = "%s.%s.%s" % (ts, "GET", path)
        sign = base64.b64encode(hmac.new(SA_SEC.encode(), msg.encode(), hashlib.sha256).digest()).decode()
        headers = {"X-Timestamp": ts, "X-API-KEY": SA_KEY, "X-Customer": SA_CID, "X-Signature": sign}
        try:
            r = requests.get(SA_BASE + path, params={"hintKeywords": kw.replace(" ", ""), "showDetail": "1"},
                             headers=headers, timeout=15)
            if r.status_code != 200:
                print("searchad %s -> %s %s" % (kw, r.status_code, r.text[:120]))
                continue
            for it in r.json().get("keywordList", []):
                if norm(it.get("relKeyword")) == norm(kw):
                    pc, mo = _sa_num(it.get("monthlyPcQcCnt")), _sa_num(it.get("monthlyMobileQcCnt"))
                    out[kw] = {"pc": pc, "mobile": mo, "total": pc + mo}
                    break
            time.sleep(0.12)   # 레이트리밋 여유
        except Exception as e:
            print("searchad 실패 %s: %s" % (kw, e))
    return out

# (키워드, 카테고리) — 자사 / 카테고리 / 시즌 / 경쟁사 / 틈새 / 인테리어
KEYWORDS = [
    # 자사·브랜드
    ("아카라", "자사"), ("아카라라이프", "자사"), ("아카라 도어락", "자사"), ("매터", "자사"),
    # 핵심 카테고리
    ("스마트홈 인테리어", "카테고리"), ("스마트 도어락", "카테고리"), ("스마트 조명", "카테고리"),
    ("스마트 커튼", "카테고리"), ("스마트 스위치", "카테고리"), ("스마트 플러그", "카테고리"),
    ("홈캠", "카테고리"), ("재실센서", "카테고리"), ("월패드", "카테고리"), ("홈네트워크", "카테고리"),
    ("스마트홈 허브", "카테고리"), ("스마트 초인종", "카테고리"), ("스마트 온도조절기", "카테고리"),
    ("스마트 블라인드", "카테고리"), ("누수감지센서", "카테고리"), ("스마트 콘센트", "카테고리"),
    # 시즌·라이프스타일
    ("이사 스마트홈", "시즌"), ("신혼 스마트홈", "시즌"), ("혼수 가전", "시즌"), ("홈오피스", "시즌"),
    ("1인가구 스마트홈", "시즌"), ("전월세 스마트홈", "시즌"), ("무타공 스마트홈", "시즌"),
    ("반려동물 홈캠", "시즌"), ("난방 자동화", "시즌"), ("폭염 에어컨 자동화", "시즌"),
    # 경쟁사
    ("스마트싱스", "경쟁사"), ("LG 씽큐", "경쟁사"), ("구글홈", "경쟁사"), ("애플 홈킷", "경쟁사"),
    ("샤오미 스마트홈", "경쟁사"), ("미홈", "경쟁사"), ("헤이홈", "경쟁사"), ("코맥스", "경쟁사"),
    # 틈새·기술
    ("스마트홈 DIY", "틈새"), ("스마트홈 렌탈", "틈새"), ("스마트홈 구독", "틈새"), ("매터 호환", "틈새"),
    ("스레드", "틈새"), ("지그비", "틈새"), ("스마트홈 자동화", "틈새"), ("IoT 인테리어", "틈새"),
    ("홈 오토메이션", "틈새"), ("스마트 가스밸브", "틈새"), ("구글 어시스턴트", "틈새"),
    ("스마트홈 구축비용", "틈새"), ("스마트홈 시공", "틈새"),
    # 인테리어(상위 트래픽)
    ("인테리어", "인테리어"), ("셀프인테리어", "인테리어"), ("아파트 인테리어", "인테리어"),
    ("리모델링", "인테리어"), ("집꾸미기", "인테리어"), ("구경하는집", "인테리어"), ("신혼 인테리어", "인테리어"),
]


def datalab(groups, start, end):
    body = {"startDate": start, "endDate": end, "timeUnit": "month",
            "keywordGroups": [{"groupName": g, "keywords": [g]} for g in groups]}
    r = requests.post(API, data=json.dumps(body).encode("utf-8"), headers=H, timeout=30)
    if r.status_code != 200:
        print("datalab 오류", r.status_code, r.text[:200])
        return None
    out = {}
    for g in r.json().get("results", []):
        out[g["title"]] = [float(x["ratio"]) for x in g.get("data", [])]
    dates = []
    res = r.json().get("results", [])
    if res:
        dates = [x["period"][:7] for x in res[0].get("data", [])]
    return {"dates": dates, "series": out}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def main():
    if not NID or not NSEC:
        raise SystemExit("ERROR: NAVER_ID/NAVER_SECRET 미설정")
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    first = kst.date().replace(day=1)
    end = (first - datetime.timedelta(days=1))          # 직전 완료 월 말일
    start = (end.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    for _ in range(24):                                 # 약 25개월 전으로
        start = (start - datetime.timedelta(days=1)).replace(day=1)
    s, e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    names = [k for k, _ in KEYWORDS]
    ref_anchor = None
    result = {}
    dates_ref = []
    # 4개씩 배치 + 앵커
    for i in range(0, len(names), 4):
        batch = names[i:i + 4]
        groups = [ANCHOR] + [b for b in batch if b != ANCHOR]
        d = datalab(groups, s, e)
        if not d:
            continue
        if not dates_ref:
            dates_ref = d["dates"]
        anc = d["series"].get(ANCHOR, [])
        if ref_anchor is None:
            ref_anchor = mean(anc) or 1.0
        factor = (ref_anchor / mean(anc)) if mean(anc) else 1.0
        for b in batch:
            ser = d["series"].get(b)
            if ser is None:
                continue
            result[b] = [round(v * factor, 2) for v in ser]
    # 앵커 자신도 포함(정규화 기준 = ref_anchor 스케일)
    if ANCHOR not in result and ANCHOR in [k for k, _ in KEYWORDS]:
        pass

    cat_of = {k: c for k, c in KEYWORDS}
    kws = []
    for name in names:
        ser = result.get(name)
        if not ser:
            continue
        latest = ser[-1]
        prev = ser[-2] if len(ser) >= 2 else None
        yago = ser[-13] if len(ser) >= 13 else None
        mom = round((latest - prev) / prev * 100) if prev else 0
        yoy = round((latest - yago) / yago * 100) if yago else None
        kws.append({"name": name, "cat": cat_of.get(name, ""), "vol": round(latest, 1),
                    "latest": round(latest, 1), "mom": mom, "yoy": yoy, "series": ser})

    maxvol = max([k["vol"] for k in kws], default=1)
    for k in kws:
        k["volPct"] = round(k["vol"] / maxvol * 100) if maxvol else 0

    # 실제 월간 검색수(검색광고 키워드도구) 병합 — 키 있을 때만
    qv = searchad_volumes([k["name"] for k in kws])
    for k in kws:
        q = qv.get(k["name"])
        if q:
            k["qMonthly"] = q["total"]
            k["qPc"] = q["pc"]
            k["qMobile"] = q["mobile"]
    has_q = bool(qv)

    data = {
        "generatedAt": kst.strftime("%Y-%m-%d %H:%M"),
        "period": "month", "startDate": s, "endDate": e, "anchor": ANCHOR,
        "source": SOURCE, "hasQuery": has_q,
        "pctBasis": "mom(전월대비) = (이번달 관심도 − 전달 관심도) ÷ 전달 관심도 × 100. 관심도는 네이버 데이터랩 월간 상대지수(0~100).",
        "queryBasis": "qMonthly = 네이버 검색광고 키워드도구 최근 30일 PC+모바일 검색수(실제 쿼리량).",
        "method": "관심도 추세(mom/yoy): 데이터랩 검색어트렌드 API, 키워드별 개별 조회 후 '스마트홈' 앵커로 교차 정규화. 검색량(qMonthly): 검색광고 키워드도구 월간 검색수.",
        "keywords": kws,
    }
    path = os.path.join(os.path.dirname(__file__), "..", "keywords_trend.json")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("keywords_trend.json OK — %d개 키워드 · %s~%s" % (len(kws), s, e))


if __name__ == "__main__":
    main()

# trigger: searchad 쿼리량 수집
