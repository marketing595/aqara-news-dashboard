// 범용 AI 도우미 (Gemini 프록시) — 세미나 담당자별 실행안 제안 등에 사용
// middleware가 보호하므로 @aqara.kr 로그인 사용자만 호출 가능. 필요 환경변수: GEMINI_API_KEY
// POST /api/ai-assist { system, prompt }
const MODELS = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-flash-latest'];

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  try {
    if (req.method !== 'POST') { res.status(405).json({ ok: false, error: 'POST only' }); return; }
    const key = (process.env.GEMINI_API_KEY || '').trim();
    if (!key) { res.status(200).json({ ok: false, error: 'NO_ENV', hint: 'Vercel 환경변수 GEMINI_API_KEY 등록 후 재배포하세요.' }); return; }
    let b = req.body; if (typeof b === 'string') { try { b = JSON.parse(b); } catch (e) { b = {}; } }
    b = b || {};
    const text = [(b.system || ''), (b.prompt || '')].filter(Boolean).join('\n\n');
    if (!text.trim()) { res.status(200).json({ ok: false, error: 'EMPTY' }); return; }

    let lastErr = '';
    for (const model of MODELS) {
      try {
        const r = await fetch('https://generativelanguage.googleapis.com/v1beta/models/' + model + ':generateContent?key=' + key, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ contents: [{ parts: [{ text }] }], generationConfig: { temperature: 0.7, maxOutputTokens: 2048 } }),
        });
        if (!r.ok) { lastErr = model + '_' + r.status; continue; }
        const d = await r.json();
        const out = (((d.candidates || [])[0] || {}).content || {}).parts?.map((p) => p.text || '').join('') || '';
        if (!out.trim()) { lastErr = model + '_EMPTY'; continue; }
        res.status(200).json({ ok: true, model, text: out });
        return;
      } catch (e) { lastErr = model + '_' + String((e && e.message) || e); }
    }
    res.status(200).json({ ok: false, error: lastErr || 'ALL_FAILED', hint: 'Gemini 호출 실패 — 키 유효성·사용량 한도를 확인하세요.' });
  } catch (e) {
    res.status(200).json({ ok: false, error: String((e && e.message) || e) });
  }
};
