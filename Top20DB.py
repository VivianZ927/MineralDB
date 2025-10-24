import pickle
from dash import Dash, html, dash_table, dcc, callback, Output, Input
import pandas as pd
import plotly.express as px

# ---------- Config ----------
PICKLE_PATH = "ea26Top20.pkl"
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

# get the top k rows for each test types k<=20
def get_top(base, k):
    min_cols = list(base.keys())
    basic_cols = ['Sampling Point', 'lat', 'long', 'Type', 'YearMonth']
    gb = ["Sampling Point", "lat", "long", "Type"]
    summarize = {}
    for col in min_cols:
        min_dict = {}
        for f, df in base[col].items():
            # 1) Per-(Sampling Point, Type) average for this metric
            means_df = (df.groupby(gb, as_index=False)['monthly concentration'].mean().rename(
                columns={'monthly concentration': "average monthly concentration"}))
            # 2) Top-k groups for this metric
            top_keys = means_df.nlargest(k, "average monthly concentration")[gb]
            # 3) Keep only rows from those top-5 groups and attach the average
            tmp = df.merge(top_keys.assign(_keep=1), on=gb, how="inner").merge(means_df, on=gb, how="left",
                                                                               suffixes=(None, "_y"))

            # 4) Select the columns you want and standardize names
            tmp = tmp[basic_cols + ["monthly concentration", "average monthly concentration"]].copy()

            min_dict[f] = tmp
        summarize[col] = min_dict
    return summarize


# get the mineral list
def get_minerals(dfs):
    return list(dfs.keys())


# ---------- Helpers ----------


def build_geo_fig(point_agg, mineral, k):
    total_point_agg = point_agg[mineral]["Total"]
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
    ma = month_agg[mineral]

    for m, d in ma.items():
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

        if pd.isna(ymin) or pd.isna(ymax):
            pass
        else:
            pad = max(1.0, 0.05 * (ymax - ymin) if ymax > ymin else 1.0)
            fig.update_layout(yaxis_range=[ymin - pad, ymax + pad])
        fig.update_traces(marker=dict(size=12))
        figures.append(fig)
    return figures


def build_table_data(point_agg, mineral):
    dfs = point_agg[mineral]
    # Only return the columns needed in the table
    tbs = {}

    for m, d in dfs.items():

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

    for dot in initial_dot:
        Dot_Charts.append(
            dcc.Graph(figure=dot, style={'padding': 10, "width": "70%"})
        )
    return table_list, Dot_Charts


# ---------- Dash App ----------
app = Dash(title="Mineral Analysis")
# k is the pre-set parameters, the sampling points which you would like to display
# Load data (deserialize) The BASE here is the top 20 data for each mineral features, including the total ones.
with open(PICKLE_PATH, 'rb') as handle:
    BASE = pickle.load(handle)
k = 5
BASE = get_top(BASE, k)
minerals = get_minerals(BASE)
if DEFAULT_MINERAL not in minerals and len(minerals) > 0:
    DEFAULT_MINERAL = minerals[0]

initial_geo = build_geo_fig(BASE, DEFAULT_MINERAL, k=k)
initial_dot = build_dot_fig(BASE, DEFAULT_MINERAL)
initial_table = build_table_data(BASE, DEFAULT_MINERAL)
table_list, Dot_Charts = build_chart_table(initial_table, initial_dot)

app.layout = html.Div(
    [
        html.Div(
            [
                html.Div(
                    [
                        html.H1("UK Mineral Analysis Dashboard",
                                style={"margin": 0, "fontSize": "24px", "fontWeight": 1000}),
                        html.Img(src=app.get_asset_url("logo.png"), style={"height": "70px"})
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


server = app.server


# ---------- Single Multi-Output Callback ----------
@callback(
    Output("mineral-dot-chart", "children"),
    Output("mineral-table", "children"),
    Output("mineral-geoscatter-chart", "figure"),
    Input("mineral-dropdown", "value")
)
def update_all(chosen_mineral):
    geo_fig = build_geo_fig(BASE, chosen_mineral, k=k)
    dot_figs = build_dot_fig(BASE, chosen_mineral)
    table_data = build_table_data(BASE, chosen_mineral)
    table_list, Dot_Charts = build_chart_table(table_data, dot_figs)

    return Dot_Charts, table_list, geo_fig


if __name__ == "__main__":
    app.run(debug=True)
