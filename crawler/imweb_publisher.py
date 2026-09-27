# -*- coding: utf-8 -*-
"""아카라라이프 자사 블로그(아임웹) 자동 포스팅 — 검수용 '비공개 초안' 등록 전용

  안전장치: 이 스크립트는 어떤 경우에도 글을 '공개'로 올리지 않는다.
  항상 비공개(draft)로 등록하고, 최종 발행은 아임웹 관리자 화면에서 사람이 누른다.

사용법
  python imweb_publisher.py --file ../../drafts/2026-09-27-smarthome-package.html
  python imweb_publisher.py --file draft.html --title "제목 직접 지정" --dry-run
  python imweb_publisher.py --check          # .env 설정만 점검하고 종료

.env (이 파일과 같은 폴더 또는 상위 폴더에 두면 자동으로 찾는다. git에 올리지 말 것)
  ── 방식 1: legacy (아임웹 API v2 · API Key/Secret) ────────────────────
  IMWEB_API_MODE=legacy
  IMWEB_API_KEY=...            # 아임웹 관리자 > 개발자 > API Key
  IMWEB_SECRET_KEY=...         # Secret Key
  IMWEB_BOARD_CODE=...         # 글을 올릴 게시판 코드

  ── 방식 2: oauth (아임웹 Open API 2.0 · openapi.imweb.me) ─────────────
  IMWEB_API_MODE=oauth
  IMWEB_CLIENT_ID=...          # 개발자센터 앱 Client ID
  IMWEB_CLIENT_SECRET=...      # Client Secret
  IMWEB_REFRESH_TOKEN=...      # Get-ImwebToken.ps1 로 1회 발급(90일)
  IMWEB_BOARD_CODE=...
  IMWEB_UNIT_CODE=...          # (선택) 없으면 /site-info 로 자동 조회

  ── 공통(선택) ────────────────────────────────────────────────────────
  IMWEB_API_BASE=...           # 엔드포인트 호스트를 직접 지정할 때
  IMWEB_POSTS_PATH=/v2/board/posts
  IMWEB_CATEGORY=...           # 게시판 카테고리 코드
  IMWEB_AUTHOR=아카라라이프

※ 같은 폴더의 Get-ImwebToken.ps1 로 이미 연동해 둔 계정은 방식 2(oauth)를 쓴다.
  방식 1은 아임웹 구 API(api.imweb.me/v2) 기준이며, 계정/게시판이 구 API 글쓰기를
  지원하는지 먼저 --dry-run 으로 payload를 확인한 뒤 실제 전송할 것.
"""
import argparse
import json
import os
import re
import sys

try:
    import requests
except ImportError:
    sys.exit("requests 모듈이 필요합니다.  pip install -r requirements.txt")

HERE = os.path.dirname(os.path.abspath(__file__))

LEGACY_BASE = "https://api.imweb.me"
OAUTH_BASE = "https://openapi.imweb.me"

# 아임웹이 게시판/버전마다 다른 이름을 쓰기 때문에, 비공개를 뜻하는 필드를 한 번에 채운다.
DRAFT_FIELDS = {
    "status": "DRAFT",      # 초안
    "isDraft": True,
    "isPublic": False,      # 공개 여부
    "is_notice": False,
    "isSecret": True,       # 비밀글(관리자만 열람)
}


# ───────────────────────── .env ─────────────────────────
def load_env(explicit=None):
    """.env 를 찾아 os.environ 에 얹는다(이미 있는 환경변수가 우선)."""
    cands = [explicit] if explicit else [
        os.path.join(HERE, ".env"),
        os.path.join(os.path.dirname(HERE), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(HERE)), ".env"),
    ]
    for path in cands:
        if not path or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        return path
    return None


def env(name, default=""):
    return os.environ.get(name, default).strip()


# ───────────────────────── 토큰 ─────────────────────────
def token_legacy(api_key, secret_key, base):
    """구 API: GET /v2/auth?key=&secret=  →  access_token"""
    r = requests.get(base + "/v2/auth",
                     params={"key": api_key, "secret": secret_key}, timeout=20)
    r.raise_for_status()
    d = r.json()
    tok = d.get("access_token") or (d.get("data") or {}).get("access_token")
    if not tok:
        raise RuntimeError("토큰 발급 실패: " + json.dumps(d, ensure_ascii=False)[:400])
    return tok, {"access-token": tok}


def token_oauth(client_id, client_secret, refresh_token, base):
    """Open API 2.0: refresh token → access token"""
    r = requests.post(base + "/oauth2/token",
                      data={"clientId": client_id, "clientSecret": client_secret,
                            "refreshToken": refresh_token, "grantType": "refresh_token"},
                      headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=20)
    r.raise_for_status()
    d = r.json()
    tok = (d.get("data") or {}).get("accessToken") or d.get("accessToken")
    if not tok:
        raise RuntimeError("토큰 발급 실패: " + json.dumps(d, ensure_ascii=False)[:400])
    new_refresh = (d.get("data") or {}).get("refreshToken")
    if new_refresh and new_refresh != refresh_token:
        print("  ↻ refresh token이 갱신됐습니다. .env 의 IMWEB_REFRESH_TOKEN 을 아래 값으로 바꾸세요:")
        print("    " + new_refresh)
    return tok, {"Authorization": "Bearer " + tok}


# ───────────────────────── 원고 ─────────────────────────
def read_article(path):
    """HTML 파일에서 제목(<h1> 또는 <title>)과 본문을 뽑는다."""
    with open(path, encoding="utf-8-sig") as f:
        raw = f.read()
    title = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", raw, re.S | re.I) or \
        re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    if m:
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
    body = raw
    m = re.search(r"<body[^>]*>(.*)</body>", raw, re.S | re.I)
    if m:
        body = m.group(1)
    body = re.sub(r"<h1[^>]*>.*?</h1>", "", body, count=1, flags=re.S | re.I)  # 제목 중복 제거
    return title, body.strip()


def build_payload(board_code, title, content, args):
    payload = {
        "boardCode": board_code,
        "board_code": board_code,      # 구/신 API 필드명 차이 흡수
        "title": title,
        "content": content,
    }
    if env("IMWEB_CATEGORY"):
        payload["category"] = env("IMWEB_CATEGORY")
    if env("IMWEB_AUTHOR"):
        payload["name"] = env("IMWEB_AUTHOR")
    if env("IMWEB_UNIT_CODE"):
        payload["unitCode"] = env("IMWEB_UNIT_CODE")
    payload.update(DRAFT_FIELDS)       # ★ 항상 마지막에 — 비공개 설정은 덮어쓰지 않는다
    return payload


def pick(d, *keys):
    """응답 JSON에서 게시글 ID/URL 후보를 찾아낸다(키 이름이 버전마다 다름)."""
    stack = [d]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in keys and isinstance(v, (str, int)) and str(v).strip():
                    return str(v)
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return ""


# ───────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser(description="아임웹 블로그 비공개 초안 등록")
    ap.add_argument("--file", help="업로드할 원고 HTML 파일")
    ap.add_argument("--title", help="제목 직접 지정(없으면 원고의 <h1>)")
    ap.add_argument("--board", help="게시판 코드 직접 지정(없으면 .env)")
    ap.add_argument("--env", help=".env 경로 직접 지정")
    ap.add_argument("--dry-run", action="store_true", help="전송하지 않고 payload만 출력")
    ap.add_argument("--check", action="store_true", help=".env 설정만 점검")
    args = ap.parse_args()

    envfile = load_env(args.env)
    print("=== 아임웹 블로그 초안 등록 ===")
    print("  .env      :", envfile or "(못 찾음)")

    mode = (env("IMWEB_API_MODE") or "legacy").lower()
    board = args.board or env("IMWEB_BOARD_CODE")
    base = env("IMWEB_API_BASE") or (OAUTH_BASE if mode == "oauth" else LEGACY_BASE)
    posts_path = env("IMWEB_POSTS_PATH") or "/v2/board/posts"

    need = ["IMWEB_CLIENT_ID", "IMWEB_CLIENT_SECRET", "IMWEB_REFRESH_TOKEN"] if mode == "oauth" \
        else ["IMWEB_API_KEY", "IMWEB_SECRET_KEY"]
    missing = [k for k in need if not env(k)] + ([] if board else ["IMWEB_BOARD_CODE"])

    print("  방식      :", mode)
    print("  엔드포인트:", base + posts_path)
    print("  게시판    :", board or "(없음)")
    print("  누락 설정 :", ", ".join(missing) if missing else "없음")

    if args.check:
        return 0 if not missing else 1
    if missing:
        print("\n[중단] .env 에 위 값을 채운 뒤 다시 실행하세요.")
        return 1
    if not args.file:
        print("\n[중단] --file 로 원고 HTML을 지정하세요.")
        return 1

    title, content = read_article(args.file)
    title = args.title or title
    if not title or not content:
        print("\n[중단] 제목 또는 본문을 읽지 못했습니다:", args.file)
        return 1

    payload = build_payload(board, title, content, args)
    print("\n  제목      :", title)
    print("  본문 길이 :", len(content), "자")
    print("  공개 상태 : 비공개(draft) — " + ", ".join(f"{k}={v}" for k, v in DRAFT_FIELDS.items()))

    if args.dry_run:
        print("\n[dry-run] 아래 payload를 전송하지 않고 종료합니다.\n")
        safe = dict(payload)
        safe["content"] = safe["content"][:300] + " …(생략)"
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        return 0

    print("\n토큰 발급 중...")
    if mode == "oauth":
        _, headers = token_oauth(env("IMWEB_CLIENT_ID"), env("IMWEB_CLIENT_SECRET"),
                                 env("IMWEB_REFRESH_TOKEN"), base)
    else:
        _, headers = token_legacy(env("IMWEB_API_KEY"), env("IMWEB_SECRET_KEY"), base)
    headers["Content-Type"] = "application/json"

    print("게시글 등록 중...")
    r = requests.post(base + posts_path, headers=headers,
                      data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=30)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:800]}

    if r.status_code >= 400 or str(body.get("code", "")) not in ("", "200", "0"):
        print("\n[실패] HTTP", r.status_code)
        print(json.dumps(body, ensure_ascii=False, indent=2)[:1500])
        return 1

    post_id = pick(body, "postId", "post_id", "idx", "no", "postNo", "id")
    url = pick(body, "url", "postUrl", "link", "permalink")
    print("\n[완료] 비공개(draft) 상태로 등록했습니다.")
    print("  게시글 ID :", post_id or "(응답에 없음)")
    if url:
        print("  URL       :", url)
    print("  게시판    :", board)
    print("\n  ※ 아임웹 관리자 > 게시판에서 내용을 검수한 뒤 직접 '공개'로 바꿔 주세요.")
    if not post_id and not url:
        print("\n  (응답 원문)\n" + json.dumps(body, ensure_ascii=False, indent=2)[:1200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
