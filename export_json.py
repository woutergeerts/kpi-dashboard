"""
export_json.py — Export all dashboard data to JSON files for static hosting.

Run once (or on your refresh cadence) to generate the files Lovable needs:

    python export_json.py

Outputs go to ./data/  (created automatically).
Each file is UTF-8 JSON.  See LOVABLE_PROMPT.md for the full schema reference.

Default export scope:
  - Global (no region / country / segment filter)
  - Segment breakdowns: one slice per commercial_segment value
  - Region breakdowns for booking distributions
  - Date window: START_DATE → END_DATE  (edit below)
  - OTB window: next 9 months from today
  - Pickup window: bookings created in the last 30 days for future stay dates
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────

START_DATE  = "2024-01-01"
END_DATE    = str(date.today())
OUT_DIR     = Path(__file__).parent / "data"

EXPORT_BREAKDOWNS = True   # regional / country / hotel-class breakdowns
EXPORT_SEGMENTS   = True   # per-segment KPI slices

# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_json(obj):
    if isinstance(obj, pd.DataFrame):
        # Replace NaN/NaT with None so json.dump produces null not NaN
        return json.loads(obj.to_json(orient="records", date_format="iso"))
    if isinstance(obj, dict):
        return {k: _to_json(v) for k, v in obj.items()}
    if isinstance(obj, (pd.Timestamp, date)):
        return str(obj)
    return obj


def save(name: str, data) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_to_json(data), fh, indent=2, default=str)
    print(f"  ✓  {path.name}")


def _f(segment=None, region=None, country=None):
    """Build a filter dict with global defaults."""
    return {
        "start":   START_DATE,
        "end":     END_DATE,
        "region":  list(region or []),
        "country": list(country or []),
        "segment": list(segment or []),
    }


# ── Pickup / pace query ───────────────────────────────────────────────────────
# Bookings created in the last 30 days for future stay nights.
# Gives a day-over-day pickup view not available in the OTB snapshot data.
PICKUP_SQL = """
    SELECT
        CAST(r.reservation_planned_start_at AS DATE)        AS stay_date,
        CAST(r.reservation_created_at AS DATE)              AS booked_on,
        DATEDIFF(
            CAST(r.reservation_planned_start_at AS DATE),
            CAST(r.reservation_created_at AS DATE)
        )                                                   AS lead_days,
        COUNT(DISTINCT r.reservation_id)                    AS new_bookings,
        COUNT(DISTINCT r.pms_property_id)                   AS property_count
    FROM product.facts.fct_reservations r
    JOIN product.dimensions.dim_pms_properties p
         ON r.pms_property_id = p.pms_property_id
    WHERE p.is_deleted = FALSE
      AND p.subscription_state = 'Enabled'
      AND r.is_reservation_deleted = FALSE
      AND r.reservation_state_code NOT IN (4)
      AND CAST(r.reservation_created_at AS DATE)
              >= DATE_SUB(CURRENT_DATE, 30)
      AND CAST(r.reservation_planned_start_at AS DATE) >= CURRENT_DATE
    GROUP BY stay_date, booked_on
    ORDER BY booked_on, stay_date
"""

# ── Enhanced cancellation query ───────────────────────────────────────────────
# Adds estimated lost revenue (cancelled room nights × property ADR that day).
# No-show state code is 3 in Mews reservations.
CANCELLATION_ENHANCED_SQL = """
    SELECT
        YEAR(r.reservation_created_at)                            AS year,
        CASE WHEN r.reservation_state_code = 4 THEN 'Cancelled'
             WHEN r.reservation_state_code = 3 THEN 'No-show'
             ELSE 'Other'
        END                                                       AS cancellation_type,
        COUNT(DISTINCT r.pms_property_id)                         AS property_count,
        COUNT(*)                                                  AS bookings,
        AVG(CASE WHEN r.reservation_state_code IN (3, 4)
                 THEN DATEDIFF(
                     r.reservation_planned_start_at,
                     COALESCE(r.reservation_canceled_at, r.reservation_planned_start_at)
                 ) END)                                           AS avg_cancel_window_days,
        -- Estimated lost revenue: LOS × ADR from the metrics mart on the stay date
        SUM(CASE WHEN r.reservation_state_code IN (3, 4)
                 THEN DATEDIFF(
                     r.reservation_planned_end_at,
                     r.reservation_planned_start_at
                 ) END)                                           AS lost_room_nights,
        AVG(CASE WHEN r.reservation_state_code IN (3, 4)
                    AND m.num_directly_occupied_accommodation_resources > 0
                 THEN m.total_adjusted_net_accommodation_revenue_eur
                      / m.num_directly_occupied_accommodation_resources
                 END)                                             AS est_adr_at_stay_date
    FROM product.facts.fct_reservations r
    JOIN product.dimensions.dim_pms_properties p
         ON r.pms_property_id = p.pms_property_id
    LEFT JOIN product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
         ON  m.pms_property_id = r.pms_property_id
         AND m.calendar_date_local = CAST(r.reservation_planned_start_at AS DATE)
    WHERE p.is_deleted = FALSE
      AND p.subscription_state = 'Enabled'
      AND r.is_reservation_deleted = FALSE
      AND YEAR(r.reservation_created_at) IN (2024, 2025, 2026)
      AND CAST(p.pms_property_created_at AS DATE)
              < MAKE_DATE(YEAR(r.reservation_created_at), 1, 1)
      AND (p.go_live_date IS NULL
           OR CAST(p.go_live_date AS DATE)
              <= DATE_SUB(MAKE_DATE(YEAR(r.reservation_created_at), 1, 1), 90))
    GROUP BY year, cancellation_type
    ORDER BY year, cancellation_type
"""


# ── Main export ───────────────────────────────────────────────────────────────

def main():
    import queries_rooms as q

    f_global = _f()

    print(f"\nExporting dashboard data  {START_DATE} → {END_DATE}")
    print(f"Output directory: {OUT_DIR}\n")

    # ── Meta ─────────────────────────────────────────────────────────────────
    segments = q.get_segments()
    save("meta", {
        "exported_at":    str(date.today()),
        "start_date":     START_DATE,
        "end_date":       END_DATE,
        "regions":        q.get_regions(),
        "countries":      q.get_countries(),
        "segments":       segments,
        "property_count": q.count_properties(f_global),
    })

    # ── Tab 2 — Market KPIs ───────────────────────────────────────────────────
    save("kpis",       q.load_kpis(f_global))
    save("ytd_growth", q.load_ytd_growth((), (), ()))
    save("otb_growth", q.load_otb_growth((), (), ()))
    save("trends",     q.load_trends(f_global))
    save("otb_trends", q.load_otb_trends(f_global))

    # ── Point 1: Segment-level KPI slices ────────────────────────────────────
    # Produces kpis_by_segment.json: array of {segment, adr, occupancy, revpar,
    # enterprises, reservations} — one row per commercial_segment value.
    if EXPORT_SEGMENTS and segments:
        seg_rows = []
        for seg in segments:
            try:
                row = q.load_kpis(_f(segment=[seg]))
                row["segment"] = seg
                seg_rows.append(row)
            except Exception as e:
                print(f"    ⚠  kpis_by_segment skipped {seg!r}: {e}")
        save("kpis_by_segment", seg_rows)

        # Trends sliced by segment for Direct-channel growth analysis
        seg_trend_rows = []
        for seg in segments:
            try:
                df = q.load_trends(_f(segment=[seg]))
                df["segment"] = seg
                seg_trend_rows.append(df)
            except Exception as e:
                print(f"    ⚠  trends_by_segment skipped {seg!r}: {e}")
        if seg_trend_rows:
            save("trends_by_segment", pd.concat(seg_trend_rows, ignore_index=True))

    # ── Tab 3 — Regional Overview ─────────────────────────────────────────────
    if EXPORT_BREAKDOWNS:
        save("regional_annual",  q.load_regional_annual((), (), ()))
        save("regional_monthly", q.load_regional_monthly((), START_DATE, END_DATE, (), ()))

        # Add region column to country data using the COUNTRY_TO_REGION mapping
        ca = q.load_country_annual((), ())
        ca.insert(0, "region", ca["country_name"].map(q.COUNTRY_TO_REGION).fillna("Other"))
        save("country_annual", ca)

        cm = q.load_country_monthly((), START_DATE, END_DATE, ())
        cm.insert(0, "region", cm["country_name"].map(q.COUNTRY_TO_REGION).fillna("Other"))
        save("country_monthly", cm)

    # ── Tab 4 — Hotel Class ───────────────────────────────────────────────────
    if EXPORT_BREAKDOWNS:
        save("hotelclass_annual",  q.load_hotelclass_annual(()))
        save("hotelclass_monthly", q.load_hotelclass_monthly((), START_DATE, END_DATE))

    # ── Tab 5 — Booking Behaviour ─────────────────────────────────────────────
    # Global cuts
    save("lead_time",      q.load_lead_time(f_global))
    save("length_of_stay", q.load_length_of_stay(f_global))
    save("group_size",     q.load_group_size(f_global))
    save("channel",        q.load_channel(f_global))
    save("payment_type",   q.load_payment_type(f_global))
    save("card_network",   q.load_card_network(f_global))
    save("behaviour_annual", q.load_behaviour_annual((), (), ()))

    # Point 3: Booking distributions by region — enables filter propagation
    if EXPORT_BREAKDOWNS:
        dist_by_region = []
        for region in q.get_regions():
            try:
                for name, fn in [
                    ("lead_time",      q.load_lead_time),
                    ("length_of_stay", q.load_length_of_stay),
                    ("group_size",     q.load_group_size),
                ]:
                    df = fn(_f(region=[region]))
                    df["region"] = region
                    df["metric"] = name
                    dist_by_region.append(df)
            except Exception as e:
                print(f"    ⚠  distributions_by_region skipped {region!r}: {e}")
        if dist_by_region:
            save("distributions_by_region", pd.concat(dist_by_region, ignore_index=True))

        # DOW distributions by region
        dow_by_region = []
        for region in q.get_regions():
            try:
                for name, fn in [
                    ("checkin_dow",  q.load_checkin_dow),
                    ("checkout_dow", q.load_checkout_dow),
                ]:
                    df = fn(_f(region=[region]))
                    df["region"] = region
                    df["metric"] = name
                    dow_by_region.append(df)
            except Exception as e:
                print(f"    ⚠  dow_by_region skipped {region!r}: {e}")
        if dow_by_region:
            save("dow_by_region", pd.concat(dow_by_region, ignore_index=True))

    # Point 5: Enhanced cancellation stats (no-show vs cancel + lost revenue estimate)
    try:
        canc_enhanced = q.query(CANCELLATION_ENHANCED_SQL)
        # Compute estimated lost revenue = lost_room_nights × est_adr_at_stay_date
        if not canc_enhanced.empty:
            canc_enhanced["est_lost_revenue_eur"] = (
                canc_enhanced["lost_room_nights"].astype(float)
                * canc_enhanced["est_adr_at_stay_date"].astype(float)
            )
        save("cancellation_enhanced", canc_enhanced)
    except Exception as e:
        print(f"    ⚠  cancellation_enhanced failed: {e}")

    save("cancellation_stats",     q.load_cancellation_stats(f_global))

    # ── Tab 6 — Direct vs OTAs ────────────────────────────────────────────────
    save("channel_adr",             q.load_channel_adr(f_global))
    save("channel_behaviour",       q.load_channel_behaviour(f_global))
    save("cancellation_by_channel", q.load_cancellation_by_channel(f_global))

    # ── Tab 7 — Hotel Performance ─────────────────────────────────────────────
    save("pnl_monthly",                  q.load_pnl_monthly(f_global))
    save("pnl_mix",                      q.load_pnl_mix(f_global))
    save("revenue_per_sqm",              q.load_revenue_per_sqm(f_global))
    save("checkin_prestay",              q.load_checkin_prestay(f_global))
    save("checkin_athotel",              q.load_checkin_athotel(f_global))
    save("checkin_dow",                  q.load_checkin_dow(f_global))
    save("checkout_dow",                 q.load_checkout_dow(f_global))
    save("upsell_by_channel",            q.load_upsell_by_channel(f_global))
    save("upsell_by_category",           q.load_upsell_by_category(f_global))
    save("upsell_avg_value_by_channel",  q.load_upsell_avg_value_by_channel(f_global))

    # ── Point 4: Pickup / pace ────────────────────────────────────────────────
    # Bookings created in the last 30 days for future stay nights.
    try:
        pickup = q.query(PICKUP_SQL)
        save("pickup", pickup)
    except Exception as e:
        print(f"    ⚠  pickup failed: {e}")

    print(f"\nDone. {len(list(OUT_DIR.glob('*.json')))} files written to {OUT_DIR}/")


if __name__ == "__main__":
    main()
