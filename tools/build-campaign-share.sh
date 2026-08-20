#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# L100 캠페인 효과 분석 — 외부 공유용(보고용) 정적 페이지 생성기
#
#   web/index.html 의 캠페인 리포트(#campReport)를 헤드리스 Edge로 실제 렌더한 뒤,
#   그 결과 HTML을 그대로 굳혀서 web/campaign-l100.html 을 만든다.
#   · 차트(canvas)는 PNG로 구워서 <img>로 박는다 → Chart.js·데이터 파일이 필요 없다
#   · 편집·업로드·선택 같은 인터랙티브 컨트롤은 제거한다 (읽기 전용 보고서)
#   · 이 페이지 하나만 미들웨어 예외로 공개되므로, 다른 데이터(json)는 노출되지 않는다
#
# 리포트 내용이 바뀌면 이 스크립트를 다시 돌려서 페이지를 갱신한다.
#   bash tools/build-campaign-share.sh
# ------------------------------------------------------------------------------
set -e
WEB="$(cd "$(dirname "$0")/.." && pwd)"
TMP="${TMPDIR:-/tmp}/campshare.$$"
EDGE="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
[ -f "$EDGE" ] || EDGE="/c/Program Files/Microsoft/Edge/Application/msedge.exe"
DRIVE="https://drive.google.com/drive/folders/1v6TPaMPylZ8WTBdGU2TfP5UHK3yGMGJw"

mkdir -p "$TMP"
cp "$WEB"/index.html "$WEB"/*.json "$TMP"/ 2>/dev/null || true
cd "$TMP"

# ── 1. 리포트를 실제로 렌더시키는 하네스 페이지 ────────────────────────────────
N=$(grep -n "</body>" index.html | tail -1 | cut -d: -f1)
{
  head -3 index.html
  echo '<script>window.__ERR=[];window.onerror=function(m,s,l,c){window.__ERR.push(m+" @"+l+":"+c)};</script>'
  sed -n "4,$((N-1))p" index.html
  cat <<'EOS'
<script>
// 캠페인 뷰를 body 직속으로 꺼내 보이게 만든다(숨겨진 상태면 canvas 크기가 0이라 차트가 안 구워진다)
setTimeout(function(){
  try{
    var v=document.getElementById("view-campaign");
    document.body.appendChild(v); v.classList.remove("hidden");
    v.style.width="1360px"; v.style.display="block";
    loadReports(function(){ try{ curCampaign="l100"; renderCampaign("l100"); }
                            catch(e){ window.__ERR.push("render:"+e.message); } });
  }catch(e){ window.__ERR.push("load:"+e.message); }
},1500);
// 차트를 PNG로 굽고, 리포트 HTML만 남긴다
setTimeout(function(){
  var el=document.getElementById("campReport"), sizes=[];
  try{
    el.querySelectorAll("canvas").forEach(function(c){
      var url=""; try{ url=c.toDataURL("image/png"); }catch(e){ url=""; }
      sizes.push(c.id+":"+url.length);
      var img=document.createElement("img");
      img.src=url; img.alt=c.id; img.style.width="100%"; img.style.height="auto";
      c.parentNode.replaceChild(img,c);
    });
  }catch(e){ window.__ERR.push("canvas:"+e.message); }
  var html=el.innerHTML||"";
  document.body.innerHTML='<div id="SNAPSTART"></div>'+html+'<div id="SNAPEND"></div>';
  document.title="ERR="+(window.__ERR.join(" | ")||"none")+" | LEN="+html.length+" | "+sizes.join(" ");
},10000);
</script>
EOS
  sed -n "${N},\$p" index.html
} > snap.html

"$EDGE" --headless --disable-gpu --allow-file-access-from-files --window-size=1400,2400 \
        --virtual-time-budget=22000 --dump-dom "file:///$(pwd -W 2>/dev/null || pwd)/snap.html" 2>/dev/null > out.html
TITLE=$(grep -o '<title>[^<]*</title>' out.html | head -1)
echo "  렌더 결과: $TITLE"
case "$TITLE" in *"ERR=none"*) ;; *) echo "  ✕ 렌더 중 오류 — 중단합니다"; exit 1;; esac

# ── 2. 인터랙티브 컨트롤 제거 ─────────────────────────────────────────────────
awk '/id="SNAPSTART"/{f=1;next} /id="SNAPEND"/{f=0} f' out.html > body_raw.html
[ -s body_raw.html ] || { echo "  ✕ 리포트 본문을 추출하지 못했습니다"; exit 1; }

sed -E \
  -e 's/<div class="chart-dl">[^<]*<\/div>//g' \
  -e '/toggleIrEdit\(\)/d' \
  -e '/id="seoCapFile"/d' \
  -e '/id="campBanFile"/d' \
  -e '/이미지 넣기</d' \
  -e '/rvSeoClear\(\)/d' \
  -e "/getElementById\('seoCapFile'\)/d" \
  -e '/campPickAll\(/d' \
  -e 's/ contenteditable="true"//g' \
  -e 's/ onclick="[^"]*"//g' \
  -e 's/ onchange="[^"]*"//g' \
  -e 's/ oninput="[^"]*"//g' \
  -e 's/\. \[[^]]*\]로 올려주세요\./ (보고 시점 기준)./g' \
  body_raw.html > body.html

cp body.html body_final.html

# ── 3. 공유 페이지 조립 ───────────────────────────────────────────────────────
STAMP=$(date +%Y-%m-%d)
{
  cat <<EOS
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="robots" content="noindex, nofollow, noarchive" />
<title>L100 스마트 도어락 캠페인 효과 분석 · 아카라라이프</title>
<link rel="icon" href="/favicon.png?v=4" sizes="32x32" type="image/png" />
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin />
<link rel="stylesheet" as="style" crossorigin
      href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css" />
<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config = { theme: { extend: {
  colors: { brand:{DEFAULT:'#FBC400',ink:'#8A6A00'}, ink:'#1D1D1F', muted:'#6E6E73',
            agreen:'#5E7350', aorange:'#C77A34', ablue:'#5E85A6', ared:'#BF5332', agray:'#6E6E73' },
  fontFamily: { sans: ['"Pretendard Variable"','Pretendard','system-ui','"Malgun Gothic"','sans-serif'] }
} } };
</script>
<style>
  :root{ --aqara:#FBC400; --ink:#1D1D1F; --muted:#6E6E73; --line:#E6E6E3; --bg:#F4F4F2; }
  body{ background:var(--bg); color:var(--ink);
    font-family:"Pretendard Variable",Pretendard,-apple-system,system-ui,"Malgun Gothic",sans-serif;
    -webkit-font-smoothing:antialiased; letter-spacing:-0.015em; line-height:1.6; word-break:keep-all;
    font-feature-settings:"tnum" 1; }
  h1,h2,h3{ letter-spacing:-0.025em; }
  .num{ font-feature-settings:"tnum" 1; letter-spacing:-0.02em; }
  .card{ background:#fff; border:1px solid var(--line); border-radius:16px; box-shadow:0 1px 2px rgba(0,0,0,.03); }
  .accent::before{ content:none; }
  table thead th{ background:#F7F7F5; color:#8A8A8E; font-weight:600; border-bottom:1px solid var(--line); }
  a.lnk{ color:var(--ink); text-decoration:none; }
  a.lnk:hover{ text-decoration:underline; }
  .chart-dl{ display:none !important; }
  img[alt\$="Chart"]{ display:block; }
  ::selection{ background:rgba(251,196,0,.25); }
  @media print{ .noprint{ display:none !important; } body{ background:#fff; } }
</style>
</head>
<body class="text-ink">
<header class="bg-ink text-white">
  <div class="max-w-[1200px] mx-auto px-5 py-4 flex flex-wrap items-center justify-between gap-3">
    <div>
      <p class="text-[11px] font-extrabold tracking-wider text-brand">AQARA LIFE · CAMPAIGN REPORT</p>
      <h1 class="text-[19px] sm:text-[22px] font-extrabold leading-tight mt-0.5">L100 스마트 도어락 캠페인 효과 분석</h1>
    </div>
    <div class="text-right">
      <p class="text-[11px] text-white/50">보고용 공유 페이지</p>
      <p class="text-[12px] font-semibold num">기준 ${STAMP}</p>
    </div>
  </div>
</header>
<div class="bg-[#FDF7F5] border-b border-[#F0D9D2] noprint">
  <div class="max-w-[1200px] mx-auto px-5 py-2">
    <p class="text-[11.5px] text-[#BF5332]">🔒 <b>대외비</b> — 매출·이익률·집행비 등 내부 수치가 포함되어 있습니다. 링크를 아는 사람은 누구나 열 수 있으니 공유 범위에 유의해 주세요.</p>
  </div>
</div>
<main class="max-w-[1200px] mx-auto px-5 py-6">
EOS
  cat body_final.html
  cat <<EOS
</main>
<footer class="max-w-[1200px] mx-auto px-5 pb-10">
  <p class="text-[11px] text-slate-400">아카라라이프 마케팅팀 · 이 페이지는 마케팅 포털의 캠페인 리포트를 ${STAMP} 기준으로 굳힌 사본입니다. 최신 수치는 포털에서 확인하세요.</p>
</footer>
</body>
</html>
EOS
} > "$WEB/campaign-l100.html"

echo "  ✓ 생성 완료: web/campaign-l100.html ($(wc -c < "$WEB/campaign-l100.html") bytes)"
rm -rf "$TMP"
