# -*- coding: utf-8 -*-
"""아카라 스마트홈 카페(cafe.naver.com/aqara) 최신 글을 네이버 카페글 검색 API로 수집해
   web/cafe.json 으로 저장. GitHub Actions에서 매시간 실행 → 커밋 → Vercel 자동 반영."""
import os, re, json, html, datetime
import requests

NID = os.environ.get("NAVER_ID", "")
NSEC = os.environ.get("NAVER_SECRET", "")
KWS = ('아카라,아카라 도어락,아카라 허브,아카라 카메라,아카라 센서,아카라 재실센서,아카라 스위치,'
       '아카라 조명,아카라 커튼,아카라 앱,아카라 허브 m3,아카라 fp2,아카라 g2h,아카라 전동커튼,'
       '아카라 스마트홈,아카라 홈킷,아카라 구글홈,아카라 스마트싱스,아카라 매터,아카라 온습도,'
       '아카라 콘센트,아카라 모션센서,아카라 초인종,아카라 도어벨,M100,M200,M3,FP300,FP2,L100,'
       'K100,P100,G100,G4,W100,E1,T1,H2,U200,아카라 후기,아카라 설치,아카라 연동,아카라 오류').split(',')
H = {'X-Naver-Client-Id': NID, 'X-Naver-Client-Secret': NSEC}

def clean(s):
    s = re.sub(r'<[^>]+>', '', s or '')
    return html.unescape(s).strip()

def main():
    seen, out = {}, []
    for q in KWS:
        for start in (1, 101, 201, 301):
            try:
                r = requests.get('https://openapi.naver.com/v1/search/cafearticle.json',
                                 params={'display': 100, 'start': start, 'sort': 'date', 'query': q},
                                 headers=H, timeout=15)
                items = r.json().get('items', [])
            except Exception as e:
                print('err', q, e); break
            if not items:
                break
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
    data = {'ok': True,
            'generatedAt': datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M') + ' UTC',
            'count': len(out), 'posts': out}
    path = os.path.join(os.path.dirname(__file__), '..', 'cafe.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print('wrote', len(out), 'posts')

if __name__ == '__main__':
    main()
