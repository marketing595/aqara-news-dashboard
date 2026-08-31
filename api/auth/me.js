// 지금 로그인한 사람이 누구인지 알려준다 (__sess 쿠키는 HttpOnly라 브라우저 JS가 직접 못 읽음)
//  → { email: 'yeojin@aqara.kr' }  또는  { email: '' }  (미로그인 · 로그인 설정 전)
// TASKS 탭에서 "내 업무만 보기"를 판단하는 데 쓴다.
const crypto = require('crypto');

function parseCookies(h){
  const o = {};
  (h || '').split(';').forEach(p=>{ const i=p.indexOf('='); if(i>-1) o[p.slice(0,i).trim()]=p.slice(i+1).trim(); });
  return o;
}

module.exports = function(req, res){
  res.setHeader('Content-Type','application/json; charset=utf-8');
  res.setHeader('Cache-Control','no-store');

  const SECRET = process.env.SESSION_SECRET;
  const tok = parseCookies(req.headers.cookie)['__sess'] || '';
  let email = '';

  if(SECRET && tok.indexOf('.') > -1){
    const i = tok.indexOf('.');
    const payload = tok.slice(0, i), sig = tok.slice(i+1);
    try{
      const mac = crypto.createHmac('sha256', SECRET).update(payload).digest('base64url');
      // 길이가 다르면 timingSafeEqual이 던지므로 먼저 확인
      const a = Buffer.from(mac), b = Buffer.from(sig);
      if(a.length === b.length && crypto.timingSafeEqual(a, b)){
        const p = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
        if(!p.exp || Math.floor(Date.now()/1000) <= p.exp) email = String(p.email || '').toLowerCase();
      }
    }catch(e){ email = ''; }
  }

  res.statusCode = 200;
  res.end(JSON.stringify({ email }));
};
