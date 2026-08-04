# -*- coding: utf-8 -*-
"""업계 뉴스 수집(인테리어·리모델링 / 스마트홈 / 도어락·보안 / 시장·정책) → web/industry_news.json
   대시보드 'PR > 이슈' 탭의 [업계] 세그먼트가 이 파일을 키워드 클러스터링해 이슈 카드로 보여준다.
   자사(아카라) 기사는 organic_news.json 쪽에서 이미 다루므로 여기서는 제외한다.
   GitHub Actions 주기 실행. 키: NAVER_ID/NAVER_SECRET."""
import os, re, json, html, time, datetime
import requests
from email.utils import parsedate_to_datetime

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
H = {"X-Naver-Client-Id": NID, "X-Naver-Client-Secret": NSEC}
URL = "https://openapi.naver.com/v1/search/news.json"

DAYS = 180          # 최근 며칠치까지 보관
PER_QUERY = 200     # 쿼리당 최대 수집(100건씩 2페이지)
PAUSE = 1.5         # 네이버 API 버스트 제한 회피(연속 호출 시 0건 반환됨)

# (그룹, 표시 브랜드/주제, 검색어, 본문·제목에 반드시 포함돼야 하는 정규식)
# ─ 인테리어·리모델링: 아카라 시공/쇼룸 사업의 직접 경쟁·협업 지형
# ─ 스마트홈: 플랫폼 주도권(매터 표준 포함) — 아카라 제품 호환성 이슈와 직결
# ─ 도어락·보안: L100 등 주력 제품군의 경쟁 지형
# ─ 시장·정책: 수요·규제·트렌드 배경
QUERIES = [
    ("인테리어", "한샘", "한샘 인테리어", r"한샘"),
    ("인테리어", "LX지인", "LX하우시스 지인", r"lx하우시스|지인|lx z:in"),
    ("인테리어", "현대리바트", "현대리바트", r"리바트"),
    ("인테리어", "KCC홈씨씨", "KCC글라스 홈씨씨", r"홈씨씨|kcc글라스"),
    ("인테리어", "이케아", "이케아 코리아", r"이케아|ikea"),
    ("인테리어", "오늘의집", "오늘의집 인테리어", r"오늘의집|버킷플레이스"),
    ("인테리어", "집닥·하우스텝", "집닥 하우스텝 시공", r"집닥|하우스텝"),
    ("인테리어", "인테리어 시공", "인테리어 시공 트렌드", r"인테리어"),
    ("인테리어", "리모델링 시장", "리모델링 시장", r"리모델링"),
    ("인테리어", "홈퍼니싱", "홈퍼니싱 시장", r"홈퍼니싱|가구 시장"),

    ("스마트홈", "삼성 스마트싱스", "삼성 스마트싱스", r"스마트싱스|smartthings"),
    ("스마트홈", "LG 씽큐", "LG 씽큐 AI홈", r"씽큐|thinq"),
    ("스마트홈", "구글 홈", "구글 홈 스마트홈", r"구글\s*홈|google home|제미나이"),
    ("스마트홈", "애플 홈킷", "애플 홈킷 스마트홈", r"홈킷|homekit|애플\s*홈"),
    ("스마트홈", "아마존 알렉사", "아마존 알렉사 스마트홈", r"알렉사|alexa"),
    ("스마트홈", "샤오미", "샤오미 스마트홈", r"샤오미|xiaomi|미홈"),
    ("스마트홈", "매터 표준", "매터 스마트홈 표준", r"매터|matter|스레드|thread|csa"),
    ("스마트홈", "헤이홈", "헤이홈 스마트홈", r"헤이홈|goodways"),
    ("스마트홈", "코맥스·코콤", "코맥스 코콤 홈네트워크", r"코맥스|코콤"),
    ("스마트홈", "월패드·홈네트워크", "월패드 홈네트워크", r"월패드|홈네트워크"),
    ("스마트홈", "AI홈", "AI홈 스마트홈", r"ai\s*홈|스마트홈"),
    ("스마트홈", "로봇청소기", "로봇청소기 스마트홈 연동", r"로봇청소기"),

    ("도어락·보안", "스마트도어락 시장", "스마트도어락 시장", r"도어락|도어록"),
    ("도어락·보안", "게이트맨", "게이트맨 도어락", r"게이트맨|아이레보"),
    ("도어락·보안", "삼성 도어락", "삼성 SDS 도어락", r"도어락|도어록"),
    ("도어락·보안", "직방 도어락", "직방 도어락", r"직방"),

    ("시장·정책", "스마트홈 시장", "스마트홈 시장 전망", r"스마트홈"),
    ("시장·정책", "홈IoT", "홈IoT 시장", r"홈\s*iot|사물인터넷"),
    ("시장·정책", "시니어 스마트홈", "시니어 스마트홈 고령친화", r"시니어|고령|돌봄"),
    ("시장·정책", "1인가구 주거", "1인가구 주거 트렌드", r"1인\s*가구|원룸|오피스텔"),
    ("시장·정책", "에너지 절감", "가정 에너지 절감 스마트", r"에너지|전기요금|절감"),
]

# 자사 기사는 '자사' 세그먼트에서 다루므로 업계 목록에서 제외
OWN = re.compile(r"아카라|aqara", re.I)
# 검색어와 무관하게 딸려오는 잡음(주가·부고·게임 등)
NOISE = re.compile(r"부고|인사말|주가|증권|코스피|코스닥|배당|무상증자|유상증자|공모주|채용공고|아카라카", re.I)

DOMAIN = {"mt.co.kr": "머니투데이", "heraldcorp.com": "헤럴드경제", "sedaily.com": "서울경제", "hankyung.com": "한국경제",
          "etnews.com": "전자신문", "mk.co.kr": "매일경제", "dt.co.kr": "디지털타임스", "yna.co.kr": "연합뉴스",
          "asiae.co.kr": "아시아경제", "zdnet.co.kr": "지디넷코리아", "inews24.com": "아이뉴스24", "newsis.com": "뉴시스",
          "edaily.co.kr": "이데일리", "fnnews.com": "파이낸셜뉴스", "chosun.com": "조선일보", "donga.com": "동아일보",
          "joongang.co.kr": "중앙일보", "khan.co.kr": "경향신문", "seoul.co.kr": "서울신문", "kmib.co.kr": "국민일보",
          "segye.com": "세계일보", "munhwa.com": "문화일보", "hankookilbo.com": "한국일보", "newspim.com": "뉴스핌",
          "ajunews.com": "아주경제", "biz.chosun.com": "조선비즈", "kukinews.com": "쿠키뉴스", "news1.kr": "뉴스1",
          "digitaltoday.co.kr": "디지털투데이", "itdaily.kr": "아이티데일리", "aitimes.com": "AI타임스",
          "businesskorea.co.kr": "비지니스코리아", "beyondpost.co.kr": "비욘드포스트", "ebn.co.kr": "EBN",
          "insightkorea.co.kr": "인사이트코리아", "electimes.com": "전기신문", "kr.aving.net": "에이빙뉴스"}


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
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    cutoff = (kst - datetime.timedelta(days=DAYS)).strftime("%Y-%m-%d")

    seen, items = set(), []
    for grp, brand, query, must in QUERIES:
        must_re = re.compile(must, re.I)
        got = 0
        for start in range(1, PER_QUERY + 1, 100):
            try:
                r = requests.get(URL, params={"query": query, "display": 100, "sort": "date", "start": start},
                                 headers=H, timeout=15).json()
            except Exception:
                break
            arr = r.get("items") or []
            if not arr:
                break
            for it in arr:
                t = clean(it.get("title"))
                blob = t + " " + clean(it.get("description"))
                if not t or OWN.search(blob) or NOISE.search(blob):
                    continue
                if not must_re.search(blob):
                    continue
                try:
                    dt = parsedate_to_datetime(it.get("pubDate")).strftime("%Y-%m-%d")
                except Exception:
                    continue
                if dt < cutoff:
                    continue
                k = re.sub(r"[^0-9A-Za-z가-힣]", "", t)
                if not k or k in seen:
                    continue
                seen.add(k)
                link = it.get("originallink") or it.get("link")
                items.append({"기사명": t, "매체": press_of(link), "게재일": dt,
                              "link": link, "그룹": grp, "브랜드": brand})
                got += 1
            time.sleep(PAUSE)
        print("  [%s] %s → %d건 (누적 %d)" % (grp, brand, got, len(items)))

    items.sort(key=lambda x: x["게재일"], reverse=True)
    groups = []
    for grp, brand, _q, _m in QUERIES:
        if grp not in groups:
            groups.append(grp)
    data = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "count": len(items), "days": DAYS,
            "note": "인테리어·스마트홈·도어락·시장 키워드로 수집한 업계 뉴스(아카라 자사 기사 제외). 이슈 탭 [업계]에서 키워드로 자동 클러스터링.",
            "groups": groups,
            "brands": [{"그룹": g, "브랜드": b, "검색어": q} for g, b, q, _m in QUERIES],
            "items": items}
    path = os.path.join(os.path.dirname(__file__), "..", "industry_news.json")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("industry_news.json OK — %d건" % len(items))


if __name__ == "__main__":
    main()
