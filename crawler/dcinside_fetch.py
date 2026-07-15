# -*- coding: utf-8 -*-
"""DCInside 홈어시스턴트(hass)·스마트싱스(smartthings) 갤러리에서 '아카라' 언급 글 수집 → web/dcinside.json
   ※ 공개 API가 없어 HTML 스크래핑. 봇 차단·구조 변경에 취약(best-effort).
   GitHub Actions 주기 실행. 키 불필요."""
import os, re, json, html, time, datetime
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Referer": "https://gall.dcinside.com/"}
GALS = [{"id": "hass", "name": "홈어시스턴트 갤러리"}, {"id": "smartthings", "name": "스마트싱스 갤러리"}]
KW = "아카라"


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def fetch_gallery(gid):
    posts = []
    for page in range(1, 4):
        url = ("https://gall.dcinside.com/mgallery/board/lists/?id=%s"
               "&s_type=search_subject_memo&s_keyword=%s&page=%d" % (gid, requests.utils.quote(KW), page))
        try:
            r = requests.get(url, headers=UA, timeout=15)
            t = r.text
        except Exception:
            break
        # 게시글 행 파싱: 제목 링크
        rows = re.findall(r'gall_tit[^>]*>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', t, re.S)
        found = 0
        for href, title_html in rows:
            title = clean(title_html)
            if not title or ("아카라" not in title and "aqara" not in title.lower()):
                continue
            link = href if href.startswith("http") else ("https://gall.dcinside.com" + href)
            # 날짜/조회/댓글은 행 단위로 못 묶으면 생략(제목·링크 우선)
            posts.append({"gid": gid, "title": title, "link": link, "date": "", "views": 0, "replies": 0})
            found += 1
        if found == 0:
            break
        time.sleep(0.5)
    # 링크 기준 중복 제거
    seen, uniq = set(), []
    for p in posts:
        if p["link"] in seen:
            continue
        seen.add(p["link"])
        uniq.append(p)
    return uniq


def main():
    all_posts = []
    for g in GALS:
        try:
            ps = fetch_gallery(g["id"])
            all_posts.extend(ps)
            print("  %s: %d건" % (g["name"], len(ps)))
        except Exception as e:
            print("  %s 실패: %s" % (g["name"], e))
        time.sleep(1)
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    data = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "keyword": KW, "count": len(all_posts),
            "note": "DCInside hass·smartthings 갤러리 아카라 언급(제목·메모 검색). 봇 차단으로 수집이 불안정할 수 있음.",
            "posts": all_posts}
    path = os.path.join(os.path.dirname(__file__), "..", "dcinside.json")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("dcinside.json OK — %d건" % len(all_posts))


if __name__ == "__main__":
    main()
