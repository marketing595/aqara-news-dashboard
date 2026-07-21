# -*- coding: utf-8 -*-
"""경쟁사 언론플레이 키워드 분석 → web/compete.json
   네이버 뉴스에서 경쟁사별 최근 기사 제목·본문을 모아 '자주 쓰는 키워드'를 집계.
   (단순 노출 건수보다 '어떤 메시지·주제로 PR 하는가'를 파악)
   GitHub Actions 주기 실행. 키: NAVER_ID/NAVER_SECRET."""
import os, re, json, html, datetime
import requests
from email.utils import parsedate_to_datetime

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
H = {"X-Naver-Client-Id": NID, "X-Naver-Client-Secret": NSEC}
URL = "https://openapi.naver.com/v1/search/news.json"

# (표시명, 검색어, 자사여부, 브랜드 제외어)
BRANDS = [
    ("아카라", "아카라 스마트홈", True, ["아카라", "아카라라이프", "aqara"]),
    ("삼성 스마트싱스", "삼성 스마트싱스", False, ["삼성", "삼성전자", "스마트싱스", "smartthings"]),
    ("LG 씽큐", "LG 씽큐", False, ["lg", "엘지", "씽큐", "thinq"]),
    ("샤오미 스마트홈", "샤오미 스마트홈", False, ["샤오미", "xiaomi", "미홈"]),
    ("애플 홈킷", "애플 홈킷", False, ["애플", "apple", "홈킷", "homekit"]),
    ("구글 홈", "구글 홈 스마트홈", False, ["구글", "google", "구글홈"]),
]

# 일반 불용어(주제성 없는 단어)
STOP = set("""스마트홈 출시 기자 뉴스 관련 통해 위해 지원 제공 서비스 기능 시장 기업 사업 그룹 공개 적용 도입 확대 강화 선보 이번 최근
오는 라이프 코리아 한국 글로벌 브랜드 고객 혁신 미래 경험 제품 신제품 소개 발표 진행 예정 계획 방침 대표 관계자 전망 기대 개최 참가 참여
사용 이용 다양 통합 연동 호환 기반 활용 중심 대상 지난 올해 내년 상반기 하반기 이날 당사 자사 업계 국내 해외 세계 대비 각종 각각 모든 함께
그동안 이후 이전 대한 위한 가운데 라고 라며 밝혔 밝혀 했다 한다 된다 있다 없다 이라 이라며 라는 이라는 통한 위주 관련해 관련된
전자 신문 데일리 경제 미디어 리포트 제하 무단 배포 저작권""".split())


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


JOSA2 = ("으로", "라고", "라며", "에서", "에게", "까지", "부터", "이라", "과의", "와의", "에는", "에도", "으로써", "이라는", "라는")
JOSA1 = ("은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "로", "만")


def strip_josa(w):
    for j in JOSA2:
        if len(w) > len(j) + 1 and w.endswith(j):
            return w[:-len(j)]
    for j in JOSA1:
        if len(w) > 2 and w.endswith(j):
            return w[:-1]
    return w


def news(query, start):
    r = requests.get(URL, params={"query": query, "display": 100, "start": start, "sort": "date"},
                     headers=H, timeout=15)
    return r.json().get("items", []) if r.status_code == 200 else []


def analyze(query, brand_stop, year):
    items, cnt, ytd, capped = [], {}, 0, False
    for start in range(1, 401, 100):     # 최근 최대 400건
        arr = news(query, start)
        if not arr:
            break
        older = False
        for it in arr:
            try:
                y = parsedate_to_datetime(it.get("pubDate")).year
            except Exception:
                y = year
            if y == year:
                ytd += 1
            elif y < year:
                older = True
            items.append(it)
        if older:
            break
    else:
        capped = True
    bstop = set(x.lower() for x in brand_stop)
    rep = {}
    for it in items:
        ttl = clean(it.get("title"))
        link = it.get("originallink") or it.get("link")
        text = ttl + " " + clean(it.get("description"))
        for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", text):
            wl = strip_josa(w) if re.search(r"[가-힣]", w) else w
            key = wl.lower()
            if len(wl) < 2 or key in STOP or key in bstop or wl in STOP:
                continue
            if re.fullmatch(r"[0-9]+", wl):
                continue
            cnt[wl] = cnt.get(wl, 0) + 1
            if wl not in rep:   # items가 최신순 → 첫 등장 = 가장 최근 대표 기사
                rep[wl] = {"title": ttl, "link": link}
    top = sorted(cnt.items(), key=lambda x: -x[1])[:18]
    return ytd, capped, [{"kw": k, "n": v, "title": rep.get(k, {}).get("title"), "link": rep.get(k, {}).get("link")}
                         for k, v in top if v >= 2], len(items)


def main():
    if not NID or not NSEC:
        raise SystemExit("ERROR: NAVER_ID/NAVER_SECRET 미설정")
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    year = kst.year
    items = []
    for name, q, me, bstop in BRANDS:
        ytd, capped, topkw, n = analyze(q, bstop, year)
        item = {"name": name, "query": q, "ytd": ytd, "capped": capped, "analyzed": n, "topKw": topkw}
        if me:
            item["me"] = True
        items.append(item)
        print("%s: %d건 분석 · 키워드 %d" % (name, n, len(topkw)))
    data = {"generatedAt": kst.strftime("%Y-%m-%d"), "year": year, "basis": "keywords", "items": items}
    path = os.path.join(os.path.dirname(__file__), "..", "compete.json")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("compete.json OK")


if __name__ == "__main__":
    main()
