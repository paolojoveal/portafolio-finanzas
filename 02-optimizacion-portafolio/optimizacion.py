"""Optimización de portafolio con activos ligados al Perú y diversificadores globales.

Estrategias comparadas (rebalanceo mensual, ventana móvil de 3 años, fuera de muestra):
    - Pesos iguales (1/N)
    - Mínima varianza
    - Máximo Sharpe (Markowitz)
    - Paridad de riesgo
    - Black-Litterman con vistas del analista

Uso:
    python optimizacion.py          # descarga precios con yfinance
    python optimizacion.py --demo   # datos simulados (sin conexión)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import minimize

AQUI = Path(__file__).resolve().parent
sys.path.append(str(AQUI.parent))
SALIDA = AQUI / "resultados"

ACTIVOS = {
    "BAP": "Credicorp",
    "SCCO": "Southern Copper",
    "BVN": "Buenaventura",
    "IFS": "Intercorp Financial",
    "SPY": "S&P 500",
    "EEM": "Mercados emergentes",
    "AGG": "Bonos US agregado",
    "GLD": "Oro",
}
BENCHMARK = "EPU"  # iShares MSCI Peru ETF
RF_ANUAL = 0.04
VENTANA = 36  # meses
PESO_MAX = 0.35


# ---------- datos ----------
def datos_demo(n_meses=144, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    nombres = list(ACTIVOS) + [BENCHMARK]
    mu = np.array([0.010, 0.012, 0.006, 0.008, 0.009, 0.006, 0.003, 0.005, 0.008])
    vol = np.array([0.08, 0.10, 0.13, 0.09, 0.045, 0.055, 0.012, 0.045, 0.07])
    k = len(nombres)
    corr = np.full((k, k), 0.35)
    corr[6, :] = corr[:, 6] = 0.05
    corr[7, :] = corr[:, 7] = 0.10
    corr[-1, :4] = corr[:4, -1] = 0.75
    np.fill_diagonal(corr, 1)
    val, vec = np.linalg.eigh(corr)  # asegurar matriz semidefinida positiva
    corr = vec @ np.diag(np.clip(val, 1e-4, None)) @ vec.T
    d = np.sqrt(np.diag(corr)); corr = corr / np.outer(d, d)
    cov = np.outer(vol, vol) * corr
    r = rng.multivariate_normal(mu, cov, n_meses)
    idx = pd.date_range("2014-01-31", periods=n_meses, freq="ME")
    return pd.DataFrame(r, index=idx, columns=nombres)


def retornos_mensuales(demo: bool) -> pd.DataFrame:
    if demo:
        return datos_demo()
    from common.data import precios
    p = precios(list(ACTIVOS) + [BENCHMARK], start="2012-01-01")
    return p.resample("ME").last().pct_change().dropna()


# ---------- optimizadores ----------
def _restricciones(n):
    return [{"type": "eq", "fun": lambda w: w.sum() - 1}], [(0, PESO_MAX)] * n


def min_varianza(mu, cov):
    n = len(mu)
    cons, bnds = _restricciones(n)
    return minimize(lambda w: w @ cov @ w, np.ones(n) / n, bounds=bnds, constraints=cons).x


def max_sharpe(mu, cov, rf=RF_ANUAL / 12):
    n = len(mu)
    cons, bnds = _restricciones(n)
    f = lambda w: -(w @ mu - rf) / np.sqrt(w @ cov @ w)
    return minimize(f, np.ones(n) / n, bounds=bnds, constraints=cons).x


def paridad_riesgo(mu, cov):
    n = len(mu)
    def f(w):
        rc = w * (cov @ w) / np.sqrt(w @ cov @ w)
        return ((rc - rc.mean()) ** 2).sum()
    return minimize(f, np.ones(n) / n, bounds=[(1e-4, 1)] * n,
                    constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}]).x


def black_litterman(mu, cov, w_mercado, P, Q, tau=0.05, delta=2.5):
    """Combina el equilibrio implícito (pi = delta·Σ·w_m, en exceso sobre rf) con vistas P·r = Q."""
    pi = delta * cov @ w_mercado
    omega = np.diag(np.diag(P @ (tau * cov) @ P.T))
    inv_tc = np.linalg.inv(tau * cov)
    mu_bl = np.linalg.inv(inv_tc + P.T @ np.linalg.inv(omega) @ P) @ (
        inv_tc @ pi + P.T @ np.linalg.inv(omega) @ Q)
    return max_sharpe(mu_bl, cov, rf=0.0)  # mu_bl ya está en exceso sobre rf


def vistas(columnas):
    """Vistas ilustrativas: (1) cobre: SCCO supera a SPY en 0.3% mensual;
    (2) BAP rinde 0.9% mensual en términos absolutos."""
    P = np.zeros((2, len(columnas)))
    P[0, columnas.index("SCCO")], P[0, columnas.index("SPY")] = 1, -1
    P[1, columnas.index("BAP")] = 1
    return P, np.array([0.003, 0.009 - RF_ANUAL / 12])  # Q en exceso sobre rf


# ---------- backtest ----------
def backtest(r: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    activos = list(ACTIVOS)
    estrategias = {"1/N": [], "Mín. varianza": [], "Máx. Sharpe": [],
                   "Paridad de riesgo": [], "Black-Litterman": []}
    fechas, pesos_bl = [], None
    P, Q = vistas(activos)
    for t in range(VENTANA, len(r)):
        hist = r[activos].iloc[t - VENTANA:t]
        mu, cov = hist.mean().values, hist.cov().values
        w = {
            "1/N": np.ones(len(activos)) / len(activos),
            "Mín. varianza": min_varianza(mu, cov),
            "Máx. Sharpe": max_sharpe(mu, cov),
            "Paridad de riesgo": paridad_riesgo(mu, cov),
            "Black-Litterman": black_litterman(mu, cov, np.ones(len(activos)) / len(activos), P, Q),
        }
        pesos_bl = w
        siguiente = r[activos].iloc[t].values
        for k in estrategias:
            estrategias[k].append(float(w[k] @ siguiente))
        fechas.append(r.index[t])
    res = pd.DataFrame(estrategias, index=fechas)
    res[f"Benchmark ({BENCHMARK})"] = r[BENCHMARK].iloc[VENTANA:].values
    return res, pesos_bl


def metricas(res: pd.DataFrame) -> pd.DataFrame:
    acum = (1 + res).cumprod()
    dd = acum / acum.cummax() - 1
    anios = len(res) / 12
    out = pd.DataFrame({
        "Retorno anual": acum.iloc[-1] ** (1 / anios) - 1,
        "Volatilidad anual": res.std() * np.sqrt(12),
    })
    out["Sharpe"] = (out["Retorno anual"] - RF_ANUAL) / out["Volatilidad anual"]
    out["Máx. drawdown"] = dd.min()
    return out


def frontera(mu, cov, n=40):
    objetivos = np.linspace(mu.min(), mu.max(), n)
    vols = []
    for m in objetivos:
        cons = [{"type": "eq", "fun": lambda w: w.sum() - 1},
                {"type": "eq", "fun": lambda w, m=m: w @ mu - m}]
        sol = minimize(lambda w: w @ cov @ w, np.ones(len(mu)) / len(mu),
                       bounds=[(0, 1)] * len(mu), constraints=cons)
        vols.append(np.sqrt(sol.fun) if sol.success else np.nan)
    return np.array(vols) * np.sqrt(12), objetivos * 12


def graficos(r, res, pesos):
    SALIDA.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    (1 + res).cumprod().plot(ax=ax, lw=1.6)
    ax.set_title("Backtest fuera de muestra (rebalanceo mensual)")
    ax.set_ylabel("Crecimiento de 1 unidad")
    ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(SALIDA / "backtest.png", dpi=150); plt.close(fig)

    activos = list(ACTIVOS)
    hist = r[activos].iloc[-VENTANA:]
    mu, cov = hist.mean().values, hist.cov().values
    vol_f, ret_f = frontera(mu, cov)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(vol_f, ret_f, color="#2E5C8A", lw=2, label="Frontera eficiente")
    ax.scatter(np.sqrt(np.diag(cov) * 12), mu * 12, color="grey")
    for i, a in enumerate(activos):
        ax.annotate(a, (np.sqrt(cov[i, i] * 12), mu[i] * 12), fontsize=8)
    for nombre, m in [("Máx. Sharpe", "*"), ("Mín. varianza", "D"), ("Black-Litterman", "P")]:
        w = pesos[nombre]
        ax.scatter(np.sqrt(w @ cov @ w * 12), w @ mu * 12, marker=m, s=120, label=nombre)
    ax.set_xlabel("Volatilidad anual"); ax.set_ylabel("Retorno anual esperado")
    ax.set_title("Frontera eficiente (últimos 36 meses)")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(SALIDA / "frontera.png", dpi=150); plt.close(fig)

    pd.DataFrame(pesos, index=activos).round(3).to_csv(SALIDA / "pesos_actuales.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    r = retornos_mensuales(args.demo)
    res, pesos = backtest(r)
    m = metricas(res)
    fmt = m.copy()
    for c in fmt:
        fmt[c] = fmt[c].map(lambda x: f"{x:.2f}") if c == "Sharpe" else fmt[c].map(lambda x: f"{x:.1%}")
    print(fmt.to_string())
    print("\nPesos actuales:\n", pd.DataFrame(pesos, index=list(ACTIVOS)).round(3).to_string())
    graficos(r, res, pesos)
    m.to_csv(SALIDA / "metricas.csv")


if __name__ == "__main__":
    main()
