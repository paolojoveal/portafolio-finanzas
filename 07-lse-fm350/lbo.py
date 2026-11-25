"""Modelo LBO (Leveraged Buyout) de un fondo de private equity.

    1. Fuentes y usos de fondos
    2. Proyección operativa y flujo de caja libre para el accionista
    3. Calendario de deuda: Senior (amortización + cash sweep) y deuda subordinada (PIK)
    4. Salida al año 5 por múltiplo EV/EBITDA
    5. TIR y múltiplo sobre el capital (MoM), descomposición del retorno
       (crecimiento de EBITDA, expansión de múltiplo, desapalancamiento)
    6. Sensibilidad de la TIR a múltiplo de entrada y de salida

    python lbo.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

S = {  # USD millones, supuestos ilustrativos
    "ebitda_ltm": 100.0,
    "multiplo_entrada": 8.0,
    "multiplo_salida": 8.0,
    "anios": 5,
    "crec_ventas": [0.08, 0.08, 0.07, 0.06, 0.05],
    "ventas_ltm": 600.0,
    "margen_ebitda": [0.170, 0.175, 0.180, 0.185, 0.185],
    "dya_pct": 0.03, "capex_pct": 0.035, "ct_pct": 0.10,
    "impuesto": 0.295,
    "senior_x": 3.5, "senior_tasa": 0.085, "senior_amort": 0.05, "cash_sweep": 0.75,
    "sub_x": 1.5, "sub_tasa_pik": 0.12,
    "caja_minima": 10.0,
    "costos_transaccion_pct": 0.02,
}
SALIDA = Path(__file__).resolve().parent / "resultados"


def correr(s: dict, verbose=False) -> dict:
    ev = s["ebitda_ltm"] * s["multiplo_entrada"]
    senior0 = s["ebitda_ltm"] * s["senior_x"]
    sub0 = s["ebitda_ltm"] * s["sub_x"]
    costos = ev * s["costos_transaccion_pct"]
    usos = {"Precio de compra (EV)": ev, "Costos de transacción": costos, "Caja mínima": s["caja_minima"]}
    equity0 = sum(usos.values()) - senior0 - sub0
    fuentes = {"Deuda senior": senior0, "Deuda subordinada (PIK)": sub0, "Capital del sponsor": equity0}

    ventas, senior, sub, caja = s["ventas_ltm"], senior0, sub0, s["caja_minima"]
    filas = []
    for t in range(s["anios"]):
        v_prev = ventas
        ventas = ventas * (1 + s["crec_ventas"][t])
        ebitda = ventas * s["margen_ebitda"][t]
        dya, capex = ventas * s["dya_pct"], ventas * s["capex_pct"]
        d_ct = (ventas - v_prev) * s["ct_pct"]
        int_senior = senior * s["senior_tasa"]
        pik = sub * s["sub_tasa_pik"]  # se capitaliza, pero es deducible
        ebt = ebitda - dya - int_senior - pik
        impuestos = max(ebt, 0) * s["impuesto"]
        fcl = ebitda - int_senior - impuestos - capex - d_ct
        amort = min(senior, senior0 * s["senior_amort"])
        sweep = min(senior - amort, max(fcl - amort, 0) * s["cash_sweep"])
        senior -= amort + sweep
        sub += pik
        caja += fcl - amort - sweep
        filas.append({"anio": t + 1, "ventas": ventas, "ebitda": ebitda, "intereses_senior": int_senior,
                      "pik": pik, "impuestos": impuestos, "fcl_antes_deuda": fcl,
                      "pago_senior": amort + sweep, "deuda_senior": senior, "deuda_sub": sub,
                      "caja": caja, "deuda_neta/ebitda": (senior + sub - caja) / ebitda})
    proy = pd.DataFrame(filas).set_index("anio")
    ebitda_salida = proy["ebitda"].iloc[-1]
    ev_salida = ebitda_salida * s["multiplo_salida"]
    equity_salida = ev_salida - senior - sub + caja
    mom = equity_salida / equity0
    tir = mom ** (1 / s["anios"]) - 1

    # Puente de valor del patrimonio
    deuda_neta0 = senior0 + sub0 - s["caja_minima"]
    puente = {
        "Capital invertido": equity0,
        "Crecimiento de EBITDA": (ebitda_salida - s["ebitda_ltm"]) * s["multiplo_entrada"],
        "Expansión de múltiplo": (s["multiplo_salida"] - s["multiplo_entrada"]) * ebitda_salida,
        "Desapalancamiento": deuda_neta0 - (senior + sub - caja),
        "Costos de transacción": -costos,
    }
    puente["Capital a la salida"] = equity_salida
    if verbose:
        print("Fuentes:", {k: round(v, 1) for k, v in fuentes.items()})
        print("Usos:   ", {k: round(v, 1) for k, v in usos.items()})
        print(f"Capital del sponsor: {equity0 / sum(usos.values()):.0%} del total\n")
        print(proy.round(1).to_string())
        print(f"\nEV salida {ev_salida:,.0f} | Capital a la salida {equity_salida:,.0f} | "
              f"MoM {mom:.2f}x | TIR {tir:.1%}")
        print("\nPuente de creación de valor:")
        for k, v in puente.items():
            print(f"  {k:24s} {v:8.1f}")
    return {"tir": tir, "mom": mom, "proy": proy, "puente": puente, "fuentes": fuentes, "usos": usos}


def main():
    r = correr(S, verbose=True)
    entradas = [7.0, 7.5, 8.0, 8.5, 9.0]
    salidas = [7.0, 7.5, 8.0, 8.5, 9.0]
    sens = pd.DataFrame(index=pd.Index([f"{x}x" for x in entradas], name="Entrada \\ Salida"),
                        columns=[f"{x}x" for x in salidas])
    for e in entradas:
        for x in salidas:
            sens.loc[f"{e}x", f"{x}x"] = f"{correr({**S, 'multiplo_entrada': e, 'multiplo_salida': x})['tir']:.1%}"
    print("\nSensibilidad de la TIR (múltiplo de entrada vs. salida):")
    print(sens.to_string())
    SALIDA.mkdir(exist_ok=True)
    r["proy"].to_csv(SALIDA / "lbo_proyeccion.csv")
    sens.to_csv(SALIDA / "lbo_sensibilidad_tir.csv")


if __name__ == "__main__":
    main()
