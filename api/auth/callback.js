// 구글 로그인 콜백 → 토큰 교환 → @aqara.kr 검증 → 세션 쿠키 발급
const crypto = require('crypto');

function cookie(name, val, opt){
  opt = opt || {};
  let c = name + '=' + val + '; Path=/; SameSite=Lax; Secure';
  if(opt.httpOnly) c += '; HttpOnly';
  c += '; Max-Age=' + (opt.maxAge || 0);
  return c;
}
function parseCookies(h){
  const o = {};
  (h || '').split(';').forEach(p=>{ const i=p.indexOf('='); if(i>-1) o[p.slice(0,i).trim()]=p.slice(i+1).trim(); });
  return o;
}
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

module.exports = async function(req, res){
  const CID = process.env.GOOGLE_CLIENT_ID, CSEC = process.env.GOOGLE_CLIENT_SECRET, SECRET = process.env.SESSION_SECRET;
  if(!CID || !CSEC || !SECRET){ res.statusCode=500; res.end('로그인 설정 미완료'); return; }

  const q = req.query || {};
  const code = q.code, state = q.state;
  const cookies = parseCookies(req.headers.cookie);
  if(!code || !state || state !== cookies['__state']){
    res.statusCode = 400;
    res.setHeader('Content-Type','text/html; charset=utf-8');
    res.end('로그인 상태 검증에 실패했습니다. <a href="/api/auth/login">다시 로그인</a>');
    return;
  }
  const proto = (req.headers['x-forwarded-proto'] || 'https').split(',')[0].trim();
  const host = req.headers['x-forwarded-host'] || req.headers.host;
  const redirectUri = proto + '://' + host + '/api/auth/callback';

  let tok;
  try{
    const r = await fetch('https://oauth2.googleapis.com/token', {
      method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body: new URLSearchParams({ code, client_id:CID, client_secret:CSEC, redirect_uri:redirectUri, grant_type:'authorization_code' }),
    });
    tok = await r.json();
  }catch(e){ res.statusCode=502; res.end('구글 토큰 교환 오류'); return; }
  if(!tok || !tok.id_token){ res.statusCode=401; res.end('토큰 교환 실패'); return; }

  let info;
  try{
    const r = await fetch('https://oauth2.googleapis.com/tokeninfo?id_token=' + encodeURIComponent(tok.id_token));
    info = await r.json();
  }catch(e){ res.statusCode=502; res.end('토큰 검증 오류'); return; }

  const domain = (process.env.ALLOWED_DOMAIN || 'aqara.kr').toLowerCase();
  const email = (info.email || '').toLowerCase();
  const verified = info.email_verified === true || info.email_verified === 'true';
  const ok = !info.error && info.aud === CID && verified && email.endsWith('@' + domain);
  if(!ok){
    res.statusCode = 403;
    res.setHeader('Content-Type','text/html; charset=utf-8');
    res.end('<!doctype html><meta charset="utf-8"><body style="font-family:system-ui,-apple-system,sans-serif;padding:48px;text-align:center;color:#26282A">'
      + '<h2 style="margin-bottom:8px">접근 권한이 없습니다</h2>'
      + '<p style="color:#666;line-height:1.6">' + esc(info.email || '해당 계정') + ' 은(는) 허용되지 않습니다.<br><b>@' + esc(domain) + '</b> 회사 이메일로 로그인해 주세요.</p>'
      + '<p style="margin-top:24px"><a href="/api/auth/login" style="background:#26282A;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">다시 로그인</a></p></body>');
    return;
  }

  const exp = Math.floor(Date.now()/1000) + 7*24*3600;   // 7일 유지
  const payload = Buffer.from(JSON.stringify({ email, exp })).toString('base64url');
  const sig = crypto.createHmac('sha256', SECRET).update(payload).digest('base64url');
  const sess = payload + '.' + sig;

  let next = '/';
  try{ next = decodeURIComponent(cookies['__next'] || '/'); }catch(e){}
  if(!next.startsWith('/')) next = '/';

  res.statusCode = 302;
  res.setHeader('Set-Cookie', [
    cookie('__sess', sess, {maxAge:7*24*3600, httpOnly:true}),
    cookie('__state', '', {maxAge:0, httpOnly:true}),
    cookie('__next', '', {maxAge:0, httpOnly:true}),
  ]);
  res.setHeader('Location', next);
  res.end();
};
