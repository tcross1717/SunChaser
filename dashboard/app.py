import os
import sys
import requests
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import func
from sqlalchemy.orm import joinedload
from db.database import get_session, init_db
from db.models import (
    FlightPrice, AwardPrice, Route, Destination,
    LoyaltyProgram, UserPoints, HotelPrice, DepartureAirport,
)
from analytics import price_percentile, route_average
from optimizer import optimize_transfers
from alerts.digest import check_flexible_destination_alerts

API_BASE = os.getenv("SUNCHASER_API", "http://localhost:8000/api")

# ── Airline → terminal lookup for JFK / EWR / LGA ────────────────────────────
AIRLINE_TERMINALS: dict[str, dict[str, str]] = {
    "JFK": {
        # Terminal 1
        "Air France": "1", "Korean Air": "1", "Japan Airlines": "1",
        "Lufthansa": "1", "Swiss International Air Lines": "1",
        "Austrian Airlines": "1", "Finnair": "1", "El Al": "1",
        "TAP Air Portugal": "1", "Aer Lingus": "1", "Singapore Airlines": "1",
        "Brussels Airlines": "1", "LOT Polish Airlines": "1",
        # Terminal 4
        "Delta": "4", "Delta Air Lines": "4", "WestJet": "4",
        "Azul": "4", "LATAM": "4", "Avianca": "4", "Copa Airlines": "4",
        "Emirates": "4", "Air Serbia": "4", "Norwegian": "4",
        "Icelandair": "4", "Volaris": "4", "VivaAerobus": "4", "Caribbean Airlines": "4",
        "Aeromexico": "4", "GOL": "4", "Spirit": "4", "Frontier": "4",
        "Air Europa": "4", "IndiGo": "4",
        # Terminal 5
        "JetBlue": "5",
        # Terminal 7
        "British Airways": "7", "Iberia": "7", "Vueling": "7",
        # Terminal 8
        "American Airlines": "8", "Qatar Airways": "8",
        "Cathay Pacific": "8", "Royal Jordanian": "8",
        "Finnair": "8", "Alaska Airlines": "8",
    },
    "EWR": {
        # Terminal A — low-cost / regional / international charters
        "Spirit": "A", "Frontier": "A", "Allegiant": "A",
        "Sun Country": "A", "Avelo": "A", "Volaris": "A",
        "VivaAerobus": "A", "Interjet": "A",
        # Terminal B — some domestic/international
        "American Airlines": "B", "Delta": "B", "Southwest": "B",
        "Air Canada": "B", "British Airways": "B", "Lufthansa": "B",
        "Virgin Atlantic": "B", "Icelandair": "B", "Norse Atlantic": "B",
        "JetBlue": "B", "Alaska Airlines": "B",
        # Terminal C — United hub
        "United": "C", "United Airlines": "C", "Air China": "C",
        "Singapore Airlines": "C", "ANA": "C", "Turkish Airlines": "C",
        "TAP Air Portugal": "C", "Copa Airlines": "C", "Avianca": "C",
    },
    "LGA": {
        # Terminal B — Delta hub
        "Delta": "B", "Delta Air Lines": "B", "WestJet": "B",
        # Terminal C — all other carriers
        "American Airlines": "C", "Southwest": "C", "United": "C",
        "Spirit": "C", "Frontier": "C", "Allegiant": "C",
        "Alaska Airlines": "C", "JetBlue": "C",
    },
}

def resolve_terminal(origin_iata: str, airline: str | None) -> str | None:
    """Return terminal string from static lookup, or None if unknown."""
    if not airline:
        return None
    airport_map = AIRLINE_TERMINALS.get(origin_iata, {})
    # Try exact match first, then partial match
    if airline in airport_map:
        return airport_map[airline]
    for key, terminal in airport_map.items():
        if key.lower() in airline.lower() or airline.lower() in key.lower():
            return terminal
    return None


# ── Lounge lookup: airport → terminal → list of lounges ───────────────────────
LOUNGES: dict[str, dict[str, list[str]]] = {
    "JFK": {
        "1": [
            "Air France Lounge — Priority Pass / Flying Blue Gold+",
            "Korean Air Lounge — Priority Pass / SkyTeam Elite+",
            "Japan Airlines Sakura Lounge — JAL status / Oneworld",
            "Lufthansa Business Lounge — Lufthansa / Star Alliance Gold",
        ],
        "4": [
            "Delta Sky Club — Delta status / Priority Pass / Amex Platinum",
        ],
        "5": [
            "British Airways Galleries Club — Priority Pass / Oneworld Sapphire+",
            "JetBlue Mint Lounge — JetBlue Mint fare / Mosaic",
        ],
        "7": [
            "British Airways Galleries Club — Priority Pass / Oneworld Sapphire+",
        ],
        "8": [
            "American Airlines Admirals Club — AA status / Priority Pass",
            "Amex Centurion Lounge — Amex Platinum or Centurion card",
        ],
    },
    "EWR": {
        "A": [
            "No dedicated lounge — gate area only",
        ],
        "B": [
            "United Club — United MileagePlus Silver+ / Priority Pass",
            "United Polaris Lounge — United Polaris Business / 1K",
        ],
        "C": [
            "United Club — United MileagePlus Silver+ / Priority Pass",
        ],
    },
    "LGA": {
        "B": [
            "Delta Sky Club — Delta status / Priority Pass / Amex Platinum",
            "American Airlines Admirals Club — AA status / Priority Pass",
        ],
        "C": [
            "Delta Sky Club — Delta status / Priority Pass / Amex Platinum",
        ],
    },
}

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SunChaser",
    page_icon="✈",
    layout="wide",
    initial_sidebar_state="collapsed",
)
init_db()

# ── Design system ─────────────────────────────────────────────────────────────
THEME = {
    "bg":          "#f0f4f8",
    "surface":     "#ffffff",
    "card":        "#ffffff",
    "card_hover":  "#f8faff",
    "border":      "rgba(0,0,0,0.07)",
    "border_hl":   "rgba(99,102,241,0.35)",
    "blue":        "#6366f1",   # indigo
    "green":       "#059669",
    "amber":       "#d97706",
    "red":         "#dc2626",
    "text":        "#0f172a",
    "text_muted":  "#64748b",
    "text_dim":    "#cbd5e1",
}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ── Reset & base ─────────────────────────────────── */
html, body, [class*="css"], .stApp {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    background-color: {THEME['bg']} !important;
    color: {THEME['text']} !important;
}}

/* Remove Streamlit chrome */
#MainMenu, footer, header {{ visibility: hidden; }}
.stDeployButton {{ display: none; }}

/* Main padding */
.main .block-container {{
    padding: 2.5rem 3rem 4rem 3rem;
    max-width: 1440px;
}}

/* ── Scrollbar ────────────────────────────────────── */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: {THEME['bg']}; }}
::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: #94a3b8; }}

/* ── Tabs ─────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    background: {THEME['card']} !important;
    border-radius: 14px !important;
    padding: 5px !important;
    gap: 2px !important;
    border: 1px solid {THEME['border']} !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent !important;
    border-radius: 10px !important;
    color: {THEME['text_muted']} !important;
    font-size: 12.5px !important;
    font-weight: 500 !important;
    padding: 7px 18px !important;
    transition: all 0.18s ease !important;
    border: none !important;
}}
.stTabs [aria-selected="true"] {{
    background: linear-gradient(135deg, {THEME['blue']}, #818cf8) !important;
    color: white !important;
    font-weight: 600 !important;
    box-shadow: 0 4px 14px rgba(99,102,241,0.3) !important;
}}
.stTabs [data-baseweb="tab"]:hover:not([aria-selected="true"]) {{
    background: #f1f5f9 !important;
    color: {THEME['text']} !important;
}}
.stTabs [data-baseweb="tab-panel"] {{
    padding-top: 28px !important;
}}

/* ── Inputs ───────────────────────────────────────── */
.stTextInput > div > div > input,
.stNumberInput > div > div > input {{
    background: {THEME['card']} !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
    color: {THEME['text']} !important;
    font-size: 13.5px !important;
    font-family: 'Inter', sans-serif !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}}
.stTextInput > div > div > input:focus,
.stNumberInput > div > div > input:focus {{
    border-color: {THEME['blue']} !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.12) !important;
}}
.stSelectbox > div > div,
.stSelectbox > div > div > div {{
    background: {THEME['card']} !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
    color: {THEME['text']} !important;
    font-size: 13.5px !important;
}}
label, .stSelectbox label, .stTextInput label, .stNumberInput label {{
    color: {THEME['text_muted']} !important;
    font-size: 11.5px !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.8px !important;
}}

/* ── Buttons ──────────────────────────────────────── */
.stButton > button {{
    background: linear-gradient(135deg, {THEME['blue']}, #818cf8) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 9px 22px !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    font-family: 'Inter', sans-serif !important;
    transition: all 0.2s ease !important;
    letter-spacing: 0.3px !important;
    box-shadow: 0 2px 8px rgba(99,102,241,0.25) !important;
}}
.stButton > button:hover {{
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(99,102,241,0.35) !important;
    filter: brightness(1.05) !important;
}}
.stButton > button:active {{
    transform: translateY(0) !important;
}}
button[kind="secondary"] {{
    background: {THEME['card']} !important;
    color: {THEME['text_muted']} !important;
    border: 1px solid #e2e8f0 !important;
    box-shadow: none !important;
}}

/* ── Metrics ──────────────────────────────────────── */
[data-testid="stMetric"] {{
    background: {THEME['card']} !important;
    border: 1px solid {THEME['border']} !important;
    border-radius: 16px !important;
    padding: 20px 24px !important;
    box-shadow: 0 1px 6px rgba(0,0,0,0.05) !important;
}}
[data-testid="stMetricValue"] {{
    color: {THEME['text']} !important;
    font-size: 26px !important;
    font-weight: 700 !important;
}}
[data-testid="stMetricLabel"] {{
    color: {THEME['text_muted']} !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
}}
[data-testid="stMetricDelta"] {{
    font-size: 12px !important;
}}

/* ── Forms ────────────────────────────────────────── */
[data-testid="stForm"] {{
    background: {THEME['card']} !important;
    border: 1px solid {THEME['border']} !important;
    border-radius: 16px !important;
    padding: 24px !important;
    box-shadow: 0 1px 6px rgba(0,0,0,0.05) !important;
}}

/* ── Dividers ─────────────────────────────────────── */
hr {{
    border: none !important;
    border-top: 1px solid #e2e8f0 !important;
    margin: 24px 0 !important;
}}

/* ── Alerts/info boxes ────────────────────────────── */
.stAlert {{
    border-radius: 12px !important;
    border: none !important;
}}
</style>
"""


# ── HTML component helpers ────────────────────────────────────────────────────

def hero():
    st.markdown(f"""
    <div style="display:flex; align-items:center; justify-content:space-between;
                margin-bottom:32px; padding:24px 28px;
                background:{THEME['card']};
                border:1px solid {THEME['border']};
                border-radius:18px;
                box-shadow:0 2px 12px rgba(0,0,0,0.06);">
        <div>
            <div style="display:flex; align-items:center; gap:12px; margin-bottom:6px;">
                <span style="font-size:28px;">✈</span>
                <span style="font-size:26px; font-weight:800; letter-spacing:-0.5px;
                             background:linear-gradient(135deg,{THEME['blue']},#818cf8);
                             -webkit-background-clip:text; -webkit-text-fill-color:transparent;">
                    SunChaser
                </span>
            </div>
            <p style="color:{THEME['text_muted']}; font-size:13px; margin:0;">
                Real-time flight & award tracker · JFK · EWR · LGA
            </p>
        </div>
        <div style="display:flex; align-items:center; gap:8px;
                    background:#f0fdf4; border:1px solid rgba(5,150,105,0.2);
                    border-radius:10px; padding:8px 16px;">
            <div style="width:7px; height:7px; border-radius:50%;
                        background:{THEME['green']};
                        box-shadow:0 0 6px {THEME['green']};"></div>
            <span style="font-size:12px; font-weight:600; color:{THEME['green']};">Live</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def section_label(text: str):
    st.markdown(f"""
    <p style="font-size:10.5px; font-weight:700; color:{THEME['text_muted']};
              text-transform:uppercase; letter-spacing:1.5px; margin:0 0 14px 2px;">
        {text}
    </p>
    """, unsafe_allow_html=True)


def badge(text: str, color: str) -> str:
    colors = {
        "green":  (THEME['green'],  "#dcfce7"),
        "amber":  (THEME['amber'],  "#fef3c7"),
        "red":    (THEME['red'],    "#fee2e2"),
        "blue":   (THEME['blue'],   "#ede9fe"),
        "purple": ("#7c3aed",       "#f5f3ff"),
        "muted":  (THEME['text_muted'], "#f1f5f9"),
    }
    fg, bg = colors.get(color, colors["muted"])
    return (
        f'<span style="display:inline-block; padding:2px 10px; border-radius:20px; '
        f'font-size:10.5px; font-weight:600; letter-spacing:0.4px; '
        f'color:{fg}; background:{bg};">{text}</span>'
    )


def cpp_badge(cpp: float | None) -> str:
    if cpp is None:
        return badge("—", "muted")
    if cpp >= 2.0:
        return badge(f"{cpp:.2f}¢/pt", "green")
    if cpp >= 1.2:
        return badge(f"{cpp:.2f}¢/pt", "amber")
    return badge(f"{cpp:.2f}¢/pt", "red")


def price_card(
    origin: str, dest: str, price_str: str,
    detail1: str, detail2: str, detail3: str,
    badge_html: str = "", right_sub: str = "",
):
    st.markdown(f"""
    <div style="display:flex; align-items:center; justify-content:space-between;
                background:{THEME['card']}; border:1px solid {THEME['border']};
                border-radius:14px; padding:16px 22px; margin-bottom:8px;
                box-shadow:0 1px 4px rgba(0,0,0,0.05);
                transition:all 0.18s ease;"
         onmouseover="this.style.borderColor='{THEME['border_hl']}';this.style.boxShadow='0 4px 16px rgba(99,102,241,0.12)'"
         onmouseout="this.style.borderColor='{THEME['border']}';this.style.boxShadow='0 1px 4px rgba(0,0,0,0.05)'">
        <div style="display:flex; align-items:center; gap:18px;">
            <div style="background:#ede9fe; border:1px solid rgba(99,102,241,0.2);
                        border-radius:10px; padding:10px 14px; text-align:center; min-width:72px;">
                <div style="font-size:11px; font-weight:700; color:{THEME['blue']}; letter-spacing:1px;">
                    {origin}
                </div>
                <div style="font-size:9px; color:{THEME['text_muted']}; margin:2px 0;">→</div>
                <div style="font-size:11px; font-weight:700; color:{THEME['blue']}; letter-spacing:1px;">
                    {dest}
                </div>
            </div>
            <div>
                <div style="font-size:14px; font-weight:600; color:{THEME['text']}; margin-bottom:4px;">
                    {detail1}
                </div>
                <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                    <span style="font-size:12px; color:{THEME['text_muted']};">{detail2}</span>
                    <span style="color:#e2e8f0;">·</span>
                    <span style="font-size:12px; color:{THEME['text_muted']};">{detail3}</span>
                    {f'<span style="color:#e2e8f0;">·</span>{badge_html}' if badge_html else ''}
                </div>
            </div>
        </div>
        <div style="text-align:right;">
            <div style="font-size:22px; font-weight:800; color:{THEME['green']}; letter-spacing:-0.5px;">
                {price_str}
            </div>
            <div style="font-size:11px; color:{THEME['text_muted']}; margin-top:2px;">
                {right_sub}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def award_card(
    origin: str, dest: str, points_str: str,
    program: str, cabin: str, date: str,
    fees_str: str, cpp_html: str, can_book: bool, pts_needed: str,
):
    book_html = (
        f'<span style="color:{THEME["green"]}; font-size:11px; font-weight:600;">✓ Can book</span>'
        if can_book else
        f'<span style="color:{THEME["text_muted"]}; font-size:11px;">Need {pts_needed} more</span>'
    )
    st.markdown(f"""
    <div style="display:flex; align-items:center; justify-content:space-between;
                background:{THEME['card']}; border:1px solid {THEME['border']};
                border-radius:14px; padding:16px 22px; margin-bottom:8px;
                box-shadow:0 1px 4px rgba(0,0,0,0.05);
                transition:all 0.18s ease;"
         onmouseover="this.style.borderColor='{THEME['border_hl']}';this.style.boxShadow='0 4px 16px rgba(99,102,241,0.12)'"
         onmouseout="this.style.borderColor='{THEME['border']}';this.style.boxShadow='0 1px 4px rgba(0,0,0,0.05)'">
        <div style="display:flex; align-items:center; gap:18px;">
            <div style="background:#ede9fe; border:1px solid rgba(99,102,241,0.2);
                        border-radius:10px; padding:10px 14px; text-align:center; min-width:72px;">
                <div style="font-size:11px; font-weight:700; color:{THEME['blue']}; letter-spacing:1px;">
                    {origin}
                </div>
                <div style="font-size:9px; color:{THEME['text_muted']}; margin:2px 0;">→</div>
                <div style="font-size:11px; font-weight:700; color:{THEME['blue']}; letter-spacing:1px;">
                    {dest}
                </div>
            </div>
            <div>
                <div style="font-size:14px; font-weight:600; color:{THEME['text']}; margin-bottom:4px;">
                    {program}
                </div>
                <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                    {badge(cabin.title(), "blue")}
                    <span style="color:#e2e8f0;">·</span>
                    <span style="font-size:12px; color:{THEME['text_muted']};">{date}</span>
                    <span style="color:#e2e8f0;">·</span>
                    <span style="font-size:12px; color:{THEME['text_muted']};">+{fees_str} fees</span>
                    <span style="color:#e2e8f0;">·</span>
                    {cpp_html}
                </div>
            </div>
        </div>
        <div style="text-align:right;">
            <div style="font-size:20px; font-weight:800; color:{THEME['blue']}; letter-spacing:-0.5px;">
                {points_str}
            </div>
            <div style="margin-top:4px;">{book_html}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def plotly_layout(fig):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color=THEME["text_muted"], size=12),
        xaxis=dict(
            gridcolor="rgba(0,0,0,0.05)",
            linecolor="rgba(0,0,0,0.08)",
            tickcolor="rgba(0,0,0,0)",
        ),
        yaxis=dict(
            gridcolor="rgba(0,0,0,0.05)",
            linecolor="rgba(0,0,0,0.08)",
            tickcolor="rgba(0,0,0,0)",
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=0, r=0, t=10, b=0),
        hovermode="x unified",
    )
    return fig


# ── Flight detail dialog ──────────────────────────────────────────────────────

@st.dialog("Flight Details", width="large")
def flight_detail_dialog(fp, origin_iata: str, dest_name: str, dest_iata: str):
    """Modal popup with full flight details and lounge info."""
    dur = fp.duration_minutes
    dur_display   = f"{dur // 60}h {dur % 60}m" if dur else "—"
    stops_display = "Non-stop ✓" if (fp.stops or 0) == 0 else f"{fp.stops} stop{'s' if (fp.stops or 0) > 1 else ''}"
    terminal      = fp.terminal or resolve_terminal(origin_iata, fp.airline)
    terminal_display = f"Terminal {terminal}" if terminal else "Unknown"
    terminal_source  = "" if fp.terminal else " *(estimated from airline)*" if terminal else ""
    fn_str        = f"  ·  {fp.flight_number}" if fp.flight_number else ""

    # ── Header ──
    st.markdown(f"## ✈  {origin_iata} → {dest_iata}  ·  {dest_name}")
    st.markdown(f"**{fp.airline or 'Various airlines'}**  ·  {fp.cabin_class.title()}{fn_str}")
    st.markdown(f"### :green[${fp.price:,.0f}] round trip")
    st.divider()

    # ── Schedule ──
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Departure", fp.departure_time or "—")
    c2.metric("Arrival",   fp.arrival_time   or "—")
    c3.metric("Duration",  dur_display)
    c4.metric("Stops",     stops_display)

    st.divider()

    # ── Dates ──
    d1, d2, d3 = st.columns(3)
    d1.metric("Departs",     fp.departure_date or "—")
    d2.metric("Returns",     fp.return_date    or "—")
    d3.metric("Trip Length", f"{fp.trip_length_days or 7} days")

    st.divider()

    # ── Historical price chart ──
    st.markdown("#### 📈  Price History")
    st.caption(f"All {fp.cabin_class} fares ever tracked for {origin_iata} → {dest_iata} — grows with every fetch")

    hist_session = get_session()
    hist_rows = (
        hist_session.query(FlightPrice)
        .filter(
            FlightPrice.route_id    == fp.route_id,
            FlightPrice.cabin_class == fp.cabin_class,
        )
        .order_by(FlightPrice.departure_date.asc())
        .all()
    )
    hist_session.close()

    if hist_rows:
        hist_df = pd.DataFrame([
            {
                "Departure Date": r.departure_date,
                "Fetched":        r.fetched_at.strftime("%Y-%m-%d") if r.fetched_at else "—",
                "Price":          r.price,
                "Airline":        r.airline or "Various",
            }
            for r in hist_rows
        ])

        chart_tab1, chart_tab2 = st.tabs(["By Departure Date", "Price Over Time (History)"])

        _layout = dict(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter", size=11, color="#64748b"),
            height=280, margin=dict(l=0, r=0, t=10, b=0),
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.2, bgcolor="rgba(0,0,0,0)"),
            xaxis=dict(gridcolor="rgba(0,0,0,0.05)", linecolor="rgba(0,0,0,0.08)", tickcolor="rgba(0,0,0,0)"),
            yaxis=dict(gridcolor="rgba(0,0,0,0.05)", linecolor="rgba(0,0,0,0.08)",
                       tickprefix="$", tickformat=",.0f", tickcolor="rgba(0,0,0,0)"),
        )

        # ── Tab 1: price by departure date ──
        with chart_tab1:
            best_df = (
                hist_df.groupby("Departure Date", as_index=False)["Price"]
                .min().sort_values("Departure Date")
            )
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hist_df["Departure Date"], y=hist_df["Price"],
                mode="markers", name="All fares",
                marker=dict(color="#c7d2fe", size=5, opacity=0.5),
                hovertemplate="%{x}<br>$%{y:,.0f}<extra></extra>",
            ))
            fig.add_trace(go.Scatter(
                x=best_df["Departure Date"], y=best_df["Price"],
                mode="lines+markers", name="Best price",
                line=dict(color="#6366f1", width=2.5, shape="spline"),
                marker=dict(color="#6366f1", size=6),
                hovertemplate="%{x}<br><b>Best: $%{y:,.0f}</b><extra></extra>",
            ))
            if fp.departure_date:
                fig.add_trace(go.Scatter(
                    x=[fp.departure_date], y=[fp.price],
                    mode="markers", name="This flight",
                    marker=dict(color="#059669", size=13, symbol="star",
                                line=dict(color="white", width=2)),
                    hovertemplate=f"<b>Selected: ${fp.price:,.0f}</b><extra></extra>",
                ))
            fig.update_layout(**_layout)
            st.plotly_chart(fig, use_container_width=True)

        # ── Tab 2: how the best price changed over fetch dates (history) ──
        with chart_tab2:
            fetch_trend = (
                hist_df.groupby("Fetched", as_index=False)["Price"]
                .min().sort_values("Fetched")
            )
            if len(fetch_trend) > 1:
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(
                    x=fetch_trend["Fetched"], y=fetch_trend["Price"],
                    mode="lines+markers", name="Best price on fetch date",
                    line=dict(color="#059669", width=2.5, shape="spline"),
                    marker=dict(color="#059669", size=7),
                    fill="tozeroy", fillcolor="rgba(5,150,105,0.06)",
                    hovertemplate="%{x}<br><b>Best available: $%{y:,.0f}</b><extra></extra>",
                ))
                fig2.update_layout(**_layout)
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Price history builds up over time as you run more fetches. Check back after your next fetch!")

        # Airline breakdown — horizontal bar
        st.markdown("#### 🏷  Lowest Fare by Airline")
        airline_df = (
            hist_df.groupby("Airline", as_index=False)["Price"]
            .min()
            .sort_values("Price")
            .head(10)
        )
        fig2 = go.Figure(go.Bar(
            x=airline_df["Price"],
            y=airline_df["Airline"],
            orientation="h",
            marker=dict(
                color=airline_df["Price"],
                colorscale=[[0, "#6366f1"], [0.5, "#818cf8"], [1, "#c7d2fe"]],
                showscale=False,
            ),
            text=[f"${p:,.0f}" for p in airline_df["Price"]],
            textposition="outside",
            hovertemplate="%{y}<br><b>$%{x:,.0f}</b><extra></extra>",
        ))
        fig2.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter", size=11, color="#64748b"),
            height=max(180, len(airline_df) * 32),
            margin=dict(l=0, r=60, t=10, b=0),
            xaxis=dict(gridcolor="rgba(0,0,0,0.05)", tickprefix="$",
                       tickformat=",.0f", tickcolor="rgba(0,0,0,0)"),
            yaxis=dict(gridcolor="rgba(0,0,0,0)", tickcolor="rgba(0,0,0,0)"),
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.caption("No historical data yet — run a fetch to populate.")

    st.divider()

    # ── Terminal & Lounges ──
    st.markdown(f"#### 🛫  Departure Terminal · {origin_iata}")
    st.info(f"**{terminal_display}**{terminal_source}")

    lounges = LOUNGES.get(origin_iata, {}).get(str(terminal).upper() if terminal else "", [])
    if lounges:
        st.markdown(f"#### 🛋  Lounges in {terminal_display}")
        for lounge in lounges:
            name, _, access = lounge.partition(" — ")
            col_name, col_access = st.columns([2, 3])
            col_name.markdown(f"**{name}**")
            col_access.markdown(f"*{access}*")
            st.divider()
    elif terminal:
        st.caption(f"No lounge data on file for {terminal_display}.")
    else:
        st.caption("Terminal info will appear after the next data fetch.")


# ── App ────────────────────────────────────────────────────────────────────────

st.markdown(CSS, unsafe_allow_html=True)
hero()

tabs = st.tabs([
    "✈  Cash Prices",
    "🏆  Award Prices",
    "⚡  Optimizer",
    "🔍  Flexible Search",
    "📈  Trends",
    "🏨  Hotels",
    "💳  My Points",
    "🔔  Alerts",
    "🌍  Destinations",
])
(tab_cash, tab_awards, tab_opt, tab_flex,
 tab_trends, tab_hotels, tab_points, tab_alerts, tab_dests) = tabs


# ── Cash Prices ───────────────────────────────────────────────────────────────
with tab_cash:

    # ── Search panel ──────────────────────────────────────────────────────────
    # Load destination + origin options from DB
    _sess = get_session()
    _all_dests   = _sess.query(Destination).filter(Destination.is_active == True).order_by(Destination.name).all()
    _all_origins = _sess.query(DepartureAirport).order_by(DepartureAirport.iata_code).all()
    _price_range = _sess.query(
        func.min(FlightPrice.price),
        func.max(FlightPrice.price),
    ).first()
    _sess.close()

    _dest_options  = {f"{d.name}  ({d.iata_code})": d.iata_code for d in _all_dests}
    _origin_options = {f"{o.iata_code} — {o.name}": o.iata_code for o in _all_origins}
    _min_p = int(_price_range[0] or 0)
    _max_p = int(_price_range[1] or 5000)

    with st.container():
        st.markdown(f"""
        <div style="background:#ffffff; border:1px solid rgba(0,0,0,0.07);
                    border-radius:16px; padding:20px 24px 8px 24px;
                    box-shadow:0 1px 6px rgba(0,0,0,0.05); margin-bottom:20px;">
        """, unsafe_allow_html=True)

        row1a, row1b, row1c = st.columns([3, 3, 2])
        sel_dests   = row1a.multiselect(
            "Destinations",
            options=list(_dest_options.keys()),
            placeholder="All destinations",
            key="search_dests",
        )
        sel_origins = row1b.multiselect(
            "Departing from",
            options=list(_origin_options.keys()),
            placeholder="JFK, EWR & LGA",
            key="search_origins",
        )
        cabin = row1c.selectbox(
            "Cabin class",
            ["Economy", "Business", "First", "Premium"],
            key="cc",
        )

        row2a, row2b, row2c, row2d = st.columns([2, 2, 2, 1])
        dep_from = row2a.date_input("Departs after",  value=None, key="dep_from")
        dep_to   = row2b.date_input("Departs before", value=None, key="dep_to")
        price_max = row2c.slider(
            "Max price",
            min_value=_min_p, max_value=max(_max_p, _min_p + 1),
            value=max(_max_p, _min_p + 1),
            step=50, format="$%d", key="price_max",
        )
        row2d.markdown("<div style='height:27px'></div>", unsafe_allow_html=True)
        nonstop_only = row2d.toggle("Non-stop", key="nonstop")

        row3a, row3b = st.columns([4, 1])
        sort_by = row3a.radio(
            "Sort by",
            ["Lowest price", "Departure date", "Duration", "Airline"],
            horizontal=True, key="sort_by",
        )

        st.markdown("</div>", unsafe_allow_html=True)

    # ── Build query ───────────────────────────────────────────────────────────
    cabin_lower = cabin.lower()
    selected_iatas   = [_dest_options[k]   for k in sel_dests]
    selected_origins = [_origin_options[k] for k in sel_origins]

    session = get_session()
    q = (
        session.query(FlightPrice, Route, Destination)
        .join(Route,       FlightPrice.route_id      == Route.id)
        .join(Destination, Route.destination_id      == Destination.id)
        .join(DepartureAirport, Route.origin_id      == DepartureAirport.id)
        .options(joinedload(Route.origin))
        .filter(FlightPrice.cabin_class == cabin_lower, Route.is_active == True)
        .filter(FlightPrice.price <= price_max)
    )
    if selected_iatas:
        q = q.filter(Destination.iata_code.in_(selected_iatas))
    if selected_origins:
        q = q.filter(DepartureAirport.iata_code.in_(selected_origins))
    if nonstop_only:
        q = q.filter(FlightPrice.stops == 0)
    if dep_from:
        q = q.filter(FlightPrice.departure_date >= str(dep_from))
    if dep_to:
        q = q.filter(FlightPrice.departure_date <= str(dep_to))

    sort_col = {
        "Lowest price":   FlightPrice.price.asc(),
        "Departure date": FlightPrice.departure_date.asc(),
        "Duration":       FlightPrice.duration_minutes.asc(),
        "Airline":        FlightPrice.airline.asc(),
    }[sort_by]

    rows = q.order_by(sort_col).limit(200).all()
    session.close()

    # ── KPI strip ─────────────────────────────────────────────────────────────
    if rows:
        prices        = [fp.price for fp, _, _ in rows]
        nonstop_count = sum(1 for fp, _, _ in rows if (fp.stops or 0) == 0)
        unique_dests  = len(set(dest.iata_code for _, _, dest in rows))

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Best Price",  f"${min(prices):,.0f}")
        m2.metric("Avg Price",   f"${sum(prices)/len(prices):,.0f}")
        m3.metric("Destinations", str(unique_dests))
        m4.metric("Results",     str(len(rows)))
        m5.metric("Non-stop",    str(nonstop_count))

        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
        section_label(f"{len(rows)} fares found — click › for details")

        for fp, route, dest in rows[:50]:
            pct = price_percentile(route.id, cabin_lower, fp.price)
            if pct is not None:
                if pct <= 20:   b_html = badge("Great deal", "green")
                elif pct <= 45: b_html = badge("Good price", "blue")
                elif pct <= 70: b_html = badge("Average",    "muted")
                else:           b_html = badge("Pricey",     "amber")
            else:
                b_html = ""

            stops_badge = (
                badge("Non-stop", "green") if (fp.stops or 0) == 0
                else badge(f"{fp.stops} stop{'s' if fp.stops > 1 else ''}", "amber")
            )
            time_str = (
                f"{fp.departure_time} → {fp.arrival_time}"
                if fp.departure_time and fp.arrival_time
                else f"Departs {fp.departure_date}"
            )

            card_col, btn_col = st.columns([11, 1])
            with card_col:
                price_card(
                    origin    = route.origin.iata_code,
                    dest      = dest.iata_code,
                    price_str = f"${fp.price:,.0f}",
                    detail1   = f"{dest.name}  ·  {fp.airline or 'Various'}",
                    detail2   = time_str,
                    detail3   = f"{fp.departure_date or ''}  ·  {fp.trip_length_days or 7}d trip",
                    badge_html= f"{stops_badge}{'  ' + b_html if b_html else ''}",
                    right_sub = f"{pct:.0f}th percentile" if pct is not None else "",
                )
            with btn_col:
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                if st.button("›", key=f"fd_{fp.id}", help="View flight details", use_container_width=True):
                    flight_detail_dialog(fp, route.origin.iata_code, dest.name, dest.iata_code)
    else:
        st.info("No flights match your search — try relaxing the filters or run a fresh fetch.")


# ── Award Prices ──────────────────────────────────────────────────────────────
with tab_awards:
    a1, a2, a3, a4 = st.columns([2, 2, 2, 1])
    cabin_a    = a1.selectbox("Cabin", ["economy", "business", "first"], key="ac")
    prog_input = a2.text_input("Program slug", placeholder="chase_ur, delta_skymiles …", key="ap")
    dest_a     = a3.text_input("Destination IATA", placeholder="LHR …", key="ad").upper()

    session = get_session()
    q = (
        session.query(AwardPrice, Route, Destination, LoyaltyProgram, UserPoints)
        .join(Route,         AwardPrice.route_id   == Route.id)
        .join(Destination,   Route.destination_id  == Destination.id)
        .join(LoyaltyProgram,AwardPrice.program_id == LoyaltyProgram.id)
        .outerjoin(UserPoints, UserPoints.program_id == LoyaltyProgram.id)
        .options(joinedload(Route.origin))
        .filter(AwardPrice.cabin_class == cabin_a, Route.is_active == True)
    )
    if prog_input:
        q = q.filter(LoyaltyProgram.slug == prog_input)
    if dest_a:
        q = q.filter(Destination.iata_code == dest_a)
    award_rows = q.order_by(AwardPrice.points_required.asc()).limit(80).all()
    session.close()

    if award_rows:
        pts_list  = [ap.points_required for ap, *_ in award_rows if ap.points_required]
        m1, m2, m3 = st.columns(3)
        m1.metric("Best Award",      f"{min(pts_list):,} pts" if pts_list else "—")
        m2.metric("Avg Points",      f"{int(sum(pts_list)/len(pts_list)):,}" if pts_list else "—")
        m3.metric("Results",         f"{len(award_rows)}")

        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
        section_label("Award Availability")

        for ap, route, dest, prog, up in award_rows[:40]:
            balance   = up.balance if up else 0
            can_book  = balance >= (ap.points_required or 0)
            pts_needed = f"{(ap.points_required or 0) - balance:,}"
            avg        = route_average(route.id, cabin_a)
            cpp        = None
            if avg and ap.points_required:
                cpp = round(((avg - (ap.cash_fees or 0)) / ap.points_required) * 100, 2)

            award_card(
                origin     = route.origin.iata_code,
                dest       = dest.iata_code,
                points_str = f"{ap.points_required:,}" if ap.points_required else "—",
                program    = prog.name,
                cabin      = cabin_a,
                date       = ap.availability_date or "—",
                fees_str   = f"${ap.cash_fees:.0f}" if ap.cash_fees else "$0",
                cpp_html   = cpp_badge(cpp),
                can_book   = can_book,
                pts_needed = pts_needed,
            )
    else:
        st.info("No award data yet — run `python main.py --fetch` to populate.")


# ── Transfer Optimizer ────────────────────────────────────────────────────────
with tab_opt:
    st.markdown(f"""
    <p style="color:{THEME['text_muted']}; font-size:13px; margin-bottom:24px;">
        Find the best credit card transfer path to any destination, ranked by cents per point.
    </p>
    """, unsafe_allow_html=True)

    o1, o2 = st.columns([2, 2])
    opt_dest  = o1.text_input("Destination IATA", placeholder="LHR, NRT, CDG …", key="od").upper()
    opt_cabin = o2.selectbox("Cabin", ["economy", "business", "first"], key="oc")

    if opt_dest:
        results = optimize_transfers(opt_dest, opt_cabin)
        if results:
            section_label(f"{len(results)} transfer paths found")
            for r in results:
                can_book = r["can_book"]
                cpp_html = cpp_badge(r["cents_per_point"])
                book_icon = f'<span style="color:{THEME["green"]}; font-weight:700;">✓</span>' if can_book else '✗'
                st.markdown(f"""
                <div style="display:grid; grid-template-columns:auto 1fr auto auto; gap:16px;
                            align-items:center; background:{THEME['card']};
                            border:1px solid {THEME['border']}; border-radius:14px;
                            padding:16px 22px; margin-bottom:8px;
                            box-shadow:0 1px 4px rgba(0,0,0,0.05);">
                    <div style="background:#ede9fe; border:1px solid rgba(99,102,241,0.2);
                                border-radius:10px; padding:10px 14px; text-align:center; min-width:72px;">
                        <div style="font-size:11px; font-weight:700; color:{THEME['blue']}; letter-spacing:1px;">
                            {r['origin']}
                        </div>
                        <div style="font-size:9px; color:{THEME['text_muted']}; margin:2px 0;">→</div>
                        <div style="font-size:11px; font-weight:700; color:{THEME['blue']}; letter-spacing:1px;">
                            {r['dest_iata']}
                        </div>
                    </div>
                    <div>
                        <div style="font-size:14px; font-weight:600; color:{THEME['text']}; margin-bottom:5px;">
                            {r['credit_card']}
                            <span style="color:{THEME['text_muted']}; font-size:12px; font-weight:400;"> → </span>
                            {r['airline_program']}
                        </div>
                        <div style="display:flex; gap:8px; align-items:center;">
                            {badge(opt_cabin.title(), "blue")}
                            <span style="color:{THEME['text_dim']};">·</span>
                            <span style="font-size:12px; color:{THEME['text_muted']};">{r['date'] or '—'}</span>
                            <span style="color:{THEME['text_dim']};">·</span>
                            <span style="font-size:12px; color:{THEME['text_muted']};">+${r['cash_fees']:.0f} fees</span>
                            <span style="color:{THEME['text_dim']};">·</span>
                            {cpp_html}
                        </div>
                    </div>
                    <div style="text-align:center;">
                        <div style="font-size:19px; font-weight:800; color:{THEME['blue']};">
                            {r['points_required']:,}
                        </div>
                        <div style="font-size:10px; color:{THEME['text_muted']}; margin-top:2px;">points needed</div>
                    </div>
                    <div style="text-align:center; font-size:20px;">{book_icon}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info(f"No transfer options found for {opt_dest}. Fetch data first.")
    else:
        st.markdown(f"""
        <div style="text-align:center; padding:60px 20px; color:{THEME['text_muted']};">
            <div style="font-size:40px; margin-bottom:12px;">⚡</div>
            <div style="font-size:15px; font-weight:500;">Enter a destination IATA code above to see transfer options</div>
            <div style="font-size:13px; margin-top:6px; opacity:0.6;">e.g. LHR for London, NRT for Tokyo, CDG for Paris</div>
        </div>
        """, unsafe_allow_html=True)


# ── Flexible Search ───────────────────────────────────────────────────────────
with tab_flex:
    st.markdown(f"""
    <p style="color:{THEME['text_muted']}; font-size:13px; margin-bottom:24px;">
        Discover any destination available under your budget right now.
    </p>
    """, unsafe_allow_html=True)

    f1, f2, f3 = st.columns([2, 2, 1])
    max_price  = f1.number_input("Max price ($)", min_value=50, max_value=5000, value=500, step=50)
    flex_cabin = f2.selectbox("Cabin", ["economy", "business", "first"], key="fc")
    f3.markdown("<div style='height:27px'></div>", unsafe_allow_html=True)
    search_btn = f3.button("Search", use_container_width=True)

    if search_btn:
        results = check_flexible_destination_alerts(max_price, flex_cabin)
        if results:
            section_label(f"{len(results)} destinations under ${max_price:,}")
            for r in results:
                price_card(
                    origin    = r["origin"],
                    dest      = r["iata"],
                    price_str = f"${r['price']:,.0f}",
                    detail1   = f"{r['destination']}  ·  {r['airline'] or 'Various'}",
                    detail2   = f"Departs {r['departs']}",
                    detail3   = r["region"] or "",
                    right_sub = "",
                )
        else:
            st.info(f"No flights found under ${max_price:,}. Try fetching fresh data.")
    else:
        st.markdown(f"""
        <div style="text-align:center; padding:60px 20px; color:{THEME['text_muted']};">
            <div style="font-size:40px; margin-bottom:12px;">🔍</div>
            <div style="font-size:15px; font-weight:500;">Set your budget and search</div>
            <div style="font-size:13px; margin-top:6px; opacity:0.6;">We'll find every destination available right now</div>
        </div>
        """, unsafe_allow_html=True)


# ── Price Trends ──────────────────────────────────────────────────────────────
with tab_trends:
    session = get_session()
    dests   = session.query(Destination).filter(Destination.is_active == True).all()
    session.close()

    dest_map  = {d.name: d.iata_code for d in dests}
    t1, t2    = st.columns([3, 2])
    sel_dest  = t1.selectbox("Destination", list(dest_map.keys()), key="td")
    trend_cab = t2.selectbox("Cabin", ["economy", "business", "first"], key="tc")

    if sel_dest:
        iata = dest_map[sel_dest]
        session = get_session()
        rows = (
            session.query(FlightPrice, Route)
            .join(Route, FlightPrice.route_id == Route.id)
            .join(Destination, Route.destination_id == Destination.id)
            .options(joinedload(Route.origin))
            .filter(Destination.iata_code == iata, FlightPrice.cabin_class == trend_cab,
                    Route.is_active == True)
            .order_by(FlightPrice.fetched_at.asc())
            .all()
        )
        session.close()

        if rows:
            df = pd.DataFrame([
                {
                    "Date":   fp.fetched_at,
                    "Price":  fp.price,
                    "Origin": route.origin.iata_code,
                }
                for fp, route in rows
            ])

            fig = go.Figure()
            colors = [THEME["blue"], THEME["green"], THEME["amber"]]
            for i, origin in enumerate(df["Origin"].unique()):
                sub = df[df["Origin"] == origin]
                color = colors[i % len(colors)]
                fig.add_trace(go.Scatter(
                    x=sub["Date"], y=sub["Price"],
                    mode="lines+markers",
                    name=f"{origin} → {iata}",
                    line=dict(color=color, width=2.5, shape="spline"),
                    marker=dict(size=5, color=color),
                    hovertemplate=f"<b>{origin}→{iata}</b><br>%{{x|%b %d}}<br>${{y:,.0f}}<extra></extra>",
                ))

            fig = plotly_layout(fig)
            fig.update_layout(height=420, legend=dict(orientation="h", y=-0.12))
            fig.update_yaxes(tickprefix="$", tickformat=",.0f")
            st.plotly_chart(fig, use_container_width=True)

            # Price distribution histogram
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            section_label("Price Distribution")
            fig2 = px.histogram(
                df, x="Price", color="Origin",
                nbins=30, barmode="overlay",
                opacity=0.7,
                color_discrete_sequence=[THEME["blue"], THEME["green"], THEME["amber"]],
            )
            fig2 = plotly_layout(fig2)
            fig2.update_layout(height=240, showlegend=False, bargap=0.05)
            fig2.update_xaxes(tickprefix="$")
            fig2.update_yaxes(title="Frequency")
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No price history yet for this route.")


# ── Hotels ────────────────────────────────────────────────────────────────────
with tab_hotels:
    session     = get_session()
    hotel_dests = session.query(Destination).filter(Destination.is_active == True).all()
    session.close()

    hdest_map = {d.name: d.id for d in hotel_dests}
    sel_hotel = st.selectbox("Destination", list(hdest_map.keys()), key="hd")

    if sel_hotel:
        did = hdest_map[sel_hotel]
        session = get_session()
        hrows = (
            session.query(HotelPrice)
            .filter(HotelPrice.destination_id == did)
            .order_by(HotelPrice.price_per_night.asc())
            .limit(30)
            .all()
        )
        best_flight = (
            session.query(FlightPrice, Route)
            .join(Route, FlightPrice.route_id == Route.id)
            .options(joinedload(Route.origin))
            .filter(Route.destination_id == did, FlightPrice.cabin_class == "economy")
            .order_by(FlightPrice.price.asc())
            .first()
        )
        session.close()

        if hrows:
            nightly = [h.price_per_night for h in hrows]
            m1, m2, m3 = st.columns(3)
            m1.metric("Best Rate/Night", f"${min(nightly):,.0f}")
            m2.metric("Avg Rate/Night",  f"${sum(nightly)/len(nightly):,.0f}")
            m3.metric("Hotels Found",    str(len(hrows)))

            flight_price = best_flight[0].price if best_flight else None
            origin_iata  = best_flight[1].origin.iata_code if best_flight else "?"

            st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
            section_label("Hotel Options")

            for h in hrows:
                total_hotel = h.price_per_night * (h.nights or 1)
                combined    = (flight_price + total_hotel) if flight_price else None
                stars       = "★" * int(h.rating) if h.rating else "—"

                st.markdown(f"""
                <div style="display:flex; align-items:center; justify-content:space-between;
                            background:{THEME['card']}; border:1px solid {THEME['border']};
                            border-radius:14px; padding:16px 22px; margin-bottom:8px;
                            box-shadow:0 1px 4px rgba(0,0,0,0.05);">
                    <div>
                        <div style="font-size:14px; font-weight:600; color:{THEME['text']}; margin-bottom:5px;">
                            {h.hotel_name}
                        </div>
                        <div style="display:flex; gap:8px; align-items:center;">
                            <span style="font-size:12px; color:{THEME['amber']};">{stars}</span>
                            <span style="color:{THEME['text_dim']};">·</span>
                            <span style="font-size:12px; color:{THEME['text_muted']};">
                                {h.check_in} – {h.check_out}
                            </span>
                            <span style="color:{THEME['text_dim']};">·</span>
                            <span style="font-size:12px; color:{THEME['text_muted']};">{h.nights or '?'} nights</span>
                        </div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:20px; font-weight:800; color:{THEME['green']};">
                            ${h.price_per_night:,.0f}<span style="font-size:12px; font-weight:400; color:{THEME['text_muted']};"> /night</span>
                        </div>
                        {'<div style="font-size:12px; color:' + THEME["text_muted"] + '; margin-top:3px;">✈ + 🏨 ' + f'${combined:,.0f} combined from {origin_iata}</div>' if combined else ''}
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No hotel data yet — run `python main.py --fetch-hotels`.")


# ── My Points ─────────────────────────────────────────────────────────────────
with tab_points:
    session   = get_session()
    prog_rows = (
        session.query(UserPoints, LoyaltyProgram)
        .join(LoyaltyProgram, UserPoints.program_id == LoyaltyProgram.id)
        .order_by(LoyaltyProgram.program_type.desc(), LoyaltyProgram.name)
        .all()
    )
    session.close()

    cc_rows      = [(up, p) for up, p in prog_rows if p.program_type == "credit_card"]
    airline_rows = [(up, p) for up, p in prog_rows if p.program_type == "airline"]

    def points_section(rows, title):
        section_label(title)
        for up, prog in rows:
            col1, col2, col3 = st.columns([4, 3, 1])
            col1.markdown(f"""
            <div style="padding:8px 0;">
                <div style="font-size:13.5px; font-weight:600; color:{THEME['text']};">
                    {prog.name}
                </div>
                <div style="font-size:11px; color:{THEME['text_muted']}; margin-top:2px;">
                    {prog.currency_name.title()}
                </div>
            </div>
            """, unsafe_allow_html=True)
            new_bal = col2.number_input(
                "balance", value=up.balance, step=1000,
                key=f"bal_{prog.slug}", label_visibility="collapsed",
            )
            col3.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            if col3.button("Save", key=f"sv_{prog.slug}", use_container_width=True):
                s = get_session()
                rec = s.query(UserPoints).filter_by(program_id=prog.id).first()
                rec.balance = new_bal
                s.commit(); s.close()
                st.toast(f"Saved {prog.name}", icon="✅")

    points_section(cc_rows, "Credit Card Points")
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    points_section(airline_rows, "Airline Miles")


# ── Alerts ────────────────────────────────────────────────────────────────────
with tab_alerts:
    try:
        active_alerts = requests.get(f"{API_BASE}/alerts", timeout=4).json()
    except Exception:
        active_alerts = []
        st.warning("API server not running — start it with `python main.py --serve`")

    if active_alerts:
        section_label(f"{len(active_alerts)} active alerts")
        for a in active_alerts:
            cash_str = f"${a['max_cash']:,}" if a.get("max_cash") else ""
            pts_str  = f"{a['max_points']:,} pts" if a.get("max_points") else ""
            val_str  = "  /  ".join(filter(None, [cash_str, pts_str])) or "—"

            col1, col2 = st.columns([6, 1])
            col1.markdown(f"""
            <div style="background:{THEME['card']}; border:1px solid {THEME['border']};
                        border-radius:12px; padding:14px 20px; display:flex;
                        align-items:center; gap:16px;
                        box-shadow:0 1px 4px rgba(0,0,0,0.05);">
                <div>
                    <div style="font-size:14px; font-weight:600; color:{THEME['text']}; margin-bottom:4px;">
                        {a['destination']}
                    </div>
                    <div style="display:flex; gap:8px; align-items:center;">
                        {badge(a['type'].upper(), "blue")}
                        {badge(a['cabin'].title(), "purple")}
                        <span style="color:{THEME['text_dim']};">·</span>
                        <span style="font-size:12px; color:{THEME['green']}; font-weight:600;">{val_str}</span>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            if col2.button("✕", key=f"del_{a['id']}", use_container_width=True):
                requests.delete(f"{API_BASE}/alerts/{a['id']}", timeout=4)
                st.rerun()

    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    section_label("Create Alert")

    with st.form("new_alert", border=False):
        r1c1, r1c2 = st.columns(2)
        dest_iata = r1c1.text_input("Destination IATA", placeholder="LHR").upper()
        alert_type = r1c2.selectbox("Alert type", ["cash", "points", "both"])

        r2c1, r2c2, r2c3 = st.columns(3)
        max_cash  = r2c1.number_input("Max cash ($)", 0, 9999, 500)
        max_pts   = r2c2.number_input("Max points", 0, 999999, 60000, step=5000)
        cabin_al  = r2c3.selectbox("Cabin", ["economy", "business", "first"])

        prog_slug = st.text_input("Program slug (for points alerts)", placeholder="chase_ur  or  delta_skymiles")

        if st.form_submit_button("Create Alert", use_container_width=True):
            payload = {
                "destination_iata": dest_iata,
                "alert_type": alert_type,
                "max_cash_price": max_cash if alert_type in ("cash","both") else None,
                "max_points":     max_pts  if alert_type in ("points","both") else None,
                "cabin_class":    cabin_al,
                "program_slug":   prog_slug or None,
            }
            try:
                r = requests.post(f"{API_BASE}/alerts", json=payload, timeout=4)
                r.raise_for_status()
                st.toast(f"Alert created for {dest_iata}", icon="🔔")
                st.rerun()
            except Exception as e:
                st.error(str(e))


# ── Destinations ──────────────────────────────────────────────────────────────
with tab_dests:
    try:
        dests_data = requests.get(f"{API_BASE}/destinations", timeout=4).json()
    except Exception:
        dests_data = []
        st.warning("API server not running — start it with `python main.py --serve`")

    if dests_data:
        active   = [d for d in dests_data if d["is_active"]]
        paused   = [d for d in dests_data if not d["is_active"]]

        section_label(f"{len(active)} active · {len(paused)} paused")

        cols = st.columns(3)
        for i, d in enumerate(dests_data):
            col = cols[i % 3]
            active_color = THEME["green"] if d["is_active"] else THEME["text_muted"]
            active_bg    = "#f0fdf4" if d["is_active"] else THEME["card"]
            active_border= "rgba(5,150,105,0.25)" if d["is_active"] else THEME["border"]
            label        = "Pause" if d["is_active"] else "Activate"

            with col:
                st.markdown(f"""
                <div style="background:{active_bg}; border:1px solid {active_border};
                            border-radius:14px; padding:18px 20px; margin-bottom:12px;
                            box-shadow:0 1px 4px rgba(0,0,0,0.05);">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <div>
                            <div style="font-size:15px; font-weight:700; color:{THEME['text']}; margin-bottom:4px;">
                                {d['name']}
                            </div>
                            <div style="font-size:12px; color:{THEME['text_muted']};">
                                {d['iata_code']}  ·  {d.get('region') or '—'}
                            </div>
                        </div>
                        <div style="width:8px; height:8px; border-radius:50%;
                                    background:{active_color}; margin-top:4px;
                                    {'box-shadow:0 0 8px ' + THEME['green'] + ';' if d['is_active'] else ''}">
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                if st.button(label, key=f"tog_{d['id']}", use_container_width=True):
                    requests.patch(f"{API_BASE}/destinations/{d['id']}/toggle", timeout=4)
                    st.rerun()
