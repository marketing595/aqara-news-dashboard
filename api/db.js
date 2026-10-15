// 고객 DB 취합 (ONLY MKT > DB 탭) — 개인정보(이름·전화·이메일)를 다루는 유일한 통로
// ------------------------------------------------------------------
// · 데이터는 Firebase `customerDb/*` 에 저장하지만, 브라우저는 Firebase에 직접 붙지 않는다.
//   (index.html의 Firebase 설정은 공개 저장소에 있고 익명 로그인이라, 브라우저 직결이면 누구나 읽을 수 있음)
// · 이 함수만 서버 비밀키(FIREBASE_DB_SECRET, 규칙 무시)로 읽고 쓴다. Firebase 규칙은 customerDb를 전면 차단해야 한다.
// · 호출자는 반드시 @aqara.kr 세션이어야 한다 — middleware가 꺼져 있어도 여기서 다시 확인(실패 시 닫힘).
// · 안전장치: Firebase 규칙이 아직 열려 있으면(익명으로 customerDb가 읽히면) 업로드를 거부한다.
//
// GET  /api/db?op=status            → { secret, locked, email }
// GET  /api/db?op=files             → { files:{fid:meta} }
// GET  /api/db?op=rows&fid=...      → { chunks:[[row...],...] }
// POST /api/db { op:'meta', fid, meta }                 파일 정보 저장(업로드 시작)
// POST /api/db { op:'chunk', fid, i, rows }             행 묶음 저장(500행씩)
// POST /api/db { op:'delete', fid }                     파일 삭제
const crypto = require('crypto');

const DB_URL = 'https://aqara-weekly-1227c-default-rtdb.asia-southeast1.firebasedatabase.app';
const WEB_API_KEY = 'AIzaSyAs_yQ1fgGKfRDKbkUb0lviIoJ2e00KRGA'; // index.html에 있는 공개 키(규칙 점검용 익명 로그인에만 사용)
const DOMAIN = (process.env.ALLOWED_DOMAIN || 'aqara.kr').toLowerCase();

function parseCookies(h){
  const o = {};
  (h || '').split(';').forEach(p=>{ const i=p.indexOf('='); if(i>-1) o[p.slice(0,i).trim()]=p.slice(i+1).trim(); });
  return o;
}

// me.js와 같은 방식으로 __sess 검증 → 이메일
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

const secret = () => (process.env.FIREBASE_DB_SECRET || '').trim();
const okId = (s) => /^[A-Za-z0-9_-]{4,40}$/.test(String(s || ''));

async function fb(method, path, body){
  const r = await fetch(`${DB_URL}/customerDb/${path}.json?auth=${encodeURIComponent(secret())}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const t = await r.text();
  if(!r.ok) throw new Error(`Firebase ${r.status}: ${t.slice(0, 200)}`);
  return t ? JSON.parse(t) : null;
}

// Firebase 규칙이 customerDb를 막고 있는지 — 공개 키로 익명 로그인해 직접 읽어 본다
async function rulesLocked(){
  try{
    const s = await fetch(`https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=${WEB_API_KEY}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ returnSecureToken: true }),
    }).then(r => r.json());
    if(!s.idToken) return null;
    const r = await fetch(`${DB_URL}/customerDb.json?shallow=true&auth=${s.idToken}`);
    return r.status === 401 || r.status === 403;
  }catch(e){ return null; }
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');   // 개인정보 → 캐시 금지
  const email = sessionEmail(req);
  if(!email) return res.status(401).json({ ok: false, error: '@' + DOMAIN + ' 로그인이 필요합니다.' });

  const op = String((req.method === 'GET' ? req.query.op : (req.body || {}).op) || '');
  try{
    if(op === 'status'){
      return res.status(200).json({ ok: true, email, secret: !!secret(), locked: await rulesLocked() });
    }
    if(!secret()) return res.status(200).json({ ok: false, error: 'Vercel 환경변수 FIREBASE_DB_SECRET이 없습니다.' });

    if(req.method === 'GET'){
      if(op === 'files') return res.status(200).json({ ok: true, files: (await fb('GET', 'files')) || {} });
      if(op === 'rows'){
        const fid = req.query.fid;
        if(!okId(fid)) return res.status(400).json({ ok: false, error: 'fid' });
        const d = (await fb('GET', `rows/${fid}`)) || [];
        const chunks = Array.isArray(d) ? d : Object.keys(d).sort((a,b)=>a-b).map(k => d[k]);
        return res.status(200).json({ ok: true, chunks: chunks.filter(Boolean) });
      }
      return res.status(400).json({ ok: false, error: 'unknown op' });
    }

    if(req.method !== 'POST') return res.status(405).json({ ok: false });
    const b = req.body || {};
    if(!okId(b.fid)) return res.status(400).json({ ok: false, error: 'fid' });

    if(op === 'delete'){
      await fb('DELETE', `rows/${b.fid}`);
      await fb('DELETE', `files/${b.fid}`);
      await fb('POST', 'log', { op: 'delete', fid: b.fid, by: email, at: Date.now() });
      return res.status(200).json({ ok: true });
    }

    // 쓰기 전 안전장치: 규칙이 열려 있으면 개인정보를 올리지 않는다
    if(await rulesLocked() !== true){
      return res.status(200).json({ ok: false, error: 'Firebase 규칙이 아직 customerDb를 막고 있지 않습니다. 규칙 적용 후 다시 시도하세요.' });
    }
    if(op === 'meta'){
      const m = b.meta || {};
      const meta = {
        name: String(m.name || '').slice(0, 200), sheet: String(m.sheet || '').slice(0, 100),
        label: String(m.label || '').slice(0, 100),
        cols: (Array.isArray(m.cols) ? m.cols : []).map(c => String(c).slice(0, 100)).slice(0, 200),
        map: (m.map && typeof m.map === 'object') ? m.map : {},
        rows: Number(m.rows) || 0, chunks: Number(m.chunks) || 0,
        by: email, at: Date.now(),
      };
      await fb('PUT', `files/${b.fid}`, meta);
      await fb('POST', 'log', { op: 'upload', fid: b.fid, name: meta.name, rows: meta.rows, by: email, at: meta.at });
      return res.status(200).json({ ok: true });
    }
    if(op === 'chunk'){
      const i = Number(b.i);
      if(!(i >= 0 && i < 1000) || !Array.isArray(b.rows)) return res.status(400).json({ ok: false, error: 'chunk' });
      await fb('PUT', `rows/${b.fid}/${i}`, b.rows.map(r => (Array.isArray(r) ? r : []).map(v => v == null ? '' : String(v).slice(0, 2000))));
      return res.status(200).json({ ok: true });
    }
    return res.status(400).json({ ok: false, error: 'unknown op' });
  }catch(e){
    return res.status(200).json({ ok: false, error: String((e && e.message) || e).replace(/auth=[^&\s]+/g, 'auth=***') });
  }
};
