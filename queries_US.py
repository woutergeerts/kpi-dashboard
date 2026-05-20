import os
import streamlit as st
import pandas as pd
from datetime import date, timedelta
from databricks import sql
from dotenv import load_dotenv

load_dotenv()

DATABRICKS_HOST      = os.getenv("DATABRICKS_HOST")
DATABRICKS_HTTP_PATH = os.getenv("DATABRICKS_HTTP_PATH")
DATABRICKS_TOKEN     = os.getenv("DATABRICKS_TOKEN")

MIN_PROPERTIES = 5

# ── Currency ───────────────────────────────────────────────────────────────────
# All monetary values are in native USD (local currency column).
# Exception: upsell tables are EUR-only in the mart; those use the constant below.
EUR_TO_USD_FIXED = 1.0816   # 2024 annual avg: AVG(1/exchange_rate_value) WHERE source='USD'

# ── US state code → full name ──────────────────────────────────────────────────
STATE_CODE_TO_NAME = {
    "US-AL":"Alabama","US-AK":"Alaska","US-AZ":"Arizona","US-AR":"Arkansas",
    "US-CA":"California","US-CO":"Colorado","US-CT":"Connecticut","US-DE":"Delaware",
    "US-FL":"Florida","US-GA":"Georgia","US-HI":"Hawaii","US-ID":"Idaho",
    "US-IL":"Illinois","US-IN":"Indiana","US-IA":"Iowa","US-KS":"Kansas",
    "US-KY":"Kentucky","US-LA":"Louisiana","US-ME":"Maine","US-MD":"Maryland",
    "US-MA":"Massachusetts","US-MI":"Michigan","US-MN":"Minnesota","US-MS":"Mississippi",
    "US-MO":"Missouri","US-MT":"Montana","US-NE":"Nebraska","US-NV":"Nevada",
    "US-NH":"New Hampshire","US-NJ":"New Jersey","US-NM":"New Mexico","US-NY":"New York",
    "US-NC":"North Carolina","US-ND":"North Dakota","US-OH":"Ohio","US-OK":"Oklahoma",
    "US-OR":"Oregon","US-PA":"Pennsylvania","US-RI":"Rhode Island","US-SC":"South Carolina",
    "US-SD":"South Dakota","US-TN":"Tennessee","US-TX":"Texas","US-UT":"Utah",
    "US-VT":"Vermont","US-VA":"Virginia","US-WA":"Washington","US-WV":"West Virginia",
    "US-WI":"Wisconsin","US-WY":"Wyoming","US-DC":"Washington D.C.",
}

# ── Room-weighted metric expressions — NATIVE USD ──────────────────────────────
ROOM_METRICS_SQL = """\
    NULLIF(SUM(CASE WHEN m.num_directly_occupied_accommodation_resources > 0
                    THEN m.total_adjusted_net_accommodation_revenue END), 0)
        / NULLIF(SUM(CASE WHEN m.num_directly_occupied_accommodation_resources > 0
                    THEN m.num_directly_occupied_accommodation_resources END), 0)  AS adr,
    NULLIF(SUM(CASE WHEN m.num_directly_occupied_accommodation_resources > 0
                    THEN m.total_adjusted_net_accommodation_revenue END), 0)
        / NULLIF(SUM(CASE WHEN m.num_directly_occupied_accommodation_resources > 0
                    THEN m.num_available_accommodation_resources END), 0)          AS revpar,
    NULLIF(SUM(CASE WHEN m.num_directly_occupied_accommodation_resources > 0
                    THEN m.num_directly_occupied_accommodation_resources END), 0)
        / NULLIF(SUM(CASE WHEN m.num_directly_occupied_accommodation_resources > 0
                    THEN m.num_available_accommodation_resources END), 0) * 100    AS occupancy"""

# ── P&L label map ──────────────────────────────────────────────────────────────
PNL_LABEL_MAP = {
    "Accommodation": "Rooms", "FoodAndBeverage": "Food & Beverage",
    "Events": "Events & Meetings", "Wellness": "Wellness & Spa",
    "Facilities": "Facilities", "Sport": "Sport & Recreation",
    "Tourism": "Tourism", "Technology": "Technology",
    "SundryIncome": "Sundry Income", "ExternalRevenue": "External Revenue",
    "NotAssigned": "Not Assigned",
}
PNL_ORDER = ["Rooms", "Food & Beverage", "Events & Meetings", "Wellness & Spa", "Facilities",
             "Sport & Recreation", "Tourism", "Technology", "Sundry Income",
             "External Revenue", "Not Assigned"]

HOTEL_CLASS_ORDER = ["Luxury", "Upscale", "Midscale", "Economy"]
DOW_ORDER         = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ── DB connection ──────────────────────────────────────────────────────────────
@st.cache_resource
def get_conn():
    return sql.connect(
        server_hostname=DATABRICKS_HOST,
        http_path=DATABRICKS_HTTP_PATH,
        access_token=DATABRICKS_TOKEN,
    )

@st.cache_data(ttl=3600)
def query(sql_str: str) -> pd.DataFrame:
    with get_conn().cursor() as cur:
        cur.execute(sql_str)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(rows, columns=cols)


# ── Private helpers ────────────────────────────────────────────────────────────
def _go_live_clause(period_start: str) -> str:
    return (f"(p.go_live_date IS NULL OR "
            f"CAST(p.go_live_date AS DATE) <= DATE_SUB('{period_start}', 90))")


def _esc(s: str) -> str:
    return s.replace("'", "''")


def _geo_clause(state: tuple, city: tuple) -> str:
    """
    Build WHERE fragments for state and/or city filters.
    State is derived from CountrySubdivisionCode in inlined_address_value JSON.
    City comes from the plain `city` column.
    """
    parts = []
    if state:
        codes = ", ".join(f"'{_esc(s)}'" for s in state)
        parts.append(f"get_json_object(p.inlined_address_value, '$.CountrySubdivisionCode') IN ({codes})")
    if city:
        cities = ", ".join(f"'{_esc(c)}'" for c in city)
        parts.append(f"p.city IN ({cities})")
    return (" AND " + " AND ".join(parts)) if parts else ""


# ── Base property filter ───────────────────────────────────────────────────────
def prop_filter(f: dict) -> str:
    parts = [
        "p.is_deleted = FALSE",
        "p.customer_status = 'Subscribed'",
        "p.country_name = 'United States'",
        f"CAST(p.pms_property_created_at AS DATE) < '{f['start']}'",
        _go_live_clause(f['start']),
    ]
    if f.get("segment"):
        s_list = ", ".join(f"'{_esc(s)}'" for s in f["segment"])
        parts.append(f"p.commercial_segment IN ({s_list})")
    geo = _geo_clause(tuple(f.get("state") or []), tuple(f.get("city") or []))
    if geo:
        parts.append(geo.lstrip(" AND "))
    return " AND ".join(parts)


def res_date_filter(f: dict) -> str:
    return (
        f"r.reservation_planned_start_at >= '{f['start']}' "
        f"AND r.reservation_planned_start_at < '{f['end']}' "
        f"AND r.reservation_state_code NOT IN (4) "
        f"AND r.is_reservation_deleted = FALSE"
    )


# ── Filter options ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_segments() -> list:
    df = query("""
        SELECT DISTINCT commercial_segment
        FROM product.dimensions.dim_pms_properties
        WHERE commercial_segment IS NOT NULL
          AND is_deleted = FALSE AND country_name = 'United States'
        ORDER BY commercial_segment
    """)
    return df["commercial_segment"].tolist()


@st.cache_data(ttl=3600)
def get_states() -> list:
    """Return list of (code, display_name) tuples for states with ≥1 Subscribed US property."""
    df = query("""
        SELECT DISTINCT get_json_object(inlined_address_value, '$.CountrySubdivisionCode') AS code
        FROM product.dimensions.dim_pms_properties
        WHERE country_name = 'United States'
          AND is_deleted = FALSE AND customer_status = 'Subscribed'
          AND get_json_object(inlined_address_value, '$.CountrySubdivisionCode') IS NOT NULL
        ORDER BY code
    """)
    codes = df["code"].tolist()
    # Return display names sorted alphabetically; fall back to raw code if unknown
    return sorted(
        [STATE_CODE_TO_NAME.get(c, c) for c in codes]
    )


@st.cache_data(ttl=3600)
def get_cities() -> list:
    df = query("""
        SELECT DISTINCT city
        FROM product.dimensions.dim_pms_properties
        WHERE country_name = 'United States'
          AND is_deleted = FALSE AND customer_status = 'Subscribed'
          AND city IS NOT NULL AND city != ''
        ORDER BY city
    """)
    return df["city"].tolist()


def _state_name_to_code(name: str) -> str:
    """Reverse lookup: state display name → US-XX code."""
    for code, n in STATE_CODE_TO_NAME.items():
        if n == name:
            return code
    return name  # fallback: already a code or unknown


# ── Property count check ───────────────────────────────────────────────────────
def count_properties(f: dict) -> int:
    pf = prop_filter(f)
    df = query(f"SELECT COUNT(DISTINCT p.pms_property_id) AS n "
               f"FROM product.dimensions.dim_pms_properties p WHERE {pf}")
    return int(df["n"].iloc[0]) if not df.empty else 0


# ── KPIs ───────────────────────────────────────────────────────────────────────
def load_kpis(f: dict) -> dict:
    pf = prop_filter(f)
    df_res = query(f"""
        SELECT COUNT(DISTINCT r.reservation_id)  AS reservations,
               COUNT(DISTINCT r.pms_property_id) AS enterprises
        FROM product.facts.fct_reservations r
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        WHERE {pf} AND {res_date_filter(f)}
    """)
    df_m = query(f"""
        SELECT {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {pf} AND m.currency_code = 'USD'
          AND m.calendar_date_local >= '{f['start']}' AND m.calendar_date_local < '{f['end']}'
    """)
    return {
        "reservations": int(df_res["reservations"].iloc[0]) if not df_res.empty else 0,
        "enterprises":  int(df_res["enterprises"].iloc[0])  if not df_res.empty else 0,
        "adr":       float(df_m["adr"].iloc[0])       if not df_m.empty and df_m["adr"].iloc[0]       else 0,
        "occupancy": float(df_m["occupancy"].iloc[0]) if not df_m.empty and df_m["occupancy"].iloc[0] else 0,
        "revpar":    float(df_m["revpar"].iloc[0])    if not df_m.empty and df_m["revpar"].iloc[0]    else 0,
    }


# ── YTD growth ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_ytd_growth(segment: tuple, state: tuple, city: tuple,
                    cohort_start: str = "2024-01-01") -> dict:
    geo = _geo_clause(state, city)
    parts = [
        "p.is_deleted = FALSE", "p.customer_status = 'Subscribed'",
        "p.country_name = 'United States'",
        f"CAST(p.pms_property_created_at AS DATE) < '{cohort_start}'",
        _go_live_clause(cohort_start),
    ]
    if segment:
        parts.append(f"p.commercial_segment IN ({', '.join(f'{chr(39)}{s}{chr(39)}' for s in segment)})")
    if geo:
        parts.append(geo.lstrip(" AND "))
    pf = " AND ".join(parts)

    today_mmdd = date.today().strftime("%m%d")
    df = query(f"""
        SELECT YEAR(m.calendar_date_local) AS year,
               COUNT(DISTINCT m.pms_property_id) AS property_count,
               {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {pf} AND m.currency_code = 'USD'
          AND YEAR(m.calendar_date_local) IN (2025, 2026)
          AND DATE_FORMAT(m.calendar_date_local, 'MMdd') <= '{today_mmdd}'
        GROUP BY year ORDER BY year
    """)
    if df.empty or len(df) < 2:
        return {}
    if df["property_count"].min() < MIN_PROPERTIES:
        return {"too_few": True}
    r25, r26 = df[df["year"] == 2025].iloc[0], df[df["year"] == 2026].iloc[0]
    def pct(n, o): return (float(n) - float(o)) / float(o) * 100 if float(o) else 0
    return {
        "adr_2025": float(r25["adr"]),      "adr_2026": float(r26["adr"]),
        "adr_chg":  pct(r26["adr"], r25["adr"]),
        "occ_2025": float(r25["occupancy"]), "occ_2026": float(r26["occupancy"]),
        "occ_chg":  pct(r26["occupancy"], r25["occupancy"]),
        "revpar_2025": float(r25["revpar"]), "revpar_2026": float(r26["revpar"]),
        "revpar_chg":  pct(r26["revpar"], r25["revpar"]),
    }


# ── OTB growth ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_otb_growth(segment: tuple, state: tuple, city: tuple,
                    cohort_start: str = "2024-01-01") -> dict:
    geo = _geo_clause(state, city)
    parts = [
        "p.is_deleted = FALSE", "p.customer_status = 'Subscribed'",
        "p.country_name = 'United States'",
        f"CAST(p.pms_property_created_at AS DATE) < '{cohort_start}'",
        _go_live_clause(cohort_start),
    ]
    if segment:
        parts.append(f"p.commercial_segment IN ({', '.join(f'{chr(39)}{s}{chr(39)}' for s in segment)})")
    if geo:
        parts.append(geo.lstrip(" AND "))
    pf = " AND ".join(parts)

    snap_df = query("SELECT MAX(snapshot_date_local) AS latest FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property_on_the_books")
    if snap_df.empty or snap_df["latest"].iloc[0] is None:
        return {}
    snap    = date.fromisoformat(str(snap_df["latest"].iloc[0]))
    snap_ly = date(snap.year - 1, snap.month, snap.day)

    df = query(f"""
        SELECT CASE WHEN m.snapshot_date_local='{snap}' THEN 'this_year'
                    WHEN m.snapshot_date_local='{snap_ly}' THEN 'last_year' END AS period,
               COUNT(DISTINCT m.pms_property_id) AS property_count,
               {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property_on_the_books m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {pf} AND m.currency_code = 'USD'
          AND m.snapshot_date_local IN ('{snap}','{snap_ly}')
          AND DATEDIFF(m.on_the_books_date_local, m.snapshot_date_local) BETWEEN 0 AND 274
        GROUP BY period
    """)
    if df.empty or len(df) < 2:
        return {}
    if df["property_count"].min() < MIN_PROPERTIES:
        return {"too_few": True}
    ty = df[df["period"] == "this_year"].iloc[0]
    ly = df[df["period"] == "last_year"].iloc[0]
    def pct(n, o): return (float(n) - float(o)) / float(o) * 100 if float(o) else 0
    return {
        "adr_ly": float(ly["adr"]),       "adr_ty": float(ty["adr"]),
        "adr_chg": pct(ty["adr"], ly["adr"]),
        "occ_ly": float(ly["occupancy"]), "occ_ty": float(ty["occupancy"]),
        "occ_chg": pct(ty["occupancy"], ly["occupancy"]),
        "revpar_ly": float(ly["revpar"]), "revpar_ty": float(ty["revpar"]),
        "revpar_chg": pct(ty["revpar"], ly["revpar"]),
        "snap_date": str(snap),
    }


# ── Historical trends ──────────────────────────────────────────────────────────
def load_trends(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    df = query(f"""
        SELECT m.calendar_date_local AS date,
               YEAR(m.calendar_date_local) AS year,
               COUNT(DISTINCT m.pms_property_id) AS property_count,
               {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {pf} AND m.currency_code = 'USD'
          AND m.calendar_date_local >= '{f['start']}' AND m.calendar_date_local < '{f['end']}'
        GROUP BY m.calendar_date_local ORDER BY m.calendar_date_local
    """)
    if df.empty:
        return df
    df = df[df["property_count"] >= MIN_PROPERTIES]
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["year"].astype(str)
    df = df.sort_values("date")
    for col in ["adr", "occupancy", "revpar"]:
        df[col] = df.groupby("year")[col].transform(lambda x: x.rolling(7, min_periods=1).mean())
    df["day_of_year"] = df["date"].dt.dayofyear
    df["month_label"] = df["date"].dt.strftime("%b")
    return df


# ── OTB trends ─────────────────────────────────────────────────────────────────
def load_otb_trends(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    snap_df = query("SELECT MAX(snapshot_date_local) AS latest FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property_on_the_books")
    if snap_df.empty or snap_df["latest"].iloc[0] is None:
        return pd.DataFrame()
    snap    = date.fromisoformat(str(snap_df["latest"].iloc[0]))
    snap_ly = date(snap.year - 1, snap.month, snap.day)

    df = query(f"""
        SELECT DATEDIFF(m.on_the_books_date_local, m.snapshot_date_local) AS days_ahead,
               CASE WHEN m.snapshot_date_local='{snap}' THEN 'This Year (OTB)'
                    WHEN m.snapshot_date_local='{snap_ly}' THEN 'Last Year (OTB)' END AS year_label,
               COUNT(DISTINCT m.pms_property_id) AS property_count,
               {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property_on_the_books m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {pf} AND m.currency_code = 'USD'
          AND m.snapshot_date_local IN ('{snap}','{snap_ly}')
          AND DATEDIFF(m.on_the_books_date_local, m.snapshot_date_local) BETWEEN 0 AND 274
        GROUP BY days_ahead, year_label ORDER BY days_ahead
    """)
    if df.empty:
        return df
    df = df[df["year_label"].notna() & (df["property_count"] >= MIN_PROPERTIES)]
    if df.empty:
        return df
    df = df.sort_values(["year_label", "days_ahead"])
    for col in ["adr", "occupancy", "revpar"]:
        df[col] = df.groupby("year_label")[col].transform(lambda x: x.rolling(7, min_periods=1).mean())
    df["display_date"] = df["days_ahead"].apply(
        lambda d: (snap + timedelta(days=int(d))).strftime("%b %d"))
    return df


# ── US Geographic Overview — annual & monthly ──────────────────────────────────
# These mirror the global dashboard's regional_annual / regional_monthly queries
# but use state as the dimension. The "Global" row is always US total.

@st.cache_data(ttl=3600)
def load_us_annual(segment: tuple, state: tuple, city: tuple) -> pd.DataFrame:
    """
    Annual averages (2024-2026) broken down by US state, always including a
    US-Total row. Filters by city if provided. State dimension shows selected
    states vs US total; if no states selected only US total is shown.
    """
    seg_clause = (f"AND p.commercial_segment IN "
                  f"({', '.join(f'{chr(39)}{s}{chr(39)}' for s in segment)})"
                  if segment else "")
    city_clause = ""
    if city:
        cities = ", ".join(f"'{_esc(c)}'" for c in city)
        city_clause = f"AND p.city IN ({cities})"

    today_mmdd = date.today().strftime("%m%d")
    go_live = _go_live_clause("2024-01-01")
    us_base = (f"p.is_deleted=FALSE AND p.customer_status='Subscribed' "
               f"AND p.country_name='United States' AND m.currency_code='USD' "
               f"AND YEAR(m.calendar_date_local) IN (2024,2025,2026) "
               f"AND CAST(p.pms_property_created_at AS DATE) < '2024-01-01' "
               f"AND {go_live} "
               f"AND DATE_FORMAT(m.calendar_date_local, 'MMdd') <= '{today_mmdd}' "
               f"{seg_clause} {city_clause}")

    # US total
    global_df = query(f"""
        SELECT 'US Total' AS state,
               YEAR(m.calendar_date_local) AS year,
               COUNT(DISTINCT m.pms_property_id) AS property_count,
               {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {us_base}
        GROUP BY year ORDER BY year
    """)

    if not state:
        return global_df

    # Per-state breakdown for selected states only
    state_codes = ", ".join(f"'{_esc(s)}'" for s in state)
    df = query(f"""
        SELECT STATE_CODE_TO_NAME.get(
                   get_json_object(p.inlined_address_value,'$.CountrySubdivisionCode'),
                   get_json_object(p.inlined_address_value,'$.CountrySubdivisionCode')
               ) AS state,
               YEAR(m.calendar_date_local) AS year,
               COUNT(DISTINCT m.pms_property_id) AS property_count,
               {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {us_base}
          AND get_json_object(p.inlined_address_value,'$.CountrySubdivisionCode') IN ({state_codes})
        GROUP BY state, year ORDER BY state, year
    """)
    # The MAP lookup above won't work in Spark SQL — resolve in Python instead
    state_codes_list = list(state)
    df2 = query(f"""
        SELECT get_json_object(p.inlined_address_value,'$.CountrySubdivisionCode') AS state_code,
               YEAR(m.calendar_date_local) AS year,
               COUNT(DISTINCT m.pms_property_id) AS property_count,
               {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {us_base}
          AND get_json_object(p.inlined_address_value,'$.CountrySubdivisionCode') IN ({state_codes})
        GROUP BY state_code, year ORDER BY state_code, year
    """)
    if not df2.empty:
        df2["state"] = df2["state_code"].map(STATE_CODE_TO_NAME).fillna(df2["state_code"])
        df2 = df2.drop(columns="state_code")
        df2 = df2[df2["property_count"] >= MIN_PROPERTIES]
    return pd.concat([global_df, df2], ignore_index=True)


@st.cache_data(ttl=3600)
def load_us_monthly(segment: tuple, start: str, end: str,
                    state: tuple, city: tuple) -> pd.DataFrame:
    """Monthly trends broken down by US state, always including US Total."""
    seg_clause = (f"AND p.commercial_segment IN "
                  f"({', '.join(f'{chr(39)}{s}{chr(39)}' for s in segment)})"
                  if segment else "")
    city_clause = ""
    if city:
        cities = ", ".join(f"'{_esc(c)}'" for c in city)
        city_clause = f"AND p.city IN ({cities})"

    go_live = _go_live_clause(start)
    us_base = (f"p.is_deleted=FALSE AND p.customer_status='Subscribed' "
               f"AND p.country_name='United States' AND m.currency_code='USD' "
               f"AND CAST(p.pms_property_created_at AS DATE) < '{start}' "
               f"AND {go_live} "
               f"AND m.calendar_date_local >= '{start}' AND m.calendar_date_local < '{end}' "
               f"{seg_clause} {city_clause}")

    global_df = query(f"""
        SELECT 'US Total' AS state,
               DATE_TRUNC('MONTH', m.calendar_date_local) AS month,
               COUNT(DISTINCT m.pms_property_id) AS property_count,
               {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {us_base}
        GROUP BY month ORDER BY month
    """)

    if not state:
        combined = global_df.copy()
        combined["month"] = pd.to_datetime(combined["month"])
        return combined.sort_values(["state", "month"])

    state_codes = ", ".join(f"'{_esc(s)}'" for s in state)
    df2 = query(f"""
        SELECT get_json_object(p.inlined_address_value,'$.CountrySubdivisionCode') AS state_code,
               DATE_TRUNC('MONTH', m.calendar_date_local) AS month,
               COUNT(DISTINCT m.pms_property_id) AS property_count,
               {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {us_base}
          AND get_json_object(p.inlined_address_value,'$.CountrySubdivisionCode') IN ({state_codes})
        GROUP BY state_code, month ORDER BY state_code, month
    """)
    if not df2.empty:
        df2["state"] = df2["state_code"].map(STATE_CODE_TO_NAME).fillna(df2["state_code"])
        df2 = df2.drop(columns="state_code")
        df2 = df2[df2["property_count"] >= MIN_PROPERTIES]

    combined = pd.concat([global_df, df2], ignore_index=True)
    combined["month"] = pd.to_datetime(combined["month"])
    return combined.sort_values(["state", "month"])


# ── Shared mrt_reservations_and_guests filter ──────────────────────────────────
def _mrt_res_filter(f: dict) -> str:
    geo = _geo_clause(tuple(f.get("state") or []), tuple(f.get("city") or []))
    parts = [
        "p.is_deleted = FALSE", "p.customer_status = 'Subscribed'",
        "p.country_name = 'United States'",
        f"CAST(p.pms_property_created_at AS DATE) < '{f['start']}'",
        _go_live_clause(f['start']),
        "r.reservation_state != 'Canceled'",
        f"r.backfilled_reservation_started_at >= '{f['start']}'",
        f"r.backfilled_reservation_started_at < '{f['end']}'",
    ]
    if f.get("segment"):
        s_list = ", ".join(f"'{_esc(s)}'" for s in f["segment"])
        parts.append(f"p.commercial_segment IN ({s_list})")
    if geo:
        parts.append(geo.lstrip(" AND "))
    return " AND ".join(parts)


# ── Lead time ──────────────────────────────────────────────────────────────────
LEAD_TIME_ORDER = ["0 - Same day", "1-3 days", "4-7 days", "8-14 days",
                   "15-30 days", "31-60 days", "61-90 days", "90+ days"]

def load_lead_time(f: dict) -> pd.DataFrame:
    mf = _mrt_res_filter(f)
    df = query(f"""
        SELECT CASE WHEN r.lead_time_days = 0 THEN '0 - Same day'
                    WHEN r.lead_time_days BETWEEN 1 AND 3 THEN '1-3 days'
                    WHEN r.lead_time_days BETWEEN 4 AND 7 THEN '4-7 days'
                    WHEN r.lead_time_days BETWEEN 8 AND 14 THEN '8-14 days'
                    WHEN r.lead_time_days BETWEEN 15 AND 30 THEN '15-30 days'
                    WHEN r.lead_time_days BETWEEN 31 AND 60 THEN '31-60 days'
                    WHEN r.lead_time_days BETWEEN 61 AND 90 THEN '61-90 days'
                    ELSE '90+ days' END AS lead_time_bucket,
               SUM(r.count_reservations) AS reservations
        FROM product.marts.mrt_reservations_and_guests r
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        WHERE {mf} AND r.lead_time_days IS NOT NULL
        GROUP BY lead_time_bucket
    """)
    df["lead_time_bucket"] = pd.Categorical(df["lead_time_bucket"], categories=LEAD_TIME_ORDER, ordered=True)
    return df.sort_values("lead_time_bucket")


# ── Length of stay ─────────────────────────────────────────────────────────────
LOS_ORDER = ["1 night", "2 nights", "3 nights", "4-7 nights", "8-14 nights", "15+ nights"]

def load_length_of_stay(f: dict) -> pd.DataFrame:
    mf = _mrt_res_filter(f)
    df = query(f"""
        SELECT CASE WHEN r.stay_length_days = 1 THEN '1 night'
                    WHEN r.stay_length_days = 2 THEN '2 nights'
                    WHEN r.stay_length_days = 3 THEN '3 nights'
                    WHEN r.stay_length_days BETWEEN 4 AND 7 THEN '4-7 nights'
                    WHEN r.stay_length_days BETWEEN 8 AND 14 THEN '8-14 nights'
                    ELSE '15+ nights' END AS los_bucket,
               SUM(r.count_reservations) AS reservations
        FROM product.marts.mrt_reservations_and_guests r
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        WHERE {mf} AND r.stay_length_days IS NOT NULL AND r.stay_length_days > 0
        GROUP BY los_bucket
    """)
    df["los_bucket"] = pd.Categorical(df["los_bucket"], categories=LOS_ORDER, ordered=True)
    return df.sort_values("los_bucket")


# ── Group size ─────────────────────────────────────────────────────────────────
def load_group_size(f: dict) -> pd.DataFrame:
    mf = _mrt_res_filter(f)
    return query(f"""
        SELECT CASE WHEN r.person_count = 1 THEN '1 guest'
                    WHEN r.person_count = 2 THEN '2 guests'
                    WHEN r.person_count = 3 THEN '3 guests'
                    WHEN r.person_count BETWEEN 4 AND 6 THEN '4-6 guests'
                    ELSE '7+ guests' END AS group_size_bucket,
               SUM(r.count_reservations) AS reservations
        FROM product.marts.mrt_reservations_and_guests r
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        WHERE {mf} AND r.person_count IS NOT NULL
        GROUP BY group_size_bucket ORDER BY MIN(r.person_count)
    """)


# ── Channel ────────────────────────────────────────────────────────────────────
def load_channel(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    df = query(f"""
        SELECT ra.reservation_origin AS origin,
               ra.reservation_commander_origin AS commander_origin,
               COUNT(DISTINCT r.reservation_id) AS reservations
        FROM product.facts.fct_reservations r
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        JOIN product.dimensions.dim_reservation_attributes ra
          ON r.reservation_attributes_key = ra.reservation_attributes_key
        WHERE {pf} AND {res_date_filter(f)} AND ra.reservation_origin != 'Import'
        GROUP BY ra.reservation_origin, ra.reservation_commander_origin
    """)
    if df.empty:
        return df
    def bucket(row):
        o, co = row["origin"] or "", row["commander_origin"] or ""
        if o in ("ChannelManager", "Connector"): return "Third-Party Channels"
        if o in ("Distributor", "Navigator"):    return "Online Direct"
        if o == "Commander" and co == "Website": return "Online Direct"
        if o == "Commander":                     return "Offline Direct"
        return None
    df["channel"] = df.apply(bucket, axis=1)
    return df[df["channel"].notna()].groupby("channel")["reservations"].sum().reset_index()


# ── Payment type ───────────────────────────────────────────────────────────────
def load_payment_type(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    df = query(f"""
        SELECT td.detailed_transaction_type AS payment_type, COUNT(*) AS transactions
        FROM fintech.public.obt_transactions__all_transactions t
        JOIN fintech.public.dim_transactions__transaction_details td
          ON t.transaction_details_id = td.transaction_details_id
        JOIN product.dimensions.dim_pms_properties p ON t.enterprise_id = p.pms_property_id
        WHERE {pf} AND t.transaction_state = 'Charged'
          AND CAST(t.created_at_utc AS DATE) >= '{f['start']}'
          AND CAST(t.created_at_utc AS DATE) < '{f['end']}'
          AND td.detailed_transaction_type IS NOT NULL
        GROUP BY td.detailed_transaction_type ORDER BY transactions DESC
    """)
    if df.empty:
        return df
    def bucket(t):
        if t in {"Mews Card Payment", "Card", "Digital Wallet", "Mews Alternative Payment"}:
            return "Card & Digital Payments"
        if t in {"WireTransfer", "CrossSettlement", "Prepayment"}:
            return "Bank Transfer & Settlement"
        if t in {"Invoice", "Commission"}:
            return "Invoice & Corporate Billing"
        if t in {"Voucher", "Cheque"}:
            return "Voucher & Cheque"
        if t == "Cash":
            return "Cash"
        return "Other"
    df["category"] = df["payment_type"].apply(bucket)
    return df.groupby("category")["transactions"].sum().reset_index()


# ── Card network ───────────────────────────────────────────────────────────────
def load_card_network(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    return query(f"""
        SELECT CASE WHEN cd.payment_card_network IN ('Visa','VPay','CarteBleue') THEN 'Visa'
                    WHEN cd.payment_card_network IN ('MasterCard','Maestro','Bancontact','Bancomat','Giro') THEN 'Mastercard'
                    WHEN cd.payment_card_network = 'Amex' THEN 'Amex'
                    ELSE 'Other' END AS card_network,
               COUNT(*) AS transactions
        FROM fintech.public.obt_transactions__all_transactions t
        JOIN fintech.public.dim_transactions__card_details cd
          ON t.card_details_id = cd.card_details_id
        JOIN product.dimensions.dim_pms_properties p ON t.enterprise_id = p.pms_property_id
        WHERE {pf} AND t.transaction_state = 'Charged' AND t.is_card_transaction = TRUE
          AND CAST(t.created_at_utc AS DATE) >= '{f['start']}'
          AND CAST(t.created_at_utc AS DATE) < '{f['end']}'
        GROUP BY card_network ORDER BY transactions DESC
    """)


# ── P&L ────────────────────────────────────────────────────────────────────────
def load_pnl_monthly(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    df = query(f"""
        SELECT DATE_TRUNC('MONTH', m.revenue_date_local) AS month,
               m.accounting_category_classification AS category,
               COUNT(DISTINCT m.pms_property_id) AS property_count,
               SUM(m.total_adjusted_net_value) AS net_revenue
        FROM product.marts.mrt_daily_property_revenue_per_accounting_category_classification m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {pf} AND m.currency_code = 'USD'
          AND m.revenue_date_local >= '{f['start']}' AND m.revenue_date_local < '{f['end']}'
          AND m.accounting_category_revenue_type NOT IN ('PaymentsRevenue','TaxesRevenue')
        GROUP BY month, category ORDER BY month, net_revenue DESC
    """)
    if df.empty:
        return df
    df = df[df["property_count"] >= MIN_PROPERTIES]
    if df.empty:
        return df
    df["month"]    = pd.to_datetime(df["month"])
    df["category"] = df["category"].map(PNL_LABEL_MAP).fillna(df["category"])
    return df


def load_pnl_mix(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    df = query(f"""
        SELECT m.accounting_category_classification AS category,
               COUNT(DISTINCT m.pms_property_id) AS property_count,
               SUM(m.total_adjusted_net_value) AS net_revenue
        FROM product.marts.mrt_daily_property_revenue_per_accounting_category_classification m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {pf} AND m.currency_code = 'USD'
          AND m.revenue_date_local >= '{f['start']}' AND m.revenue_date_local < '{f['end']}'
          AND m.accounting_category_revenue_type NOT IN ('PaymentsRevenue','TaxesRevenue')
        GROUP BY category ORDER BY net_revenue DESC
    """)
    if df.empty:
        return df
    df = df[df["property_count"] >= MIN_PROPERTIES]
    if df.empty:
        return df
    df["category"] = df["category"].map(PNL_LABEL_MAP).fillna(df["category"])
    return df


# ── Revenue per sqm ────────────────────────────────────────────────────────────
def load_revenue_per_sqm(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    df = query(f"""
        SELECT rev.accounting_category_classification AS category,
               COUNT(DISTINCT rev.pms_property_id) AS property_count,
               SUM(rev.total_adjusted_net_value) AS total_revenue,
               SUM(rev.total_adjusted_net_value) / NULLIF(SUM(CASE
                   WHEN rev.accounting_category_classification='Accommodation'
                       THEN sqm.room_area_meters_squared
                   WHEN rev.accounting_category_classification='FoodAndBeverage'
                       THEN sqm.eating_and_drinking_areas_meters_squared
                   WHEN rev.accounting_category_classification='Events'
                       THEN sqm.meeting_and_event_rooms_area_meters_squared
                   WHEN rev.accounting_category_classification IN ('Wellness','Sport')
                       THEN sqm.wellness_and_sports_area_meters_squared
               END), 0) AS revenue_per_sqm
        FROM product.marts.mrt_daily_property_revenue_per_accounting_category_classification rev
        JOIN tech.value_pillars.dim_scraped_property_sqm_estimations sqm
          ON rev.pms_property_id = sqm.pms_property_id
        JOIN product.dimensions.dim_pms_properties p ON rev.pms_property_id = p.pms_property_id
        WHERE {pf} AND rev.currency_code = 'USD'
          AND rev.revenue_date_local >= '{f['start']}' AND rev.revenue_date_local < '{f['end']}'
          AND rev.accounting_category_revenue_type NOT IN ('PaymentsRevenue','TaxesRevenue')
          AND rev.accounting_category_classification IN
              ('Accommodation','FoodAndBeverage','Events','Wellness','Sport')
          AND sqm.accuracy_grade >= 3
        GROUP BY category ORDER BY revenue_per_sqm DESC
    """)
    if df.empty:
        return df
    df = df[df["property_count"] >= MIN_PROPERTIES]
    if df.empty:
        return df
    df["category"] = df["category"].map({
        "Accommodation": "Rooms", "FoodAndBeverage": "Food & Beverage",
        "Events": "Events & Meetings", "Wellness": "Wellness & Spa",
        "Sport": "Sport & Recreation",
    }).fillna(df["category"])
    return df


# ── Upsells (EUR → constant USD) ───────────────────────────────────────────────
def load_upsell_by_channel(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    df = query(f"""
        SELECT COUNT(DISTINCT u.pms_property_id) AS property_count,
               SUM(u.count_booking_engine_upsells) AS booking_engine,
               SUM(u.count_kiosk_upsells)          AS kiosk,
               SUM(u.count_guest_portal_upsells)   AS online_checkin,
               SUM(u.count_front_desk_upsells)     AS front_desk
        FROM product.marts.mrt_daily_upsells_channel_shares_and_weights_per_accounting_category u
        JOIN product.dimensions.dim_pms_properties p ON u.pms_property_id = p.pms_property_id
        WHERE {pf} AND u.checkin_date >= '{f['start']}' AND u.checkin_date < '{f['end']}'
    """)
    if df.empty or int(df["property_count"].iloc[0] or 0) < MIN_PROPERTIES:
        return pd.DataFrame()
    row = df.iloc[0]
    result = pd.DataFrame({
        "channel": ["Booking Engine", "Kiosk", "Online Check-in (OCI)", "Front Desk (PMS)"],
        "upsells": [float(row["booking_engine"] or 0), float(row["kiosk"] or 0),
                    float(row["online_checkin"] or 0), float(row["front_desk"] or 0)],
    })
    total = result["upsells"].sum()
    result["pct"] = result["upsells"] / total * 100 if total > 0 else 0
    return result


def load_upsell_by_category(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    return query(f"""
        SELECT COALESCE(u.accounting_category_classification,'NotAssigned') AS category,
               SUM(u.count_total_upsells) AS upsells,
               SUM(u.total_upsell_gross_value_eur) * {EUR_TO_USD_FIXED} AS total_value,
               CASE WHEN SUM(u.count_total_upsells) > 0
                    THEN SUM(u.total_upsell_gross_value_eur) * {EUR_TO_USD_FIXED}
                         / SUM(u.count_total_upsells)
                    ELSE 0 END AS avg_value
        FROM product.marts.mrt_daily_upsells_by_product u
        JOIN product.dimensions.dim_pms_properties p ON u.pms_property_id = p.pms_property_id
        WHERE {pf} AND u.checkin_date >= '{f['start']}' AND u.checkin_date < '{f['end']}'
          AND u.accounting_category_classification NOT IN ('Payments','Taxes','NotAssigned')
        GROUP BY category ORDER BY upsells DESC LIMIT 10
    """)


def load_upsell_avg_value_by_channel(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    df = query(f"""
        SELECT COUNT(DISTINCT u.pms_property_id) AS property_count,
               AVG(u.avg_booking_engine_upsell_value_per_reservation_eur) * {EUR_TO_USD_FIXED} AS booking_engine,
               AVG(u.avg_kiosk_upsell_value_per_reservation_eur)          * {EUR_TO_USD_FIXED} AS kiosk,
               AVG(u.avg_guest_portal_upsell_value_per_reservation_eur)   * {EUR_TO_USD_FIXED} AS online_checkin,
               AVG(u.avg_front_desk_upsell_value_per_reservation_eur)     * {EUR_TO_USD_FIXED} AS front_desk
        FROM product.marts.mrt_daily_upsells_channel_shares_and_weights_per_accounting_category u
        JOIN product.dimensions.dim_pms_properties p ON u.pms_property_id = p.pms_property_id
        WHERE {pf} AND u.checkin_date >= '{f['start']}' AND u.checkin_date < '{f['end']}'
    """)
    if df.empty or int(df["property_count"].iloc[0] or 0) < MIN_PROPERTIES:
        return pd.DataFrame()
    row = df.iloc[0]
    return pd.DataFrame({
        "channel":   ["Booking Engine", "Kiosk", "Online Check-in (OCI)", "Front Desk (PMS)"],
        "avg_value": [float(row["booking_engine"] or 0), float(row["kiosk"] or 0),
                      float(row["online_checkin"] or 0), float(row["front_desk"] or 0)],
    })


# ── Check-in ───────────────────────────────────────────────────────────────────
def load_checkin_prestay(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    return query(f"""
        SELECT 'Online Check-in (OCI)' AS checkin_method, COUNT(*) AS reservations
        FROM product.facts.fct_reservation_checkins__online ci
        JOIN product.facts.fct_reservations r ON ci.reservation_id = r.reservation_id
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        WHERE {pf}
          AND ci.online_check_in_finished_at >= '{f['start']}'
          AND ci.online_check_in_finished_at < '{f['end']}'
          AND r.is_reservation_deleted = FALSE
    """)


def load_checkin_athotel(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    df_kfd = query(f"""
        SELECT SUM(ci.count_kiosk_checkins + ci.count_non_mews_kiosk_checkins) AS kiosk,
               SUM(ci.count_front_desk_checkins) AS front_desk
        FROM product.marts.mrt_daily_checkins_channel_shares_and_weights ci
        JOIN product.dimensions.dim_pms_properties p ON ci.pms_property_id = p.pms_property_id
        WHERE {pf} AND ci.checkin_date >= '{f['start']}' AND ci.checkin_date < '{f['end']}'
    """)
    df_dk = query(f"""
        SELECT SUM(dk.count_reservations) AS digital_key
        FROM product.marts.mrt_digital_key_checkin_metrics dk
        JOIN product.dimensions.dim_pms_properties p ON dk.pms_property_id = p.pms_property_id
        WHERE {pf} AND dk.arrival_date >= '{f['start']}' AND dk.arrival_date < '{f['end']}'
          AND dk.checkin_type = 'Mews Digital Key' AND dk.has_opened_door = 'opened door'
    """)
    rows = []
    if not df_kfd.empty:
        rows.append({"checkin_method": "Kiosk",            "reservations": float(df_kfd["kiosk"].iloc[0] or 0)})
        rows.append({"checkin_method": "Front Desk (PMS)", "reservations": float(df_kfd["front_desk"].iloc[0] or 0)})
    if not df_dk.empty:
        rows.append({"checkin_method": "Digital Key",      "reservations": float(df_dk["digital_key"].iloc[0] or 0)})
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── Day of week ────────────────────────────────────────────────────────────────
def load_checkin_dow(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    df = query(f"""
        SELECT DATE_FORMAT(r.reservation_planned_start_at, 'EEEE') AS day_of_week,
               COUNT(*) AS reservations
        FROM product.facts.fct_reservations r
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        WHERE {pf} AND {res_date_filter(f)}
        GROUP BY day_of_week
    """)
    df["day_of_week"] = pd.Categorical(df["day_of_week"], categories=DOW_ORDER, ordered=True)
    df["pct"] = df["reservations"] / df["reservations"].sum() * 100
    return df.sort_values("day_of_week")


def load_checkout_dow(f: dict) -> pd.DataFrame:
    pf = prop_filter(f)
    df = query(f"""
        SELECT DATE_FORMAT(r.reservation_planned_end_at, 'EEEE') AS day_of_week,
               COUNT(*) AS reservations
        FROM product.facts.fct_reservations r
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        WHERE {pf} AND {res_date_filter(f)}
        GROUP BY day_of_week
    """)
    df["day_of_week"] = pd.Categorical(df["day_of_week"], categories=DOW_ORDER, ordered=True)
    df["pct"] = df["reservations"] / df["reservations"].sum() * 100
    return df.sort_values("day_of_week")


# ── Cancellations ──────────────────────────────────────────────────────────────
def _canc_base_filter(f: dict) -> str:
    geo = _geo_clause(tuple(f.get("state") or []), tuple(f.get("city") or []))
    parts = ["p.is_deleted = FALSE", "p.customer_status = 'Subscribed'",
             "p.country_name = 'United States'"]
    if f.get("segment"):
        s_list = ", ".join(f"'{_esc(s)}'" for s in f["segment"])
        parts.append(f"p.commercial_segment IN ({s_list})")
    if geo:
        parts.append(geo.lstrip(" AND "))
    return " AND ".join(parts)


def load_cancellation_stats(f: dict) -> pd.DataFrame:
    pf_base = _canc_base_filter(f)
    df = query(f"""
        SELECT YEAR(r.reservation_created_at) AS year,
               COUNT(DISTINCT r.pms_property_id) AS property_count,
               COUNT(*) AS total_bookings,
               SUM(CASE WHEN r.reservation_state_code = 4 THEN 1 ELSE 0 END) AS cancellations,
               AVG(CASE WHEN r.reservation_state_code = 4
                   THEN DATEDIFF(r.reservation_planned_start_at, r.reservation_canceled_at)
                   ELSE NULL END) AS avg_cancel_window
        FROM product.facts.fct_reservations r
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        WHERE {pf_base} AND r.is_reservation_deleted = FALSE
          AND YEAR(r.reservation_created_at) IN (2024, 2025, 2026)
          AND CAST(p.pms_property_created_at AS DATE)
              < MAKE_DATE(YEAR(r.reservation_created_at), 1, 1)
          AND (p.go_live_date IS NULL OR CAST(p.go_live_date AS DATE)
              <= DATE_SUB(MAKE_DATE(YEAR(r.reservation_created_at), 1, 1), 90))
        GROUP BY year ORDER BY year
    """)
    if df.empty:
        return df
    df = df[df["property_count"] >= MIN_PROPERTIES]
    if df.empty:
        return df
    df["cancel_rate"] = df["cancellations"] / df["total_bookings"] * 100
    return df


def load_cancellation_by_channel(f: dict) -> pd.DataFrame:
    pf_base = _canc_base_filter(f)
    df = query(f"""
        SELECT YEAR(r.reservation_created_at) AS year,
               CASE
                   WHEN ra.reservation_origin IN ('ChannelManager','Connector') THEN 'Third-Party'
                   WHEN ra.reservation_origin IN ('Distributor','Navigator')    THEN 'Direct'
                   WHEN ra.reservation_origin = 'Commander'
                        AND ra.reservation_commander_origin = 'Website'         THEN 'Direct'
                   WHEN ra.reservation_origin = 'Commander'                     THEN 'Direct'
               END AS channel,
               COUNT(DISTINCT r.pms_property_id) AS property_count,
               COUNT(*) AS total_bookings,
               SUM(CASE WHEN r.reservation_state_code = 4 THEN 1 ELSE 0 END) AS cancellations,
               AVG(CASE WHEN r.reservation_state_code = 4
                   THEN DATEDIFF(r.reservation_planned_start_at, r.reservation_canceled_at)
                   ELSE NULL END) AS avg_cancel_window
        FROM product.facts.fct_reservations r
        JOIN product.dimensions.dim_reservation_attributes ra
          ON r.reservation_attributes_key = ra.reservation_attributes_key
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        WHERE {pf_base} AND r.is_reservation_deleted = FALSE
          AND ra.reservation_origin != 'Import'
          AND YEAR(r.reservation_created_at) IN (2024, 2025, 2026)
          AND CAST(p.pms_property_created_at AS DATE)
              < MAKE_DATE(YEAR(r.reservation_created_at), 1, 1)
          AND (p.go_live_date IS NULL OR CAST(p.go_live_date AS DATE)
              <= DATE_SUB(MAKE_DATE(YEAR(r.reservation_created_at), 1, 1), 90))
        GROUP BY year, channel
        HAVING channel IS NOT NULL
        ORDER BY year, channel
    """)
    if df.empty:
        return df
    df = df[df["property_count"] >= MIN_PROPERTIES]
    if df.empty:
        return df
    df["cancel_rate"] = df["cancellations"] / df["total_bookings"] * 100
    return df


# ── Annual booking behaviour averages ──────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_behaviour_annual(segment: tuple, state: tuple, city: tuple) -> dict:
    geo = _geo_clause(state, city)
    parts = ["p.is_deleted = FALSE", "p.customer_status = 'Subscribed'",
             "p.country_name = 'United States'"]
    if segment:
        parts.append(f"p.commercial_segment IN ({', '.join(f'{chr(39)}{s}{chr(39)}' for s in segment)})")
    if geo:
        parts.append(geo.lstrip(" AND "))
    pf_base = " AND ".join(parts)

    df_avg = query(f"""
        SELECT YEAR(r.reservation_planned_start_at) AS year,
               COUNT(DISTINCT r.pms_property_id) AS property_count,
               AVG(DATEDIFF(r.reservation_planned_end_at, r.reservation_planned_start_at)) AS avg_los,
               AVG(r.person_count) AS avg_group_size,
               AVG(DATEDIFF(r.reservation_planned_start_at, r.reservation_created_at)) AS avg_lead_time
        FROM product.facts.fct_reservations r
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        WHERE {pf_base}
          AND r.reservation_state_code NOT IN (4) AND r.is_reservation_deleted = FALSE
          AND YEAR(r.reservation_planned_start_at) IN (2024, 2025, 2026)
          AND CAST(p.pms_property_created_at AS DATE)
              < MAKE_DATE(YEAR(r.reservation_planned_start_at), 1, 1)
          AND (p.go_live_date IS NULL OR CAST(p.go_live_date AS DATE)
              <= DATE_SUB(MAKE_DATE(YEAR(r.reservation_planned_start_at), 1, 1), 90))
        GROUP BY year ORDER BY year
    """)
    if not df_avg.empty:
        df_avg = df_avg[df_avg["property_count"] >= MIN_PROPERTIES]

    df_ch = query(f"""
        SELECT YEAR(r.reservation_planned_start_at) AS year,
               ra.reservation_origin AS origin,
               ra.reservation_commander_origin AS commander_origin,
               COUNT(DISTINCT r.reservation_id) AS reservations
        FROM product.facts.fct_reservations r
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        JOIN product.dimensions.dim_reservation_attributes ra
          ON r.reservation_attributes_key = ra.reservation_attributes_key
        WHERE {pf_base}
          AND r.reservation_state_code NOT IN (4) AND r.is_reservation_deleted = FALSE
          AND ra.reservation_origin != 'Import'
          AND YEAR(r.reservation_planned_start_at) IN (2024, 2025, 2026)
          AND CAST(p.pms_property_created_at AS DATE)
              < MAKE_DATE(YEAR(r.reservation_planned_start_at), 1, 1)
          AND (p.go_live_date IS NULL OR CAST(p.go_live_date AS DATE)
              <= DATE_SUB(MAKE_DATE(YEAR(r.reservation_planned_start_at), 1, 1), 90))
        GROUP BY year, origin, commander_origin
    """)

    def bucket(row):
        o, co = row["origin"] or "", row["commander_origin"] or ""
        if o in ("ChannelManager", "Connector"): return "Third-Party"
        if o in ("Distributor", "Navigator"):    return "Online Direct"
        if o == "Commander" and co == "Website": return "Online Direct"
        if o == "Commander":                     return "Offline Direct"
        return None

    channel_pcts = {}
    if not df_ch.empty:
        df_ch["channel"] = df_ch.apply(bucket, axis=1)
        df_ch = df_ch[df_ch["channel"].notna()]
        for yr in [2024, 2025, 2026]:
            yr_df = df_ch[df_ch["year"] == yr]
            if yr_df.empty:
                channel_pcts[yr] = {}
                continue
            total = yr_df["reservations"].sum()
            channel_pcts[yr] = {
                row["channel"]: row["reservations"] / total * 100
                for _, row in yr_df.groupby("channel")["reservations"]
                .sum().reset_index().iterrows()
            }
    return {"averages": df_avg, "channel_pcts": channel_pcts}


# ── Hotel Class ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_hotelclass_annual(segment: tuple, state: tuple, city: tuple) -> pd.DataFrame:
    geo = _geo_clause(state, city)
    seg_clause = (f"AND p.commercial_segment IN "
                  f"({', '.join(f'{chr(39)}{s}{chr(39)}' for s in segment)})"
                  if segment else "")
    geo_clause = geo if geo else ""
    today_mmdd = date.today().strftime("%m%d")
    go_live = _go_live_clause("2024-01-01")
    us_base = (f"p.is_deleted=FALSE AND p.customer_status='Subscribed' "
               f"AND p.country_name='United States' AND m.currency_code='USD' "
               f"AND YEAR(m.calendar_date_local) IN (2024,2025,2026) "
               f"AND CAST(p.pms_property_created_at AS DATE) < '2024-01-01' "
               f"AND {go_live} "
               f"AND DATE_FORMAT(m.calendar_date_local, 'MMdd') <= '{today_mmdd}' "
               f"{seg_clause} {geo_clause}")
    df = query(f"""
        SELECT p.hotel_class, YEAR(m.calendar_date_local) AS year,
               COUNT(DISTINCT m.pms_property_id) AS property_count, {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {us_base} AND p.hotel_class IS NOT NULL
        GROUP BY hotel_class, year ORDER BY hotel_class, year
    """)
    global_df = query(f"""
        SELECT 'Global' AS hotel_class, YEAR(m.calendar_date_local) AS year,
               COUNT(DISTINCT m.pms_property_id) AS property_count, {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {us_base}
        GROUP BY year ORDER BY year
    """)
    if not df.empty:
        df = df[df["property_count"] >= MIN_PROPERTIES]
    return pd.concat([global_df, df], ignore_index=True)


@st.cache_data(ttl=3600)
def load_hotelclass_monthly(segment: tuple, start: str, end: str,
                             state: tuple, city: tuple) -> pd.DataFrame:
    geo = _geo_clause(state, city)
    seg_clause = (f"AND p.commercial_segment IN "
                  f"({', '.join(f'{chr(39)}{s}{chr(39)}' for s in segment)})"
                  if segment else "")
    geo_clause = geo if geo else ""
    go_live = _go_live_clause(start)
    us_base = (f"p.is_deleted=FALSE AND p.customer_status='Subscribed' "
               f"AND p.country_name='United States' AND m.currency_code='USD' "
               f"AND CAST(p.pms_property_created_at AS DATE)<'{start}' "
               f"AND {go_live} "
               f"AND m.calendar_date_local>='{start}' AND m.calendar_date_local<'{end}' "
               f"{seg_clause} {geo_clause}")
    df = query(f"""
        SELECT p.hotel_class, DATE_TRUNC('MONTH', m.calendar_date_local) AS month,
               COUNT(DISTINCT m.pms_property_id) AS property_count, {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {us_base} AND p.hotel_class IS NOT NULL
        GROUP BY hotel_class, month ORDER BY hotel_class, month
    """)
    global_df = query(f"""
        SELECT 'Global' AS hotel_class, DATE_TRUNC('MONTH', m.calendar_date_local) AS month,
               COUNT(DISTINCT m.pms_property_id) AS property_count, {ROOM_METRICS_SQL}
        FROM product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
        JOIN product.dimensions.dim_pms_properties p ON m.pms_property_id = p.pms_property_id
        WHERE {us_base}
        GROUP BY month ORDER BY month
    """)
    if df.empty and global_df.empty:
        return pd.DataFrame()
    if not df.empty:
        df = df[df["property_count"] >= MIN_PROPERTIES]
    combined = pd.concat([global_df, df], ignore_index=True)
    combined["month"] = pd.to_datetime(combined["month"])
    return combined.sort_values(["hotel_class", "month"])


# ── Channel behaviour (Tab 6) ──────────────────────────────────────────────────
def load_channel_behaviour(f: dict) -> pd.DataFrame:
    geo = _geo_clause(tuple(f.get("state") or []), tuple(f.get("city") or []))
    parts = ["p.is_deleted = FALSE", "p.customer_status = 'Subscribed'",
             "p.country_name = 'United States'"]
    if f.get("segment"):
        s_list = ", ".join(f"'{_esc(s)}'" for s in f["segment"])
        parts.append(f"p.commercial_segment IN ({s_list})")
    if geo:
        parts.append(geo.lstrip(" AND "))
    pf_base = " AND ".join(parts)

    df = query(f"""
        SELECT YEAR(r.reservation_created_date) AS year,
               CASE
                   WHEN r.reservation_origin IN ('ChannelManager','Connector') THEN 'Third-Party'
                   WHEN r.reservation_origin IN ('Distributor','Navigator')    THEN 'Direct'
                   WHEN r.reservation_origin = 'Commander'
                        AND r.reservation_commander_origin = 'Website'         THEN 'Direct'
                   WHEN r.reservation_origin = 'Commander'                     THEN 'Direct'
               END AS channel,
               COUNT(DISTINCT r.pms_property_id) AS property_count,
               SUM(r.count_reservations) AS total_reservations,
               SUM(r.stay_length_days * r.count_reservations)
                   / NULLIF(SUM(r.count_reservations), 0) AS avg_los,
               SUM(r.lead_time_days * r.count_reservations)
                   / NULLIF(SUM(r.count_reservations), 0) AS avg_lead_time,
               SUM(r.person_count * r.count_reservations)
                   / NULLIF(SUM(r.count_reservations), 0) AS avg_group_size
        FROM product.marts.mrt_reservations_and_guests r
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        WHERE {pf_base}
          AND r.reservation_state != 'Canceled' AND r.reservation_origin != 'Import'
          AND YEAR(r.reservation_created_date) IN (2024, 2025, 2026)
          AND CAST(p.pms_property_created_at AS DATE)
              < MAKE_DATE(YEAR(r.reservation_created_date), 1, 1)
          AND (p.go_live_date IS NULL OR CAST(p.go_live_date AS DATE)
              <= DATE_SUB(MAKE_DATE(YEAR(r.reservation_created_date), 1, 1), 90))
        GROUP BY year, channel
        HAVING channel IS NOT NULL ORDER BY year, channel
    """)
    if df.empty:
        return df
    return df[df["property_count"] >= MIN_PROPERTIES]


def load_channel_adr(f: dict) -> pd.DataFrame:
    geo = _geo_clause(tuple(f.get("state") or []), tuple(f.get("city") or []))
    parts = [
        "p.is_deleted = FALSE", "p.customer_status = 'Subscribed'",
        "p.country_name = 'United States'",
        _go_live_clause(f["start"]),
        f"CAST(p.pms_property_created_at AS DATE) < '{f['start']}'",
    ]
    if f.get("segment"):
        s_list = ", ".join(f"'{_esc(s)}'" for s in f["segment"])
        parts.append(f"p.commercial_segment IN ({s_list})")
    if geo:
        parts.append(geo.lstrip(" AND "))
    pf = " AND ".join(parts)

    df = query(f"""
        SELECT YEAR(m.calendar_date_local) AS year,
               CASE
                   WHEN ra.reservation_origin IN ('ChannelManager','Connector') THEN 'Third-Party'
                   WHEN ra.reservation_origin IN ('Distributor','Navigator')    THEN 'Direct'
                   WHEN ra.reservation_origin = 'Commander'
                        AND ra.reservation_commander_origin = 'Website'         THEN 'Direct'
                   WHEN ra.reservation_origin = 'Commander'                     THEN 'Direct'
               END AS channel,
               COUNT(DISTINCT m.pms_property_id) AS property_count,
               COUNT(*) AS room_nights,
               SUM(m.total_adjusted_net_accommodation_revenue
                   / NULLIF(m.num_directly_occupied_accommodation_resources, 0))
                   / NULLIF(COUNT(*), 0) AS adr_usd
        FROM product.facts.fct_reservations r
        JOIN product.dimensions.dim_reservation_attributes ra
          ON r.reservation_attributes_key = ra.reservation_attributes_key
        JOIN product.marts.mrt_daily_resource_and_revenue_metrics_per_property m
          ON m.pms_property_id      = r.pms_property_id
         AND m.calendar_date_local >= CAST(r.reservation_planned_start_at AS DATE)
         AND m.calendar_date_local  < CAST(r.reservation_planned_end_at   AS DATE)
        JOIN product.dimensions.dim_pms_properties p ON r.pms_property_id = p.pms_property_id
        WHERE {pf} AND m.currency_code = 'USD'
          AND r.is_reservation_deleted = FALSE AND r.reservation_state_code NOT IN (4)
          AND ra.reservation_origin != 'Import'
          AND m.num_directly_occupied_accommodation_resources > 0
          AND m.calendar_date_local >= '{f['start']}' AND m.calendar_date_local < '{f['end']}'
        GROUP BY year, channel
        HAVING channel IS NOT NULL ORDER BY year, channel
    """)
    if df.empty:
        return df
    return df[df["property_count"] >= MIN_PROPERTIES]