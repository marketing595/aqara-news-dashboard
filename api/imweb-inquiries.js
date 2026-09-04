// 홈페이지 문의 '내용' 실시간 조회 (아임웹 Open API 2.0 프록시)
// ------------------------------------------------------------------
// · 대시보드가 열릴 때만 아임웹에서 직접 불러와 화면에 보여준다. **어디에도 저장하지 않는다.**
//   (저장소는 공개라 개인정보를 파일로 커밋하면 안 됨 → 집계는 /api/homepage-live 가 따로 담당)
// · middleware.js가 이 경로를 보호하므로 구글 로그인(@aqara.kr)한 사람만 호출할 수 있다.
// · 필요한 Vercel 환경변수: IMWEB_CLIENT_ID, IMWEB_CLIENT_SECRET, IMWEB_REFRESH_TOKEN
//   (선택) IMWEB_UNIT_CODE — 없으면 /site-info로 자동 감지
//
// GET /api/imweb-inquiries?from=YYYY-MM-DD&to=YYYY-MM-DD&limit=200
const { getToken, resolveUnit, fetchAll, parseTime, hintFor } = require('./_imweb');

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
    const unit = await resolveUnit(token);

    const list = await fetchAll(token, '/community/form-submissions', unit, { cap: 30 });
    const rows = [];
    list.forEach((s) => {
      const { d, t } = parseTime(s.wtime);
      if (from && d && d < from) return;
      if (to && d && d > to) return;
      rows.push({
        d, t,
        form: (s.formName || '문의').toString(),
        answers: answersOf(s.item),
      });
    });
    rows.sort((a, b) => (b.d + b.t).localeCompare(a.d + a.t));
    res.status(200).json({ ok: true, count: rows.length, rows: rows.slice(0, limit), note: '실시간 조회 · 서버에 저장하지 않음' });
  } catch (e) {
    const msg = String((e && e.message) || e);
    res.status(200).json({ ok: false, error: msg, hint: hintFor(msg) });
  }
};
