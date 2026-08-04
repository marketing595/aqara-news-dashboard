// 환경변수 점검 — 값은 절대 보여주지 않고 '들어와 있는지(true/false)'와 '이름'만 알려준다.
// 브라우저에서 https://aqara-news-dashboard.vercel.app/api/env-check 를 열면 JSON이 뜬다.
// (middleware가 보호하므로 @aqara.kr 로그인 사용자만 볼 수 있다)
const WATCH = [
  'GEMINI_API_KEY',
  'IMWEB_CLIENT_ID', 'IMWEB_CLIENT_SECRET', 'IMWEB_REFRESH_TOKEN', 'IMWEB_UNIT_CODE',
  'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'SESSION_SECRET',
];

module.exports = (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  const has = (n) => !!(process.env[n] || '').trim();
  const keys = {};
  WATCH.forEach((n) => { keys[n] = has(n) ? '등록됨' : '없음'; });

  // 오타 잡기용 — 비슷한 이름의 변수 '이름만' 나열(값 노출 없음)
  const similar = Object.keys(process.env)
    .filter((k) => /GEMINI|IMWEB|GOOGLE|SESSION|API|KEY|TOKEN|SECRET/i.test(k))
    .filter((k) => !/^(AWS|VERCEL_OIDC)/i.test(k))
    .sort();

  res.status(200).json({
    ok: true,
    안내: '값은 표시하지 않습니다. 이 화면을 그대로 캡처해 공유해도 안전합니다.',
    배포환경: process.env.VERCEL_ENV || '(local)',
    배포커밋: (process.env.VERCEL_GIT_COMMIT_SHA || '').slice(0, 7),
    커밋메시지: (process.env.VERCEL_GIT_COMMIT_MESSAGE || '').split('\n')[0],
    확인: keys,
    비슷한이름의_변수들: similar,
  });
};
