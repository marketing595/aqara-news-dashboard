# -*- coding: utf-8 -*-
"""스마트홈 & 인테리어 데일리 브리핑 자동 생성 → web/briefing.json
   네이버 뉴스 수집 → Gemini로 카테고리별 요약+아카라 인사이트 생성 → 날짜별 누적.
   GitHub Actions 매일 실행. 키: NAVER_ID/NAVER_SECRET, GEMINI_API_KEY."""
import os, re, json, html, datetime
import requests

# 일일 언론 모니터링 보고 자동 생성 (네이버 뉴스 + Gemini)
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
          "dnews.co.kr": "대한전문건설신문", "greened.kr": "그린포스트", "shinailbo.co.kr": "신아일보",
          "beyondpost.co.kr": "비욘드포스트", "insightkorea.co.kr": "인사이트코리아"}


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
        "너는 스마트홈·인테리어 분야 뉴스를 사실 그대로 요약하는 신문 편집 담당자다.\n"
        "아래 뉴스 후보 중 스마트홈·인테리어에 의미있는 기사만 8~12건 선별해 '일일 언론 모니터링 보고'를 작성하라.\n"
        "무관/중복 기사는 제외. 각 기사는 [자사/경쟁사/시장/업계] 중 하나로 분류한다.\n"
        "(자사=아카라 직접 관련, 경쟁사=삼성·LG·샤오미·구글·애플 등, 시장=인테리어·시공·B2B 등, 업계=정책·표준·거시 트렌드)\n"
        "★가장 중요한 규칙★ 'insight'는 '그 기사 한 건'에 실제로 보도된 사실만 3인칭으로 건조하게 요약한다(1~2문장).\n"
        "- 경쟁사·시장·업계 기사의 insight에는 '아카라'를 절대 언급하지 마라. 그 기사의 사실만 옮겨라.\n"
        "- 여러 기사나 회사를 서로 연결짓지 마라. '~하는 가운데/~에 대응하여/~에 따라 아카라는…' 같은 연결·훈수 문장 금지.\n"
        "- 전략·제언·시사점·평가·추천·전망·해석 금지. '~해야 한다/필요하다/공략/틈새시장/강점으로 내세워/전략적으로/주목된다/전망된다' 같은 표현 금지.\n"
        "  나쁜 예(절대 금지): '삼성·LG가 AI홈을 확장하는 가운데, 아카라는 Matter 호환성을 무기로 틈새시장을 확대해야 함.'\n"
        "  좋은 예(이렇게): '삼성전자가 신형 스마트싱스 허브를 공개하고 Matter 지원 기기를 확대했다고 밝혔다.'\n"
        "즉 기자가 쓴 사실 보도 문장처럼, 누가/무엇을/어떻게 했는지 사실만 옮겨라.\n"
        "headlines도 마찬가지로 자사/업계/경쟁사 각 한 줄 '사실' 종합(제언·평가 금지, 경쟁사·업계엔 아카라 언급 금지).\n"
        "반드시 아래 JSON 스키마로만 출력(선택 기사는 후보의 대괄호 id로 지정):\n"
        '{"headlines":{"자사":"...","업계":"...","경쟁사":"..."},'
        '"rows":[{"id":"tech-0","cat":"자사","insight":"기사에 적힌 사실만 요약(제언·시사점·해석 없이)"}]}\n\n'
        "뉴스 후보:\n" + newsblock)
    if not GKEY:
        raise SystemExit("ERROR: GEMINI_API_KEY 미설정")
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0.15}}
    last = ""
    for model in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-flash-latest"):
        url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s" % (model, GKEY)
        r = requests.post(url, json=body, timeout=90)
        if r.status_code != 200:
            last = "%s -> HTTP %s %s" % (model, r.status_code, r.text[:300])
            print("Gemini", last)
            continue
        j = r.json()
        if "candidates" not in j or not j["candidates"]:
            last = "%s -> no candidates: %s" % (model, json.dumps(j)[:300])
            print("Gemini", last)
            continue
        print("Gemini OK model:", model)
        txt = j["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(txt)
    raise SystemExit("ERROR: 모든 Gemini 모델 실패 - " + last)


BAN = ("해야 한다", "해야 합니다", "해야할", "해야 할", "필요하다", "필요합니다", "필요가 있다", "필요가있다",
       "공략해야", "공략할", "노려야", "대비해야", "주력해야", "확대해야", "강화해야", "삼아야",
       "강점으로 내세", "틈새 시장", "틈새시장", "기회로 삼", "전략적으로", "선점해야", "차별화해야",
       "것으로 보인다", "것으로 전망", "것으로 분석", "주목된다", "기대된다", "전망된다", "풀이된다")


def is_opinion(t, cat=None):
    """제언·해석성 표현이 있거나, 경쟁사/시장/업계 기사인데 '아카라'를 끌어들이면 훈수로 판정."""
    t = str(t or '')
    if any(b in t for b in BAN):
        return True
    if cat and cat != '자사' and '아카라' in t:
        return True
    return False


def clean_headline(t, cat=None):
    """헤드라인에서 훈수 절(콤마 단위) 제거. 남는 게 없으면 원문 유지."""
    t = str(t or '').strip()
    if not is_opinion(t, cat):
        return t
    keep = [c.strip() for c in re.split(r',\s*', t) if not is_opinion(c.strip(), cat)]
    out = ', '.join(keep).strip().strip(',').strip()
    return out if len(out) >= 8 else t


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
        cat = p.get("cat", "시장")
        raw = (p.get("insight", "") or "").strip()
        # Gemini가 훈수를 넣으면 통째로 버리고 기사 원문 설명(스니펫)으로 대체
        ins = raw if not is_opinion(raw, cat) else ((it.get("snippet") or "").strip() or raw)
        rows.append({"cat": cat, "s": it["source"], "t": it["title"],
                     "d": it["date"], "ins": ins, "link": it["link"]})
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    day = kst.strftime("%Y-%m-%d")
    hl = res.get("headlines", {}) or {}
    hl = {k: clean_headline(v, k) for k, v in hl.items()}
    today = {"headlines": hl, "rows": rows}

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
