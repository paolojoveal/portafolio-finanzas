"""Descarga de datos con caché local: series del BCRP y precios de mercado (Yahoo Finance).

Tres reglas que evitan los errores silenciosos más comunes al trabajar con estas fuentes:

1. Cada serie del BCRP se pide por separado y se comprueba que el nombre oficial que
   devuelve la API corresponde a lo que el código espera. La API devuelve las series de un
   pedido conjunto en su propio orden (no en el pedido), así que confiar en la posición
   termina etiquetando la tasa de referencia como inflación sin que nada falle.
2. Las descargas se reintentan (ambas fuentes cortan conexiones con frecuencia) y solo se
   guarda en caché lo que pasó la validación. Una descarga incompleta nunca se guarda.
3. La caché caduca: pasado `max_edad_horas` se vuelve a descargar.
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

BCRP_URL = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{codigo}/json/{inicio}/{fin}/esp"

# nombre corto -> (código, final del nombre oficial que devuelve la API, descripción)
# Códigos verificados contra la API el 25 de noviembre de 2026. Si el BCRP recodifica una
# serie, `bcrp_series` falla con un mensaje claro en lugar de devolver otra variable.
SERIES_BCRP: dict[str, tuple[str, str, str]] = {
    "ipc_var12m": ("PN01273PM", "(var% 12 meses) - IPC",
                   "IPC de Lima Metropolitana, variación % 12 meses"),
    "ipc_sae_var12m": ("PN01277PM", "(var% 12 meses) - IPC Sin Alimentos y Energía",
                       "IPC sin alimentos y energía, variación % 12 meses"),
    "ipc_subyacente_var12m": ("PN01279PM", "(var% 12 meses) - IPC Subyacente",
                              "IPC subyacente, variación % 12 meses"),
    "expectativas_inf_12m": ("PD12912AM", "Expectativa de Inflación a 12 meses",
                             "Expectativa de inflación a 12 meses (%)"),
    "tasa_referencia": ("PD04722MM", "Tasa de Referencia de la Política Monetaria",
                        "Tasa de referencia de la política monetaria (%)"),
    "tipo_cambio": ("PN01207PM", "Interbancario - Promedio",
                    "Tipo de cambio interbancario promedio (S/ por US$)"),
    "pbi_var12m": ("PN01728AM", "(variación porcentual interanual) - PBI",
                   "PBI, variación % interanual"),
    "pbi_indice_sa": ("PN01773AM", "(índice 2007 = 100) - PBI Desestacionalizado - mensual",
                      "PBI desestacionalizado, índice 2007 = 100"),
    "embig_peru": ("PN01129XM", "(EMBIG) - Perú",
                   "EMBIG Perú, diferencial de rendimientos (puntos básicos)"),
    "cobre": ("PN01652XM", "Cobre - LME (¢US$ por libras)",
              "Cobre LME, promedio del periodo (¢US$ por libra)"),
}

_MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
          "jul": 7, "ago": 8, "set": 9, "sep": 9, "oct": 10, "nov": 11, "dic": 12}


class ErrorDeDatos(RuntimeError):
    """La fuente respondió algo distinto de lo esperado (serie equivocada, datos incompletos)."""


# ---------- utilidades ----------
def _parse_periodo(nombre: str) -> pd.Timestamp:
    """'Ene.2024' -> 2024-01-01. Solo series mensuales."""
    try:
        mes, anio = nombre.strip().split(".")
        return pd.Timestamp(year=int(anio), month=_MESES[mes[:3].lower()], day=1)
    except (ValueError, KeyError) as e:
        raise ErrorDeDatos(f"Periodo del BCRP no reconocido: {nombre!r} (se esperaba 'Ene.2024').") from e


def serie_desde_json(js: dict, nombre: str, debe_terminar_en: str | None = None) -> pd.Series:
    """Convierte la respuesta JSON del BCRP (una sola serie) en una serie mensual.

    Si se indica `debe_terminar_en`, comprueba que el nombre oficial de la serie termine así
    («... (var% 12 meses) - IPC» no es lo mismo que «... - IPC Sin Alimentos»).
    """
    oficiales = [s["name"] for s in js["config"]["series"]]
    if len(oficiales) != 1:
        raise ErrorDeDatos(f"Se esperaba una serie y llegaron {len(oficiales)}: {oficiales}")
    if debe_terminar_en and not oficiales[0].strip().lower().endswith(debe_terminar_en.lower()):
        raise ErrorDeDatos(
            f"La serie '{nombre}' no es la esperada. La API devolvió «{oficiales[0]}» y el nombre "
            f"debería terminar en «{debe_terminar_en}». Revisa el código en SERIES_BCRP: el BCRP "
            "recodifica series cuando cambia el año base.")
    fechas = [_parse_periodo(p["name"]) for p in js["periods"]]
    valores = [pd.to_numeric(p["values"][0], errors="coerce") for p in js["periods"]]
    return pd.Series(valores, index=pd.DatetimeIndex(fechas, name="fecha"), name=nombre, dtype=float)


def _get_json(url: str, intentos: int = 5, pausa: float = 1.5) -> dict:
    ultimo: Exception | None = None
    for i in range(intentos):
        try:
            resp = requests.get(url, timeout=40)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:  # conexión cortada, 5xx o respuesta sin JSON
            ultimo = e
            time.sleep(pausa * (i + 1))
    raise ErrorDeDatos(f"El BCRP no respondió tras {intentos} intentos ({type(ultimo).__name__}). "
                       "Vuelve a intentar en unos minutos o usa --demo.") from ultimo


def _cache_vigente(archivo: Path, max_edad_horas: float) -> bool:
    return archivo.exists() and (time.time() - archivo.stat().st_mtime) < max_edad_horas * 3600


# ---------- BCRP ----------
def bcrp_series(nombres: list[str], start: str = "2004-1", end: str | None = None,
                cache: bool = True, max_edad_horas: float = 24) -> pd.DataFrame:
    """Series mensuales del BCRP en un DataFrame indexado por mes, con las columnas en el orden pedido.

    `start` y `end` van como 'AAAA-M'. Sin `end` se pide hasta el mes en curso.
    """
    desconocidas = [n for n in nombres if n not in SERIES_BCRP]
    if desconocidas:
        raise KeyError(f"Series no definidas en SERIES_BCRP: {desconocidas}")
    hoy = date.today()
    fin = end or f"{hoy.year}-{hoy.month}"
    columnas = []
    for nombre in nombres:
        codigo, final_esperado, _ = SERIES_BCRP[nombre]
        archivo = DATA_DIR / f"bcrp_{codigo}_{start}_{fin}.csv"
        if cache and _cache_vigente(archivo, max_edad_horas):
            s = pd.read_csv(archivo, index_col=0, parse_dates=True).iloc[:, 0].rename(nombre)
        else:
            js = _get_json(BCRP_URL.format(codigo=codigo, inicio=start, fin=fin))
            s = serie_desde_json(js, nombre, final_esperado)
            if s.dropna().empty:
                raise ErrorDeDatos(f"La serie '{nombre}' ({codigo}) llegó sin datos para {start} a {fin}.")
            DATA_DIR.mkdir(exist_ok=True)
            s.to_csv(archivo)
            time.sleep(0.3)  # el servidor corta las ráfagas de pedidos
        columnas.append(s)
    return pd.concat(columnas, axis=1).sort_index()


# ---------- precios de mercado ----------
def validar_precios(df: pd.DataFrame, tickers: list[str], min_obs: int = 30) -> None:
    """Falla si falta un ticker o si llegó vacío (Yahoo devuelve columnas de NaN cuando corta la conexión)."""
    faltan = [t for t in tickers if t not in df.columns or df[t].count() < min_obs]
    if faltan:
        raise ErrorDeDatos(f"Yahoo Finance no devolvió datos suficientes para: {', '.join(faltan)}. "
                           "Suele ser un corte temporal: vuelve a correr o usa --demo.")


def precios(tickers: list[str], start: str = "2015-01-01", cache: bool = True,
            max_edad_horas: float = 24, intentos: int = 3) -> pd.DataFrame:
    """Precios de cierre diarios ajustados por dividendos y splits (yfinance), una columna por ticker."""
    archivo = DATA_DIR / f"precios_{'_'.join(t.replace('.', '-').replace('=', '-') for t in tickers)}_{start}.csv"
    if cache and _cache_vigente(archivo, max_edad_horas):
        return pd.read_csv(archivo, index_col=0, parse_dates=True)

    import yfinance as yf

    error: Exception | None = None
    for i in range(intentos):
        try:
            df = yf.download(tickers, start=start, auto_adjust=True, progress=False)["Close"]
            if isinstance(df, pd.Series):
                df = df.to_frame(tickers[0])
            df = df.dropna(how="all")
            validar_precios(df, tickers)
            df = df[tickers]
            df.index.name = "fecha"
            DATA_DIR.mkdir(exist_ok=True)
            df.to_csv(archivo)
            return df
        except Exception as e:  # yfinance lanza excepciones propias según la versión
            error = e
            time.sleep(2 * (i + 1))
    raise ErrorDeDatos(f"No se pudieron descargar los precios tras {intentos} intentos: {error}") from error
