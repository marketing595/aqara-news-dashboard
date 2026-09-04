// 홈페이지 문의 인입 '실시간' 집계 (아임웹 Open API 2.0 프록시)
// ------------------------------------------------------------------
// · 대시보드 홈페이지 탭이 열릴 때 아임웹에서 바로 받아 homepage.json과 똑같은 모양으로 돌려준다.
//   (homepage.json은 매일 1회 도는 GitHub Actions 결과물이라 토큰이 만료되면 그대로 멈춘다.
//    이 API가 1순위, 실패하면 화면이 homepage.json으로 자동 폴백한다.)
// · 개인정보는 담지 않는다 — 접수 일시 / 폼 이름 / 선택형(라디오·체크박스) 응답만.
//   자유입력 '내용'은 별도의 /api/imweb-inquiries(조회 전용)에서만 다룬다.
// · middleware.js가 이 경로를 보호하므로 구글 로그인(@aqara.kr)한 사람만 호출할 수 있다.
//
// GET /api/homepage-live
const { getToken, api, resolveUnit, fetchAll, parseTime, hintFor } = require('./_imweb');

// 항목 제목에 아래 단어가 들어가면 무조건 제외(개인정보 이중 안전장치)
const PII_WORDS = ['이름', '성함', '성명', '연락처', '전화', '휴대', '핸드폰', '메일', 'mail', '주소',
  '내용', '문의내용', '상세', '요청사항', '회사명', '상호', '생년', '카톡', '아이디'];
// 선택형 항목만 태그로 보관
const CHOICE_TYPES = ['select', 'radio', 'checkbox', 'check', 'dropdown', 'agree'];

function cleanTags(items) {
  const tags = {};
  (items || []).forEach((it) => {
    const subj = (it.itemSubject || '').toString().trim();
    if (!subj) return;
    const low = subj.toLowerCase();
    if (PII_WORDS.some((w) => low.indexOf(w) >= 0)) return;
    const itype = (it.itemType || '').toString().toLowerCase();
    if (!CHOICE_TYPES.some((t) => itype.indexOf(t) >= 0)) return;
    let val = (it.value || '').toString().trim();
    if (!val && Array.isArray(it.valueList)) val = it.valueList.filter(Boolean).join(', ');
    val = val.replace(/[\r\n]+/g, ' ').trim();
    if (!val || val.length > 40) return;
    tags[subj] = val;
  });
  return tags;
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');   // 항상 최신
  try {
    const token = await getToken();
    const unit = await resolveUnit(token);

    const [formList, subList] = await Promise.all([
      fetchAll(token, '/community/forms', unit),
      fetchAll(token, '/community/form-submissions', unit),
    ]);

    const forms = formList.map((f) => ({
      formNo: f.formNo,
      boardCode: f.boardCode || f.formCode,
      name: (f.formName || '').toString(),
    }));
    const nameOf = {};
    forms.forEach((f) => { nameOf[f.formNo] = f.name; });

    const rows = [];
    subList.forEach((s) => {
      const { d, h } = parseTime(s.wtime);
      if (!d) return;
      rows.push({
        d, h,
        form: (s.formName || nameOf[s.formNo] || '문의').toString(),
        tags: cleanTags(s.item),
      });
    });
    rows.sort((a, b) => (a.d === b.d ? (a.h || 0) - (b.h || 0) : a.d < b.d ? -1 : 1));

    const monthly = {};
    rows.forEach((r) => {
      const m = r.d.slice(0, 7);
      if (!monthly[m]) monthly[m] = {};
      monthly[m][r.form] = (monthly[m][r.form] || 0) + 1;
    });

    res.status(200).json({
      ok: true,
      generatedAt: new Date().toISOString().slice(0, 19) + 'Z',
      source: 'imweb-api',
      live: true,
      site: 'www.aqaralife.kr',
      unitCode: unit,
      totalCount: rows.length,
      forms, monthly, submissions: rows,
    });
  } catch (e) {
    const msg = String((e && e.message) || e);
    res.status(200).json({ ok: false, error: msg, hint: hintFor(msg) });
  }
};
