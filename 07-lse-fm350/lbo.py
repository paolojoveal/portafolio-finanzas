"""Modelo LBO (compra apalancada) de un fondo de private equity.

    1. Fuentes y usos de fondos
    2. Proyección operativa y flujo de caja disponible para pagar deuda
    3. Calendario de deuda: senior (amortización obligatoria + cash sweep) y subordinada con
       intereses capitalizados (PIK)
    4. Salida al año 5 por múltiplo EV/EBITDA
    5. TIR, múltiplo sobre el capital (MoM) y puente de creación de valor: crecimiento del
       EBITDA, expansión de múltiplo y desapalancamiento
    6. Sensibilidad de la TIR a los múltiplos de entrada y de salida

    python lbo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))

from common import estilo  # noqa: E402

SALIDA = AQUI / "resultados"
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


def correr(s: dict) -> dict:
    ev = s["ebitda_ltm"] * s["multiplo_entrada"]
    senior0, sub0 = s["ebitda_ltm"] * s["senior_x"], s["ebitda_ltm"] * s["sub_x"]
    costos = ev * s["costos_transaccion_pct"]
    usos = {"Precio de compra (EV)": ev, "Costos de transacción": costos, "Caja mínima": s["caja_minima"]}
    equity0 = sum(usos.values()) - senior0 - sub0
    fuentes = {"Deuda senior": senior0, "Deuda subordinada (PIK)": sub0, "Capital del fondo": equity0}

    ventas, senior, sub, caja = s["ventas_ltm"], senior0, sub0, s["caja_minima"]
    filas = []
    for t in range(s["anios"]):
        ventas_prev, ventas = ventas, ventas * (1 + s["crec_ventas"][t])
        ebitda = ventas * s["margen_ebitda"][t]
        dya, capex = ventas * s["dya_pct"], ventas * s["capex_pct"]
        d_ct = (ventas - ventas_prev) * s["ct_pct"]
        int_senior = senior * s["senior_tasa"]
        pik = sub * s["sub_tasa_pik"]                       # no se paga en efectivo, pero es gasto deducible
        impuestos = max(ebitda - dya - int_senior - pik, 0) * s["impuesto"]
        flujo = ebitda - int_senior - impuestos - capex - d_ct
        amort = min(senior, senior0 * s["senior_amort"])
        sweep = min(senior - amort, max(flujo - amort, 0) * s["cash_sweep"])
        senior -= amort + sweep
        sub += pik
        caja += flujo - amort - sweep
        filas.append({"anio": t + 1, "ventas": ventas, "ebitda": ebitda, "intereses_senior": int_senior,
                      "pik": pik, "impuestos": impuestos, "flujo_para_deuda": flujo,
                      "pago_senior": amort + sweep, "deuda_senior": senior, "deuda_sub": sub,
                      "caja": caja, "deuda_neta/ebitda": (senior + sub - caja) / ebitda})
    proy = pd.DataFrame(filas).set_index("anio")
    ebitda_salida = proy["ebitda"].iloc[-1]
    equity_salida = ebitda_salida * s["multiplo_salida"] - senior - sub + caja
    mom = equity_salida / equity0
    deuda_neta0 = senior0 + sub0 - s["caja_minima"]
    puente = {
        "Capital invertido": equity0,
        "Crecimiento del EBITDA": (ebitda_salida - s["ebitda_ltm"]) * s["multiplo_entrada"],
        "Expansión de múltiplo": (s["multiplo_salida"] - s["multiplo_entrada"]) * ebitda_salida,
        "Desapalancamiento": deuda_neta0 - (senior + sub - caja),
        "Costos de transacción": -costos,
        "Capital a la salida": equity_salida,
    }
    return {"tir": mom ** (1 / s["anios"]) - 1, "mom": mom, "proy": proy, "puente": puente,
            "fuentes": fuentes, "usos": usos, "deuda_inicial": {"senior": senior0, "sub": sub0}}


def sensibilidad(s: dict, multiplos=(7.0, 7.5, 8.0, 8.5, 9.0)) -> pd.DataFrame:
    """TIR según el múltiplo de entrada (filas) y de salida (columnas)."""
    return pd.DataFrame([[correr({**s, "multiplo_entrada": e, "multiplo_salida": x})["tir"] for x in multiplos]
                         for e in multiplos], index=pd.Index(multiplos, name="entrada"),
                        columns=pd.Index(multiplos, name="salida"))


def figura(r: dict, pie: str):
    fig, (a, b) = plt.subplots(1, 2, figsize=(11.5, 4.6))
    # --- puente de valor: barras flotantes
    nombres, valores = list(r["puente"]), list(r["puente"].values())
    base = 0.0
    for i, v in enumerate(valores):
        total = i in (0, len(valores) - 1)
        inicio = 0.0 if total else (base if v >= 0 else base + v)
        color = estilo.AZUL if total else (estilo.AGUA if v >= 0 else estilo.ROJO)
        a.bar(i, abs(v), bottom=inicio, width=0.5, color=color)
        a.text(i, inicio + abs(v) + 12, f"{v:,.0f}" if total else f"{v:+,.0f}", ha="center", va="bottom",
               fontsize=9, color=estilo.TINTA)
        base = v if i == 0 else (base if total else base + v)
    cortos = {"Capital invertido": "Capital\ninvertido", "Crecimiento del EBITDA": "Crecimiento\ndel EBITDA",
              "Expansión de múltiplo": "Expansión\nde múltiplo", "Desapalancamiento": "Desapalan-\ncamiento",
              "Costos de transacción": "Costos de\ntransacción", "Capital a la salida": "Capital a\nla salida"}
    a.set_xticks(range(len(nombres)), [cortos[n] for n in nombres], fontsize=8.5)
    a.set_ylim(0, max(valores) * 1.14)
    a.set_ylabel("USD millones")
    estilo.formato_miles(a)
    estilo.titulo(a, f"De dónde sale el retorno: MoM {r['mom']:.2f}x, TIR {r['tir']:.1%}", "Puente de valor del capital del fondo")

    # --- deuda por tramo
    p = r["proy"]
    anios = [0, *p.index]
    senior = [r["deuda_inicial"]["senior"], *p["deuda_senior"]]
    sub = [r["deuda_inicial"]["sub"], *p["deuda_sub"]]
    b.bar(anios, senior, width=0.5, color=estilo.AZUL, edgecolor=estilo.SUPERFICIE, linewidth=2, label="Deuda senior")
    b.bar(anios, sub, bottom=senior, width=0.5, color=estilo.NARANJA, edgecolor=estilo.SUPERFICIE, linewidth=2,
          label="Deuda subordinada (PIK)")
    for x, s_, u, apal in zip(anios[1:], senior[1:], sub[1:], p["deuda_neta/ebitda"]):
        b.text(x, s_ + u + 8, f"{apal:.1f}x", ha="center", va="bottom", fontsize=9, color=estilo.TINTA)
    b.set_xticks(anios, ["Compra", *[f"Año {i}" for i in p.index]])
    b.set_ylim(0, (senior[0] + sub[0]) * 1.22)
    b.set_ylabel("USD millones")
    estilo.titulo(b, "La caja paga la deuda senior; la subordinada crece", "Sobre cada barra: deuda neta / EBITDA")
    b.legend(loc="upper right", ncol=2)
    return estilo.guardar(fig, SALIDA / "lbo.png", pie)


def main():
    estilo.aplicar()
    pd.set_option("display.width", 200)
    r = correr(S)
    print("Fuentes:", {k: round(v, 1) for k, v in r["fuentes"].items()})
    print("Usos:   ", {k: round(v, 1) for k, v in r["usos"].items()})
    print(f"Capital del fondo: {r['fuentes']['Capital del fondo'] / sum(r['usos'].values()):.0%} del total\n")
    print(r["proy"].round(1).to_string())
    print(f"\nCapital a la salida {r['puente']['Capital a la salida']:,.0f} | MoM {r['mom']:.2f}x | TIR {r['tir']:.1%}")
    print("\nPuente de creación de valor:")
    for k, v in r["puente"].items():
        print(f"  {k:24s} {v:8.1f}")
    sens = sensibilidad(S)
    print("\nSensibilidad de la TIR (filas: múltiplo de entrada; columnas: múltiplo de salida):")
    print(sens.rename(index="{:.1f}x".format, columns="{:.1f}x".format).map("{:.1%}".format).to_string())
    SALIDA.mkdir(exist_ok=True)
    figura(r, "Supuestos ilustrativos (al inicio del script). Elaboración propia.")
    r["proy"].round(2).to_csv(SALIDA / "lbo_proyeccion.csv")
    sens.round(4).to_csv(SALIDA / "lbo_sensibilidad_tir.csv")


if __name__ == "__main__":
    main()
