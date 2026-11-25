"""Inflación y política monetaria en el Perú con datos del BCRP.

Tres preguntas, cada una con su figura:

1. ¿Cómo fija su tasa el BCRP? Regla de Taylor con suavizamiento, por MCO con errores HAC:
       i_t = c + rho·i_{t-1} + a·(pi_t - 2) + b·brecha_t + e_t
   Se reportan los coeficientes de largo plazo phi_pi = a/(1-rho) y phi_y = b/(1-rho), con
   errores estándar por el método delta, usando la inflación observada y las expectativas a
   12 meses, con y sin el periodo en que la tasa estuvo en su mínimo de 0.25%.
2. ¿Qué pasa con la inflación después de un alza de la tasa? VAR recursivo (brecha, inflación,
   expectativas, tasa, depreciación) estimado sin los meses de cierre de 2020. Funciones impulso-respuesta
   con bandas de 90% por bootstrap.
3. ¿Hacia dónde va la inflación? Pronóstico a 12 meses con bandas, y una evaluación fuera de
   muestra contra el pronóstico ingenuo (la inflación se queda donde está).

Uso:
    python inflacion_bcrp.py          # descarga las series de la API del BCRP
    python inflacion_bcrp.py --demo   # economía simulada con parámetros conocidos
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.filters.hp_filter import hpfilter
from statsmodels.tsa.stattools import adfuller

AQUI = Path(__file__).resolve().parent
sys.path[:0] = [str(AQUI), str(AQUI.parent)]

import var_recursivo as var  # noqa: E402
from common import estilo  # noqa: E402

SALIDA = AQUI / "resultados"
META, META_MIN, META_MAX = 2.0, 1.0, 3.0            # rango meta del BCRP y su punto medio
TASA_MINIMA = ("2020-03-01", "2021-07-01")           # tasa en 0.25%: fuera de una regla lineal
CIERRES = ("2020-03-01", "2020-12-01")               # meses que no entran en la estimación del VAR
SIN_TENDENCIA = ("2020-03-01", "2021-02-01")         # meses que no entran al estimar la tendencia del PBI
# Orden de Cholesky: la tasa reacciona en el mismo mes a la actividad, los precios y las expectativas;
# el tipo de cambio reacciona en el mismo mes a todo. Las expectativas van antes de la tasa porque son
# la información con la que el BCRP decide (sin ellas el VAR confunde esa reacción con un choque).
ORDEN = ["brecha_producto", "ipc_var12m", "expectativas_inf_12m", "tasa_referencia", "depreciacion_12m"]
SIN_EXPECTATIVAS = [v for v in ORDEN if v != "expectativas_inf_12m"]
ETIQUETAS = {"brecha_producto": "Brecha del producto (%)", "ipc_var12m": "Inflación 12 meses (pp)",
             "expectativas_inf_12m": "Expectativas de inflación a 12 meses (pp)",
             "tasa_referencia": "Tasa de referencia (pp)", "depreciacion_12m": "Depreciación 12 meses (pp)"}
SERIES = ["ipc_var12m", "expectativas_inf_12m", "tasa_referencia", "tipo_cambio", "pbi_var12m", "pbi_indice_sa"]

# Parámetros verdaderos de la economía simulada (las pruebas verifican que la estimación los recupera)
DEMO = {"rho": 0.90, "phi_pi": 1.5, "phi_y": 0.5, "tasa_real_neutral": 1.5}


# ---------- datos ----------
def datos_demo(seed: int = 11, pandemia: bool = True) -> pd.DataFrame:
    """Economía simulada: curva IS, curva de Phillips y una regla de Taylor con parámetros DEMO."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2003-01-01", "2026-09-01", freq="MS")
    n = len(idx)
    rho, phi_pi, phi_y, r_n = DEMO["rho"], DEMO["phi_pi"], DEMO["phi_y"], DEMO["tasa_real_neutral"]
    cierre = pd.Series(0.0, index=idx)
    if pandemia:
        cierre.loc["2020-03-01":"2020-09-01"] = [-15.0, -40.0, -30.0, -14.0, -7.0, -4.0, -2.0]
    brecha = np.zeros(n)
    inf = np.full(n, META)
    tasa = np.full(n, r_n + META)
    ds = np.zeros(n)                                   # variación % mensual del tipo de cambio
    for t in range(2, n):
        ds[t] = 0.25 * ds[t - 1] - 0.6 * (tasa[t - 1] - tasa[t - 2]) + rng.normal(0, 1.0)
        dep12 = ds[max(0, t - 12):t].sum()
        brecha[t] = 0.90 * brecha[t - 1] - 0.08 * (tasa[t - 1] - inf[t - 1] - r_n) + rng.normal(0, 0.35)
        inf[t] = META + 0.93 * (inf[t - 1] - META) + 0.05 * brecha[t - 1] + 0.008 * dep12 + rng.normal(0, 0.16)
        objetivo = r_n + META + phi_pi * (inf[t] - META) + phi_y * (brecha[t] + cierre.iloc[t])
        tasa[t] = max(0.25, rho * tasa[t - 1] + (1 - rho) * objetivo + rng.normal(0, 0.08))
    indice = 100 * np.exp(0.0035 * np.arange(n) + (brecha + cierre.to_numpy()) / 100)
    df = pd.DataFrame({
        "ipc_var12m": inf,
        "expectativas_inf_12m": META + 0.45 * (inf - META) + rng.normal(0, 0.06, n),
        "tasa_referencia": tasa,
        "tipo_cambio": 3.4 * np.exp(np.cumsum(ds / 100)),
        "pbi_indice_sa": indice,
    }, index=idx)
    df["pbi_var12m"] = df["pbi_indice_sa"].pct_change(12, fill_method=None) * 100
    return df[SERIES]


def cargar(demo: bool) -> pd.DataFrame:
    if demo:
        return datos_demo()
    from common.data import bcrp_series
    return bcrp_series(SERIES, start="2003-1")


def brecha_producto(indice_sa: pd.Series, lamb: float = 14400) -> pd.Series:
    """Brecha = 100·(log PBI desestacionalizado - tendencia HP).

    La tendencia se estima sin los meses de cierre de la pandemia (se interpolan): si entran al
    filtro, la caída de 2020 arrastra la tendencia hacia abajo y aparece una brecha positiva
    ficticia de 5 a 6% justo antes de marzo de 2020.
    """
    y = np.log(indice_sa.dropna())
    y_tendencia = y.copy()
    y_tendencia.loc[SIN_TENDENCIA[0]:SIN_TENDENCIA[1]] = np.nan
    _, tendencia = hpfilter(y_tendencia.interpolate(), lamb=lamb)
    return ((y - tendencia) * 100).rename("brecha_producto")


def preparar(df: pd.DataFrame, lamb: float = 14400) -> pd.DataFrame:
    d = df.copy()
    d["brecha_producto"] = brecha_producto(d["pbi_indice_sa"], lamb)
    d["depreciacion_12m"] = d["tipo_cambio"].pct_change(12, fill_method=None) * 100
    return d.dropna(subset=ORDEN)


# ---------- 1. regla de Taylor ----------
def regla_taylor(d: pd.DataFrame, inflacion: str = "ipc_var12m", sin_tasa_minima: bool = False) -> dict:
    X = pd.DataFrame({"const": 1.0, "tasa_rezagada": d["tasa_referencia"].shift(1),
                      "desvio_inflacion": d[inflacion] - META,
                      "brecha_producto": d["brecha_producto"]}).dropna()
    y = d["tasa_referencia"].loc[X.index]
    if sin_tasa_minima:
        fuera = (X.index >= TASA_MINIMA[0]) & (X.index <= TASA_MINIMA[1])
        X, y = X[~fuera], y[~fuera]
    res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 12})
    b, V = res.params, res.cov_params()
    rho = b["tasa_rezagada"]

    def largo_plazo(nombre: str) -> tuple[float, float]:
        """Coeficiente / (1 - rho) y su error estándar por el método delta."""
        grad = pd.Series(0.0, index=b.index)
        grad[nombre] = 1 / (1 - rho)
        grad["tasa_rezagada"] = b[nombre] / (1 - rho) ** 2
        return b[nombre] / (1 - rho), float(np.sqrt(grad @ V @ grad))

    return {"modelo": res, "n": int(res.nobs), "r2": res.rsquared,
            "rho": (rho, res.bse["tasa_rezagada"]),
            "phi_pi": largo_plazo("desvio_inflacion"),
            "phi_y": largo_plazo("brecha_producto"),
            "tasa_neutral": largo_plazo("const")}


def tabla_taylor(d: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    especificaciones = {
        "Inflación observada": ("ipc_var12m", False),
        "Inflación observada, sin 2020-21": ("ipc_var12m", True),
        "Expectativas a 12 meses": ("expectativas_inf_12m", False),
        "Expectativas a 12 meses, sin 2020-21": ("expectativas_inf_12m", True),
    }
    filas = {"rho": "rho (suavizamiento)", "phi_pi": "phi_pi (respuesta a la inflación)",
             "phi_y": "phi_y (respuesta a la brecha)", "tasa_neutral": "Tasa neutral nominal (%)"}
    estimaciones = {nombre: regla_taylor(d, v, s) for nombre, (v, s) in especificaciones.items()}
    tabla = pd.DataFrame({nombre: {**{etiqueta: f"{e[k][0]:.2f} ({e[k][1]:.2f})" for k, etiqueta in filas.items()},
                                   "Observaciones": str(e["n"])}
                          for nombre, e in estimaciones.items()})
    return tabla, estimaciones


def tasa_sugerida(d: pd.DataFrame, e: dict, inflacion: str) -> pd.Series:
    """Tasa de largo plazo que implica la regla estimada, sin el suavizamiento."""
    return (e["tasa_neutral"][0] + e["phi_pi"][0] * (d[inflacion] - META)
            + e["phi_y"][0] * d["brecha_producto"]).rename("tasa_sugerida")


# ---------- 2 y 3. VAR ----------
def cierres(indice: pd.DatetimeIndex) -> np.ndarray:
    """Marca los meses de cierre de 2020. Las filas del VAR en que uno de esos meses aparece como
    variable dependiente o como rezago no entran en la estimación: una brecha de -40% no informa
    sobre la dinámica normal y, como rezago, arrastraría los coeficientes."""
    return np.asarray((indice >= CIERRES[0]) & (indice <= CIERRES[1]))


def modelo_var(d: pd.DataFrame, max_p: int = 6, p: int | None = None):
    Y, excluir = d[ORDEN].to_numpy(), cierres(d.index)
    criterios = var.seleccionar_rezagos(Y, max_p, excluir)
    p = p or min(criterios["bic"], key=criterios["bic"].get)
    return var.estimar(Y, p, excluir), p, criterios


def respuesta_a_la_tasa(d: pd.DataFrame, p: int, horizonte: int = 36, repeticiones: int = 1000,
                        choque_pb: float = 25, orden: list[str] = ORDEN) -> dict[str, pd.DataFrame]:
    """Respuestas a un alza sorpresiva de la tasa, reescaladas a `choque_pb` puntos básicos en el mes 0."""
    Y = d[orden].to_numpy()
    punto, inf, sup = var.irf_bootstrap(Y, p, horizonte, cierres(d.index), repeticiones=repeticiones)
    j = orden.index("tasa_referencia")
    escala = (choque_pb / 100) / punto[0, j, j]
    meses = pd.RangeIndex(horizonte + 1, name="mes")
    return {v: pd.DataFrame({"respuesta": punto[:, i, j], "inferior": inf[:, i, j], "superior": sup[:, i, j]},
                            index=meses) * escala for i, v in enumerate(orden)}


def pronostico(d: pd.DataFrame, modelo: var.VAR, pasos: int = 12) -> pd.DataFrame:
    fc, lo, hi = var.pronosticar(modelo, d[ORDEN].to_numpy(), pasos)
    fechas = pd.date_range(d.index[-1] + pd.offsets.MonthBegin(), periods=pasos, freq="MS", name="fecha")
    j = ORDEN.index("ipc_var12m")
    return pd.DataFrame({"pronostico": fc[:, j], "banda_inferior": lo[:, j], "banda_superior": hi[:, j]}, index=fechas)


def evaluar_pronostico(d: pd.DataFrame, p: int, inicio: str = "2012-01-01",
                       horizontes: tuple[int, ...] = (1, 3, 6, 12)) -> pd.DataFrame:
    """Evaluación fuera de muestra con ventana creciente: en cada mes desde `inicio` se estima el
    VAR solo con los datos disponibles hasta entonces y se pronostica la inflación. Se compara con
    el pronóstico ingenuo (la inflación dentro de h meses es igual a la de hoy)."""
    Y = d[ORDEN].to_numpy()
    j = ORDEN.index("ipc_var12m")
    excluir = cierres(d.index)
    filas = []
    for t in range(d.index.get_loc(pd.Timestamp(inicio)), len(d) - 1):
        fc, _, _ = var.pronosticar(var.estimar(Y[:t + 1], p, excluir[:t + 1]), Y[:t + 1], max(horizontes))
        desde_cierre = bool(excluir[t - p + 1:t + 1].any())      # el pronóstico parte de un mes de cierre
        for h in horizontes:
            if t + h < len(d):
                filas.append({"h": h, "desde_cierre": desde_cierre,
                              "var": fc[h - 1, j] - Y[t + h, j], "ingenuo": Y[t, j] - Y[t + h, j]})
    e = pd.DataFrame(filas)
    recm = lambda x: float(np.sqrt(np.mean(np.square(x))))
    normal = e[~e["desde_cierre"]].groupby("h")
    tabla = pd.DataFrame({
        "Pronósticos": normal.size(),
        "RECM del VAR (pp)": normal["var"].apply(recm),
        "RECM ingenuo (pp)": normal["ingenuo"].apply(recm),
    })
    tabla["VAR / ingenuo"] = tabla["RECM del VAR (pp)"] / tabla["RECM ingenuo (pp)"]
    todos = e.groupby("h")
    tabla["VAR / ingenuo, con 2020"] = todos["var"].apply(recm) / todos["ingenuo"].apply(recm)
    tabla.index.name = "Horizonte (meses)"
    return tabla


def pruebas_adf(d: pd.DataFrame) -> pd.Series:
    def p_valor(x) -> float:
        with warnings.catch_warnings():               # statsmodels avisa que cambiará el tipo del resultado
            warnings.simplefilter("ignore", FutureWarning)
            r = adfuller(x, autolag="AIC")
        return float(r[1] if isinstance(r, tuple) else r.pvalue)
    return pd.Series({v: p_valor(d[v]) for v in ORDEN}, name="p-valor ADF")


# ---------- figuras ----------
def _sombrear_tasa_minima(ax):
    ax.axvspan(pd.Timestamp(TASA_MINIMA[0]), pd.Timestamp(TASA_MINIMA[1]), color=estilo.GRILLA, alpha=0.6, lw=0)


def figura_taylor(d, sugerida, pie):
    fig, (a, b) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    a.axhspan(META_MIN, META_MAX, color=estilo.AGUA, alpha=0.12, lw=0, label="Rango meta (1% a 3%)")
    a.plot(d.index, d["ipc_var12m"], color=estilo.AZUL, label="Inflación 12 meses")
    a.plot(d.index, d["expectativas_inf_12m"], color=estilo.NARANJA, label="Expectativas a 12 meses")
    estilo.titulo(a, "Inflación y expectativas frente al rango meta", "Variación % 12 meses del IPC de Lima")
    a.legend(loc="upper left", ncol=3)
    estilo.formato_pct(a)
    b.plot(d.index, d["tasa_referencia"], color=estilo.AZUL, label="Tasa de referencia observada")
    b.plot(sugerida.index, sugerida, color=estilo.NARANJA, label="Tasa que sugiere la regla estimada")
    estilo.titulo(b, "Tasa de referencia: observada y sugerida por la regla de Taylor",
                  "La regla se estima sin el periodo sombreado, en que la tasa estuvo en su mínimo")
    b.set_ylim(-1.5, max(float(sugerida.max()), float(d["tasa_referencia"].max())) + 2.5)
    if sugerida.loc[TASA_MINIMA[0]:TASA_MINIMA[1]].min() < -1.5:
        b.annotate("En 2020 la regla\npedía tasas negativas", (pd.Timestamp("2020-06-01"), -1.2),
                   xytext=(pd.Timestamp("2016-09-01"), -0.55), fontsize=8.5, color=estilo.TINTA_2, va="center",
                   arrowprops={"arrowstyle": "-", "color": estilo.TENUE, "lw": 0.8})
    b.legend(loc="upper left", ncol=2)
    estilo.formato_pct(b)
    for ax in (a, b):
        _sombrear_tasa_minima(ax)
    return estilo.guardar(fig, SALIDA / "regla_taylor.png", pie)


def figura_irf(respuestas, pie):
    fig, axs = plt.subplots(2, 2, figsize=(10, 6.4), sharex=True)
    for ax, v in zip(axs.ravel(), ["tasa_referencia", "ipc_var12m", "expectativas_inf_12m", "brecha_producto"]):
        r = respuestas[v]
        ax.axhline(0, color=estilo.EJE, lw=1)
        ax.fill_between(r.index, r["inferior"], r["superior"], color=estilo.AZUL, alpha=0.14, lw=0)
        ax.plot(r.index, r["respuesta"], color=estilo.AZUL)
        ax.set_title(ETIQUETAS[v], fontsize=10.5, loc="left")
    for ax in axs[1]:
        ax.set_xlabel("Meses después del choque")
    fig.suptitle("Respuesta a un alza sorpresiva de 25 pb en la tasa de referencia", x=0.012, y=0.985, ha="left",
                 fontsize=12.5, fontweight="bold")
    fig.text(0.012, 0.925, "VAR recursivo estimado sin los meses de cierre de 2020. Banda: 90% por bootstrap de residuos",
             fontsize=9.5, color=estilo.TINTA_2)
    fig.tight_layout(rect=(0, 0.045, 1, 0.915))
    fig.text(0.012, 0.012, pie, fontsize=8, color=estilo.TENUE)
    fig.savefig(SALIDA / "irf_politica_monetaria.png")
    plt.close(fig)


def figura_pronostico(d, fc, pie):
    fig, ax = plt.subplots(figsize=estilo.ANCHO)
    hist = d["ipc_var12m"].iloc[-60:]
    ax.axhspan(META_MIN, META_MAX, color=estilo.AGUA, alpha=0.12, lw=0, label="Rango meta (1% a 3%)")
    ax.plot(hist.index, hist, color=estilo.AZUL, label="Observada")
    x = fc.index.insert(0, hist.index[-1])
    ax.fill_between(x, np.r_[hist.iloc[-1], fc["banda_inferior"]], np.r_[hist.iloc[-1], fc["banda_superior"]],
                    color=estilo.AZUL, alpha=0.14, lw=0, label="Banda de 90%")
    ax.plot(x, np.r_[hist.iloc[-1], fc["pronostico"]], color=estilo.AZUL, ls=(0, (4, 2)), label="Pronóstico del VAR")
    estilo.punto_final(ax, hist.index[-1], hist.iloc[-1], estilo.AZUL)
    estilo.punto_final(ax, fc.index[-1], fc["pronostico"].iloc[-1], estilo.AZUL)
    estilo.etiqueta(ax, hist.index[-1], hist.iloc[-1], f"{hist.iloc[-1]:.1f}%", dx=-8, dy=11, ha="right")
    estilo.etiqueta(ax, fc.index[-1], fc["pronostico"].iloc[-1], f"{fc['pronostico'].iloc[-1]:.1f}%")
    estilo.titulo(ax, "Inflación: últimos cinco años y pronóstico a 12 meses", "Variación % 12 meses del IPC de Lima")
    ax.legend(loc="upper right", ncol=2)
    ax.set_ylim(None, float(max(hist.max(), fc["banda_superior"].max())) + 1.6)
    ax.margins(x=0.06)
    estilo.formato_pct(ax)
    return estilo.guardar(fig, SALIDA / "pronostico_inflacion.png", pie)


# ---------- programa ----------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--demo", action="store_true", help="usa una economía simulada (sin conexión)")
    ap.add_argument("--lambda-hp", type=float, default=14400, help="suavizamiento del filtro HP (mensual)")
    ap.add_argument("--rezagos", type=int, default=None, help="rezagos del VAR (por defecto, los que elige el BIC)")
    ap.add_argument("--repeticiones", type=int, default=1000, help="repeticiones del bootstrap")
    args = ap.parse_args()
    estilo.aplicar()
    pd.set_option("display.width", 200)
    d = preparar(cargar(args.demo), args.lambda_hp)
    pie = ("Datos simulados (modo demo)." if args.demo else
           f"Fuente: BCRP, series estadísticas. Datos de {d.index[0]:%m/%Y} a {d.index[-1]:%m/%Y}. Elaboración propia.")
    print(f"Muestra: {d.index[0]:%Y-%m} a {d.index[-1]:%Y-%m} ({len(d)} meses)" + (" · DATOS SIMULADOS" if args.demo else ""))

    tabla, est = tabla_taylor(d)
    print("\n1. Regla de Taylor: coeficientes de largo plazo (error estándar entre paréntesis)")
    print(tabla.to_string())
    base = est["Expectativas a 12 meses, sin 2020-21"]
    print("   Principio de Taylor: la tasa real sube cuando sube la inflación solo si phi_pi > 1.")

    modelo, p, criterios = modelo_var(d, p=args.rezagos)
    print("\n2. VAR recursivo. Pruebas de raíz unitaria ADF (H0: la serie tiene raíz unitaria):")
    print(pruebas_adf(d).round(3).to_string())
    print(f"   Rezagos: AIC elige {min(criterios['aic'], key=criterios['aic'].get)}, "
          f"BIC elige {min(criterios['bic'], key=criterios['bic'].get)}; se usan {p}.")
    respuestas = respuesta_a_la_tasa(d, p, repeticiones=args.repeticiones)
    r, tasa = respuestas["ipc_var12m"], respuestas["tasa_referencia"]["respuesta"]
    m_min, m_max = int(r["respuesta"].idxmin()), int(r["respuesta"].idxmax())
    banda = lambda m: f"{r['inferior'].iloc[m]:+.2f} a {r['superior'].iloc[m]:+.2f}"
    print(f"   Un alza sorpresiva de 25 pb suele iniciar un ciclo: la tasa llega a {tasa.max():+.2f} pp en el mes "
          f"{int(tasa.idxmax())} y vuelve a cero hacia el mes {int((tasa.iloc[int(tasa.idxmax()):] <= 0).idxmax())}.")
    print(f"   Inflación: máximo {r['respuesta'].max():+.2f} pp en el mes {m_max} (banda de 90%: {banda(m_max)}); "
          f"mínimo {r['respuesta'].min():+.2f} pp en el mes {m_min} (banda: {banda(m_min)}).")
    sin = respuesta_a_la_tasa(d, p, repeticiones=args.repeticiones, orden=SIN_EXPECTATIVAS)["ipc_var12m"]
    m_sin = int(sin["respuesta"].idxmax())
    print(f"   Sin las expectativas en el VAR, el máximo sube a {sin['respuesta'].max():+.2f} pp en el mes {m_sin} "
          f"(banda: {sin['inferior'].iloc[m_sin]:+.2f} a {sin['superior'].iloc[m_sin]:+.2f}): el conocido «price puzzle».")

    fc = pronostico(d, modelo)
    print("\n3. Pronóstico de inflación a 12 meses (banda de 90%):")
    print(fc.iloc[[0, 2, 5, 11]].round(2).to_string())
    evaluacion = evaluar_pronostico(d, p)
    print("\n   Evaluación fuera de muestra desde 2012 (RECM: raíz del error cuadrático medio; sin los pronósticos\n"
          "   que parten de un mes de cierre de 2020, salvo la última columna):")
    print(evaluacion.round(3).to_string())

    SALIDA.mkdir(exist_ok=True)
    figura_taylor(d, tasa_sugerida(d, base, "expectativas_inf_12m"), pie)
    figura_irf(respuestas, pie)
    figura_pronostico(d, fc, pie)
    tabla.to_csv(SALIDA / "regla_taylor.csv")
    pd.concat(respuestas, axis=1).to_csv(SALIDA / "irf_politica_monetaria.csv")
    fc.to_csv(SALIDA / "pronostico_inflacion.csv")
    evaluacion.to_csv(SALIDA / "evaluacion_pronostico.csv")
    print(f"\nFiguras y tablas en {SALIDA.relative_to(AQUI.parent)}/")


if __name__ == "__main__":
    main()
