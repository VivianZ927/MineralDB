import re
from copy import copy

from dash import Dash, html, dash_table, dcc, callback, Output, Input
import pandas as pd
import plotly.express as px

# ---------- Config ----------
CSV_PATH = "ea26.csv"
DEFAULT_MINERAL = "Magnesium"  # default selection
UK_GEO = dict(
    scope="europe",
    projection_type="mercator",
    center=dict(lat=54.5, lon=-3.0),
    lonaxis=dict(range=[-11, 3]),
    lataxis=dict(range=[49, 60]),
    showcountries=True,
    showland=True,
)


# ---------- Load & Preprocess (static) ----------

# Base filter: drop groups with only 1 sample; drop rows without lat/lon
# (Do once at start; all callbacks reuse this.)

def get_minerals(df):
    cols_total = [c for c in df.columns if
                  re.search(r"\(ug/l\)|\(mg/l\)", c) and "Total" not in c and ("," not in c and ":" not in c)]
    minerals = []
    for c in cols_total:
        words = c.split()
        if "as" in words:
            idx = words.index("as")
            mineral = (" ").join(words[:idx])
            minerals.append(mineral)
        else:
            minerals.append(words[0])

    return minerals


BASE = pd.read_csv(CSV_PATH)
minerals = get_minerals(BASE)
if DEFAULT_MINERAL not in minerals and len(minerals) > 0:
    DEFAULT_MINERAL = minerals[0]


# df['YearMonth'] = pd.to_datetime(df['YearMonth'], format='%Y-%m', errors='coerce')
# df['Year'] = df['YearMonth'].dt.year
# df = df[df["Year"] == 2025]

# BASE = build_base(df)


# ---------- Helpers ----------
def select_topk_pairs(base, mineral, k):
    """
    Pick the top-K (Sampling Point, Type) pairs by mean(mineral), then
    return a filtered DataFrame with only those pairs (all rows for those pairs).
    """
    matched_mineral_cols = base.filter(like=mineral, axis=1).columns
    mm = matched_mineral_cols.tolist()

    basic_cols = ["Sampling Point", "Type", "YearMonth", "lat", "long"]
    basic_cols.extend(mm)

    Filtered_Base = base.loc[:, basic_cols].copy()  # explicit copy
    if mm:  # optional guard in case mm is empty
        Filtered_Base = Filtered_Base.dropna(subset=mm, how="all")

    if len(mm) > 1:
        Filtered_Base["Total"] = base[mm].sum(axis=1, min_count=1)
        mm.extend(["Total"])
    gb = ["Sampling Point", "lat", "long", "Type"]
    keep_cols = gb + ["YearMonth"]

    out = {}
    for m in mm:
        cols = copy(keep_cols)
        cols.append(m)
        fb = copy(Filtered_Base[cols])
        fb.dropna(subset=m, how="all", inplace=True)
        # 1) Per-(Sampling Point, Type) average for this metric
        means_df = (fb.groupby(gb, as_index=False)[m]
                    .mean()
                    .rename(columns={m: "average monthly concentration"}))
        # 2) Top-5 groups for this metric
        top_keys = means_df.nlargest(k, "average monthly concentration")[gb]
        # 3) Keep only rows from those top-5 groups and attach the average
        tmp = Filtered_Base.merge(top_keys.assign(_keep=1), on=gb, how="inner").merge(means_df, on=gb, how="left")
        # 4) Select the columns you want and standardize names
        tmp = tmp[keep_cols + [m, "average monthly concentration"]].copy()

        tmp = tmp.rename(columns={m: "monthly concentration"})
        out[m] = tmp

    return out

def build_geo_fig(point_agg, mineral, k):
    total_point_agg = point_agg["Total"]
    fig = px.scatter_geo(
        total_point_agg,
        color="Sampling Point",
        lat="lat",
        lon="long",
        hover_name="Sampling Point",
        size="average monthly concentration",
        # projection="natural earth",
        opacity=0.5
    )
    fig.update_layout(
        geo=UK_GEO,
        title="UK — {} Distribution (Top {} Sites)".format(mineral, k))
    return fig


def build_dot_fig(month_agg, mineral):
    figures = []
    for m, d in month_agg.items():
        d.rename(columns={"monthly concentration": "Detected Concentration", "YearMonth": "Time"}, inplace=True)
        mineral_col = m
        # Safe padding even if all equal
        ymin = d["Detected Concentration"].min()
        ymax = d["Detected Concentration"].max()
        fig = px.scatter(
            d,
            x="Time",
            y="Detected Concentration",
            color="Sampling Point",
            symbol="Sampling Point",
            title=f"Concentration of {mineral_col}",
        )
        # else:
        #     label = "Total " + mineral
        #     fig = px.scatter(
        #         df,
        #         x="Time",
        #         y="Detected Concentration",
        #         color="Sampling Point",
        #         symbol="Sampling Point",
        #         title=f"Concentration of {label}",
        #     )

        if pd.isna(ymin) or pd.isna(ymax):
            pass
        else:
            pad = max(1.0, 0.05 * (ymax - ymin) if ymax > ymin else 1.0)
            fig.update_layout(yaxis_range=[ymin - pad, ymax + pad])
        fig.update_traces(marker=dict(size=12))
        figures.append(fig)
    return figures


def build_table_data(point_agg):
    # Only return the columns needed in the table
    tbs = {}

    for m, d in point_agg.items():

        if "Total" not in m:
            label = m
        else:
            label = "Total Detected Concentration"
        tbl = d[["Sampling Point", "Type", 'average monthly concentration']].sort_values(by=['average monthly '
                                                                                             'concentration'],
                                                                                         ascending=False)
        tbl = tbl.drop_duplicates()
        tbl['average monthly concentration'] = tbl['average monthly concentration'].map(lambda x: f"{x:.2f}")
        tbl.rename(columns={'average monthly concentration': "MonthlyMean"}, inplace=True)
        tbs[label] = tbl.to_dict("records")
    return tbs


def build_chart_table(initial_table, initial_dot):
    table_list = []
    Dot_Charts = []
    # if len(initial_table) > 1:
    for k, v in initial_table.items():
        table_list.append(
            html.Div(children=[
                html.Div(["Top 5 {}".format(k)],
                         style={"margin": 8, 'fontSize': 12, "fontWeight": "bold"}),
                dash_table.DataTable(data=v,
                                     style_cell={'fontSize': 12,
                                                 "textAlign": "left",  # align text to the left

                                                 "whiteSpace": "normal",  # allow wrapping
                                                 "height": "auto",  # adjust row height
                                                 },
                                     )
            ])
        )

    # table_list.append(
    #     html.Div(children=[
    #         html.Div([f"Dissolved {mineral} Top 5"],
    #                  style={"margin": 8, 'fontSize': 12, "fontWeight": "bold"}),
    #         dash_table.DataTable(data=initial_table[1][1], id="dissolved-table",
    #                              style_cell={'fontSize': 12,
    #                                          "textAlign": "left",  # align text to the left
    #                                          # "padding": "5px",  # reduce left/right padding
    #                                          "whiteSpace": "normal",  # allow wrapping
    #                                          "height": "auto",  # adjust row height
    #                                          })
    #     ])
    # )
    # table_list.append(
    #     html.Div(children=[
    #         html.Div([f"Total {mineral} Top 5"],
    #                  style={"margin": 8, 'fontSize': 12, "fontWeight": "bold"}),
    #         dash_table.DataTable(data=initial_table[2][1], id="total-table",
    #                              style_cell={'fontSize': 12,
    #                                          "textAlign": "left",  # align text to the left
    #                                          # "padding": "5px",  # reduce left/right padding
    #                                          "whiteSpace": "normal",  # allow wrapping
    #                                          "height": "auto",  # adjust row height
    #                                          })
    #     ])
    # )

    # Dot_Charts.append(
    #     dcc.Graph(figure=initial_dot[1], style={'padding': 10, "width": "70%"})
    # )
    # Dot_Charts.append(
    #     dcc.Graph(figure=initial_dot[2], style={'padding': 10, "width": "70%"})
    # )
    # else:
    #     table_list.append(
    #         html.Div(children=[
    #             html.Div([f"{mineral} Top 5"], id="chosen-mineral",
    #                      style={"margin": 8, 'fontSize': 12, "fontWeight": "bold"}),
    #             dash_table.DataTable(data=initial_table[0][1], id="sole-table",
    #                                  style_cell={'fontSize': 12,
    #                                              "textAlign": "left",  # align text to the left
    #                                              # "padding": "5px",  # reduce left/right padding
    #                                              "whiteSpace": "normal",  # allow wrapping
    #                                              "height": "auto",  # adjust row height
    #                                              },
    #                                  )
    #         ])
    #     )
    for dot in initial_dot:
        Dot_Charts.append(
            dcc.Graph(figure=dot, style={'padding': 10, "width": "70%"})
        )
    return table_list, Dot_Charts


# ---------- Dash App ----------
app = Dash(title="Mineral Analysis")
# k is the pre-set parameters, the sampling points which you would like to display
k = 5
# Precompute initial displays for DEFAULT_MINERAL (so the app isn't blank at load)
_initial_qm = select_topk_pairs(BASE, DEFAULT_MINERAL, k=k)

initial_geo = build_geo_fig(_initial_qm, DEFAULT_MINERAL, k=k)
initial_dot = build_dot_fig(_initial_qm, DEFAULT_MINERAL)
initial_table = build_table_data(_initial_qm)
table_list, Dot_Charts = build_chart_table(initial_table, initial_dot)

app.layout = html.Div(
    [
        html.Div(
            [
                html.Div(
                    [
                        html.H1("UK Mineral Analysis Dashboard",
                                style={"margin": 0, "fontSize": "24px", "fontWeight": 1000}),
                        html.Img(src=app.get_asset_url("Hydrostar.png"), style={"height": "70px"})
                    ],
                    style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "alignItems": "center",
                        "padding": "12px 16px",
                        "backgroundColor": "white",  # <-- your background color
                        "color": "#499823",
                        "position": "sticky",
                        "top": 0,
                        "zIndex": 999
                    }
                ),
                html.Hr(),
                html.Div(children=[
                    html.H4("Mineral to be analysed:"),
                    dcc.Dropdown(minerals, DEFAULT_MINERAL, id="mineral-dropdown", clearable=False),
                ], style={'padding': 10, 'flex': 1}
                ),
                html.Div(children=table_list, id="mineral-table",
                         style={"display": "flex", "flexDirection": "row", "gap": "10px",
                                # controls space between tables
                                "justifyContent": "space-between",  # or "space-between", "center"
                                "width": "100%"
                                }),
                html.Div(children=Dot_Charts, id="mineral-dot-chart"),
                html.Div([dcc.Graph(figure=initial_geo, id="mineral-geoscatter-chart")])

            ]

        )])
# server = app.server


# ---------- Single Multi-Output Callback ----------
@callback(
    Output("mineral-dot-chart", "children"),
    Output("mineral-table", "children"),
    Output("mineral-geoscatter-chart", "figure"),
    Input("mineral-dropdown", "value")
)
def update_all(chosen_mineral):
    qm = select_topk_pairs(BASE, chosen_mineral, k=5)
    dot_figs = build_dot_fig(qm, chosen_mineral)
    geo_fig = build_geo_fig(qm, chosen_mineral, k=5)

    table_data = build_table_data(qm)
    table_list, Dot_Charts = build_chart_table(table_data, dot_figs)

    return Dot_Charts, table_list, geo_fig


if __name__ == "__main__":
    app.run(debug=True)
