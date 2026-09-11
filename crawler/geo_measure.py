# -*- coding: utf-8 -*-
"""
GEO 자동 측정 — geo_measure.json 갱신
=====================================
진단 프롬프트 35개를 매달 자동으로 돌려, AI 답변에 아카라가 나오는지 기록한다.
사람이 답변을 붙여넣지 않아도 되는 몫을 여기서 처리한다.

측정 엔진 2가지
  gemini  Gemini + 구글 검색 그라운딩. 답변 본문과 groundingMetadata(근거 URL)를 같이 받는다.
          → 실제 '검색형 AI 답변'에 우리가 인용되는지를 그대로 본다. GEMINI_API_KEY 필요.
  search  네이버 검색(뉴스·블로그·웹) 결과에 우리 문서가 들어가는지.
          → 국내 검색 근거 후보. NAVER_ID/NAVER_SECRET 있으면 함께 측정한다.

키가 없으면 그 엔진만 건너뛴다(실패로 처리하지 않음).
결과는 geo_measure.json의 runs에 이어 붙이고, 같은 달·같은 질문·같은 엔진이 이미 있으면
그 회차는 남겨 둔 채 새 회차를 추가한다(반복 측정이 쌓여야 노출률이 안정된다).
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
HERE = os.path.dirname(__file__)
SEED = os.path.join(HERE, '..', 'geo_seed.json')
OUT = os.path.join(HERE, '..', 'geo_measure.json')
KEEP_MONTHS = 6                      # 오래된 달은 파일에서 덜어낸다

OURS = ['aqaralife.kr', 'aqaralife.shop', 'catalogue.aqara.kr', 'aqaralife.gitbook.io', 'aqara.kr']
COMPET = ['삼성', '스마트싱스', 'SmartThings', 'LG', '씽큐', '샤오미', 'Xiaomi', '헤이홈',
          '구글 홈', 'Google Home', '애플 홈', 'HomeKit', '필립스', 'Hue', '이케아', 'Tuya',
          'TP-Link', 'Tapo', '다원', '시하스']
MODELS = ['gemini-2.5-flash', 'gemini-2.0-flash']


def load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def post_json(url, payload, headers=None, timeout=60):
    data = json.dumps(payload).encode('utf-8')
    h = {'Content-Type': 'application/json'}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def get_json(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def domain_of(u):
    m = re.match(r'^https?://([^/]+)', str(u or ''))
    return m.group(1).lower() if m else ''


def analyze(text, cites):
    """답변 텍스트와 근거 URL에서 언급·경쟁사·순위를 뽑는다."""
    t = text or ''
    mention = 1 if re.search(r'아카라|aqara', t, re.I) else 0
    comp = sorted({c for c in COMPET if re.search(re.escape(c), t, re.I)})
    rank = 0
    if mention:
        # 브랜드가 몇 번째로 등장하는지 — 다른 브랜드보다 앞이면 1
        pos = [(re.search(r'아카라|aqara', t, re.I).start(), 'aqara')]
        for c in comp:
            m = re.search(re.escape(c), t, re.I)
            if m:
                pos.append((m.start(), c))
        pos.sort()
        rank = [i for i, (_p, n) in enumerate(pos, 1) if n == 'aqara'][0]
    return mention, comp, rank


GEMINI_DIAG = []          # 왜 실패했는지 결과 파일에 남긴다(추정하지 않기 위해)


def run_gemini(prompt, key):
    """Gemini + 구글 검색 그라운딩. 근거 URL은 groundingMetadata에서 뽑는다.
       도구 이름이 모델 세대마다 달라서(google_search / google_search_retrieval) 둘 다 시도한다."""
    for model in MODELS:
      for tool in ({'google_search': {}}, {'google_search_retrieval': {}}):
        url = ('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s'
               % (model, key))
        payload = {
            'contents': [{'parts': [{'text': prompt}]}],
            'tools': [tool],
            'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 1200},
        }
        try:
            d = post_json(url, payload)
        except Exception as e:
            msg = '%s/%s %s' % (model, list(tool)[0], e)
            body = ''
            try:
                body = e.read().decode('utf-8', 'ignore')[:200]      # HTTPError 본문에 이유가 들어 있다
            except Exception:
                pass
            print('   ! %s %s' % (msg, body))
            if len(GEMINI_DIAG) < 4:
                GEMINI_DIAG.append(msg + ' ' + body)
            continue
        cand = (d.get('candidates') or [{}])[0]
        text = ''.join(p.get('text', '') for p in ((cand.get('content') or {}).get('parts') or []))
        cites, seen = [], set()
        gm = cand.get('groundingMetadata') or {}
        for ch in (gm.get('groundingChunks') or []):
            w = ch.get('web') or {}
            uri, title = w.get('uri', ''), w.get('title', '')
            # 그라운딩 URI는 리디렉션 주소라 실제 도메인이 title에 담겨 온다
            dom = title if ('.' in title and ' ' not in title) else domain_of(uri)
            key2 = (dom or uri)
            if not key2 or key2 in seen:
                continue
            seen.add(key2)
            cites.append({'url': uri, 'domain': dom})
        if text.strip():
            return text, cites, model
    return '', [], ''


def run_naver(query, cid, csec):
    """네이버 웹·블로그 검색 결과를 근거 후보로 본다."""
    cites, texts = [], []
    for kind in ('webkr', 'blog'):
        url = ('https://openapi.naver.com/v1/search/%s.json?query=%s&display=5'
               % (kind, urllib.parse.quote(query)))
        try:
            d = get_json(url, {'X-Naver-Client-Id': cid, 'X-Naver-Client-Secret': csec})
        except Exception as e:
            print('   ! naver %s %s' % (kind, e))
            continue
        for it in (d.get('items') or []):
            link = it.get('link', '')
            texts.append(re.sub(r'<[^>]+>', '', (it.get('title', '') + ' ' + it.get('description', ''))))
            cites.append({'url': link, 'domain': domain_of(link)})
        time.sleep(1.5)                      # 네이버 검색 API 버스트 제한
    return ' '.join(texts), cites


def main():
    now = datetime.now(KST)
    ym = now.strftime('%Y-%m')
    seed = load_json(SEED, {})
    prompts = seed.get('prompts') or []
    if not prompts:
        print('geo_seed.json에서 프롬프트를 읽지 못했습니다'); return 1

    out = load_json(OUT, {'runs': []})
    runs = out.get('runs') or []

    gkey = (os.environ.get('GEMINI_API_KEY') or '').strip()
    ncid = (os.environ.get('NAVER_ID') or '').strip()
    nsec = (os.environ.get('NAVER_SECRET') or '').strip()
    if not gkey and not (ncid and nsec):
        print('GEMINI_API_KEY도 NAVER_ID/SECRET도 없습니다 — 측정하지 않고 종료'); return 0

    added = 0
    for p in prompts:
        q = p.get('q', '')
        if not q:
            continue
        print('· %s %s' % (p.get('id'), q[:30]))

        if gkey:
            text, cites, model = run_gemini(q, gkey)
            if text:
                mention, comp, rank = analyze(text, cites)
                runs.append({'ym': ym, 'pid': p['id'], 'eng': 'gemini', 'q': q,
                             'ts': int(now.timestamp() * 1000), 'by': '자동(' + model + ')',
                             'mention': mention, 'rank': rank, 'cites': cites[:8], 'comp': comp,
                             'err': 0, 'errNote': '', 'senti': 'neu',
                             'raw': re.sub(r'\s+', ' ', text)[:600]})
                added += 1
            time.sleep(1.5)

        if ncid and nsec:
            text, cites = run_naver(q, ncid, nsec)
            if cites:
                joined = text + ' ' + ' '.join(c['url'] for c in cites)
                mention, comp, rank = analyze(joined, cites)
                # 검색 결과는 우리 도메인이 들어 있으면 언급으로 본다
                if any(any(o in c['domain'] for o in OURS) for c in cites):
                    mention = 1
                runs.append({'ym': ym, 'pid': p['id'], 'eng': 'search', 'q': q,
                             'ts': int(now.timestamp() * 1000), 'by': '자동(네이버 검색)',
                             'mention': mention, 'rank': rank, 'cites': cites[:8], 'comp': comp,
                             'err': 0, 'errNote': '', 'senti': 'neu', 'raw': ''})
                added += 1

    # 오래된 달 정리
    keep = {(now - timedelta(days=31 * i)).strftime('%Y-%m') for i in range(KEEP_MONTHS)}
    runs = [r for r in runs if r.get('ym') in keep or r.get('ym') == ym]

    gem_n = len([r for r in runs if r.get('ym') == ym and r.get('eng') == 'gemini'])
    out.update({'generatedAt': now.isoformat(timespec='seconds'),
                'note': out.get('note') or '진단 프롬프트 자동 측정 결과',
                'engines': sorted({r.get('eng') for r in runs if r.get('ym') == ym}),
                'diag': ({'gemini': '이번 달 Gemini 측정 0건 — ' + ' / '.join(GEMINI_DIAG)}
                         if (gkey and not gem_n) else {}),
                'runs': runs})
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('완료 — %d건 추가 / 전체 %d건' % (added, len(runs)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
