"""Estructura de capital: teoría del trade-off y valor presente ajustado (APV).

Para una empresa peruana sin deuda (EBIT y riesgo dados) se evalúan niveles de deuda permanente:

    1. Rating sintético según la cobertura de intereses (EBIT / intereses) -> spread y costo de deuda
    2. Valor presente del escudo fiscal (limitado a la utilidad disponible para deducir intereses)
    3. Valor presente de los costos esperados de quiebra = prob. de incumplimiento × costo de quiebra
    4. APV = valor sin deuda + escudo fiscal - costos esperados de quiebra
    5. WACC implícito: la tasa que, aplicada al mismo flujo, da ese valor (WACC = g + FCFF_1 / APV)

El nivel de deuda que maximiza el APV es, por construcción, el que minimiza el WACC implícito.

    python estructura_capital.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))

from common import estilo  # noqa: E402

SALIDA = AQUI / "resultados"

# Supuestos ilustrativos (S/ millones)
EBIT = 650.0
TASA_IMPUESTO = 0.295            # impuesto a la renta en el Perú
CRECIMIENTO = 0.03
REINVERSION = 0.30               # fracción del NOPAT que se reinvierte
BETA_U = 0.85
RF = 0.065                       # bono soberano en soles a 10 años, aproximado
PRIMA_MERCADO = 0.065            # incluye riesgo país
COSTO_QUIEBRA = 0.20             # pérdida de valor en una quiebra, como fracción del valor sin deuda

# Rating sintético: (cobertura mínima, rating, spread, probabilidad de incumplimiento acumulada).
# Tabla ilustrativa con la forma de las que se usan en la práctica (más cobertura, mejor rating,
# menor spread); no reproduce las cifras de ninguna agencia.
RATINGS = [
    (8.5, "AAA", 0.0060, 0.006), (6.5, "AA", 0.0080, 0.015), (4.25, "A", 0.0110, 0.029),
    (3.0, "BBB", 0.0180, 0.163), (2.0, "BB", 0.0300, 0.299), (1.25, "B", 0.0500, 0.537),
    (-np.inf, "CCC", 0.0900, 0.700),
]
GRADO_INVERSION = ["AAA", "AA", "A", "BBB"]


def valor_sin_deuda() -> tuple[float, float, float]:
    """Vu = FCFF_1 / (ku - g), con ku = rf + beta_u × prima. Devuelve (Vu, ku, FCFF_1)."""
    ku = RF + BETA_U * PRIMA_MERCADO
    fcff_1 = EBIT * (1 - TASA_IMPUESTO) * (1 - REINVERSION) * (1 + CRECIMIENTO)
    return fcff_1 / (ku - CRECIMIENTO), ku, fcff_1


def rating_sintetico(deuda: float) -> tuple[str, float, float]:
    """Busca, de mejor a peor, el primer rating cuya cobertura mínima se cumple con su propio costo de deuda."""
    for minimo, rating, spread, prob in RATINGS:
        if EBIT / (deuda * (RF + spread)) >= minimo:
            return rating, spread, prob
    raise AssertionError("la última fila de RATINGS acepta cualquier cobertura")


def evaluar(deuda: float, vu: float, fcff_1: float) -> dict:
    if deuda == 0:
        return {"deuda": 0.0, "D/V": 0.0, "rating": "Sin deuda", "cobertura": np.inf, "kd": RF,
                "vp_escudo_fiscal": 0.0, "vp_costos_quiebra": 0.0, "apv": vu,
                "wacc_implicito": CRECIMIENTO + fcff_1 / vu}
    rating, spread, prob = rating_sintetico(deuda)
    kd = RF + spread
    intereses = deuda * kd
    t_efectivo = TASA_IMPUESTO * min(1.0, EBIT / intereses)      # no se deduce más interés que el EBIT
    vp_escudo = t_efectivo * deuda                                # deuda perpetua: t·D (Modigliani-Miller, 1963)
    vp_quiebra = prob * COSTO_QUIEBRA * vu
    apv = vu + vp_escudo - vp_quiebra
    return {"deuda": deuda, "D/V": deuda / apv, "rating": rating, "cobertura": EBIT / intereses, "kd": kd,
            "vp_escudo_fiscal": vp_escudo, "vp_costos_quiebra": vp_quiebra, "apv": apv,
            "wacc_implicito": CRECIMIENTO + fcff_1 / apv}


def tabla_de_deuda(maximo: float = 3500, paso: float = 250) -> pd.DataFrame:
    vu, _, fcff_1 = valor_sin_deuda()
    return pd.DataFrame([evaluar(d, vu, fcff_1) for d in np.arange(0, maximo + 1, paso)]).set_index("deuda")


def figura(tabla: pd.DataFrame, vu: float, optimo: float, con_grado: float, pie: str):
    fig, (a, b) = plt.subplots(1, 2, figsize=estilo.DOBLE)
    x = tabla["D/V"] * 100
    a.plot(x, tabla["wacc_implicito"] * 100, "-o", ms=4.5, color=estilo.AZUL)
    for d, texto, desplazamiento in [(optimo, "Mínimo", (0, -30)), (con_grado, "Mejor con grado de inversión", (-88, -44))]:
        punto = (tabla.loc[d, "D/V"] * 100, tabla.loc[d, "wacc_implicito"] * 100)
        estilo.punto_final(a, *punto, estilo.AZUL)
        a.annotate(f"{texto}:\n{tabla.loc[d, 'wacc_implicito']:.2%} ({tabla.loc[d, 'rating']})", punto,
                   xytext=desplazamiento, textcoords="offset points", ha="center", va="center", fontsize=9,
                   color=estilo.TINTA_2, arrowprops={"arrowstyle": "-", "color": estilo.TENUE, "lw": 0.8, "shrinkB": 6})
    a.set_ylim(tabla["wacc_implicito"].min() * 100 - 0.38, None)
    a.set_xlabel("Deuda / valor de la empresa")
    estilo.formato_pct(a, "x")
    estilo.formato_pct(a, "y")
    estilo.titulo(a, "Costo de capital implícito", "WACC que resulta de cada nivel de deuda")

    b.axhline(vu, color=estilo.CONTEXTO, lw=1.6, label="Valor sin deuda")
    b.plot(x, vu + tabla["vp_escudo_fiscal"], color=estilo.NARANJA, label="Con escudo fiscal")
    b.plot(x, tabla["apv"], "-o", ms=4.5, color=estilo.AZUL, label="APV: neto de costos de quiebra")
    b.fill_between(x, tabla["apv"], vu + tabla["vp_escudo_fiscal"], color=estilo.NARANJA, alpha=0.12, lw=0)
    estilo.punto_final(b, tabla.loc[optimo, "D/V"] * 100, tabla.loc[optimo, "apv"], estilo.AZUL)
    b.set_xlabel("Deuda / valor de la empresa")
    b.set_ylabel("S/ millones")
    estilo.formato_pct(b, "x")
    estilo.formato_miles(b)
    estilo.titulo(b, "Trade-off: escudo fiscal frente a costos de quiebra",
                  "El área sombreada es el costo esperado de quiebra")
    b.legend(loc="upper left")
    return estilo.guardar(fig, SALIDA / "estructura_capital.png", pie)


def main():
    estilo.aplicar()
    vu, ku, _ = valor_sin_deuda()
    tabla = tabla_de_deuda()
    optimo = tabla["apv"].idxmax()
    con_grado = tabla[tabla["rating"].isin(GRADO_INVERSION)]["apv"].idxmax()
    pd.set_option("display.width", 200)
    print(f"Valor sin deuda (Vu): S/ {vu:,.0f} mm | costo de capital sin deuda ku = {ku:.2%}\n")
    print(tabla.to_string(formatters={"D/V": "{:.0%}".format, "cobertura": "{:.2f}".format, "kd": "{:.2%}".format,
                                      "vp_escudo_fiscal": "{:,.0f}".format, "vp_costos_quiebra": "{:,.0f}".format,
                                      "apv": "{:,.0f}".format, "wacc_implicito": "{:.2%}".format}))
    o, g = tabla.loc[optimo], tabla.loc[con_grado]
    print(f"\nMáximo APV: deuda de S/ {optimo:,.0f} mm (D/V {o['D/V']:.0%}, rating {o['rating']}, "
          f"WACC implícito {o['wacc_implicito']:.2%}). Valor creado frente a no tener deuda: {o['apv'] / vu - 1:+.1%}.")
    print(f"Mejor nivel con grado de inversión: S/ {con_grado:,.0f} mm (D/V {g['D/V']:.0%}, rating {g['rating']}). "
          f"Renuncia a {o['apv'] / g['apv'] - 1:.1%} del valor a cambio de conservar el acceso al mercado.")
    print("Cómo leerlo: con el escudo valorado como t·D y costos de quiebra de 20%, el modelo empuja hacia mucha deuda.\n"
          "Es la versión de libro de texto: no incluye impuestos personales, pérdida de flexibilidad financiera ni\n"
          "costos de agencia, que es por lo que las empresas reales se endeudan bastante menos.")
    SALIDA.mkdir(exist_ok=True)
    figura(tabla, vu, optimo, con_grado, "Supuestos ilustrativos (al inicio del script). Elaboración propia.")
    tabla.to_csv(SALIDA / "estructura_capital.csv")


if __name__ == "__main__":
    main()
