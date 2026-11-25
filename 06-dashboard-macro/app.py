"""Dashboard macro-financiero del Perú (Streamlit).

    streamlit run 06-dashboard-macro/app.py
    streamlit run 06-dashboard-macro/app.py -- --demo   # sin conexión
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

AQUI = Path(__file__).resolve().parent
sys.path.append(str(AQUI.parent))
sys.path.append(str(AQUI.parent / "04-inflacion-bcrp"))

DEMO = "--demo" in sys.argv
META_MIN, META_MAX = 1.0, 3.0

st.set_page_config(page_title="Perú: tablero macro-financiero", layout="wide")


@st.cache_data(ttl=6 * 3600)
def macro() -> pd.DataFrame:
    if DEMO:
        from inflacion_bcrp import datos_demo
        return datos_demo()
    from common.data import bcrp_series
    return bcrp_series(["ipc_var12m", "tasa_referencia", "tipo_cambio", "pbi_var"],
                       start="2010-1", cache=False)


@st.cache_data(ttl=6 * 3600)
def mercado() -> pd.DataFrame:
    tickers = ["EPU", "BAP", "SCCO", "HG=F"]
    if DEMO:
        rng = np.random.default_rng(1)
        idx = pd.bdate_range(end=pd.Timestamp.today(), periods=1500)
        r = rng.normal(0.0003, 0.015, (len(idx), len(tickers)))
        return pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=tickers)
    from common.data import precios
    return precios(tickers, start="2019-01-01", cache=False)


def kpi(col, nombre, serie, sufijo="", fmt="{:.2f}"):
    actual, previo = serie.dropna().iloc[-1], serie.dropna().iloc[-13] if len(serie.dropna()) > 13 else np.nan
    col.metric(nombre, fmt.format(actual) + sufijo,
               None if np.isnan(previo) else f"{actual - previo:+.2f} vs. hace 12 meses",
               delta_color="inverse" if nombre.startswith(("Inflación", "Tipo")) else "normal")


def linea(df, cols, titulo, banda=False, ytitle=""):
    fig = go.Figure()
    for c, nombre in cols.items():
        fig.add_trace(go.Scatter(x=df.index, y=df[c], name=nombre, mode="lines"))
    if banda:
        fig.add_hrect(y0=META_MIN, y1=META_MAX, fillcolor="green", opacity=0.08, line_width=0,
                      annotation_text="Rango meta", annotation_position="top left")
    fig.update_layout(title=titulo, height=360, margin=dict(l=10, r=10, t=50, b=10),
                      yaxis_title=ytitle, legend=dict(orientation="h", y=-0.2))
    return fig


st.title("Perú: tablero macro-financiero")
st.caption("Fuente: BCRP (series estadísticas) y Yahoo Finance." + (" **Modo demo: datos simulados.**" if DEMO else ""))

m = macro()
desde = st.sidebar.slider("Desde el año", int(m.index.year.min()), int(m.index.year.max()), 2015)
m = m[m.index.year >= desde]

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Inflación 12m", m["ipc_var12m"], "%")
kpi(c2, "Tasa de referencia", m["tasa_referencia"], "%")
kpi(c3, "Tipo de cambio", m["tipo_cambio"], "", "S/ {:.3f}")
kpi(c4, "PBI (var. % anual)", m["pbi_var"], "%", "{:.1f}")

m = m.assign(tasa_real_ex_post=m["tasa_referencia"] - m["ipc_var12m"])
a, b = st.columns(2)
a.plotly_chart(linea(m, {"ipc_var12m": "Inflación 12m", "tasa_referencia": "Tasa de referencia",
                         "tasa_real_ex_post": "Tasa real ex post"},
                     "Inflación y política monetaria", banda=True, ytitle="%"), use_container_width=True)
b.plotly_chart(linea(m, {"tipo_cambio": "S/ por US$"}, "Tipo de cambio interbancario"), use_container_width=True)

st.subheader("Mercado")
p = mercado()
p = p[p.index.year >= desde]
base100 = p / p.iloc[0] * 100
nombres = {"EPU": "MSCI Peru (EPU)", "BAP": "Credicorp", "SCCO": "Southern Copper", "HG=F": "Cobre (futuro)"}
a, b = st.columns(2)
a.plotly_chart(linea(base100, nombres, "Desempeño relativo (base 100)"), use_container_width=True)
r = np.log(p / p.shift(1)).dropna()
vol = r.rolling(63).std() * np.sqrt(252) * 100
b.plotly_chart(linea(vol, nombres, "Volatilidad realizada a 3 meses (anualizada)", ytitle="%"),
               use_container_width=True)

st.subheader("Correlación con el cobre")
corr = r.rolling(126).corr(r["HG=F"]).drop(columns="HG=F")
st.plotly_chart(linea(corr, {k: v for k, v in nombres.items() if k != "HG=F"},
                      "Correlación móvil de 6 meses con el precio del cobre"), use_container_width=True)
st.caption("La economía peruana y la BVL dependen fuertemente de la minería: el cobre explica buena parte "
           "de los movimientos del mercado local.")
