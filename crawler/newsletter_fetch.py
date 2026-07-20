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


STAT_CANDIDATES = [
    "/emails/{id}/statistics", "/emails/{id}/statistics/summary", "/emails/{id}/statistics/detail",
    "/emails/{id}/reports", "/emails/{id}/report", "/emails/{id}/analytics", "/emails/{id}/result",
    "/emails/{id}/results", "/emails/{id}/opens", "/emails/{id}/clicks", "/emails/{id}/stat",
    "/emails/{id}/stats", "/statistics/emails/{id}", "/reports/emails/{id}", "/emails/{id}/summary",
]
STAT_KEYS = ("sent", "sentCount", "delivered", "deliverySuccess", "success", "totalSent",
             "openRate", "opened", "open", "opens", "openCount", "uniqueOpen",
             "clicked", "click", "clicks", "clickCount", "uniqueClick")


def _body(j):
    return j.get("value") if isinstance(j, dict) and isinstance(j.get("value"), dict) else j


def find_stat_endpoint(eid):
    """통계 후보 엔드포인트를 모두 시도해 실제 통계가 담긴 경로를 찾음. (probe 결과도 반환)"""
    found, results = None, {}
    for tmpl in STAT_CANDIDATES:
        sc, j = _get(tmpl.replace("{id}", str(eid)))
        b = _body(j)
        has = stat(b, *STAT_KEYS) is not None if isinstance(b, dict) else False
        results[tmpl] = {"status": sc, "hasStats": has,
                         "keys": list(b.keys())[:25] if isinstance(b, dict) else None}
        if has and found is None:
            found = tmpl
    return found, results


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

    sent_items = [e for e in items if e.get("sentTime")]
    sent_items.sort(key=lambda e: (e.get("sentTime") or ""), reverse=True)

    # 통계 엔드포인트 자동 탐색 (첫 발송 이메일로 후보 15종 테스트)
    stat_ep, probe = (None, {})
    if sent_items:
        stat_ep, probe = find_stat_endpoint(sent_items[0].get("id"))
    print("stat endpoint:", stat_ep)

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
    all_compact = [{"id": e.get("id"), "subject": e.get("subject"), "sender": e.get("senderName"),
                    "listId": e.get("listId"), "status": e.get("status"),
                    "sentTime": e.get("sentTime"), "createdTime": e.get("createdTime")} for e in items]
    json.dump({"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "total": total,
               "statEndpoint": stat_ep, "listIdDistribution": lists, "statProbe": probe,
               "allItems": all_compact},
              open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    def parse(e):
        eid = e.get("id")
        title = pick(e, "subject", "title", "name") or "(제목 없음)"
        # 발송시각이 플레이스홀더(1990/0001 등 웹 발행)면 생성일로 대체
        st = pick(e, "sentTime", "sentAt")
        if st and str(st)[:4] in ("1990", "0001", "1970"):
            st = None
        date = (st or pick(e, "createdTime", "createdAt") or "")[:10]
        link = pick(e, "permanentLink", "url", "permalink") or ("https://stibee.com/email/%s/" % eid)
        row = {"id": eid, "title": title, "date": date, "link": link,
               "listId": e.get("listId"), "sender": pick(e, "senderName"),
               "sent": None, "openRate": None, "clickRate": None}
        # 통계 병합(엔드포인트가 탐색된 경우에만)
        if stat_ep:
            sc, j = _get(stat_ep.replace("{id}", str(eid)))
            sdata = _body(j) if sc == 200 else None
            if isinstance(sdata, dict):
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

    rows = [parse(e) for e in sent_items]

    def is_b2c(x):
        if x["listId"] in B2C_LIST_IDS:
            return True
        blob = ((x.get("sender") or "") + " " + (x["title"] or "")).lower()
        return any(h.lower() in blob for h in B2C_HINT)

    b2b = [x for x in rows if not is_b2c(x)]
    b2c = [x for x in rows if is_b2c(x)]

    out = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "source": "Stibee API v2 (자동)",
           "subscribers": prev.get("subscribers"), "b2b": b2b, "b2c": b2c,
           "note": "Stibee API v2 자동 수집 · GET /emails + 이메일별 통계."}
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("newsletter.json OK — b2b:%d b2c:%d" % (len(b2b), len(b2c)))


if __name__ == "__main__":
    main()
