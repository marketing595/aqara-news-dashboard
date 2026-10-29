// 세미나 RSVP(참석 확인) — 개인별 링크 /r/<토큰> 으로 참석·불참·동행인 수정
// ※ 파일명이 _로 시작해 독립 함수가 아니다(Vercel Hobby 함수 12개 제한). middleware가 /api/rsvp → /api/db?rsvp=1 로 넘기고 db.js가 이 모듈을 부른다.
// ------------------------------------------------------------------
// · 개인정보(이름·연락처·이메일)는 아래 "저장소" 설명대로 비공개 경로에 암호화해서 저장한다.
//   (처음엔 customerDb + FIREBASE_DB_SECRET였으나 그 키가 Firebase에서 거부돼 2026-10-29 변경)
// · 손님(로그인 없음): 토큰을 아는 사람만 그 그룹 1건을 읽고 저장할 수 있다. 목록 조회는 불가.
//   토큰은 추측 불가능한 무작위 12자. middleware 예외에 api/rsvp·rsvp.html·r/ 를 넣어 로그인 없이 열린다.
// · 관리자(@aqara.kr 세션): 명단 가져오기·전체 목록·수정·삭제·응답 마감.
//
// GET  /api/rsvp?op=get&t=TOKEN                       손님: 내 그룹
// POST /api/rsvp { op:'save', t, status, rep, sub, comps }   손님: 저장
// GET  /api/rsvp?op=list                               관리자: 전체(+meta)
// POST /api/rsvp { op:'import', groups:[...] }         관리자: 명단 가져오기(기존 링크 유지)
// POST /api/rsvp { op:'admin-save', t, status, rep, sub, comps, memo }
// POST /api/rsvp { op:'delete', t } / { op:'meta', closed }
const crypto = require('crypto');

const DB_URL = 'https://aqara-weekly-1227c-default-rtdb.asia-southeast1.firebasedatabase.app';
const WEB_API_KEY = 'AIzaSyAs_yQ1fgGKfRDKbkUb0lviIoJ2e00KRGA'; // 공개 키(규칙 점검용 익명 로그인에만 사용)
const DOMAIN = (process.env.ALLOWED_DOMAIN || 'aqara.kr').toLowerCase();

// 행사 정보(손님 화면 상단) — seminar.json 기준
const EVENT = {
  title: 'SMART HOME INTERIOR 2026',
  sub: '공간디자인의 새로운 표준',
  date: '2026년 11월 19일 (목) 13:00 – 17:30',
  place: '서울 코엑스 401호 세미나룸',
  addr: '서울 강남구 영동대로 513 코엑스',
  way: '2호선 삼성역과 지하로 바로 연결돼요. 차량은 코엑스 주차장을 이용해 주세요.',
  map: 'https://map.naver.com/p/search/%EC%BD%94%EC%97%91%EC%8A%A4',
};

function parseCookies(h){
  const o = {};
  (h || '').split(';').forEach(p=>{ const i=p.indexOf('='); if(i>-1) o[p.slice(0,i).trim()]=p.slice(i+1).trim(); });
  return o;
}
// db.js와 같은 방식으로 __sess 검증 → 이메일
function sessionEmail(req){
  const SECRET = process.env.SESSION_SECRET;
  const tok = parseCookies(req.headers.cookie)['__sess'] || '';
  if(!SECRET || tok.indexOf('.') < 0) return '';
  const i = tok.indexOf('.');
  const payload = tok.slice(0, i), sig = tok.slice(i+1);
  try{
    const mac = crypto.createHmac('sha256', SECRET).update(payload).digest('base64url');
    const a = Buffer.from(mac), b = Buffer.from(sig);
    if(a.length !== b.length || !crypto.timingSafeEqual(a, b)) return '';
    const p = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    if(p.exp && Math.floor(Date.now()/1000) > p.exp) return '';
    const email = String(p.email || '').toLowerCase();
    return email.endsWith('@' + DOMAIN) ? email : '';
  }catch(e){ return ''; }
}

const okTok = (s) => /^[A-Za-z0-9_-]{12}$/.test(String(s || ''));
const newTok = () => crypto.randomBytes(9).toString('base64url');   // 12자
const str = (v, n) => String(v == null ? '' : v).trim().slice(0, n || 100);
const digits = (v) => String(v || '').replace(/\D/g, '').slice(0, 15);

// ── 저장소: 암호화 + 익명 로그인 ──
// FIREBASE_DB_SECRET(관리자 키)이 유효하지 않아(2026-10-29 확인: Permission denied) 관리자 키 없이 동작하게 바꿨다.
// · 서버가 익명 로그인 토큰으로 Firebase에 접근한다(브라우저는 Firebase에 직접 붙지 않음).
// · 저장 위치는 SESSION_SECRET에서 만든 비공개 경로(rsvpx_<해시>) — 브라우저 코드·저장소 어디에도 안 나온다. 루트 목록은 익명에게 막혀 있다.
// · 그룹·이력 내용은 AES-256-GCM으로 암호화해서 넣는다. 경로를 알아내도 이름·연락처는 읽을 수 없다.
//   키 = SHA-256(SESSION_SECRET + 'rsvp'). ⚠️ SESSION_SECRET을 바꾸면 기존 RSVP 데이터를 못 읽는다(바꾸기 전 명단을 내보낼 것).
const SS = () => (process.env.SESSION_SECRET || '').trim();
const ROOT = () => 'rsvpx_' + crypto.createHmac('sha256', SS()).update('rsvp-root').digest('hex').slice(0, 24);
const KEY = () => crypto.createHash('sha256').update(SS() + 'rsvp').digest();
const gid = (t) => crypto.createHmac('sha256', SS()).update('g:' + t).digest('hex').slice(0, 20);   // 토큰도 경로에 그대로 쓰지 않는다
function enc(obj){
  const iv = crypto.randomBytes(12), c = crypto.createCipheriv('aes-256-gcm', KEY(), iv);
  const ct = Buffer.concat([c.update(JSON.stringify(obj), 'utf8'), c.final()]);
  return Buffer.concat([iv, c.getAuthTag(), ct]).toString('base64');
}
function dec(s){
  try{
    const b = Buffer.from(String(s || ''), 'base64');
    const d = crypto.createDecipheriv('aes-256-gcm', KEY(), b.subarray(0, 12));
    d.setAuthTag(b.subarray(12, 28));
    return JSON.parse(Buffer.concat([d.update(b.subarray(28)), d.final()]).toString('utf8'));
  }catch(e){ return null; }
}
let ANON = { tok: '', exp: 0 };
async function anonToken(force){
  if(!force && ANON.tok && Date.now() < ANON.exp) return ANON.tok;
  const s = await fetch(`https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=${WEB_API_KEY}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ returnSecureToken: true }),
  }).then(r => r.json());
  if(!s.idToken) throw new Error('Firebase 익명 로그인 실패');
  ANON = { tok: s.idToken, exp: Date.now() + 50 * 60 * 1000 };
  return ANON.tok;
}
async function raw(method, path, body, retried){
  const r = await fetch(`${DB_URL}/${ROOT()}/${path}.json?auth=${encodeURIComponent(await anonToken(retried))}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const t = await r.text();
  if(r.status === 401 && !retried) return raw(method, path, body, true);   // 토큰 만료 → 한 번 다시
  if(!r.ok) throw new Error(`Firebase ${r.status}: ${t.slice(0, 200)}`);
  return t ? JSON.parse(t) : null;
}
// 예전 경로 이름(groups/<t>, groups, log/<t>, meta)을 그대로 받아 암호화 저장소로 옮겨 준다
async function fb(method, path, body){
  const [kind, t] = path.split('/');
  if(kind === 'meta') return raw(method, 'meta', body);
  if(kind === 'groups'){
    if(t){
      if(method === 'GET'){ const v = await raw('GET', 'g/' + gid(t)); return v ? dec(v.c) : null; }
      if(method === 'PUT') return raw('PUT', 'g/' + gid(t), { c: enc(Object.assign({}, body, { _t: t })) });
      return raw(method, 'g/' + gid(t));
    }
    if(method === 'GET'){
      const all = (await raw('GET', 'g')) || {}, out = {};
      Object.keys(all).forEach(k => { const g = all[k] && dec(all[k].c); if(g && g._t) out[g._t] = g; });
      return out;
    }
    if(method === 'PATCH'){
      const o = {};
      Object.keys(body).forEach(k => { o[gid(k)] = { c: enc(Object.assign({}, body[k], { _t: k })) }; });
      return raw('PATCH', 'g', o);
    }
  }
  if(kind === 'log'){
    if(t && method === 'POST') return raw('POST', 'l/' + gid(t), { c: enc(body) });
    if(t) return raw(method, 'l/' + gid(t));
  }
  throw new Error('unknown path ' + path);
}
// 관리자 목록용: 그룹별 변경 이력 { 토큰: {키: 이력} }
async function logsFor(tokens){
  const all = (await raw('GET', 'l')) || {}, out = {};
  tokens.forEach(t => { const L = all[gid(t)]; if(!L) return; out[t] = {}; Object.keys(L).forEach(k => { const v = dec(L[k] && L[k].c); if(v) out[t][k] = v; }); });
  return out;
}

function cleanPerson(p){
  p = p || {};
  return { name: str(p.name, 40), title: str(p.title, 40), org: str(p.org, 80), phone: digits(p.phone) };
}
function cleanComps(a){
  return (Array.isArray(a) ? a : []).slice(0, 30).map(cleanPerson).filter(c => c.name || c.phone);
}
const STATUSES = ['pending', 'yes', 'no'];

// 손님이 고를 수 있는 동행인 = 처음 명단(orig) + 지금 명단(담당자가 추가한 사람). 손님은 새 사람을 추가할 수 없다(2026-10-29 사용자 지정).
// 예외: '이름 미기재' 자리는 손님이 이름을 적을 수 있다. 적은 뒤엔 comp.from 에 원래 자리 이름(이름 미기재 N)을 남겨 같은 자리로 추적한다.
const isPH = (n) => /미기재|미정/.test(String(n || ''));
function allowedComps(g){
  const m = {};
  String((g.orig && g.orig.comps) || '').split(', ').map(s => s.trim()).filter(Boolean)
    .forEach(n => { m[n] = { name: n, title: '', org: g.rep.org || '', phone: '' }; });
  (g.comps || []).forEach(c => { if(c && c.name) m[c.name] = c; });
  (g.comps || []).forEach(c => { if(c && c.from && c.from !== c.name) delete m[c.from]; });   // 이름을 적은 자리는 원래 자리 이름으로 따로 안 보이게
  return m;
}
// 손님에게 돌려줄 값 — 이메일·메모·원본은 빼고. removed = 명단에 있었지만 지금 빠진 동행인(되돌리기용)
function guestView(g, meta){
  const now = (g.comps || []).map(c => c.name);
  return {
    ok: true, event: EVENT, closed: !!(meta && meta.closed),
    rep: { name: g.rep.name, title: g.rep.title || '', org: g.rep.org || '', phone: g.rep.phone || '' },
    sub: g.sub || null, comps: g.comps || [], status: g.status || 'pending',
    removed: Object.keys(allowedComps(g)).filter(n => !now.includes(n)),
    updatedAt: g.updatedAt || 0, answered: !!g.answeredAt,
  };
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');   // 개인정보 → 캐시 금지
  res.setHeader('X-Robots-Tag', 'noindex');
  const body = req.body || {};
  const op = String((req.method === 'GET' ? req.query.op : body.op) || '');
  try{
    if(!SS()) return res.status(200).json({ ok: false, error: "서버 설정이 끝나지 않았어요(SESSION_SECRET)." });

    // ── 손님 ──
    if(op === 'get' || op === 'save'){
      const t = req.method === 'GET' ? req.query.t : body.t;
      if(!okTok(t)) return res.status(200).json({ ok: false, error: 'link' });
      const g = await fb('GET', `groups/${t}`);
      if(!g || !g.rep) return res.status(200).json({ ok: false, error: 'link' });
      const meta = (await fb('GET', 'meta')) || {};
      if(op === 'get') return res.status(200).json(guestView(g, meta));

      if(req.method !== 'POST') return res.status(405).json({ ok: false });
      if(meta.closed) return res.status(200).json({ ok: false, error: '응답이 마감되었어요. 변경이 필요하면 담당자에게 연락해 주세요.' });
      const status = STATUSES.includes(body.status) && body.status !== 'pending' ? body.status : '';
      if(!status) return res.status(200).json({ ok: false, error: '참석 여부를 선택해 주세요.' });
      // 손님이 바꿀 수 있는 것: 참석 여부, 본인 연락처, 동행인 빼기/되돌리기와 동행인 연락처. 이름·소속·대리 참석은 담당자만.
      const rep = cleanPerson(body.rep);
      const allow = allowedComps(g), seen = {};
      // 이름 미기재 자리: 처음 명단의 미기재 이름 + 이미 이름을 적은 자리(from)
      const phs = {};
      Object.keys(allow).forEach(n => { if(isPH(n)) phs[n] = { name: n, title: '', org: g.rep.org || '', phone: '' }; });
      (g.comps || []).forEach(c => { if(c && c.from) phs[c.from] = c; });
      const comps = [];
      (Array.isArray(body.comps) ? body.comps : []).slice(0, 30).forEach(x => {
        const nm = str(x && x.name, 40), from = str(x && x.from, 40), phone = digits(x && x.phone);
        if(from && phs[from]){
          if(seen[from]) return; seen[from] = 1;
          const c = Object.assign({}, phs[from], { name: nm || from, phone });
          if(c.name === from) delete c.from; else c.from = from;
          comps.push(c);
        }else if(nm && allow[nm] && !seen[nm]){
          seen[nm] = 1; comps.push(Object.assign({}, allow[nm], { phone }));
        }
      });
      const sub = g.sub || null;
      const now = Date.now();
      const next = Object.assign({}, g, {
        status, rep: Object.assign({}, g.rep, { phone: rep.phone }),
        sub, comps, updatedAt: now, updatedBy: 'guest', answeredAt: now,
      });
      await fb('PUT', `groups/${t}`, next);
      await fb('POST', `log/${t}`, { at: now, by: 'guest', status, n: (status === 'yes' ? 1 + comps.length : 0), sub: sub ? sub.name : '', comps: comps.map(c => c.name).join(', ') });
      return res.status(200).json(guestView(next, meta));
    }

    // ── 관리자 ──
    const email = sessionEmail(req);
    if(!email) return res.status(401).json({ ok: false, error: '@' + DOMAIN + ' 로그인이 필요합니다.' });

    if(op === 'list'){
      const [groups, meta] = await Promise.all([fb("GET", "groups"), fb("GET", "meta")]);
      const log = await logsFor(Object.keys(groups || {}));
      return res.status(200).json({ ok: true, email, groups: groups || {}, meta: meta || {}, log: log || {}, locked: true });
    }
    if(req.method !== 'POST') return res.status(405).json({ ok: false });

    if(op === 'import'){
      const incoming = (Array.isArray(body.groups) ? body.groups : []).slice(0, 3000);
      const cur = (await fb('GET', 'groups')) || {};
      const byKey = {};
      Object.keys(cur).forEach(t => { if(cur[t] && cur[t].key) byKey[cur[t].key] = t; });
      const patch = {}, seen = {}; let added = 0, refreshed = 0, kept = 0;
      const now = Date.now();
      for(const x of incoming){
        const rep = cleanPerson(x.rep);
        if(!rep.name) continue;
        const email2 = str(x.email, 120).toLowerCase();
        let key = rep.phone ? 'p' + rep.phone : (email2 ? 'e' + email2 : 'n' + (rep.name + '|' + rep.org).replace(/[.#$\[\]\/]/g, ''));
        // 같은 파일 안에서 연락처가 겹치면(대표번호 공유 등) 이름을 붙여 따로 둔다
        if(seen[key]) key += '|' + rep.name.replace(/[.#$\[\]\/]/g, '') + '|' + seen[key];
        seen[key.split('|')[0]] = (seen[key.split('|')[0]] || 0) + 1;
        const comps = cleanComps(x.comps);
        const base = { key, email: email2, route: str(x.route, 80), vip: !!x.vip, note: str(x.note, 300), orig: { n: 1 + comps.length, comps: comps.map(c => c.name).join(', ') } };
        const t = byKey[key];
        if(t){
          const g = cur[t];
          if(!g) continue;
          if(g.answeredAt || g.updatedBy){ kept++; continue; }   // 이미 손님/담당자가 손댄 그룹은 그대로 둔다
          patch[t] = Object.assign({}, g, base, { rep, comps });
          refreshed++;
        }else{
          let nt = newTok(); while(cur[nt] || patch[nt]) nt = newTok();
          patch[nt] = Object.assign(base, { rep, comps, sub: null, status: 'pending', created: now, updatedAt: 0 });
          byKey[key] = nt; added++;
        }
      }
      if(Object.keys(patch).length) await fb('PATCH', 'groups', patch);
      return res.status(200).json({ ok: true, added, refreshed, kept });
    }
    if(op === 'admin-save'){
      if(!okTok(body.t)) return res.status(400).json({ ok: false, error: 't' });
      const g = await fb('GET', `groups/${body.t}`);
      if(!g) return res.status(404).json({ ok: false, error: '없는 그룹' });
      const now = Date.now();
      const rep = cleanPerson(body.rep);
      const next = Object.assign({}, g, {
        status: STATUSES.includes(body.status) ? body.status : g.status,
        rep: Object.assign({}, g.rep, rep, { name: rep.name || g.rep.name }),
        sub: body.sub && str(body.sub.name, 40) ? cleanPerson(body.sub) : null,
        // 손님이 이름을 적은 '이름 미기재' 자리 표시(from)는 담당자가 저장해도 유지
        comps: cleanComps(body.comps).map(c => { const p = (g.comps || []).find(x => x.name === c.name && x.from); return p ? Object.assign(c, { from: p.from }) : c; }),
        memo: str(body.memo, 300),
        updatedAt: now, updatedBy: email,
      });
      await fb('PUT', `groups/${body.t}`, next);
      await fb('POST', `log/${body.t}`, { at: now, by: email, status: next.status, n: (next.status === 'yes' ? 1 + next.comps.length : 0), sub: next.sub ? next.sub.name : '', comps: next.comps.map(c => c.name).join(', ') });
      return res.status(200).json({ ok: true, group: next });
    }
    if(op === 'delete'){
      if(!okTok(body.t)) return res.status(400).json({ ok: false, error: 't' });
      await fb('DELETE', `groups/${body.t}`);
      await fb('DELETE', `log/${body.t}`);
      return res.status(200).json({ ok: true });
    }
    if(op === 'meta'){
      await fb('PATCH', 'meta', { closed: !!body.closed, by: email, at: Date.now() });
      return res.status(200).json({ ok: true });
    }
    return res.status(400).json({ ok: false, error: 'unknown op' });
  }catch(e){
    return res.status(200).json({ ok: false, error: String((e && e.message) || e).replace(/auth=[^&\s]+/g, 'auth=***') });
  }
};
