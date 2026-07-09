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
        "너는 스마트홈 AIoT·인테리어 기업 '아카라라이프'의 데일리 뉴스 브리핑 봇이다.\n"
        "아래 카테고리별 뉴스 후보 중, 아카라라이프에 의미있는 기사만 카테고리별 1~3개 선별해 요약하고 '아카라 인사이트'를 써라.\n"
        "무관하거나 중복이면 제외. 각 카테고리 최소 1개는 채우되 마땅한 게 없으면 비워도 된다.\n"
        "요약은 2~3문장, 인사이트는 아카라 제품/전략 관점의 시사점 1~2문장.\n"
        "반드시 아래 JSON 스키마로만 출력(선택한 기사는 대괄호 안 인덱스 문자열 id로 지정):\n"
        '{"headline":"오늘 전체를 관통하는 핵심 한 줄", '
        '"picks":{"tech":[{"id":"tech-0","summary":"...","insight":"..."}],"comp":[...],"intr":[...],"trend":[...]}}\n\n'
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
    sections = []
    for key, icon, title, _k in CATS:
        picks = (res.get("picks", {}) or {}).get(key, []) or []
        items = []
        for p in picks:
            it = idx.get(p.get("id"))
            if not it:
                continue
            items.append({"t": it["title"], "s": it["source"], "d": it["date"], "link": it["link"],
                          "sum": p.get("summary", ""), "ins": p.get("insight", "")})
        if items:
            sections.append({"icon": icon, "title": title, "items": items})
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    day = kst.strftime("%Y-%m-%d")
    today = {"headline": res.get("headline", ""), "sections": sections}

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
    print("briefing for", day, "sections:", len(sections))


if __name__ == "__main__":
    main()
