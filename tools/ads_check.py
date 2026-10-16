#!/usr/bin/env python3
"""광고 성과 점검 계산기 — ads-check 스킬이 쓰는 고정 절차.

같은 파일을 넣으면 언제나 같은 숫자가 나온다. AI는 이 결과를 읽고 보고서만 쓴다.

    python3 tools/ads_check.py <광고 CSV 또는 xlsx>        # 마지막 날짜 기준 최근 7일 vs 그 전 7일
    python3 tools/ads_check.py <광고 CSV> --days 14       # 비교 기간 길이 바꾸기
    python3 tools/ads_check.py <광고 CSV> --end 2026-10-11
    python3 tools/ads_check.py <광고 CSV> --json          # 다른 프로그램이 읽을 때

절차: 1. 데이터 검증 → 2. 지표 계산 → 3. 변화 비교 → 4. 이상 신호
외부 라이브러리 없이 python3 만으로 돈다.
"""
import argparse
import csv
import json
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta

# ── 기준 — 내 업무에 맞게 바꿔도 되는 숫자 ──────────────────────────────
DEFAULT_DAYS = 7          # 비교 기간 길이(일)
MIN_PURCHASES = 5         # 구매가 이보다 적으면 「표본이 작다」
MIN_CLICKS = 100          # 클릭이 이보다 적으면 「표본이 작다」
SPEND_UP = 0.10           # 광고비가 10% 이상 늘었는데
PURCHASE_DOWN = 0.0       # 구매가 줄었으면 → 신호
CTR_HIGH_CVR_LOW = 1.3    # 클릭률은 평균의 1.3배 이상인데 구매율은 평균의 1/1.3 이하면 → 신호
DAY_SPIKE = 2.0           # 하루 광고비가 기간 하루 평균의 2배 이상이면 → 신호
MAX_LIST = 5              # 「새로 시작 · 멈춤」은 광고비 큰 순으로 이만큼만 따로 적는다

# ── 칸 이름 — Meta 광고관리자 내보내기(한글 · 영문) ─────────────────────
COLUMNS = {
    "date": ["일", "날짜", "보고 시작", "day", "date", "reporting starts"],
    "campaign": ["캠페인 이름", "캠페인", "campaign name", "campaign"],
    "adset": ["광고 세트 이름", "광고 세트", "ad set name", "ad set"],
    "ad": ["광고 이름", "광고", "ad name", "ad"],
    "spend": ["지출 금액 (krw)", "지출 금액", "지출", "amount spent (krw)", "amount spent", "spend"],
    "impressions": ["노출", "impressions"],
    "clicks": ["링크 클릭", "클릭(링크)", "link clicks", "clicks (link)", "클릭", "clicks"],
    "purchases": ["구매", "purchases", "결과", "results"],
    "value": ["구매 전환값", "구매 전환 값", "결과 값", "purchases conversion value", "purchase conversion value", "results value"],
    "result_type": ["결과 유형", "result type", "result indicator"],
}
REQUIRED = ["date", "spend"]
# 칸 하나가 없으면 「모름」이 되는 지표
DEPENDS = {
    "impressions": {"impressions", "ctr"},
    "clicks": {"clicks", "ctr", "cpc", "cvr"},
    "purchases": {"purchases", "cvr", "cpa"},
    "value": {"value", "roas"},
}
# 칸이 없을 때 못 하는 판단
NEEDS = {
    "ad": "어느 광고에서 변했는지",
    "campaign": "어느 캠페인에서 변했는지",
    "impressions": "클릭률(CTR)",
    "clicks": "클릭률(CTR) · 클릭당 비용(CPC) · 구매율(CVR)",
    "purchases": "구매 · 구매당 비용(CPA) · 구매율(CVR)",
    "value": "광고 효율(ROAS)",
}


def norm(name):
    return " ".join(str(name).replace("﻿", "").strip().lower().split())


def read_xlsx(path):
    """xlsx 첫 시트를 행 목록(dict)으로 — 외부 라이브러리 없이."""
    m = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(m + "si"):
            shared.append("".join(t.text or "" for t in si.iter(m + "t")))
    sheet = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))[0]

    def col(ref):
        n = 0
        for ch in ref:
            if ch.isalpha():
                n = n * 26 + ord(ch.upper()) - 64
            else:
                break
        return n - 1

    table = []
    for r in ET.fromstring(z.read(sheet)).iter(m + "row"):
        cells = {}
        for c in r.findall(m + "c"):
            v, t = c.find(m + "v"), c.get("t")
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(m + "t"))
            else:
                val = v.text if v is not None else ""
            cells[col(c.get("r", "A"))] = val
        if cells:
            table.append([cells.get(i, "") for i in range(max(cells) + 1)])
    if not table:
        return []
    head = table[0]
    rows = []
    for line in table[1:]:
        row = {}
        for i, h in enumerate(head):
            if h and h not in row:  # 같은 칸 이름이 두 번이면 앞의 것
                row[h] = line[i] if i < len(line) else ""
        rows.append(row)
    return rows


def nfc_rows(rows):
    """한글 조합 방식(NFC/NFD)이 섞인 파일에서 같은 이름이 둘로 갈라지지 않게 전부 NFC로."""
    out = []
    for r in rows:
        out.append({unicodedata.normalize("NFC", str(k)): (unicodedata.normalize("NFC", v) if isinstance(v, str) else v) for k, v in r.items()})
    return out


def read_rows(path):
    if path.lower().endswith(".xlsx"):
        return nfc_rows(read_xlsx(path))
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(path, newline="", encoding=enc) as f:
                return nfc_rows(list(csv.DictReader(f)))
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"파일을 읽지 못했어요 (UTF-8 · CP949 모두 실패): {path}")


def map_columns(headers):
    found, by_norm = {}, {norm(h): h for h in headers}
    for key, names in COLUMNS.items():
        for n in names:
            if n in by_norm:
                found[key] = by_norm[n]
                break
    return found


def num(v):
    s = str(v or "").replace(",", "").replace("₩", "").replace("원", "").strip()
    if s in ("", "-"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_date(v):
    s = str(v or "").strip()
    if s.replace(".", "", 1).isdigit() and 20000 < float(s) < 80000:  # 엑셀 날짜 숫자
        return date(1899, 12, 30) + timedelta(days=int(float(s)))
    s = s[:10].replace(".", "-").replace("/", "-")
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def metrics(t):
    def div(a, b):
        return a / b if b else None
    return {
        "spend": t["spend"], "impressions": t["impressions"], "clicks": t["clicks"],
        "purchases": t["purchases"], "value": t["value"],
        "ctr": div(t["clicks"], t["impressions"]),
        "cpc": div(t["spend"], t["clicks"]),
        "cvr": div(t["purchases"], t["clicks"]),
        "cpa": div(t["spend"], t["purchases"]),
        "roas": div(t["value"], t["spend"]),
    }


def empty():
    return {"spend": 0.0, "impressions": 0.0, "clicks": 0.0, "purchases": 0.0, "value": 0.0}


def change(cur, prev):
    if prev in (None, 0) or cur is None:
        return None
    return (cur - prev) / prev


def check(path, days=DEFAULT_DAYS, end=None):
    rows = read_rows(path)
    if not rows:
        raise SystemExit("파일에 행이 없어요.")
    cols = map_columns(rows[0].keys())

    # 1. 데이터 검증
    missing_required = [k for k in REQUIRED if k not in cols]
    missing = [k for k in NEEDS if k not in cols]
    validation = {
        "file": path,
        "rows": len(rows),
        "columns_read": {k: cols[k] for k in COLUMNS if k in cols},
        "missing_required": missing_required,
        "blocked": [NEEDS[k] for k in missing],
    }
    if "result_type" in cols:
        types = sorted({str(r.get(cols["result_type"]) or "").strip() for r in rows} - {""})
        validation["result_types"] = types
        if len(types) > 1:
            validation["blocked"].append(f"「결과」에 서로 다른 결과가 섞여 있어요({' · '.join(types)}) — 구매로 합쳐 세면 틀릴 수 있어요")
    if missing_required:
        return {"validation": validation, "ok": False}

    dated, bad_dates = [], 0
    for r in rows:
        d = parse_date(r.get(cols["date"]))
        if d is None:
            bad_dates += 1
            continue
        dated.append((d, r))
    if not dated:
        validation["bad_dates"] = bad_dates
        return {"validation": validation, "ok": False}
    first, last = min(d for d, _ in dated), max(d for d, _ in dated)
    end_d = date.fromisoformat(end) if end else last
    cur_start = end_d - timedelta(days=days - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    cur_days = {d for d, _ in dated if cur_start <= d <= end_d}
    prev_days = {d for d, _ in dated if prev_start <= d <= prev_end}
    validation.update({
        "bad_dates": bad_dates,
        "data_range": [first.isoformat(), last.isoformat()],
        "current": [cur_start.isoformat(), end_d.isoformat(), len(cur_days)],
        "previous": [prev_start.isoformat(), prev_end.isoformat(), len(prev_days)],
        "periods_complete": len(cur_days) == days and len(prev_days) == days,
    })

    # 2. 지표 계산
    total = {"current": empty(), "previous": empty()}
    by = {"campaign": {}, "ad": {}}
    daily = {}
    for d, r in dated:
        period = "current" if cur_start <= d <= end_d else "previous" if prev_start <= d <= prev_end else None
        if not period:
            continue
        vals = {k: num(r.get(cols[k])) if k in cols else 0.0 for k in ("spend", "impressions", "clicks", "purchases", "value")}
        for k, v in vals.items():
            total[period][k] += v
        day = daily.setdefault(d.isoformat(), empty())
        for k, v in vals.items():
            day[k] += v
        for level in ("campaign", "ad"):
            if level not in cols:
                continue
            name = str(r.get(cols[level]) or "(이름 없음)").strip()
            slot = by[level].setdefault(name, {"current": empty(), "previous": empty()})
            for k, v in vals.items():
                slot[period][k] += v

    # 3. 변화 비교
    # 칸이 없는 지표는 0이 아니라 「모름」(None)
    unknown = set()
    for k, deps in DEPENDS.items():
        if k not in cols:
            unknown |= deps

    def compare(t):
        c, p = metrics(t["current"]), metrics(t["previous"])
        for k in unknown:
            c[k] = p[k] = None
        return {"current": c, "previous": p, "change": {k: change(c[k], p[k]) for k in c}}

    summary = compare(total)
    levels = {}
    for level, items in by.items():
        rows_ = []
        for name, t in items.items():
            x = compare(t)
            x["name"] = name
            x["spend_delta"] = t["current"]["spend"] - t["previous"]["spend"]
            x["status"] = ("새로 시작" if t["previous"]["spend"] == 0 and t["current"]["spend"] > 0
                           else "멈춤" if t["current"]["spend"] == 0 and t["previous"]["spend"] > 0 else "계속")
            rows_.append(x)
        rows_.sort(key=lambda x: (-abs(x["spend_delta"]), x["name"]))
        levels[level] = rows_

    # 4. 이상 신호 — 일반적인 기준만 · 원인을 단정하지 않는다
    signals = []
    if not validation["periods_complete"]:
        signals.append({"kind": "기간 불완전", "what": f"이번 기간 {len(cur_days)}일 · 지난 기간 {len(prev_days)}일만 데이터가 있어요. 비교 결과를 그대로 믿기 어려워요."})
    sc = summary["change"]
    if sc["spend"] is not None and sc["spend"] >= SPEND_UP and "purchases" in cols and sc["purchases"] is not None and sc["purchases"] < PURCHASE_DOWN:
        signals.append({"kind": "광고비↑ 구매↓", "what": f"광고비는 {sc['spend']:+.1%}인데 구매는 {sc['purchases']:+.1%}예요."})
    cur = summary["current"]
    if cur["purchases"] is not None and cur["purchases"] < MIN_PURCHASES:
        signals.append({"kind": "표본 작음", "what": f"이번 기간 구매가 {cur['purchases']:.0f}건이라 판단하기 일러요 (기준 {MIN_PURCHASES}건)."})
    if cur["clicks"] is not None and cur["clicks"] < MIN_CLICKS:
        signals.append({"kind": "표본 작음", "what": f"이번 기간 클릭이 {cur['clicks']:.0f}번이라 판단하기 일러요 (기준 {MIN_CLICKS}번)."})
    if "ad" in cols and cur["ctr"] and cur["cvr"]:
        for a in levels["ad"]:
            ac = a["current"]
            if ac["ctr"] and ac["cvr"] is not None and (ac["clicks"] or 0) >= MIN_CLICKS / 2 \
                    and ac["ctr"] >= cur["ctr"] * CTR_HIGH_CVR_LOW and ac["cvr"] <= cur["cvr"] / CTR_HIGH_CVR_LOW:
                signals.append({"kind": "클릭↑ 구매율↓", "what": f"{a['name']}: 클릭률 {ac['ctr']:.2%}(전체 {cur['ctr']:.2%})인데 구매율 {ac['cvr']:.2%}(전체 {cur['cvr']:.2%})예요."})
    for status in ("새로 시작", "멈춤"):
        items = [a for a in levels.get("ad", []) if a["status"] == status]
        for a in items[:MAX_LIST]:
            signals.append({"kind": status, "what": f"{a['name']}: 지난 기간 광고비 {a['previous']['spend']:,.0f}원 → 이번 기간 {a['current']['spend']:,.0f}원"})
        if len(items) > MAX_LIST:
            signals.append({"kind": status, "what": f"외 {len(items) - MAX_LIST}개 (광고비가 작은 순으로 생략 — 광고별 표에 모두 있어요)"})
    # 하루 광고비가 기간 평균의 2배 이상인 날
    cur_days_sorted = [k for k in sorted(daily) if cur_start.isoformat() <= k <= end_d.isoformat()]
    if cur_days_sorted:
        avg = sum(daily[k]["spend"] for k in cur_days_sorted) / len(cur_days_sorted)
        for k in cur_days_sorted:
            if avg and daily[k]["spend"] >= avg * DAY_SPIKE:
                signals.append({"kind": "하루 급증", "what": f"{k}: 광고비 {daily[k]['spend']:,.0f}원 — 이번 기간 하루 평균 {avg:,.0f}원의 {daily[k]['spend'] / avg:.1f}배예요."})

    daily_out = {k: metrics(v) for k, v in sorted(daily.items()) if prev_start.isoformat() <= k <= end_d.isoformat()}
    for v in daily_out.values():
        for k in unknown:
            v[k] = None
    return {"ok": True, "validation": validation, "summary": summary, "levels": levels, "daily": daily_out, "signals": signals,
            "settings": {"days": days, "min_purchases": MIN_PURCHASES, "min_clicks": MIN_CLICKS}}


# ── 사람이 읽는 출력 ───────────────────────────────────────────────────
def fmt(k, v):
    if v is None:
        return "—"
    if k in ("ctr", "cvr"):
        return f"{v:.2%}"
    if k == "roas":
        return f"{v:.0%}"
    if k in ("spend", "cpc", "cpa", "value"):
        return f"{v:,.0f}원"
    return f"{v:,.0f}"


def pct(v):
    return "—" if v is None else f"{v:+.1%}"


LABEL = {"result_type": "결과 유형", "date": "날짜", "campaign": "캠페인", "adset": "광고 세트", "ad": "광고", "spend": "광고비", "impressions": "노출", "clicks": "클릭", "ctr": "클릭률(CTR)", "cpc": "클릭당 비용(CPC)",
         "purchases": "구매", "cvr": "구매율(CVR)", "cpa": "구매당 비용(CPA)", "value": "구매 전환값", "roas": "광고 효율(ROAS)"}


def render(r):
    v = r["validation"]
    out = ["## 1. 데이터 검증", f"- 파일: {v['file']} · {v['rows']}행"]
    out.append("- 읽은 칸: " + " · ".join(f"{LABEL.get(k, k)}={c}" for k, c in v["columns_read"].items()))
    if v["missing_required"]:
        out.append(f"- ⛔ 꼭 있어야 하는 칸이 없어요: {', '.join(v['missing_required'])} → 계산하지 않았어요.")
        return "\n".join(out)
    if v.get("result_types"):
        out.append("- 「결과」 종류: " + " · ".join(v["result_types"]) + " — 구매 · 구매 금액은 이 결과 기준이에요")
    if v.get("blocked"):
        out.append("- 칸이 없어서 못 보는 것: " + " · ".join(v["blocked"]))
    if v.get("bad_dates"):
        out.append(f"- 날짜를 읽지 못한 행 {v['bad_dates']}개는 뺐어요.")
    out.append(f"- 데이터 기간: {v['data_range'][0]} ~ {v['data_range'][1]}")
    out.append(f"- 비교: 이번 {v['current'][0]} ~ {v['current'][1]} ({v['current'][2]}일) vs 지난 {v['previous'][0]} ~ {v['previous'][1]} ({v['previous'][2]}일)")

    s = r["summary"]
    out += ["", "## 2. 지표 계산 · 3. 변화 비교", "| 지표 | 지난 기간 | 이번 기간 | 변화 |", "|---|---|---|---|"]
    keys = ["spend", "impressions", "clicks", "ctr", "cpc", "purchases", "cvr", "cpa", "value", "roas"]
    for k in keys:
        out.append(f"| {LABEL[k]} | {fmt(k, s['previous'][k])} | {fmt(k, s['current'][k])} | {pct(s['change'][k])} |")
    if r.get("daily"):
        out += ["", "### 일별", "| 날짜 | 광고비 | 구매 | 구매 전환값 | ROAS |", "|---|---|---|---|---|"]
        for k, m in r["daily"].items():
            out.append(f"| {k} | {fmt('spend', m['spend'])} | {fmt('purchases', m['purchases'])} | {fmt('value', m['value'])} | {fmt('roas', m['roas'])} |")
    for level, title in (("campaign", "캠페인별"), ("ad", "광고별")):
        items = r["levels"].get(level) or []
        if not items:
            continue
        out += ["", f"### {title} (광고비 변화가 큰 순)", "| 이름 | 상태 | 광고비 지난→이번 | 구매 지난→이번 | 클릭률 | 구매율 | 구매당 비용 | ROAS |", "|---|---|---|---|---|---|---|---|"]
        for a in items:
            c, p = a["current"], a["previous"]
            out.append(f"| {a['name']} | {a['status']} | {fmt('spend', p['spend'])} → {fmt('spend', c['spend'])} | {fmt('purchases', p['purchases'])} → {fmt('purchases', c['purchases'])} | {fmt('ctr', c['ctr'])} | {fmt('cvr', c['cvr'])} | {fmt('cpa', c['cpa'])} | {fmt('roas', c['roas'])} |")

    out += ["", "## 4. 이상 신호 (원인 아님 — 확인해 볼 것)"]
    out += [f"- [{x['kind']}] {x['what']}" for x in r["signals"]] or ["- 없음"]
    st = r["settings"]
    out += ["", f"_기준: 비교 {st['days']}일 · 표본 구매 {st['min_purchases']}건 · 클릭 {st['min_clicks']}번 — tools/ads_check.py 맨 위에서 바꿀 수 있어요._"]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="광고 성과 점검 계산기")
    ap.add_argument("file")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--end", help="이번 기간 마지막 날 (YYYY-MM-DD) · 없으면 파일의 마지막 날짜")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = check(a.file, days=a.days, end=a.end)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else render(r))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
