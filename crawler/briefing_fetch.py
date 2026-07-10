# -*- coding: utf-8 -*-
"""스마트홈 & 인테리어 데일리 브리핑 자동 생성 → web/briefing.json
   네이버 뉴스 수집 → Gemini로 카테고리별 요약+아카라 인사이트 생성 → 날짜별 누적.
   GitHub Actions 매일 실행. 키: NAVER_ID/NAVER_SECRET, GEMINI_API_KEY."""
import os, re, json, html, datetime
import requests

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
GKEY = os.environ.get("GEMINI_API_KEY", "")
NH = {"X-Naver-Client-Id": NID, "X-Naver-Client-Secret": NSEC}

CATS = [
    ("tech", "🔍", "1. 자사 및 기술 생태계 (아카라 & 표준 기술)",
     ["아카라라이프", "매터 스마트홈", "스레드 스마트홈", "지그비", "AIoT 스마트홈"]),
    ("comp", "⚔️", "2. 경쟁사 동향 (삼성, LG, 빅테크, 샤오미 등)",
     ["스마트싱스", "LG 씽큐", "구글홈", "애플 홈킷", "샤오미 스마트홈"]),
    ("intr", "🏠", "3. 스마트홈 인테리어 & B2B 시공 시장",
     ["스마트홈 인테리어", "스마트 도어락", "신축 아파트 IoT", "스마트홈 시공"]),
    ("trend", "📈", "4. 거시 트렌드 (AI, IT, 유통, 에너지)",
     ["AI 인테리어", "스마트홈 에너지 절감", "홈 IoT 트렌드", "스마트홈 트렌드"]),
]
REL = re.compile("스마트홈|스마트 도어|도어락|스마트 조명|재실|스마트 커튼|월패드|홈네트워크|매터|스레드|지그비|smartthings|스마트싱스|씽큐|thinq|홈킷|구글홈|샤오미|미홈|aiot|스마트 가전|홈 iot|aqara|아카라|스마트 스위치|홈캠|홈 cctv|스마트빌딩|공간 지능|스마트홈 인테리어", re.I)
DOMAIN = {"mt.co.kr": "머니투데이", "news.mt.co.kr": "머니투데이", "heraldcorp.com": "헤럴드경제", "sedaily.com": "서울경제",
          "hankyung.com": "한국경제", "etnews.com": "전자신문", "mk.co.kr": "매일경제", "dt.co.kr": "디지털타임스",
          "yna.co.kr": "연합뉴스", "asiae.co.kr": "아시아경제", "dailian.co.kr": "데일리안", "biz.chosun.com": "조선비즈",
          "dnews.co.kr": "대한전문건설신문", "greened.kr": "그린포스트", "shinailbo.co.kr": "신아일보"}


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def press(url):
    m = re.match(r"https?://([^/]+)", url or "")
    h = (m.group(1).replace("www.", "") if m else "")
    return DOMAIN.get(h, h)


def collect():
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)
    cand = {}
    for key, _icon, _title, kws in CATS:
        seen, items = set(), []
        for q in kws:
            try:
                r = requests.get("https://openapi.naver.com/v1/search/news.json",
                                 params={"query": q, "display": 30, "sort": "date"}, headers=NH, timeout=15)
                arr = r.json().get("items", [])
            except Exception:
                continue
            for it in arr:
                title = clean(it.get("title"))
                desc = clean(it.get("description"))
                if not REL.search(title + " " + desc):
                    continue
                try:
                    from email.utils import parsedate_to_datetime
                    pub = parsedate_to_datetime(it.get("pubDate"))
                except Exception:
                    pub = None
                if not pub or pub < cutoff:
                    continue
                k = re.sub(r"[^0-9a-z가-힣]", "", title.lower())
                if k in seen:
                    continue
                seen.add(k)
                link = it.get("link") or it.get("originallink")
                items.append({"title": title, "source": press(it.get("originallink") or link),
                              "date": pub.strftime("%Y-%m-%d"), "link": link, "snippet": desc[:120]})
            if len(items) >= 12:
                break
        cand[key] = items[:10]
    return cand


def gemini(cand):
    lines = []
    for key, _icon, title, _kws in CATS:
        lines.append(f"\n## 카테고리 {key} ({title})")
        for i, it in enumerate(cand.get(key, [])):
            lines.append(f"[{key}-{i}] {it['title']} / {it['source']} / {it['date']} :: {it['snippet']}")
    newsblock = "\n".join(lines)
    prompt = (
        "너는 스마트홈 AIoT·인테리어 기업 '아카라라이프'의 홍보(PR)·언론 모니터링 전문가다.\n"
        "아래 뉴스 후보 중 아카라라이프에 의미있는 기사만 8~12건 선별해 '일일 언론 모니터링 보고'를 작성하라.\n"
        "무관/중복 기사는 제외. 각 기사는 [자사/경쟁사/시장/업계] 중 하나로 분류한다.\n"
        "(자사=아카라 직접 관련, 경쟁사=삼성·LG·샤오미·구글·애플 등, 시장=인테리어·시공·B2B 등, 업계=정책·표준·거시 트렌드)\n"
        "'insight'는 단순 요약을 넘어 아카라 비즈니스에 주는 시사점을 개조식으로 1~2문장.\n"
        "headlines는 자사/업계/경쟁사 각 한 줄 종합 요약.\n"
        "반드시 아래 JSON 스키마로만 출력(선택 기사는 후보의 대괄호 id로 지정):\n"
        '{"headlines":{"자사":"...","업계":"...","경쟁사":"..."},'
        '"rows":[{"id":"tech-0","cat":"자사","insight":"핵심 내용 및 시사점"}]}\n\n'
        "뉴스 후보:\n" + newsblock)
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=" + GKEY
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0.4}}
    r = requests.post(url, json=body, timeout=90)
    txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(txt)


def main():
    cand = collect()
    idx = {}
    for key, _i, _t, _k in CATS:
        for i, it in enumerate(cand.get(key, [])):
            idx[f"{key}-{i}"] = it
    res = gemini(cand)
    rows = []
    for p in (res.get("rows", []) or []):
        it = idx.get(p.get("id"))
        if not it:
            continue
        rows.append({"cat": p.get("cat", "시장"), "s": it["source"], "t": it["title"],
                     "d": it["date"], "ins": p.get("insight", ""), "link": it["link"]})
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    day = kst.strftime("%Y-%m-%d")
    today = {"headlines": res.get("headlines", {}), "rows": rows}

    path = os.path.join(os.path.dirname(__file__), "..", "briefing.json")
    store = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "briefings": {}}
    if os.path.exists(path):
        try:
            store = json.load(open(path, encoding="utf-8"))
            store.setdefault("briefings", {})
        except Exception:
            pass
    store["briefings"][day] = today
    store["generatedAt"] = kst.strftime("%Y-%m-%d %H:%M")
    # 최근 30일만 유지
    keys = sorted(store["briefings"].keys(), reverse=True)[:30]
    store["briefings"] = {k: store["briefings"][k] for k in keys}
    json.dump(store, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("briefing for", day, "rows:", len(rows))


if __name__ == "__main__":
    main()
