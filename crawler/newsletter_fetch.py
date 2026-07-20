# -*- coding: utf-8 -*-
"""스티비(Stibee) 뉴스레터 발송 이력 자동 수집 → web/newsletter.json
   Stibee API v2 (이메일 API · 프로 요금제 이상). 여러 워크스페이스 지원.
   키: STIBEE_TOKEN(아카라), STIBEE_TOKEN_SIJEOL(시절레터·B2C).
   각 워크스페이스의 GET /emails(페이지네이션) 수집 → 제목 기준 중복 제거 → B2B/B2C 분류.
   ※ 오픈율·클릭률 통계는 스티비 API v2가 공개 엔드포인트로 제공하지 않음(후보 15종 전부 404).
   GitHub Actions 매일 실행."""
import os, re, json, datetime
import requests

BASE = "https://api.stibee.com/v2"

# (표시명, 토큰, 강제분류) — 강제분류가 'b2c'면 해당 워크스페이스 이메일은 전부 B2C.
# 시절레터를 먼저 처리해 중복 시 시절 워크스페이스 값이 우선되도록 함.
WORKSPACES = [
    ("시절레터", os.environ.get("STIBEE_TOKEN_SIJEOL", ""), "b2c"),
    ("아카라", os.environ.get("STIBEE_TOKEN", ""), None),
]
B2C_HINT = ["시절레터", "시절", "sijeol", "sijeul"]


def _get(path, token, params=None):
    h = {"AccessToken": token, "Content-Type": "application/json"}
    r = requests.get(BASE + path, headers=h, params=params or {}, timeout=25)
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


def _body(j):
    return j.get("value") if isinstance(j, dict) and isinstance(j.get("value"), dict) else j


def fetch_all_emails(token):
    items, offset, total = [], 0, None
    while True:
        sc, page = _get("/emails", token, {"offset": offset, "limit": 100})
        if sc != 200 or not isinstance(page, dict):
            break
        batch = page.get("items") or page.get("value") or []
        items.extend(batch)
        total = page.get("total", total)
        offset += len(batch) if batch else 1
        if not batch or (total is not None and offset >= total) or len(items) >= 3000:
            break
    return items, total


STAT_CANDIDATES = [
    "/emails/{id}/statistics", "/emails/{id}/statistics/summary", "/emails/{id}/reports",
    "/emails/{id}/report", "/emails/{id}/analytics", "/emails/{id}/result",
    "/emails/{id}/opens", "/emails/{id}/clicks", "/emails/{id}/stat", "/emails/{id}/stats",
]
STAT_KEYS = ("sent", "sentCount", "delivered", "success", "totalSent",
             "openRate", "opened", "open", "opens", "openCount", "uniqueOpen",
             "clicked", "click", "clicks", "clickCount", "uniqueClick")


def find_stat_endpoint(eid, token):
    for tmpl in STAT_CANDIDATES:
        sc, j = _get(tmpl.replace("{id}", str(eid)), token)
        b = _body(j)
        if sc == 200 and isinstance(b, dict) and stat(b, *STAT_KEYS) is not None:
            return tmpl
    return None


def parse(e, token, stat_ep, force_bucket):
    eid = e.get("id")
    title = pick(e, "subject", "title", "name") or "(제목 없음)"
    # 발송시각 플레이스홀더(1990/0001/1970 = 웹 발행)면 생성일로 대체
    st = pick(e, "sentTime", "sentAt")
    if st and str(st)[:4] in ("1990", "0001", "1970"):
        st = None
    date = (st or pick(e, "createdTime", "createdAt") or "")[:10]
    link = pick(e, "permanentLink", "url", "permalink") or ("https://stibee.com/email/%s/" % eid)
    sender = pick(e, "senderName")
    row = {"id": eid, "title": title, "date": date, "link": link,
           "listId": e.get("listId"), "sender": sender,
           "sent": None, "openRate": None, "clickRate": None}
    if stat_ep:
        sc, j = _get(stat_ep.replace("{id}", str(eid)), token)
        sd = _body(j) if sc == 200 else None
        if isinstance(sd, dict):
            sent = stat(sd, "sent", "sentCount", "delivered", "success", "totalSent")
            opened = stat(sd, "opened", "openCount", "uniqueOpen", "open", "opens")
            clicked = stat(sd, "clicked", "clickCount", "uniqueClick", "click", "clicks")
            orate = stat(sd, "openRate", "openrate", "open_rate")
            crate = stat(sd, "clickRate", "clickrate", "click_rate")

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
    # 분류
    if force_bucket:
        row["bucket"] = force_bucket
    else:
        blob = ((sender or "") + " " + title).lower()
        row["bucket"] = "b2c" if any(h.lower() in blob for h in B2C_HINT) else "b2b"
    return row


def main():
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    path = os.path.join(os.path.dirname(__file__), "..", "newsletter.json")
    prev = {}
    if os.path.exists(path):
        try:
            prev = json.load(open(path, encoding="utf-8"))
        except Exception:
            prev = {}

    if not any(t for _, t, _ in WORKSPACES):
        print("STIBEE 토큰 없음 — 건너뜀(기존 newsletter.json 유지)")
        return

    all_rows, raw = [], {}
    for name, token, force in WORKSPACES:
        if not token:
            print(name, "토큰 미설정 — 건너뜀")
            continue
        sc, auth = _get("/auth-check", token)
        sc_em, em_body = _get("/emails", token, {"limit": 5})
        items, total = fetch_all_emails(token)
        sent_items = [e for e in items if e.get("sentTime")]
        sent_items.sort(key=lambda e: (e.get("sentTime") or ""), reverse=True)
        stat_ep = find_stat_endpoint(sent_items[0].get("id"), token) if sent_items else None
        rows = [parse(e, token, stat_ep, force) for e in sent_items]
        all_rows.extend(rows)
        raw[name] = {"auth": sc, "emailsStatus": sc_em,
                     "emailsSnippet": json.dumps(em_body, ensure_ascii=False)[:400],
                     "total": total, "fetched": len(items),
                     "sent": len(sent_items), "statEndpoint": stat_ep}
        print("%s: auth %s · total %s · sent %d · stat %s" % (name, sc, total, len(sent_items), stat_ep))

    # 제목 기준 중복 제거(먼저 온 워크스페이스=시절레터 우선)
    seen, merged = set(), []
    for r in all_rows:
        k = re.sub(r"\s+", "", (r["title"] or "").lower())
        if k in seen:
            continue
        seen.add(k)
        merged.append(r)

    b2b = [x for x in merged if x.get("bucket") != "b2c"]
    b2c = [x for x in merged if x.get("bucket") == "b2c"]
    b2b.sort(key=lambda x: x["date"] or "", reverse=True)
    b2c.sort(key=lambda x: x["date"] or "", reverse=True)

    raw_path = os.path.join(os.path.dirname(__file__), "..", "newsletter_raw.json")
    json.dump({"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "workspaces": raw,
               "merged": len(merged), "b2b": len(b2b), "b2c": len(b2c)},
              open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    for x in (b2b + b2c):
        x.pop("bucket", None)
    out = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "source": "Stibee API v2 (자동)",
           "subscribers": prev.get("subscribers"), "b2b": b2b, "b2c": b2c,
           "note": "Stibee API v2 자동 수집(아카라+시절레터 워크스페이스) · 제목 기준 중복 제거."}
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("newsletter.json OK — b2b:%d b2c:%d" % (len(b2b), len(b2c)))


if __name__ == "__main__":
    main()
