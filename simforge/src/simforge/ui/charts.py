"""Charts (Altair, bundled with Streamlit). Palette: validated categorical slots 1-5,
fixed order per state; every chart is paired with a table view in the UI."""

from __future__ import annotations

import altair as alt
import pandas as pd

from ..engine.base import NodeState

STATE_COLORS = {  # fixed order: colour follows the state, never the rank
    NodeState.BUSY: "#2a78d6",
    NodeState.WAITING_RESOURCE: "#eb6834",
    NodeState.BLOCKED: "#1baf7a",
    NodeState.STARVED: "#eda100",
    NodeState.DOWN: "#e87ba4",
}
STATE_LABELS = {NodeState.BUSY: "Busy", NodeState.WAITING_RESOURCE: "Waiting resource", NodeState.BLOCKED: "Blocked",
                NodeState.STARVED: "Starved", NodeState.DOWN: "Down"}


def station_states(df: pd.DataFrame) -> alt.Chart:
    """df: columns station, state, fraction."""
    order = list(STATE_LABELS.values())
    return (
        alt.Chart(df)
        .mark_bar(stroke="white", strokeWidth=2)
        .encode(
            y=alt.Y("station:N", sort=None, title=None, scale=alt.Scale(paddingInner=0.35)),
            x=alt.X("fraction:Q", stack="zero", axis=alt.Axis(format="%", grid=True, gridOpacity=0.3), title="Share of time",
                    scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("state:N", scale=alt.Scale(domain=order, range=[STATE_COLORS[s] for s in STATE_LABELS]),
                            legend=alt.Legend(orient="top", title=None)),
            order=alt.Order("order:Q"),
            tooltip=["station", "state", alt.Tooltip("fraction:Q", format=".1%")],
        )
        .properties(height=alt.Step(40))
    )


def wip_series(t_h: list[float], wip: list[float]) -> alt.Chart:
    df = pd.DataFrame({"time_h": t_h, "wip": wip})
    return (
        alt.Chart(df).mark_line(interpolate="step-after", strokeWidth=2, color="#2a78d6")
        .encode(x=alt.X("time_h:Q", title="Time (h)"), y=alt.Y("wip:Q", title="WIP (units)"),
                tooltip=[alt.Tooltip("time_h:Q", format=".2f"), "wip:Q"])
        .properties(height=220)
    )


def experiment_line(df: pd.DataFrame, x: str, y: str, y_title: str) -> alt.Chart:
    """df columns: x, mean, lo, hi (lo/hi may be NaN for deterministic runs)."""
    base = alt.Chart(df).encode(x=alt.X(f"{x}:Q", title=x, axis=alt.Axis(tickMinStep=1)))
    line = base.mark_line(strokeWidth=2, color="#2a78d6")
    pts = base.mark_circle(size=70, color="#2a78d6", stroke="white", strokeWidth=2).encode(
        y=alt.Y("mean:Q", title=y_title, scale=alt.Scale(zero=False)),
        tooltip=[x, alt.Tooltip("mean:Q", format=".3f"), alt.Tooltip("lo:Q", format=".3f"), alt.Tooltip("hi:Q", format=".3f")])
    layers = [line.encode(y="mean:Q"), pts]
    if df["lo"].notna().any():
        layers.insert(0, base.mark_errorbar(color="#6da7ec").encode(y=alt.Y("lo:Q", title=y_title), y2="hi:Q"))
    return alt.layer(*layers).properties(height=260)
