# -*- coding: utf-8 -*-
"""
GEO(생성형 엔진 최적화) 현황 수집기 — geo.json 생성
=====================================================
'AI가 우리 콘텐츠를 읽을 수 있는가 / 읽고 인용할 만한 형태인가'를 매일 자동 점검한다.

1) 채널별 AI 크롤러 접근 정책   robots.txt를 파싱해 GPTBot·ClaudeBot·PerplexityBot 등이 차단됐는지 확인
2) 자사 홈페이지 페이지별 GEO 점검  title·description·H1·구조화데이터(JSON-LD)·본문량
3) 사이트 기본기                robots.txt / sitemap.xml / llms.txt 유무와 형식

수집만 하고 판단(점수 가중치·개선 액션)은 대시보드에서 한다.
GitHub Actions에서 매일 실행 → geo.json 커밋.
"""
import json, os, re, sys, time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin
import urllib.request

KST = timezone(timedelta(hours=9))
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')

# 생성형 엔진이 쓰는 크롤러들 — 차단되면 그 채널 콘텐츠는 AI 답변에 인용되지 못한다
BOTS = ['GPTBot', 'OAI-SearchBot', 'ChatGPT-User', 'PerplexityBot',
        'ClaudeBot', 'Claude-SearchBot', 'Google-Extended', 'CCBot',
        'meta-externalagent', 'Applebot-Extended']

# 우리가 다루는 채널 (own=우리가 직접 고칠 수 있는 것)
CHANNELS = [
    {'key': 'home',      'label': '자사 홈페이지',   'host': 'www.aqaralife.kr',  'own': True,  'area': '홈페이지'},
    {'key': 'shop',      'label': '자사몰',          'host': 'aqaralife.shop',    'own': True,  'area': '홈페이지'},
    {'key': 'catalogue', 'label': '제품 카탈로그',    'host': 'catalogue.aqara.kr','own': True,  'area': '홈페이지'},
    {'key': 'nblog',     'label': '네이버 블로그',    'host': 'blog.naver.com',    'own': False, 'area': '온드미디어'},
    {'key': 'youtube',   'label': '유튜브',          'host': 'www.youtube.com',   'own': False, 'area': '온드미디어'},
    {'key': 'instagram', 'label': '인스타그램',       'host': 'www.instagram.com', 'own': False, 'area': '온드미디어'},
    {'key': 'nnews',     'label': '네이버 뉴스',      'host': 'n.news.naver.com',  'own': False, 'area': 'PR'},
]

# PR 원문이 실리는 주요 매체 — 매체 사이트가 AI를 막으면 그 기사는 AI 답변에 못 쓰인다
MEDIA = [
    ('etnews.com', '전자신문'), ('www.mt.co.kr', '머니투데이'), ('www.mk.co.kr', '매일경제'),
    ('www.hankyung.com', '한국경제'), ('www.edaily.co.kr', '이데일리'), ('biz.chosun.com', '조선비즈'),
    ('zdnet.co.kr', 'ZDNet코리아'), ('www.boannews.com', '보안뉴스'), ('www.dt.co.kr', '디지털타임스'),
    ('it.chosun.com', 'IT조선'), ('www.newsis.com', '뉴시스'), ('www.yna.co.kr', '연합뉴스'),
]

# 자사 홈페이지에서 GEO가 중요한 페이지들
PAGES = [
    ('홈',             '/',                 'home'),
    ('회사소개',        '/about',            'home'),
    ('아카라라이프',     '/aqaralife',        'home'),
    ('스마트홈',        '/smarthome',        'home'),
    ('스마트홈 바이블',  '/smarthome-bible',  'content'),
    ('블로그',          '/blog',             'content'),
    ('뉴스룸',          '/newsroom',         'content'),
    ('뉴스레터',        '/newsletter',       'content'),
    ('도어락',          '/door-lock',        'product'),
    ('센서',            '/sensor',           'product'),
    ('허브·카메라',      '/hub-camera',       'product'),
    ('조명',            '/lightings',        'product'),
    ('스위치·패드',      '/switch-pad',       'product'),
    ('블라인드',         '/shadings',         'product'),
    ('시공 서비스',      '/si_service',       'convert'),
    ('도입 사례',        '/case',             'convert'),
    ('기업(B2B)',       '/Enterprise',       'convert'),
    ('인테리어 문의',    '/inrequest',        'convert'),
    ('파트너십',        '/partnership',      'convert'),
]

BASE = 'https://www.aqaralife.kr'
# 콘텐츠형 구조화 데이터 — AI가 '무슨 글인지' 이해하는 데 쓰인다(쇼핑몰 배송·반품 스키마는 제외)
CONTENT_LD = {'Article', 'NewsArticle', 'BlogPosting', 'Product', 'FAQPage', 'HowTo',
              'Organization', 'BreadcrumbList', 'WebPage', 'ItemList', 'VideoObject'}


def get(url, timeout=25):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, raw.decode('utf-8', 'ignore')


def safe_get(url, timeout=25):
    try:
        return get(url, timeout)
    except Exception as e:
        print('  ! %s — %s' % (url, e))
        return 0, ''


def robots_policy(host):
    """robots.txt를 읽어 봇별로 전면차단(Disallow: /)인지 판정."""
    st, txt = safe_get('https://%s/robots.txt' % host, 15)
    out = {'status': st, 'blocked': [], 'partial': [], 'sitemaps': [], 'has': bool(txt.strip()) and st == 200}
    if not out['has']:
        return out
    groups, cur, last_ua = {}, [], False
    for line in txt.splitlines():
        line = line.split('#')[0].strip()
        if not line:
            continue
        if ':' not in line:
            continue
        k, v = line.split(':', 1)
        k, v = k.strip().lower(), v.strip()
        if k == 'user-agent':
            # User-agent가 여러 줄 연달아 오면 한 그룹(같은 규칙)이다
            cur = (cur + [v.lower()]) if last_ua else [v.lower()]
            last_ua = True
            groups.setdefault(v.lower(), [])
            continue
        last_ua = False
        if k == 'sitemap':
            out['sitemaps'].append(v)
        elif k in ('disallow', 'allow') and cur:
            for c in cur:
                groups.setdefault(c, []).append((k, v))
    for b in BOTS:
        rules = groups.get(b.lower())
        if rules is None:
            continue                       # 개별 규칙 없음 = 전체(*) 규칙을 따름
        if any(k == 'disallow' and v == '/' for k, v in rules):
            out['blocked'].append(b)
        elif any(k == 'disallow' and v for k, v in rules):
            out['partial'].append(b)
    return out


TAG_RE = re.compile(r'<(script|style)[^>]*>.*?</\1>', re.S | re.I)


def audit_page(label, path, kind):
    url = urljoin(BASE, path)
    st, html = safe_get(url)
    if not html:
        return {'label': label, 'path': path, 'kind': kind, 'url': url, 'status': st, 'ok': False}
    title = ''
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.S | re.I)
    if m:
        title = re.sub(r'\s+', ' ', m.group(1)).strip()
    desc = ''
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.S | re.I)
    if m:
        desc = re.sub(r'\s+', ' ', m.group(1)).strip()
    canon = ''
    m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\'](.*?)["\']', html, re.I)
    if m:
        canon = m.group(1).strip()
    h1 = len(re.findall(r'<h1[\s>]', html, re.I))
    h2 = len(re.findall(r'<h2[\s>]', html, re.I))
    ld = sorted(set(re.findall(r'"@type"\s*:\s*"([A-Za-z]+)"', html)))
    body = TAG_RE.sub(' ', html)
    body = re.sub(r'<[^>]+>', ' ', body)
    body = re.sub(r'\s+', ' ', body).strip()
    return {'label': label, 'path': path, 'kind': kind, 'url': url, 'status': st, 'ok': True,
            'title': title[:160], 'desc': desc[:300], 'descLen': len(desc),
            'h1': h1, 'h2': h2, 'ld': ld,
            'contentLd': sorted(set(ld) & CONTENT_LD), 'chars': len(body),
            'canonical': canon}


def main():
    now = datetime.now(KST)
    data = {'generatedAt': now.isoformat(timespec='seconds'), 'bots': BOTS,
            'channels': [], 'media': [], 'pages': [], 'site': {}}

    print('1) 채널별 AI 크롤러 정책')
    for ch in CHANNELS:
        pol = robots_policy(ch['host'])
        row = dict(ch); row.update({'blocked': pol['blocked'], 'partial': pol['partial'],
                                    'robots': pol['has'], 'status': pol['status']})
        data['channels'].append(row)
        print('   %-22s 차단 %s' % (ch['host'], ','.join(pol['blocked']) or '없음'))
        time.sleep(0.4)

    print('2) 언론사 AI 크롤러 정책')
    for host, label in MEDIA:
        pol = robots_policy(host)
        data['media'].append({'host': host, 'label': label, 'blocked': pol['blocked'],
                              'partial': pol['partial'], 'robots': pol['has']})
        print('   %-20s 차단 %s' % (host, ','.join(pol['blocked']) or '없음'))
        time.sleep(0.4)

    print('3) 자사 홈페이지 기본기')
    st, robots_txt = safe_get(BASE + '/robots.txt', 15)
    st_l, llms = safe_get(BASE + '/llms.txt', 15)
    st_s, sm = safe_get(BASE + '/sitemap.xml', 25)
    locs = re.findall(r'<loc>\s*([^<]+?)\s*</loc>', sm or '')
    # 표준 llms.txt는 '# 제목' 으로 시작하는 마크다운. robots 문법이면 규격 밖.
    llms_kind = 'none'
    if st_l == 200 and llms.strip():
        llms_kind = 'markdown' if llms.lstrip().startswith('#') else 'nonstandard'
    data['site'] = {
        'robots': st == 200, 'robotsSitemapHttp': ('Sitemap: http://' in (robots_txt or '')),
        'llms': llms_kind, 'llmsBody': (llms or '')[:400],
        'sitemap': st_s == 200, 'sitemapUrls': len(locs),
        'sitemapHasPosts': any(('bmode=view' in u or 'idx=' in u) for u in locs),
        'sitemapHttp': sum(1 for u in locs if u.startswith('http://')),
    }
    print('   robots=%s llms=%s sitemap=%d건' % (data['site']['robots'], llms_kind, len(locs)))

    print('4) 게시판 글 수 (AI가 읽을 수 있는 우리 글)')
    boards = {}
    for key, path_ in (('blogPosts', '/blog'), ('newsroomPosts', '/newsroom')):
        _st, html = safe_get(BASE + path_)
        boards[key] = len(set(re.findall(r'idx=(\d{4,})', html or '')))
        time.sleep(0.4)
    boards['note'] = '게시판 1페이지 기준 · 글 상세 링크(idx) 개수'
    data['boards'] = boards
    print('   블로그 %d · 뉴스룸 %d' % (boards['blogPosts'], boards['newsroomPosts']))

    print('5) 페이지별 GEO 점검')
    for label, path, kind in PAGES:
        p = audit_page(label, path, kind)
        data['pages'].append(p)
        if p.get('ok'):
            print('   %-14s title=%d desc=%d h1=%d ld=%s' %
                  (label, len(p['title']), p['descLen'], p['h1'], ','.join(p['contentLd']) or '-'))
        time.sleep(0.4)

    path = os.path.join(os.path.dirname(__file__), '..', 'geo.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print('완료 — geo.json (%d페이지 / %d채널 / %d매체)'
          % (len(data['pages']), len(data['channels']), len(data['media'])))


if __name__ == '__main__':
    sys.exit(main())
