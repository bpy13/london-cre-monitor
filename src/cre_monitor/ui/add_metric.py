"""Dashboard > Metrics > "Add a metric" panel (filled in by the add-metric assessment step)."""

from __future__ import annotations

import streamlit as st


def add_metric_panel() -> None:
    st.markdown("**➕ Add a metric**")
    st.caption("Coming next: describe a metric and Claude checks whether the current skills can collect it.")
