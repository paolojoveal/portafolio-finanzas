"""Optimización de portafolio con activos ligados al Perú y diversificadores globales.

Cinco estrategias, evaluadas fuera de muestra (ventana móvil de 36 meses, rebalanceo mensual):
    - Pesos iguales (1/N)
    - Mínima varianza
    - Máximo Sharpe (Markowitz)
    - Paridad de riesgo
    - Black-Litterman: punto de partida neutral (1/N) más dos vistas del analista

Los pesos de cada mes se calculan solo con retornos anteriores a ese mes. La covarianza se
estima con contracción de Ledoit-Wolf, los resultados se reportan netos de costos de
transacción y un activo entra al universo recién cuando completa los 36 meses de historia.

Uso:
    python optimizacion.py          # precios reales (Yahoo Finance)
    python optimizacion.py --demo   # retornos simulados, sin conexión
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))

from common import estilo  # noqa: E402

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
BENCHMARK = "EPU"       # iShares MSCI Peru ETF
RF_ANUAL = 0.04
VENTANA = 36            # meses de historia para estimar
PESO_MAX = 0.35         # tope por activo en mínima varianza, máximo Sharpe y Black-Litterman
COSTO_PB = 10           # costo por cada unidad de portafolio rotada, en puntos básicos
ESTRATEGIAS = ["1/N", "Mín. varianza", "Máx. Sharpe", "Paridad de riesgo", "Black-Litterman"]


# ---------- datos ----------
def datos_demo(n_meses: int = 144, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    nombres = [*ACTIVOS, BENCHMARK]
    mu = np.array([0.010, 0.012, 0.006, 0.008, 0.009, 0.006, 0.003, 0.005, 0.008])
    vol = np.array([0.08, 0.10, 0.13, 0.09, 0.045, 0.055, 0.012, 0.045, 0.07])
    k = len(nombres)
    corr = np.full((k, k), 0.35)
    corr[6, :] = corr[:, 6] = 0.05
    corr[7, :] = corr[:, 7] = 0.10
    corr[-1, :4] = corr[:4, -1] = 0.75
    np.fill_diagonal(corr, 1)
    val, vec = np.linalg.eigh(corr)                      # asegurar matriz definida positiva
    corr = vec @ np.diag(np.clip(val, 1e-4, None)) @ vec.T
    d = np.sqrt(np.diag(corr))
    cov = np.outer(vol, vol) * corr / np.outer(d, d)
    idx = pd.date_range("2014-01-31", periods=n_meses, freq="ME")
    return pd.DataFrame(rng.multivariate_normal(mu, cov, n_meses), index=idx, columns=nombres)


def a_mensual(p: pd.DataFrame) -> pd.DataFrame:
    """Retornos mensuales a partir de precios diarios. Descarta el mes en curso si está incompleto."""
    mensual = p.resample("ME").last()
    if (mensual.index[-1] - p.index[-1]).days > 3:
        mensual = mensual.iloc[:-1]
    return mensual.pct_change(fill_method=None).iloc[1:]


def retornos_mensuales(demo: bool) -> pd.DataFrame:
    if demo:
        return datos_demo()
    from common.data import precios
    return a_mensual(precios([*ACTIVOS, BENCHMARK], start="2012-01-01"))


# ---------- estimación y optimizadores ----------
def covarianza(hist: np.ndarray) -> np.ndarray:
    """Covarianza con contracción de Ledoit-Wolf: con 36 meses y 8 activos la matriz muestral
    tiene mucho error de estimación, y los optimizadores lo amplifican."""
    return LedoitWolf().fit(hist).covariance_


def _optimizar(objetivo, n: int, cotas) -> np.ndarray:
    sol = minimize(objetivo, np.full(n, 1 / n), bounds=cotas, method="SLSQP",
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}],
                   options={"maxiter": 500, "ftol": 1e-12})
    if not sol.success:
        raise RuntimeError(sol.message)
    return sol.x


def min_varianza(mu: np.ndarray, cov: np.ndarray, peso_max: float = PESO_MAX) -> np.ndarray:
    n = len(mu)
    return _optimizar(lambda w: 1e4 * w @ cov @ w, n, [(0, peso_max)] * n)


def max_sharpe(mu: np.ndarray, cov: np.ndarray, rf: float = RF_ANUAL / 12, peso_max: float = PESO_MAX) -> np.ndarray:
    n = len(mu)
    return _optimizar(lambda w: -(w @ mu - rf) / np.sqrt(w @ cov @ w), n, [(0, peso_max)] * n)


def paridad_riesgo(mu: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Cada activo aporta el mismo riesgo. Se resuelve el problema convexo equivalente
    min 0.5·y'Σy - (1/n)·Σ ln(y_i) y se normaliza (Spinu, 2013); no usa `mu`."""
    n = len(mu)
    escala = 1 / np.sqrt(np.diag(cov).mean())            # lleva la solución a un orden de magnitud cercano a 1
    sol = minimize(lambda y: 0.5 * y @ cov @ y - np.log(y).mean(), np.full(n, escala),
                   jac=lambda y: cov @ y - 1 / (n * y), bounds=[(1e-8, None)] * n, method="L-BFGS-B")
    if not sol.success:
        raise RuntimeError(sol.message)
    return sol.x / sol.x.sum()


def retornos_black_litterman(cov: np.ndarray, w_previo: np.ndarray, P: np.ndarray, Q: np.ndarray,
                             tau: float = 0.05, delta: float = 2.5) -> np.ndarray:
    """Retornos esperados (en exceso) que combinan los implícitos en `w_previo` (pi = delta·Σ·w)
    con las vistas P·mu = Q. La incertidumbre de cada vista es proporcional a su varianza."""
    pi = delta * cov @ w_previo
    if len(Q) == 0:
        return pi
    omega = np.diag(np.diag(P @ (tau * cov) @ P.T))
    inv_tc = np.linalg.inv(tau * cov)
    inv_om = np.linalg.inv(omega)
    return np.linalg.solve(inv_tc + P.T @ inv_om @ P, inv_tc @ pi + P.T @ inv_om @ Q)


def vistas(columnas: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Vistas ilustrativas, en exceso sobre la tasa libre de riesgo:
    (1) SCCO rinde 0.3% mensual más que SPY (tesis: ciclo del cobre);
    (2) BAP rinde 0.9% mensual en términos absolutos."""
    P = np.zeros((2, len(columnas)))
    P[0, columnas.index("SCCO")], P[0, columnas.index("SPY")] = 1, -1
    P[1, columnas.index("BAP")] = 1
    return P, np.array([0.003, 0.009 - RF_ANUAL / 12])


def pesos(hist: pd.DataFrame) -> dict[str, np.ndarray]:
    """Pesos de las cinco estrategias a partir de una ventana de retornos (sin datos faltantes)."""
    columnas = list(hist.columns)
    n = len(columnas)
    mu, cov = hist.mean().to_numpy(), covarianza(hist.to_numpy())
    igual = np.full(n, 1 / n)
    P, Q = vistas(columnas)
    mu_bl = retornos_black_litterman(cov, igual, P, Q)
    return {"1/N": igual, "Mín. varianza": min_varianza(mu, cov), "Máx. Sharpe": max_sharpe(mu, cov),
            "Paridad de riesgo": paridad_riesgo(mu, cov), "Black-Litterman": max_sharpe(mu_bl, cov, rf=0.0)}


# ---------- backtest ----------
def backtest(r: pd.DataFrame, costo_pb: float = COSTO_PB) -> dict:
    """Devuelve retornos netos y brutos por estrategia, rotación mensual y los últimos pesos."""
    activos = [a for a in ACTIVOS if a in r.columns]
    netos, brutos, rotacion, fechas = [], [], [], []
    previos = {e: pd.Series(0.0, index=activos) for e in ESTRATEGIAS}
    fallas = 0
    for t in range(VENTANA, len(r)):
        ventana = r[activos].iloc[t - VENTANA:t]
        disponibles = [a for a in activos if ventana[a].notna().all() and pd.notna(r[a].iloc[t])]
        try:
            w_mes = pesos(ventana[disponibles])
        except RuntimeError:                              # el optimizador no convergió: se mantiene 1/N ese mes
            fallas += 1
            w_mes = {e: np.full(len(disponibles), 1 / len(disponibles)) for e in ESTRATEGIAS}
        r_mes = r[activos].iloc[t].fillna(0.0)
        fila_n, fila_b, fila_r = {}, {}, {}
        for e in ESTRATEGIAS:
            w = pd.Series(w_mes[e], index=disponibles).reindex(activos).fillna(0.0)
            fila_r[e] = float((w - previos[e]).abs().sum())           # compras + ventas, como fracción del portafolio
            fila_b[e] = float(w @ r_mes)
            fila_n[e] = fila_b[e] - fila_r[e] * costo_pb / 1e4
            previos[e] = w * (1 + r_mes) / (1 + fila_b[e])            # pesos después del movimiento de precios
        netos.append(fila_n); brutos.append(fila_b); rotacion.append(fila_r); fechas.append(r.index[t])
        ultimos = {e: pd.Series(w_mes[e], index=disponibles).reindex(activos).fillna(0.0) for e in ESTRATEGIAS}
    idx = pd.DatetimeIndex(fechas, name="fecha")
    neto = pd.DataFrame(netos, index=idx)
    neto[f"Benchmark ({BENCHMARK})"] = r[BENCHMARK].iloc[VENTANA:].to_numpy()
    rot = pd.DataFrame(rotacion, index=idx)
    rot.iloc[0] = np.nan                                   # el primer mes es la compra inicial, no rotación
    return {"neto": neto, "bruto": pd.DataFrame(brutos, index=idx), "rotacion": rot,
            "pesos": pd.DataFrame(ultimos), "fallas": fallas}


def metricas(res: pd.DataFrame, rotacion: pd.DataFrame | None = None) -> pd.DataFrame:
    acum = (1 + res).cumprod()
    out = pd.DataFrame({
        "Retorno anual": acum.iloc[-1] ** (12 / len(res)) - 1,
        "Volatilidad anual": res.std() * np.sqrt(12),
        "Sharpe": (res.mean() - RF_ANUAL / 12) / res.std() * np.sqrt(12),
        "Máx. caída": (acum / acum.cummax() - 1).min(),
    })
    if rotacion is not None:
        out["Rotación anual"] = (rotacion.mean() * 12).reindex(out.index)
    return out


def frontera(mu: np.ndarray, cov: np.ndarray, peso_max: float = PESO_MAX, n: int = 40):
    """Frontera eficiente con las mismas restricciones que las estrategias (sin ventas en corto, tope por activo)."""
    k = len(mu)
    w_mv = min_varianza(mu, cov, peso_max)
    orden = np.argsort(mu)[::-1]                          # mayor retorno posible respetando el tope
    w_tope, queda = np.zeros(k), 1.0
    for i in orden:
        w_tope[i] = min(peso_max, queda)
        queda -= w_tope[i]
    vols, rets = [], []
    for m in np.linspace(w_mv @ mu, w_tope @ mu, n):
        sol = minimize(lambda w: 1e4 * w @ cov @ w, np.full(k, 1 / k), bounds=[(0, peso_max)] * k, method="SLSQP",
                       constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1},
                                    {"type": "eq", "fun": lambda w, m=m: 1e2 * (w @ mu - m)}],
                       options={"maxiter": 500, "ftol": 1e-12})
        if sol.success:
            vols.append(np.sqrt(sol.x @ cov @ sol.x) * np.sqrt(12))
            rets.append(m * 12)
    return np.array(vols), np.array(rets)


# ---------- figuras ----------
def figura_backtest(neto: pd.DataFrame, pie: str):
    fig, ax = plt.subplots(figsize=estilo.ANCHO)
    acum = (1 + neto).cumprod()
    inicio = acum.index[0] - pd.offsets.MonthEnd()
    acum = pd.concat([pd.DataFrame(1.0, index=[inicio], columns=acum.columns), acum])
    ref = f"Benchmark ({BENCHMARK})"
    ax.plot(acum.index, acum[ref], color=estilo.CONTEXTO, lw=2, label=f"MSCI Peru ({BENCHMARK}), referencia")
    for e, color in zip(ESTRATEGIAS, estilo.SERIE):
        ax.plot(acum.index, acum[e], color=color, label=e)
        estilo.punto_final(ax, acum.index[-1], acum[e].iloc[-1], color)
    estilo.titulo(ax, "Crecimiento de 1 unidad invertida, fuera de muestra",
                  f"Rebalanceo mensual, neto de {COSTO_PB} pb de costo por unidad rotada")
    ax.legend(loc="upper left", ncol=2)
    return estilo.guardar(fig, SALIDA / "backtest.png", pie)


def figura_frontera(r: pd.DataFrame, pesos_actuales: pd.DataFrame, pie: str):
    hist = r[[a for a in ACTIVOS if a in r.columns]].iloc[-VENTANA:].dropna(axis=1)
    mu, cov = hist.mean().to_numpy(), covarianza(hist.to_numpy())
    vol_f, ret_f = frontera(mu, cov)
    fig, ax = plt.subplots(figsize=estilo.CUADRADO)
    ax.plot(vol_f * 100, ret_f * 100, color=estilo.AZUL, label=f"Frontera eficiente (tope de {PESO_MAX:.0%} por activo)")
    ax.scatter(np.sqrt(np.diag(cov) * 12) * 100, mu * 1200, s=36, color=estilo.CONTEXTO, zorder=3, label="Activos individuales")
    for i, a in enumerate(hist.columns):
        estilo.etiqueta(ax, np.sqrt(cov[i, i] * 12) * 100, mu[i] * 1200, a, dx=6, fontsize=8.5)
    for e, color, marca in [("Mín. varianza", estilo.NARANJA, "D"), ("Máx. Sharpe", estilo.AGUA, "s"),
                            ("Paridad de riesgo", estilo.AMARILLO, "^")]:
        w = pesos_actuales[e].reindex(hist.columns).to_numpy()
        ax.scatter(np.sqrt(w @ cov @ w * 12) * 100, w @ mu * 1200, marker=marca, s=130 if marca == "^" else 95, color=color,
                   edgecolor=estilo.SUPERFICIE, linewidth=2, zorder=5, label=e)
    ax.set_xlabel("Volatilidad anual")
    ax.set_ylabel("Retorno anual esperado")
    estilo.formato_pct(ax, "x")
    estilo.formato_pct(ax, "y")
    ax.grid(axis="x", visible=True)
    estilo.titulo(ax, "Frontera eficiente con los últimos 36 meses",
                  "Retorno esperado = promedio histórico de la ventana (ruidoso por construcción)")
    ax.legend(loc="lower right")
    return estilo.guardar(fig, SALIDA / "frontera.png", pie)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--demo", action="store_true", help="usa retornos simulados (sin conexión)")
    ap.add_argument("--costo-pb", type=float, default=COSTO_PB, help="costo de transacción en puntos básicos")
    args = ap.parse_args()
    estilo.aplicar()
    pd.set_option("display.width", 200)
    r = retornos_mensuales(args.demo)
    bt = backtest(r, args.costo_pb)
    neto = bt["neto"]
    print(f"Retornos mensuales: {r.index[0]:%Y-%m} a {r.index[-1]:%Y-%m}. Evaluación fuera de muestra: "
          f"{neto.index[0]:%Y-%m} a {neto.index[-1]:%Y-%m} ({len(neto)} meses)" + (" · DATOS SIMULADOS" if args.demo else ""))
    tardios = [a for a in ACTIVOS if a in r.columns and r[a].isna().any()]
    if tardios:
        print("Entran al universo al completar 36 meses de historia: "
              + ", ".join(f"{a} (cotiza desde {r[a].first_valid_index():%Y-%m})" for a in tardios))
    if bt["fallas"]:
        print(f"Aviso: el optimizador no convergió en {bt['fallas']} meses; en esos meses se usó 1/N.")

    m = metricas(neto, bt["rotacion"])
    fmt = m.copy()
    for c in fmt:
        fmt[c] = fmt[c].map(lambda x, c=c: "" if pd.isna(x) else (f"{x:.2f}" if c == "Sharpe" else f"{x:.1%}"))
    print(f"\nResultados netos de costos ({args.costo_pb:.0f} pb por unidad rotada):")
    print(fmt.to_string())
    print(f"\nPesos vigentes (estimados con datos hasta {r.index[-1]:%Y-%m}):")
    print(bt["pesos"].round(3).to_string())

    SALIDA.mkdir(exist_ok=True)
    pie = ("Datos simulados (modo demo)." if args.demo else
           f"Fuente: Yahoo Finance, precios ajustados. Evaluación de {neto.index[0]:%m/%Y} a {neto.index[-1]:%m/%Y}. Elaboración propia.")
    figura_backtest(neto, pie)
    figura_frontera(r, bt["pesos"], pie)
    m.to_csv(SALIDA / "metricas.csv")
    bt["pesos"].round(4).to_csv(SALIDA / "pesos_actuales.csv")
    print(f"\nFiguras y tablas en {SALIDA.relative_to(AQUI.parent)}/")


if __name__ == "__main__":
    main()
