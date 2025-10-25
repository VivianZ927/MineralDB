import pickle
from typing import Dict, Any, Tuple, List

from dash import Dash, html, dash_table, dcc, callback, Output, Input
import pandas as pd
import plotly.express as px
from pandas.api.types import is_timedelta64_dtype

# =========================
# Config
# =========================
PICKLE_PATH = "ea26Top20.pkl"
DEFAULT_MINERAL = "Magnesium"
TOP_K = 5
VALUE_COL = "monthly concentration"
AVG_COL = "average monthly concentration"

UK_GEO = dict(
    scope="europe",
    projection_type="mercator",
    center=dict(lat=54.5, lon=-3.0),
    lonaxis=dict(range=[-11, 3]),
    lataxis=dict(range=[49, 60]),
    showcountries=True,
    showland=True,
)


# =========================
# Data loading & preprocessing
# =========================
def get_top(base: Dict[str, Dict[str, pd.DataFrame]], k: int) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    For each mineral (key), each sub-df (e.g., 'Total', etc.), keep rows
    belonging to the top-k (Sampling Point, Type) groups by mean concentration.
    """
    basic_cols = ["Sampling Point", "lat", "long", "Type", "YearMonth"]
    gb = ["Sampling Point", "lat", "long", "Type"]
    out: Dict[str, Dict[str, pd.DataFrame]] = {}

    for mineral, sub in base.items():
        sub_out: Dict[str, pd.DataFrame] = {}
        for name, df in sub.items():
            # Compute per-(Sampling Point, Type) mean once
            means = (
                df.groupby(gb, as_index=False)[VALUE_COL]
                  .mean()
                  .rename(columns={VALUE_COL: AVG_COL})
            )
            # Top-k groups by mean
            top_keys = means.nlargest(k, AVG_COL)[gb]

            # Keep rows from those groups + attach the mean
            keep = df.merge(top_keys.assign(_keep=1), on=gb, how="inner")
            keep = keep.merge(means, on=gb, how="left", suffixes=(None, "_y"))

            # Select standard columns
            keep = keep[basic_cols + [VALUE_COL, AVG_COL]].copy()
            sub_out[name] = keep
        out[mineral] = sub_out
    return out


def get_minerals(dfs: Dict[str, Any]) -> List[str]:
    return list(dfs.keys())


# =========================
# Dtype helpers (no is_period_dtype)
# =========================
# Use isinstance on dtype/array types; fall back to string check.
try:
    from pandas import PeriodDtype
except Exception:  # pragma: no cover
    PeriodDtype = type("PeriodDtypeMissing", (), {})  # fallback

try:
    from pandas.arrays import PeriodArray
except Exception:  # pragma: no cover
    PeriodArray = type("PeriodArrayMissing", (), {})

try:
    from pandas import DatetimeTZDtype
except Exception:  # pragma: no cover
    DatetimeTZDtype = type("DatetimeTZDtypeMissing", (), {})


def _series_is_period(s: pd.Series) -> bool:
    dt = getattr(s, "dtype", None)
    return (
        isinstance(dt, PeriodDtype)
        or isinstance(getattr(s, "array", None), PeriodArray)
        or str(dt).startswith("period[")
    )


def _series_is_tzaware_datetime(s: pd.Series) -> bool:
    return isinstance(getattr(s, "dtype", None), DatetimeTZDtype)


def _series_is_timedelta(s: pd.Series) -> bool:
    dt = getattr(s, "dtype", None)
    return is_timedelta64_dtype(s) or getattr(dt, "kind", "") == "m"


def sanitize_base(base: Dict[str, Dict[str, pd.DataFrame]]) -> None:
    """
    In-place: convert non-JSON-serializable types so Plotly/Dash can serialize.
      - PeriodIndex -> Timestamp index
      - Period series -> Timestamp (if time-like name) else str
      - tz-aware datetimes -> naive UTC
      - timedelta -> seconds (float)
    """
    for _, sub in base.items():
        for _, df in sub.items():
            # Index
            if isinstance(df.index, pd.PeriodIndex):
                df.index = df.index.to_timestamp()

            # Columns
            for col in list(df.columns):
                s = df[col]
                try:
                    if _series_is_period(s):
                        if col.lower() in ("yearmonth", "time", "month", "period", "date"):
                            df[col] = s.dt.to_timestamp()
                        else:
                            df[col] = s.astype(str)
                    elif _series_is_tzaware_datetime(s):
                        df[col] = s.dt.tz_convert("UTC").dt.tz_localize(None)
                    elif _series_is_timedelta(s):
                        df[col] = (s.astype("int64") / 1e9)  # seconds
                except Exception:
                    # Safety: never fail at import/startup
                    pass


# =========================
# Figure / table builders
# =========================
def build_geo_fig(point_agg: Dict[str, Dict[str, pd.DataFrame]], mineral: str, k: int):
    df = point_agg[mineral]["Total"].copy()

    # Drop potential troublemaker used by other charts
    df = df.drop(columns=["YearMonth"], errors="ignore")

    # Keep only the columns used by the chart to minimize JSON
    cols = ["Sampling Point", "lat", "long", "Type", AVG_COL]
    df = df[cols]

    fig = px.scatter_geo(
        df,
        lat="lat",
        lon="long",
        color="Sampling Point",
        hover_name="Sampling Point",
        size=AVG_COL,
        opacity=0.5,
        hover_data={"Type": True, AVG_COL: ":.2f"},
    )
    fig.update_layout(geo=UK_GEO, title=f"UK — {mineral} Distribution (Top {k} Sites)")
    return fig


def build_dot_fig(month_agg: Dict[str, Dict[str, pd.DataFrame]], mineral: str):
    figures = []
    for name, d in month_agg[mineral].items():
        df = d.copy()
        df.rename(columns={VALUE_COL: "Detected Concentration", "YearMonth": "Time"}, inplace=True)

        if "Time" in df.columns:
            dtype_str = str(getattr(df["Time"], "dtype", ""))
            if isinstance(getattr(df["Time"], "dtype", None), PeriodDtype) or dtype_str.startswith("period["):
                df["Time"] = df["Time"].dt.to_timestamp()

        ymin = df["Detected Concentration"].min()
        ymax = df["Detected Concentration"].max()

        fig = px.scatter(
            df,
            x="Time",
            y="Detected Concentration",
            color="Sampling Point",
            symbol="Sampling Point",
            title=f"Concentration of {name}",
        )

        if pd.notna(ymin) and pd.notna(ymax):
            pad = max(1.0, 0.05 * (ymax - ymin) if ymax > ymin else 1.0)
            fig.update_layout(yaxis_range=[ymin - pad, ymax + pad])

        fig.update_traces(marker=dict(size=12))
        figures.append(fig)
    return figures


def build_table_data(point_agg: Dict[str, Dict[str, pd.DataFrame]], mineral: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build small tables for display. We format numbers early (reduces JSON size).
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for name, df in point_agg[mineral].items():
        label = name if "Total" not in name else "Total Detected Concentration"

        tbl = (
            df[["Sampling Point", "Type", AVG_COL]]
            .drop_duplicates()
            .sort_values(by=[AVG_COL], ascending=False)
            .copy()
        )
        tbl[AVG_COL] = tbl[AVG_COL].map(lambda x: f"{x:.2f}")
        tbl.rename(columns={AVG_COL: "MonthlyMean"}, inplace=True)
        out[label] = tbl.to_dict("records")
    return out


def build_chart_table(initial_table: Dict[str, List[Dict[str, Any]]], initial_dot):
    table_divs = []
    dot_graphs = []

    for label, rows in initial_table.items():
        table_divs.append(
            html.Div(
                children=[
                    html.Div([f"Top {TOP_K} {label}"], style={"margin": 8, "fontSize": 12, "fontWeight": "bold"}),
                    dash_table.DataTable(
                        data=rows,
                        style_cell={
                            "fontSize": 12,
                            "textAlign": "left",
                            "whiteSpace": "normal",
                            "height": "auto",
                        },
                    ),
                ]
            )
        )

    for fig in initial_dot:
        dot_graphs.append(dcc.Graph(figure=fig, style={"padding": 10, "width": "70%"}))

    return table_divs, dot_graphs


# =========================
# Dash app
# =========================
app = Dash(title="Mineral Analysis")
server = app.server

# Load serialized data
with open(PICKLE_PATH, "rb") as f:
    raw_base = pickle.load(f)

BASE = get_top(raw_base, TOP_K)
sanitize_base(BASE)

minerals = get_minerals(BASE)
if DEFAULT_MINERAL not in minerals and minerals:
    DEFAULT_MINERAL = minerals[0]

# Initial artifacts
initial_geo = build_geo_fig(BASE, DEFAULT_MINERAL, k=TOP_K)
initial_dot = build_dot_fig(BASE, DEFAULT_MINERAL)
initial_table = build_table_data(BASE, DEFAULT_MINERAL)
table_list, dot_charts = build_chart_table(initial_table, initial_dot)

app.layout = html.Div(
    [
        html.Div(
            [
                html.Div(
                    [
                        html.H1(
                            "UK Mineral Analysis Dashboard",
                            style={"margin": 0, "fontSize": "24px", "fontWeight": 1000},
                        ),
                        html.Img(src=app.get_asset_url("logo.png"), style={"height": "70px"}),
                    ],
                    style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "alignItems": "center",
                        "padding": "12px 16px",
                        "backgroundColor": "white",
                        "color": "#499823",
                        "position": "sticky",
                        "top": 0,
                        "zIndex": 999,
                    },
                ),
                html.Hr(),
                html.Div(
                    children=[
                        html.H4("Mineral to be analysed:"),
                        dcc.Dropdown(minerals, DEFAULT_MINERAL, id="mineral-dropdown", clearable=False),
                    ],
                    style={"padding": 10, "flex": 1},
                ),
                html.Div(
                    children=table_list,
                    id="mineral-table",
                    style={
                        "display": "flex",
                        "flexDirection": "row",
                        "gap": "10px",
                        "justifyContent": "space-between",
                        "width": "100%",
                    },
                ),
                html.Div(children=dot_charts, id="mineral-dot-chart"),
                html.Div([dcc.Graph(figure=initial_geo, id="mineral-geoscatter-chart")]),
            ]
        )
    ]
)


# =========================
# Callback
# =========================
@callback(
    Output("mineral-dot-chart", "children"),
    Output("mineral-table", "children"),
    Output("mineral-geoscatter-chart", "figure"),
    Input("mineral-dropdown", "value"),
)
def update_all(chosen_mineral: str) -> Tuple[List[Any], List[Any], Any]:
    geo_fig = build_geo_fig(BASE, chosen_mineral, k=TOP_K)
    dot_figs = build_dot_fig(BASE, chosen_mineral)
    table_data = build_table_data(BASE, chosen_mineral)
    tables, dots = build_chart_table(table_data, dot_figs)
    return dots, tables, geo_fig


if __name__ == "__main__":
    # In production, Gunicorn will run this module, so debug=False is fine here
    app.run(debug=False)
