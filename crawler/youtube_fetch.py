# -*- coding: utf-8 -*-
"""L100 캠페인 인플루언서 유튜브 영상 실측 → web/youtube.json
   조회수·좋아요·댓글수 + 댓글 감성(긍/중/부) + 언급 키워드 + 제품 관련 대표 댓글.
   GitHub Actions에서 매일 실행 → 커밋 → Vercel 자동 반영. 키: 환경변수 YT_API_KEY."""
import os, re, json, html, datetime
import requests

KEY = os.environ.get("YT_API_KEY", "")
VIDEOS = [
    {"id": "URJrux1lc-M", "n": "동네친구강나미", "t": "매크로"},
    {"id": "xH8VY4g3YeI", "n": "30대의삶",     "t": "매크로"},
    {"id": "m3f8bUOgx7w", "n": "김한용의모카",  "t": "매크로"},
    {"id": "F1Nmnm8f4UY", "n": "지니스펙트럼",  "t": "매크로"},
    {"id": "F3BkofA6J_A", "n": "리뷰닉",       "t": "마이크로"},
    {"id": "JhPSS1RTRYk", "n": "판다리뷰",      "t": "마이크로"},
    {"id": "SBs2sUJncpo", "n": "앱준",         "t": "마이크로"},
]
API = "https://www.googleapis.com/youtube/v3/"

POS = re.compile(r"좋|최고|대박|굿|감사|예쁘|이쁘|멋지|유용|도움|사고싶|갖고싶|편하|만족|추천|깔끔|신기|와우|기대|응원|귀엽|사랑|👍|❤|🥰|😍|기능|필요|설치")
NEG = re.compile(r"별로|비싸|아쉽|실망|안좋|불편|문제|오류|최악|그닥|뒷광고|짜증|버벅|먹통|후회|화나|별루|글쎄|사기|과장|ㅠ|ㅜ")
PROD = re.compile(r"도어락|아카라|L100|스마트홈|무타공|테슬라|홈킷|구글홈|허브|설치|잠금|현관|비밀번호|지문|매터|재실|커튼|조명|가격|디자인|기능|제품|카메라")
PROMO = re.compile(r"할인|공식몰|프로모션|구독자.{0,4}위한|이벤트 기간|광고주|혜택|aqaralife|http")
OFFTOPIC = set("디스크 허리 수술 주사 통증 병원 재활 강남 승리 로건 침대 운동 스트레칭 쇼파 방사 요추".split())
STOP = set(("그냥 진짜 정말 너무 이거 저거 근데 그리고 하는 있는 저는 저도 제가 나도 영상 그거 이제 요즘 하고 보고 같아요 있어요 네요 어요 아요 에서 합니다 하네요 이런 저런 그런 으로 인데 는데 스마트 아카라 완전 약간 조금 많이 때문 하지만 지금 오늘 정도 사람 우리 저희 그때 " ).split())
JOSA = re.compile(r"(이에요|예요|입니다|이라고|이라는|이라|이나|으로|에서|까지|부터|에게|한테|처럼|보다|마다|이야|하고|이랑|랑|은|는|이|가|을|를|에|의|도|로|과|와|만|요)$")


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def main():
    ids = ",".join(v["id"] for v in VIDEOS)
    stat = {}
    try:
        r = requests.get(API + "videos", params={"part": "statistics,snippet", "id": ids, "key": KEY}, timeout=25)
        for it in r.json().get("items", []):
            stat[it["id"]] = it
    except Exception as e:
        print("stat err", e); return

    videos, freq, prod_comments = [], {}, []
    for v in VIDEOS:
        st = stat.get(v["id"], {}).get("statistics", {})
        p = n = g = 0
        page = ""
        for _ in range(3):
            try:
                params = {"part": "snippet", "videoId": v["id"], "maxResults": 100,
                          "order": "relevance", "textFormat": "plainText", "key": KEY}
                if page:
                    params["pageToken"] = page
                cr = requests.get(API + "commentThreads", params=params, timeout=20).json()
            except Exception:
                break
            for c in cr.get("items", []):
                sn = c["snippet"]["topLevelComment"]["snippet"]
                t = re.sub(r"\s+", " ", clean(sn.get("textDisplay"))).strip()
                lk = int(sn.get("likeCount", 0))
                hp, hn = bool(POS.search(t)), bool(NEG.search(t))
                if hp and not hn:
                    p += 1
                elif hn and not hp:
                    g += 1
                else:
                    n += 1
                for w in re.split(r"[^0-9A-Za-z가-힣]+", t):
                    if len(w) < 2:
                        continue
                    w = JOSA.sub("", w)
                    if len(w) < 2 or w in STOP:
                        continue
                    freq[w] = freq.get(w, 0) + 1
                if PROD.search(t) and not PROMO.search(t) and lk >= 3:
                    prod_comments.append({"v": v["n"], "l": lk, "t": t[:140]})
            page = cr.get("nextPageToken", "")
            if not page:
                break
        videos.append({"n": v["n"], "t": v["t"], "id": v["id"],
                       "title": clean(stat.get(v["id"], {}).get("snippet", {}).get("title", "")),
                       "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                       "comments": int(st.get("commentCount", 0)), "pos": p, "neu": n, "neg": g})

    kw = sorted(freq.items(), key=lambda x: -x[1])
    kw = [[w, c, ("e" if w in OFFTOPIC else "p")] for w, c in kw if c >= 4][:13]
    prod_comments.sort(key=lambda x: -x["l"])
    top = prod_comments[:5]

    kst = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")
    data = {"ok": True, "generatedAt": kst, "videos": videos, "keywords": kw, "topComments": top}
    path = os.path.join(os.path.dirname(__file__), "..", "youtube.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("wrote", len(videos), "videos,", len(kw), "keywords,", len(top), "comments")


if __name__ == "__main__":
    main()
