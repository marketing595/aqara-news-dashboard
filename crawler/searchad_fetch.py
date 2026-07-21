# -*- coding: utf-8 -*-
"""네이버 검색광고 성과 + 소재 → web/searchad.json
   검색광고 API: 캠페인(/ncc/campaigns) + 성과(/stats, 기간 4종) + 소재(/ncc/adgroups→/ncc/ads).
   기간: 최근 7/30/90일·이번 달. 성과: 노출·클릭·CTR·CPC·광고비·전환·전환매출·ROAS.
   키: SEARCHAD_API_KEY / SEARCHAD_SECRET / SEARCHAD_CUSTOMER_ID."""
import os, json, time, hmac, hashlib, base64, datetime
import requests

KEY = os.environ.get("SEARCHAD_API_KEY", "")
SEC = os.environ.get("SEARCHAD_SECRET", "")
CID = os.environ.get("SEARCHAD_CUSTOMER_ID", "")
BASE = "https://api.searchad.naver.com"
TYPE_KR = {"WEB_SITE": "파워링크", "SHOPPING": "쇼핑검색", "POWER_CONTENTS": "파워컨텐츠",
           "BRAND_SEARCH": "브랜드검색", "PLACE": "플레이스", "CATALOG": "카탈로그", "PLACE_AD": "플레이스"}
FIELDS = ["impCnt", "clkCnt", "salesAmt", "ctr", "cpc", "ccnt", "crto", "convAmt"]


def _sign(ts, method, path):
    return base64.b64encode(hmac.new(SEC.encode(), ("%s.%s.%s" % (ts, method, path)).encode(), hashlib.sha256).digest()).decode()


def sa_get(path, params=None):
    ts = str(int(time.time() * 1000))
    h = {"X-Timestamp": ts, "X-API-KEY": KEY, "X-Customer": str(CID), "X-Signature": _sign(ts, "GET", path)}
    try:
        r = requests.get(BASE + path, params=params or {}, headers=h, timeout=25)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"_text": r.text[:300]}
    except Exception as e:
        return 0, {"_err": str(e)}


def num(v):
    try:
        f = float(v)
        return round(f, 2) if ("." in str(v)) else int(f)
    except Exception:
        return 0


def stats(ids, s, u):
    return sa_get("/stats", {"ids": ids, "fields": json.dumps(FIELDS),
                             "timeRange": json.dumps({"since": s, "until": u}), "timeIncrement": "allDays"})


def summarize(ids, s, u, info):
    sc, j = stats(ids, s, u)
    per = []
    for row in (j.get("data", []) if isinstance(j, dict) else []):
        cid = row.get("id")
        m = info.get(cid, {})
        cost = num(row.get("salesAmt"))
        camt = num(row.get("convAmt"))
        per.append({"id": cid, "name": m.get("name"), "type": m.get("type"),
                    "imp": num(row.get("impCnt")), "clk": num(row.get("clkCnt")),
                    "ctr": num(row.get("ctr")), "cpc": num(row.get("cpc")), "cost": cost,
                    "conv": num(row.get("ccnt")), "convRate": num(row.get("crto")),
                    "convAmt": camt, "roas": round(camt / cost * 100) if cost else 0})
    bytype = {}
    for c in per:
        e = bytype.setdefault(c["type"] or "기타", {"imp": 0, "clk": 0, "cost": 0, "conv": 0, "convAmt": 0})
        for k in ("imp", "clk", "cost", "conv", "convAmt"):
            e[k] += c[k]
    for e in bytype.values():
        e["ctr"] = round(e["clk"] / e["imp"] * 100, 2) if e["imp"] else 0
        e["cpc"] = round(e["cost"] / e["clk"]) if e["clk"] else 0
        e["roas"] = round(e["convAmt"] / e["cost"] * 100) if e["cost"] else 0
    return {"since": s, "until": u, "campaigns": per, "byType": bytype}


def _txt(v):
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, dict):
        for k in ("text", "value", "final", "content"):
            if isinstance(v.get(k), str) and v.get(k).strip():
                return v.get(k).strip()
    return None


def get_creatives(ids, info, raw):
    out = []
    sample_by_type = {}
    for cid in ids:
        typ = info.get(cid, {}).get("type")
        sc, ags = sa_get("/ncc/adgroups", {"nccCampaignId": cid})
        if not isinstance(ags, list):
            continue
        for ag in ags[:6]:
            sc, adl = sa_get("/ncc/ads", {"nccAdgroupId": ag.get("nccAdgroupId")})
            if not isinstance(adl, list):
                continue
            for a in adl[:6]:
                if typ not in sample_by_type:
                    sample_by_type[typ] = a           # 유형별 원본 1개 덤프(구조 확인용)
                ad = a.get("ad", {}) or {}
                pc = ad.get("pc", {}) or {}
                mo = ad.get("mobile", {}) or {}
                heads, descs = [], []
                # 1) 레거시 단일 필드
                for k in ("headline", "subject", "title", "headText", "mainCopy", "brandMessage", "name"):
                    t = _txt(ad.get(k))
                    if t:
                        heads.append(t)
                for k in ("description", "subText", "desc", "explain"):
                    t = _txt(ad.get(k))
                    if t:
                        descs.append(t)
                # 2) RSA 배열(headlines/descriptions)
                for h in (ad.get("headlines") or []):
                    t = _txt(h)
                    if t:
                        heads.append(t)
                for d in (ad.get("descriptions") or []):
                    t = _txt(d)
                    if t:
                        descs.append(t)
                # 3) assets(확장소재) — assetType으로 제목/설명 분류
                for asset in (a.get("assets") or []) + (ad.get("assets") or []):
                    t = _txt(asset) or _txt(asset.get("adTextAsset") if isinstance(asset, dict) else None)
                    if not t:
                        continue
                    at = (asset.get("assetType") or asset.get("type") or "") if isinstance(asset, dict) else ""
                    if "DESCRIPTION" in str(at).upper():
                        descs.append(t)
                    else:
                        heads.append(t)
                url = _txt(pc.get("final")) or _txt(mo.get("final")) or _txt(ad.get("displayUrl")) or _txt(ad.get("pcFinalUrl")) or _txt(pc.get("display"))
                # 이미지(브랜드검색 등 템플릿 소재 미리보기 썸네일)
                img = _txt(ad.get("thumbnail")) or _txt(ad.get("image"))
                # 브랜드검색: 연결 URL은 adAttr.naAccountList, 문구 없으면 소재명 사용
                if not url:
                    accs = (a.get("adAttr", {}) or {}).get("naAccountList") or []
                    if accs:
                        url = _txt(accs[0].get("url"))
                dh = list(dict.fromkeys(heads))
                dd = list(dict.fromkeys(descs))
                if not dh and not dd:
                    nm = _txt(a.get("name"))
                    if nm:
                        dh = [nm]
                if dh or dd or img:
                    out.append({"campaign": info.get(cid, {}).get("name"), "type": typ,
                                "headline": (" · ".join(dh))[:140] if dh else None,
                                "desc": (" · ".join(dd))[:240] if dd else None,
                                "url": url, "image": img})
            if len(out) >= 140:
                raw["sampleByType"] = sample_by_type
                return out
    raw["sampleByType"] = sample_by_type
    return out


def main():
    if not (KEY and SEC and CID):
        print("SEARCHAD 키 미설정 — 건너뜀")
        return
    kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    today = kst.date()
    until = today - datetime.timedelta(days=1)

    sc, camps = sa_get("/ncc/campaigns")
    if not isinstance(camps, list):
        camps = []
    info, ids = {}, []
    for c in camps:
        cid = c.get("nccCampaignId")
        if cid:
            info[cid] = {"name": c.get("name"), "type": TYPE_KR.get(c.get("campaignTp"), c.get("campaignTp"))}
            ids.append(cid)

    raw = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "campaigns": len(ids)}
    periods = {}
    if ids:
        for key, days in (("7d", 7), ("30d", 30), ("90d", 90)):
            s = (until - datetime.timedelta(days=days - 1)).strftime("%Y-%m-%d")
            periods[key] = summarize(ids, s, until.strftime("%Y-%m-%d"), info)
        mStart = today.replace(day=1).strftime("%Y-%m-%d")
        periods["month"] = summarize(ids, mStart, until.strftime("%Y-%m-%d"), info)

    creatives = get_creatives(ids, info, raw) if ids else []

    out = {"generatedAt": kst.strftime("%Y-%m-%d %H:%M"), "source": "네이버 검색광고 API",
           "defaultPeriod": "30d", "periods": periods, "creatives": creatives}
    d = os.path.dirname(__file__)
    json.dump(out, open(os.path.join(d, "..", "searchad.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(raw, open(os.path.join(d, "..", "searchad_raw.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("searchad.json OK — periods:%s creatives:%d" % (list(periods.keys()), len(creatives)))


if __name__ == "__main__":
    main()
