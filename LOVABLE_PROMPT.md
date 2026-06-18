# Lovable Build Prompt — Mews Hotel Performance Dashboard

## What to build

A **public-facing hotel industry benchmark dashboard** for Mews, built as a static React/TypeScript app.  
All data comes from pre-exported JSON files in the `data/` folder — **no backend, no API calls**.  
Import them directly (e.g. `import kpis from '../data/kpis.json'`).

The app should look clean and modern, consistent with the Mews brand (dark navy + teal accent, sans-serif).

---

## File structure to create

```
src/
  data/          ← copy the exported JSON files here
  components/    ← one component per dashboard section
  App.tsx
```

---

## Data files and their schemas

### `meta.json`
```json
{
  "exported_at": "2026-06-01",
  "start_date": "2024-01-01",
  "end_date": "2026-06-01",
  "regions": ["North America", "South America", "Europe", "APAC", "MEA"],
  "countries": ["Germany", "United Kingdom", ...],
  "segments": ["Luxury", "Upscale", ...],
  "property_count": 3842
}
```
Use `exported_at` to show a "Last updated" badge. Show `property_count` as a trust signal.

---

### `kpis.json`
```json
{
  "adr":          142.50,
  "occupancy":    71.3,
  "revpar":       101.6,
  "enterprises":  1240,
  "reservations": 4820000
}
```
**Component:** 5 KPI tiles in a row.  
- ADR and RevPAR in EUR (2 decimal places).  
- Occupancy as a percentage (1 decimal).  
- Enterprises and Reservations as formatted integers.

---

### `ytd_growth.json`
```json
{
  "adr_2025":      138.2,
  "adr_2026":      142.5,
  "adr_growth":    3.1,
  "occupancy_2025": 69.8,
  "occupancy_2026": 71.3,
  "occupancy_growth": 2.2,
  "revpar_2025":   96.4,
  "revpar_2026":   101.6,
  "revpar_growth": 5.4
}
```
**Component:** YTD Growth summary table with 3 rows (ADR / Occupancy / RevPAR), columns for 2025, 2026 YTD, and delta (coloured green/red).

---

### `trends.json`
Array of daily rows:
```json
[
  { "date": "2024-01-01", "year": 2024, "adr": 128.4, "occupancy": 65.2, "revpar": 83.7 },
  ...
]
```
**Component:** Three overlapping multi-year line charts (one each for ADR / Occupancy / RevPAR).  
- X-axis = day of year (1–365), so years overlay.  
- Each year = separate coloured line.  
- Apply a 7-day rolling average before rendering (compute in JS with a simple sliding window).

---

### `otb_trends.json`
Array of forward-looking rows:
```json
[
  { "days_ahead": 0, "year": "TY", "adr": 145.0, "occupancy": 72.1, "revpar": 104.6 },
  { "days_ahead": 0, "year": "LY", "adr": 139.5, "occupancy": 69.4, "revpar":  96.8 },
  ...
]
```
**Component:** OTB line charts (ADR / Occupancy / RevPAR), This Year vs Last Year.  
X-axis = days ahead (0–274, ~9 months). Two lines per chart.

---

### `otb_growth.json`
```json
{
  "adr_ty": 145.0, "adr_ly": 139.5, "adr_growth": 3.9,
  "occupancy_ty": 72.1, "occupancy_ly": 69.4, "occupancy_growth": 3.9,
  "revpar_ty": 104.6, "revpar_ly": 96.8, "revpar_growth": 8.1
}
```
**Component:** 3 OTB growth tiles (same style as KPI tiles) showing TY value and YoY %.

---

### `regional_annual.json`
Array of region rows with annual averages:
```json
[
  { "region": "Global", "year": 2024, "adr": 132.1, "occupancy": 68.4, "revpar": 90.4, "property_count": 3200 },
  { "region": "Europe", "year": 2024, "adr": 138.5, "occupancy": 71.2, "revpar": 98.6, "property_count": 1840 },
  ...
]
```
**Component:** Table grouped by region, columns for 2024 / 2025 / 2026 YTD, with YoY delta columns. Rows with `property_count < 5` should be suppressed.

---

### `regional_monthly.json`
Array of monthly region rows:
```json
[
  { "region": "Europe", "month": "2024-01", "adr": 135.2, "occupancy": 68.0, "revpar": 91.9 },
  ...
]
```
**Component:** Line charts by region (one line per region), one chart each for ADR / Occupancy / RevPAR.

---

### `country_annual.json` / `country_monthly.json`
Same structure as regional equivalents, but with a `"country"` field instead of `"region"`.

**Component:** Collapsible section below the regional charts. Show as a table (annual) and line chart (monthly).

---

### `hotelclass_annual.json`
```json
[
  { "hotel_class": "Luxury",   "year": 2024, "adr": 210.4, "occupancy": 74.1, "revpar": 155.9 },
  { "hotel_class": "Upscale",  "year": 2024, "adr": 158.2, "occupancy": 72.3, "revpar": 114.4 },
  { "hotel_class": "Midscale", "year": 2024, "adr": 118.6, "occupancy": 69.8, "revpar":  82.8 },
  { "hotel_class": "Economy",  "year": 2024, "adr":  88.1, "occupancy": 66.2, "revpar":  58.3 }
]
```
**Component:** Table with 4 rows (one per class), grouped bar chart comparing ADR/RevPAR across classes.

---

### `hotelclass_monthly.json`
Same as `regional_monthly.json` but with `"hotel_class"` field. Same chart treatment.

---

### `lead_time.json`
```json
[
  { "lead_time_bucket": "Same day",  "pct": 18.2 },
  { "lead_time_bucket": "1–3 days",  "pct": 12.4 },
  { "lead_time_bucket": "4–7 days",  "pct": 11.8 },
  { "lead_time_bucket": "8–14 days", "pct": 10.6 },
  { "lead_time_bucket": "15–30 days","pct": 14.2 },
  { "lead_time_bucket": "31–60 days","pct": 13.9 },
  { "lead_time_bucket": "61–90 days","pct":  8.7 },
  { "lead_time_bucket": "90+ days",  "pct": 10.2 }
]
```
**Component:** Horizontal bar chart, sorted by bucket order above.

---

### `length_of_stay.json`
```json
[
  { "los_bucket": "1 night",   "pct": 28.4 },
  { "los_bucket": "2 nights",  "pct": 22.1 },
  { "los_bucket": "3 nights",  "pct": 14.8 },
  { "los_bucket": "4–7 nights","pct": 22.3 },
  { "los_bucket": "8–14 nights","pct": 8.6 },
  { "los_bucket": "15+ nights","pct": 3.8 }
]
```
**Component:** Horizontal bar chart.

---

### `group_size.json`
```json
[
  { "group_size_bucket": "1",    "pct": 38.2 },
  { "group_size_bucket": "2",    "pct": 35.4 },
  { "group_size_bucket": "3–4",  "pct": 16.8 },
  { "group_size_bucket": "5–9",  "pct":  7.2 },
  { "group_size_bucket": "10+",  "pct":  2.4 }
]
```
**Component:** Horizontal bar chart.

---

### `channel.json`
```json
[
  { "channel": "Direct",           "reservations": 1820400 },
  { "channel": "OTA",              "reservations": 1640200 },
  { "channel": "GDS",              "reservations":  124800 },
  { "channel": "Corporate Direct", "reservations":  280600 }
]
```
**Component:** Pie chart + table with % share column.

---

### `payment_type.json`
```json
[
  { "category": "Card",            "transactions": 3840200 },
  { "category": "Cash",            "transactions":  248400 },
  { "category": "Invoice",         "transactions":  182600 }
]
```
**Component:** Pie chart.

---

### `card_network.json`
```json
[
  { "card_network": "Visa",       "transactions": 2140200 },
  { "card_network": "Mastercard", "transactions": 1480400 },
  { "card_network": "Amex",       "transactions":  219600 }
]
```
**Component:** Pie chart.

---

### `cancellation_stats.json`
```json
[
  { "channel": "All channels",  "cancellation_rate": 18.4, "avg_cancel_window_days": 12.6 },
  { "channel": "OTA",           "cancellation_rate": 24.8, "avg_cancel_window_days":  9.2 },
  { "channel": "Direct",        "cancellation_rate": 12.1, "avg_cancel_window_days": 16.4 }
]
```
**Component:** Table with cancellation rate (%) and avg cancel window (days).

---

### `channel_adr.json`
```json
[
  { "channel_type": "Direct",      "year": 2024, "adr": 148.2 },
  { "channel_type": "Third-Party", "year": 2024, "adr": 136.8 }
]
```
**Component:** Grouped bar chart comparing Direct vs Third-Party ADR by year.

---

### `channel_behaviour.json`
```json
[
  { "channel_type": "Direct",      "avg_los": 2.8, "avg_lead_time": 22.4, "avg_group_size": 1.9 },
  { "channel_type": "Third-Party", "avg_los": 2.4, "avg_lead_time": 14.8, "avg_group_size": 1.7 }
]
```
**Component:** Three side-by-side stat cards comparing Direct vs Third-Party.

---

### `cancellation_by_channel.json`
Same structure as `cancellation_stats.json` but channel-level only.  
**Component:** Two-column table.

---

### `pnl_monthly.json`
```json
[
  { "month": "2024-01", "department": "Accommodation", "revenue_eur": 42800000 },
  { "month": "2024-01", "department": "F&B",           "revenue_eur":  8240000 },
  { "month": "2024-01", "department": "Other",         "revenue_eur":  2180000 }
]
```
**Component:** Stacked bar chart (% of total), one bar per month, stacked by department.

---

### `pnl_mix.json`
```json
[
  { "department": "Accommodation", "revenue_eur": 512000000 },
  { "department": "F&B",           "revenue_eur":  98800000 },
  { "department": "Other",         "revenue_eur":  26200000 }
]
```
**Component:** Pie chart.

---

### `revenue_per_sqm.json`
```json
[
  { "department": "Accommodation", "revenue_per_sqm": 4820 },
  { "department": "F&B",           "revenue_per_sqm":  940 }
]
```
**Component:** Horizontal bar chart, values in EUR/m².

---

### `checkin_prestay.json`
```json
[
  { "month": "2024-01", "oci_rate": 42.8 }
]
```
**Component:** Line chart of OCI (online check-in) rate % over time.

---

### `checkin_athotel.json`
```json
[
  { "method": "Front Desk",   "pct": 58.2 },
  { "method": "Kiosk",        "pct": 24.6 },
  { "method": "Digital Key",  "pct": 17.2 }
]
```
**Component:** Pie or donut chart.

---

### `checkin_dow.json` / `checkout_dow.json`
```json
[
  { "day_of_week": 0, "day_name": "Monday",    "count": 284200 },
  { "day_of_week": 1, "day_name": "Tuesday",   "count": 210400 },
  ...
]
```
**Component:** Bar chart, days Mon–Sun on X-axis.

---

### `upsell_by_channel.json`
```json
[
  { "channel": "Pre-Stay Email", "revenue_eur": 8240000, "pct": 38.2 },
  { "channel": "Web",            "revenue_eur": 6180000, "pct": 28.6 },
  { "channel": "At-Hotel",       "revenue_eur": 7140000, "pct": 33.2 }
]
```
**Component:** Horizontal bar chart by channel.

---

### `upsell_by_category.json`
```json
[
  { "category": "Early Check-In", "revenue_eur": 4820000 },
  { "category": "Late Check-Out", "revenue_eur": 3640000 },
  { "category": "Room Upgrade",   "revenue_eur": 6280000 }
]
```
**Component:** Horizontal bar chart by category.

---

### `upsell_avg_value_by_channel.json`
```json
[
  { "channel": "Pre-Stay Email", "avg_value_eur": 28.40 },
  { "channel": "Web",            "avg_value_eur": 24.80 },
  { "channel": "At-Hotel",       "avg_value_eur": 32.60 }
]
```
**Component:** Bar chart.

---

## Navigation / Tabs

Organise the dashboard into these tabs (match the internal dashboard):

| Tab | Content |
|-----|---------|
| Market KPIs | KPI tiles, YTD growth table, historical trends, OTB trends + growth tiles |
| Regional Overview | Regional annual table, regional monthly charts, country annual table, country monthly charts |
| Hotel Class | Hotel class annual table + grouped bar chart, hotel class monthly charts |
| Booking Behaviour | Lead time, LOS, group size, channel mix, payment type, card network, cancellation stats |
| Direct vs OTAs | Channel ADR, channel behaviour stats, cancellation by channel |
| Hotel Performance | P&L stacked bar, revenue mix pie, revenue per m², check-in method, check-in/checkout DOW, upsell charts |

---

## Suppression rule

**Do not render a chart or table row if `property_count < 5`.**  
Show a small grey message: *"Not enough properties to display this segment."*

---

## Data freshness banner

At the top of every page show:  
> *"Data covers {start_date} – {end_date} across {property_count} properties.  
> Last updated: {exported_at}."*

Read all three values from `meta.json`.

---

## Notes

- All monetary values are in **EUR** unless otherwise labelled.
- Percentages are already pre-computed in the JSON (do not divide by 100 again).
- `null` values in numeric fields mean the data was suppressed (< 5 properties) — treat the same as the suppression rule above.
- Date fields are ISO strings (`"YYYY-MM-DD"` or `"YYYY-MM"`). Parse with `new Date()` or a date library.
