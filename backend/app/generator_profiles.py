"""Curated generator-set profiles from manufacturer-published specifications.

Ratings are package ratings for the stated frequency and are not a substitute
for the serial-number-specific datasheet or site derating calculation.
"""

CAT_SOURCE = "https://emc.cat.com/n/api/pubdirect?media_string_id=LEXE7582-"
CUMMINS_SOURCE = "https://www.cummins.com/sites/default/files/2025-09/europe-50hz-model-range-2025.pdf"
CUMMINS_C100_SOURCE = "https://www.cummins.com/sites/default/files/2021-01/PSBU_008_6B5.9_100-125kVA_Rev-3.pdf"
REHLKO_SOURCE = "https://resources.rehlko.com/industrial/pdf/Industrial_Full_Line_Brochure.pdf"


def _profile(identifier, manufacturer, model, frequency_hz, standby_kw, prime_kw,
             engine_model, source_url, *, standby_kva=None, prime_kva=None,
             speed_rpm=None, battery_voltage=None, service_hours=None, fuel_curve=None,
             fuel_curve_basis="standby"):
    kva = standby_kva if standby_kva is not None else (round(standby_kw / 0.8, 2) if standby_kw else None)
    rated_kva = kva or prime_kva
    return {
        "id": identifier, "manufacturer": manufacturer, "model": model,
        "name": f"{manufacturer} {model}", "frequency_hz": frequency_hz,
        "standby_kw": standby_kw, "prime_kw": prime_kw,
        "standby_kva": kva,
        "prime_kva": prime_kva if prime_kva is not None else (round(prime_kw / 0.8, 2) if prime_kw else None),
        "rated_kw": standby_kw or prime_kw,
        "rated_kvar": round((rated_kva or 0) * 0.6, 2),
        "power_factor": 0.8, "engine_model": engine_model,
        "speed_rpm": speed_rpm or (1500 if frequency_hz == 50 else 1800),
        "nominal_battery_voltage": battery_voltage,
        "maintenance_interval_hours": service_hours,
        "fuel_curve": fuel_curve or [], "fuel_curve_basis": fuel_curve_basis if fuel_curve else None,
        "fuel_type": "diesel", "source_url": source_url,
    }


# Caterpillar 50 Hz rating nodes. The official ratings guide states that these
# three-phase ratings use 0.8 power factor.
_cat_rows = [
    ("c2-2-22", "C2.2 / 22 kVA", 22, 20, "Cat C2.2"),
    ("c3-3-33", "C3.3 / 33 kVA", 33, 30, "Cat C3.3"),
    ("c3-3-50", "C3.3 / 50 kVA", 50, 45, "Cat C3.3"),
    ("c4-4-65", "C4.4 / 65 kVA", 65, 60, "Cat C4.4"),
    ("c4-4-88", "C4.4 / 88 kVA", 88, 80, "Cat C4.4"),
    ("c4-4-110", "C4.4 / 110 kVA", 110, 100, "Cat C4.4"),
    ("c7-1-150", "C7.1 / 150 kVA", 150, 135, "Cat C7.1"),
    ("c7-1-200", "C7.1 / 200 kVA", 200, 180, "Cat C7.1"),
    ("c9-250", "C9 / 250 kVA", 250, 230, "Cat C9"),
    ("c9-300", "C9 / 300 kVA", 300, 275, "Cat C9"),
    ("c13-400", "C13 / 400 kVA", 400, 350, "Cat C13"),
    ("c15-500", "C15 / 500 kVA", 500, 455, "Cat C15"),
]

GENERATOR_PROFILES = [
    _profile(f"cat-{key}", "Caterpillar", model, 50, kva * .8, prime * .8,
             engine, CAT_SOURCE, standby_kva=kva, prime_kva=prime)
    for key, model, kva, prime, engine in _cat_rows
]

# Cummins Europe 50 Hz range, except the C100D5 B5.9 entry which uses its own
# published regional specification because that sheet includes a measured curve.
_cummins_rows = [
    ("c17d5", "C17D5", 13, 12, "X2.5-G2"),
    ("c22d5q", "C22D5Q", 18, 16, "X2.5-G2"),
    ("c28d5", "C28D5", 22, 20, "X2.5-G2"),
    ("c44d5e", "C44D5e", 35, 32, "B3.3-G14"),
    ("c55d5e", "C55D5e", 44, 40, "B3.3-G14"),
    ("c66d5e", "C66D5e", 53, 48, "B3.3-G14"),
    ("c90d5", "C90D5", 72, 65, "6BTA5.9-G5"),
    ("c150d5", "C150D5", 120, 109, "6BTAA5.9-G6"),
    ("c200d5e", "C200D5E", 160, 146, "QSB7-G5"),
    ("c220d5e", "C220D5e", 176, 160, "QSB7-G5"),
    ("c275d5", "C275D5", 220, 200, "QSL9-G5"),
    ("c330d5", "C330D5", 264, 240, "QSL9-G5"),
    ("c400d5", "C400D5", 320, 288, "QSG12-G3"),
    ("c500d5", "C500D5", 400, 364, "QSZ13-G5"),
    ("c825d5", "C825D5", 660, 600, "QSK23-G3"),
]
GENERATOR_PROFILES += [
    _profile(f"cummins-{key}", "Cummins", model, 50, standby, prime, engine, CUMMINS_SOURCE)
    for key, model, standby, prime, engine in _cummins_rows
]
GENERATOR_PROFILES.append(_profile(
    "cummins-c100d5-b59", "Cummins", "C100D5 B5.9 (India)", 50, None, 80,
    "6BTAA5.9-G13", CUMMINS_C100_SOURCE, prime_kva=100, battery_voltage=12,
    service_hours=250,
    fuel_curve=[{"load_percent": 75, "litres_per_hour": 18.32},
                {"load_percent": 100, "litres_per_hour": 24.60}],
    fuel_curve_basis="prime",
))

# FG Wilson pages/spec sheets. Values use the 50 Hz package rating.
_fg_rows = [
    ("p22-1", "P22-1", 17.6, 16, "Perkins", "https://www.fgwilson.com/en_GB/products/new/fg-wilson/diesel-generators/small-range-220-kva/1000021793.html", None),
    ("p50-3", "P50-3", 40, 36, "Perkins 1103A-33TG1", "https://s7d2.scene7.com/is/content/Caterpillar/CM20150624-22054-31761", [{"load_percent": 50, "litres_per_hour": 6.0}, {"load_percent": 75, "litres_per_hour": 8.7}, {"load_percent": 100, "litres_per_hour": 11.7}]),
    ("p65-6", "P65-6", 52, 48, "Perkins", "https://www.fgwilson.com/en_GB/products/new.index.html", None),
    ("p88-3", "P88-3", 70.4, 64, "Perkins 1104A-44TG2", "https://s7d2.scene7.com/is/content/Caterpillar/CM20150624-22054-54378", [{"load_percent": 50, "litres_per_hour": 10.3}, {"load_percent": 75, "litres_per_hour": 14.9}, {"load_percent": 100, "litres_per_hour": 20.1}]),
    ("p110-6", "P110-6", 88, 80, "Perkins", "https://www.fgwilson.com/en_GB/products/new.index.html", None),
    ("p150-5", "P150-5", 120, 108, "Perkins 1100 Series", "https://www.fgwilson.com/en_GB/products/new/fg-wilson/diesel-generators/small-range-220-kva/1000004202.html", None),
    ("p165-5", "P165-5", 132, 120, "Perkins 1100 Series", "https://www.fgwilson.com/en_GB/products/new/fg-wilson/diesel-generators/small-range-220-kva/1000004206.html", None),
    ("p275-2", "P275-2", 220, 200, "Perkins", "https://www.fgwilson.com/en_GB/products/new/fg-wilson/diesel-generators/medium-range-225-938-kva/227227255580579.html", None),
    ("p500-3", "P500-3", 400, 364, "Perkins 2506A-E15TAG1", "https://www.fgwilson.com/en_GB/products/new/fg-wilson/diesel-generators/medium-range-225-938-kva/1000012492.html", None),
    ("p850-1", "P850-1", 680, 616, "Perkins", "https://www.fgwilson.com/en_GB/products/new/fg-wilson/diesel-generators/medium-range-225-938-kva/754644808634080.html", None),
]
GENERATOR_PROFILES += [
    _profile(f"fg-{key}", "FG Wilson", model, 50, standby, prime, engine, source,
             service_hours=500 if key in {"p150-5", "p165-5"} else None,
             fuel_curve=curve)
    for key, model, standby, prime, engine, source, curve in _fg_rows
]

# Rehlko/Kohler industrial 60 Hz full-line brochure.
_rehlko_rows = [
    ("15reozk", "15REOZK", 17, 15, 21.3, 18.8, "Kohler"),
    ("20reozk", "20REOZK", 24, 21, 30, 26.3, "Kohler"),
    ("30reozk", "30REOZK", 31, 28, 39, 35, "Kohler"),
    ("40reozk", "40REOZK", 42, 37, 52, 46, "Kohler"),
    ("50reozk", "50REOZK", 52, 47, 65, 58, "Kohler"),
    ("60reozk", "60REOZK", 60, 54, 75, 67, "Kohler"),
    ("80reozjf", "80REOZJF", 83, 76, 104, 95, "John Deere"),
    ("100reozjf", "100REOZJF", 102, 92, 128, 115, "John Deere"),
    ("125reozjg", "125REOZJG", 128, 116, 160, 145, "John Deere"),
    ("150reozjf", "150REOZJF", 154, 140, 193, 175, "John Deere"),
    ("200reozjf", "200REOZJF", 200, 180, 250, 225, "John Deere"),
    ("250reozje", "250REOZJE", 255, 230, 319, 288, "John Deere"),
]
GENERATOR_PROFILES += [
    _profile(f"rehlko-{key}", "Rehlko (Kohler)", model, 60, standby, prime,
             engine, REHLKO_SOURCE, standby_kva=standby_kva, prime_kva=prime_kva,
             fuel_curve=([{"load_percent": 25, "litres_per_hour": 19.7},
                          {"load_percent": 50, "litres_per_hour": 31.4},
                          {"load_percent": 75, "litres_per_hour": 43.3},
                          {"load_percent": 100, "litres_per_hour": 58.0}]
                         if key == "200reozjf" else None))
    for key, model, standby, prime, standby_kva, prime_kva, engine in _rehlko_rows
]

CUSTOM_GENERATOR_PROFILE = {
    "id": "custom", "manufacturer": "Custom", "model": "Custom generator",
    "name": "Custom generator", "frequency_hz": None, "standby_kw": None,
    "prime_kw": None, "standby_kva": None, "prime_kva": None,
    "rated_kw": None, "rated_kvar": None, "power_factor": None,
    "engine_model": "", "speed_rpm": None, "nominal_battery_voltage": None,
    "maintenance_interval_hours": None, "fuel_curve": [],
    "fuel_curve_basis": None, "fuel_type": "diesel", "source_url": None,
}


def list_generator_profiles():
    return [CUSTOM_GENERATOR_PROFILE, *GENERATOR_PROFILES]
