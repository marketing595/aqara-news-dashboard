// 홈페이지 문의 '내용' 실시간 조회 (아임웹 Open API 2.0 프록시)
// ------------------------------------------------------------------
// · 대시보드가 열릴 때만 아임웹에서 직접 불러와 화면에 보여준다. **어디에도 저장하지 않는다.**
//   (저장소는 공개라 개인정보를 파일로 커밋하면 안 됨 → homepage.json에는 계속 건수·선택형 응답만)
// · middleware.js가 이 경로를 보호하므로 구글 로그인(@aqara.kr)한 사람만 호출할 수 있다.
// · 필요한 Vercel 환경변수: IMWEB_CLIENT_ID, IMWEB_CLIENT_SECRET, IMWEB_REFRESH_TOKEN
//   (선택) IMWEB_UNIT_CODE — 없으면 /site-info로 자동 감지
//
// GET /api/imweb-inquiries?from=YYYY-MM-DD&to=YYYY-MM-DD&limit=200
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

// 제출 항목(item[]) → [{q, a}] · 값이 비었거나 동의 항목만 있는 건 제외
function answersOf(items) {
  const out = [];
  (items || []).forEach((it) => {
    const q = (it.itemSubject || '').toString().trim();
    let a = (it.value || '').toString().trim();
    if (!a && Array.isArray(it.valueList)) a = it.valueList.filter(Boolean).join(', ');
    a = a.replace(/\r/g, '').trim();
    if (!q || !a) return;
    out.push({ q, a });
  });
  return out;
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');   // 개인정보 → 캐시 금지
  try {
    const from = (req.query.from || '').toString().slice(0, 10);
    const to = (req.query.to || '').toString().slice(0, 10);
    const limit = Math.min(parseInt(req.query.limit, 10) || 200, 500);

    const token = await getToken();
    let unit = (process.env.IMWEB_UNIT_CODE || '').trim();
    if (!unit) {
      const si = await api(token, '/site-info', {});
      unit = (((si || {}).unitList || [])[0] || {}).unitCode || '';
    }
    if (!unit) throw new Error('NO_UNIT');

    const rows = [];
    for (let page = 1; page <= 10 && rows.length < limit; page++) {
      const d = await api(token, '/community/form-submissions', { page, limit: 100, unitCode: unit });
      const list = (d || {}).list || [];
      list.forEach((s) => {
        const t = new Date((s.wtime || 0) * (String(s.wtime).length > 10 ? 1 : 1000));
        const kst = new Date(t.getTime() + 9 * 3600 * 1000);
        const day = isNaN(kst.getTime()) ? '' : kst.toISOString().slice(0, 10);
        if (from && day && day < from) return;
        if (to && day && day > to) return;
        rows.push({
          d: day,
          t: isNaN(kst.getTime()) ? '' : kst.toISOString().slice(11, 16),
          form: (s.formName || '문의').toString(),
          answers: answersOf(s.item),
        });
      });
      const totalPage = (d || {}).totalPage || 1;
      if (page >= totalPage || !list.length) break;
    }
    rows.sort((a, b) => (b.d + b.t).localeCompare(a.d + a.t));
    res.status(200).json({ ok: true, count: rows.length, rows: rows.slice(0, limit), note: '실시간 조회 · 서버에 저장하지 않음' });
  } catch (e) {
    const msg = String((e && e.message) || e);
    const hint = msg === 'NO_ENV'
      ? 'Vercel 환경변수 IMWEB_CLIENT_ID / IMWEB_CLIENT_SECRET / IMWEB_REFRESH_TOKEN 을 등록한 뒤 재배포하세요.'
      : msg.indexOf('TOKEN_') === 0
        ? '아임웹 토큰이 만료·회전되었습니다. crawler/imweb-token.bat 으로 새 refresh token을 발급해 Vercel 환경변수를 갱신하세요.'
        : '아임웹 API 호출에 실패했습니다.';
    res.status(200).json({ ok: false, error: msg, hint });
  }
};
