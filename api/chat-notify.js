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
// POST /api/chat-notify { text: '보낼 문구', thread: '스레드키(선택)',
//                          card: { title, subtitle, body, url, image }  ← 있으면 카드로 보냄 }
//
// 보내는 사람 이름·아이콘은 **웹훅을 만들 때 정한 이름/아바타**를 따릅니다(메시지로는 못 바꿉니다.
// Chat API의 sender는 읽기 전용). 이름이 '알 수 없는 사용자'로 보이면 구글챗 스페이스의
// [앱 및 통합 → 웹훅 관리]에서 그 웹훅의 이름과 아바타 URL을 채워 넣으면 됩니다.
// 그래서 메시지 자체에도 제목이 보이도록 카드(cardsV2) 형태로 보내고, 카드가 거부되면 일반 텍스트로 재시도합니다.

const MAX = 2000;                      // 너무 긴 문구는 잘라서 보냄
const AVATAR = 'https://aqara-news-dashboard.vercel.app/favicon-192.png';   // 로그인 없이 열리는 경로

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
    const withThread = (p) => (thread ? Object.assign({}, p, { thread: { threadKey: thread } }) : p);

    // 카드 — 메시지 안에 제목·아이콘이 함께 보이게 한다
    const c = b.card && typeof b.card === 'object' ? b.card : null;
    const cardPayload = c && String(c.title || '').trim() ? withThread({
      cardsV2: [{
        cardId: 'aqara-tasks',
        card: {
          header: {
            title: String(c.title).slice(0, 120),
            subtitle: String(c.subtitle || '').slice(0, 160),
            imageUrl: String(c.image || AVATAR),
            imageType: 'CIRCLE',
          },
          sections: [{
            widgets: [].concat(
              String(c.body || '').trim()
                ? [{ decoratedText: { text: String(c.body).slice(0, 800), wrapText: true } }] : [],
              String(c.url || '').trim()
                ? [{ buttonList: { buttons: [{ text: '대시보드 열기',
                      onClick: { openLink: { url: String(c.url) } } }] } }] : []
            ),
          }],
        },
      }],
    }) : null;

    const post = async (payload) => {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=UTF-8' },
        body: JSON.stringify(payload),
      });
      return { ok: r.ok, status: r.status, body: await r.text() };
    };

    if (cardPayload) {
      const r1 = await post(cardPayload);
      if (r1.ok) { res.status(200).json({ ok: true, mode: 'card' }); return; }
      // 카드가 거부되면 알림을 놓치지 않도록 일반 텍스트로 다시 보낸다
      const r2 = await post(withThread({ text }));
      if (r2.ok) { res.status(200).json({ ok: true, mode: 'text', cardError: 'CHAT_' + r1.status }); return; }
      res.status(200).json({ ok: false, error: 'CHAT_' + r2.status, detail: r2.body.slice(0, 300) });
      return;
    }

    const r = await post(withThread({ text }));
    if (!r.ok) { res.status(200).json({ ok: false, error: 'CHAT_' + r.status, detail: r.body.slice(0, 300) }); return; }
    res.status(200).json({ ok: true, mode: 'text' });
  } catch (e) {
    res.status(200).json({ ok: false, error: String((e && e.message) || e) });
  }
};
