#!/usr/bin/env python3
"""
Elpris-app: henter spotpriser, tariffer og prognose og skriver docs/data.json.
Sender prisalarmer som push-beskeder via ntfy.

Kører uden eksterne pakker (kun Pythons standardbibliotek).

Brug:
  python scripts/update.py                 # normal kørsel (GitHub Actions)
  python scripts/update.py --dry-run       # send ingen beskeder, vis dem kun
  python scripts/update.py --discover      # vis netselskabets gældende tariffer
  python scripts/update.py --fixtures tests/fixtures --now 2026-11-15T11:30 --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Europe/Copenhagen")
UTC = dt.timezone.utc
EDS = "https://api.energidataservice.dk/dataset/"
ELPRISER_FORECAST = "https://elpriser.org/api/forecast"
CARNOT_PREDICT = "https://openapi.carnot.dk/openapi/get_predict"
UA = "elpris-app/1.0 (privat elpris-app; GitHub Actions)"
VAT = 0.25
UGEDAGE = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def kr(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def hh(h: int) -> str:
    return f"{h:02d}"


# --------------------------------------------------------------------------- #
# Netværk
# --------------------------------------------------------------------------- #
class Net:
    def __init__(self, fixtures: Path | None = None):
        self.fixtures = fixtures

    def get_json(self, url: str, fixture: str, headers: dict | None = None):
        if self.fixtures is not None:
            p = self.fixtures / fixture
            if not p.exists():
                raise FileNotFoundError(f"Mangler testfil {p}")
            return json.loads(p.read_text(encoding="utf-8"))
        hdrs = {"User-Agent": UA, "Accept": "application/json"}
        hdrs.update(headers or {})
        req = urllib.request.Request(url, headers=hdrs)
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in (429, 500, 502, 503, 504):
                    wait = int(e.headers.get("Retry-After") or 0) or 10 * (attempt + 1)
                    log(f"  HTTP {e.code} fra {url[:80]}… venter {wait}s")
                    time.sleep(min(wait, 60))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                time.sleep(5 * (attempt + 1))
        raise last_err  # type: ignore[misc]

    def post_json(self, url: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"User-Agent": UA, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status


def eds_url(dataset: str, params: dict) -> str:
    q = {}
    for k, v in params.items():
        q[k] = json.dumps(v, separators=(",", ":")) if isinstance(v, (dict, list)) else str(v)
    return EDS + dataset + "?" + urllib.parse.urlencode(q)


# --------------------------------------------------------------------------- #
# Spotpriser (Energi Data Service, DayAheadPrices, DKK/MWh pr. kvarter)
# --------------------------------------------------------------------------- #
def fetch_spot(net: Net, area: str, first: dt.date, last: dt.date) -> dict[dt.datetime, list[float]]:
    """Returnerer {time_start_utc: [kvarterpriser i kr/kWh ekskl. moms]}."""
    url = eds_url("DayAheadPrices", {
        "start": (first - dt.timedelta(days=1)).isoformat() + "T00:00",
        "end": (last + dt.timedelta(days=2)).isoformat() + "T00:00",
        "filter": {"PriceArea": [area]},
        "sort": "TimeUTC ASC",
        "limit": 2000,
    })
    data = net.get_json(url, "spot.json")
    hours: dict[dt.datetime, list[tuple[dt.datetime, float]]] = {}
    for rec in data.get("records", []):
        t_raw = rec.get("TimeUTC") or rec.get("HourUTC")
        price = rec.get("DayAheadPriceDKK", rec.get("SpotPriceDKK"))
        if price is None and rec.get("DayAheadPriceEUR") is not None:
            price = float(rec["DayAheadPriceEUR"]) * 7.46  # DKK mangler endnu: omregn med fast kurs
        if t_raw is None or price is None:
            continue
        t = dt.datetime.fromisoformat(t_raw.replace("Z", "")).replace(tzinfo=UTC)
        hour = t.replace(minute=0, second=0, microsecond=0)
        hours.setdefault(hour, []).append((t, float(price) / 1000.0))
    out = {}
    for hour, vals in hours.items():
        vals.sort()
        q = [v for _, v in vals]
        if len(q) == 1:
            q = q * 4
        out[hour] = q
    return out


# --------------------------------------------------------------------------- #
# Tariffer (Energi Data Service, DatahubPricelist, kr/kWh ekskl. moms)
# --------------------------------------------------------------------------- #
class Charge:
    def __init__(self, rec: dict):
        self.code = rec["ChargeTypeCode"]
        self.note = rec.get("Note") or ""
        self.valid_from = dt.datetime.fromisoformat(rec["ValidFrom"]).replace(tzinfo=TZ)
        vt = rec.get("ValidTo")
        self.valid_to = dt.datetime.fromisoformat(vt).replace(tzinfo=TZ) if vt else None
        p1 = float(rec.get("Price1") or 0.0)
        self.prices = []
        for i in range(1, 25):
            v = rec.get(f"Price{i}")
            self.prices.append(p1 if v is None else float(v))

    def valid_at(self, t: dt.datetime) -> bool:
        return self.valid_from <= t and (self.valid_to is None or t < self.valid_to)


class Tariffs:
    """Holder styr på alle tariflinjer og finder den gældende pris for en given time."""

    def __init__(self, components: list[tuple[str, str]], charges: list[Charge]):
        self.components = components  # [(kode, visningsnavn)] i visningsrækkefølge
        self.by_code: dict[str, list[Charge]] = {}
        for c in charges:
            self.by_code.setdefault(c.code, []).append(c)
        for lst in self.by_code.values():
            lst.sort(key=lambda c: c.valid_from)
        missing = [code for code, _ in components if code not in self.by_code]
        if missing:
            log(f"ADVARSEL: ingen tariflinjer fundet for kode(r): {', '.join(missing)}")

    def row(self, code: str, t: dt.datetime) -> Charge | None:
        rows = self.by_code.get(code, [])
        valid = [c for c in rows if c.valid_at(t)]
        if valid:
            return valid[-1]
        # Fremtid uden offentliggjort pris: brug seneste kendte linje
        earlier = [c for c in rows if c.valid_from <= t]
        return earlier[-1] if earlier else None

    def parts(self, t_local: dt.datetime) -> dict[str, float]:
        out = {}
        for code, _ in self.components:
            c = self.row(code, t_local)
            out[code] = c.prices[t_local.hour] if c else 0.0
        return out

    def total(self, t_local: dt.datetime) -> float:
        return sum(self.parts(t_local).values())

    def known_until(self, code: str) -> dt.datetime | None:
        rows = self.by_code.get(code, [])
        if not rows:
            return None
        return max((c.valid_to for c in rows if c.valid_to), default=None)


def fetch_charges(net: Net, gln: str, codes: list[str], fixture: str, types=("D03",)) -> list[Charge]:
    if not codes:
        return []
    url = eds_url("DatahubPricelist", {
        "filter": {"GLN_Number": [gln], "ChargeTypeCode": codes},
        "limit": 2000,
    })
    data = net.get_json(url, fixture)
    out = []
    for rec in data.get("records", []):
        if rec.get("ChargeType") not in (None, *types):
            continue
        try:
            out.append(Charge(rec))
        except (KeyError, ValueError) as e:
            log(f"  springer tariflinje over: {e}")
    return out


def discover(net: Net, gln: str):
    """Viser netselskabets gældende tariffer, så man kan finde de rigtige koder."""
    url = eds_url("DatahubPricelist", {
        "filter": {"GLN_Number": [gln], "ChargeType": ["D03"]},
        "start": (dt.date.today() - dt.timedelta(days=400)).isoformat(),
        "limit": 5000,
    })
    data = net.get_json(url, "discover.json")
    now = dt.datetime.now(TZ)
    seen = {}
    for rec in data.get("records", []):
        c = Charge(rec)
        if c.valid_at(now):
            seen[c.code] = (c.note, min(c.prices), max(c.prices))
    print(f"Gældende tariffer for GLN {gln} lige nu (kr/kWh ekskl. moms):")
    for code, (note, lo, hi) in sorted(seen.items()):
        print(f"  {code:<14} {note:<55} {lo:.4f} – {hi:.4f}")


# --------------------------------------------------------------------------- #
# Prognose
# --------------------------------------------------------------------------- #
def fetch_forecast_elpriser(net: Net, area: str) -> dict[dt.date, dict]:
    url = ELPRISER_FORECAST + "?" + urllib.parse.urlencode({"area": area, "mode": "spot_ex"})
    data = net.get_json(url, "forecast.json")
    out = {}
    for day in data.get("days", []):
        prices = day.get("prices") or []
        if not prices:
            continue
        d = dt.date.fromisoformat(day["date"])
        vals = [p.get("price") for p in prices if p.get("price") is not None]
        scale = 1 / 1000 if vals and sorted(vals)[len(vals) // 2] > 20 else 1  # DKK/MWh → kr/kWh
        hours = {}
        for p in prices:
            if p.get("price") is None:
                continue
            h = int(p["hour"])
            v = float(p["price"]) * scale
            lo = p.get("min")
            hi = p.get("max")
            hours[h] = (v, float(lo) * scale if lo is not None else v, float(hi) * scale if hi is not None else v)
        out[d] = {"type": day.get("type"), "source": day.get("source") or day.get("type"), "hours": hours}
    return out


def fetch_forecast_carnot(net: Net, area: str, days: int) -> dict[dt.date, dict]:
    key = os.environ.get("CARNOT_APIKEY")
    user = os.environ.get("CARNOT_USERNAME")
    if not key or not user:
        return {}
    url = CARNOT_PREDICT + "?" + urllib.parse.urlencode(
        {"energysource": "spotprice", "region": area.lower(), "daysahead": min(days, 7)})
    data = net.get_json(url, "carnot.json", headers={"apikey": key, "username": user})
    out: dict[dt.date, dict] = {}
    for p in data.get("predictions", []):
        t = dt.datetime.fromisoformat(p["utctime"]).astimezone(TZ)
        v = float(p["prediction"])
        v = v / 1000 if v > 20 else v  # DKK/MWh → kr/kWh
        day = out.setdefault(t.date(), {"type": "forecast", "source": "carnot", "hours": {}})
        day["hours"][t.hour] = (v, v, v)
    return out


# --------------------------------------------------------------------------- #
# Byg data
# --------------------------------------------------------------------------- #
def r5(x: float) -> float:
    return round(x, 5)


def build_actual_days(spot: dict, tariffs: Tariffs, dates: list[dt.date]) -> list[dict]:
    days = []
    for d in dates:
        hours = []
        for hour_utc in sorted(spot):
            lt = hour_utc.astimezone(TZ)
            if lt.date() != d:
                continue
            q = spot[hour_utc]
            hours.append({
                "t": lt.isoformat(),
                "h": hh(lt.hour),
                "spot": r5(sum(q) / len(q)),
                "q": [r5(v) for v in q],
                "tariff": r5(tariffs.total(lt)),
            })
        if len(hours) >= 23:  # hele døgnet er offentliggjort (23/25 timer ved sommertid)
            days.append({"date": d.isoformat(), "kind": "actual", "hours": hours})
    return days


def build_forecast_days(fc: dict, tariffs: Tariffs, today: dt.date, actual_dates: set, n_days: int) -> list[dict]:
    out = []
    for i in range(1, n_days + 1):
        d = today + dt.timedelta(days=i)
        if d.isoformat() in actual_dates or d not in fc:
            continue
        day = fc[d]
        hours = []
        for h in range(24):
            if h not in day["hours"]:
                continue
            v, lo, hi = day["hours"][h]
            t = dt.datetime(d.year, d.month, d.day, h, tzinfo=TZ)
            hours.append({"h": hh(h), "spot": r5(v), "lo": r5(lo), "hi": r5(hi), "tariff": r5(tariffs.total(t))})
        if len(hours) < 20:
            continue
        conf = 3 if i <= 2 else (2 if i <= 4 else 1)
        if day.get("source") == "heuristic":
            conf = 1
        out.append({"date": d.isoformat(), "kind": "forecast", "source": day.get("source"), "conf": conf, "hours": hours})
    return out


def subscriptions(subs: Tariffs, extra: list[dict], today: dt.date, horizon_days: int = 120):
    """Faste abonnementer i kr/md inkl. moms + kommende ændringer (ekskl. moms, som tarifferne)."""
    t0 = dt.datetime(today.year, today.month, today.day, tzinfo=TZ)
    out, changes = [], []
    for code, name in subs.components:
        row = subs.row(code, t0)
        if row:
            out.append({"navn": name, "kr": round(row.prices[0] * (1 + VAT), 2)})
        for c in subs.by_code.get(code, []):
            if t0 < c.valid_from <= t0 + dt.timedelta(days=horizon_days):
                before = subs.row(code, c.valid_from - dt.timedelta(minutes=1))
                if before and before.prices[0] == c.prices[0]:
                    continue
                changes.append({"date": c.valid_from.date().isoformat(), "name": f"{name} (abonnement)", "unit": "md",
                                "before": [r5(before.prices[0] if before else 0.0)], "after": [r5(c.prices[0])]})
    out += [{"navn": e["navn"], "kr": float(e["kr"])} for e in extra]
    return out, changes


def tariff_overview(tariffs: Tariffs, today: dt.date, horizon_days: int = 120) -> dict:
    t0 = dt.datetime(today.year, today.month, today.day, tzinfo=TZ)
    comps = []
    for code, name in tariffs.components:
        row = tariffs.row(code, t0)
        comps.append({"code": code, "name": name, "note": row.note if row else "",
                      "prices": [r5(p) for p in (row.prices if row else [0.0] * 24)],
                      "valid_from": row.valid_from.date().isoformat() if row else None})
    # Kommende ændringer
    changes = []
    end = t0 + dt.timedelta(days=horizon_days)
    for code, name in tariffs.components:
        cur = tariffs.row(code, t0)
        for c in tariffs.by_code.get(code, []):
            if t0 < c.valid_from <= end:
                before = tariffs.row(code, c.valid_from - dt.timedelta(minutes=1))
                if before and before.prices == c.prices:
                    continue
                changes.append({
                    "date": c.valid_from.date().isoformat(),
                    "name": name,
                    "before": [r5(p) for p in (before.prices if before else (cur.prices if cur else [0.0] * 24))],
                    "after": [r5(p) for p in c.prices],
                })
    changes.sort(key=lambda x: x["date"])
    return {"components": comps, "changes": changes}


# --------------------------------------------------------------------------- #
# Alarmer
# --------------------------------------------------------------------------- #
def totals(day: dict, markup: float) -> list[float]:
    return [(h["spot"] + h["tariff"]) * (1 + VAT) + markup for h in day["hours"]]


def hour_ranges(idx: list[int], hours: list[dict]) -> str:
    """[17,18,19,20] → 'kl. 17–21'."""
    if not idx:
        return ""
    parts = []
    start = prev = idx[0]
    for i in idx[1:] + [None]:
        if i is not None and i == prev + 1:
            prev = i
            continue
        end_h = (int(hours[prev]["h"]) + 1) % 24
        parts.append(f"{hours[start]['h']}–{hh(end_h)}")
        if i is not None:
            start = prev = i
    return "kl. " + ", ".join(parts)


def day_name(d: dt.date) -> str:
    return f"{UGEDAGE[d.weekday()]} {d.day}/{d.month}"


def evaluate_alarms(cfg: dict, now: dt.datetime, actual: list[dict], forecast: list[dict], markup: float) -> list[dict]:
    a = cfg.get("alarmer", {})
    today = now.date()
    tomorrow = (today + dt.timedelta(days=1)).isoformat()
    by_date = {d["date"]: d for d in actual}
    msgs = []

    # 1) Morgendagens billigste timer
    al = a.get("billigste_timer_i_morgen", {})
    if al.get("aktiv") and tomorrow in by_date:
        d = by_date[tomorrow]
        tot = totals(d, markup)
        n = max(1, int(al.get("antal_timer", 3)))
        best_i, best = 0, float("inf")
        for i in range(0, len(tot) - n + 1):
            s = sum(tot[i:i + n]) / n
            if s < best:
                best, best_i = s, i
        mx = max(range(len(tot)), key=lambda i: tot[i])
        mn = min(range(len(tot)), key=lambda i: tot[i])
        end_h = (int(d["hours"][best_i + n - 1]["h"]) + 1) % 24
        msgs.append({
            "key": f"tomorrow:{tomorrow}",
            "title": "Morgendagens billigste timer",
            "message": (f"Kl. {d['hours'][best_i]['h']}–{hh(end_h)} · ca. {kr(best)} kr/kWh. "
                        f"Billigst kl. {d['hours'][mn]['h']} ({kr(tot[mn])} kr), "
                        f"dyrest kl. {d['hours'][mx]['h']} ({kr(tot[mx])} kr)."),
            "tags": ["zap"],
        })

    # 2) Pris over grænse i morgen
    al = a.get("pris_over_i_morgen", {})
    if al.get("aktiv") and tomorrow in by_date:
        g = float(al.get("graense_kr", 2.5))
        d = by_date[tomorrow]
        tot = totals(d, markup)
        over = [i for i, v in enumerate(tot) if v > g]
        if over:
            mx = max(over, key=lambda i: tot[i])
            msgs.append({
                "key": f"over:{tomorrow}",
                "title": f"Dyr strøm i morgen (over {kr(g)} kr)",
                "message": f"{hour_ranges(over, d['hours']).capitalize()}. Højest {kr(tot[mx])} kr/kWh kl. {d['hours'][mx]['h']}.",
                "tags": ["warning"],
            })

    # 3) Pris under grænse lige nu (sendes når en billig periode starter)
    al = a.get("pris_under", {})
    if al.get("aktiv") and today.isoformat() in by_date:
        g = float(al.get("graense_kr", 1.0))
        seq = []  # alle kendte timer fra i dag og frem
        for ds in sorted(by_date):
            if ds >= today.isoformat():
                d = by_date[ds]
                for h, v in zip(d["hours"], totals(d, markup)):
                    seq.append((dt.datetime.fromisoformat(h["t"]), h["h"], v))
        cur_i = next((i for i, (t, _, _) in enumerate(seq) if t <= now < t + dt.timedelta(hours=1)), None)
        if cur_i is not None and seq[cur_i][2] < g:
            prev_cheap = cur_i > 0 and seq[cur_i - 1][2] < g
            if not prev_cheap:
                j = cur_i
                while j + 1 < len(seq) and seq[j + 1][2] < g:
                    j += 1
                end_t = seq[j][0] + dt.timedelta(hours=1)
                msgs.append({
                    "key": f"under:{seq[cur_i][0].isoformat()}",
                    "title": f"Billig strøm nu: {kr(seq[cur_i][2])} kr/kWh",
                    "message": f"Prisen er under {kr(g)} kr/kWh frem til kl. {hh(end_t.hour)}.",
                    "tags": ["zap", "green_circle"],
                })

    # 4) Billig dag på vej i prognosen
    al = a.get("billig_dag_i_prognose", {})
    if al.get("aktiv") and forecast:
        pct = float(al.get("procent_under_snit", 15))
        avgs = {}
        for d in [x for x in actual if x["date"] > today.isoformat()] + forecast:
            t = totals(d, markup)
            avgs[d["date"]] = sum(t) / len(t)
        if len(avgs) >= 3:
            week = sum(avgs.values()) / len(avgs)
            for d in forecast:
                ds = d["date"]
                if ds <= tomorrow:
                    continue
                if avgs[ds] <= week * (1 - pct / 100):
                    below = round((1 - avgs[ds] / week) * 100)
                    msgs.append({
                        "key": f"cheapday:{ds}",
                        "title": "Billig dag på vej",
                        "message": (f"{day_name(dt.date.fromisoformat(ds)).capitalize()} ser ud til at blive ca. "
                                    f"{below} % billigere end ugens snit (gns. {kr(avgs[ds])} kr/kWh)."),
                        "tags": ["chart_with_downwards_trend"],
                    })
    return msgs


def send_ntfy(net: Net, msg: dict, topic: str, server: str, click: str | None):
    payload = {"topic": topic, "title": msg["title"], "message": msg["message"],
               "tags": msg.get("tags", []), "priority": 3}
    if click:
        payload["click"] = click
    return net.post_json(server.rstrip("/") + "/", payload)


# --------------------------------------------------------------------------- #
# Hovedprogram
# --------------------------------------------------------------------------- #
def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixtures", type=Path, help="læs testdata fra mappe i stedet for nettet")
    ap.add_argument("--now", help="lad som om klokken er (lokal tid), fx 2026-11-15T11:30")
    ap.add_argument("--dry-run", action="store_true", help="send ingen push-beskeder")
    ap.add_argument("--discover", action="store_true", help="vis netselskabets gældende tariffer og stop")
    ap.add_argument("--config", type=Path, default=ROOT / "config.json")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "data.json")
    ap.add_argument("--state", type=Path, default=ROOT / "data" / "state.json")
    args = ap.parse_args()

    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    net = Net(args.fixtures)

    if args.discover:
        discover(net, cfg["netselskab"]["gln"])
        return

    now = dt.datetime.fromisoformat(args.now).replace(tzinfo=TZ) if args.now else dt.datetime.now(TZ)
    today = now.date()
    area = cfg.get("prisomraade", "DK1")
    n_days = int(cfg.get("prognose", {}).get("dage", 7))
    markup = float(cfg.get("elselskab_tillaeg_oere_inkl_moms", 0)) / 100

    # Tariffer
    grid_cfg, eng_cfg = cfg["netselskab"], cfg["energinet"]
    log("Henter tariffer …")
    charges = fetch_charges(net, grid_cfg["gln"], list(grid_cfg["tariffer"]), "grid.json")
    charges += fetch_charges(net, eng_cfg["gln"], list(eng_cfg["tariffer"]), "energinet.json")
    components = list(grid_cfg["tariffer"].items()) + list(eng_cfg["tariffer"].items())
    tariffs = Tariffs(components, charges)
    sub_cfg = grid_cfg.get("abonnementer", {})
    sub_charges = fetch_charges(net, grid_cfg["gln"], list(sub_cfg), "grid_subs.json", types=("D01",))
    subs, sub_changes = subscriptions(Tariffs(list(sub_cfg.items()), sub_charges),
                                      cfg.get("ekstra_abonnementer_kr_pr_md_inkl_moms", []), today)

    # Spotpriser for i går, i dag og i morgen
    log("Henter spotpriser …")
    spot = fetch_spot(net, area, today - dt.timedelta(days=1), today + dt.timedelta(days=1))
    dates = [today - dt.timedelta(days=1), today, today + dt.timedelta(days=1)]
    actual = build_actual_days(spot, tariffs, dates)
    actual_dates = {d["date"] for d in actual}
    if today.isoformat() not in actual_dates:
        log("ADVARSEL: dagens spotpriser mangler")

    # Prognose
    forecast: list[dict] = []
    fc_source = None
    fc: dict = {}
    pref = cfg.get("prognose", {}).get("kilde", "elpriser")
    order = ["carnot", "elpriser"] if pref == "carnot" else ["elpriser", "carnot"]
    for src in order:
        try:
            log(f"Henter prognose fra {src} …")
            fc = fetch_forecast_elpriser(net, area) if src == "elpriser" else fetch_forecast_carnot(net, area, n_days)
            if fc:
                fc_source = src
                break
        except Exception as e:  # prognosen må aldrig vælte resten
            log(f"  prognose fra {src} fejlede: {e}")
    if fc:
        forecast = build_forecast_days(fc, tariffs, today, actual_dates, n_days)

    # Alarmer
    state = load_json(args.state, {"sent": {}, "log": []})
    msgs = evaluate_alarms(cfg, now, actual, forecast, markup)
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip() or "https://ntfy.sh"
    click = os.environ.get("APP_URL") or None
    state_changed = False
    for m in msgs:
        if m["key"] in state["sent"]:
            continue
        if args.dry_run or not topic:
            log(f"[{'dry-run' if args.dry_run else 'ingen NTFY_TOPIC – sendes ikke'}] {m['title']}: {m['message']}")
            continue
        else:
            try:
                send_ntfy(net, m, topic, server, click)
                log(f"Sendt: {m['title']}")
            except Exception as e:
                log(f"Kunne ikke sende besked: {e}")
                continue
        state["sent"][m["key"]] = now.isoformat(timespec="minutes")
        state["log"] = ([{"t": now.isoformat(timespec="minutes"), "title": m["title"], "message": m["message"]}]
                        + state.get("log", []))[:15]
        state_changed = True
    # Ryd gamle nøgler (ældre end 14 dage)
    cutoff = (now - dt.timedelta(days=14)).isoformat()
    old = [k for k, v in state["sent"].items() if v < cutoff]
    for k in old:
        del state["sent"][k]
        state_changed = True

    overview = tariff_overview(tariffs, today)
    overview["changes"] = sorted(overview["changes"] + sub_changes, key=lambda x: x["date"])

    data = {
        "generated": now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "name": cfg.get("navn", "Hjem"),
        "area": area,
        "grid": grid_cfg.get("navn", ""),
        "vat": VAT,
        "markup": markup,
        "days": actual,
        "forecast": forecast,
        "forecast_source": fc_source,
        "tariffs": overview,
        "subscriptions": subs,
        "alarms": cfg.get("alarmer", {}),
        "recent_alarms": state.get("log", [])[:10],
        "sources": {
            "spot": "Energinet (www.energidataservice.dk), DayAheadPrices",
            "tariffs": "Energinet (www.energidataservice.dk), DatahubPricelist",
            "forecast": {"elpriser": "elpriser.org", "carnot": "Carnot.dk"}.get(fc_source or "", None),
        },
    }

    # Skriv kun data.json når indholdet har ændret sig (færre commits)
    old_data = load_json(args.out, {})
    strip = lambda x: {k: v for k, v in x.items() if k != "generated"}
    if strip(old_data) != strip(data):
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        log(f"Skrev {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}")
    else:
        log("Ingen ændringer i data")
    if state_changed and not args.dry_run:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    # Kort status til loggen
    for d in actual:
        tot = totals(d, markup)
        log(f"  {d['date']}: {len(tot)} timer, {kr(min(tot))}–{kr(max(tot))} kr/kWh (gns. {kr(sum(tot)/len(tot))})")
    log(f"  Prognose: {len(forecast)} dage fra {fc_source or '–'}")


if __name__ == "__main__":
    main()
