// 링크 미리보기 — 주소를 주면 대표이미지·제목·설명을 뽑아준다 (브랜드북 레퍼런스용)
// 브라우저에서 남의 사이트를 직접 읽으면 CORS에 막히므로 서버가 대신 읽어서 넘겨준다.
// middleware가 보호하므로 @aqara.kr 로그인 사용자만 호출 가능.
// GET /api/og-preview?url=https://...
const MAX_BYTES = 300 * 1024;      // 앞부분 300KB만 읽는다 (<head>만 있으면 충분)
const TIMEOUT_MS = 8000;

// 내부망 주소로 요청을 돌리는 공격(SSRF)을 막는다
function isBlockedHost(h) {
  h = (h || '').toLowerCase().replace(/^\[|\]$/g, '');
  if (!h || h === 'localhost' || h.endsWith('.localhost') || h.endsWith('.internal') || h.endsWith('.local')) return true;
  if (h === '::1' || h.startsWith('fc') || h.startsWith('fd') || h.startsWith('fe80')) return true;
  const m = h.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (m) {
    const a = +m[1], b = +m[2];
    if (a === 127 || a === 10 || a === 0 || a === 169) return true;
    if (a === 172 && b >= 16 && b <= 31) return true;
    if (a === 192 && b === 168) return true;
  }
  return false;
}

function decodeEntities(s) {
  return String(s || '')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&#0?39;|&apos;/g, "'").replace(/&nbsp;/g, ' ')
    .replace(/&#(\d+);/g, (_, d) => { try { return String.fromCharCode(+d); } catch (e) { return _; } })
    .replace(/&amp;/g, '&')
    .trim();
}

// <meta property="og:image" content="..."> — 속성 순서가 뒤바뀐 페이지도 있어 두 방향 모두 시도
function metaContent(html, names) {
  for (const name of names) {
    const n = name.replace(/[:.]/g, '\\$&');
    const pats = [
      new RegExp('<meta[^>]+(?:property|name)\\s*=\\s*["\']' + n + '["\'][^>]*content\\s*=\\s*["\']([^"\']*)["\']', 'i'),
      new RegExp('<meta[^>]+content\\s*=\\s*["\']([^"\']*)["\'][^>]*(?:property|name)\\s*=\\s*["\']' + n + '["\']', 'i'),
    ];
    for (const p of pats) { const m = html.match(p); if (m && m[1].trim()) return decodeEntities(m[1]); }
  }
  return '';
}

// 응답 앞부분만 바이트로 받아온다 (본문 전체를 받지 않기 위해)
async function readHead(r) {
  const reader = r.body && r.body.getReader ? r.body.getReader() : null;
  if (!reader) return Buffer.from(await r.arrayBuffer()).slice(0, MAX_BYTES);
  const chunks = [];
  let got = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(Buffer.from(value));
      got += value.length;
      if (got >= MAX_BYTES) { try { await reader.cancel(); } catch (e) {} break; }
    }
  } catch (e) { /* 읽다 끊겨도 지금까지 받은 만큼으로 파싱 */ }
  return Buffer.concat(chunks, Math.min(got, MAX_BYTES));
}

// 한글 사이트는 아직 EUC-KR도 있어서, 헤더·메타태그를 보고 인코딩을 정한 뒤 한 번만 디코딩한다
function decodeHtml(buf, ctypeHeader) {
  const ascii = buf.toString('latin1');                     // 인코딩 선언만 읽기 위한 임시 디코딩
  let cs = (String(ctypeHeader || '').match(/charset\s*=\s*["']?\s*([\w-]+)/i) || [])[1] || '';
  if (!cs) cs = (ascii.match(/<meta[^>]+charset\s*=\s*["']?\s*([\w-]+)/i) || [])[1] || '';
  cs = cs.toLowerCase().trim();
  if (!cs || cs === 'utf8') cs = 'utf-8';
  try { return new TextDecoder(cs, { fatal: false }).decode(buf); }
  catch (e) { return buf.toString('utf8'); }                // 모르는 인코딩이면 UTF-8로
}

module.exports = async (req, res) => {
  const fail = (error, extra) => {
    res.setHeader('Cache-Control', 'no-store');             // 실패는 캐시하지 않는다 (일시적 오류일 수 있으므로)
    res.status(200).json(Object.assign({ ok: false, error }, extra || {}));
  };
  try {
    const raw = (req.query && req.query.url) || '';
    if (!raw) { fail('NO_URL'); return; }

    let u;
    try { u = new URL(raw); } catch (e) { fail('BAD_URL'); return; }
    if (u.protocol !== 'http:' && u.protocol !== 'https:') { fail('BAD_SCHEME'); return; }
    if (isBlockedHost(u.hostname)) { fail('BLOCKED_HOST'); return; }

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    let r;
    try {
      r = await fetch(u.toString(), {
        redirect: 'follow', signal: ctrl.signal,
        headers: {
          // 봇을 막는 사이트가 많아 일반 브라우저처럼 요청한다
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
          'Accept': 'text/html,application/xhtml+xml',
          'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
        },
      });
    } catch (e) {
      clearTimeout(timer);
      fail((e && e.name === 'AbortError') ? 'TIMEOUT' : 'FETCH_FAIL', { url: u.toString() });
      return;
    }
    clearTimeout(timer);

    const finalUrl = r.url || u.toString();
    if (!r.ok) { fail('HTTP_' + r.status, { url: finalUrl }); return; }

    const ctype = (r.headers.get('content-type') || '').toLowerCase();
    // 같은 주소를 여러 명이 붙여넣어도 한 번만 긁도록 CDN에 하루 캐시
    res.setHeader('Cache-Control', 's-maxage=86400, stale-while-revalidate=604800');

    if (ctype.startsWith('image/')) {           // 이미지 주소를 그대로 붙여넣은 경우
      try { r.body && r.body.cancel && r.body.cancel(); } catch (e) {}
      const name = decodeURIComponent((u.pathname.split('/').pop() || '').trim());
      res.status(200).json({ ok: true, url: finalUrl, image: finalUrl, title: name, desc: '', site: u.hostname.replace(/^www\./, '') });
      return;
    }
    if (ctype && !ctype.includes('html') && !ctype.includes('xml')) {
      try { r.body && r.body.cancel && r.body.cancel(); } catch (e) {}
      fail('NOT_HTML', { url: finalUrl });
      return;
    }

    const html = decodeHtml(await readHead(r), ctype);

    let image = metaContent(html, ['og:image:secure_url', 'og:image:url', 'og:image', 'twitter:image', 'twitter:image:src']);
    if (!image) {                               // og 태그가 없으면 사이트 아이콘이라도
      const li = html.match(/<link[^>]+rel\s*=\s*["'][^"']*(?:apple-touch-icon|icon)[^"']*["'][^>]*href\s*=\s*["']([^"']+)["']/i);
      if (li) image = decodeEntities(li[1]);
    }
    if (image) { try { image = new URL(image, finalUrl).toString(); } catch (e) { image = ''; } }

    let title = metaContent(html, ['og:title', 'twitter:title']);
    if (!title) { const t = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i); if (t) title = decodeEntities(t[1].replace(/\s+/g, ' ')); }

    const desc = metaContent(html, ['og:description', 'twitter:description', 'description']);
    const site = metaContent(html, ['og:site_name']) || u.hostname.replace(/^www\./, '');

    res.status(200).json({
      ok: true, url: finalUrl,
      title: title.slice(0, 200), desc: desc.slice(0, 300),
      image, site: site.slice(0, 80),
    });
  } catch (e) {
    fail(String((e && e.message) || e));
  }
};
