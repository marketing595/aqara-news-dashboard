// 구글챗 알림 (Google Chat Incoming Webhook 프록시)
// ------------------------------------------------
// TASKS 탭에서 업무가 추가·이동되면 마케팅팀 채팅방에 한 줄 알립니다.
// 웹훅 URL에는 비밀 token이 들어 있어 브라우저에 내려보내면 안 되므로,
// 서버(이 파일)만 URL을 알고 브라우저는 /api/chat-notify 로 문구만 보냅니다.
// middleware가 보호하므로 @aqara.kr 로그인 사용자만 호출할 수 있습니다.
//
// 필요한 환경변수 (Vercel):
//   CHAT_WEBHOOK = https://chat.googleapis.com/v1/spaces/XXXX/messages?key=...&token=...
//   (구글챗 스페이스 → 스페이스 이름 옆 ▾ → 앱 및 통합 → 웹훅 추가 → URL 복사)
//   대상 스페이스 = 마케팅팀 방(space AAQAZ7Bg8Gg) — 웹훅은 그 방 안에서 만들어야 그 방으로 갑니다.
// 미설정이면 { ok:false, error:'NO_ENV' }를 돌려주고 대시보드는 조용히 넘어갑니다.
//
// POST /api/chat-notify { text: '보낼 문구', thread: '스레드키(선택)' }

const MAX = 2000;                      // 너무 긴 문구는 잘라서 보냄

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  try {
    if (req.method !== 'POST') { res.status(405).json({ ok: false, error: 'POST only' }); return; }

    const hook = (process.env.CHAT_WEBHOOK || '').trim();
    if (!hook) {
      res.status(200).json({ ok: false, error: 'NO_ENV',
        hint: 'Vercel 환경변수 CHAT_WEBHOOK(구글챗 웹훅 URL)을 등록한 뒤 재배포하세요.' });
      return;
    }
    if (!/^https:\/\/chat\.googleapis\.com\//.test(hook)) {
      res.status(200).json({ ok: false, error: 'BAD_ENV', hint: 'CHAT_WEBHOOK이 구글챗 웹훅 주소가 아닙니다.' });
      return;
    }

    let b = req.body; if (typeof b === 'string') { try { b = JSON.parse(b); } catch (e) { b = {}; } }
    b = b || {};
    const text = String(b.text || '').trim().slice(0, MAX);
    if (!text) { res.status(200).json({ ok: false, error: 'EMPTY' }); return; }

    // 같은 주제는 한 스레드로 묶어 채팅방이 지저분해지지 않게 한다(선택)
    let url = hook;
    const thread = String(b.thread || '').trim().slice(0, 60);
    if (thread) {
      url += (url.indexOf('?') > -1 ? '&' : '?') +
             'messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD';
    }
    const payload = thread ? { text, thread: { threadKey: thread } } : { text };

    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=UTF-8' },
      body: JSON.stringify(payload),
    });
    const body = await r.text();
    if (!r.ok) { res.status(200).json({ ok: false, error: 'CHAT_' + r.status, detail: body.slice(0, 300) }); return; }
    res.status(200).json({ ok: true });
  } catch (e) {
    res.status(200).json({ ok: false, error: String((e && e.message) || e) });
  }
};
