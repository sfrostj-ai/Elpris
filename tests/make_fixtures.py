#!/usr/bin/env python3
"""
Laver testdata i samme format som de rigtige API'er, så scriptet og appen kan
afprøves uden net:  python tests/make_fixtures.py

  tests/fixtures/foer-13   – søndag 15/11-2026 kl. 11:30, morgendagens priser er ikke ude
  tests/fixtures/efter-13  – søndag 15/11-2026 kl. 14:00, morgendagens priser er ude

Spotpriserne for 15/11 er de rigtige DK1-priser fra Energi Data Service.
Tariflinjerne er de rigtige fra DatahubPricelist. Prognosen er opdigtet.
"""
import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Rigtige DK1-kvarterpriser 15/11-2026 (DKK/MWh), kl. 00:00 → 23:45
SPOT_1115 = [
    1268.684128, 1260.984156, 1255.975519, 1145.411439, 1297.166142, 1205.889021, 1178.378865, 1142.421244,
    1181.668144, 1131.357274, 1111.920781, 1045.163621, 1050.247081, 1003.898272, 956.353508, 952.017645,
    986.405398, 978.555995, 975.042456, 958.297179, 1010.701098, 983.938435, 970.930965, 927.721945,
    939.234377, 949.475971, 950.672037, 967.865939, 999.487698, 1000.982795, 989.470423, 968.987235,
    1008.533226, 916.807577, 874.570429, 824.633421, 788.526310, 758.922890, 745.242579, 739.710598,
    784.339937, 747.709490, 740.009629, 713.845029, 725.058429, 710.854774, 711.079094, 705.098592,
    699.342402, 710.705292, 708.088839, 753.615221, 781.050710, 800.038690, 814.616139, 880.700421,
    975.715342, 1090.764826, 1153.186019, 1182.565179, 1206.262823, 1220.092728, 1264.348265, 1277.505277,
    1270.029677, 1270.253937, 1269.880135, 1259.190079, 1293.951574, 1282.813005, 1268.385037, 1277.729537,
    1247.901856, 1252.088281, 1229.810919, 1245.061202, 1255.228026, 1240.426256, 1209.103581, 1198.263872,
    1156.774381, 1160.885872, 1170.529463, 1115.808019, 1145.261898, 1105.641195, 1060.189644, 1026.923135,
    1146.383305, 1077.831956, 1060.339074, 993.731456, 978.107474, 902.828190, 885.634339, 790.993221,
]

LOW, DAY, PEAK = 0.0605, 0.1816, 0.5449
NET_C = [LOW] * 6 + [DAY] * 11 + [PEAK] * 4 + [DAY] * 3


def rabat(a, b, c):
    return [a] * 6 + [b] * 11 + [c] * 4 + [b] * 3


def prices(lst):
    return {f"Price{i + 1}": v for i, v in enumerate(lst)}


def flat(v):
    d = {"Price1": v}
    d.update({f"Price{i}": None for i in range(2, 25)})
    return d


GRID = {"records": [
    {"ChargeOwner": "Konstant Net A/S - 151", "GLN_Number": "5790000704842", "ChargeType": "D03",
     "ChargeTypeCode": "C_FBTNTR_B", "Note": "Nettarif C", "ValidFrom": "2026-10-01T00:00:00",
     "ValidTo": "2027-02-01T00:00:00", **prices(NET_C)},
    {"ChargeOwner": "Konstant Net A/S - 151", "GLN_Number": "5790000704842", "ChargeType": "D03",
     "ChargeTypeCode": "C_FBTNTR_B", "Note": "Nettarif C", "ValidFrom": "2026-04-01T00:00:00",
     "ValidTo": "2026-10-01T00:00:00",
     **prices([LOW] * 6 + [0.0908] * 11 + [0.2361] * 4 + [0.0908] * 3)},
    {"ChargeOwner": "Konstant Net A/S - 151", "GLN_Number": "5790000704842", "ChargeType": "D03",
     "ChargeTypeCode": "C_FBTNTR_R", "Note": "Rabat Nettarif C - KONSTANT Net A/S", "ValidFrom": "2027-01-01T00:00:00",
     "ValidTo": "2027-02-01T00:00:00", **prices(rabat(-0.0099, -0.0297, -0.0890))},
    {"ChargeOwner": "Konstant Net A/S - 151", "GLN_Number": "5790000704842", "ChargeType": "D03",
     "ChargeTypeCode": "C_FBTNTR_R", "Note": "Rabat Nettarif C - KONSTANT Net A/S", "ValidFrom": "2026-11-01T00:00:00",
     "ValidTo": "2027-01-01T00:00:00", **prices(rabat(-0.0111, -0.0332, -0.0996))},
    {"ChargeOwner": "Konstant Net A/S - 151", "GLN_Number": "5790000704842", "ChargeType": "D03",
     "ChargeTypeCode": "C_FBTNTR_R", "Note": "Rabat på Nettarif C - KONSTANT Net A/S", "ValidFrom": "2026-10-01T00:00:00",
     "ValidTo": "2026-11-01T00:00:00", **prices(rabat(-0.0111, -0.0332, -0.0996))},
]}

SUBS = {"records": [
    {"ChargeOwner": "Konstant Net A/S - 151", "GLN_Number": "5790000704842", "ChargeType": "D01",
     "ChargeTypeCode": "C_FBAHM__B", "Note": "Net abo C forbrug", "ValidFrom": "2026-03-01T00:00:00",
     "ValidTo": "2027-02-01T00:00:00", "ResolutionDuration": "P1M", **flat(36.9167)},
    {"ChargeOwner": "Konstant Net A/S - 151", "GLN_Number": "5790000704842", "ChargeType": "D01",
     "ChargeTypeCode": "C_FBAHM__R", "Note": "Rabat Net abo C forbrug - KONSTANT Net A/S", "ValidFrom": "2027-01-01T00:00:00",
     "ValidTo": "2027-02-01T00:00:00", "ResolutionDuration": "P1M", **flat(-6.0285)},
    {"ChargeOwner": "Konstant Net A/S - 151", "GLN_Number": "5790000704842", "ChargeType": "D01",
     "ChargeTypeCode": "C_FBAHM__R", "Note": "Rabat Net abo C forbrug - KONSTANT Net A/S", "ValidFrom": "2026-11-01T00:00:00",
     "ValidTo": "2027-01-01T00:00:00", "ResolutionDuration": "P1M", **flat(-6.7484)},
]}

ENERGINET = {"records": [
    {"ChargeOwner": None, "GLN_Number": "5790000432752", "ChargeType": "D03", "ChargeTypeCode": "40000",
     "Note": "Transmissions nettarif", "ValidFrom": "2027-01-01T00:00:00", "ValidTo": "2028-01-01T00:00:00", **flat(0.056)},
    {"ChargeOwner": None, "GLN_Number": "5790000432752", "ChargeType": "D03", "ChargeTypeCode": "40000",
     "Note": "Transmissions nettarif", "ValidFrom": "2026-01-01T00:00:00", "ValidTo": "2027-01-01T00:00:00", **flat(0.043)},
    {"ChargeOwner": None, "GLN_Number": "5790000432752", "ChargeType": "D03", "ChargeTypeCode": "41000",
     "Note": "Systemtarif", "ValidFrom": "2027-01-01T00:00:00", "ValidTo": "2028-01-01T00:00:00", **flat(0.049)},
    {"ChargeOwner": None, "GLN_Number": "5790000432752", "ChargeType": "D03", "ChargeTypeCode": "41000",
     "Note": "Systemtarif", "ValidFrom": "2026-01-01T00:00:00", "ValidTo": "2027-01-01T00:00:00", **flat(0.072)},
    {"ChargeOwner": None, "GLN_Number": "5790000432752", "ChargeType": "D03", "ChargeTypeCode": "EA-001",
     "Note": "Elafgift", "ValidFrom": "2026-01-01T00:00:00", "ValidTo": "2028-01-01T00:00:00", **flat(0.008)},
]}

# Opdigtet prognose (totalpris inkl. afgifter og moms) for mandag 16/11 – formen genbruges for de næste dage
MON_TOTAL = [1.42, 1.38, 1.35, 1.34, 1.37, 1.45, 1.78, 2.05, 2.12, 1.88, 1.66, 1.55, 1.49, 1.52, 1.63, 1.80,
             2.02, 2.48, 2.55, 2.41, 2.20, 1.84, 1.70, 1.52]
TARIFF_NOV = [LOW - 0.0111 + 0.123] * 6 + [DAY - 0.0332 + 0.123] * 11 + [PEAK - 0.0996 + 0.123] * 4 + [DAY - 0.0332 + 0.123] * 3
MON_SPOT = [t / 1.25 - tf for t, tf in zip(MON_TOTAL, TARIFF_NOV)]
FACTORS = [1.0, 0.86, 0.62, 0.52, 0.92, 0.95, 0.78, 0.9, 1.0]  # 16/11 … 24/11


def records_for(day: dt.date, quarter_prices: list[float]):
    out = []
    t = dt.datetime(day.year, day.month, day.day)
    for i, p in enumerate(quarter_prices):
        dk = t + dt.timedelta(minutes=15 * i)
        utc = dk - dt.timedelta(hours=1)  # vintertid
        out.append({"TimeUTC": utc.isoformat(), "TimeDK": dk.isoformat(), "PriceArea": "DK1",
                    "DayAheadPriceEUR": round(p / 7.46, 6), "DayAheadPriceDKK": round(p, 6)})
    return out


def forecast_json(first_forecast: dt.date):
    days = [{"date": "2026-11-15", "type": "actual", "weekday": 7,
             "prices": [{"hour": h, "price": round(sum(SPOT_1115[h * 4:h * 4 + 4]) / 4000, 4)} for h in range(24)]}]
    for i, f in enumerate(FACTORS):
        d = dt.date(2026, 11, 16) + dt.timedelta(days=i)
        typ = "actual" if d < first_forecast else "forecast"
        spread = 0.12 + 0.04 * i
        ps = []
        for h in range(24):
            v = max(0.05, MON_SPOT[h] * f)
            p = {"hour": h, "price": round(v, 4)}
            if typ == "forecast":
                p["min"] = round(v * (1 - spread), 4)
                p["max"] = round(v * (1 + spread), 4)
            ps.append(p)
        days.append({"date": d.isoformat(), "type": typ, "weekday": d.isoweekday(),
                     "source": "model" if i < 6 else "heuristic", "prices": ps})
    return {"area": "DK1", "mode": "spot_ex", "generated": "2026-11-15",
            "model": {"name": "test", "generatedAt": "2026-11-15T10:00:00Z"}, "days": days}


def write(dirname: str, with_tomorrow: bool):
    d = HERE / "fixtures" / dirname
    d.mkdir(parents=True, exist_ok=True)
    recs = records_for(dt.date(2026, 11, 15), SPOT_1115)
    if with_tomorrow:
        q = []
        for h in range(24):
            base = MON_SPOT[h] * 1000
            q += [base * (1 + k) for k in (0.02, 0.0, -0.01, -0.01)]
        recs += records_for(dt.date(2026, 11, 16), q)
    (d / "spot.json").write_text(json.dumps({"total": len(recs), "dataset": "DayAheadPrices", "records": recs}))
    (d / "grid.json").write_text(json.dumps(GRID))
    (d / "grid_subs.json").write_text(json.dumps(SUBS))
    (d / "energinet.json").write_text(json.dumps(ENERGINET))
    first = dt.date(2026, 11, 17) if with_tomorrow else dt.date(2026, 11, 16)
    (d / "forecast.json").write_text(json.dumps(forecast_json(first)))
    print("skrev", d)


if __name__ == "__main__":
    write("foer-13", with_tomorrow=False)
    write("efter-13", with_tomorrow=True)
