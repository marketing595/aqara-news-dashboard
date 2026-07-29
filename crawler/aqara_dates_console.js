/* ─────────────────────────────────────────────────────────────
   아카라 카페 작성일·조회수 수집 스니펫 (사장님 PC 브라우저용)
   사용법:
     1) 크롬에서 네이버 로그인 후  https://cafe.naver.com/aqara  접속
     2) F12 → [Console] 탭 클릭
     3) 아래 전체를 복사해 붙여넣고 Enter
     4) 잠시 후 aqara_dates.json 파일이 자동 다운로드됨
   ※ 비밀번호는 어디에도 저장하지 않습니다. 사장님 로그인 세션만 사용.
   ───────────────────────────────────────────────────────────── */
(async () => {
  const CLUB = '30394815';         // 아카라 스마트홈 카페 내부 ID
  const PER = 50;                   // 페이지당 글 수
  const MAX_PAGES = 80;            // 최대 페이지(≈4000글)
  const DELAY = 400;              // 페이지 간 대기(ms) — 서버 배려
  const out = {};
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  function normDate(ts) {
    if (ts == null) return '';
    if (typeof ts === 'number') { const d = new Date(ts > 1e12 ? ts : ts * 1000); return isNaN(d) ? '' : d.toISOString().slice(0, 10); }
    const m = String(ts).match(/(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})/);
    if (m) return `${m[1]}-${String(m[2]).padStart(2, '0')}-${String(m[3]).padStart(2, '0')}`;
    const d = new Date(ts); return isNaN(d) ? '' : d.toISOString().slice(0, 10);
  }
  function collect(list) {
    let n = 0;
    for (const raw of list) {
      const a = raw && raw.article ? raw.article : raw;
      if (!a || typeof a !== 'object') continue;
      const id = a.articleId || a.refArticleId || a.articleid;
      if (!id) continue;
      const ts = a.writeDateTimestamp ?? a.writeDate ?? a.writeDttm ?? a.registerDttm;
      const rc = (a.readCount ?? a.readcount ?? a.viewCount);
      out[id] = { date: normDate(ts), views: (rc != null ? rc : null) };
      n++;
    }
    return n;
  }
  // 응답 구조가 버전마다 달라서 article-like 배열을 재귀 탐색
  function findArrays(obj) {
    const res = [];
    (function walk(o) {
      if (Array.isArray(o)) {
        if (o.length && o.some(x => x && typeof x === 'object' && (x.articleId || (x.article && x.article.articleId)))) res.push(o);
        o.forEach(walk);
      } else if (o && typeof o === 'object') { Object.values(o).forEach(walk); }
    })(obj);
    return res;
  }
  const urls = p => [
    `https://apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json?search.clubid=${CLUB}&search.queryType=lastArticle&search.menuid=0&search.page=${p}&search.perPage=${PER}&ad=false`,
    `https://apis.naver.com/cafe-web/cafe-articleapi/v3/cafes/${CLUB}/menus/0/articles?page=${p}&pageSize=${PER}&sortBy=TIME&viewType=L`,
    `https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/${CLUB}/menus/0/articles?page=${p}&pageSize=${PER}&sortBy=TIME&viewType=L`,
    `https://apis.naver.com/cafe-web/cafe2/ArticleList.json?search.clubid=${CLUB}&search.menuid=0&search.boardtype=L&search.page=${p}&userDisplay=${PER}`,
  ];
  let good = -1, lastErr = '';
  for (let p = 1; p <= MAX_PAGES; p++) {
    let list = null, used = '';
    const tries = good >= 0 ? [urls(p)[good]] : urls(p);
    for (let i = 0; i < tries.length; i++) {
      try {
        const r = await fetch(tries[i], { credentials: 'include', headers: { 'Accept': 'application/json' } });
        if (!r.ok) { lastErr = 'HTTP ' + r.status + ' @ ' + tries[i]; continue; }
        const j = await r.json();
        const arrs = findArrays(j);
        if (arrs.length) { list = arrs.sort((a, b) => b.length - a.length)[0]; used = tries[i]; if (good < 0) good = urls(p).indexOf(tries[i]); break; }
        lastErr = 'no article array @ ' + tries[i] + ' :: ' + JSON.stringify(j).slice(0, 200);
      } catch (e) { lastErr = e.message + ' @ ' + tries[i]; }
    }
    if (!list || !list.length) { console.log(`⏹ page ${p}: 더 이상 데이터 없음 → 종료`); break; }
    const n = collect(list);
    console.log(`page ${p}: +${n}건 (누적 ${Object.keys(out).length})`);
    if (n === 0) break;
    await sleep(DELAY);
  }
  const keys = Object.keys(out);
  if (!keys.length) {
    console.error('❌ 수집 실패. 로그인 상태인지, cafe.naver.com/aqara 페이지에서 실행했는지 확인하세요.');
    console.error('마지막 오류:', lastErr);
    alert('데이터를 못 받았습니다.\n로그인 상태와 실행 페이지(cafe.naver.com/aqara)를 확인하고,\n콘솔의 빨간 오류 메시지를 복사해 전달해 주세요.');
    return;
  }
  const payload = { clubid: CLUB, generatedAt: new Date().toISOString(), count: keys.length, dates: out };
  const blob = new Blob([JSON.stringify(payload, null, 1)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'aqara_dates.json';
  document.body.appendChild(a); a.click(); a.remove();
  console.log(`✅ 완료: ${keys.length}건 → aqara_dates.json 다운로드됨. 이제 apply-aqara-dates.bat 을 더블클릭하세요.`);
  alert(`✅ ${keys.length}건 수집 완료!\naqara_dates.json 이 다운로드 폴더에 저장됐습니다.\n이제 apply-aqara-dates.bat 을 더블클릭하세요.`);
})();
