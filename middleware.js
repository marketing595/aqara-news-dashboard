// 사이트 전체 접근 제한(엣지 미들웨어)
//  - 로그인(유효한 __sess 쿠키) 없으면 /api/auth/login 으로 보냄 → 구글 로그인 → @aqara.kr만 통과
//  - GOOGLE_CLIENT_ID / SESSION_SECRET 환경변수가 없으면 '개방'(설정 완료 전 사이트가 잠기지 않도록)
//  - 정적 파일·데이터(json)까지 모두 이 미들웨어를 거치므로 함께 보호됨
export const config = {
  // /api/auth/* (로그인 처리) 와 내부 리소스는 제외하고 나머지 전부 보호
  // 파비콘 파일은 로그인 화면에서도 떠야 하므로 제외 대상에 포함
  matcher: ['/((?!api/auth|_next|favicon|apple-touch-icon|robots.txt|sitemap.xml).*)'],
};

function fromB64url(s){ s=s.replace(/-/g,'+').replace(/_/g,'/'); while(s.length%4) s+='='; return atob(s); }
function toB64url(bytes){ let s=''; for(let i=0;i<bytes.length;i++) s+=String.fromCharCode(bytes[i]); return btoa(s).replace(/=/g,'').replace(/\+/g,'-').replace(/\//g,'_'); }

async function verifySession(token, secret){
  if(!token || token.indexOf('.')<0) return null;
  const [p, sig] = token.split('.');
  try{
    const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), {name:'HMAC', hash:'SHA-256'}, false, ['sign']);
    const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(p));
    if(toB64url(new Uint8Array(mac)) !== sig) return null;
    const payload = JSON.parse(fromB64url(p));
    if(payload.exp && Math.floor(Date.now()/1000) > payload.exp) return null;
    return payload;
  }catch(e){ return null; }
}

function getCookie(req, name){
  const h = req.headers.get('cookie') || '';
  for(const part of h.split(';')){ const i=part.indexOf('='); if(i>-1 && part.slice(0,i).trim()===name) return part.slice(i+1).trim(); }
  return '';
}

export default async function middleware(req){
  const CID = process.env.GOOGLE_CLIENT_ID, SECRET = process.env.SESSION_SECRET;
  if(!CID || !SECRET) return;                 // 미설정 → 개방(설정 전 잠금 방지)
  const payload = await verifySession(getCookie(req,'__sess'), SECRET);
  if(payload && payload.email) return;        // 로그인 확인 → 통과
  const url = new URL(req.url);
  const login = new URL('/api/auth/login', url.origin);
  login.searchParams.set('next', url.pathname + url.search);
  return Response.redirect(login.toString(), 302);
}
