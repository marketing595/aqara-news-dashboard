# -*- coding: utf-8 -*-
"""홈페이지(아임웹) 문의 인입 수집 → web/homepage.json

아임웹 Open API 2.0(openapi.imweb.me)의 입력폼 API를 사용한다.
  GET /community/forms            : 입력폼 게시판 목록
  GET /community/form-submissions : 입력폼 제출(=문의) 목록

※ 개인정보 보호: 이름·연락처·이메일·주소·문의내용 등 '자유입력' 항목은 저장하지 않는다.
   접수 일시 / 폼 이름 / 선택형(라디오·체크박스·셀렉트) 응답값만 homepage.json에 남긴다.

환경변수(GitHub Secrets)
  IMWEB_CLIENT_ID      개발자센터 앱 Client ID
  IMWEB_CLIENT_SECRET  개발자센터 앱 Client Secret
  IMWEB_REFRESH_TOKEN  최초 1회 발급받은 refresh token (유효 90일)
  IMWEB_UNIT_CODE      (선택) 유닛 코드. 없으면 /site-info로 자동 조회
  IMWEB_ACCESS_TOKEN   (선택) 이미 있는 access token으로 바로 호출할 때
"""
import os, json, datetime
import requests

BASE = "https://openapi.imweb.me"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "homepage.json")
TOKEN_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".imweb_refresh")

CID = os.environ.get("IMWEB_CLIENT_ID", "").strip()
CSECRET = os.environ.get("IMWEB_CLIENT_SECRET", "").strip()
RTOKEN = os.environ.get("IMWEB_REFRESH_TOKEN", "").strip()
UNIT = os.environ.get("IMWEB_UNIT_CODE", "").strip()
ATOKEN = os.environ.get("IMWEB_ACCESS_TOKEN", "").strip()

# 자유입력이라도 항목 제목에 아래 단어가 들어가면 무조건 제외(이중 안전장치)
PII_WORDS = ("이름", "성함", "성명", "연락처", "전화", "휴대", "핸드폰", "메일", "mail", "주소",
             "내용", "문의내용", "상세", "요청사항", "회사명", "상호", "생년", "카톡", "아이디")
# 선택형 항목만 태그로 보관
CHOICE_TYPES = ("select", "radio", "checkbox", "check", "dropdown", "agree")


def load_prev():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(data):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("saved:", OUT, len(data.get("submissions", [])), "submissions")


def get_access_token():
    if ATOKEN:
        return ATOKEN, ""
    if not (CID and CSECRET and RTOKEN):
        return "", ""
    r = requests.post(BASE + "/oauth2/token",
                      data={"clientId": CID, "clientSecret": CSECRET,
                            "refreshToken": RTOKEN, "grantType": "refresh_token"},
                      headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=20)
    if r.status_code != 200:
        print("token error:", r.status_code, r.text[:300])
        return "", ""
    d = (r.json() or {}).get("data") or {}
    new_rt = d.get("refreshToken", "")
    if new_rt and new_rt != RTOKEN:
        # 갱신된 refresh token은 워크플로가 GitHub Secret으로 되돌려 저장한다(저장소에 커밋 금지)
        try:
            with open(TOKEN_OUT, "w", encoding="utf-8") as f:
                f.write(new_rt)
        except Exception as e:
            print("refresh token 저장 실패:", e)
    return d.get("accessToken", ""), new_rt


def api(token, path, params=None):
    r = requests.get(BASE + path, params=params or {},
                     headers={"Authorization": "Bearer " + token, "access-token": token},
                     timeout=30)
    if r.status_code != 200:
        print("api error:", path, r.status_code, r.text[:300])
        return None
    return (r.json() or {}).get("data")


def resolve_unit(token):
    if UNIT:
        return UNIT
    d = api(token, "/site-info")
    units = (d or {}).get("unitList") or []
    if units:
        print("unit 자동 감지:", units[0].get("unitCode"), units[0].get("name"))
        return units[0].get("unitCode", "")
    return ""


def fetch_all(token, path, unit, extra=None, limit=100, cap=200):
    """페이지네이션 전체 수집"""
    out, page = [], 1
    while page <= cap:
        p = {"page": page, "limit": limit, "unitCode": unit}
        p.update(extra or {})
        d = api(token, path, p)
        if not d:
            break
        rows = d.get("list") or []
        out.extend(rows)
        total_page = d.get("totalPage") or 1
        if page >= total_page or not rows:
            break
        page += 1
    return out


def clean_tags(items):
    """선택형 응답만 {항목명: 값}으로 추출 (개인정보 제외)"""
    tags = {}
    for it in items or []:
        subj = (it.get("itemSubject") or "").strip()
        itype = (it.get("itemType") or "").lower()
        if not subj:
            continue
        low = subj.lower()
        if any(w in low for w in PII_WORDS):
            continue
        if not any(t in itype for t in CHOICE_TYPES):
            continue
        val = (it.get("value") or "").strip()
        if not val:
            vl = it.get("valueList") or []
            val = ", ".join(str(v) for v in vl if v)
        val = val.replace("\n", " ").strip()
        if not val or len(val) > 40:
            continue
        tags[subj] = val
    return tags


def parse_time(w):
    """제출 일시 → (YYYY-MM-DD, hour) · KST 기준"""
    if not w:
        return "", None
    s = str(w).strip()
    try:
        if s.isdigit():                      # unixtime
            dt = datetime.datetime.utcfromtimestamp(int(s)) + datetime.timedelta(hours=9)
        elif s.endswith("Z"):                # ISO UTC
            dt = datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S") + datetime.timedelta(hours=9)
        elif "T" in s:
            dt = datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        else:
            dt = datetime.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d"), dt.hour
    except Exception:
        return s[:10], None


def main():
    prev = load_prev()
    token, _ = get_access_token()
    if not token:
        print("아임웹 토큰 없음 → 기존 homepage.json 유지(연동 대기 상태)")
        if not prev:
            save({"generatedAt": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                  "source": "none", "site": "www.aqaralife.kr", "forms": [], "submissions": []})
        return

    unit = resolve_unit(token)
    if not unit:
        print("unitCode를 확인할 수 없습니다 (site-info:read 권한 확인)")
        return

    forms = fetch_all(token, "/community/forms", unit)
    form_meta = [{"formNo": f.get("formNo"), "boardCode": f.get("boardCode") or f.get("formCode"),
                  "name": str(f.get("formName") or "")} for f in forms]
    name_of = {f["formNo"]: f["name"] for f in form_meta}
    print("입력폼:", ", ".join("%s(%s)" % (f["name"], f["formNo"]) for f in form_meta) or "없음")

    subs = fetch_all(token, "/community/form-submissions", unit)
    rows = []
    for s in subs:
        d, h = parse_time(s.get("wtime"))
        if not d:
            continue
        rows.append({"d": d, "h": h,
                     "form": str(s.get("formName") or name_of.get(s.get("formNo"), "문의")),
                     "tags": clean_tags(s.get("item"))})
    rows.sort(key=lambda x: (x["d"], x["h"] or 0))

    monthly = {}
    for r in rows:
        m = r["d"][:7]
        monthly.setdefault(m, {})
        monthly[m][r["form"]] = monthly[m].get(r["form"], 0) + 1

    save({"generatedAt": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
          "source": "imweb-api", "site": "www.aqaralife.kr", "unitCode": unit,
          "totalCount": len(rows), "forms": form_meta, "monthly": monthly, "submissions": rows})


if __name__ == "__main__":
    main()
