"""Valor en Riesgo (VaR), Expected Shortfall y backtesting regulatorio.

Portafolio de USD 1 millón en acciones peruanas y el ETF MSCI Peru. Se comparan cinco modelos
de VaR y ES al 99% a 1 día (ventana móvil de 500 días):

    - Simulación histórica
    - Paramétrico normal
    - EWMA / RiskMetrics (lambda = 0.94)
    - Paramétrico t de Student (colas pesadas)
    - Histórico filtrado: retornos reescalados por la volatilidad EWMA vigente (Hull y White, 1998)

y se valida cada uno como lo haría un área de riesgos:

    - Kupiec (1995): ¿el número de excepciones es el esperado?
    - Christoffersen (1998): ¿las excepciones son independientes o llegan agrupadas?
    - Cobertura condicional: ambas a la vez
    - Semáforo de Basilea sobre los últimos 250 días

Uso:
    python var_backtesting.py          # precios reales (Yahoo Finance)
    python var_backtesting.py --demo   # retornos simulados GARCH(1,1) con colas pesadas
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))

from common import estilo  # noqa: E402

SALIDA = AQUI / "resultados"
PESOS = {"BAP": 0.35, "SCCO": 0.30, "BVN": 0.15, "EPU": 0.20}
VALOR_PORTAFOLIO = 1_000_000   # USD
ALFA = 0.99
VENTANA = 500
LAMBDA = 0.94
MODELOS = ["Histórico", "Normal", "EWMA (RiskMetrics)", "t de Student", "Histórico filtrado"]


# ---------- datos ----------
def datos_demo(n: int = 2500, seed: int = 3) -> pd.Series:
    """Retornos con volatilidad agrupada (GARCH(1,1)) e innovaciones t con 5 grados de libertad."""
    rng = np.random.default_rng(seed)
    w, a, b = 2e-6, 0.08, 0.90
    r, s2 = np.zeros(n), np.full(n, w / (1 - a - b))
    z = rng.standard_t(5, n) / np.sqrt(5 / 3)
    for t in range(1, n):
        s2[t] = w + a * r[t - 1] ** 2 + b * s2[t - 1]
        r[t] = np.sqrt(s2[t]) * z[t] + 0.0003
    return pd.Series(r, index=pd.bdate_range("2015-01-01", periods=n, name="fecha"), name="portafolio")


def retornos(demo: bool) -> pd.Series:
    """Retorno diario del portafolio con pesos fijos (se rebalancea cada día a los pesos objetivo)."""
    if demo:
        return datos_demo()
    from common.data import precios
    p = precios(list(PESOS), start="2014-01-01")
    return (p.pct_change(fill_method=None).dropna() @ pd.Series(PESOS)).rename("portafolio")


# ---------- modelos: devuelven (VaR, ES) como pérdidas positivas, en retorno ----------
def var_historico(x: np.ndarray, alfa: float = ALFA) -> tuple[float, float]:
    q = np.quantile(x, 1 - alfa)
    return -q, -x[x <= q].mean()


def var_normal(x: np.ndarray, alfa: float = ALFA) -> tuple[float, float]:
    mu, s = x.mean(), x.std(ddof=1)
    z = stats.norm.ppf(1 - alfa)
    return -(mu + z * s), -mu + s * stats.norm.pdf(z) / (1 - alfa)


def var_sigma(sigma: float, alfa: float = ALFA) -> tuple[float, float]:
    """Normal de media cero con una volatilidad dada (la usa el modelo EWMA)."""
    z = stats.norm.ppf(1 - alfa)
    return -z * sigma, sigma * stats.norm.pdf(z) / (1 - alfa)


def var_t(x: np.ndarray, alfa: float = ALFA) -> tuple[float, float]:
    """t de Student ajustada por máxima verosimilitud. VaR y ES tienen fórmula cerrada."""
    gl, loc, escala = stats.t.fit(x)
    gl = max(gl, 2.5)                                    # con menos de ~2 grados de libertad el ES no existe
    q = stats.t.ppf(1 - alfa, gl)
    es_estandar = stats.t.pdf(q, gl) / (1 - alfa) * (gl + q ** 2) / (gl - 1)
    return -(loc + escala * q), -loc + escala * es_estandar


def volatilidad_ewma(r: np.ndarray, lam: float = LAMBDA, semilla: int = VENTANA) -> np.ndarray:
    """sigma[t]: volatilidad pronosticada para el día t con datos hasta t-1.
    sigma²[t] = lam·sigma²[t-1] + (1 - lam)·r²[t-1], iniciada con la varianza de los primeros `semilla` días."""
    s2 = np.empty(len(r))
    s2[0] = np.var(r[:semilla])
    for t in range(1, len(r)):
        s2[t] = lam * s2[t - 1] + (1 - lam) * r[t - 1] ** 2
    return np.sqrt(s2)


def var_historico_filtrado(x: np.ndarray, sigma_x: np.ndarray, sigma_hoy: float, alfa: float = ALFA):
    """Histórico sobre retornos llevados a la volatilidad de hoy: x_s · sigma_hoy / sigma_s."""
    return var_historico(x / sigma_x * sigma_hoy, alfa)


def estimar(r: pd.Series) -> pd.DataFrame:
    x = r.to_numpy()
    sigma = volatilidad_ewma(x)
    filas = []
    for t in range(VENTANA, len(x)):
        v = x[t - VENTANA:t]
        medidas = {
            "Histórico": var_historico(v),
            "Normal": var_normal(v),
            "EWMA (RiskMetrics)": var_sigma(sigma[t]),
            "t de Student": var_t(v),
            "Histórico filtrado": var_historico_filtrado(v, sigma[t - VENTANA:t], sigma[t]),
        }
        fila = {"fecha": r.index[t], "retorno": x[t]}
        for nombre, (var, es) in medidas.items():
            fila[f"VaR {nombre}"], fila[f"ES {nombre}"] = var, es
        filas.append(fila)
    return pd.DataFrame(filas).set_index("fecha")


# ---------- backtesting ----------
def _ll(p: float, ceros: int, unos: int) -> float:
    """Log-verosimilitud Bernoulli, con la convención 0·ln(0) = 0."""
    return (ceros * np.log(1 - p) if ceros else 0.0) + (unos * np.log(p) if unos else 0.0)


def kupiec(fallas: np.ndarray, p: float = 1 - ALFA) -> tuple[float, float]:
    """Proporción de fallas: H0, la frecuencia de excepciones es p. LR ~ chi2(1)."""
    n, x = len(fallas), int(fallas.sum())
    lr = -2 * (_ll(p, n - x, x) - _ll(x / n, n - x, x))
    return lr, float(stats.chi2.sf(lr, 1))


def christoffersen(fallas: np.ndarray) -> tuple[float, float]:
    """Independencia: H0, la probabilidad de una excepción no depende de si ayer hubo una. LR ~ chi2(1)."""
    f = fallas.astype(int)
    n00 = int(((f[:-1] == 0) & (f[1:] == 0)).sum()); n01 = int(((f[:-1] == 0) & (f[1:] == 1)).sum())
    n10 = int(((f[:-1] == 1) & (f[1:] == 0)).sum()); n11 = int(((f[:-1] == 1) & (f[1:] == 1)).sum())
    pi0 = n01 / max(n00 + n01, 1)
    pi1 = n11 / max(n10 + n11, 1)
    pi = (n01 + n11) / max(len(f) - 1, 1)
    lr = -2 * (_ll(pi, n00 + n10, n01 + n11) - _ll(pi0, n00, n01) - _ll(pi1, n10, n11))
    return lr, float(stats.chi2.sf(lr, 1))


def semaforo_basilea(fallas_250: int) -> str:
    """Zonas del Comité de Basilea para 250 días al 99%: verde hasta 4, amarillo de 5 a 9, rojo desde 10."""
    return "Verde" if fallas_250 <= 4 else ("Amarillo" if fallas_250 <= 9 else "Rojo")


def backtest(est: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for nombre in MODELOS:
        fallas = (est["retorno"] < -est[f"VaR {nombre}"]).to_numpy()
        lr_uc, p_uc = kupiec(fallas)
        lr_ind, p_ind = christoffersen(fallas)
        filas.append({
            "Modelo": nombre, "Días": len(fallas), "Excepciones": int(fallas.sum()),
            "Esperadas": round(len(fallas) * (1 - ALFA), 1),
            "Kupiec (p)": round(p_uc, 3), "Independencia (p)": round(p_ind, 3),
            "Cobertura cond. (p)": round(float(stats.chi2.sf(lr_uc + lr_ind, 2)), 3),
            "Basilea (250 d)": semaforo_basilea(int(fallas[-250:].sum())),
            "VaR hoy (USD)": round(est[f"VaR {nombre}"].iloc[-1] * VALOR_PORTAFOLIO),
            "ES hoy (USD)": round(est[f"ES {nombre}"].iloc[-1] * VALOR_PORTAFOLIO),
        })
    return pd.DataFrame(filas).set_index("Modelo")


# ---------- figuras ----------
def figura_excepciones(est: pd.DataFrame, pie: str):
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.plot(est.index, est["retorno"] * 100, color=estilo.CONTEXTO, lw=0.6, label="Retorno diario del portafolio")
    for nombre, color in [("Histórico", estilo.AZUL), ("Histórico filtrado", estilo.NARANJA)]:
        limite = -est[f"VaR {nombre}"] * 100
        ax.plot(est.index, limite, color=color, lw=1.6, label=f"VaR 99%, {nombre.lower()}")
        f = est["retorno"] * 100 < limite
        ax.scatter(est.index[f], est["retorno"][f] * 100, s=34, color=color, edgecolor=estilo.SUPERFICIE,
                   linewidth=1.2, zorder=4)
    estilo.titulo(ax, "VaR al 99% a un día y excepciones",
                  "Los puntos marcan los días en que la pérdida superó el VaR de cada modelo")
    estilo.formato_pct(ax)
    ax.legend(loc="lower right", ncol=1)
    return estilo.guardar(fig, SALIDA / "var_excepciones.png", pie)


def figura_backtesting(tabla: pd.DataFrame, pie: str):
    fig, ax = plt.subplots(figsize=(9, 3.9))
    y = np.arange(len(tabla))
    ax.barh(y, tabla["Excepciones"], height=0.42, color=estilo.AZUL)
    esperadas = float(tabla["Esperadas"].iloc[0])
    ax.axvline(esperadas, color=estilo.TINTA_2, lw=1.2, ls=(0, (4, 3)))
    estilo.etiqueta(ax, esperadas, -0.72, f"Esperadas: {esperadas:.0f}", dx=6, fontsize=8.5)
    for i, (_, f) in enumerate(tabla.iterrows()):
        veredicto = "pasa ambas pruebas" if min(f["Kupiec (p)"], f["Independencia (p)"]) >= 0.05 else (
            "falla en cantidad" if f["Kupiec (p)"] < 0.05 <= f["Independencia (p)"] else (
                "falla en independencia" if f["Independencia (p)"] < 0.05 <= f["Kupiec (p)"] else "falla ambas pruebas"))
        estilo.etiqueta(ax, f["Excepciones"], i, f"{f['Excepciones']:.0f}  ·  {veredicto}")
    ax.set_yticks(y, tabla.index)
    ax.set_ylim(len(tabla) - 0.5, -0.95)
    ax.set_xlim(0, max(tabla["Excepciones"].max(), esperadas) * 1.65)
    ax.set_xlabel(f"Excepciones en {int(tabla['Días'].iloc[0]):,} días")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    estilo.titulo(ax, "Excepciones por modelo frente a las esperadas",
                  "Pruebas al 5%: Kupiec (cantidad) y Christoffersen (independencia)")
    return estilo.guardar(fig, SALIDA / "backtesting.png", pie)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--demo", action="store_true", help="usa retornos simulados (sin conexión)")
    args = ap.parse_args()
    estilo.aplicar()
    r = retornos(args.demo)
    est = estimar(r)
    tabla = backtest(est)
    pd.set_option("display.width", 220)
    print(f"Evaluación de {est.index[0]:%Y-%m-%d} a {est.index[-1]:%Y-%m-%d}" + (" · DATOS SIMULADOS" if args.demo else ""))
    print(tabla.to_string())
    SALIDA.mkdir(exist_ok=True)
    pie = ("Datos simulados (modo demo)." if args.demo else
           f"Fuente: Yahoo Finance, precios ajustados. Evaluación de {est.index[0]:%m/%Y} a {est.index[-1]:%m/%Y}. Elaboración propia.")
    figura_excepciones(est, pie)
    figura_backtesting(tabla, pie)
    tabla.to_csv(SALIDA / "backtesting.csv")
    print(f"\nFiguras y tabla en {SALIDA.relative_to(AQUI.parent)}/")


if __name__ == "__main__":
    main()
