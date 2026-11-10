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
  date: '2026년 11월 19일 (목) 14:00 – 17:00',
  place: '서울 코엑스 컨퍼런스룸(남) 4층 401호',
  addr: '서울 강남구 영동대로 513 코엑스',
  way: '2호선 삼성역과 지하로 바로 연결돼요. 차량은 코엑스 주차장을 이용해 주세요. (유료)',
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
// 엑셀 숫자 칸에서 앞 0이 빠진 휴대폰(10xxxxxxxx, 10자리)은 0을 붙여 저장(2026-11-10)
const digits = (v) => { const d = String(v || '').replace(/\D/g, '').slice(0, 15); return /^10\d{8}$/.test(d) ? '0' + d : d; };

// ── 저장소: 암호화 + 익명 로그인 ──
// FIREBASE_DB_SECRET(관리자 키)이 유효하지 않아(2026-10-29 확인: Permission denied) 관리자 키 없이 동작하게 바꿨다.
// · 서버가 익명 로그인 토큰으로 Firebase에 접근한다(브라우저는 Firebase에 직접 붙지 않음).
// · 저장 위치는 SESSION_SECRET에서 만든 비공개 경로(rsvpx_<해시>) — 브라우저 코드·저장소 어디에도 안 나온다. 루트 목록은 익명에게 막혀 있다.
// · 그룹·이력 내용은 AES-256-GCM으로 암호화해서 넣는다. 경로를 알아내도 이름·연락처는 읽을 수 없다.
//   키 = SHA-256(SESSION_SECRET + 'rsvp'). ⚠️ SESSION_SECRET을 바꾸면 기존 RSVP 데이터를 못 읽는다(바꾸기 전 명단을 내보낼 것).
const SS = () => (process.env.SESSION_SECRET || '').trim();
const ROOT = () => 'rsvpx_' + crypto.createHmac('sha256', SS()).update('rsvp-root').digest('hex').slice(0, 24);
const KEY = () => crypto.createHash('sha256').update(SS() + 'rsvp').digest();
const viewKey = (gen) => crypto.createHmac('sha256', SS()).update('view:' + (gen || 0)).digest('base64url').slice(0, 20);   // 보기 전용 공유 링크 키
const gid = (t) =>crypto.createHmac('sha256', SS()).update('g:' + t).digest('hex').slice(0, 20);   // 토큰도 경로에 그대로 쓰지 않는다
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
  const em = str(p.email, 120).trim().toLowerCase();
  return Object.assign({ name: str(p.name, 40), title: str(p.title, 40), org: str(p.org, 80), phone: digits(p.phone) }, /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em) ? { email: em } : {});
}
// 동행인 소속이 비어 있으면 대표자 소속으로 채운다(2026-10-30 사용자 지정)
const fillOrg = (comps, org) => (comps || []).map(c => c.org ? c : Object.assign({}, c, { org: org || '' }));
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
// cans = 동행인이 자기 링크로 직접 답한 것 { 자리 이름: 'yes'|'no' } — 대표자 화면에서 미리 골라 보여 준다
function guestView(g, meta, masked){
  const now = (g.comps || []).map(c => c.name), cans = {};
  Object.keys(g.cans || {}).forEach(s => { if(g.cans[s] && g.cans[s].v) cans[s] = g.cans[s].v; });
  const rep = { name: g.rep.name, title: g.rep.title || '', org: g.rep.org || '', phone: g.rep.phone || '', email: g.email || '' };
  const comps = fillOrg(g.comps, g.rep.org);
  // 공통 링크로 들어온 경우 연락처·이메일은 가린다(끝 4자리만). 이름 미기재 자리 등 나머지는 그대로
  const removed = Object.keys(allowedComps(g)).filter(n => !now.includes(n));
  return {
    ok: true, event: EVENT, closed: !!(meta && meta.closed), masked: !!masked,
    rep: masked ? maskP(rep) : rep,
    sub: g.sub ? { name: g.sub.name } : null, comps: masked ? comps.map(maskP) : comps, status: g.status || 'pending',
    removed, removedPh4: masked ? removed.map(n => last4((allowedComps(g)[n] || {}).phone)) : undefined,
    updatedAt: g.updatedAt || 0, answered: !!g.answeredAt, cans,
  };
}

// ── 동행인 개인 링크(2026-11-04): hakdongmap.kr/c/<7자> ──
// 대표자 링크를 동행인에게 그대로 주면 대표자 이름으로 열려서, 동행인마다 자기 이름으로 열리는 링크를 따로 준다.
// 코드 = HMAC(그룹 토큰 + 자리 이름) 앞 7자 → 저장할 필요가 없고, 그룹 토큰을 몰라도 대표자 화면은 못 연다.
// 자리 이름 = 처음 명단 이름(이름 미기재 자리는 c.from). 담당자가 동행인 이름을 고치면 링크도 바뀐다.
const slotOf = (c) => (c && (c.from || c.name)) || '';
function compSlots(g){
  return [...new Set([...String((g.orig && g.orig.comps) || '').split(', ').map(s => s.trim()).filter(Boolean), ...(g.comps || []).map(slotOf).filter(Boolean)])];
}
const ccode = (t, slot) => crypto.createHmac('sha256', SS()).update('c:' + t + '|' + slot).digest('base64url').slice(0, 7);
const okC = (s) => /^[A-Za-z0-9_-]{7}$/.test(String(s || ''));
let CMAP = { at: 0, m: {} };
async function codeToSlot(code){
  if(Date.now() - CMAP.at > 5 * 60 * 1000 || !CMAP.m[code]){
    const all = (await fb('GET', 'groups')) || {}, m = {};
    Object.keys(all).forEach(t => { const g = all[t]; if(!g || !g.rep) return; compSlots(g).forEach(s => { m[ccode(t, s)] = { t, slot: s }; }); });
    CMAP = { at: Date.now(), m };
  }
  return CMAP.m[code] || null;
}
// 동행인 한 명의 현재 상태: 본인이 답했으면 그 값, 아니면 대표자/담당자가 답한 그룹 기준(명단에 남아 있으면 참석)
function compState(g, slot){
  const cur = (g.comps || []).find(c => slotOf(c) === slot) || null;
  const a = (g.cans || {})[slot];
  const status = a && a.v ? a.v : ((g.status === 'yes' || g.status === 'no') ? (cur ? 'yes' : 'no') : 'pending');
  return { cur, status, at: a && a.at ? a.at : 0 };
}
// ── 공통 링크(2026-11-04): hakdongmap.kr/rsvp — "성함이 어떻게 되시나요?" → 이름으로 명단에서 찾기 ──
// 개별 링크 배포 오류를 줄이려고 모두 같은 링크를 쓰고, 이름으로 본인/동행인 자리를 찾는다.
// 이름만 알면 들어올 수 있으므로: 찾기 결과엔 소속·일행 이름만, 화면엔 등록된 연락처·이메일을 보여 주지 않는다(끝 4자리만).
// 찾은 뒤엔 서명된 표(k = 그룹 토큰·자리·만료 3시간)로만 그 사람 화면을 읽고 저장한다 — 그룹 토큰은 브라우저로 안 나간다.
const normName = (s) => String(s || '').replace(/\s+/g, '').toLowerCase();
const TK_TTL = 3 * 3600 * 1000;
const tkMac = (p) => crypto.createHmac('sha256', SS()).update('k:' + p).digest('base64url').slice(0, 22);
function mkTk(t, s){ const p = Buffer.from(JSON.stringify({ t, s: s || '', e: Date.now() + TK_TTL })).toString('base64url'); return p + '.' + tkMac(p); }
function readTk(k){
  const i = String(k || '').lastIndexOf('.'); if(i < 1) return null;
  const p = k.slice(0, i), m = k.slice(i + 1);
  if(m.length !== 22 || !crypto.timingSafeEqual(Buffer.from(m), Buffer.from(tkMac(p)))) return null;
  try{ const o = JSON.parse(Buffer.from(p, 'base64url').toString('utf8')); return o && okTok(o.t) && Date.now() < o.e ? o : null; }catch(e){ return null; }
}
const last4 = (v) => { const d = digits(v); return d.length >= 4 ? d.slice(-4) : ''; };
// 가린 화면: 연락처·이메일은 비우고 끝 4자리만(ph4). 저장 때 비워 보내면 기존 값 유지
function maskP(p){ const o = Object.assign({}, p); o.ph4 = last4(p.phone); o.hasEmail = !!p.email; o.phone = ''; o.email = ''; return o; }
let GCACHE = { at: 0, all: null };
async function groupsCached(){
  if(!GCACHE.all || Date.now() - GCACHE.at > 60 * 1000) GCACHE = { at: Date.now(), all: (await fb('GET', 'groups')) || {} };
  return GCACHE.all;
}

// 대표자·담당자가 나중에 고친 명단과 어긋나는 동행인 응답은 지운다(나중에 저장한 쪽이 이긴다)
function syncCans(g){
  if(!g.cans) return g;
  const going = new Set((g.comps || []).map(slotOf)), out = {};
  Object.keys(g.cans).forEach(s => { const a = g.cans[s]; if(a && (a.v === 'yes') === going.has(s)) out[s] = a; });
  if(Object.keys(out).length) g.cans = out; else delete g.cans;
  return g;
}
function compView(g, meta, code, slot, masked){
  const s = compState(g, slot), base = s.cur || { name: slot, title: '', org: g.rep.org || '', phone: '' };
  const ph = isPH(slot);
  const me = { name: ph && base.name === slot ? '' : base.name, ph, title: base.title || '', org: base.org || g.rep.org || '', phone: base.phone || '', email: base.email || '' };
  return {
    ok: true, mode: 'comp', c: code, event: EVENT, closed: !!(meta && meta.closed),
    me: masked ? maskP(me) : me, masked: !!masked,
    host: g.rep.name, status: s.status, answered: s.status !== 'pending', updatedAt: s.at,
  };
}

// 앞 6자 → 전체 토큰. 그룹 목록을 한 번 읽어 5분간 기억(같은 앞자리가 둘 이상이면 찾지 않음 — 관리 화면이 경고)
let SHORT = { at: 0, m: {} };
async function shortToTok(sc){
  const build = async () => { const all = (await fb('GET', 'groups')) || {}, m = {};
    Object.keys(all).forEach(t => { const k = t.slice(0, 6); m[k] = m[k] ? '!' : t; }); SHORT = { at: Date.now(), m }; };
  if(Date.now() - SHORT.at > 5 * 60 * 1000 || !SHORT.m[sc]) await build();
  const t = SHORT.m[sc];
  return t && t !== '!' ? t : '';
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');   // 개인정보 → 캐시 금지
  res.setHeader('X-Robots-Tag', 'noindex');
  const body = req.body || {};
  const op = String((req.method === 'GET' ? req.query.op : body.op) || '');
  try{
    if(!SS()) return res.status(200).json({ ok: false, error: "서버 설정이 끝나지 않았어요(SESSION_SECRET)." });

    // ── 공통 링크: 이름으로 찾기 — 같은 이름이 여럿이면 소속·일행 이름만 보여 주고 고르게 한다 ──
    if(op === 'find'){
      const q = normName(req.query.name);
      if(q.length < 2) return res.status(200).json({ ok: false, error: '성함을 입력해 주세요.' });
      const all = await groupsCached(), list = [];
      Object.keys(all).forEach(t => { const g = all[t]; if(!g || !g.rep || g.test) return;
        if(normName(g.rep.name) === q) list.push({ k: mkTk(t, ''), role: 'rep', name: g.rep.name, org: g.rep.org || '', n: compSlots(g).length });
        compSlots(g).forEach(s => { const cur = (g.comps || []).find(c => slotOf(c) === s), nm = cur ? cur.name : s;
          if(!isPH(nm) && normName(nm) === q) list.push({ k: mkTk(t, s), role: 'comp', name: nm, org: (cur && cur.org) || g.rep.org || '', host: g.rep.name }); }); });
      return res.status(200).json({ ok: true, event: EVENT, list: list.slice(0, 10) });
    }
    // 찾은 뒤 표(k)로 들어온 손님: 대표자 = get/save, 동행인 = cget/csave 로 넘긴다(연락처는 가려서)
    const TK = readTk(req.method === 'GET' ? req.query.k : body.k);
    const masked = !!TK;
    if(TK && TK.s && (op === 'get' || op === 'save')) return res.status(200).json({ ok: false, error: 'link' });

    // ── 손님 ──
    if(op === 'get' || op === 'save'){
      let t = TK ? TK.t : (req.method === 'GET' ? req.query.t : body.t);
      // 초단축 링크 hakdongmap.kr/<토큰 앞 6자>(이벤터스 직함 칸 길이 제한, 2026-10-30) → 전체 토큰으로 찾아 준다
      const sc = req.method === 'GET' ? String(req.query.s || '') : '';
      if(!okTok(t) && /^[A-Za-z0-9_-]{6}$/.test(sc)) t = await shortToTok(sc);
      if(!okTok(t)) return res.status(200).json({ ok: false, error: 'link' });
      const g = await fb('GET', `groups/${t}`);
      if(!g || !g.rep) return res.status(200).json({ ok: false, error: 'link' });
      const meta = (await fb('GET', 'meta')) || {};
      if(op === 'get'){
        // 링크 열람 기록(o/<gid>: 처음·마지막·횟수) — 담당자가 관리 화면에서 '열기'로 연 건 세지 않는다
        if(!sessionEmail(req)){
          try{ const o = (await raw('GET', 'o/' + gid(t))) || {}; const now = Date.now();
            await raw('PUT', 'o/' + gid(t), { first: o.first || now, last: now, n: (o.n || 0) + 1 }); }catch(e){}
        }
        return res.status(200).json(masked ? guestView(g, meta, true) : Object.assign(guestView(g, meta), { t }));   // 공통 링크엔 토큰을 돌려주지 않는다
      }

      if(req.method !== 'POST') return res.status(405).json({ ok: false });
      if(meta.closed) return res.status(200).json({ ok: false, error: '응답이 마감되었어요. 변경이 필요하면 담당자에게 연락해 주세요.' });
      const status = STATUSES.includes(body.status) && body.status !== 'pending' ? body.status : '';
      if(!status) return res.status(200).json({ ok: false, error: '참석 여부를 선택해 주세요.' });
      // 손님이 바꿀 수 있는 것: 본인·동행인 각자의 참석 여부, 소속, 연락처(+ 이름 미기재 자리의 이름). 동행인 추가·이름 수정·대리 참석은 담당자만.
      const rep = cleanPerson(body.rep);
      const allow = allowedComps(g), seen = {};
      // 이름 미기재 자리: 처음 명단의 미기재 이름 + 이미 이름을 적은 자리(from)
      const phs = {};
      Object.keys(allow).forEach(n => { if(isPH(n)) phs[n] = { name: n, title: '', org: g.rep.org || '', phone: '' }; });
      (g.comps || []).forEach(c => { if(c && c.from) phs[c.from] = c; });
      const comps = [];
      (Array.isArray(body.comps) ? body.comps : []).slice(0, 30).forEach(x => {
        const nm = str(x && x.name, 40), from = str(x && x.from, 40);
        // 공통 링크(가린 화면)에서 연락처를 비워 보내면 등록된 번호 유지
        const phone = digits(x && x.phone) || (masked ? (((from && phs[from]) || allow[nm] || {}).phone || '') : '');
        const org = (o) => (x && x.org !== undefined) ? { org: str(x.org, 80) } : (o ? { org: o } : {});   // 소속: 손님이 적은 값, 안 보냈으면 기존 값
        const title = (o) => (x && x.title !== undefined) ? { title: str(x.title, 40) } : (o ? { title: o } : {});   // 직책도 같은 방식
        const mail = (o) => { const e = str(x && x.email, 120).trim().toLowerCase(); return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e) ? { email: e } : (o ? { email: o } : {}); };   // 동행인 이메일(2026-11-03): 비워 보내면 기존 값
        if(from && phs[from]){
          if(seen[from]) return; seen[from] = 1;
          const c = Object.assign({}, phs[from], { name: nm || from, phone }, org(phs[from].org), title(phs[from].title), mail(phs[from].email));
          if(c.name === from) delete c.from; else c.from = from;
          comps.push(c);
        }else if(nm && allow[nm] && !seen[nm]){
          seen[nm] = 1; comps.push(Object.assign({}, allow[nm], { phone }, org(allow[nm].org), title(allow[nm].title), mail(allow[nm].email)));
        }
      });
      const sub = g.sub || null;
      const now = Date.now();
      const next = Object.assign({}, g, {
        status, rep: Object.assign({}, g.rep, { phone: rep.phone || (masked ? g.rep.phone || '' : '') }, body.rep && body.rep.org !== undefined ? { org: rep.org } : {}, body.rep && body.rep.title !== undefined ? { title: rep.title } : {}),
        sub, updatedAt: now, updatedBy: 'guest', answeredAt: now,
      });
      next.comps = fillOrg(comps, next.rep.org);
      syncCans(next);
      // 이메일(2026-11-03): 손님이 적은 값이 형식에 맞으면 저장, 비워 보내면 기존 값 유지
      const em = body.rep && typeof body.rep.email === 'string' ? str(body.rep.email, 120).trim().toLowerCase() : '';
      if(em && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em)) next.email = em;
      await fb('PUT', `groups/${t}`, next);
      await fb('POST', `log/${t}`, { at: now, by: 'guest', status, n: (status === 'yes' ? 1 : 0) + comps.length, sub: sub ? sub.name : '', comps: comps.map(c => c.name).join(', '), via: masked ? 'common' : undefined });
      GCACHE.at = 0;
      return res.status(200).json(guestView(next, meta, masked));
    }

    // ── 동행인(자기 링크) — 자기 참석 여부·연락처만. 대표자·다른 동행인 정보는 안 보인다 ──
    if(op === 'cget' || op === 'csave'){
      let code = String((req.method === 'GET' ? req.query.c : body.c) || ''), hit = null;
      if(TK && TK.s){ hit = { t: TK.t, slot: TK.s }; code = ccode(TK.t, TK.s); }   // 공통 링크로 찾은 동행인
      else{
        if(!okC(code)) return res.status(200).json({ ok: false, error: 'link' });
        hit = await codeToSlot(code);
      }
      if(!hit) return res.status(200).json({ ok: false, error: 'link' });
      const { t, slot } = hit;
      const g = await fb('GET', `groups/${t}`);
      if(!g || !g.rep || !compSlots(g).includes(slot) || ccode(t, slot) !== code) return res.status(200).json({ ok: false, error: 'link' });
      const meta = (await fb('GET', 'meta')) || {};
      if(op === 'cget'){
        if(!sessionEmail(req)){
          try{ const k = 'c' + gid(t + '|' + slot); const o = (await raw('GET', 'o/' + k)) || {}; const now = Date.now();
            await raw('PUT', 'o/' + k, { first: o.first || now, last: now, n: (o.n || 0) + 1, t: gid(t) }); }catch(e){}
        }
        return res.status(200).json(compView(g, meta, masked ? '' : code, slot, masked));
      }
      if(req.method !== 'POST') return res.status(405).json({ ok: false });
      if(meta.closed) return res.status(200).json({ ok: false, error: '응답이 마감되었어요. 변경이 필요하면 담당자에게 연락해 주세요.' });
      const status = body.status === 'yes' || body.status === 'no' ? body.status : '';
      if(!status) return res.status(200).json({ ok: false, error: '참석 여부를 선택해 주세요.' });
      const me = body.me || {}, s = compState(g, slot);
      const base = s.cur || allowedComps(g)[slot] || { name: slot, title: '', org: g.rep.org || '', phone: '' };
      const p = Object.assign({}, base, { phone: digits(me.phone) || (masked ? base.phone || '' : '') });
      if(me.org !== undefined) p.org = str(me.org, 80);
      if(me.title !== undefined) p.title = str(me.title, 40);
      const em = str(me.email, 120).trim().toLowerCase(); if(/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em)) p.email = em;
      if(isPH(slot)){ const nm = str(me.name, 40); if(nm) p.name = nm; if(p.name !== slot) p.from = slot; else delete p.from; }
      // 명단 순서를 지키며 이 사람만 넣고/뺀다
      const comps = (g.comps || []).slice(), i = comps.findIndex(c => slotOf(c) === slot);
      if(status === 'yes'){ if(i >= 0) comps[i] = p; else comps.push(p); } else if(i >= 0) comps.splice(i, 1);
      const now = Date.now();
      const next = Object.assign({}, g, { comps: fillOrg(comps, g.rep.org), cans: Object.assign({}, g.cans, { [slot]: { v: status, at: now } }), updatedAt: now,
        updatedBy: g.updatedBy || 'guest-comp' });   // 처음 손댄 게 동행인이면 명단 가져오기가 덮어쓰지 않게 표시
      await fb('PUT', `groups/${t}`, next);
      await fb('POST', `log/${t}`, { at: now, by: 'guest-comp', status: next.status || 'pending', n: (next.status === 'yes' ? 1 : 0) + next.comps.length, sub: '', comps: next.comps.map(c => c.name).join(', '), who: p.name, v: status });
      GCACHE.at = 0;
      return res.status(200).json(compView(next, meta, masked ? '' : code, slot, masked));
    }

    // ── 보기 전용 공유 링크(2026-11-05): /rsvp-view?v=<키> — 로그인 없이 목록만 읽는다(수정·삭제·가져오기 op는 아래 관리자 검사에 막힘) ──
    //  키 = HMAC(SESSION_SECRET, 'view:'+meta.viewGen) 앞 20자. 관리 화면 [새 키로 바꾸기]를 누르면 예전 링크는 바로 막힌다.
    //  손님 개인 링크(토큰)·동행인 링크 코드는 내보내지 않는다(그룹 키 = gid) → 이 링크로 손님 화면에 들어가 응답을 고칠 수 없다.
    if(op === 'list' && req.method === 'GET' && req.query.v){
      const [groups, meta, opens, sent, msg] = await Promise.all([fb('GET', 'groups'), fb('GET', 'meta'), raw('GET', 'o'), raw('GET', 's'), raw('GET', 'm')]);
      const m = meta || {};
      if(!m.viewOn || String(req.query.v) !== viewKey(m.viewGen)) return res.status(401).json({ ok: false, error: '보기 전용 링크가 만료됐어요. 담당자에게 새 링크를 받아 주세요.' });
      const ts = Object.keys(groups || {}), log = await logsFor(ts), G = {}, L = {};
      ts.forEach(t => { const g = Object.assign({}, groups[t]), k = gid(t);
        if(opens && opens[k]) g.open = opens[k];
        if(sent && sent[k]) g.sent = sent[k];
        if(msg && msg[k]) g.msg = msg[k];   // 문자/메일 발송(m/) — RSVP 초대 문자(s/)와 따로
        G[k] = g; if(log[t]) L[k] = log[t]; });
      return res.status(200).json({ ok: true, viewOnly: true, groups: G, meta: { closed: !!m.closed }, log: L, locked: true });
    }

    // ── 관리자 ──
    const email = sessionEmail(req);
    if(!email) return res.status(401).json({ ok: false, error: '@' + DOMAIN + ' 로그인이 필요합니다.' });

    if(op === 'list'){
      const [groups, meta, opens, sent, msg] = await Promise.all([fb("GET", "groups"), fb("GET", "meta"), raw('GET', 'o'), raw('GET', 's'), raw('GET', 'm')]);
      const log = await logsFor(Object.keys(groups || {}));
      // 문자 발송·링크 열람 기록을 그룹에 붙여 준다(저장은 따로: s/<gid>, o/<gid>)
      Object.keys(groups || {}).forEach(t => { const k = gid(t), g = groups[t];
        if(opens && opens[k]) g.open = opens[k];
        if(sent && sent[k]) g.sent = sent[k];
        if(msg && msg[k]) g.msg = msg[k];   // 문자/메일 발송(m/) — RSVP 초대 문자(s/)와 따로
        // 동행인 개인 링크 코드 { 자리 이름: 7자 } + 동행인 링크 열람
        if(g && g.rep){ g.clinks = {}; g.copen = {}; compSlots(g).forEach(s => { g.clinks[s] = ccode(t, s); const o = opens && opens['c' + gid(t + '|' + s)]; if(o) g.copen[s] = o; }); } });
      return res.status(200).json({ ok: true, email, groups: groups || {}, meta: meta || {}, log: log || {}, locked: true });
    }
    if(req.method !== 'POST') return res.status(405).json({ ok: false });

    // 문자 보냄 표시: { ts: [토큰…] } (unmark: true 면 표시 해제). 같은 사람에게 다시 보내면 횟수가 늘어난다.
    // at(ms)을 주면 그 시각을 '마지막 문자 전송'으로 기록(외부 도구로 이미 보낸 시각 입력). 같은 시각을 또 넣어도 횟수는 그대로.
    // 문자/메일 발송 완료(2026-11-10): RSVP 초대 문자(s/)와 별개인 행사 안내 발송 기록 m/<gid> = { at, by } (unmark면 삭제). 개인정보 없음.
    if(op === 'msent'){
      const ts = (Array.isArray(body.ts) ? body.ts : []).filter(okTok).slice(0, 3000);
      if(!ts.length) return res.status(200).json({ ok: true, n: 0 });
      const now = Date.now(), patch = {};
      ts.forEach(t => { patch[gid(t)] = body.unmark ? null : { at: now, by: email }; });
      await raw('PATCH', 'm', patch);
      return res.status(200).json({ ok: true, n: ts.length });
    }
    if(op === 'sent'){
      const ts = (Array.isArray(body.ts) ? body.ts : []).filter(okTok).slice(0, 3000);
      if(!ts.length) return res.status(200).json({ ok: true, n: 0 });
      const cur = (await raw('GET', 's')) || {}, now = Date.now(), patch = {};
      const atIn = Number(body.at), at = Number.isFinite(atIn) && atIn > 1.7e12 && atIn < now + 864e5 ? Math.round(atIn) : now;
      ts.forEach(t => { const k = gid(t), c = cur[k] || {};
        patch[k] = body.unmark ? null : { first: c.first ? Math.min(c.first, at) : at, at: Math.max(c.at || 0, at), n: (c.n || 0) + (c.at === at ? 0 : 1), by: email }; });
      await raw('PATCH', 's', patch);
      return res.status(200).json({ ok: true, n: ts.length });
    }

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
        const comps = fillOrg(cleanComps(x.comps), rep.org);
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
          patch[nt] = Object.assign(base, { rep, comps, sub: null, status: 'pending', created: now, updatedAt: 0, regBy: ['엑셀 등록', '이벤터스', '설문 응답'].includes(body.via) ? body.via : '엑셀 등록' });
          byKey[key] = nt; added++;
        }
      }
      if(Object.keys(patch).length) await fb('PATCH', 'groups', patch);
      return res.status(200).json({ ok: true, added, refreshed, kept });
    }
    // 현황 엑셀 반영(2026-11-02): 담당자가 정리한 '참석 확정 여부·발송 여부' 엑셀을 기존 그룹에 덮어 쓴다(새 그룹은 안 만듦).
    // items: [{ t, status?, comps?:[참석 동행인 이름], src?, sent?, sendNote? }]. 손님이 링크로 답한 그룹·담당자가 직접 고친 그룹의 상태는 건드리지 않는다.
    if(op === 'status'){
      const items = (Array.isArray(body.items) ? body.items : []).filter(x => x && okTok(x.t)).slice(0, 3000);
      const cur = (await fb('GET', 'groups')) || {}, sentCur = (await raw('GET', 's')) || {};
      const patch = {}, sentPatch = {}, logs = [], now = Date.now(); let applied = 0, kept = 0, sentN = 0, notes = 0;
      for(const x of items){
        const g0 = cur[x.t]; if(!g0 || !g0.rep || g0.test) continue;
        const g = Object.assign({}, g0);
        if(x.status === 'yes' || x.status === 'no'){
          const mine = g.src && g.updatedBy !== 'guest';   // 전에 이 기능으로 넣은 값이면 다시 반영해도 된다
          if(g.updatedBy === 'guest' || (g.updatedBy && !mine && (g.status || 'pending') !== 'pending')) kept++;
          else{
            g.status = x.status;
            if(Array.isArray(x.comps)){ const keep = x.comps.map(n => str(n, 40)); g.comps = (g.comps || []).filter(c => keep.includes(c.name) || (c.from && keep.includes(c.from))); syncCans(g); }
            g.src = str(x.src, 40) || '담당자 엑셀'; g.updatedAt = now; g.updatedBy = email;
            logs.push([x.t, { at: now, by: email, status: g.status, n: (g.status === 'yes' ? 1 : 0) + (g.comps || []).length, sub: '', comps: (g.comps || []).map(c => c.name).join(', '), src: g.src }]);
            applied++;
          }
        }
        // 이벤터스 응답 시각(타임라인용) — 이 기능으로 넣은 응답에만
        if(Number(x.at) > 1.6e12 && Number(x.at) < now + 864e5 && g.src && g.updatedBy !== 'guest') g.srcAt = Number(x.at);
        const note = str(x.sendNote, 60);
        if(note !== (g.sendNote || '')){ if(note) g.sendNote = note; else delete g.sendNote; notes++; }
        if(JSON.stringify(g) !== JSON.stringify(g0)) patch[x.t] = g;
        const k = gid(x.t);
        if(x.sent && !sentCur[k]){ sentPatch[k] = { first: now, at: now, n: 1, by: email, src: 'excel' }; sentN++; }
      }
      if(Object.keys(patch).length) await fb('PATCH', 'groups', patch);
      if(Object.keys(sentPatch).length) await raw('PATCH', 's', sentPatch);
      await Promise.all(logs.map(([t, l]) => fb('POST', `log/${t}`, l)));
      return res.status(200).json({ ok: true, applied, kept, sent: sentN, notes });
    }
    // 일괄 반영(2026-11-07): 담당자가 내보낸 엑셀에 적은 상태·메모를 그대로 반영(손님 응답이 있어도 담당자 지시가 우선).
    // items [{ t, status:'yes'|'no'|'', memo, flag:'애매'|'' }] — status '' 면 상태는 그대로, flag '' 면 표시 해제
    // 사람별 참석/불참(2026-11-09, 관리자): { t, slot:''(본인)|동행인 자리 이름, v:'yes'|'no' } — 동행인은 csave와 같은 방식으로 명단에 넣고/뺀다
    if(op === 'pset'){
      // 비밀번호 확인(2026-11-09 사용자 지정) — 저장소가 공개라 평문 대신 PBKDF2 값만 둔다
      const ph = crypto.pbkdf2Sync(String(body.pw || ''), 'aqara-rsvp-pset-2026', 100000, 32, 'sha256');
      if(!crypto.timingSafeEqual(ph, Buffer.from('a481ea96d324e6c91969b65c4450d7133163a3e2fb815858e65074e247654046', 'hex'))) return res.status(200).json({ ok: false, error: '비밀번호가 맞지 않아요', pw: true });
      if(!okTok(body.t)) return res.status(400).json({ ok: false, error: 't' });
      const v = body.v === 'yes' || body.v === 'no' ? body.v : ''; if(!v) return res.status(200).json({ ok: false, error: 'v' });
      const g = await fb('GET', `groups/${body.t}`); if(!g || !g.rep) return res.status(404).json({ ok: false, error: '없는 그룹' });
      const slot = str(body.slot, 60), now = Date.now(); let next, who;
      if(!slot){ next = Object.assign({}, g, { status: v }); who = g.rep.name; }
      else{
        if(!compSlots(g).includes(slot)) return res.status(200).json({ ok: false, error: '그 동행인 자리를 찾지 못했어요' });
        const s = compState(g, slot), base = s.cur || allowedComps(g)[slot] || { name: slot, title: '', org: g.rep.org || '', phone: '' };
        const comps = (g.comps || []).slice(), i = comps.findIndex(c => slotOf(c) === slot);
        if(v === 'yes'){ if(i < 0) comps.push(base); } else if(i >= 0) comps.splice(i, 1);
        next = Object.assign({}, g, { comps: fillOrg(comps, g.rep.org), cans: Object.assign({}, g.cans, { [slot]: { v, at: now, by: email } }) });
        who = base.name || slot;
      }
      next.updatedAt = now; next.updatedBy = email; next.src = '담당자 직접 선택';
      await fb('PUT', `groups/${body.t}`, next);
      await fb('POST', `log/${body.t}`, { at: now, by: email, status: next.status || 'pending', n: (next.status === 'yes' ? 1 : 0) + (next.comps || []).length, sub: '', comps: (next.comps || []).map(c => c.name).join(', '), who, v, src: next.src });
      GCACHE.at = 0;
      return res.status(200).json({ ok: true, group: next });
    }
    if(op === 'bulk'){
      const items = (Array.isArray(body.items) ? body.items : []).filter(x => x && okTok(x.t)).slice(0, 3000);
      const cur = (await fb('GET', 'groups')) || {}, patch = {}, logs = [], now = Date.now(); let n = 0;
      for(const x of items){
        const g0 = cur[x.t]; if(!g0 || !g0.rep || g0.test) continue;
        const g = Object.assign({}, g0);
        if(x.status === 'yes' || x.status === 'no') g.status = x.status;
        if(typeof x.memo === 'string' && x.memo.trim()) g.memo = str(x.memo, 300);
        if(x.flag) g.flag = str(x.flag, 10); else delete g.flag;
        if(JSON.stringify(g) === JSON.stringify(g0)) continue;
        g.src = '담당자 일괄 반영'; g.updatedAt = now; g.updatedBy = email;
        patch[x.t] = g; n++;
        if(g.status !== g0.status) logs.push([x.t, { at: now, by: email, status: g.status, n: (g.status === 'yes' ? 1 : 0) + (g.comps || []).length, sub: g.sub ? g.sub.name : '', comps: (g.comps || []).map(c => c.name).join(', '), src: g.src }]);
      }
      if(Object.keys(patch).length) await fb('PATCH', 'groups', patch);
      await Promise.all(logs.map(([t, l]) => fb('POST', `log/${t}`, l)));
      GCACHE.at = 0;
      return res.status(200).json({ ok: true, n });
    }
    // 참석 거절(2026-11-05): 담당자가 참석을 받지 않기로 한 그룹. 손님 응답과 상관없이 '참석 거절'로 따로 센다.
    // items [{ t, on, why }] — on=false 면 해제. add [{ rep, email, why }] — 명단에 없는 사람을 거절 상태로 새로 넣는다(거절 명단 엑셀).
    if(op === 'reject'){
      const items = (Array.isArray(body.items) ? body.items : []).filter(x => x && okTok(x.t)).slice(0, 3000);
      const adds = (Array.isArray(body.add) ? body.add : []).slice(0, 1000);
      const cur = (await fb('GET', 'groups')) || {}, patch = {}, now = Date.now(); let on = 0, off = 0, added = 0;
      for(const x of items){
        const g0 = cur[x.t]; if(!g0 || !g0.rep) continue;
        const g = Object.assign({}, g0);
        if(x.on === false){ if(!g.rejected) continue; delete g.rejected; off++; }
        else { g.rejected = { at: (g0.rejected && g0.rejected.at) || now, by: email, why: str(x.why, 100) }; on++; }
        g.updatedAt = now; g.updatedBy = g.updatedBy || email;
        patch[x.t] = g;
      }
      const keys = new Set(Object.keys(cur).map(t => cur[t] && cur[t].key).filter(Boolean));
      for(const x of adds){
        const rep = cleanPerson(x && x.rep); if(!rep.name) continue;
        const email2 = str(x.email, 120).toLowerCase();
        let key = rep.phone ? 'p' + rep.phone : (email2 ? 'e' + email2 : 'n' + (rep.name + '|' + rep.org).replace(/[.#$\[\]\/]/g, ''));
        if(keys.has(key)) continue; keys.add(key);
        let t = newTok(); while(cur[t] || patch[t]) t = newTok();
        patch[t] = { key, email: email2, route: '', vip: false, note: '', orig: { n: 1, comps: '' }, rep, comps: [], sub: null, status: 'pending', created: now, updatedAt: now, updatedBy: email,
          addedBy: email, regBy: '거절 명단', rejected: { at: now, by: email, why: str(x.why, 100) } };
        added++;
      }
      if(Object.keys(patch).length) await fb('PATCH', 'groups', patch);
      GCACHE.at = 0;
      return res.status(200).json({ ok: true, on, off, added });
    }
    // 직접 입력: 한 그룹 추가. test=true 면 테스트 탭 전용(실제 명단·통계·내보내기에서 빠짐)
    if(op === 'add'){
      const rep = cleanPerson(body.rep);
      if(!rep.name) return res.status(200).json({ ok: false, error: '성함을 입력해 주세요.' });
      const test = !!body.test, comps = fillOrg(cleanComps(body.comps), rep.org), email2 = str(body.email, 120).toLowerCase();
      const cur = (await fb('GET', 'groups')) || {};
      let t = newTok(); while(cur[t]) t = newTok();
      const key = test ? 'test|' + t : (rep.phone ? 'p' + rep.phone : (email2 ? 'e' + email2 : 'n' + (rep.name + '|' + rep.org).replace(/[.#$\[\]\/]/g, '')));
      if(!test){
        const dup = Object.keys(cur).find(k => cur[k] && !cur[k].test && cur[k].key === key);
        if(dup) return res.status(200).json({ ok: false, error: `같은 연락처(또는 이메일)로 이미 명단에 있어요: ${cur[dup].rep.name}` });
      }
      const now = Date.now();
      const g = { key, email: email2, route: str(body.route, 80), vip: false, note: str(body.note, 300), orig: { n: 1 + comps.length, comps: comps.map(c => c.name).join(', ') },
        rep, comps, sub: null, status: 'pending', created: now, updatedAt: 0, addedBy: email, regBy: '수기 등록' };
      if(test) g.test = true;
      await fb('PUT', `groups/${t}`, g);
      return res.status(200).json({ ok: true, t, group: g });
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
        comps: fillOrg(cleanComps(body.comps), rep.org || g.rep.org).map(c => { const p = (g.comps || []).find(x => x.name === c.name && x.from); return p ? Object.assign(c, { from: p.from }) : c; }),
        memo: str(body.memo, 300),
        email: typeof body.email === 'string' ? str(body.email, 120).trim().toLowerCase() : (g.email || ''),   // 2026-11-03 담당자가 이메일 입력·수정
        updatedAt: now, updatedBy: email,
      });
      syncCans(next);
      await fb('PUT', `groups/${body.t}`, next);
      await fb('POST', `log/${body.t}`, { at: now, by: email, status: next.status, n: (next.status === 'yes' ? 1 : 0) + (next.status === 'no' || next.status === 'yes' ? next.comps.length : 0), sub: next.sub ? next.sub.name : '', comps: next.comps.map(c => c.name).join(', ') });
      return res.status(200).json({ ok: true, group: next });
    }
    // 기존 그룹에 동행인 추가(2026-11-03, 이벤터스 명단 가져오기): items [{ t, comps:[사람] }].
    // import 는 손님·담당자가 손댄 그룹을 덮어쓰지 않아서 동행인이 안 붙었다 → 여기선 상태는 그대로 두고 없는 사람만 덧붙인다.
    if(op === 'addcomps'){
      const items = (Array.isArray(body.items) ? body.items : []).slice(0, 500);
      let added = 0;
      for(const x of items){
        if(!okTok(x && x.t)) continue;
        const g = await fb('GET', `groups/${x.t}`); if(!g) continue;
        const have = new Set([...(g.comps || []).flatMap(c => [c.name, c.phone]), ...String((g.orig && g.orig.comps) || '').split(', ')].filter(Boolean));
        const add = cleanComps(x.comps).filter(c => !have.has(c.name) && !(c.phone && have.has(c.phone)));
        if(!add.length) continue;
        g.comps = fillOrg([...(g.comps || []), ...add], g.rep.org);
        const names = [String((g.orig && g.orig.comps) || ''), ...add.map(c => c.name)].filter(Boolean).join(', ');
        g.orig = Object.assign({}, g.orig, { n: ((g.orig && g.orig.n) || 1) + add.length, comps: names });
        await fb('PUT', `groups/${x.t}`, g);
        await fb('POST', `log/${x.t}`, { at: Date.now(), by: email, status: g.status, n: 0, sub: '', comps: g.comps.map(c => c.name).join(', '), src: '이벤터스 동행인 추가' });
        added += add.length;
      }
      return res.status(200).json({ ok: true, added });
    }
    // 발송 메모(빨간 글씨) 지우기/고치기(2026-11-03): { t, sendNote }
    if(op === 'sendnote'){
      if(!okTok(body.t)) return res.status(400).json({ ok: false, error: 't' });
      const g = await fb('GET', `groups/${body.t}`);
      if(!g) return res.status(404).json({ ok: false, error: '없는 그룹' });
      const note = str(body.sendNote, 60);
      if(note) g.sendNote = note; else delete g.sendNote;
      await fb('PUT', `groups/${body.t}`, g);
      return res.status(200).json({ ok: true });
    }
    // 이메일 일괄 반영(2026-11-03): items [{ t, email }] — 설문 응답 엑셀 기준으로 담당자가 확인 후 저장. 상태·응답 시각은 건드리지 않는다.
    if(op === 'emails'){
      const items = (Array.isArray(body.items) ? body.items : []).slice(0, 3000);
      const cur = (await fb('GET', 'groups')) || {}, patch = {};
      items.forEach(x => {
        const t = x && x.t, em = str(x && x.email, 120).trim().toLowerCase();
        if(!okTok(t) || !cur[t] || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em) || cur[t].email === em) return;
        patch[t] = Object.assign({}, cur[t], { email: em });
      });
      if(Object.keys(patch).length) await fb('PATCH', 'groups', patch);
      return res.status(200).json({ ok: true, n: Object.keys(patch).length });
    }
    // 삭제 = 휴지통으로(2026-11-05): 그룹을 x/<gid> 에 암호화해 옮기고 목록에서 뺀다. 변경 이력·발송·열람 기록은 그대로 둬서 복원하면 다 돌아온다.
    // 휴지통에 있는 동안 개인 링크는 열리지 않는다(groups 에 없으므로).
    if(op === 'delete'){
      if(!okTok(body.t)) return res.status(400).json({ ok: false, error: 't' });
      const g = await fb('GET', `groups/${body.t}`);
      if(g) await raw('PUT', 'x/' + gid(body.t), { c: enc(Object.assign({}, g, { _t: body.t, deletedAt: Date.now(), deletedBy: email }, str(body.why, 120) ? { deletedWhy: str(body.why, 120) } : {})) });
      await fb('DELETE', `groups/${body.t}`);
      GCACHE.at = 0;
      return res.status(200).json({ ok: true });
    }
    if(op === 'trash'){
      const all = (await raw('GET', 'x')) || {}, items = [];
      Object.keys(all).forEach(k => { const g = all[k] && dec(all[k].c); if(g && g._t) items.push(g); });
      items.sort((a, b) => (b.deletedAt || 0) - (a.deletedAt || 0));
      return res.status(200).json({ ok: true, items });
    }
    if(op === 'restore' || op === 'purge'){
      if(!okTok(body.t)) return res.status(400).json({ ok: false, error: 't' });
      const k = gid(body.t), v = await raw('GET', 'x/' + k), g = v && dec(v.c);
      if(!g) return res.status(404).json({ ok: false, error: '휴지통에 없는 그룹' });
      if(op === 'restore'){
        if(await fb('GET', `groups/${body.t}`)) return res.status(200).json({ ok: false, error: '같은 링크의 그룹이 이미 명단에 있어요' });
        delete g.deletedAt; delete g.deletedBy; delete g.deletedWhy;
        await fb('PUT', `groups/${body.t}`, g);
        await raw('DELETE', 'x/' + k);
        GCACHE.at = 0;
        return res.status(200).json({ ok: true, group: g });
      }
      await Promise.all([raw('DELETE', 'x/' + k), raw('DELETE', 'l/' + k), raw('DELETE', 'o/' + k), raw('DELETE', 's/' + k)]);
      return res.status(200).json({ ok: true });
    }
    // 보기 전용 링크: {} = 지금 키(없으면 켬) · { regen:true } = 새 키(예전 링크 막힘) · { off:true } = 끄기
    if(op === 'viewkey'){
      const m = (await fb('GET', 'meta')) || {};
      if(body.off){ await fb('PATCH', 'meta', { viewOn: false }); return res.status(200).json({ ok: true, off: true }); }
      const gen = (m.viewGen || 0) + (body.regen ? 1 : 0);
      if(body.regen || !m.viewOn) await fb('PATCH', 'meta', { viewOn: true, viewGen: gen, viewBy: email, viewAt: Date.now() });
      return res.status(200).json({ ok: true, key: viewKey(gen) });
    }
    if(op === 'meta'){
      await fb('PATCH', 'meta', { closed: !!body.closed, by: email, at: Date.now() });
      return res.status(200).json({ ok: true });
    }
    // 응답 초기화: 모든 그룹을 미응답으로 되돌리고 동행인은 처음 명단 이름으로, 변경 이력 삭제. 링크(토큰)는 그대로.
    // 초기화 뒤 같은 명단 엑셀을 다시 가져오면 연락처·소속까지 명단 값으로 돌아간다(미응답 그룹은 가져오기가 갱신하므로).
    if(op === 'reset'){
      // test=true 면 테스트 그룹만, 아니면 실제 명단만 초기화한다
      const onlyTest = !!body.test;
      const cur = (await fb('GET', 'groups')) || {}, patch = {};
      if(onlyTest){
        const ts = Object.keys(cur).filter(t => cur[t] && cur[t].test);
        await Promise.all(ts.flatMap(t => [raw('DELETE', 'l/' + gid(t)), raw('DELETE', 'o/' + gid(t)), raw('DELETE', 's/' + gid(t))]));
      }
      Object.keys(cur).forEach(t => {
        const g = cur[t];
        if(!g || !!g.test !== onlyTest) return;
        if(!g.rep || (!g.answeredAt && !g.updatedBy && (g.status || 'pending') === 'pending')) return;
        const names = String((g.orig && g.orig.comps) || '').split(', ').map(s => s.trim()).filter(Boolean);
        const comps = names.map(n => { const c = (g.comps || []).find(x => x.name === n); if(c){ const o = Object.assign({}, c); delete o.from; return o; } return { name: n, title: '', org: g.rep.org || '', phone: '' }; });
        const next = Object.assign({}, g, { status: 'pending', comps, updatedAt: 0 });
        delete next.answeredAt; delete next.updatedBy; delete next._t; delete next.cans;
        patch[t] = next;
      });
      if(Object.keys(patch).length) await fb('PATCH', 'groups', patch);
      if(onlyTest) return res.status(200).json({ ok: true, reset: Object.keys(patch).length });
      await raw('DELETE', 'l');
      await raw('DELETE', 'o');   // 테스트하며 연 기록도 지운다(문자 발송 기록 s/ 는 유지)
      await fb('PATCH', 'meta', { resetBy: email, resetAt: Date.now() });
      return res.status(200).json({ ok: true, reset: Object.keys(patch).length });
    }
    return res.status(400).json({ ok: false, error: 'unknown op' });
  }catch(e){
    return res.status(200).json({ ok: false, error: String((e && e.message) || e).replace(/auth=[^&\s]+/g, 'auth=***') });
  }
};
