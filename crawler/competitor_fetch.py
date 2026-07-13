# -*- coding: utf-8 -*-
"""경쟁사 분석 데이터 수집 → web/competitor.json
   자사(아카라) 포함 5개 브랜드의 뉴스 언급량·키워드·연관검색어·데이터랩 트렌드.
   ※ 뉴스 API는 버스트 제한이 있어 순차+지연 수집. 카페는 할당량 이슈로 제외.
   GitHub Actions 주기 실행. 키: NAVER_ID/NAVER_SECRET."""
import os, re, json, html, time, datetime
import requests

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
H = {"X-Naver-Client-Id": NID, "X-Naver-Client-Secret": NSEC}
HJ = dict(H, **{"Content-Type": "application/json"})
DOMAIN = {"mt.co.kr": "머니투데이", "heraldcorp.com": "헤럴드경제", "sedaily.com": "서울경제", "hankyung.com": "한국경제",
          "etnews.com": "전자신문", "mk.co.kr": "매일경제", "dt.co.kr": "디지털타임스", "yna.co.kr": "연합뉴스",
          "asiae.co.kr": "아시아경제", "zdnet.co.kr": "지디넷", "inews24.com": "아이뉴스24", "newsis.com": "뉴시스",
          "edaily.co.kr": "이데일리", "fnnews.com": "파이낸셜뉴스"}
STOP = set("스마트홈 스마트 삼성 삼성전자 LG 엘지 전자 구글 애플 아카라 통해 위해 대한 관련 이번 최대 최고 지원 출시 공개 진행 예정 확대 강화 개발 도입 적용 기능 서비스 제품 브랜드 오픈 시장 기술 사업 그리고 기자 사진 제공 무단 배포 금지 뉴스 기사 이날 관계자 지난 오는 올해 가장 함께 모든 다양한 통합".split())
POS = re.compile("혁신|호평|인기|1위|수상|성장|확대|호실적|신기록|돌파|강화|협업|파트너십|호응|각광|주목|선도|최초|개선|만족|호조|흥행|수출|계약|투자|공략|기대|우수|첨단|프리미엄|글로벌")
NEG = re.compile("오류|결함|불편|하자|리콜|논란|불만|먹통|해킹|취약|유출|과징금|소송|패소|실패|지연|중단|하락|부진|철수|축소|우려|비판|경고|위반|사고|버그|장애|지적|둔화|적자|피해")
BRANDS = [
    {"name": "아카라", "q": "아카라 스마트홈", "ac": "아카라", "dl": ["아카라", "아카라 스마트홈"], "me": True},
    {"name": "헤이홈", "q": "헤이홈", "ac": "헤이홈", "dl": ["헤이홈"], "me": False},
    {"name": "삼성 스마트싱스", "q": "삼성 스마트싱스", "ac": "삼성 스마트싱스", "dl": ["스마트싱스", "삼성 스마트싱스"], "me": False},
    {"name": "LG 씽큐", "q": "LG 씽큐", "ac": "LG 씽큐", "dl": ["LG 씽큐", "씽큐"], "me": False},
    {"name": "구글홈", "q": "구글 홈", "ac": "구글 홈", "dl": ["구글홈", "구글 홈"], "me": False},
]


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def press(url):
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    h = m.group(1) if m else ""
    return DOMAIN.get(h, h)


def main():
    if not NID or not NSEC:
        raise SystemExit("ERROR: NAVER_ID/NAVER_SECRET 미설정")
    # 1) 뉴스 순차 수집
    news = {}
    for b in BRANDS:
        r = None
        for _ in range(3):
            try:
                r = requests.get("https://openapi.naver.com/v1/search/news.json",
                                 params={"query": b["q"], "display": 60, "sort": "date"}, headers=H, timeout=15).json()
                if r.get("items"):
                    break
            except Exception:
                r = None
            time.sleep(2)
        news[b["name"]] = r
        time.sleep(1.8)
    # 2) 자동완성(연관검색어)
    rel = {}
    for b in BRANDS:
        arr = []
        try:
            ac = requests.get("https://ac.search.naver.com/nx/ac",
                              params={"q": b["ac"], "st": 100, "r_format": "json", "frm": "nv"}, timeout=10).json()
            for x in (ac.get("items") or [[]])[0]:
                if x and x[0]:
                    arr.append(x[0])
        except Exception:
            pass
        rel[b["name"]] = arr[:12]
        time.sleep(0.25)
    # 처리
    out = []
    for b in BRANDS:
        r = news.get(b["name"]) or {}
        tot = int(r.get("total", 0) or 0)
        seen, items, freq, posw = set(), [], {}, {}
        for it in (r.get("items") or []):
            t, d = clean(it.get("title")), clean(it.get("description"))
            k = re.sub(r"[^0-9A-Za-z가-힣]", "", t)
            if k in seen:
                continue
            seen.add(k)
            blob = t + " " + d
            for m in POS.findall(blob):
                posw[m] = posw.get(m, 0) + 1
            if len(items) < 15:
                dt = ""
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(it.get("pubDate")).strftime("%Y-%m-%d")
                except Exception:
                    pass
                items.append({"title": t, "source": press(it.get("originallink") or it.get("link")), "date": dt, "link": it.get("link")})
            for w in re.sub(r"[^0-9A-Za-z가-힣 ]", " ", blob).split():
                w = w.strip()
                if len(w) < 2 or w in STOP or w.isdigit() or re.search("씽큐|스마트싱스|헤이홈|아카라", w):
                    continue
                freq[w] = freq.get(w, 0) + 1
        # 뉴스 감성
        pos = neg = neu = 0
        for it in (r.get("items") or []):
            blob = clean(it.get("title")) + " " + clean(it.get("description"))
            hp, hn = bool(POS.search(blob)), bool(NEG.search(blob))
            if hp and not hn:
                pos += 1
            elif hn and not hp:
                neg += 1
            else:
                neu += 1
        kw = sorted(freq.items(), key=lambda x: -x[1])[:18]
        pw = sorted(posw.items(), key=lambda x: -x[1])[:8]
        out.append({"name": b["name"], "me": b["me"], "query": b["q"], "total": tot,
                    "sentiment": {"pos": pos, "neu": neu, "neg": neg},
                    "keywords": [[w, c] for w, c in kw], "posWords": [[w, c] for w, c in pw],
                    "related": rel.get(b["name"], []), "recent": items})
    # DataLab 트렌드
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    end = (kst.date().replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    body = {"startDate": "2023-01-01", "endDate": end, "timeUnit": "month",
            "keywordGroups": [{"groupName": b["name"], "keywords": b["dl"]} for b in BRANDS]}
    dates, series = [], {}
    try:
        dl = requests.post("https://openapi.naver.com/v1/datalab/search", data=json.dumps(body).encode("utf-8"), headers=HJ, timeout=30).json()
        for g in dl.get("results", []):
            series[g["title"]] = [round(float(x["ratio"]), 2) for x in g["data"]]
        if dl.get("results"):
            dates = [x["period"] for x in dl["results"][0]["data"]]
    except Exception as e:
        print("datalab 실패:", e)
    data = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "brands": out, "trend": {"dates": dates, "series": series}}
    path = os.path.join(os.path.dirname(__file__), "..", "competitor.json")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("competitor.json OK:", {b["name"]: b["total"] for b in out})


if __name__ == "__main__":
    main()
