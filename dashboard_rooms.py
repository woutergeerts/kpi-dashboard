import io
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date
from queries_rooms import (
    get_regions, get_countries, get_segments,
    load_kpis, load_ytd_growth, load_otb_growth,
    load_trends, load_otb_trends,
    load_pnl_monthly, load_pnl_mix, PNL_ORDER,
    load_revenue_per_sqm,
    load_lead_time, load_length_of_stay, load_group_size,
    load_channel, load_payment_type, load_card_network,
    load_upsell_by_channel, load_upsell_by_category, load_upsell_avg_value_by_channel,
    load_checkin_prestay, load_checkin_athotel,
    load_checkin_dow, load_checkout_dow,
    load_cancellation_stats, load_cancellation_by_channel,
    load_channel_behaviour, load_channel_adr, load_behaviour_annual,
    load_regional_annual, load_regional_monthly,
    load_country_annual, load_country_monthly,
    load_hotelclass_annual, load_hotelclass_monthly,
    count_properties, MIN_PROPERTIES,
    HOTEL_CLASS_ORDER, REGION_ORDER,
)

st.set_page_config(page_title="Hotel Performance Report", page_icon="🏨", layout="wide")

PINK       = "#E87DC2"
ORANGE     = "#FF6B00"
YELLOW     = "#D4E833"
WARM_GREY  = "#E8E6DF"
BLUE       = "#C8E5EE"
MAUVE      = "#F0E0EE"
RICH_BLACK = "#262626"
PALETTE    = [PINK, ORANGE, YELLOW, BLUE, MAUVE, WARM_GREY]
GLOBAL_COLOR = RICH_BLACK

TOO_FEW_MSG = f"⚠️ Fewer than {MIN_PROPERTIES} properties match these filters. Data suppressed to protect confidentiality."

st.title("🏨 Hotel Performance Report")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")

    regions   = get_regions()
    countries = get_countries()
    segments  = get_segments()

    selected_region  = st.multiselect("Region",   options=regions,   default=[])
    selected_country = st.multiselect("Country",  options=countries, default=[])
    selected_segment = st.multiselect("Segment",  options=segments,  default=[])

    st.divider()
    st.markdown("**Date Range**")
    col1, col2 = st.columns(2)
    start_date = col1.date_input("Start date", value=pd.Timestamp("2024-01-01"))
    end_date   = col2.date_input("End date",   value=pd.Timestamp.today().normalize())
    st.divider()
    st.caption("Data is cached for 1 hour.")

filters = {
    "region":   selected_region,
    "country":  selected_country,
    "segment":  selected_segment,
    "start":    str(start_date),
    "end":      str(end_date),
}

ANALYST_TEXT  = """Write your commentary here."""
ANALYST_NAME  = "Your Name Here"
ANALYST_TITLE = "Your Title Here"
ANALYST_PHOTO = "analyst_photo.jpg"

# ── Helper: minimum property check ───────────────────────────────────────────
def _too_few(n: int) -> bool:
    return n < MIN_PROPERTIES

# ── Helper: Excel download button ────────────────────────────────────────────
def excel_download_btn(df: pd.DataFrame, filename: str,
                       label: str = "⬇️ Download data (.xlsx)"):
    df = df.copy()
    for col in df.select_dtypes(include=["datetimetz"]).columns:
        df[col] = df[col].dt.tz_localize(None)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    st.download_button(label=label, data=buf.getvalue(), file_name=filename,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=False)

# ── Helper: annual metric tiles ───────────────────────────────────────────────
def render_annual_tiles(df_ann: pd.DataFrame, dim_col: str, selected_items: list,
                        global_label: str = "🌍 **Global**", item_icon: str = "📍"):
    if df_ann.empty:
        st.info("No annual data available.")
        return
    show_items = ["Global"] + selected_items
    for metric, label, fmt in [
        ("occupancy", "Occupancy (%)",  lambda v: f"{v:.1f}%"),
        ("adr",       "Avg ADR (€)",    lambda v: f"€{v:,.2f}"),
        ("revpar",    "Avg RevPAR (€)", lambda v: f"€{v:,.2f}"),
    ]:
        st.markdown(f"**{label}**")
        hcols = st.columns([2, 1, 1, 1])
        hcols[0].markdown("**Dimension**")
        hcols[1].markdown("**2024**")
        hcols[2].markdown("**2025**")
        hcols[3].markdown("**2026 (YTD)**")
        for item in show_items:
            row_df = df_ann[df_ann[dim_col] == item]
            cols = st.columns([2, 1, 1, 1])
            cols[0].markdown(global_label if item == "Global" else f"{item_icon} {item}")
            for ci, yr in enumerate([2024, 2025, 2026], 1):
                yr_row = row_df[row_df["year"] == yr]
                if yr_row.empty or pd.isna(yr_row[metric].iloc[0]):
                    cols[ci].metric(str(yr), "—")
                else:
                    val = float(yr_row[metric].iloc[0])
                    prev = row_df[row_df["year"] == yr - 1]
                    if not prev.empty and not pd.isna(prev[metric].iloc[0]):
                        pv = float(prev[metric].iloc[0])
                        delta = (f"{val-pv:+.1f}pp vs {yr-1}"
                                 if metric == "occupancy"
                                 else f"{(val-pv)/pv*100:+.1f}% vs {yr-1}")
                    else:
                        delta = None
                    cols[ci].metric(str(yr), fmt(val), delta)
        st.divider()

# ── Helper: monthly line charts ───────────────────────────────────────────────
def render_monthly_lines(df_mon: pd.DataFrame, dim_col: str, selected_items: list,
                         color_map: dict):
    if df_mon.empty:
        st.info("No monthly trend data for selected filters.")
        return
    show_items = ["Global"] + selected_items
    df_plot = df_mon[df_mon[dim_col].isin(show_items)].copy()
    df_plot["month_label"] = df_plot["month"].dt.strftime("%b %Y")
    tick_months = (df_plot[df_plot[dim_col] == "Global"]
                   .sort_values("month")[["month", "month_label"]].drop_duplicates())
    col_r1, col_r2, col_r3 = st.columns(3)
    for col, metric, label in [
        (col_r1, "occupancy", "Occupancy (%)"),
        (col_r2, "adr",       "ADR (€)"),
        (col_r3, "revpar",    "RevPAR (€)"),
    ]:
        with col:
            fig = px.line(df_plot, x="month", y=metric, color=dim_col,
                          title=label,
                          labels={"month": "", metric: label,
                                  dim_col: dim_col.replace("_", " ").title()},
                          color_discrete_map=color_map)
            fig.update_xaxes(tickvals=tick_months["month"].tolist(),
                             ticktext=tick_months["month_label"].tolist(),
                             tickangle=-45)
            for trace in fig.data:
                if trace.name == "Global":
                    trace.line.width = 3
                    trace.line.dash  = "dot"
            fig.update_layout(legend_title_text="")
            st.plotly_chart(fig, use_container_width=True)
    excel_download_btn(df_plot.drop(columns="month_label", errors="ignore"),
                       f"monthly_{dim_col}.xlsx")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "💡 Analyst Insights",
    "📊 Market KPIs",
    "🗺️ Regional Overview",
    "🏷️ Hotel Class",
    "🔍 Booking Behaviour",
    "📊 Direct vs OTAs",
    "🏨 Hotel Performance",
    "📥 Export",
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Analyst Insights
# ═══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Analyst Insight")
    with st.container(border=True):
        col_text, col_photo = st.columns([3, 1])
        with col_text:
            st.markdown(ANALYST_TEXT)
            st.markdown(f"**{ANALYST_NAME}**  \n*{ANALYST_TITLE}*")
        with col_photo:
            if ANALYST_PHOTO:
                try:
                    st.image(ANALYST_PHOTO, width=120)
                except Exception:
                    st.caption("📷 Photo not found.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Market KPIs
# ═══════════════════════════════════════════════════════════════════════════════
with tab2:
    with st.spinner("Checking filters…"):
        n_props = count_properties(filters)

    if _too_few(n_props):
        st.warning(TOO_FEW_MSG)
    else:
        st.subheader("Key Metrics")
        with st.spinner("Loading KPIs…"):
            kpis = load_kpis(filters)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Enterprises",        f"{kpis.get('enterprises', 0):,}")
        c2.metric("ADR (€)",            f"€{kpis.get('adr', 0):,.2f}")
        c3.metric("Occupancy",          f"{kpis.get('occupancy', 0):.1f}%")
        c4.metric("RevPAR (€)",         f"€{kpis.get('revpar', 0):,.2f}")
        c5.metric("Total Reservations", f"{kpis.get('reservations', 0):,}")

        st.markdown(f"**YTD Growth — 2026 vs 2025 (Jan 1 – {date.today().strftime('%b %d')})**")
        with st.spinner("Loading YTD growth…"):
            ytd = load_ytd_growth(
                tuple(selected_region), tuple(selected_country), tuple(selected_segment))
        if ytd.get("too_few"):
            st.info(TOO_FEW_MSG)
        elif ytd:
            g1, g2, g3 = st.columns(3)
            g1.metric("Occupancy 2026 YTD", f"{ytd['occ_2026']:.1f}%",
                      f"{ytd['occ_chg']:+.1f}% vs 2025 ({ytd['occ_2025']:.1f}%)")
            g2.metric("ADR 2026 YTD", f"€{ytd['adr_2026']:,.2f}",
                      f"{ytd['adr_chg']:+.1f}% vs 2025 (€{ytd['adr_2025']:,.2f})")
            g3.metric("RevPAR 2026 YTD", f"€{ytd['revpar_2026']:,.2f}",
                      f"{ytd['revpar_chg']:+.1f}% vs 2025 (€{ytd['revpar_2025']:,.2f})")
        else:
            st.info("YTD growth data not available.")

        st.divider()
        st.subheader("Historical Performance (7-day rolling average)")
        with st.spinner("Loading trends…"):
            df_trends = load_trends(filters)
        if not df_trends.empty:
            tick_df = df_trends.drop_duplicates("month_label").sort_values("day_of_year")
            years = sorted(df_trends["year"].unique())
            year_colors = dict(zip(years, PALETTE))
            col_t1, col_t2, col_t3 = st.columns(3)
            for col, metric, label in [
                (col_t1, "occupancy", "Occupancy (%)"),
                (col_t2, "adr",       "ADR (€)"),
                (col_t3, "revpar",    "RevPAR (€)"),
            ]:
                with col:
                    fig = px.line(df_trends, x="day_of_year", y=metric, color="year",
                                  title=label,
                                  labels={"day_of_year": "", metric: label, "year": "Year"},
                                  color_discrete_map=year_colors)
                    fig.update_xaxes(tickvals=tick_df["day_of_year"].tolist(),
                                     ticktext=tick_df["month_label"].tolist())
                    st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(
                df_trends[["date", "year", "occupancy", "adr", "revpar"]],
                "historical_trends.xlsx")
        else:
            st.info("No trend data for selected filters.")

        st.divider()
        st.subheader("On The Books — Next 9 Months vs Last Year")
        with st.spinner("Loading OTB data…"):
            df_otb = load_otb_trends(filters)
        if not df_otb.empty:
            otb_color_map = {"This Year (OTB)": PINK, "Last Year (OTB)": WARM_GREY}
            tick_df_otb = (df_otb[df_otb["year_label"] == "This Year (OTB)"]
                           .drop_duplicates("display_date").copy())
            tick_df_otb["month"] = tick_df_otb["display_date"].str[:3]
            tick_df_otb = tick_df_otb.drop_duplicates("month")
            col_o1, col_o2, col_o3 = st.columns(3)
            for col, metric, label in [
                (col_o1, "occupancy", "Occupancy (%)"),
                (col_o2, "adr",       "ADR (€)"),
                (col_o3, "revpar",    "RevPAR (€)"),
            ]:
                with col:
                    fig = px.line(df_otb, x="days_ahead", y=metric, color="year_label",
                                  title=f"{label} — On The Books",
                                  labels={"days_ahead": "", metric: label, "year_label": ""},
                                  color_discrete_map=otb_color_map)
                    fig.update_xaxes(tickvals=tick_df_otb["days_ahead"].tolist(),
                                     ticktext=tick_df_otb["display_date"].tolist())
                    st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(
                df_otb[["days_ahead","display_date","year_label","occupancy","adr","revpar"]],
                "otb_trends.xlsx")
        else:
            st.info("No on-the-books data available.")

        with st.spinner("Loading OTB growth…"):
            otb_g = load_otb_growth(
                tuple(selected_region), tuple(selected_country), tuple(selected_segment))
        if otb_g.get("too_few"):
            st.info(TOO_FEW_MSG)
        elif otb_g:
            snap_label = otb_g.get("snap_date", "latest snapshot")
            st.markdown(f"**OTB Growth — 2026 vs 2025 (next 9 months from {snap_label})**")
            o1, o2, o3 = st.columns(3)
            o1.metric("OTB Occupancy 2026", f"{otb_g['occ_ty']:.1f}%",
                      f"{otb_g['occ_chg']:+.1f}% vs 2025 ({otb_g['occ_ly']:.1f}%)")
            o2.metric("OTB ADR 2026", f"€{otb_g['adr_ty']:,.2f}",
                      f"{otb_g['adr_chg']:+.1f}% vs 2025 (€{otb_g['adr_ly']:,.2f})")
            o3.metric("OTB RevPAR 2026", f"€{otb_g['revpar_ty']:,.2f}",
                      f"{otb_g['revpar_chg']:+.1f}% vs 2025 (€{otb_g['revpar_ly']:,.2f})")
        else:
            st.info("OTB growth data not available.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Regional Overview
# ═══════════════════════════════════════════════════════════════════════════════
with tab3:
    show_regions   = len(selected_region) > 0
    show_countries = len(selected_country) > 0

    if show_regions or not show_countries:
        with st.spinner("Loading regional data…"):
            df_reg_ann = load_regional_annual(
                tuple(selected_segment), tuple(selected_region), tuple(selected_country))
            df_reg_mon = load_regional_monthly(
                tuple(selected_segment), str(start_date), str(end_date),
                tuple(selected_region), tuple(selected_country))

        region_color_map = {r: PALETTE[i % len(PALETTE)] for i, r in enumerate(selected_region)}
        region_color_map["Global"] = GLOBAL_COLOR

        st.subheader("Annual Averages by Region")
        st.caption("Full-year averages for 2024–2026 (2026 up to today). Independent of date filter.")
        render_annual_tiles(df_reg_ann, "region", selected_region,
                            global_label="🌍 **Global**", item_icon="🗺️")

        st.subheader("Monthly Trends by Region")
        st.caption("Select regions in the sidebar to compare against the global average.")
        render_monthly_lines(df_reg_mon, "region", selected_region, region_color_map)

    if show_countries:
        if show_regions:
            st.divider()

        with st.spinner("Loading country data…"):
            df_ctry_ann = load_country_annual(
                tuple(selected_segment), tuple(selected_country))
            df_ctry_mon = load_country_monthly(
                tuple(selected_segment), str(start_date), str(end_date),
                tuple(selected_country))

        country_color_map = {c: PALETTE[i % len(PALETTE)] for i, c in enumerate(selected_country)}
        country_color_map["Global"] = GLOBAL_COLOR

        st.subheader("Annual Averages by Country")
        st.caption("Full-year averages for 2024–2026 (2026 up to today). Independent of date filter.")
        render_annual_tiles(df_ctry_ann, "country_name", selected_country,
                            global_label="🌍 **Global**", item_icon="🏳️")

        st.subheader("Monthly Trends by Country")
        st.caption("Select countries in the sidebar to compare against the global average.")
        render_monthly_lines(df_ctry_mon, "country_name", selected_country, country_color_map)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Hotel Class
# ═══════════════════════════════════════════════════════════════════════════════
with tab4:
    with st.spinner("Loading hotel class data…"):
        df_hc_ann = load_hotelclass_annual(
            tuple(selected_segment), tuple(selected_region), tuple(selected_country))
        df_hc_mon = load_hotelclass_monthly(
            tuple(selected_segment), str(start_date), str(end_date),
            tuple(selected_region), tuple(selected_country))

    available_classes = [c for c in HOTEL_CLASS_ORDER
                         if c in df_hc_ann["hotel_class"].unique()]
    selected_classes  = st.multiselect("Hotel Class", options=available_classes,
                                       default=available_classes, key="hc_filter")

    hc_color_map = {c: PALETTE[i % len(PALETTE)] for i, c in enumerate(available_classes)}
    hc_color_map["Global"] = GLOBAL_COLOR

    st.subheader("Annual Averages by Hotel Class")
    st.caption("Full-year averages for 2024–2026. Independent of date filter.")
    render_annual_tiles(df_hc_ann, "hotel_class", selected_classes,
                        global_label="🌍 **Global**", item_icon="🏷️")

    st.subheader("Monthly Trends by Hotel Class")
    render_monthly_lines(df_hc_mon, "hotel_class", selected_classes, hc_color_map)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — Booking Behaviour
# ═══════════════════════════════════════════════════════════════════════════════
with tab5:
    with st.spinner("Loading annual averages…"):
        beh = load_behaviour_annual(
            tuple(selected_region), tuple(selected_country), tuple(selected_segment))
    avgs_df      = beh.get("averages", pd.DataFrame())
    channel_pcts = beh.get("channel_pcts", {})

    def annual_behaviour_tiles(metric_key: str, label: str, fmt):
        if avgs_df.empty:
            return
        cols = st.columns(3)
        for ci, yr in enumerate([2024, 2025, 2026]):
            yr_row = avgs_df[avgs_df["year"] == yr]
            if yr_row.empty or pd.isna(yr_row[metric_key].iloc[0]):
                cols[ci].metric(f"{yr}", "—")
            else:
                val = float(yr_row[metric_key].iloc[0])
                prev = avgs_df[avgs_df["year"] == yr - 1]
                if not prev.empty and not pd.isna(prev[metric_key].iloc[0]):
                    pv = float(prev[metric_key].iloc[0])
                    delta = f"{val-pv:+.2f} vs {yr-1}"
                else:
                    delta = None
                cols[ci].metric(f"{yr}", fmt(val), delta)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Reservations by Length of Stay")
        st.caption("**Annual avg LOS (nights)**")
        annual_behaviour_tiles("avg_los", "Avg LOS", lambda v: f"{v:.1f} nights")
        with st.spinner("Loading…"):
            df_los = load_length_of_stay(filters)
        if not df_los.empty:
            df_los["pct"] = df_los["reservations"] / df_los["reservations"].sum() * 100
            fig = px.bar(df_los, x="los_bucket", y="pct",
                         labels={"los_bucket":"Nights","pct":"% of Reservations"},
                         color_discrete_sequence=[ORANGE],
                         text=df_los["pct"].apply(lambda x: f"{x:.1f}%"))
            fig.update_traces(textposition="outside")
            fig.update_xaxes(categoryorder="array",
                             categoryarray=["1 night","2 nights","3 nights",
                                            "4-7 nights","8-14 nights","15+ nights"])
            fig.update_yaxes(ticksuffix="%")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_los, "length_of_stay.xlsx")
        else:
            st.info("No data.")

    with col_b:
        st.subheader("Reservations by Group Size")
        st.caption("**Annual avg group size (guests)**")
        annual_behaviour_tiles("avg_group_size", "Avg Group Size", lambda v: f"{v:.1f} guests")
        with st.spinner("Loading…"):
            df_gs = load_group_size(filters)
        if not df_gs.empty:
            df_gs["pct"] = df_gs["reservations"] / df_gs["reservations"].sum() * 100
            fig = px.bar(df_gs, x="group_size_bucket", y="pct",
                         labels={"group_size_bucket":"Guests per reservation",
                                 "pct":"% of Reservations"},
                         color_discrete_sequence=[YELLOW],
                         text=df_gs["pct"].apply(lambda x: f"{x:.1f}%"))
            fig.update_traces(textposition="outside")
            fig.update_yaxes(ticksuffix="%")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_gs, "group_size.xlsx")
        else:
            st.info("No data.")

    st.divider()
    col_c, col_d = st.columns(2)
    with col_c:
        st.subheader("Reservations by Lead Time")
        st.caption("**Annual avg lead time (days)**")
        annual_behaviour_tiles("avg_lead_time", "Avg Lead Time", lambda v: f"{v:.0f} days")
        with st.spinner("Loading…"):
            df_lt = load_lead_time(filters)
        if not df_lt.empty:
            df_lt["pct"] = df_lt["reservations"] / df_lt["reservations"].sum() * 100
            fig = px.bar(df_lt, x="lead_time_bucket", y="pct",
                         labels={"lead_time_bucket":"Days before check-in",
                                 "pct":"% of Reservations"},
                         color_discrete_sequence=[PINK],
                         text=df_lt["pct"].apply(lambda x: f"{x:.1f}%"))
            fig.update_traces(textposition="outside")
            fig.update_xaxes(categoryorder="array",
                             categoryarray=["0 - Same day","1-3 days","4-7 days","8-14 days",
                                            "15-30 days","31-60 days","61-90 days","90+ days"])
            fig.update_yaxes(ticksuffix="%")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_lt, "lead_time.xlsx")
        else:
            st.info("No data.")

    with col_d:
        st.subheader("Reservations by Channel")
        if channel_pcts:
            st.caption("**Annual channel split (%)**")
            ch_labels = ["Third-Party","Online Direct","Offline Direct"]
            header = st.columns([2, 1, 1, 1])
            header[0].markdown("**Channel**")
            for ci, yr in enumerate([2024, 2025, 2026], 1):
                header[ci].markdown(f"**{yr}**")
            for ch in ch_labels:
                row_cols = st.columns([2, 1, 1, 1])
                row_cols[0].markdown(ch)
                for ci, yr in enumerate([2024, 2025, 2026], 1):
                    val = channel_pcts.get(yr, {}).get(ch)
                    row_cols[ci].metric("", f"{val:.1f}%" if val is not None else "—")
        with st.spinner("Loading…"):
            df_ch = load_channel(filters)
        if not df_ch.empty:
            fig = px.pie(df_ch, names="channel", values="reservations",
                         color_discrete_sequence=PALETTE)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_ch, "channel.xlsx")
        else:
            st.info("No data.")

    st.divider()
    col_e, col_f = st.columns(2)
    with col_e:
        st.subheader("Payment Type Breakdown")
        with st.spinner("Loading…"):
            df_pay = load_payment_type(filters)
        if not df_pay.empty:
            fig = px.pie(df_pay, names="category", values="transactions",
                         color_discrete_sequence=PALETTE)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_pay, "payment_type.xlsx")
        else:
            st.info("No data.")

    with col_f:
        st.subheader("Card Network Breakdown")
        with st.spinner("Loading…"):
            df_card = load_card_network(filters)
        if not df_card.empty:
            card_colors = {"Visa":BLUE,"Mastercard":PINK,"Amex":YELLOW,"Other":WARM_GREY}
            fig = px.pie(df_card, names="card_network", values="transactions",
                         color="card_network", color_discrete_map=card_colors)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_card, "card_network.xlsx")
            st.caption("Visa includes VPay & Carte Bleue. Mastercard includes Maestro, Bancontact & Giro.")
        else:
            st.info("No data.")

    st.divider()
    st.subheader("Cancellation Insights")
    st.caption("Annual figures — full calendar years, independent of date filter.")
    with st.spinner("Loading cancellation data…"):
        df_canc      = load_cancellation_stats(filters)
        df_canc_ch   = load_cancellation_by_channel(filters)

    if not df_canc.empty:
        # ── Annual totals ─────────────────────────────────────────────────────
        st.markdown("**Cancellation Rate (% of total bookings) — All Channels**")
        canc_cols = st.columns(len(df_canc))
        for i, row in df_canc.iterrows():
            yr  = int(row["year"])
            val = float(row["cancel_rate"])
            prev = df_canc[df_canc["year"] == yr - 1]
            delta = None
            if not prev.empty:
                pv = float(prev["cancel_rate"].iloc[0])
                delta = f"{val-pv:+.1f}pp vs {yr-1}"
            canc_cols[i].metric(str(yr), f"{val:.1f}%", delta)

        st.markdown("**Avg Cancellation Window (days before arrival) — All Channels**")
        win_cols = st.columns(len(df_canc))
        for i, row in df_canc.iterrows():
            yr  = int(row["year"])
            val = row["avg_cancel_window"]
            if pd.isna(val):
                win_cols[i].metric(str(yr), "—")
            else:
                val = float(val)
                prev = df_canc[df_canc["year"] == yr - 1]
                delta = None
                if not prev.empty and not pd.isna(prev["avg_cancel_window"].iloc[0]):
                    pv = float(prev["avg_cancel_window"].iloc[0])
                    delta = f"{val-pv:+.1f} days vs {yr-1}"
                win_cols[i].metric(str(yr), f"{val:.0f} days", delta)

        # ── Channel breakdown ─────────────────────────────────────────────────
        if not df_canc_ch.empty:
            st.divider()
            st.markdown("**Cancellation Rate by Channel (%)**")
            channels = ["Third-Party", "Online Direct", "Offline Direct"]
            years    = [2024, 2025, 2026]
            hdr = st.columns([2, 1, 1, 1])
            hdr[0].markdown("**Channel**")
            for ci, yr in enumerate(years, 1):
                hdr[ci].markdown(f"**{yr}**")
            for ch in channels:
                ch_df = df_canc_ch[df_canc_ch["channel"] == ch]
                row_cols = st.columns([2, 1, 1, 1])
                row_cols[0].markdown(ch)
                for ci, yr in enumerate(years, 1):
                    yr_row = ch_df[ch_df["year"] == yr]
                    if yr_row.empty or pd.isna(yr_row["cancel_rate"].iloc[0]):
                        row_cols[ci].metric("", "—")
                    else:
                        val = float(yr_row["cancel_rate"].iloc[0])
                        prev_row = ch_df[ch_df["year"] == yr - 1]
                        delta = None
                        if not prev_row.empty and not pd.isna(prev_row["cancel_rate"].iloc[0]):
                            pv = float(prev_row["cancel_rate"].iloc[0])
                            delta = f"{val-pv:+.1f}pp vs {yr-1}"
                        row_cols[ci].metric("", f"{val:.1f}%", delta)

            st.markdown("**Avg Cancellation Window by Channel (days before arrival)**")
            hdr2 = st.columns([2, 1, 1, 1])
            hdr2[0].markdown("**Channel**")
            for ci, yr in enumerate(years, 1):
                hdr2[ci].markdown(f"**{yr}**")
            for ch in channels:
                ch_df = df_canc_ch[df_canc_ch["channel"] == ch]
                row_cols = st.columns([2, 1, 1, 1])
                row_cols[0].markdown(ch)
                for ci, yr in enumerate(years, 1):
                    yr_row = ch_df[ch_df["year"] == yr]
                    if yr_row.empty or pd.isna(yr_row["avg_cancel_window"].iloc[0]):
                        row_cols[ci].metric("", "—")
                    else:
                        val = float(yr_row["avg_cancel_window"].iloc[0])
                        prev_row = ch_df[ch_df["year"] == yr - 1]
                        delta = None
                        if not prev_row.empty and not pd.isna(prev_row["avg_cancel_window"].iloc[0]):
                            pv = float(prev_row["avg_cancel_window"].iloc[0])
                            delta = f"{val-pv:+.1f} days vs {yr-1}"
                        row_cols[ci].metric("", f"{val:.0f} days", delta)

        excel_download_btn(
            df_canc[["year","total_bookings","cancellations","cancel_rate","avg_cancel_window"]],
            "cancellations.xlsx")
        if not df_canc_ch.empty:
            excel_download_btn(
                df_canc_ch[["year","channel","total_bookings","cancellations",
                            "cancel_rate","avg_cancel_window"]],
                "cancellations_by_channel.xlsx",
                label="⬇️ Download channel breakdown (.xlsx)")
    else:
        st.info("No cancellation data for selected filters." if n_props >= MIN_PROPERTIES
                else TOO_FEW_MSG)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — Direct vs OTAs
# ═══════════════════════════════════════════════════════════════════════════════
with tab6:
    st.subheader("Direct vs OTAs — Booking Channel Breakdown")
    st.caption(
        "Annual figures — full calendar years (2024–2026 YTD), independent of date filter. "
        "Third-Party = Channel Manager & Connector. "
        "Online Direct = Booking engine (Distributor, Navigator, Commander/Website). "
        "Offline Direct = Phone, email, in-person, and other Commander origins."
    )

    with st.spinner("Loading channel data…"):
        df_ch_beh  = load_channel_behaviour(filters)
        df_ch_canc = load_cancellation_by_channel(filters)
        df_ch_adr  = load_channel_adr(filters)

    CHANNELS      = ["Third-Party", "Direct"]
    CHANNEL_ICONS = {"Third-Party": "🌐", "Direct": "🤝"}
    YEARS         = [2024, 2025, 2026]

    # ── Shared helper: render a channel × year metric grid ───────────────────
    def _channel_grid(df: pd.DataFrame, metric: str, fmt, is_pp: bool = False) -> None:
        if df.empty:
            st.info("No data for selected filters.")
            return
        hdr = st.columns([2, 1, 1, 1])
        hdr[0].markdown("**Channel**")
        for ci, yr in enumerate(YEARS, 1):
            hdr[ci].markdown(f"**{yr}**")
        for ch in CHANNELS:
            ch_df = df[df["channel"] == ch]
            row   = st.columns([2, 1, 1, 1])
            row[0].markdown(f"{CHANNEL_ICONS[ch]} {ch}")
            for ci, yr in enumerate(YEARS, 1):
                yr_row = ch_df[ch_df["year"] == yr]
                if yr_row.empty or pd.isna(yr_row[metric].iloc[0]):
                    row[ci].metric("", "—")
                else:
                    val  = float(yr_row[metric].iloc[0])
                    prev = ch_df[ch_df["year"] == yr - 1]
                    delta = None
                    if not prev.empty and not pd.isna(prev[metric].iloc[0]):
                        pv = float(prev[metric].iloc[0])
                        delta = (f"{val - pv:+.1f}pp vs {yr-1}" if is_pp
                                 else f"{val - pv:+.2f} vs {yr-1}")
                    row[ci].metric("", fmt(val), delta)

    # ── ADR ───────────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("#### Average Daily Rate (€)")
        st.caption("Room revenue per occupied room-night, attributed to the booking channel.")
        _channel_grid(df_ch_adr, "adr_eur", lambda v: f"€{v:,.2f}")
        if not df_ch_adr.empty:
            excel_download_btn(
                df_ch_adr[["year","channel","room_nights","adr_eur"]],
                "channel_adr.xlsx")

    # ── Length of Stay ────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("#### Avg Length of Stay (nights)")
        _channel_grid(df_ch_beh, "avg_los", lambda v: f"{v:.1f} nights")

    # ── Lead Time ─────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("#### Avg Lead Time (days before arrival)")
        _channel_grid(df_ch_beh, "avg_lead_time", lambda v: f"{v:.0f} days")

    # ── Group Size ────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("#### Avg Group Size (guests per reservation)")
        _channel_grid(df_ch_beh, "avg_group_size", lambda v: f"{v:.2f} guests")

    if not df_ch_beh.empty:
        excel_download_btn(
            df_ch_beh[["year","channel","total_reservations",
                        "avg_los","avg_lead_time","avg_group_size"]],
            "channel_behaviour.xlsx")

    # ── Cancellations ─────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("#### Cancellation Rate (%)")
        _channel_grid(df_ch_canc, "cancel_rate",
                      lambda v: f"{v:.1f}%", is_pp=True)

    with st.container(border=True):
        st.markdown("#### Avg Cancellation Window (days before arrival)")
        _channel_grid(df_ch_canc, "avg_cancel_window",
                      lambda v: f"{v:.0f} days")

    if not df_ch_canc.empty:
        excel_download_btn(
            df_ch_canc[["year","channel","total_bookings","cancellations",
                         "cancel_rate","avg_cancel_window"]],
            "channel_cancellations.xlsx")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 7 — Hotel Performance
# ═══════════════════════════════════════════════════════════════════════════════
with tab7:
    st.subheader("Revenue by Department")
    with st.spinner("Loading revenue data…"):
        df_pnl_monthly = load_pnl_monthly(filters)
        df_pnl_mix     = load_pnl_mix(filters)

    if not df_pnl_monthly.empty:
        color_map = dict(zip(PNL_ORDER, PALETTE * 3))
        col_pl1, col_pl2 = st.columns([2, 1])
        with col_pl1:
            st.markdown("**Monthly Revenue by Department (%)**")
            monthly_totals = df_pnl_monthly.groupby("month")["net_revenue_eur"].transform("sum")
            df_pnl_pct = df_pnl_monthly.copy()
            df_pnl_pct["pct"] = df_pnl_pct["net_revenue_eur"] / monthly_totals * 100
            fig = px.bar(df_pnl_pct, x="month", y="pct", color="category",
                         labels={"month":"","pct":"% of Revenue","category":"Department"},
                         color_discrete_map=color_map, category_orders={"category":PNL_ORDER})
            fig.update_layout(barmode="stack", yaxis_ticksuffix="%",
                              legend=dict(orientation="h",yanchor="bottom",y=-0.4,
                                          xanchor="left",x=0))
            fig.update_xaxes(dtick="M1", tickformat="%b %Y")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_pnl_monthly, "revenue_monthly.xlsx")
        with col_pl2:
            st.markdown("**Revenue Mix**")
            df_pie = df_pnl_mix[df_pnl_mix["category"] != "Not Assigned"].copy()
            fig = px.pie(df_pie, names="category", values="net_revenue_eur",
                         color="category", color_discrete_map=color_map)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_pnl_mix, "revenue_mix.xlsx")
            st.caption("ℹ️ 'Not Assigned' excluded from mix chart.")
        with st.expander("View full revenue breakdown"):
            total_all = df_pnl_mix["net_revenue_eur"].sum()
            df_tbl = df_pnl_mix[["category", "net_revenue_eur"]].copy()
            df_tbl["% of Total"] = (df_tbl["net_revenue_eur"] / total_all * 100).apply(
                lambda x: f"{x:.1f}%")
            df_tbl["net_revenue_eur"] = df_tbl["net_revenue_eur"].apply(
                lambda x: f"€{x:,.0f}")
            df_tbl.columns = ["Department","Net Revenue (€)","% of Total"]
            st.dataframe(df_tbl, use_container_width=True, hide_index=True)
    else:
        st.info("No revenue data for selected filters." if n_props >= MIN_PROPERTIES
                else TOO_FEW_MSG)

    st.divider()
    st.subheader("Revenue per m² by Department")
    with st.spinner("Loading sq m data…"):
        df_sqm = load_revenue_per_sqm(filters)
    if not df_sqm.empty:
        col_sqm1, col_sqm2 = st.columns(2)
        with col_sqm1:
            st.markdown("**Avg Revenue per m² (€)**")
            fig = px.bar(df_sqm.sort_values("revenue_per_sqm_eur"),
                         x="revenue_per_sqm_eur", y="category", orientation="h",
                         labels={"category":"","revenue_per_sqm_eur":"€ per m²"},
                         color="category",
                         color_discrete_map=dict(zip(
                             ["Rooms","Food & Beverage","Events & Meetings",
                              "Wellness & Spa","Sport & Recreation"], PALETTE)),
                         text=df_sqm.sort_values("revenue_per_sqm_eur")["revenue_per_sqm_eur"]
                             .apply(lambda x: f"€{x:.2f}"))
            fig.update_traces(textposition="outside")
            fig.update_layout(showlegend=False, yaxis={"categoryorder":"total ascending"})
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_sqm, "revenue_per_sqm.xlsx")
        with col_sqm2:
            st.markdown("**Properties with sq m data**")
            df_sqm_tbl = df_sqm[["category","property_count","revenue_per_sqm_eur"]].copy()
            df_sqm_tbl["revenue_per_sqm_eur"] = df_sqm_tbl["revenue_per_sqm_eur"].apply(
                lambda x: f"€{x:.2f}")
            df_sqm_tbl.columns = ["Department","Properties","€ per m²"]
            st.dataframe(df_sqm_tbl, use_container_width=True, hide_index=True)
            st.caption("ℹ️ Accuracy grade ≥ 3 only.")
    else:
        st.info("No sq m data.")

    st.divider()
    st.subheader("Arrivals & Departures by Day of Week")
    col_dow1, col_dow2 = st.columns(2)
    with col_dow1:
        st.markdown("**Check-in Day**")
        with st.spinner("Loading…"):
            df_ci_dow = load_checkin_dow(filters)
        if not df_ci_dow.empty:
            fig = px.bar(df_ci_dow, x="day_of_week", y="pct",
                         labels={"day_of_week":"","pct":"% of Arrivals"},
                         color_discrete_sequence=[PINK],
                         text=df_ci_dow["pct"].apply(lambda x: f"{x:.1f}%"))
            fig.update_traces(textposition="outside")
            fig.update_yaxes(ticksuffix="%")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_ci_dow, "checkin_dow.xlsx")
        else:
            st.info("No data.")
    with col_dow2:
        st.markdown("**Check-out Day**")
        with st.spinner("Loading…"):
            df_co_dow = load_checkout_dow(filters)
        if not df_co_dow.empty:
            fig = px.bar(df_co_dow, x="day_of_week", y="pct",
                         labels={"day_of_week":"","pct":"% of Departures"},
                         color_discrete_sequence=[BLUE],
                         text=df_co_dow["pct"].apply(lambda x: f"{x:.1f}%"))
            fig.update_traces(textposition="outside")
            fig.update_yaxes(ticksuffix="%")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_co_dow, "checkout_dow.xlsx")
        else:
            st.info("No data.")

    st.divider()
    st.subheader("Check-in Methods")
    col_ci1, col_ci2 = st.columns(2)
    with col_ci1:
        st.markdown("**Pre-Stay: Online Check-in (OCI)**")
        with st.spinner("Loading…"):
            kpis_ci = load_kpis(filters)
            df_pre  = load_checkin_prestay(filters)
        total_res = kpis_ci.get("reservations", 0)
        if not df_pre.empty and total_res > 0:
            oci_count = int(df_pre["reservations"].sum())
            df_oci_pie = pd.DataFrame({
                "status":       ["OCI Yes","OCI No"],
                "reservations": [oci_count, max(total_res - oci_count, 0)],
            })
            fig = px.pie(df_oci_pie, names="status", values="reservations",
                         color="status",
                         color_discrete_map={"OCI Yes":PINK,"OCI No":WARM_GREY})
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_oci_pie, "oci_prestay.xlsx")
        else:
            st.info("No data.")
    with col_ci2:
        st.markdown("**At Hotel: Check-in Method**")
        with st.spinner("Loading…"):
            df_hotel = load_checkin_athotel(filters)
        if not df_hotel.empty:
            fig = px.pie(df_hotel, names="checkin_method", values="reservations",
                         color_discrete_sequence=PALETTE)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_hotel, "checkin_athotel.xlsx")
        else:
            st.info("No data.")

    st.divider()
    st.subheader("Upsell Performance")
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        st.markdown("**Upsells by Channel**")
        with st.spinner("Loading…"):
            df_uch = load_upsell_by_channel(filters)
        if not df_uch.empty:
            fig = px.pie(df_uch, names="channel", values="upsells",
                         color_discrete_sequence=PALETTE)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_uch, "upsell_channel.xlsx")
        else:
            st.info("No data." if n_props >= MIN_PROPERTIES else TOO_FEW_MSG)
    with col_u2:
        st.markdown("**Avg Upsell Value per Reservation by Channel (€)**")
        with st.spinner("Loading…"):
            df_uval = load_upsell_avg_value_by_channel(filters)
        if not df_uval.empty:
            fig = px.bar(df_uval, x="channel", y="avg_value",
                         labels={"channel":"","avg_value":"Avg Value (€)"},
                         color_discrete_sequence=[ORANGE],
                         text=df_uval["avg_value"].apply(lambda x: f"€{x:.2f}"))
            fig.update_traces(textposition="outside")
            st.plotly_chart(fig, use_container_width=True)
            excel_download_btn(df_uval, "upsell_avg_value.xlsx")
        else:
            st.info("No data." if n_props >= MIN_PROPERTIES else TOO_FEW_MSG)

    st.markdown("**Top Upsell Categories**")
    with st.spinner("Loading…"):
        df_ucat = load_upsell_by_category(filters)
    if not df_ucat.empty:
        col_u3, col_u4 = st.columns(2)
        with col_u3:
            df_ucat["pct"] = df_ucat["upsells"] / df_ucat["upsells"].sum() * 100
            fig = px.bar(df_ucat, x="pct", y="category", orientation="h",
                         labels={"category":"","pct":"% of Upsells"},
                         color_discrete_sequence=[BLUE],
                         text=df_ucat["pct"].apply(lambda x: f"{x:.1f}%"))
            fig.update_traces(textposition="outside")
            fig.update_layout(yaxis={"categoryorder":"total ascending"})
            fig.update_xaxes(ticksuffix="%")
            st.plotly_chart(fig, use_container_width=True)
        with col_u4:
            fig = px.bar(df_ucat, x="avg_value_eur", y="category", orientation="h",
                         labels={"category":"","avg_value_eur":"Avg Value per Upsell (€)"},
                         color_discrete_sequence=[MAUVE],
                         text=df_ucat["avg_value_eur"].apply(lambda x: f"€{x:.2f}"))
            fig.update_traces(textposition="outside")
            fig.update_layout(yaxis={"categoryorder":"total ascending"})
            st.plotly_chart(fig, use_container_width=True)
        excel_download_btn(df_ucat, "upsell_categories.xlsx")
    else:
        st.info("No upsell data.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 8 — Export to PowerPoint
# ═══════════════════════════════════════════════════════════════════════════════
with tab8:
    st.subheader("📥 Export to PowerPoint")
    st.caption(
        "Generates a branded Mews deck with all charts and KPI tiles, "
        "using the current sidebar filters."
    )
    with st.container(border=True):
        col_s1, col_s2 = st.columns(2)
        col_s1.markdown(
            f"**Region:** {', '.join(selected_region) or 'Global (all)'}")
        col_s2.markdown(
            f"**Country:** {', '.join(selected_country) or 'All countries'}")
        col_s1.markdown(
            f"**Segment:** {', '.join(selected_segment) or 'All segments'}")
        col_s2.markdown(f"**Date range:** {start_date} → {end_date}")
        st.markdown(
            "**Sections included:** Market KPIs · Regional · "
            "Hotel Class · Booking Behaviour · Hotel Performance")
    st.divider()

    if st.button("🔄 Generate PowerPoint", type="primary", use_container_width=False):
        with st.spinner("Loading data and building slides… this may take 20–40 seconds."):
            from export_pptx import build_pptx

            f = filters
            kpis_ex    = load_kpis(f)
            ytd_ex     = load_ytd_growth(
                tuple(selected_region), tuple(selected_country), tuple(selected_segment))
            otb_g_ex   = load_otb_growth(
                tuple(selected_region), tuple(selected_country), tuple(selected_segment))
            trends_ex  = load_trends(f)
            otb_ex     = load_otb_trends(f)
            reg_ann_ex = load_regional_annual(
                tuple(selected_segment), tuple(selected_region), tuple(selected_country))
            reg_mon_ex = load_regional_monthly(
                tuple(selected_segment), str(start_date), str(end_date),
                tuple(selected_region), tuple(selected_country))
            hc_ann_ex  = load_hotelclass_annual(
                tuple(selected_segment), tuple(selected_region), tuple(selected_country))
            hc_mon_ex  = load_hotelclass_monthly(
                tuple(selected_segment), str(start_date), str(end_date),
                tuple(selected_region), tuple(selected_country))
            avail_classes = [c for c in HOTEL_CLASS_ORDER
                             if c in hc_ann_ex["hotel_class"].unique()]
            beh_ex   = load_behaviour_annual(
                tuple(selected_region), tuple(selected_country), tuple(selected_segment))
            los_ex   = load_length_of_stay(f)
            gs_ex    = load_group_size(f)
            lt_ex    = load_lead_time(f)
            ch_ex    = load_channel(f)
            pay_ex   = load_payment_type(f)
            card_ex  = load_card_network(f)
            canc_ex  = load_cancellation_stats(f)
            pnl_mon_ex = load_pnl_monthly(f)
            pnl_mix_ex = load_pnl_mix(f)
            sqm_ex     = load_revenue_per_sqm(f)
            ci_dow_ex  = load_checkin_dow(f)
            co_dow_ex  = load_checkout_dow(f)
            pre_ex     = load_checkin_prestay(f)
            hotel_ex   = load_checkin_athotel(f)
            uch_ex     = load_upsell_by_channel(f)
            uval_ex    = load_upsell_avg_value_by_channel(f)
            ucat_ex    = load_upsell_by_category(f)

            pptx_bytes = build_pptx(
                filters=f,
                kpis=kpis_ex, ytd=ytd_ex,
                df_trends=trends_ex, df_otb=otb_ex, otb_g=otb_g_ex,
                df_reg_ann=reg_ann_ex, df_reg_mon=reg_mon_ex,
                selected_territory=selected_region,
                df_hc_ann=hc_ann_ex, df_hc_mon=hc_mon_ex,
                selected_classes=avail_classes,
                beh=beh_ex,
                df_los=los_ex, df_gs=gs_ex, df_lt=lt_ex,
                df_ch=ch_ex, df_pay=pay_ex, df_card=card_ex,
                df_canc=canc_ex,
                df_pnl_monthly=pnl_mon_ex, df_pnl_mix=pnl_mix_ex,
                df_sqm=sqm_ex,
                df_ci_dow=ci_dow_ex, df_co_dow=co_dow_ex,
                df_pre=pre_ex, df_hotel=hotel_ex,
                df_uch=uch_ex, df_uval=uval_ex, df_ucat=ucat_ex,
            )

        fname = (
            f"Hotel_Performance_Report_"
            f"{'_'.join(selected_region) or 'Global'}_"
            f"{start_date}_{end_date}.pptx"
        ).replace(" ", "_")
        st.success("✅ Deck ready! Click below to download.")
        st.download_button(
            label="⬇️ Download PowerPoint (.pptx)",
            data=pptx_bytes, file_name=fname,
            mime=("application/vnd.openxmlformats-officedocument"
                  ".presentationml.presentation"),
            use_container_width=False,
        )

# ── Disclaimer ────────────────────────────────────────────────────────────────
st.divider()
st.markdown(
    f"""<div style="font-size:0.75rem; color:#888; padding-top:0.5rem;">
    <strong>Disclaimer:</strong> This report contains proprietary and confidential data owned by
    Mews Systems B.V. Intended solely for internal use. Unauthorised reproduction or disclosure is
    strictly prohibited. Metrics are based on aggregated, anonymised property-level data and do not
    constitute financial advice.<br><br>
   <strong>Data scope:</strong> Active Mews customers (Subscribed) as of today that joined at least
    one day before the selected start date ({str(start_date)}), and have been live on Mews for at least
    90 days prior to the start date. Properties without a go-live date are included. Churned or
    post-start-date enterprises excluded. Data is suppressed where fewer than {MIN_PROPERTIES}
    properties contribute to a metric.<br><br>
    <strong>Methodology:</strong> Occupancy, ADR and RevPAR are room-weighted market aggregates.
    Occupancy = total occupied rooms ÷ total available rooms. ADR = total room revenue ÷ total
    occupied rooms. RevPAR = total room revenue ÷ total available rooms. Each individual room
    counts equally regardless of property size. Days on which a property has available rooms
    but zero occupied rooms are excluded from all three metrics, to avoid seasonal markets
    (e.g. Greece, Spain) being distorted by closed hotels that have not blocked their inventory
    in Mews during the off-season.<br><br>
    <strong>Filters applied:</strong>
    Region: {', '.join(selected_region) or 'All'} |
    Country: {', '.join(selected_country) or 'All'} |
    Segment: {', '.join(selected_segment) or 'All'}<br><br>
    <strong>Last updated:</strong> {date.today().strftime("%B %d, %Y")}
    </div>""",
    unsafe_allow_html=True,
)