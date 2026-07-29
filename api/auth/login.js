// 구글 로그인 시작 → 구글 동의화면으로 리다이렉트 (hd=aqara.kr 로 회사계정 우선)
const crypto = require('crypto');

function cookie(name, val, opt){
  opt = opt || {};
  let c = name + '=' + val + '; Path=/; SameSite=Lax; Secure';
  if(opt.httpOnly) c += '; HttpOnly';
  c += '; Max-Age=' + (opt.maxAge || 0);
  return c;
}

module.exports = function(req, res){
  const CID = process.env.GOOGLE_CLIENT_ID;
  if(!CID || !process.env.SESSION_SECRET){
    res.statusCode = 500;
    res.setHeader('Content-Type','text/html; charset=utf-8');
    res.end('로그인이 아직 설정되지 않았습니다. Vercel 환경변수(GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / SESSION_SECRET)를 등록한 뒤 재배포하세요.');
    return;
  }
  const proto = (req.headers['x-forwarded-proto'] || 'https').split(',')[0].trim();
  const host = req.headers['x-forwarded-host'] || req.headers.host;
  const redirectUri = proto + '://' + host + '/api/auth/callback';
  const state = crypto.randomBytes(16).toString('hex');
  let next = '/';
  try{ if(req.query && req.query.next) next = req.query.next; }catch(e){}
  res.setHeader('Set-Cookie', [
    cookie('__state', state, {maxAge:600, httpOnly:true}),
    cookie('__next', encodeURIComponent(next), {maxAge:600, httpOnly:true}),
  ]);
  const params = new URLSearchParams({
    client_id: CID,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: 'openid email profile',
    hd: (process.env.ALLOWED_DOMAIN || 'aqara.kr'),
    state: state,
    access_type: 'online',
    prompt: 'select_account',
  });
  res.statusCode = 302;
  res.setHeader('Location', 'https://accounts.google.com/o/oauth2/v2/auth?' + params.toString());
  res.end();
};
