"""Tablero macro-financiero del Perú (Streamlit).

    streamlit run 06-dashboard-macro/app.py              # datos del BCRP y de Yahoo Finance
    streamlit run 06-dashboard-macro/app.py -- --demo    # datos simulados, sin conexión
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

AQUI = Path(__file__).resolve().parent
sys.path[:0] = [str(AQUI.parent), str(AQUI.parent / "04-inflacion-bcrp")]

from common import estilo  # noqa: E402

DEMO = "--demo" in sys.argv
META_MIN, META_MAX = 1.0, 3.0
MACRO = ["ipc_var12m", "expectativas_inf_12m", "tasa_referencia", "tipo_cambio", "pbi_var12m", "embig_peru", "cobre"]
MERCADO = {"EPU": "MSCI Peru (EPU)", "BAP": "Credicorp", "SCCO": "Southern Copper", "HG=F": "Cobre (futuro)"}

st.set_page_config(page_title="Perú: tablero macro-financiero", layout="wide")


@st.cache_data(ttl=6 * 3600)
def macro(demo: bool) -> pd.DataFrame:
    if demo:
        from inflacion_bcrp import datos_demo
        d = datos_demo()
        rng = np.random.default_rng(5)
        d["embig_peru"] = 160 + np.cumsum(rng.normal(0, 6, len(d)))
        d["cobre"] = 300 * np.exp(np.cumsum(rng.normal(0.002, 0.05, len(d))))
        return d[MACRO].loc["2010-01-01":]
    from common.data import bcrp_series
    return bcrp_series(MACRO, start="2010-1", max_edad_horas=6)


@st.cache_data(ttl=6 * 3600)
def mercado(demo: bool) -> pd.DataFrame:
    if demo:
        rng = np.random.default_rng(1)
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=1500)
        r = rng.normal(0.0003, 0.015, (len(idx), len(MERCADO)))
        return pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=list(MERCADO))
    from common.data import precios
    # Los futuros y las acciones no tienen los mismos feriados: se arrastra el último precio conocido.
    return precios(list(MERCADO), start="2019-01-01", max_edad_horas=6).ffill().dropna()


def indicador(col, nombre: str, serie: pd.Series, formato: str, unidad_delta: str, sube_es_malo: bool = False):
    s = serie.dropna()
    actual, previo = s.iloc[-1], (s.iloc[-13] if len(s) > 13 else np.nan)
    delta = None if np.isnan(previo) else f"{actual - previo:+.2f} {unidad_delta} en 12 meses"
    col.metric(f"{nombre} · {s.index[-1]:%m/%Y}", formato.format(actual), delta,
               delta_color="inverse" if sube_es_malo else "normal")


def linea(df: pd.DataFrame, series: dict[str, str], titulo: str, unidad: str = "", banda_meta: bool = False,
          cero: bool = False) -> go.Figure:
    fig = go.Figure()
    for (columna, nombre), color in zip(series.items(), estilo.SERIE):
        fig.add_trace(go.Scatter(x=df.index, y=df[columna], name=nombre, mode="lines",
                                 line={"color": color, "width": 2},
                                 hovertemplate=f"%{{y:.2f}}{unidad}<extra>{nombre}</extra>"))
    if banda_meta:
        fig.add_hrect(y0=META_MIN, y1=META_MAX, fillcolor=estilo.AGUA, opacity=0.12, line_width=0,
                      annotation_text="Rango meta", annotation_position="top left",
                      annotation_font={"size": 11, "color": estilo.TINTA_2})
    if cero:
        fig.add_hline(y=0, line_color=estilo.EJE, line_width=1)
    fig.update_layout(
        title={"text": titulo, "font": {"size": 15, "color": estilo.TINTA}}, height=340,
        margin={"l": 10, "r": 10, "t": 48, "b": 10}, hovermode="x unified", showlegend=len(series) > 1,
        legend={"orientation": "h", "y": -0.18, "font": {"color": estilo.TINTA_2}},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "system-ui, -apple-system, 'Segoe UI', sans-serif", "color": estilo.TINTA_2},
        xaxis={"showgrid": False, "linecolor": estilo.EJE},
        yaxis={"gridcolor": estilo.GRILLA, "zeroline": False, "ticksuffix": unidad},
    )
    return fig


st.title("Perú: tablero macro-financiero")
st.caption("Fuente: BCRP (series estadísticas) y Yahoo Finance. Elaboración propia."
           + (" **Modo demo: datos simulados.**" if DEMO else ""))

m = macro(DEMO)
desde = st.sidebar.slider("Desde el año", int(m.index.year.min()), int(m.index.year.max()) - 1, 2015)
m = m[m.index.year >= desde].assign(tasa_real=lambda d: d["tasa_referencia"] - d["expectativas_inf_12m"])

c = st.columns(5)
indicador(c[0], "Inflación 12 meses", m["ipc_var12m"], "{:.2f}%", "pp", sube_es_malo=True)
indicador(c[1], "Expectativas a 12 meses", m["expectativas_inf_12m"], "{:.2f}%", "pp", sube_es_malo=True)
indicador(c[2], "Tasa de referencia", m["tasa_referencia"], "{:.2f}%", "pp")
indicador(c[3], "Tipo de cambio", m["tipo_cambio"], "S/ {:.3f}", "soles", sube_es_malo=True)
indicador(c[4], "PBI, var. % 12 meses", m["pbi_var12m"], "{:.1f}%", "pp")

a, b = st.columns(2)
a.plotly_chart(linea(m, {"ipc_var12m": "Inflación 12 meses", "expectativas_inf_12m": "Expectativas a 12 meses",
                         "tasa_referencia": "Tasa de referencia"},
                     "Inflación, expectativas y tasa de referencia", "%", banda_meta=True), width="stretch")
b.plotly_chart(linea(m, {"tasa_real": "Tasa de referencia menos expectativas de inflación"},
                     "Tasa de referencia real (ex ante)", "%", cero=True), width="stretch")
a, b, d = st.columns(3)
a.plotly_chart(linea(m, {"tipo_cambio": "S/ por US$"}, "Tipo de cambio interbancario (S/ por US$)"), width="stretch")
b.plotly_chart(linea(m, {"embig_peru": "EMBIG Perú"}, "Riesgo país: EMBIG Perú (puntos básicos)"), width="stretch")
d.plotly_chart(linea(m, {"cobre": "Cobre LME"}, "Cobre LME (¢US$ por libra)"), width="stretch")

st.subheader("Mercado")
p = mercado(DEMO)
p = p[p.index.year >= desde]
r = np.log(p / p.shift(1)).dropna()
a, b = st.columns(2)
a.plotly_chart(linea(p / p.iloc[0] * 100, MERCADO, f"Desempeño relativo (base 100 = {p.index[0]:%d/%m/%Y})"), width="stretch")
b.plotly_chart(linea(r.rolling(63).std() * np.sqrt(252) * 100, MERCADO,
                     "Volatilidad realizada a 3 meses, anualizada", "%"), width="stretch")

st.subheader("Dependencia del cobre")
corr = r.rolling(126).corr(r["HG=F"]).drop(columns="HG=F")
st.plotly_chart(linea(corr, {k: v for k, v in MERCADO.items() if k != "HG=F"},
                      "Correlación móvil de 6 meses con el precio del cobre", cero=True), width="stretch")
st.caption("Correlación de retornos diarios en ventanas de 126 días. Mide cuánto se mueven juntos, no causalidad.")
