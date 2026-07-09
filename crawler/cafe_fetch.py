# -*- coding: utf-8 -*-
"""아카라 스마트홈 카페(cafe.naver.com/aqara) 최신 글을 네이버 카페글 검색 API로 수집해
   web/cafe.json 으로 저장. GitHub Actions에서 매시간 실행 → 커밋 → Vercel 자동 반영."""
import os, re, json, html, datetime
import requests

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
KWS = ['아카라','아카라 도어락','아카라 허브','아카라 카메라','아카라 재실센서','아카라 스위치',
       '아카라 조명','아카라 커튼','M100','M200','FP300','L100','K100','매터','스마트싱스 아카라']
H = {'X-Naver-Client-Id': NID, 'X-Naver-Client-Secret': NSEC}

def clean(s):
    s = re.sub(r'<[^>]+>', '', s or '')
    return html.unescape(s).strip()

def main():
    seen, out = {}, []
    for q in KWS:
        try:
            r = requests.get('https://openapi.naver.com/v1/search/cafearticle.json',
                             params={'display': 30, 'sort': 'date', 'query': q}, headers=H, timeout=15)
            items = r.json().get('items', [])
        except Exception as e:
            print('err', q, e); continue
        for it in items:
            if 'aqara' not in (it.get('cafeurl') or ''):
                continue
            link = it.get('link', '')
            if not link or link in seen:
                continue
            seen[link] = True
            m = re.search(r'/aqara/(\d+)', link)
            out.append({'no': int(m.group(1)) if m else 0,
                        'title': clean(it.get('title')),
                        'desc': clean(it.get('description')),
                        'link': link})
    out.sort(key=lambda x: x['no'], reverse=True)
    out = out[:50]
    data = {'ok': True,
            'generatedAt': datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M') + ' UTC',
            'count': len(out), 'posts': out}
    path = os.path.join(os.path.dirname(__file__), '..', 'cafe.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print('wrote', len(out), 'posts')

if __name__ == '__main__':
    main()
