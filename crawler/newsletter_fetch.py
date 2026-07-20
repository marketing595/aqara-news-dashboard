# -*- coding: utf-8 -*-
"""스티비(Stibee) 뉴스레터 발송 통계 자동 수집 → web/newsletter.json
   Stibee API v2 (이메일 API · 프로 요금제 이상). 키: STIBEE_TOKEN.
   GET /auth-check → GET /emails(페이지네이션) → 이메일별 통계 엔드포인트 호출.
   통계 엔드포인트명이 확정되기 전까지 후보를 probe해서 newsletter_raw.json에 원본 저장.
   GitHub Actions 매일 실행."""
import os, json, datetime
import requests

TOKEN = os.environ.get("STIBEE_TOKEN", "")
BASE = "https://api.stibee.com/v2"
H = {"AccessToken": TOKEN, "Content-Type": "application/json"}

# B2C(시절레터) 분류 listId — 확인 후 채움. 그 외 listId는 B2B(아카라레터).
B2C_LIST_IDS = []
B2C_HINT = ["시절레터", "시절", "sijeol", "sijeul"]


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


def stat(obj, *keys):
    """통계가 flat/중첩 어디에 있어도 탐색."""
    if not isinstance(obj, dict):
        return None
    containers = [obj]
    for c in ("statistics", "stat", "report", "result", "value", "data", "summary", "overview"):
        if isinstance(obj.get(c), dict):
            containers.append(obj[c])
    for c in containers:
        v = pick(c, *keys)
        if v is not None:
            return v
    return None


def fetch_all_emails():
    items, offset, total = [], 0, None
    while True:
        sc, page = _get("/emails", {"offset": offset, "limit": 100})
        if sc != 200 or not isinstance(page, dict):
            break
        batch = page.get("items") or page.get("value") or []
        items.extend(batch)
        total = page.get("total", total)
        offset += len(batch) if batch else 1
        if not batch or (total is not None and offset >= total) or len(items) >= 1000:
            break
    return items, total


def fetch_stats(eid):
    """이메일별 통계 조회. 후보 엔드포인트를 순서대로 시도, 200이면 반환."""
    for ep in ("/emails/%s/statistics", "/emails/%s/stat", "/emails/%s/report",
               "/emails/%s/statistics/overview", "/emails/%s"):
        sc, j = _get(ep % eid)
        if sc == 200 and isinstance(j, dict):
            body = j.get("value") if isinstance(j.get("value"), dict) else j
            if stat(body, "sent", "sentCount", "delivered", "success", "openRate", "opened", "open", "uniqueOpen") is not None:
                return ep, body
    return None, None


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
        print("STIBEE_TOKEN 미설정 — 건너뜀(기존 newsletter.json 유지)")
        return

    sc, auth = _get("/auth-check")
    print("auth-check:", sc, json.dumps(auth, ensure_ascii=False)[:150])

    items, total = fetch_all_emails()
    print("emails:", len(items), "/ total", total)

    # 통계 엔드포인트 확정용 probe (첫 발송 이메일 기준)
    probe = {}
    sent_items = [e for e in items if e.get("sentTime")]
    if sent_items:
        eid = sent_items[0].get("id")
        for ep in ("/emails/%s/statistics", "/emails/%s/stat", "/emails/%s/report",
                   "/emails/%s", "/emails/%s/statistics/overview", "/emails/%s/summary"):
            sc, j = _get(ep % eid)
            probe[ep % "{id}"] = {"status": sc, "body": j if sc == 200 else (pick(j, "code") or str(j)[:120])}

    # listId 분포(B2B/B2C 분류 확인용)
    lists = {}
    for e in items:
        lid = e.get("listId")
        d = lists.setdefault(str(lid), {"count": 0, "senders": [], "sample": e.get("subject")})
        d["count"] += 1
        sn = e.get("senderName")
        if sn and sn not in d["senders"]:
            d["senders"].append(sn)

    raw_path = os.path.join(os.path.dirname(__file__), "..", "newsletter_raw.json")
    json.dump({"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "total": total,
               "listIdDistribution": lists, "statProbe": probe, "sampleItem": items[0] if items else None},
              open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    def parse(e):
        eid = e.get("id")
        title = pick(e, "subject", "title", "name") or "(제목 없음)"
        date = (pick(e, "sentTime", "sentAt", "createdTime", "createdAt") or "")[:10]
        link = pick(e, "permanentLink", "url", "permalink") or ("https://stibee.com/email/%s/" % eid)
        row = {"id": eid, "title": title, "date": date, "link": link, "listId": e.get("listId"),
               "sent": None, "openRate": None, "clickRate": None}
        # 통계 병합
        ep, sdata = fetch_stats(eid)
        if sdata:
            sent = stat(sdata, "sent", "sentCount", "delivered", "deliverySuccess", "success", "totalSent")
            opened = stat(sdata, "opened", "openCount", "uniqueOpen", "open", "opens")
            clicked = stat(sdata, "clicked", "clickCount", "uniqueClick", "click", "clicks")
            orate = stat(sdata, "openRate", "openrate", "open_rate")
            crate = stat(sdata, "clickRate", "clickrate", "click_rate")

            def rate(n):
                try:
                    return round(n / sent * 100, 1) if (sent and n is not None) else None
                except Exception:
                    return None

            def pct(v):
                try:
                    v = float(v)
                    return round(v * 100, 1) if v <= 1 else round(v, 1)
                except Exception:
                    return None
            row["sent"] = sent
            row["openRate"] = pct(orate) if orate is not None else rate(opened)
            row["clickRate"] = pct(crate) if crate is not None else rate(clicked)
        return row

    # 발송된 이메일만, 최신순
    sent_items.sort(key=lambda e: (e.get("sentTime") or ""), reverse=True)
    rows = [parse(e) for e in sent_items]

    def is_b2c(x):
        if x["listId"] in B2C_LIST_IDS:
            return True
        return any(h.lower() in (x["title"] or "").lower() for h in B2C_HINT)

    b2b = [x for x in rows if not is_b2c(x)]
    b2c = [x for x in rows if is_b2c(x)]

    out = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "source": "Stibee API v2 (자동)",
           "subscribers": prev.get("subscribers"), "b2b": b2b, "b2c": b2c,
           "note": "Stibee API v2 자동 수집 · GET /emails + 이메일별 통계."}
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("newsletter.json OK — b2b:%d b2c:%d" % (len(b2b), len(b2c)))


if __name__ == "__main__":
    main()
