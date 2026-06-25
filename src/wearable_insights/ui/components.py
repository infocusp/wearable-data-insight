"""Branded UI components — header, footer, profile card, signal cards, badges.

Pure presentation. These build HTML strings styled by the CSS in ``theme.py`` and
render them via ``st.markdown(..., unsafe_allow_html=True)``.
"""

from __future__ import annotations

import base64
from datetime import date
from functools import lru_cache
from pathlib import Path

import streamlit as st

from wearable_insights.config import DISCLAIMER
from wearable_insights.ui import theme

_AVATAR_DIR = Path(__file__).resolve().parent.parent / "assets" / "avatars"


@lru_cache(maxsize=32)
def _avatar_data_uri(filename: str | None) -> str:
    """Return a base64 ``data:`` URI for an avatar so it can be inlined in HTML."""
    path = _AVATAR_DIR / (filename or "default.svg")
    if not path.exists():
        path = _AVATAR_DIR / "default.svg"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def _identity_bits(profile_dict: dict) -> list[str]:
    bits: list[str] = []
    age = profile_dict.get("age")
    gender = profile_dict.get("gender")
    if age:
        bits.append(str(age))
    if gender and gender != "Non-specified":
        bits.append(gender)
    return bits


# ── Header / footer ─────────────────────────────────────────────────────────────

def render_header(profile_dict: dict | None = None) -> None:
    """Infocusp topbar: logo + product name + Live badge + (optional) profile chip."""
    chip = ""
    if profile_dict:
        name = profile_dict.get("display_name") or profile_dict.get("user_id", "User")
        sub = " · ".join(_identity_bits(profile_dict))
        uri = _avatar_data_uri(profile_dict.get("avatar"))
        sub_html = f" · {sub}" if sub else ""
        chip = (
            f'<div class="ic-user-chip"><img src="{uri}" alt="avatar"/>'
            f"<span><b>{name}</b>{sub_html}</span></div>"
        )

    html = (
        '<div class="ic-topbar">'
        f'<div class="ic-logo">{theme.LOGO_SVG}</div>'
        '<div><div class="ic-logo-name">Infocusp</div>'
        '<span class="ic-logo-tag">Wearable Health AI</span></div>'
        '<div class="ic-topbar-right">'
        '<div class="ic-live"><span class="ic-live-dot"></span>Live</div>'
        f"{chip}</div></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def render_footer() -> None:
    """Infocusp footer: brand, address, link, and the informational disclaimer."""
    html = (
        '<div class="ic-footer"><div class="ic-footer-inner">'
        '<div class="ic-footer-brand">'
        f'<div class="ic-footer-logo">{theme.LOGO_SVG}</div>'
        '<span class="ic-footer-name">Infocusp</span></div>'
        '<div class="ic-footer-info">'
        "<div>© 2025 Infocusp Innovations Pvt. Ltd. All rights reserved.</div>"
        "<div>Ahmedabad, Gujarat, India &nbsp;·&nbsp; "
        '<a href="https://www.infocusp.com/" target="_blank" rel="noopener noreferrer">'
        "www.infocusp.com</a></div></div>"
        f'<div class="ic-footer-disc">For demonstration purposes only — not a medical '
        f"device. {DISCLAIMER}</div>"
        "</div></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def render_profile_card(profile_dict: dict, analysis_date: date) -> None:
    """Dashboard profile card: photo + name + DOB/age/gender + analysis context."""
    name = profile_dict.get("display_name") or profile_dict.get("user_id", "User")
    uri = _avatar_data_uri(profile_dict.get("avatar"))
    bits = _identity_bits(profile_dict)
    dob = profile_dict.get("dob")
    if dob:
        bits.append(f"DOB {dob}")
    n_records = len(profile_dict.get("records", []))
    meta1 = " · ".join(bits) if bits else profile_dict.get("user_id", "")
    meta2 = f"Analysis date {analysis_date.isoformat()} · {n_records} days history"

    html = (
        '<div class="ic-profile">'
        f'<img src="{uri}" alt="avatar"/>'
        f'<div><div class="ic-profile-name">{name}</div>'
        f'<div class="ic-profile-meta">{meta1}<br>{meta2}</div></div>'
        "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ── Signal cards ────────────────────────────────────────────────────────────────

_STATUS_COLOR = {
    "ok": theme.OK,
    "warn": theme.WARN,
    "crit": theme.CRIT,
    "neutral": theme.TEXT3,
}


def signal_card_html(
    label: str,
    value: str,
    unit: str = "",
    status: str = "neutral",
    trend: str = "",
) -> str:
    """Return one ``.ic-sig-card`` HTML string (compose many via ``render_signal_grid``)."""
    color = _STATUS_COLOR.get(status, theme.TEXT3)
    unit_html = f' <span class="ic-sig-unit">{unit}</span>' if unit else ""
    trend_html = (
        f'<div class="ic-sig-trend" style="color:{color}">{trend}</div>' if trend else ""
    )
    return (
        '<div class="ic-sig-card">'
        f'<div class="ic-sig-top"><span class="ic-sig-lbl">{label}</span>'
        f'<span class="ic-sig-dot" style="background:{color};box-shadow:0 0 6px {color}"></span>'
        "</div>"
        f'<div class="ic-sig-val">{value}{unit_html}</div>'
        f"{trend_html}</div>"
    )


def render_signal_grid(cards: list[str]) -> None:
    """Render a responsive grid of signal-card HTML strings."""
    st.markdown(
        '<div class="ic-sig-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


def section_label(text: str) -> None:
    """Small accent-bordered section label (demo's ``.sec-title``)."""
    st.markdown(f'<div class="ic-sec">{text}</div>', unsafe_allow_html=True)


# ── Badges / deltas (dark-mode palette) ──────────────────────────────────────────

_TAG_STYLE: dict[str, tuple[str, str]] = {
    "Stable / Within Normal Baseline": (theme.OK_BG, theme.OK),
    "Significantly Elevated":          (theme.WARN_BG, theme.WARN),
    "Significantly Depressed":         ("rgba(59,130,246,.18)", "#93c5fd"),
    "Critically Elevated":             (theme.CRIT_BG, theme.CRIT),
    "Critically Depressed":            ("rgba(239,68,68,.24)", "#f8b4b4"),
}

_TREND_ICON = {"up": "↑", "down": "↓", "stable": "→"}


def tag_badge(tag: str) -> str:
    bg, fg = _TAG_STYLE.get(tag, ("rgba(148,168,212,.15)", theme.TEXT2))
    return f'<span class="ic-badge" style="background:{bg};color:{fg}">{tag}</span>'


def fmt_delta(pct: float | None, trend: str) -> str:
    icon = _TREND_ICON.get(trend, "→")
    if pct is None:
        return f'<span style="color:{theme.TEXT3}">{icon} —</span>'
    sign = "+" if pct > 0 else ""
    color = theme.OK if abs(pct) < 15 else theme.WARN if abs(pct) < 50 else theme.CRIT
    return f'<span style="color:{color};font-weight:700">{icon} {sign}{pct:.0f}%</span>'
