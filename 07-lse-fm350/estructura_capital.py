"""Estructura de capital óptima: teoría del trade-off y Valor Presente Ajustado (APV).

Para una empresa peruana sin deuda (EBIT y riesgo dados), se evalúan niveles de
apalancamiento D/V de 0% a 70%:

    1. Rating sintético según cobertura de intereses (EBIT / intereses) -> spread de crédito
    2. Beta apalancado (Hamada) y costo de capital por CAPM
    3. WACC y valor de la firma para cada nivel de deuda
    4. APV = V_sin_deuda + VP(escudo fiscal) - VP(costos esperados de quiebra)

El óptimo es el D/V que minimiza el WACC / maximiza el APV. Ilustra Modigliani-Miller
(con impuestos), el trade-off estático y por qué en la práctica las empresas no se
endeudan al 100%.

    python estructura_capital.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SALIDA = Path(__file__).resolve().parent / "resultados"

# Supuestos ilustrativos (S/ millones)
EBIT = 650.0                      # S/ millones
TASA_IMPUESTO = 0.295            # Perú
CRECIMIENTO = 0.03
REINVERSION = 0.30               # % del NOPAT reinvertido
BETA_U = 0.85
RF = 0.065                       # bono soberano en soles a 10 años, aprox.
PRIMA_MERCADO = 0.065            # incluye riesgo país
COSTO_QUIEBRA = 0.20             # pérdida en quiebra, % del valor sin deuda

# Tabla de rating sintético (cobertura de intereses -> rating, spread, prob. default acumulada)
RATINGS = [  # (cobertura mínima, rating, spread, prob. de default acumulada)
    (8.5, "AAA", 0.0060, 0.006), (6.5, "AA", 0.0080, 0.015), (4.25, "A", 0.0110, 0.029),
    (3.0, "BBB", 0.0180, 0.163), (2.0, "BB", 0.0300, 0.299), (1.25, "B", 0.0500, 0.537),
    (-np.inf, "CCC", 0.0900, 0.700),
]


def rating_por_cobertura(cobertura: float):
    for minimo, rating, spread, pd_ in RATINGS:
        if cobertura >= minimo:
            return rating, spread, pd_
    raise ValueError


def valor_sin_deuda() -> tuple[float, float]:
    """Vu = FCFF_1 / (ku - g), con ku = rf + beta_u × prima."""
    ku = RF + BETA_U * PRIMA_MERCADO
    fcff = EBIT * (1 - TASA_IMPUESTO) * (1 - REINVERSION)
    return fcff * (1 + CRECIMIENTO) / (ku - CRECIMIENTO), ku


def evaluar(deuda: float, vu: float, ku: float) -> dict:
    """Para un nivel de deuda permanente: rating por cobertura (iterando hasta que el
    rating conjeturado sea consistente con la cobertura que implica), APV y WACC."""
    rating, spread, pd_ = "Sin deuda", 0.0, 0.0
    kd = RF
    if deuda > 0:
        for minimo, rating, spread, pd_ in RATINGS:  # de mejor a peor rating
            kd = RF + spread
            if EBIT / (deuda * kd) >= minimo:
                break
    intereses = deuda * kd
    t_efectivo = TASA_IMPUESTO * min(1.0, EBIT / intereses) if deuda > 0 else TASA_IMPUESTO
    vp_escudo = t_efectivo * deuda                 # deuda perpetua (MM con impuestos)
    vp_quiebra = pd_ * COSTO_QUIEBRA * vu          # costo esperado de quiebra
    apv = vu + vp_escudo - vp_quiebra
    dv = deuda / apv
    beta_l = BETA_U * (1 + (1 - t_efectivo) * deuda / (apv - deuda))
    ke = RF + beta_l * PRIMA_MERCADO
    wacc = (1 - dv) * ke + dv * kd * (1 - t_efectivo)
    return {"deuda": deuda, "D/V": dv, "rating": rating,
            "cobertura": EBIT / intereses if deuda > 0 else np.inf, "kd": kd,
            "beta_l": beta_l, "ke": ke, "wacc": wacc, "vp_escudo_fiscal": vp_escudo,
            "vp_costos_quiebra": vp_quiebra, "apv": apv}


def main():
    vu, ku = valor_sin_deuda()
    tabla = pd.DataFrame([evaluar(d, vu, ku) for d in np.arange(0, 3501, 250)]).set_index("deuda")
    opt = tabla["apv"].idxmax()
    pd.set_option("display.width", 200)
    fmt = tabla.copy()
    for c in ["kd", "ke", "wacc"]:
        fmt[c] = fmt[c].map("{:.2%}".format)
    for c in ["vp_escudo_fiscal", "vp_costos_quiebra", "apv"]:
        fmt[c] = fmt[c].map("{:,.0f}".format)
    fmt["D/V"] = fmt["D/V"].map("{:.0%}".format)
    fmt["beta_l"] = fmt["beta_l"].round(2)
    fmt["cobertura"] = fmt["cobertura"].round(2)
    fmt.index = [f"{x:,.0f}" for x in fmt.index]
    print(f"Valor sin deuda (Vu): S/ {vu:,.0f} mm | ku = {ku:.2%}\n")
    print(fmt.to_string())
    print(f"\nDeuda óptima: S/ {opt:,.0f} mm (D/V {tabla.loc[opt, 'D/V']:.0%}, rating "
          f"{tabla.loc[opt, 'rating']}, WACC {tabla.loc[opt, 'wacc']:.2%})")
    ig = tabla[tabla["rating"].isin(["AAA", "AA", "A", "BBB"])]["apv"].idxmax()
    print(f"Mejor opción manteniendo grado de inversión: S/ {ig:,.0f} mm (D/V {tabla.loc[ig, 'D/V']:.0%}, "
          f"rating {tabla.loc[ig, 'rating']}). Diferencia de APV frente al óptimo: "
          f"{tabla.loc[opt, 'apv'] / tabla.loc[ig, 'apv'] - 1:+.1%}")
    print("  -> Si la ganancia adicional es pequeña, la flexibilidad financiera y el acceso al mercado de\n"
          "     capitales favorecen quedarse en grado de inversión (argumento que el modelo no captura).")
    print(f"Ganancia de valor vs. sin deuda: S/ {tabla['apv'].max() - vu:,.0f} mm "
          f"({tabla['apv'].max() / vu - 1:+.1%})")

    SALIDA.mkdir(exist_ok=True)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    x = tabla["D/V"] * 100
    ax[0].plot(x, tabla["wacc"] * 100, "o-", color="#2E5C8A", label="WACC")
    ax[0].plot(x, tabla["ke"] * 100, "--", color="grey", label="Costo del patrimonio")
    ax[0].plot(x, tabla["kd"] * (1 - TASA_IMPUESTO) * 100, ":", color="grey", label="Costo de deuda neto")
    ax[0].axvline(tabla.loc[opt, "D/V"] * 100, color="#C0392B", lw=0.8)
    ax[0].set_xlabel("Deuda / Valor (%)"); ax[0].set_ylabel("%"); ax[0].set_title("Costo de capital")
    ax[0].legend(fontsize=8); ax[0].grid(alpha=0.3)
    ax[1].stackplot(x, [np.full(len(x), vu), tabla["vp_escudo_fiscal"]], labels=["Vu", "VP escudo fiscal"],
                    colors=["#BFD3E6", "#2E5C8A"], alpha=0.8)
    ax[1].plot(x, tabla["apv"], "k-", lw=2, label="APV (neto de costos de quiebra)")
    ax[1].axvline(tabla.loc[opt, "D/V"] * 100, color="#C0392B", lw=0.8)
    ax[1].set_ylim(vu * 0.8, None)
    ax[1].set_xlabel("Deuda / Valor (%)"); ax[1].set_title("Trade-off: escudo fiscal vs. quiebra")
    ax[1].legend(fontsize=8, loc="lower left"); ax[1].grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(SALIDA / "estructura_capital.png", dpi=150); plt.close(fig)
    tabla.to_csv(SALIDA / "estructura_capital.csv")


if __name__ == "__main__":
    main()
