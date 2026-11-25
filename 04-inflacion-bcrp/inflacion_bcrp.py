"""Inflación y política monetaria en el Perú con datos del BCRP.

1. Regla de Taylor con suavizamiento de tasas, estimada por MCO:
       i_t = rho·i_{t-1} + (1-rho)·[r* + pi_e + phi_pi·(pi_t - 2%) + phi_y·brecha_t] + e_t
2. Modelo VAR (inflación, tasa de referencia, depreciación, crecimiento del PBI):
       - selección de rezagos por AIC, funciones impulso-respuesta
       - pronóstico de inflación a 12 meses con bandas
3. Comparación de la tasa observada vs. la tasa "sugerida" por la regla.

Uso:
    python inflacion_bcrp.py          # descarga series de la API del BCRP
    python inflacion_bcrp.py --demo   # datos simulados con la dinámica típica peruana
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.api import VAR
from statsmodels.tsa.filters.hp_filter import hpfilter

AQUI = Path(__file__).resolve().parent
sys.path.append(str(AQUI.parent))
SALIDA = AQUI / "resultados"
META = 2.0  # punto medio del rango meta del BCRP (1% – 3%)


def datos_demo(seed=11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2005-01-01", "2026-09-01", freq="MS")
    n = len(idx)
    pbi = np.zeros(n); inf = np.zeros(n); tasa = np.zeros(n); dep = np.zeros(n)
    pbi[0], inf[0], tasa[0] = 5.0, 2.0, 3.0
    for t in range(1, n):
        dep[t] = 0.3 * dep[t - 1] + rng.normal(0, 2.0)
        pbi[t] = 1.2 + 0.75 * pbi[t - 1] - 0.15 * (tasa[t - 1] - inf[t - 1] - 1.5) + rng.normal(0, 1.2)
        inf[t] = 0.25 + 0.88 * inf[t - 1] + 0.03 * dep[t - 1] + 0.02 * pbi[t - 1] + rng.normal(0, 0.25)
        obj = 1.5 + inf[t] + 0.8 * (inf[t] - META) + 0.3 * (pbi[t] - 3.5)
        tasa[t] = max(0.25, 0.85 * tasa[t - 1] + 0.15 * obj + rng.normal(0, 0.1))
    # choque tipo pandemia y alza inflacionaria 2021-2023
    i20 = idx.get_loc(pd.Timestamp("2020-04-01")); i21 = idx.get_loc(pd.Timestamp("2021-06-01"))
    pbi[i20:i20 + 3] -= [30, 25, 15]
    inf[i21:i21 + 24] += np.concatenate([np.linspace(0, 5, 12), np.linspace(5, 0, 12)])
    tipo_cambio = 3.3 * np.exp(np.cumsum(dep / 100 / 12))
    return pd.DataFrame({"ipc_var12m": inf, "tasa_referencia": tasa,
                         "tipo_cambio": tipo_cambio, "pbi_var": pbi}, index=idx)


def cargar(demo: bool) -> pd.DataFrame:
    if demo:
        return datos_demo()
    from common.data import bcrp_series
    return bcrp_series(["ipc_var12m", "tasa_referencia", "tipo_cambio", "pbi_var"],
                       start="2005-1").dropna()


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["depreciacion_12m"] = d["tipo_cambio"].pct_change(12) * 100
    # índice de actividad aproximado a partir del crecimiento interanual -> brecha por filtro HP
    nivel = np.log(100) + (np.log1p(d["pbi_var"] / 100) / 12).cumsum()
    ciclo, _ = hpfilter(nivel, lamb=14400)
    d["brecha_producto"] = ciclo * 100
    return d.dropna()


def regla_taylor(d: pd.DataFrame):
    y = d["tasa_referencia"]
    X = pd.DataFrame({
        "tasa_rezagada": d["tasa_referencia"].shift(1),
        "desvio_inflacion": d["ipc_var12m"] - META,
        "brecha_producto": d["brecha_producto"],
    })
    X = sm.add_constant(X).dropna()
    mod = sm.OLS(y.loc[X.index], X).fit(cov_type="HAC", cov_kwds={"maxlags": 6})
    rho = mod.params["tasa_rezagada"]
    largo_plazo = {
        "rho (suavizamiento)": rho,
        "phi_pi (respuesta a inflación)": mod.params["desvio_inflacion"] / (1 - rho),
        "phi_y (respuesta a brecha)": mod.params["brecha_producto"] / (1 - rho),
        "tasa neutral implícita": mod.params["const"] / (1 - rho),
    }
    sugerida = (mod.params["const"] + mod.params["desvio_inflacion"] * X["desvio_inflacion"]
                + mod.params["brecha_producto"] * X["brecha_producto"]) / (1 - rho)
    return mod, largo_plazo, sugerida


def modelo_var(d: pd.DataFrame, horizonte=12):
    cols = ["pbi_var", "depreciacion_12m", "ipc_var12m", "tasa_referencia"]  # orden de Cholesky
    # Todas las variables son tasas de variación; bajo metas de inflación se tratan como
    # estacionarias (verificar con ADF: ver `pruebas_adf`).
    datos = d[cols]
    sel = VAR(datos).select_order(maxlags=6)
    p = max(1, sel.aic)
    res = VAR(datos).fit(p)
    fc, lo, hi = res.forecast_interval(datos.values[-p:], steps=horizonte, alpha=0.1)
    fechas = pd.date_range(d.index[-1] + pd.offsets.MonthBegin(), periods=horizonte, freq="MS")
    df = lambda m: pd.DataFrame(m, index=fechas, columns=cols)
    return res, p, df(fc), df(lo), df(hi)


def pruebas_adf(d: pd.DataFrame) -> pd.Series:
    from statsmodels.tsa.stattools import adfuller
    cols = ["pbi_var", "depreciacion_12m", "ipc_var12m", "tasa_referencia"]
    return pd.Series({c: adfuller(d[c], autolag="AIC", result_object=False)[1] for c in cols}, name="p-valor ADF")


def graficos(d, sugerida, res_var, fc, lo, hi):
    SALIDA.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(d.index, d["tasa_referencia"], label="Tasa de referencia BCRP", color="#2E5C8A")
    ax.plot(sugerida.index, sugerida, label="Tasa sugerida por la regla de Taylor", color="#C0392B", ls="--")
    ax.plot(d.index, d["ipc_var12m"], label="Inflación 12m", color="grey", alpha=0.7)
    ax.axhspan(1, 3, color="green", alpha=0.08, label="Rango meta 1%–3%")
    ax.set_ylabel("%"); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set_title("Política monetaria del BCRP vs. regla de Taylor")
    fig.tight_layout(); fig.savefig(SALIDA / "regla_taylor.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4))
    hist = d["ipc_var12m"].iloc[-48:]
    ax.plot(hist.index, hist, color="#2E5C8A", label="Observada")
    ax.plot(fc.index, fc["ipc_var12m"], color="#C0392B", label="Pronóstico VAR")
    ax.fill_between(fc.index, lo["ipc_var12m"], hi["ipc_var12m"], color="#C0392B", alpha=0.15, label="Banda 90%")
    ax.axhspan(1, 3, color="green", alpha=0.08)
    ax.set_title("Pronóstico de inflación a 12 meses"); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(SALIDA / "pronostico_inflacion.png", dpi=150); plt.close(fig)

    irf = res_var.irf(24)
    fig = irf.plot(impulse="tasa_referencia", response="ipc_var12m", orth=True, figsize=(7, 4))
    fig.suptitle("Respuesta de la inflación a un choque de política monetaria")
    fig.tight_layout(); fig.savefig(SALIDA / "irf_tasa_inflacion.png", dpi=150); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    d = preparar(cargar(args.demo))
    mod, lp, sugerida = regla_taylor(d)
    print(mod.summary().tables[1])
    print("\nParámetros de largo plazo de la regla de Taylor:")
    for k, v in lp.items():
        print(f"  {k:32s} {v:6.2f}")
    print("  (Principio de Taylor: phi_pi > 1, es decir, la tasa real sube cuando sube la inflación)")
    print("\nPruebas de raíz unitaria (H0: no estacionaria):")
    print(pruebas_adf(d).round(3).to_string())
    res, p, fc, lo, hi = modelo_var(d)
    print(f"\nVAR con {p} rezagos (AIC). Pronóstico de inflación 12m:")
    print(pd.DataFrame({"pronóstico": fc["ipc_var12m"], "banda_inf": lo["ipc_var12m"],
                        "banda_sup": hi["ipc_var12m"]}).round(2).to_string())
    graficos(d, sugerida, res, fc, lo, hi)
    fc.to_csv(SALIDA / "pronostico_var.csv")


if __name__ == "__main__":
    main()
