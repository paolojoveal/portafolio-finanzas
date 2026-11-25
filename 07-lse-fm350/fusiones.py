"""Fusiones y adquisiciones: valor de sinergias, prima de control y accretion/dilution.

Un grupo de consumo masivo listado en la BVL (comprador) evalúa adquirir un competidor
regional (objetivo). El script:
    1. Valoriza las sinergias (ingresos y costos) como un DCF con costos de integración
    2. Compara el valor de las sinergias con la prima pagada -> VPN para el comprador
    3. Analiza el efecto en la UPA (EPS) del comprador según la forma de pago
       (efectivo con deuda, acciones o mixto): accretion / dilution
    4. Calcula la sinergia mínima para que la operación no diluya la UPA
    5. Tabla de sensibilidad: prima vs. % pagado en acciones

    python fusiones.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Supuestos ilustrativos (S/ millones, excepto por acción)
COMPRADOR = {"utilidad_neta": 900, "acciones": 850, "precio": 9.0}
OBJETIVO = {"utilidad_neta": 120, "acciones": 200, "precio": 7.5, "deuda_neta": 400}
PRIMA = 0.30
TASA_IMPUESTO = 0.295
COSTO_DEUDA = 0.075
RENDIMIENTO_CAJA = 0.04
SINERGIAS = {  # antes de impuestos, nivel de régimen (año 3)
    "costos": 90,        # compras conjuntas, logística, cierre de plantas
    "ingresos": 40,      # venta cruzada; margen de contribución
}
RAMPA = [0.4, 0.8, 1.0, 1.0, 1.0]
COSTOS_INTEGRACION = [80, 40, 0, 0, 0]
TASA_DESCUENTO_SINERGIAS = {"costos": 0.10, "ingresos": 0.14}  # las de ingresos son más inciertas
G_PERPETUO = 0.02


def valor_sinergias() -> dict:
    t = np.arange(1, len(RAMPA) + 1)
    out = {}
    for tipo, nivel in SINERGIAS.items():
        r = TASA_DESCUENTO_SINERGIAS[tipo]
        flujos = nivel * np.array(RAMPA) * (1 - TASA_IMPUESTO)
        vt = flujos[-1] * (1 + G_PERPETUO) / (r - G_PERPETUO)
        out[tipo] = float((flujos / (1 + r) ** t).sum() + vt / (1 + r) ** t[-1])
    integ = np.array(COSTOS_INTEGRACION) * (1 - TASA_IMPUESTO)
    out["integracion"] = -float((integ / 1.10 ** t).sum())
    out["total"] = sum(out.values())
    return out


def accretion(prima: float, pct_acciones: float, sinergia_anual_pre_tax: float) -> dict:
    precio_oferta = OBJETIVO["precio"] * (1 + prima)
    equity_pagado = precio_oferta * OBJETIVO["acciones"]
    pago_acciones = equity_pagado * pct_acciones
    pago_efectivo = equity_pagado - pago_acciones
    nuevas_acciones = pago_acciones / COMPRADOR["precio"]
    costo_financiamiento = pago_efectivo * COSTO_DEUDA * (1 - TASA_IMPUESTO)
    utilidad_pf = (COMPRADOR["utilidad_neta"] + OBJETIVO["utilidad_neta"]
                   + sinergia_anual_pre_tax * (1 - TASA_IMPUESTO) - costo_financiamiento)
    upa_base = COMPRADOR["utilidad_neta"] / COMPRADOR["acciones"]
    upa_pf = utilidad_pf / (COMPRADOR["acciones"] + nuevas_acciones)
    return {"precio_oferta": precio_oferta, "equity_pagado": equity_pagado,
            "nuevas_acciones": nuevas_acciones, "upa_base": upa_base, "upa_proforma": upa_pf,
            "accretion": upa_pf / upa_base - 1}


def sinergia_breakeven(prima, pct_acciones):
    lo, hi = -500.0, 1000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if accretion(prima, pct_acciones, mid)["accretion"] < 0:
            lo = mid
        else:
            hi = mid
    return hi


def main():
    sv = valor_sinergias()
    prima_pagada = OBJETIVO["precio"] * PRIMA * OBJETIVO["acciones"]
    print("Valor presente de las sinergias (S/ mm):")
    for k, v in sv.items():
        print(f"  {k:12s} {v:8.0f}")
    print(f"Prima pagada ({PRIMA:.0%}): {prima_pagada:,.0f}  ->  VPN para el comprador: "
          f"{sv['total'] - prima_pagada:,.0f}")
    print(f"Prima máxima justificable por sinergias: {sv['total'] / (OBJETIVO['precio'] * OBJETIVO['acciones']):.0%}")

    sin_regimen = sum(SINERGIAS.values())
    print("\nEfecto en la UPA del comprador (año de régimen, sinergias completas):")
    filas = []
    for nombre, pct in [("100% efectivo (deuda)", 0.0), ("50/50", 0.5), ("100% acciones", 1.0)]:
        r = accretion(PRIMA, pct, sin_regimen)
        r0 = accretion(PRIMA, pct, 0)
        filas.append({"forma de pago": nombre, "UPA base": r["upa_base"], "UPA proforma": r["upa_proforma"],
                      "accretion/(dilution)": r["accretion"], "sin sinergias": r0["accretion"],
                      "sinergia breakeven (S/ mm)": sinergia_breakeven(PRIMA, pct)})
    t = pd.DataFrame(filas).set_index("forma de pago")
    print(t.to_string(formatters={"UPA base": "{:.3f}".format, "UPA proforma": "{:.3f}".format,
                                  "accretion/(dilution)": "{:+.1%}".format, "sin sinergias": "{:+.1%}".format,
                                  "sinergia breakeven (S/ mm)": "{:,.0f}".format}))
    pe_c = COMPRADOR["precio"] / (COMPRADOR["utilidad_neta"] / COMPRADOR["acciones"])
    pe_o = OBJETIVO["precio"] * (1 + PRIMA) / (OBJETIVO["utilidad_neta"] / OBJETIVO["acciones"])
    print(f"\nP/E comprador {pe_c:.1f}x vs. P/E pagado por el objetivo {pe_o:.1f}x: pagar con acciones "
          f"{'diluye' if pe_o > pe_c else 'aumenta'} la UPA antes de sinergias.")
    print("Ojo: accretion de UPA no implica creación de valor; lo que importa es VPN = sinergias - prima.")

    primas = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
    pcts = [0.0, 0.25, 0.5, 0.75, 1.0]
    sens = pd.DataFrame({f"{p:.0%} acciones": [f"{accretion(pr, p, sin_regimen)['accretion']:+.1%}" for pr in primas]
                         for p in pcts}, index=[f"prima {pr:.0%}" for pr in primas])
    print("\nSensibilidad de accretion/(dilution):")
    print(sens.to_string())


if __name__ == "__main__":
    main()
