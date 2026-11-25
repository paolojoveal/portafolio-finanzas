"""Fusiones y adquisiciones: valor de las sinergias, prima de control y efecto en la utilidad por acción.

Un grupo de consumo masivo listado en la BVL (comprador) evalúa adquirir a un competidor regional
(objetivo). El script:
    1. Valoriza las sinergias de costos y de ingresos, con tasas de descuento distintas, netas
       de los costos de integración
    2. Compara ese valor con la prima pagada: VPN para los accionistas del comprador
    3. Calcula el efecto en la utilidad por acción (UPA) según la forma de pago: efectivo
       financiado con deuda, acciones o una mezcla (accretion / dilution)
    4. Halla la sinergia mínima para que la operación no diluya la UPA
    5. Muestra la sensibilidad a la prima y al porcentaje pagado en acciones

    python fusiones.py
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

# Supuestos ilustrativos (S/ millones, salvo precios por acción)
COMPRADOR = {"utilidad_neta": 900, "acciones": 850, "precio": 9.0}
OBJETIVO = {"utilidad_neta": 120, "acciones": 200, "precio": 7.5}
PRIMA = 0.30
TASA_IMPUESTO = 0.295
COSTO_DEUDA = 0.075
SINERGIAS = {"costos": 90, "ingresos": 40}       # antes de impuestos, en régimen (año 3); las de ingresos, como margen
RAMPA = [0.4, 0.8, 1.0, 1.0, 1.0]                # fracción de la sinergia de régimen que se logra cada año
COSTOS_INTEGRACION = [80, 40, 0, 0, 0]
TASA_DESCUENTO = {"costos": 0.10, "ingresos": 0.14}   # las de ingresos son más inciertas
G_PERPETUO = 0.02


def valor_sinergias() -> dict:
    t = np.arange(1, len(RAMPA) + 1)
    out = {}
    for tipo, nivel in SINERGIAS.items():
        r = TASA_DESCUENTO[tipo]
        flujos = nivel * np.array(RAMPA) * (1 - TASA_IMPUESTO)
        terminal = flujos[-1] * (1 + G_PERPETUO) / (r - G_PERPETUO)
        out[tipo] = float((flujos / (1 + r) ** t).sum() + terminal / (1 + r) ** t[-1])
    integracion = np.array(COSTOS_INTEGRACION) * (1 - TASA_IMPUESTO)
    out["integracion"] = -float((integracion / (1 + TASA_DESCUENTO["costos"]) ** t).sum())
    out["total"] = sum(out.values())
    return out


def accretion(prima: float, pct_acciones: float, sinergia_anual: float) -> dict:
    """UPA proforma del comprador. `sinergia_anual` va antes de impuestos."""
    precio_oferta = OBJETIVO["precio"] * (1 + prima)
    pagado = precio_oferta * OBJETIVO["acciones"]
    nuevas_acciones = pagado * pct_acciones / COMPRADOR["precio"]
    costo_financiamiento = pagado * (1 - pct_acciones) * COSTO_DEUDA * (1 - TASA_IMPUESTO)
    utilidad_pf = (COMPRADOR["utilidad_neta"] + OBJETIVO["utilidad_neta"]
                   + sinergia_anual * (1 - TASA_IMPUESTO) - costo_financiamiento)
    upa_base = COMPRADOR["utilidad_neta"] / COMPRADOR["acciones"]
    upa_pf = utilidad_pf / (COMPRADOR["acciones"] + nuevas_acciones)
    return {"precio_oferta": precio_oferta, "pagado": pagado, "nuevas_acciones": nuevas_acciones,
            "upa_base": upa_base, "upa_proforma": upa_pf, "accretion": upa_pf / upa_base - 1}


def sinergia_de_equilibrio(prima: float, pct_acciones: float) -> float:
    """Sinergia anual (antes de impuestos) con la que la UPA no cambia. La UPA es lineal en la
    sinergia, así que basta despejar."""
    sin, con = accretion(prima, pct_acciones, 0.0), accretion(prima, pct_acciones, 100.0)
    return -100.0 * sin["accretion"] / (con["accretion"] - sin["accretion"])


def sensibilidad(sinergia_anual: float, primas=(0.15, 0.20, 0.25, 0.30, 0.35, 0.40),
                 pcts=(0.0, 0.25, 0.5, 0.75, 1.0)) -> pd.DataFrame:
    return pd.DataFrame([[accretion(pr, p, sinergia_anual)["accretion"] for p in pcts] for pr in primas],
                        index=pd.Index(primas, name="prima"), columns=pd.Index(pcts, name="pct_acciones"))


def figura(sens: pd.DataFrame, pie: str):
    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    amplitud = float(np.abs(sens.to_numpy()).max())
    ax.imshow(sens.to_numpy(), cmap=estilo.MAPA_DIVERGENTE.reversed(), vmin=-amplitud, vmax=amplitud, aspect="auto")
    for i in range(sens.shape[0]):
        for j in range(sens.shape[1]):
            v = sens.iat[i, j]
            texto = "0.0%" if abs(v) < 0.0005 else f"{v:+.1%}".replace("-", "−")
            ax.text(j, i, texto, ha="center", va="center", fontsize=10,
                    color="#ffffff" if abs(v) / amplitud > 0.55 else estilo.TINTA)
    ax.set_xticks(range(sens.shape[1]), [f"{p:.0%}" for p in sens.columns])
    ax.set_yticks(range(sens.shape[0]), [f"{p:.0%}" for p in sens.index])
    ax.set_xlabel("Porcentaje del precio pagado en acciones")
    ax.set_ylabel("Prima sobre el precio de mercado")
    ax.grid(False)
    ax.tick_params(length=0)
    for lado in ax.spines.values():
        lado.set_visible(False)
    estilo.titulo(ax, "Efecto de la compra en la utilidad por acción",
                  "Año de régimen, con sinergias completas. Azul: aumenta la UPA; rojo: la diluye")
    return estilo.guardar(fig, SALIDA / "fusiones.png", pie)


def main():
    estilo.aplicar()
    pd.set_option("display.width", 200)
    sv = valor_sinergias()
    valor_objetivo = OBJETIVO["precio"] * OBJETIVO["acciones"]
    prima_pagada = valor_objetivo * PRIMA
    print("Valor presente de las sinergias (S/ mm):")
    for k, v in sv.items():
        print(f"  {k:12s} {v:8.0f}")
    print(f"Prima pagada ({PRIMA:.0%}): {prima_pagada:,.0f}  ->  VPN para el comprador: {sv['total'] - prima_pagada:,.0f}")
    print(f"Prima máxima que las sinergias justifican: {sv['total'] / valor_objetivo:.0%}")

    regimen = sum(SINERGIAS.values())
    print("\nEfecto en la UPA del comprador (año de régimen, sinergias completas):")
    filas = []
    for nombre, pct in [("100% efectivo (deuda)", 0.0), ("50% / 50%", 0.5), ("100% acciones", 1.0)]:
        r = accretion(PRIMA, pct, regimen)
        filas.append({"forma de pago": nombre, "UPA base": r["upa_base"], "UPA proforma": r["upa_proforma"],
                      "con sinergias": r["accretion"], "sin sinergias": accretion(PRIMA, pct, 0)["accretion"],
                      "sinergia de equilibrio (S/ mm)": sinergia_de_equilibrio(PRIMA, pct)})
    print(pd.DataFrame(filas).set_index("forma de pago").to_string(formatters={
        "UPA base": "{:.3f}".format, "UPA proforma": "{:.3f}".format, "con sinergias": "{:+.1%}".format,
        "sin sinergias": "{:+.1%}".format, "sinergia de equilibrio (S/ mm)": "{:,.0f}".format}))
    pe_c = COMPRADOR["precio"] / (COMPRADOR["utilidad_neta"] / COMPRADOR["acciones"])
    pe_o = OBJETIVO["precio"] * (1 + PRIMA) / (OBJETIVO["utilidad_neta"] / OBJETIVO["acciones"])
    print(f"\nP/E del comprador {pe_c:.1f}x frente a P/E pagado por el objetivo {pe_o:.1f}x: pagar con acciones "
          f"{'diluye' if pe_o > pe_c else 'aumenta'} la UPA antes de sinergias.")
    print("Que la UPA suba no significa que se cree valor: lo que importa es el VPN = sinergias - prima.")

    sens = sensibilidad(regimen)
    print("\nSensibilidad del efecto en la UPA (filas: prima; columnas: % pagado en acciones):")
    print(sens.rename(index="{:.0%}".format, columns="{:.0%}".format).map("{:+.1%}".format).to_string())
    SALIDA.mkdir(exist_ok=True)
    figura(sens, "Supuestos ilustrativos (al inicio del script). Elaboración propia.")
    sens.round(4).to_csv(SALIDA / "fusiones_sensibilidad_upa.csv")


if __name__ == "__main__":
    main()
