// 아임웹 Open API 2.0 공통 모듈 (토큰 발급 · 호출 · 시간 파싱)
// ------------------------------------------------------------------
// api/imweb-inquiries.js(문의 내용)와 api/homepage-live.js(집계)가 함께 쓴다.
// 필요한 Vercel 환경변수: IMWEB_CLIENT_ID, IMWEB_CLIENT_SECRET, IMWEB_REFRESH_TOKEN
//   (선택) IMWEB_UNIT_CODE — 없으면 /site-info로 자동 감지
const BASE = 'https://openapi.imweb.me';

async function getToken() {
  if (process.env.IMWEB_ACCESS_TOKEN) return process.env.IMWEB_ACCESS_TOKEN.trim();
  const cid = (process.env.IMWEB_CLIENT_ID || '').trim();
  const sec = (process.env.IMWEB_CLIENT_SECRET || '').trim();
  const rt = (process.env.IMWEB_REFRESH_TOKEN || '').trim();
  if (!cid || !sec || !rt) throw new Error('NO_ENV');
  const body = new URLSearchParams({ clientId: cid, clientSecret: sec, refreshToken: rt, grantType: 'refresh_token' });
  const r = await fetch(BASE + '/oauth2/token', {
    method: 'POST', body,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
  if (!r.ok) throw new Error('TOKEN_' + r.status);
  const d = ((await r.json()) || {}).data || {};
  if (!d.accessToken) throw new Error('TOKEN_EMPTY');
  return d.accessToken;
}

async function api(token, path, params) {
  const url = new URL(BASE + path);
  Object.keys(params || {}).forEach((k) => { if (params[k] != null && params[k] !== '') url.searchParams.set(k, params[k]); });
  const r = await fetch(url.toString(), {
    headers: { Authorization: 'Bearer ' + token, 'access-token': token },
  });
  if (!r.ok) throw new Error('API_' + r.status + '_' + path);
  return ((await r.json()) || {}).data;
}

async function resolveUnit(token) {
  const env = (process.env.IMWEB_UNIT_CODE || '').trim();
  if (env) return env;
  const si = await api(token, '/site-info', {});
  const unit = (((si || {}).unitList || [])[0] || {}).unitCode || '';
  if (!unit) throw new Error('NO_UNIT');
  return unit;
}

// 목록 API 전체 수집. 1페이지로 totalPage를 확인한 뒤 나머지는 동시에 받아 온다
// (서버리스 실행시간 한도가 있어 순차 호출로는 1,000건대에서 타임아웃 위험).
async function fetchAll(token, path, unit, opt) {
  const o = opt || {};
  const limit = o.limit || 100, cap = o.cap || 30, chunk = o.chunk || 5;
  const first = await api(token, path, { page: 1, limit, unitCode: unit });
  const rows = ((first || {}).list || []).slice();
  const totalPage = Math.min((first || {}).totalPage || 1, cap);
  for (let p = 2; p <= totalPage; p += chunk) {
    const batch = [];
    for (let i = p; i < p + chunk && i <= totalPage; i++) batch.push(api(token, path, { page: i, limit, unitCode: unit }));
    const got = await Promise.all(batch);
    got.forEach((d) => { rows.push(...(((d || {}).list) || [])); });
  }
  return rows;
}

// 제출 일시 → KST { d:'YYYY-MM-DD', h:시, t:'HH:MM' }
// 아임웹은 상황에 따라 unixtime(초/밀리초) 또는 ISO 문자열을 준다.
function parseTime(w) {
  if (w == null || w === '') return { d: '', h: null, t: '' };
  const s = String(w).trim();
  let dt;
  if (/^\d+$/.test(s)) {
    dt = new Date(Number(s) * (s.length > 10 ? 1 : 1000) + 9 * 3600 * 1000);   // unixtime(UTC) → KST
  } else if (/Z$/i.test(s)) {
    dt = new Date(new Date(s).getTime() + 9 * 3600 * 1000);                    // ISO UTC → KST
  } else {
    dt = new Date(s.slice(0, 19).replace(' ', 'T') + 'Z');                     // 이미 KST 표기 → 그대로
  }
  if (isNaN(dt.getTime())) return { d: s.slice(0, 10), h: null, t: '' };
  const iso = dt.toISOString();
  return { d: iso.slice(0, 10), h: dt.getUTCHours(), t: iso.slice(11, 16) };
}

// 실패 원인별 안내 문구
function hintFor(msg) {
  if (msg === 'NO_ENV') return 'Vercel 환경변수 IMWEB_CLIENT_ID / IMWEB_CLIENT_SECRET / IMWEB_REFRESH_TOKEN 을 등록한 뒤 재배포하세요.';
  if (msg.indexOf('TOKEN_') === 0) return '아임웹 토큰이 만료·회전되었습니다. crawler/imweb-token.bat 으로 새 refresh token을 발급해 Vercel 환경변수를 갱신하세요.';
  if (msg === 'NO_UNIT') return '아임웹 unitCode를 확인할 수 없습니다 (site-info:read 권한 확인).';
  return '아임웹 API 호출에 실패했습니다.';
}

module.exports = { BASE, getToken, api, resolveUnit, fetchAll, parseTime, hintFor };
