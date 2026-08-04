// 블로그 글 AI 초안 작성 (Gemini 프록시)
// ------------------------------------------------------------------
// · 블로그별 '컨셉(결)'과 사용자가 넣은 SEO 키워드를 프롬프트에 넣어 본문 초안을 만든다.
// · middleware.js가 이 경로를 보호하므로 구글 로그인(@aqara.kr)한 사람만 호출할 수 있다.
// · 필요한 Vercel 환경변수: GEMINI_API_KEY (GitHub Secrets에 있는 값과 동일)
//
// POST /api/blog-draft  { blog, concept, topic, keywords:[], tone, length }
const MODELS = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-flash-latest'];

function buildPrompt(b) {
  const kw = (b.keywords || []).filter(Boolean);
  const lenMap = { short: '900~1,200자', mid: '1,500~2,000자', long: '2,500~3,000자' };
  return [
    '당신은 스마트홈·인테리어 브랜드 「아카라라이프」의 네이버 블로그 콘텐츠 에디터입니다.',
    '아래 조건으로 네이버 블로그에 바로 올릴 수 있는 한국어 초안을 작성하세요.',
    '',
    '[블로그] ' + (b.blog || '아카라라이프'),
    '[이 블로그의 결(컨셉)] ' + (b.concept || ''),
    '[이번 글 주제] ' + (b.topic || '컨셉에 맞는 주제를 직접 정해서 쓸 것'),
    '[톤] ' + (b.tone || '컨셉에 맞는 톤'),
    '[분량] ' + (lenMap[b.length] || lenMap.mid),
    kw.length ? '[반드시 반영할 SEO 키워드] ' + kw.join(', ') : '[SEO 키워드] 주제에 맞는 키워드를 직접 선정',
    '',
    '작성 규칙:',
    '1) SEO 키워드는 제목·첫 문단·소제목·본문에 자연스럽게 배치한다. 억지로 반복하지 말고,',
    '   핵심 키워드는 본문 전체에서 3~5회, 나머지는 1~2회 정도로 쓴다.',
    '2) 소제목(H2)을 3~5개 넣고, 문단은 2~4줄로 짧게 끊어 모바일에서 읽기 좋게 쓴다.',
    '3) 과장·단정 표현과 의학적/절대적 효과 주장은 쓰지 않는다. 가격·수치는 확인되지 않으면 쓰지 않는다.',
    '4) 블로그의 결에 맞는 화자를 유지한다(공식=전문적, 일상 블로그=1인칭 경험담).',
    '5) 마지막에 자연스러운 마무리 + 행동 유도(문의/방문/댓글) 한 문장.',
    '',
    '아래 JSON 형식으로만 응답한다(코드블록 없이 JSON만):',
    '{',
    '  "titles": ["제목 후보 3개(각 32자 내외, 키워드 포함)"],',
    '  "meta": "검색 결과에 노출될 요약문 1문장(80자 내외)",',
    '  "outline": ["소제목1", "소제목2", "소제목3"],',
    '  "body": "소제목을 포함한 본문 전체(줄바꿈 \\n 사용)",',
    '  "tags": ["네이버 블로그 태그 8~12개"],',
    '  "keywordUsage": [{"keyword": "키워드", "count": 3}],',
    '  "imageGuide": "이미지 촬영·배치 가이드 2~3문장"',
    '}',
  ].join('\n');
}

async function callGemini(key, prompt) {
  let lastErr = '';
  for (const model of MODELS) {
    const url = 'https://generativelanguage.googleapis.com/v1beta/models/' + model + ':generateContent?key=' + key;
    try {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: { temperature: 0.85, maxOutputTokens: 4096, responseMimeType: 'application/json' },
        }),
      });
      if (!r.ok) { lastErr = model + '_' + r.status; continue; }
      const d = await r.json();
      const txt = (((d.candidates || [])[0] || {}).content || {}).parts?.map((p) => p.text || '').join('') || '';
      if (!txt.trim()) { lastErr = model + '_EMPTY'; continue; }
      return { model, text: txt };
    } catch (e) {
      lastErr = model + '_' + String((e && e.message) || e);
    }
  }
  throw new Error(lastErr || 'ALL_MODELS_FAILED');
}

function parseDraft(txt) {
  const s = txt.replace(/^```(?:json)?/i, '').replace(/```$/, '').trim();
  try { return JSON.parse(s); } catch (e) {}
  const m = s.match(/\{[\s\S]*\}/);
  if (m) { try { return JSON.parse(m[0]); } catch (e) {} }
  return { body: s };            // JSON이 아니면 본문 텍스트로 취급
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  try {
    if (req.method !== 'POST') { res.status(405).json({ ok: false, error: 'POST only' }); return; }
    const key = (process.env.GEMINI_API_KEY || '').trim();
    if (!key) {
      res.status(200).json({ ok: false, error: 'NO_ENV', hint: 'Vercel 환경변수 GEMINI_API_KEY 를 등록한 뒤 재배포하세요. (GitHub Secrets에 있는 값과 동일)' });
      return;
    }
    let b = req.body;
    if (typeof b === 'string') { try { b = JSON.parse(b); } catch (e) { b = {}; } }
    b = b || {};
    const out = await callGemini(key, buildPrompt(b));
    const draft = parseDraft(out.text);
    res.status(200).json({ ok: true, model: out.model, draft });
  } catch (e) {
    const msg = String((e && e.message) || e);
    res.status(200).json({ ok: false, error: msg, hint: 'Gemini 호출에 실패했습니다. 키가 유효한지, 사용량 한도를 넘지 않았는지 확인하세요.' });
  }
};
