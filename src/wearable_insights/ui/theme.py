"""Infocusp dark-blue theme — palette tokens, logo, and global CSS injection.

The palette mirrors the company demo (``infocusp_wearable_demo_v2.html``) so the
Streamlit dashboard reads as the same product. All visual constants live here so
components/charts import one source of truth.
"""

from __future__ import annotations

import streamlit as st

# ── Palette (from the demo :root) ───────────────────────────────────────────────
GROUND = "#0D1E45"
SURFACE = "#132450"
SURFACE2 = "#1A2D5A"
TOPBAR = "#091733"
BORDER = "#1E3160"
BORDER2 = "#253D6E"
TEXT = "#EDF2FF"
TEXT2 = "#94A8D4"
TEXT3 = "#5C7AAA"
ACCENT = "#00C6FF"
COBALT = "#3B6FD6"

# Status colors (dark-mode friendly), reused by badges/cards/charts.
OK = "#4ade80"
WARN = "#fcd34d"
CRIT = "#fca5a5"
OK_BG = "rgba(34,197,94,.18)"
WARN_BG = "rgba(245,158,11,.18)"
CRIT_BG = "rgba(239,68,68,.18)"

# Chart series colors (sleep stages / activity), mirrored from the demo.
SLEEP_DEEP = "#6366f1"
SLEEP_REM = "#3b82f6"
SLEEP_LIGHT = "#60a5fa"
SLEEP_AWAKE = "#334d7a"
GOAL_MET = "#22c55e"

# ── Infocusp logo (inline SVG, scalable, no file dependency) ────────────────────
LOGO_SVG = (
    '<svg viewBox="0 0 26.343 26.898" fill="none" '
    'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Infocusp logo">'
    '<path d="M0 13.2206L13.1714 26.8972V13.2206H0Z" fill="#1F5AD0"/>'
    '<path d="M0 13.2206L13.1714 17.7795V13.2206H0Z" fill="#193782"/>'
    '<path d="M12.9138 0H0.000244141V13.2207H12.9138H26.343L12.9138 0Z" fill="#00C6FF"/>'
    "</svg>"
)


def _css() -> str:
    return f"""
<style>
/* ── App shell ───────────────────────────────────────────────────────────── */
.stApp {{ background: {GROUND}; }}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 1.2rem; padding-bottom: 280px; }}

/* Sidebar */
[data-testid="stSidebar"] {{
  background: {TOPBAR};
  border-right: 1px solid {BORDER};
}}

/* Expanders look like the demo's cards */
[data-testid="stExpander"] details {{
  background: {SURFACE};
  border: 1px solid {BORDER};
  border-radius: 12px;
}}
[data-testid="stExpander"] summary {{ color: {TEXT}; font-weight: 600; }}

/* Dividers a touch darker */
hr {{ border-color: {BORDER}; }}

/* ── Topbar (header) ─────────────────────────────────────────────────────── */
.ic-topbar {{
  position: relative; display: flex; align-items: center; gap: 12px;
  padding: 12px 18px; background: {TOPBAR};
  border: 1px solid {BORDER}; border-radius: 12px; overflow: hidden;
  margin-bottom: 14px;
}}
.ic-topbar::after {{
  content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, transparent, {ACCENT}, transparent);
  background-size: 300% 100%; animation: ic-scan 3s ease-in-out infinite;
}}
@keyframes ic-scan {{ 0%,100% {{ background-position: -100% 0; }} 50% {{ background-position: 100% 0; }} }}
@media (prefers-reduced-motion: reduce) {{ .ic-topbar::after {{ animation: none; opacity: .4; }} }}
.ic-logo {{
  width: 40px; height: 40px; border-radius: 9px; flex-shrink: 0; padding: 4px;
  background: #fff; border: 1.5px solid rgba(0,198,255,.35);
  display: flex; align-items: center; justify-content: center;
}}
.ic-logo svg {{ width: 100%; height: 100%; }}
.ic-logo-name {{ font-size: 17px; font-weight: 700; color: #fff; letter-spacing: -.01em; line-height: 1.1; }}
.ic-logo-tag {{ font-size: 10px; color: rgba(0,198,255,.85); display: block; margin-top: 2px;
  letter-spacing: .06em; text-transform: uppercase; }}
.ic-topbar-right {{ margin-left: auto; display: flex; align-items: center; gap: 12px; }}
.ic-live {{ display: flex; align-items: center; gap: 6px; font-size: 11px; color: {ACCENT};
  font-weight: 700; letter-spacing: .05em; }}
.ic-live-dot {{ width: 7px; height: 7px; border-radius: 50%; background: {ACCENT};
  box-shadow: 0 0 7px {ACCENT}; animation: ic-blink 1.4s infinite; }}
@keyframes ic-blink {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: .25; }} }}
.ic-user-chip {{ display: flex; align-items: center; gap: 9px; font-size: 12px;
  padding: 5px 12px 5px 5px; border-radius: 22px; background: rgba(0,198,255,.10);
  border: 1px solid rgba(0,198,255,.28); color: {TEXT2}; }}
.ic-user-chip img {{ width: 30px; height: 30px; border-radius: 50%; object-fit: cover;
  border: 1px solid rgba(0,198,255,.4); }}
.ic-user-chip b {{ color: {TEXT}; font-weight: 600; }}

/* ── Profile card ────────────────────────────────────────────────────────── */
.ic-profile {{ display: flex; align-items: center; gap: 14px; background: {SURFACE};
  border: 1px solid {BORDER}; border-radius: 12px; padding: 12px 14px; margin-bottom: 6px; }}
.ic-profile img {{ width: 56px; height: 56px; border-radius: 50%; object-fit: cover;
  border: 2px solid rgba(0,198,255,.4); flex-shrink: 0; }}
.ic-profile-name {{ font-size: 16px; font-weight: 700; color: {TEXT}; }}
.ic-profile-meta {{ font-size: 12px; color: {TEXT2}; margin-top: 2px; line-height: 1.6; }}

/* ── Signal cards ────────────────────────────────────────────────────────── */
.ic-sig-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }}
.ic-sig-card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
  padding: 11px 13px; transition: border-color .2s; }}
.ic-sig-card:hover {{ border-color: {BORDER2}; }}
.ic-sig-top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 5px; }}
.ic-sig-lbl {{ font-size: 10px; color: {TEXT3}; text-transform: uppercase; letter-spacing: .05em; font-weight: 600; }}
.ic-sig-dot {{ width: 7px; height: 7px; border-radius: 50%; }}
.ic-sig-val {{ font-size: 23px; font-weight: 700; color: {TEXT}; line-height: 1.1;
  font-variant-numeric: tabular-nums; }}
.ic-sig-unit {{ font-size: 11px; color: {TEXT3}; font-weight: 400; }}
.ic-sig-trend {{ font-size: 10px; margin-top: 3px; font-weight: 600; }}

/* ── Badges / pills ──────────────────────────────────────────────────────── */
.ic-badge {{ font-size: .78em; padding: 3px 10px; border-radius: 10px; font-weight: 700;
  letter-spacing: .02em; white-space: nowrap; }}

/* ── Footer ──────────────────────────────────────────────────────────────── */
.ic-footer {{ position: fixed; bottom: 0; left: 0; right: 0; border-top: 1px solid {BORDER};
  background: {TOPBAR}; z-index: 100; padding: 16px 18px; margin: 0; }}
.ic-footer-inner {{ display: flex; flex-wrap: wrap; align-items: flex-start; gap: 14px; max-width: 1400px; margin: 0 auto; width: 100%; padding: 0 18px; box-sizing: border-box; }}
.ic-footer-brand {{ display: flex; align-items: center; gap: 9px; flex-shrink: 0; }}
.ic-footer-logo {{ width: 28px; height: 28px; border-radius: 6px; padding: 3px; background: #fff;
  border: 1px solid rgba(0,198,255,.3); flex-shrink: 0; }}
.ic-footer-logo svg {{ width: 100%; height: 100%; }}
.ic-footer-name {{ font-size: 13px; font-weight: 700; color: {TEXT2}; letter-spacing: -.01em; }}
.ic-footer-info {{ flex: 1; min-width: 200px; font-size: 11px; color: {TEXT3}; line-height: 1.9; }}
.ic-footer-info a {{ color: {ACCENT}; text-decoration: none; border-bottom: 1px solid rgba(0,198,255,.25); }}
.ic-footer-info a:hover {{ border-color: {ACCENT}; }}
.ic-footer-disc {{ width: 100%; padding-top: 10px; border-top: 1px solid {BORDER};
  font-size: 9px; color: {TEXT3}; letter-spacing: .02em; line-height: 1.6; margin-top: 4px; }}

/* Section label like the demo's .sec-title */
.ic-sec {{ font-size: 10px; font-weight: 700; color: {TEXT3}; text-transform: uppercase;
  letter-spacing: .1em; padding-left: 8px; border-left: 2px solid {ACCENT}; margin: 6px 0 4px; }}
</style>
"""


def inject_theme() -> None:
    """Inject the global Infocusp CSS. Call once near the top of ``main()``."""
    st.markdown(_css(), unsafe_allow_html=True)
