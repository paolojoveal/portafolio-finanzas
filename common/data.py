"""Descarga de datos: API del BCRP (series estadísticas) y precios de mercado (yfinance).

Las funciones guardan una copia en `data/` para que los notebooks y scripts
puedan correr sin conexión una vez descargados los datos.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(exist_ok=True)

BCRP_URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{codes}/json/{start}/{end}"

# Códigos de series mensuales del BCRP usados en el portafolio.
# Verifícalos en https://estadisticas.bcrp.gob.pe/estadisticas/series/ antes de la primera corrida:
# el BCRP a veces reemplaza códigos cuando cambia el año base de una serie.
SERIES_BCRP = {
    "ipc_var12m": "PN01273PM",      # Inflación Lima Metropolitana, var. % 12 meses
    "ipc_sae_var12m": "PN38706PM",  # Inflación sin alimentos y energía, var. % 12 meses
    "tasa_referencia": "PD04722MM",  # Tasa de referencia de la política monetaria (%)
    "tipo_cambio": "PN01234PM",     # Tipo de cambio interbancario venta, promedio (S/ por US$)
    "pbi_var": "PN01731AM",         # PBI, var. % interanual
    "expectativas_inf": "PD38045AM", # Expectativas de inflación a 12 meses (%)
}

_MESES = {"Ene": 1, "Feb": 2, "Mar": 3, "Abr": 4, "May": 5, "Jun": 6,
          "Jul": 7, "Ago": 8, "Set": 9, "Sep": 9, "Oct": 10, "Nov": 11, "Dic": 12}


def _parse_periodo(p: str) -> pd.Timestamp:
    mes, anio = p.split(".")
    return pd.Timestamp(year=int(anio), month=_MESES[mes[:3].title()], day=1)


def bcrp_series(nombres: list[str], start: str = "2004-1", end: str = "2026-12",
                cache: bool = True) -> pd.DataFrame:
    """Descarga series mensuales del BCRP y devuelve un DataFrame indexado por mes."""
    archivo = DATA_DIR / f"bcrp_{'_'.join(nombres)}.csv"
    if cache and archivo.exists():
        return pd.read_csv(archivo, index_col=0, parse_dates=True)

    codes = "-".join(SERIES_BCRP[n] for n in nombres)
    resp = requests.get(BCRP_URL.format(codes=codes, start=start, end=end), timeout=30)
    resp.raise_for_status()
    js = resp.json()
    filas = []
    for p in js["periods"]:
        valores = [float(v) if v not in ("n.d.", "") else None for v in p["values"]]
        filas.append([_parse_periodo(p["name"]), *valores])
    df = pd.DataFrame(filas, columns=["fecha", *nombres]).set_index("fecha")
    df.to_csv(archivo)
    return df


def precios(tickers: list[str], start: str = "2015-01-01", cache: bool = True) -> pd.DataFrame:
    """Precios de cierre ajustados diarios vía yfinance."""
    archivo = DATA_DIR / f"precios_{'_'.join(t.replace('.', '-') for t in tickers)}.csv"
    if cache and archivo.exists():
        return pd.read_csv(archivo, index_col=0, parse_dates=True)

    import yfinance as yf
    df = yf.download(tickers, start=start, auto_adjust=True, progress=False)["Close"]
    if isinstance(df, pd.Series):
        df = df.to_frame(tickers[0])
    df = df.dropna(how="all")
    df.to_csv(archivo)
    return df
