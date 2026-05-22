# Mews Hotel Performance Dashboard — Handoff Document

**Last updated:** May 2026  
**Repo:** [github.com/woutergeerts/kpi-dashboard](https://github.com/woutergeerts/kpi-dashboard)  
**Status:** Working locally. Not yet deployed. Two-dashboard split (internal / public) is the agreed next step.

---

## 1. What This Is

A Streamlit dashboard that surfaces Mews PMS performance benchmarks from Databricks. It is designed for internal analyst use but is being split into two versions — one private/internal and one public-facing. See [Section 9](#9-next-steps) for the roadmap.

---

## 2. How to Run Locally

```bash
# 1. Clone
git clone https://github.com/woutergeerts/kpi-dashboard.git
cd kpi-dashboard

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add credentials
cp .env.example .env
# Edit .env and fill in the three Databricks values

# 4. Run
streamlit run dashboard_rooms.py
```

The app opens at `http://localhost:8501`.

---

## 3. File Structure

```
kpi-dashboard/
├── dashboard_rooms.py       ← Main Streamlit app (8 tabs)
├── queries_rooms.py         ← All Databricks SQL query functions
├── export_pptx.py           ← PowerPoint export builder
├── requirements.txt
├── .env                     ← Real credentials (gitignored)
├── .env.example             ← Credential template (committed)
├── .gitignore
└── HANDOFF.md               ← This file

# Legacy / older files (not used by the main dashboard)
├── dashboard.py
├── dashboard_US.py
├── queries.py
├── queries_US.py
├── data_dictionary.py
```

---

## 4. Credentials & Environment

Credentials live in `.env` (never committed). The three required variables:

```
DATABRICKS_HOST=adb-xxxxxxxxxxxxxxxx.x.azuredatabricks.net
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/xxxxxxxxxxxxxxxx
DATABRICKS_TOKEN=dapixxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

`queries_rooms.py` loads these via `python-dotenv` at startup. The Databricks token needs read access to:
- `product.dimensions.*`
- `product.facts.*`
- `product.marts.*`
- `fintech.public.*`
- `tech.value_pillars.*`

---

## 5. Dashboard Structure (8 Tabs)

### Sidebar filters (apply globally)
- **Region** — multiselect; maps to COUNTRY_TO_REGION dict in queries_rooms.py
- **Country** — multiselect; direct `p.country_name` filter
- **Segment** — multiselect; `p.commercial_segment`
- **Date range** — start/end date pickers
- **Local currency toggle** — appears only when exactly 1 non-EUR country is selected; switches all monetary values to native local currency pulled straight from Databricks (not an FX conversion on top of EUR)

### Tab 1 — Analyst Insights
Static text block for analyst commentary. Edit `ANALYST_TEXT`, `ANALYST_NAME`, `ANALYST_TITLE`, `ANALYST_PHOTO` at the top of `dashboard_rooms.py`.

### Tab 2 — Market KPIs
- Top-line KPI tiles (ADR, Occupancy, RevPAR, Enterprises, Reservations)
- YTD Growth table (2026 vs 2025, up to today's date)
- Historical trends (7-day rolling avg, multi-year overlay)
- OTB trends (next 9 months vs last year)
- OTB growth summary tiles

### Tab 3 — Regional Overview
- Annual averages by region (2024 / 2025 / 2026 YTD) with YoY delta
- Monthly trends by region (line charts)
- Annual averages by country (same structure)
- Monthly trends by country

### Tab 4 — Hotel Class
- Annual averages by class: Luxury / Upscale / Midscale / Economy
- Monthly trends by class
- Multi-select within the tab to pick which classes to show

### Tab 5 — Booking Behaviour
- Length of stay distribution
- Group size distribution
- Lead time distribution
- Channel mix (pie + annual split table)
- Payment type breakdown
- Card network breakdown
- Cancellation rate + avg cancel window (all channels + by channel)

### Tab 6 — Direct vs OTAs
- ADR by channel (Third-Party vs Direct)
- Avg LOS by channel
- Avg lead time by channel
- Avg group size by channel
- Cancellation rate by channel
- Avg cancellation window by channel

### Tab 7 — Hotel Performance
- Monthly revenue by department (stacked bar %)
- Revenue mix (pie)
- Revenue per m² by department
- Check-in day of week
- Checkout day of week
- Pre-stay OCI check-in rate
- At-hotel check-in method breakdown (Kiosk, Front Desk, Digital Key)
- Upsell performance (by channel, by category, avg value)

### Tab 8 — Export
Generates a branded Mews PowerPoint deck from all currently-loaded data. Uses `export_pptx.py` (python-pptx + matplotlib).

---

## 6. Key Technical Decisions

### Room-weighted metrics (ROOM_METRICS_SQL)
ADR, RevPAR, and Occupancy use a fleet-level room-weighted formula rather than a simple average of per-property rates. This means:

- **ADR** = total room revenue / total occupied rooms
- **RevPAR** = total room revenue / total available rooms
- **Occupancy** = total occupied rooms / total available rooms × 100

**Seasonality fix:** days where a property has available rooms but *zero* occupied rooms are excluded from all three denominators. This prevents seasonal markets (Greece, Spain etc.) from dragging down occupancy by counting "closed but not blocked" days.

The formula is defined as the `ROOM_METRICS_SQL` constant in `queries_rooms.py` and reused across ~12 query functions. `ROOM_METRICS_SQL_LOCAL` is a derived variant that substitutes the local-currency revenue column.

### Local currency (native, not FX conversion)
When a single non-EUR country is selected, a toggle appears to show values in local currency. This pulls the `total_adjusted_net_accommodation_revenue` (no `_eur` suffix) and `total_adjusted_net_value` columns directly from Databricks instead of converting EUR figures after the fact.

Exception: **upsell tables** (`mrt_daily_upsells_*`) have no local currency columns, so those charts continue to use the EUR value × an FX rate from `product.facts.fct_exchange_rates`.

The **Global benchmark row** in regional/country/hotel-class queries is always computed in EUR (to avoid summing GBP + EUR + USD meaninglessly), then multiplied by `fx_rate` in Python before display.

### Data suppression
Any metric computed from fewer than 5 properties (`MIN_PROPERTIES = 5`) is suppressed and replaced with a warning message. This is enforced in every query function via `df[df["property_count"] >= MIN_PROPERTIES]`.

### Caching
- `@st.cache_resource` — the Databricks connection object (one per session)
- `@st.cache_data(ttl=3600)` — all query results; 1-hour TTL

---

## 7. Key Tables Used

| Table | What it's used for |
|---|---|
| `product.dimensions.dim_pms_properties` | Property metadata, filters, country, segment, hotel class |
| `product.facts.fct_reservations` | Reservation counts, channel, DOW, cancellations |
| `product.dimensions.dim_reservation_attributes` | Booking channel / origin |
| `product.marts.mrt_daily_resource_and_revenue_metrics_per_property` | ADR, RevPAR, Occupancy (actuals) |
| `product.marts.mrt_daily_resource_and_revenue_metrics_per_property_on_the_books` | OTB forward-looking metrics |
| `product.marts.mrt_daily_property_revenue_per_accounting_category_classification` | P&L / revenue by department |
| `product.marts.mrt_reservations_and_guests` | LOS, lead time, group size |
| `product.marts.mrt_daily_upsells_by_product` | Upsell revenue by category |
| `product.marts.mrt_daily_upsells_channel_shares_and_weights_per_accounting_category` | Upsell volume by channel |
| `product.marts.mrt_daily_checkins_channel_shares_and_weights` | Check-in method (kiosk, front desk) |
| `product.marts.mrt_digital_key_checkin_metrics` | Digital key check-in count |
| `product.facts.fct_reservation_checkins__online` | OCI / pre-stay check-in |
| `product.facts.fct_exchange_rates` | FX rates (for upsell local currency only) |
| `tech.value_pillars.dim_scraped_property_sqm_estimations` | Floor area for revenue-per-m² |
| `fintech.public.obt_transactions__all_transactions` | Payment transactions |
| `fintech.public.dim_transactions__transaction_details` | Payment type detail |
| `fintech.public.dim_transactions__card_details` | Card network (Visa, Mastercard etc.) |

### Property filter logic
Active properties are defined as:
```sql
p.is_deleted = FALSE
AND p.subscription_state = 'Enabled'
AND CAST(p.pms_property_created_at AS DATE) < '{period_start}'
AND (p.go_live_date IS NULL OR CAST(p.go_live_date AS DATE) <= DATE_SUB('{period_start}', 90))
```
The 90-day go-live buffer ensures properties are included only once they've been live long enough to produce meaningful data.

---

## 8. Schema Changes Applied (vs Original Code)

These broke the original dashboard and were fixed:

| Original | Fixed | Where |
|---|---|---|
| `p.customer_status = 'Subscribed'` | `p.subscription_state = 'Enabled'` | All query functions |
| `t.created_at_utc` | `t.created_at` | Payment queries |
| `fct_exchange_rates` `valid_to IS NULL` | `valid_to = '9999-12-31'` | `load_fx_rate()` |
| Hardcoded Databricks credentials | `os.getenv()` via `.env` | Top of `queries_rooms.py` |

---

## 9. Next Steps (Agreed Direction)

The dashboard is being split into two separate GitHub repositories:

### Repo 1: Internal dashboard (current → `kpi-dashboard`)
- All current functionality preserved
- Hosted on a **private URL** (Azure App Service + Azure AD SSO, or Streamlit Teams plan)
- Live Databricks connection, 1-hour cache refresh

### Repo 2: Public dashboard (new → `kpi-dashboard-public`)
- Forked from the internal repo as a starting point
- **Data scope to be confirmed:** likely global/regional only (no country or hotel-class drill-down), no P&L or upsell data
- **Date range to be confirmed:** e.g. rolling 12 months with a deliberate lag
- **Filtering to be confirmed:** fixed view, region-only, or full sidebar
- **Update cadence to be confirmed:** monthly or quarterly refresh rather than live
- Deployed on Streamlit Community Cloud (public URL)
- UX refresh for external audiences

*These decisions are pending input from Wouter before any code is written.*

---

## 10. Running Into Problems?

**Streamlit shows stale data after a schema/query fix**  
Kill the process (`Ctrl+C`) and restart — `@st.cache_data` persists between hot-reloads.

**`UNRESOLVED_COLUMN` error**  
A Databricks table was renamed or restructured. Check the column name against the live schema using the Databricks SQL MCP connector, then update the relevant query in `queries_rooms.py`.

**`too_few` returned by growth functions**  
Fewer than 5 properties match the current filters. This is intentional — narrow the filters or select a broader geography.

**Local currency toggle not appearing**  
Only shows when exactly 1 country is selected AND that country is not in the eurozone. EUR countries (Germany, France, Netherlands etc.) don't trigger it.

**PowerPoint export is slow**  
Expected — it runs all queries again (no pre-caching) and renders ~20 matplotlib charts. Budget 30–60 seconds.
