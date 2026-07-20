# -*- coding: utf-8 -*-
"""스티비(Stibee) 뉴스레터 발송 통계 자동 수집 → web/newsletter.json
   Stibee API v2 (이메일 API · 프로 요금제 이상). 키: STIBEE_TOKEN.
   GET /auth-check(인증확인) → GET /emails(발송 이메일 목록·통계) 수집.
   실제 응답 필드가 확정되기 전이라 방어적으로 파싱하고, 원본은 newsletter_raw.json에 저장(첫 확인용).
   GitHub Actions 매일 실행."""
import os, json, datetime
import requests

TOKEN = os.environ.get("STIBEE_TOKEN", "")
BASE = "https://api.stibee.com/v2"
H = {"AccessToken": TOKEN, "Content-Type": "application/json"}

# B2C(시절레터)로 분류할 힌트 — 나머지는 B2B(아카라레터)로
B2C_HINT = ["시절레터", "시절", "sijeol", "b2c"]


def _get(path, params=None):
    r = requests.get(BASE + path, headers=H, params=params or {}, timeout=25)
    try:
        j = r.json()
    except Exception:
        j = {"_status": r.status_code, "_text": r.text[:400]}
    return r.status_code, j


def pick(d, *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        if d.get(k) not in (None, ""):
            return d.get(k)
    return None


def stat(e, *keys):
    """통계가 flat/중첩(statistics·stat·report·result) 어디에 있어도 탐색."""
    containers = [e]
    for c in ("statistics", "stat", "report", "result", "summary"):
        if isinstance(e.get(c), dict):
            containers.append(e[c])
    for c in containers:
        v = pick(c, *keys)
        if v is not None:
            return v
    return None


def to_date(dt):
    if isinstance(dt, (int, float)):
        try:
            return datetime.datetime.utcfromtimestamp(dt / 1000 if dt > 1e12 else dt).strftime("%Y-%m-%d")
        except Exception:
            return ""
    if isinstance(dt, str):
        return dt[:10]
    return ""


def main():
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    path = os.path.join(os.path.dirname(__file__), "..", "newsletter.json")
    prev = {}
    if os.path.exists(path):
        try:
            prev = json.load(open(path, encoding="utf-8"))
        except Exception:
            prev = {}

    if not TOKEN:
        print("STIBEE_TOKEN 미설정 — 자동 수집 건너뜀(기존 newsletter.json 유지)")
        return

    # 1) 인증 확인
    sc, auth = _get("/auth-check")
    print("auth-check:", sc, json.dumps(auth, ensure_ascii=False)[:200])

    # 2) 발송 이메일 목록·통계
    sc, emails = _get("/emails")
    print("emails status:", sc)

    # 원본 저장(첫 확인용 — 실제 필드 확인 후 파싱 정교화)
    raw_path = os.path.join(os.path.dirname(__file__), "..", "newsletter_raw.json")
    json.dump({"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "emailsStatus": sc, "emails": emails},
              open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if sc != 200:
        print("emails 조회 실패(%s) — 기존 newsletter.json 유지" % sc)
        return

    # 목록 추출 ({value|data|emails|items:[...]} 또는 [...] 대응)
    lst = None
    if isinstance(emails, dict):
        lst = emails.get("value") or emails.get("data") or emails.get("emails") or emails.get("items")
    elif isinstance(emails, list):
        lst = emails
    lst = lst or []

    def parse(e):
        title = pick(e, "subject", "title", "name") or "(제목 없음)"
        date = to_date(pick(e, "sentAt", "sendAt", "sentDate", "publishedAt", "sentTime", "createdAt", "created"))
        sent = stat(e, "sent", "sentCount", "deliverySuccess", "success", "totalSent", "delivered")
        opened = stat(e, "opened", "openCount", "uniqueOpen", "open", "opens")
        clicked = stat(e, "clicked", "clickCount", "uniqueClick", "click", "clicks")
        orate = stat(e, "openRate", "openrate", "open_rate")
        crate = stat(e, "clickRate", "clickrate", "click_rate")

        def rate(n):
            try:
                return round(n / sent * 100, 1) if (sent and n is not None) else None
            except Exception:
                return None
        # 비율이 0~1 소수로 오면 %로 환산
        def pct(v):
            if v is None:
                return None
            try:
                v = float(v)
                return round(v * 100, 1) if v <= 1 else round(v, 1)
            except Exception:
                return None
        orate = pct(orate) if orate is not None else rate(opened)
        crate = pct(crate) if crate is not None else rate(clicked)
        eid = pick(e, "id", "emailId")
        link = pick(e, "url", "permalink", "shareUrl", "webUrl")
        if not link and eid:
            link = "https://stibee.com/email/%s/" % eid
        status = pick(e, "status", "state")
        return {"id": eid, "title": title, "date": date, "sent": sent,
                "openRate": orate, "clickRate": crate, "link": link, "status": status}

    items = [parse(e) for e in lst if isinstance(e, dict)]
    # 발송된 이메일 위주(발송일 있는 것) · 최신순
    items.sort(key=lambda x: x["date"] or "", reverse=True)

    def is_b2c(x):
        s = ((x["title"] or "") + " " + (x["link"] or "")).lower()
        return any(h.lower() in s for h in B2C_HINT)

    b2b = [x for x in items if not is_b2c(x)]
    b2c = [x for x in items if is_b2c(x)]

    out = {
        "generatedAt": kst.strftime("%Y-%m-%d %H:%M"),
        "source": "Stibee API v2 (자동)",
        "subscribers": prev.get("subscribers"),
        "b2b": b2b,
        "b2c": b2c,
        "note": "Stibee API v2 자동 수집 · GET /emails 기준. B2C=시절레터 힌트 분류, 그 외 B2B.",
    }
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("newsletter.json OK — b2b:%d b2c:%d (total %d)" % (len(b2b), len(b2c), len(items)))


if __name__ == "__main__":
    main()
