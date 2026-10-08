# -*- coding: utf-8 -*-
"""
GEO 자동 측정 (데일리) — geo_measure/<YYYY-MM>.json + geo_daily.json 갱신
======================================================================
진단 프롬프트 35개를 매일 AI 엔진에 그대로 물어, 답변에 아카라가 나오는지·무엇을 근거로 인용하는지 기록한다.
전부 '검색(그라운딩) 켠 상태'로 묻는다 — 검색이 꺼진 답은 근거 URL이 없어 측정에 쓸 수 없다.

엔진 (키가 없으면 그 엔진만 건너뛰고 geo_daily.json engines[]에 이유를 남긴다)
  gemini   Gemini + Google 검색 그라운딩                GEMINI_API_KEY
  chatgpt  OpenAI Responses API + web_search 도구        OPENAI_API_KEY      (모델: OPENAI_MODEL)
  ppx      Perplexity Sonar (항상 검색)                  PERPLEXITY_API_KEY  (모델: PPX_MODEL, 기본 sonar)
  claude   Claude Messages API + web_search 서버 도구    ANTHROPIC_API_KEY   (모델: CLAUDE_MODEL)
  search   네이버 웹·블로그 검색 결과(근거 후보)          NAVER_ID / NAVER_SECRET

저장
  geo_measure/<YYYY-MM>.json  그 달의 회차 전부 {ym, runs:[{date, pid, eng, mention, rank, comp, cites, raw, ...}]}
  geo_daily.json              날짜 × 엔진 요약(n·언급·자사 인용, 브랜드 질문 제외분 따로) + 엔진 상태
  같은 날 다시 돌리면 회차가 더 쌓인다(반복 측정이 많을수록 노출률이 안정된다).
  예전 geo_measure.json(월 단위 단일 파일)은 첫 실행에서 월 파일로 옮기고 지운다.
"""
import glob, json, os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
SEED = os.path.join(ROOT, 'geo_seed.json')
LEGACY = os.path.join(ROOT, 'geo_measure.json')
MDIR = os.path.join(ROOT, 'geo_measure')
DAILY = os.path.join(ROOT, 'geo_daily.json')
KEEP_MONTHS = 12
RAW_MAX = 800                     # 답변 원문은 앞부분만 남긴다(월 파일 크기 관리)

OURS = ['aqaralife.kr', 'aqaralife.shop', 'catalogue.aqara.kr', 'aqaralife.gitbook.io', 'aqara.kr',
        'blog.naver.com/aqaralife', 'blog.naver.com/sksmsehfehfdl', 'blog.naver.com/untorn',
        'blog.naver.com/gogetthat']
COMPET = ['삼성', '스마트싱스', 'SmartThings', 'LG', '씽큐', '샤오미', 'Xiaomi', '헤이홈',
          '구글 홈', 'Google Home', '애플 홈', 'HomeKit', '필립스', 'Hue', '이케아', 'Tuya',
          'TP-Link', 'Tapo', '다원', '시하스']
KR_LOC = {'type': 'approximate', 'country': 'KR', 'timezone': 'Asia/Seoul'}


# ---------------------------------------------------------------- 공통
def load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj, indent=None):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent, separators=(',', ':') if indent is None else None)


def http(url, payload=None, headers=None, timeout=120):
    h = {'Content-Type': 'application/json'} if payload is not None else {}
    h.update(headers or {})
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def err_text(e):
    body = ''
    try:
        body = e.read().decode('utf-8', 'ignore')[:300]      # HTTPError 본문에 이유가 들어 있다
    except Exception:
        pass
    return ('%s %s' % (e, body)).strip()


def domain_of(u):
    m = re.match(r'^https?://([^/]+)', str(u or ''))
    return m.group(1).lower() if m else ''


def cite(url, title=''):
    url = str(url or '')
    dom = domain_of(url)
    if 'grounding-api-redirect' in url:                  # Gemini 리디렉션 주소 — 실제 도메인은 title에
        dom = title if ('.' in title and ' ' not in title) else dom
        url = ''
    return {'url': url[:300], 'domain': dom}


def dedupe(cites, limit=10):
    out, seen = [], set()
    for c in cites:
        k = c.get('url') or c.get('domain')
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out[:limit]


def analyze(text):
    """답변 텍스트에서 언급·경쟁사·순위를 뽑는다."""
    t = text or ''
    m0 = re.search(r'아카라|aqara', t, re.I)
    comp = sorted({c for c in COMPET if re.search(re.escape(c), t, re.I)})
    rank = 0
    if m0:
        pos = [(m0.start(), 'aqara')]
        for c in comp:
            m = re.search(re.escape(c), t, re.I)
            if m:
                pos.append((m.start(), c))
        pos.sort()
        rank = [i for i, (_p, n) in enumerate(pos, 1) if n == 'aqara'][0]
    return (1 if m0 else 0), comp, rank


def is_ours(c):
    s = ((c.get('url') or '') + ' ' + (c.get('domain') or '')).lower()
    return any(o in s for o in OURS)


# ---------------------------------------------------------------- 엔진
class Engine:
    key = ''
    label = ''

    def __init__(self):
        self.model = ''
        self.status = 'ok'
        self.errors = []

    def note(self, msg):
        print('   ! [%s] %s' % (self.key, msg[:300]))
        if len(self.errors) < 3:
            self.errors.append(msg[:300])

    def ask(self, q):          # → (text, cites)
        raise NotImplementedError


class Gemini(Engine):
    key, label = 'gemini', 'Gemini'

    def __init__(self, k):
        super().__init__()
        self.k = k
        self.models = self.discover()

    def discover(self):
        """구형 모델이 내려가면 404가 난다(2026-10 실측: 2.5/2.0-flash 종료). 목록에서 최신 flash를 고른다."""
        names = []
        try:
            url = 'https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key=' + self.k
            for m in http(url, timeout=30).get('models', []):
                n = m.get('name', '').replace('models/', '')
                if 'generateContent' not in (m.get('supportedGenerationMethods') or []):
                    continue
                if re.fullmatch(r'gemini-\d+(\.\d+)?-flash', n):
                    names.append(n)
        except Exception as e:
            self.note('모델 목록 조회 실패 ' + err_text(e))
        ver = lambda n: float(re.search(r'gemini-(\d+(?:\.\d+)?)', n).group(1))
        names.sort(key=ver, reverse=True)
        env = (os.environ.get('GEMINI_MODEL') or '').strip()
        return ([env] if env else []) + names + ['gemini-flash-latest']

    def ask(self, q):
        for model in self.models:
            url = ('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s'
                   % (model, self.k))
            payload = {'contents': [{'parts': [{'text': q}]}], 'tools': [{'google_search': {}}]}
            try:
                d = http(url, payload)
            except Exception as e:
                self.note('%s %s' % (model, err_text(e)))
                if getattr(e, 'code', 0) in (400, 403, 404):
                    self.models = [m for m in self.models if m != model] or self.models
                continue
            cand = (d.get('candidates') or [{}])[0]
            text = ''.join(p.get('text', '') for p in ((cand.get('content') or {}).get('parts') or []))
            gm = cand.get('groundingMetadata') or {}
            cites = [cite((ch.get('web') or {}).get('uri'), (ch.get('web') or {}).get('title', ''))
                     for ch in (gm.get('groundingChunks') or [])]
            if text.strip():
                self.model = model
                return text, cites
        return '', []


class ChatGPT(Engine):
    key, label = 'chatgpt', 'ChatGPT'

    def __init__(self, k):
        super().__init__()
        self.k = k
        self.models = self.discover()
        self.tool = 'web_search'

    def discover(self):
        env = (os.environ.get('OPENAI_MODEL') or '').strip()
        found = []
        try:
            d = http('https://api.openai.com/v1/models', headers={'Authorization': 'Bearer ' + self.k}, timeout=30)
            for m in d.get('data', []):
                mid = m.get('id', '')
                mm = re.fullmatch(r'gpt-(\d+(?:\.\d+)?)(-mini)?', mid)
                if mm:
                    found.append((float(mm.group(1)), 1 if mm.group(2) else 0, mid))
        except Exception as e:
            self.note('모델 목록 조회 실패 ' + err_text(e))
        found.sort(reverse=True)          # 최신 버전 우선, 같은 버전이면 mini(비용) 우선
        return ([env] if env else []) + [f[2] for f in found] + ['gpt-5-mini', 'gpt-4.1-mini']

    def ask(self, q):
        for model in list(self.models):
            for tool in ([self.tool] + [t for t in ('web_search', 'web_search_preview') if t != self.tool]):
                payload = {'model': model, 'input': q,
                           'tools': [{'type': tool, 'user_location': KR_LOC}]}
                try:
                    d = http('https://api.openai.com/v1/responses', payload,
                             {'Authorization': 'Bearer ' + self.k}, timeout=180)
                except Exception as e:
                    self.note('%s/%s %s' % (model, tool, err_text(e)))
                    continue
                text, cites = '', []
                for item in d.get('output') or []:
                    if item.get('type') != 'message':
                        continue
                    for c in item.get('content') or []:
                        if c.get('type') == 'output_text':
                            text += c.get('text', '')
                            for a in c.get('annotations') or []:
                                if a.get('type') == 'url_citation':
                                    cites.append(cite(a.get('url'), a.get('title', '')))
                if text.strip():
                    self.model, self.tool = model, tool
                    self.models = [model] + [m for m in self.models if m != model]
                    return text, cites
            self.models = [m for m in self.models if m != model] or self.models
        return '', []


class Perplexity(Engine):
    key, label = 'ppx', 'Perplexity'

    def __init__(self, k):
        super().__init__()
        self.k = k
        self.model = (os.environ.get('PPX_MODEL') or 'sonar').strip()
        self.loc = True

    def ask(self, q):
        for attempt in range(2):
            payload = {'model': self.model, 'messages': [{'role': 'user', 'content': q}]}
            if self.loc:
                payload['web_search_options'] = {'user_location': {'country': 'KR'}}
            try:
                d = http('https://api.perplexity.ai/chat/completions', payload,
                         {'Authorization': 'Bearer ' + self.k}, timeout=180)
            except Exception as e:
                self.note(err_text(e))
                if getattr(e, 'code', 0) == 400 and self.loc:
                    self.loc = False           # 위치 옵션을 못 받는 모델이면 빼고 다시
                    continue
                return '', []
            text = (((d.get('choices') or [{}])[0].get('message') or {}).get('content') or '')
            cites = [cite(r.get('url'), r.get('title', '')) for r in (d.get('search_results') or [])]
            if not cites:
                cites = [cite(u) for u in (d.get('citations') or []) if isinstance(u, str)]
            return text, cites
        return '', []


class Claude(Engine):
    key, label = 'claude', 'Claude'

    def __init__(self, k):
        super().__init__()
        import anthropic                      # 워크플로에서 pip install anthropic
        self.client = anthropic.Anthropic(api_key=k)
        self.model = (os.environ.get('CLAUDE_MODEL') or 'claude-opus-5-5').strip()

    def ask(self, q):
        tools = [{'type': 'web_search_20260209', 'name': 'web_search', 'max_uses': 3, 'user_location': KR_LOC}]
        messages = [{'role': 'user', 'content': q}]
        text, cites = '', []
        try:
            for _ in range(3):                # pause_turn이면 이어서 한 번 더 보낸다
                resp = self.client.beta.messages.create(
                    model=self.model, max_tokens=16000,
                    output_config={'effort': 'low'},
                    tools=tools, messages=messages,
                    betas=['server-side-fallback-2026-07-01'],
                    extra_body={'fallbacks': 'default'},
                )
                if resp.stop_reason == 'refusal':
                    self.note('refusal %s' % (getattr(resp, 'stop_details', None),))
                    return '', []
                for b in resp.content:
                    if b.type == 'text':
                        text += b.text
                        for c in (getattr(b, 'citations', None) or []):
                            u = getattr(c, 'url', None)
                            if u:
                                cites.append(cite(u, getattr(c, 'title', '') or ''))
                    # web_search_tool_result(검색만 하고 안 쓴 문서)는 세지 않는다 — 답변 인용만 근거로 본다
                if resp.stop_reason != 'pause_turn':
                    break
                messages = [messages[0], {'role': 'assistant', 'content': resp.content}]
        except Exception as e:
            self.note('%s %s' % (type(e).__name__, str(e)[:250]))
            return '', []
        return text, cites


class NaverSearch(Engine):
    key, label = 'search', '네이버 검색'

    def __init__(self, cid, csec):
        super().__init__()
        self.cid, self.csec = cid, csec
        self.model = 'naver-openapi'

    def ask(self, q):
        cites, texts = [], []
        for kind in ('webkr', 'blog'):
            url = ('https://openapi.naver.com/v1/search/%s.json?query=%s&display=5'
                   % (kind, urllib.parse.quote(q)))
            try:
                d = http(url, headers={'X-Naver-Client-Id': self.cid, 'X-Naver-Client-Secret': self.csec}, timeout=30)
            except Exception as e:
                self.note('%s %s' % (kind, err_text(e)))
                continue
            for it in (d.get('items') or []):
                texts.append(re.sub(r'<[^>]+>', '', it.get('title', '') + ' ' + it.get('description', '')))
                cites.append(cite(it.get('link', '')))
            time.sleep(1.5)                      # 네이버 검색 API 버스트 제한
        return ' '.join(texts), cites


# ---------------------------------------------------------------- 저장
def month_path(ym):
    return os.path.join(MDIR, ym + '.json')


def load_month(ym):
    return load_json(month_path(ym), {'ym': ym, 'runs': []})


def run_date(r):
    if r.get('date'):
        return r['date']
    try:
        return datetime.fromtimestamp(int(r.get('ts', 0)) / 1000, KST).strftime('%Y-%m-%d')
    except Exception:
        return (r.get('ym') or '0000-00') + '-01'


def migrate_legacy():
    """예전 geo_measure.json(단일 파일) → 월 파일. 한 번만."""
    if not os.path.exists(LEGACY):
        return
    old = load_json(LEGACY, {}).get('runs') or []
    by = {}
    for r in old:
        r['date'] = run_date(r)
        r['ym'] = r['date'][:7]
        by.setdefault(r['ym'], []).append(r)
    for ym, rs in by.items():
        m = load_month(ym)
        have = {(x.get('pid'), x.get('eng'), x.get('ts')) for x in m['runs']}
        m['runs'].extend(x for x in rs if (x.get('pid'), x.get('eng'), x.get('ts')) not in have)
        save_json(month_path(ym), m)
    os.remove(LEGACY)
    print('예전 geo_measure.json %d건을 월 파일로 옮겼습니다' % len(old))


def build_daily(prompts, engines_state, now):
    branded = {p['id'] for p in prompts if p.get('type') == 'branded'}
    days = {}
    for path in sorted(glob.glob(os.path.join(MDIR, '*.json'))):
        for r in load_json(path, {}).get('runs') or []:
            d = days.setdefault(run_date(r), {}).setdefault(r.get('eng', '?'),
                                                             {'n': 0, 'men': 0, 'cited': 0, 'gn': 0, 'gmen': 0})
            men = 1 if int(r.get('mention') or 0) == 1 else 0
            d['n'] += 1
            d['men'] += men
            d['cited'] += 1 if any(is_ours(c) for c in (r.get('cites') or [])) else 0
            if r.get('pid') not in branded:          # 브랜드 질문은 당연히 나오므로 따로 센다
                d['gn'] += 1
                d['gmen'] += men
    prev = load_json(DAILY, {})
    eng = prev.get('engines') or {}
    eng.update(engines_state)
    save_json(DAILY, {'generatedAt': now.isoformat(timespec='seconds'),
                      'note': '날짜 × 엔진 요약. n=측정 회차, men=아카라 언급, cited=자사 문서 인용, gn/gmen=브랜드 질문 제외',
                      'engines': eng, 'days': dict(sorted(days.items()))}, indent=1)


# ---------------------------------------------------------------- 실행
def main():
    now = datetime.now(KST)
    today, ym = now.strftime('%Y-%m-%d'), now.strftime('%Y-%m')
    os.makedirs(MDIR, exist_ok=True)
    migrate_legacy()

    prompts = [p for p in (load_json(SEED, {}).get('prompts') or []) if p.get('q')]
    if not prompts:
        print('geo_seed.json에서 프롬프트를 읽지 못했습니다'); return 1

    env = lambda k: (os.environ.get(k) or '').strip()
    want = [s.strip() for s in env('GEO_ENGINES').split(',') if s.strip()]     # 일부만 돌리고 싶을 때
    plan = [('gemini', 'GEMINI_API_KEY', lambda: Gemini(env('GEMINI_API_KEY'))),
            ('chatgpt', 'OPENAI_API_KEY', lambda: ChatGPT(env('OPENAI_API_KEY'))),
            ('ppx', 'PERPLEXITY_API_KEY', lambda: Perplexity(env('PERPLEXITY_API_KEY'))),
            ('claude', 'ANTHROPIC_API_KEY', lambda: Claude(env('ANTHROPIC_API_KEY'))),
            ('search', 'NAVER_ID', lambda: NaverSearch(env('NAVER_ID'), env('NAVER_SECRET')))]
    engines, state = [], {}
    for key, secret, make in plan:
        if want and key not in want:
            continue
        if not env(secret) or (key == 'search' and not env('NAVER_SECRET')):
            state[key] = {'status': 'nokey', 'secret': secret, 'at': today,
                          'msg': 'GitHub Secret %s 미등록 — 이 엔진은 측정하지 않음' % secret}
            continue
        try:
            engines.append(make())
        except Exception as e:
            state[key] = {'status': 'error', 'at': today, 'msg': '%s %s' % (type(e).__name__, e)}

    def work(e):
        out = []
        for p in prompts:
            ts = int(time.time() * 1000)
            text, cites = e.ask(p['q'])
            if not text.strip() and not cites:
                continue
            cites = dedupe(cites)
            mention, comp, rank = analyze(text)
            if e.key == 'search':
                mention = 1 if (mention or any(is_ours(c) for c in cites)) else 0
            out.append({'date': today, 'ym': ym, 'pid': p['id'], 'eng': e.key, 'ts': ts,
                        'by': '자동(%s)' % (e.model or e.label), 'model': e.model,
                        'mention': mention, 'rank': rank, 'comp': comp, 'cites': cites,
                        'err': 0, 'errNote': '', 'senti': 'neu',
                        'raw': re.sub(r'\s+', ' ', text).strip()[:RAW_MAX] if e.key != 'search' else ''})
            print('· %-8s %s %s' % (e.key, p['id'], '언급' if mention else '-'))
            time.sleep(1)
        return e, out

    runs = []
    with ThreadPoolExecutor(max_workers=max(1, len(engines))) as ex:
        for e, out in ex.map(work, engines):
            runs.extend(out)
            st = 'ok' if out else 'error'
            state[e.key] = {'status': st, 'model': e.model, 'at': today, 'n': len(out),
                            'msg': '' if out else ('측정 0건 — ' + ' / '.join(e.errors)),
                            'warn': ' / '.join(e.errors) if (out and e.errors) else ''}

    m = load_month(ym)
    m['runs'].extend(runs)
    m['updatedAt'] = now.isoformat(timespec='seconds')
    save_json(month_path(ym), m)

    keep = {(now.replace(day=1) - timedelta(days=31 * i)).strftime('%Y-%m') for i in range(KEEP_MONTHS)}
    for path in glob.glob(os.path.join(MDIR, '*.json')):
        if os.path.basename(path)[:7] not in keep:
            os.remove(path)

    build_daily(prompts, state, now)
    print('완료 — 오늘 %d건 추가 (%s)' % (len(runs), ', '.join('%s:%s' % (k, v['status']) for k, v in state.items())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
