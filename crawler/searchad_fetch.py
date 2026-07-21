# -*- coding: utf-8 -*-
"""네이버 검색광고 성과(파워링크·브랜드검색 등) → web/searchad.json
   검색광고 API: 캠페인 목록(/ncc/campaigns) + 성과(/stats). 최근 30일 · 캠페인별/타입별/일별.
   키: SEARCHAD_API_KEY / SEARCHAD_SECRET / SEARCHAD_CUSTOMER_ID.
   ※ 응답 필드 확정 전이라 원본을 searchad_raw.json에 덤프."""
import os, json, time, hmac, hashlib, base64, datetime
import requests

KEY = os.environ.get("SEARCHAD_API_KEY", "")
SEC = os.environ.get("SEARCHAD_SECRET", "")
CID = os.environ.get("SEARCHAD_CUSTOMER_ID", "")
BASE = "https://api.searchad.naver.com"
TYPE_KR = {"WEB_SITE": "파워링크", "SHOPPING": "쇼핑검색", "POWER_CONTENTS": "파워컨텐츠",
           "BRAND_SEARCH": "브랜드검색", "PLACE": "플레이스", "CATALOG": "카탈로그", "PLACE_AD": "플레이스"}


def _sign(ts, method, path):
    msg = "%s.%s.%s" % (ts, method, path)
    return base64.b64encode(hmac.new(SEC.encode(), msg.encode(), hashlib.sha256).digest()).decode()


def sa_get(path, params=None):
    ts = str(int(time.time() * 1000))
    h = {"X-Timestamp": ts, "X-API-KEY": KEY, "X-Customer": str(CID), "X-Signature": _sign(ts, "GET", path)}
    try:
        r = requests.get(BASE + path, params=params or {}, headers=h, timeout=25)
        try:
            j = r.json()
        except Exception:
            j = {"_status": r.status_code, "_text": r.text[:400]}
        return r.status_code, j
    except Exception as e:
        return 0, {"_err": str(e)}


def num(v):
    try:
        return round(float(v), 2) if isinstance(v, float) or (isinstance(v, str) and "." in str(v)) else int(v)
    except Exception:
        return 0


def stats(ids, fields, since, until, increment="allDays"):
    params = {"ids": ids, "fields": json.dumps(fields),
              "timeRange": json.dumps({"since": since, "until": until}), "timeIncrement": increment}
    return sa_get("/stats", params)


def main():
    if not (KEY and SEC and CID):
        print("SEARCHAD 키 미설정 — 건너뜀")
        return
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    until = kst.date() - datetime.timedelta(days=1)
    since = until - datetime.timedelta(days=29)
    s, u = since.strftime("%Y-%m-%d"), until.strftime("%Y-%m-%d")

    sc_c, camps = sa_get("/ncc/campaigns")
    if not isinstance(camps, list):
        camps = []
    info = {}
    ids = []
    for c in camps:
        cid = c.get("nccCampaignId")
        if cid:
            info[cid] = {"name": c.get("name"), "type": TYPE_KR.get(c.get("campaignTp"), c.get("campaignTp"))}
            ids.append(cid)

    raw = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "campaignsStatus": sc_c, "campaignCount": len(ids)}

    FIELDS = ["impCnt", "clkCnt", "salesAmt", "ctr", "cpc", "ccnt", "crto", "convAmt"]
    per_camp = []
    if ids:
        sc, j = stats(ids, FIELDS, s, u, "allDays")
        raw["campaignStats"] = {"status": sc, "sample": (j.get("data", [])[:2] if isinstance(j, dict) else j)}
        for row in (j.get("data", []) if isinstance(j, dict) else []):
            cid = row.get("id")
            m = info.get(cid, {})
            per_camp.append({"id": cid, "name": m.get("name"), "type": m.get("type"),
                             "imp": num(row.get("impCnt")), "clk": num(row.get("clkCnt")),
                             "ctr": num(row.get("ctr")), "cpc": num(row.get("cpc")),
                             "cost": num(row.get("salesAmt")), "conv": num(row.get("ccnt")),
                             "convRate": num(row.get("crto")), "convAmt": num(row.get("convAmt"))})

    daily = []
    if ids:
        sc, j = stats(ids, ["impCnt", "clkCnt", "salesAmt"], s, u, "1")
        raw["dailyStatus"] = sc
        byd = {}
        for row in (j.get("data", []) if isinstance(j, dict) else []):
            d = row.get("dateStart") or row.get("statDt") or row.get("date")
            if not d:
                continue
            e = byd.setdefault(d[:10], {"imp": 0, "clk": 0, "cost": 0})
            e["imp"] += num(row.get("impCnt"))
            e["clk"] += num(row.get("clkCnt"))
            e["cost"] += num(row.get("salesAmt"))
        daily = [{"date": d, "imp": byd[d]["imp"], "clk": byd[d]["clk"], "cost": byd[d]["cost"]} for d in sorted(byd)]

    bytype = {}
    for c in per_camp:
        t = c["type"] or "기타"
        e = bytype.setdefault(t, {"imp": 0, "clk": 0, "cost": 0, "conv": 0})
        e["imp"] += c["imp"]; e["clk"] += c["clk"]; e["cost"] += c["cost"]; e["conv"] += c["conv"]
    for t, e in bytype.items():
        e["ctr"] = round(e["clk"] / e["imp"] * 100, 2) if e["imp"] else 0
        e["cpc"] = round(e["cost"] / e["clk"]) if e["clk"] else 0

    out = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "since": s, "until": u,
           "source": "네이버 검색광고 API · /stats", "campaigns": per_camp, "byType": bytype, "daily": daily}
    d = os.path.dirname(__file__)
    json.dump(out, open(os.path.join(d, "..", "searchad.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(raw, open(os.path.join(d, "..", "searchad_raw.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("searchad.json OK — campaigns:%d types:%s daily:%d" % (len(per_camp), list(bytype.keys()), len(daily)))


if __name__ == "__main__":
    main()
