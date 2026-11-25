"""Valor en Riesgo (VaR), Expected Shortfall y backtesting regulatorio.

Portafolio: posición en acciones peruanas y ETF Perú, valorizada en USD.

Modelos (ventana móvil de 500 días, nivel 99%, horizonte 1 día):
    - Simulación histórica
    - Paramétrico normal
    - EWMA / RiskMetrics (lambda = 0.94)
    - Monte Carlo con t de Student (colas pesadas)

Backtesting:
    - Test de Kupiec (proporción de fallas, POF)
    - Test de independencia de Christoffersen y cobertura condicional
    - Semáforo de Basilea (últimos 250 días)

Uso:
    python var_backtesting.py          # precios reales (yfinance)
    python var_backtesting.py --demo   # datos simulados GARCH(1,1)
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
sys.path.append(str(AQUI.parent))
SALIDA = AQUI / "resultados"

PESOS = {"BAP": 0.35, "SCCO": 0.30, "BVN": 0.15, "EPU": 0.20}
VALOR_PORTAFOLIO = 1_000_000  # USD
ALFA = 0.99
VENTANA = 500
LAMBDA = 0.94


def datos_demo(n=2500, seed=3) -> pd.Series:
    """Retornos con volatilidad agrupada (GARCH(1,1)) e innovaciones t, como en datos reales."""
    rng = np.random.default_rng(seed)
    w, a, b = 2e-6, 0.08, 0.90
    r, s2 = np.zeros(n), np.full(n, w / (1 - a - b))
    z = rng.standard_t(5, n) / np.sqrt(5 / 3)
    for t in range(1, n):
        s2[t] = w + a * r[t - 1] ** 2 + b * s2[t - 1]
        r[t] = np.sqrt(s2[t]) * z[t] + 0.0003
    return pd.Series(r, index=pd.bdate_range("2015-01-01", periods=n), name="portafolio")


def retornos(demo: bool) -> pd.Series:
    if demo:
        return datos_demo()
    from common.data import precios
    p = precios(list(PESOS), start="2014-01-01")
    r = np.log(p / p.shift(1)).dropna()
    return (r[list(PESOS)] @ pd.Series(PESOS)).rename("portafolio")


# ---------- modelos de VaR (devuelven VaR y ES como pérdidas positivas, en retorno) ----------
def var_historico(x):
    q = np.quantile(x, 1 - ALFA)
    return -q, -x[x <= q].mean()


def var_normal(x):
    mu, s = x.mean(), x.std(ddof=1)
    z = stats.norm.ppf(1 - ALFA)
    return -(mu + z * s), -(mu - s * stats.norm.pdf(z) / (1 - ALFA))


def var_ewma(x):
    pesos = LAMBDA ** np.arange(len(x))[::-1]
    pesos = pesos * (1 - LAMBDA) / (1 - LAMBDA ** len(x))
    s = np.sqrt(np.sum(pesos * x ** 2))
    z = stats.norm.ppf(1 - ALFA)
    return -z * s, s * stats.norm.pdf(z) / (1 - ALFA)


def var_montecarlo_t(x, n_sim=20_000, rng=np.random.default_rng(0)):
    df, loc, scale = stats.t.fit(x)
    df = max(df, 2.5)
    sim = stats.t.rvs(df, loc, scale, size=n_sim, random_state=rng)
    q = np.quantile(sim, 1 - ALFA)
    return -q, -sim[sim <= q].mean()


MODELOS = {"Histórico": var_historico, "Normal": var_normal,
           "EWMA (RiskMetrics)": var_ewma, "Monte Carlo t": var_montecarlo_t}


def estimar(r: pd.Series) -> pd.DataFrame:
    x = r.values
    filas = []
    for t in range(VENTANA, len(x)):
        ventana = x[t - VENTANA:t]
        fila = {"fecha": r.index[t], "retorno": x[t]}
        for nombre, f in MODELOS.items():
            fila[f"VaR {nombre}"], fila[f"ES {nombre}"] = f(ventana)
        filas.append(fila)
    return pd.DataFrame(filas).set_index("fecha")


# ---------- backtesting ----------
def kupiec(fallas: np.ndarray, p=1 - ALFA):
    n, x = len(fallas), fallas.sum()
    pi = x / n
    if x == 0:
        lr = -2 * n * np.log(1 - p)
    else:
        lr = -2 * ((n - x) * np.log(1 - p) + x * np.log(p)
                   - (n - x) * np.log(1 - pi) - x * np.log(pi))
    return lr, 1 - stats.chi2.cdf(lr, 1)


def christoffersen(fallas: np.ndarray):
    f = fallas.astype(int)
    n00 = np.sum((f[:-1] == 0) & (f[1:] == 0)); n01 = np.sum((f[:-1] == 0) & (f[1:] == 1))
    n10 = np.sum((f[:-1] == 1) & (f[1:] == 0)); n11 = np.sum((f[:-1] == 1) & (f[1:] == 1))
    pi0 = n01 / max(n00 + n01, 1); pi1 = n11 / max(n10 + n11, 1)
    pi = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)
    def ll(p, a, b):
        return (a * np.log(1 - p) if a else 0) + (b * np.log(p) if b and p > 0 else 0)
    lr = -2 * (ll(pi, n00 + n10, n01 + n11) - ll(pi0, n00, n01) - ll(pi1, n10, n11))
    return lr, 1 - stats.chi2.cdf(lr, 1)


def semaforo_basilea(fallas_250: int) -> str:
    return "Verde" if fallas_250 <= 4 else ("Amarillo" if fallas_250 <= 9 else "Rojo")


def backtest(est: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for nombre in MODELOS:
        fallas = (est["retorno"] < -est[f"VaR {nombre}"]).values
        lr_uc, p_uc = kupiec(fallas)
        lr_ind, p_ind = christoffersen(fallas)
        lr_cc = lr_uc + lr_ind
        filas.append({
            "Modelo": nombre, "Días": len(fallas), "Fallas": int(fallas.sum()),
            "Esperadas": round(len(fallas) * (1 - ALFA), 1),
            "Kupiec p-valor": round(p_uc, 3),
            "Christoffersen ind. p-valor": round(p_ind, 3),
            "Cobertura cond. p-valor": round(1 - stats.chi2.cdf(lr_cc, 2), 3),
            "Basilea (250d)": semaforo_basilea(int(fallas[-250:].sum())),
            f"VaR actual (USD)": round(est[f"VaR {nombre}"].iloc[-1] * VALOR_PORTAFOLIO),
            f"ES actual (USD)": round(est[f"ES {nombre}"].iloc[-1] * VALOR_PORTAFOLIO),
        })
    return pd.DataFrame(filas).set_index("Modelo")


def grafico(est: pd.DataFrame):
    SALIDA.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(est.index, est["retorno"], color="grey", lw=0.6, label="Retorno diario")
    for nombre, c in zip(["Histórico", "EWMA (RiskMetrics)"], ["#2E5C8A", "#C0392B"]):
        ax.plot(est.index, -est[f"VaR {nombre}"], color=c, lw=1.2, label=f"-VaR 99% {nombre}")
        f = est["retorno"] < -est[f"VaR {nombre}"]
        ax.scatter(est.index[f], est["retorno"][f], color=c, s=12, zorder=3)
    ax.set_title("VaR 99% a 1 día y excepciones")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(SALIDA / "var_excepciones.png", dpi=150); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    r = retornos(args.demo)
    est = estimar(r)
    tabla = backtest(est)
    pd.set_option("display.width", 200)
    print(tabla.to_string())
    grafico(est)
    tabla.to_csv(SALIDA / "backtesting.csv")


if __name__ == "__main__":
    main()
