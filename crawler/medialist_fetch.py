# -*- coding: utf-8 -*-
"""미디어리스트 발굴 → web/medialist.json
   분야 키워드(부동산·인테리어·스마트홈·AI·경쟁사 등)로 네이버 뉴스를 수집하고,
   각 기사 본문에서 기자명·이메일을 정규식으로 추출해 매체별 담당 기자 연락처를 만든다.
   ※ 이메일은 기사 하단 바이라인에 공개된 경우에만 자동 수집(개인정보 아님).
   GitHub Actions 주기 실행. 키: NAVER_ID/NAVER_SECRET."""
import os, re, json, html, time, datetime
import requests

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
H = {"X-Naver-Client-Id": NID, "X-Naver-Client-Secret": NSEC}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

DOMAIN = {"mt.co.kr": "머니투데이", "heraldcorp.com": "헤럴드경제", "sedaily.com": "서울경제", "hankyung.com": "한국경제",
          "etnews.com": "전자신문", "mk.co.kr": "매일경제", "dt.co.kr": "디지털타임스", "yna.co.kr": "연합뉴스",
          "asiae.co.kr": "아시아경제", "zdnet.co.kr": "지디넷코리아", "inews24.com": "아이뉴스24", "newsis.com": "뉴시스",
          "edaily.co.kr": "이데일리", "fnnews.com": "파이낸셜뉴스", "chosun.com": "조선일보", "donga.com": "동아일보",
          "joongang.co.kr": "중앙일보", "hani.co.kr": "한겨레", "khan.co.kr": "경향신문", "seoul.co.kr": "서울신문",
          "kmib.co.kr": "국민일보", "segye.com": "세계일보", "munhwa.com": "문화일보", "hankookilbo.com": "한국일보",
          "biz.chosun.com": "조선비즈", "newspim.com": "뉴스핌", "ajunews.com": "아주경제", "ceoscoredaily.com": "CEO스코어데일리",
          "housing-herald.co.kr": "하우징헤럴드", "rensunion.com": "리모델링신문", "kukinews.com": "쿠키뉴스",
          "digitaltoday.co.kr": "디지털투데이", "itdaily.kr": "아이티데일리", "aitimes.com": "AI타임스", "dealsite.co.kr": "딜사이트"}

# 분야 키워드 → beat 분류
KEYWORDS = [
    ("부동산", "부동산"), ("아파트 분양", "부동산"), ("재건축 재개발", "부동산"), ("빌트인 가전", "부동산"),
    ("인테리어", "인테리어"), ("리모델링", "인테리어"), ("홈스타일링", "인테리어"),
    ("스마트홈", "스마트홈"), ("스마트홈 인테리어", "스마트홈"), ("스마트도어락", "스마트홈"),
    ("AI홈", "AI"), ("AI 인테리어", "AI"), ("인공지능 가전", "AI"), ("AI 스마트홈", "AI"),
    ("삼성 스마트싱스", "경쟁사"), ("LG 씽큐", "경쟁사"), ("매터 스마트홈", "IT"),
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
NAME_RE = re.compile(r"([가-힣]{2,4})\s*기자")
BAD_EMAIL = re.compile(r"(example|sentry|@2x|png|jpg|gif|@media|no-?reply)", re.I)


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def press_of(url):
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    h = m.group(1) if m else ""
    for d, name in DOMAIN.items():
        if h.endswith(d):
            return name
    return h


def extract_reporter(url):
    """기사 HTML에서 기자명·이메일 best-effort 추출."""
    try:
        r = requests.get(url, headers=UA, timeout=8)
        t = r.text
    except Exception:
        return None, None
    email = None
    for e in EMAIL_RE.findall(t):
        if not BAD_EMAIL.search(e) and len(e) < 40:
            email = e
            break
    nm = NAME_RE.search(t)
    name = nm.group(1) if nm else None
    # 이메일 로컬파트가 한글 이름과 무관해도 그대로 사용(바이라인 우선)
    return name, email


def main():
    if not NID or not NSEC:
        raise SystemExit("ERROR: NAVER_ID/NAVER_SECRET 미설정")
    contacts = {}   # key=(press,name,email) → dict
    for kw, beat in KEYWORDS:
        try:
            r = requests.get("https://openapi.naver.com/v1/search/news.json",
                             params={"query": kw, "display": 30, "sort": "date"}, headers=H, timeout=15).json()
        except Exception as e:
            print("news 실패", kw, e); continue
        for it in (r.get("items") or [])[:18]:
            link = it.get("originallink") or it.get("link")
            press = press_of(link)
            name, email = extract_reporter(link)
            if not name and not email:
                continue
            key = (press, name or "", email or "")
            dt = ""
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(it.get("pubDate")).strftime("%Y-%m-%d")
            except Exception:
                pass
            if key not in contacts:
                contacts[key] = {"beat": beat, "press": press, "reporter": name or "", "email": email or "",
                                 "title": clean(it.get("title")), "link": link, "date": dt, "beats": set([beat])}
            else:
                contacts[key]["beats"].add(beat)
            time.sleep(0.15)
        time.sleep(0.5)
    # 정리: 이메일 있는 것 우선, beat별 정렬
    out = []
    for c in contacts.values():
        c["beats"] = sorted(c["beats"])
        out.append(c)
    out.sort(key=lambda x: (0 if x["email"] else 1, x["beat"], x["press"]))
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    data = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"),
            "keywords": [k for k, _ in KEYWORDS],
            "note": "네이버 뉴스 분야 키워드 수집 후 기사 바이라인에서 기자명·이메일 자동추출(공개된 경우). 참고용이며 최신 연락처는 매체에 확인 권장.",
            "contacts": out}
    path = os.path.join(os.path.dirname(__file__), "..", "medialist.json")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("medialist.json OK — 연락처 %d건(이메일 %d건)" % (len(out), sum(1 for c in out if c["email"])))


if __name__ == "__main__":
    main()
