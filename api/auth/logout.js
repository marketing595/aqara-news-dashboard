// 로그아웃 → 세션 쿠키 삭제 후 홈으로
module.exports = function(req, res){
  res.statusCode = 302;
  res.setHeader('Set-Cookie', '__sess=; Path=/; SameSite=Lax; Secure; HttpOnly; Max-Age=0');
  res.setHeader('Location', '/');
  res.end();
};
