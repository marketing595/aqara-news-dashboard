# -*- coding: utf-8 -*-
"""
TASKS 하루 두 번 요약 알림 — 구글챗 마케팅팀 방
==============================================
매일 오전 8시 / 오후 12시 30분(KST)에 지난 알림 이후 바뀐 것만 모아서 보낸다.
  · 새로 추가된 업무 (행의 ts)
  · 완료된 업무 (행의 dts)
  · 사람별 이번 주 진행률
바뀐 게 없으면 오전에만 '남은 일' 브리핑을 보내고, 낮에는 조용히 넘어간다.

읽고 쓰는 곳 — Firebase Realtime Database REST
  tasks/p_<이름>/w/<월요일>/<칸>/<id>   업무
  tasks/_chat                           알림 방식(digest/live/off) — off면 아무것도 안 보냄
  tasks/_digest/last                    마지막으로 보낸 시각(ms) — 이 이후 것만 모은다

필요한 GitHub Secrets
  CHAT_WEBHOOK        구글챗 스페이스 웹훅 URL
  FIREBASE_DB_SECRET  Firebase 콘솔 → 프로젝트 설정 → 서비스 계정 → 데이터베이스 비밀번호(레거시)
   또는 FIREBASE_SA   서비스 계정 JSON 전체(레거시 비밀번호를 못 쓰는 경우. google-auth 필요)
둘 다 없으면 아무 일도 하지 않고 끝난다(실패로 처리하지 않음).
"""
import json, os, sys, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
DB = 'https://aqara-weekly-1227c-default-rtdb.asia-southeast1.firebasedatabase.app'
PEOPLE = ['강유선', '정여진', '홍수영']
FIELDS = [('done', '이번 주 진행 · 성과'), ('plan', '다음 주 계획'),
          ('issue', '이슈 · 공유'), ('check', '확인 필요 사항')]
DASH = 'https://aqara-news-dashboard.vercel.app/'
AVATAR = DASH + 'favicon-192.png'


def _auth_param():
    """REST 호출에 붙일 인증 쿼리스트링. 없으면 None."""
    sec = (os.environ.get('FIREBASE_DB_SECRET') or '').strip()
    if sec:
        return 'auth=' + sec
    sa = (os.environ.get('FIREBASE_SA') or '').strip()
    if sa:
        try:
            from google.oauth2 import service_account          # pip install google-auth
            from google.auth.transport.requests import Request
            info = json.loads(sa)
            cred = service_account.Credentials.from_service_account_info(
                info, scopes=['https://www.googleapis.com/auth/firebase.database',
                              'https://www.googleapis.com/auth/userinfo.email'])
            cred.refresh(Request())
            return 'access_token=' + cred.token
        except Exception as e:
            print('서비스 계정으로 토큰을 만들지 못했습니다:', e)
    return None


def db_get(path, auth):
    # 사람 칸 키에 한글이 들어가므로(p_홍수영) 반드시 URL 인코딩해야 한다
    url = '%s/%s.json?%s' % (DB, urllib.parse.quote(path, safe='/'), auth)
    req = urllib.request.Request(url, headers={'User-Agent': 'aqara-tasks-digest'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8') or 'null')


def db_put(path, value, auth):
    url = '%s/%s.json?%s' % (DB, urllib.parse.quote(path, safe='/'), auth)
    req = urllib.request.Request(url, data=json.dumps(value).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'}, method='PUT')
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def monday(d):
    return (d - timedelta(days=d.weekday())).strftime('%Y-%m-%d')


def week_label(mon):
    m = datetime.strptime(mon, '%Y-%m-%d')
    f = m + timedelta(days=4)
    dow = '월화수목금토일'
    return '%d/%d(%s) ~ %d/%d(%s)' % (m.month, m.day, dow[m.weekday()], f.month, f.day, dow[f.weekday()])


def rows_of(node, fk):
    out = []
    for rid, it in (((node or {}).get(fk)) or {}).items():
        if not isinstance(it, dict):
            continue
        t = str(it.get('t') or '').strip()
        if not t:
            continue
        out.append({'id': rid, 't': t, 'c': bool(it.get('c')), 'w': it.get('w') or '',
                    'ts': int(it.get('ts') or 0), 'dts': int(it.get('dts') or 0),
                    'by': it.get('by') or ''})
    return out


def post_chat(hook, text, card, thread):
    payload = {'cardsV2': [{'cardId': 'aqara-tasks-digest', 'card': {
        'header': {'title': card['title'], 'subtitle': card['subtitle'],
                   'imageUrl': AVATAR, 'imageType': 'CIRCLE'},
        'sections': [{'widgets': [
            {'decoratedText': {'text': card['body'], 'wrapText': True}},
            {'buttonList': {'buttons': [{'text': '대시보드 열기',
                                         'onClick': {'openLink': {'url': DASH}}}]}},
        ]}]}}]}
    if thread:
        payload['thread'] = {'threadKey': thread}
    url = hook + ('&' if '?' in hook else '?') + 'messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD'

    def send(body):
        req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'),
                                     headers={'Content-Type': 'application/json; charset=UTF-8'})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    try:
        return send(payload)
    except urllib.error.HTTPError as e:
        print('카드 전송 실패(%s) → 텍스트로 재시도' % e.code)
        body = {'text': text}
        if thread:
            body['thread'] = {'threadKey': thread}
        return send(body)


def main():
    hook = (os.environ.get('CHAT_WEBHOOK') or '').strip()
    auth = _auth_param()
    if not hook:
        print('CHAT_WEBHOOK 미설정 — 보내지 않고 종료'); return 0
    if not auth:
        print('FIREBASE_DB_SECRET / FIREBASE_SA 미설정 — 보내지 않고 종료'); return 0

    now = datetime.now(KST)
    slot = '오전' if now.hour < 11 else '낮'
    try:
        mode = db_get('tasks/_chat', auth) or 'digest'
    except Exception as e:
        print('설정을 읽지 못했습니다:', e); return 0
    if mode == 'off':
        print('알림 꺼짐(tasks/_chat=off) — 종료'); return 0

    last = 0
    try:
        last = int(db_get('tasks/_digest/last', auth) or 0)
    except Exception:
        last = 0
    if not last:                                   # 처음 도는 경우 24시간 전부터
        last = int((now - timedelta(hours=24)).timestamp() * 1000)

    mon = monday(now)
    added, doneList, prog, nodes = [], [], [], {}
    for name in PEOPLE:
        try:
            node = db_get('tasks/p_%s/w/%s' % (name, mon), auth) or {}
        except Exception as e:
            print('%s 읽기 실패: %s' % (name, e)); node = {}
        nodes[name] = node
        n = d = 0
        for fk, flabel in FIELDS:
            for r in rows_of(node, fk):
                n += 1
                if r['c']:
                    d += 1
                if r['ts'] > last:
                    added.append((name, flabel, r['t'], r['by']))
                if r['c'] and r['dts'] > last:
                    doneList.append((name, flabel, r['t']))
        prog.append((name, d, n))

    open_items = []
    if slot == '오전':
        for name in PEOPLE:
            node = nodes.get(name) or {}
            for fk, flabel in FIELDS:
                if fk == 'plan':
                    continue                        # 다음 주 계획은 오늘 할 일이 아니므로 뺀다
                for r in rows_of(node, fk):
                    if not r['c']:
                        open_items.append((name, r['t']))

    if not added and not doneList and not (slot == '오전' and open_items):
        print('바뀐 내용 없음 — 보내지 않음')
        db_put('tasks/_digest/last', int(now.timestamp() * 1000), auth)
        return 0

    lines = []
    if added:
        lines.append('<b>새로 추가된 업무 %d건</b>' % len(added))
        for name, flabel, t, by in added[:15]:
            who = ('%s님이 등록' % by) if (by and by != name) else ''
            lines.append('· <b>%s</b> — %s <font color="#8E8E93">(%s%s)</font>'
                         % (name, t, flabel, (' · ' + who) if who else ''))
        if len(added) > 15:
            lines.append('· 외 %d건' % (len(added) - 15))
    if doneList:
        if lines:
            lines.append('')
        lines.append('<b>완료 %d건</b>' % len(doneList))
        for name, flabel, t in doneList[:10]:
            lines.append('· <b>%s</b> — %s' % (name, t))
        if len(doneList) > 10:
            lines.append('· 외 %d건' % (len(doneList) - 10))
    if slot == '오전' and open_items:
        if lines:
            lines.append('')
        lines.append('<b>아직 남은 일 %d건</b>' % len(open_items))
        for name, t in open_items[:12]:
            lines.append('· <b>%s</b> — %s' % (name, t))
        if len(open_items) > 12:
            lines.append('· 외 %d건' % (len(open_items) - 12))
    if lines:
        lines.append('')
    lines.append('<b>이번 주 진행</b>  ' + ' · '.join('%s %d/%d' % (n, d, t) for n, d, t in prog))

    body = '\n'.join(lines)
    title = '🗒 TASKS %s 요약' % slot
    subtitle = '%s · %d/%d %s' % (week_label(mon), now.month, now.day,
                                  now.strftime('%H:%M'))
    plain = '%s (%s)\n%s\n%s' % (title, subtitle,
                                 body.replace('<b>', '').replace('</b>', '')
                                     .replace('<font color="#8E8E93">', '').replace('</font>', ''),
                                 DASH)

    st = post_chat(hook, plain, {'title': title, 'subtitle': subtitle, 'body': body},
                   'tasks-' + mon)
    print('구글챗 전송 %s — 추가 %d · 완료 %d · 남은 일 %d'
          % (st, len(added), len(doneList), len(open_items)))
    db_put('tasks/_digest/last', int(now.timestamp() * 1000), auth)
    return 0


if __name__ == '__main__':
    sys.exit(main())
