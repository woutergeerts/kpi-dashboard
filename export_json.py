"""
export_json.py — Export all dashboard data to JSON files for static hosting.

Run once (or on your refresh cadence) to generate the files Lovable needs:

    python export_json.py

Outputs go to ./data/  (created automatically).
Each file is UTF-8 JSON.  See LOVABLE_PROMPT.md for the full schema reference.

Default export scope:
  - Global (no region / country / segment filter)
  - Date window: START_DATE → END_DATE  (edit below)
  - OTB window: next 9 months from today
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────

START_DATE  = "2024-01-01"          # inclusive start of actuals window
END_DATE    = str(date.today())     # exclusive end  (today = up to yesterday)
OTB_END     = str(date.today() + timedelta(days=274))  # ~9 months ahead

OUT_DIR     = Path(__file__).parent / "data"

# Set to True to also export region / country / hotel-class breakdowns.
# These add ~20 extra queries; fine for a monthly batch, slow for ad-hoc runs.
EXPORT_BREAKDOWNS = True

# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_json(obj):
    """Convert DataFrames, dicts-of-DataFrames, or plain dicts to JSON-safe form."""
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")
    if isinstance(obj, dict):
        return {k: _to_json(v) for k, v in obj.items()}
    if isinstance(obj, (pd.Timestamp, date)):
        return str(obj)
    if isinstance(obj, float) and pd.isna(obj):
        return None
    return obj


def save(name: str, data) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_to_json(data), fh, indent=2, default=str)
    print(f"  ✓  {path.name}")


# ── Main export ───────────────────────────────────────────────────────────────

def main():
    # Import here so the module works even before credentials are set.
    import queries_rooms as q

    # Shared filter dict used by the majority of functions.
    f = {
        "start":   START_DATE,
        "end":     END_DATE,
        "region":  [],
        "country": [],
        "segment": [],
    }

    print(f"\nExporting dashboard data  {START_DATE} → {END_DATE}")
    print(f"Output directory: {OUT_DIR}\n")

    # ── Meta ─────────────────────────────────────────────────────────────────
    save("meta", {
        "exported_at":  str(date.today()),
        "start_date":   START_DATE,
        "end_date":     END_DATE,
        "regions":      q.get_regions(),
        "countries":    q.get_countries(),
        "segments":     q.get_segments(),
        "property_count": q.count_properties(f),
    })

    # ── Tab 2 — Market KPIs ───────────────────────────────────────────────────
    save("kpis",        q.load_kpis(f))
    save("ytd_growth",  q.load_ytd_growth((), (), ()))
    save("otb_growth",  q.load_otb_growth((), (), ()))
    save("trends",      q.load_trends(f))
    save("otb_trends",  q.load_otb_trends(f))

    # ── Tab 3 — Regional Overview ─────────────────────────────────────────────
    if EXPORT_BREAKDOWNS:
        save("regional_annual",  q.load_regional_annual((), (), ()))
        save("regional_monthly", q.load_regional_monthly((), START_DATE, END_DATE))
        save("country_annual",   q.load_country_annual((), ()))
        save("country_monthly",  q.load_country_monthly((), START_DATE, END_DATE))

    # ── Tab 4 — Hotel Class ───────────────────────────────────────────────────
    if EXPORT_BREAKDOWNS:
        save("hotelclass_annual",  q.load_hotelclass_annual(()))
        save("hotelclass_monthly", q.load_hotelclass_monthly((), START_DATE, END_DATE))

    # ── Tab 5 — Booking Behaviour ─────────────────────────────────────────────
    save("lead_time",          q.load_lead_time(f))
    save("length_of_stay",     q.load_length_of_stay(f))
    save("group_size",         q.load_group_size(f))
    save("channel",            q.load_channel(f))
    save("payment_type",       q.load_payment_type(f))
    save("card_network",       q.load_card_network(f))
    save("cancellation_stats", q.load_cancellation_stats(f))
    save("behaviour_annual",   q.load_behaviour_annual((), (), ()))

    # ── Tab 6 — Direct vs OTAs ────────────────────────────────────────────────
    save("channel_adr",               q.load_channel_adr(f))
    save("channel_behaviour",         q.load_channel_behaviour(f))
    save("cancellation_by_channel",   q.load_cancellation_by_channel(f))

    # ── Tab 7 — Hotel Performance ─────────────────────────────────────────────
    save("pnl_monthly",               q.load_pnl_monthly(f))
    save("pnl_mix",                   q.load_pnl_mix(f))
    save("revenue_per_sqm",           q.load_revenue_per_sqm(f))
    save("checkin_prestay",           q.load_checkin_prestay(f))
    save("checkin_athotel",           q.load_checkin_athotel(f))
    save("checkin_dow",               q.load_checkin_dow(f))
    save("checkout_dow",              q.load_checkout_dow(f))
    save("upsell_by_channel",         q.load_upsell_by_channel(f))
    save("upsell_by_category",        q.load_upsell_by_category(f))
    save("upsell_avg_value_by_channel", q.load_upsell_avg_value_by_channel(f))

    print(f"\nDone. {len(list(OUT_DIR.glob('*.json')))} files written to {OUT_DIR}/")


if __name__ == "__main__":
    main()
