"""Valorización por Flujo de Caja Descontado (DCF) de una empresa listada en la BVL.

Uso:
    python dcf.py                      # usa supuestos.json
    python dcf.py --supuestos otro.json --excel

Genera:
    resultados/proyeccion.csv, resultados/sensibilidad.csv, resultados/football_field.png
    resultados/valorizacion.xlsx (con --excel)
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "resultados"


@dataclass
class ResultadoWACC:
    beta_apalancado: float
    costo_capital_usd: float
    costo_capital_pen: float
    costo_deuda_neto: float
    peso_capital: float
    peso_deuda: float
    wacc: float


def calcular_wacc(p: dict, tasa_impuesto: float) -> ResultadoWACC:
    """CAPM con prima por riesgo país (enfoque estilo Damodaran), convertido a soles
    por paridad de inflación (Fisher)."""
    d_e = p["deuda_sobre_capital"]
    beta_l = p["beta_desapalancado"] * (1 + (1 - tasa_impuesto) * d_e)  # Hamada
    ke_usd = p["tasa_libre_riesgo_usd"] + beta_l * p["prima_riesgo_mercado"] + p["riesgo_pais_embig"]
    ke_pen = (1 + ke_usd) * (1 + p["inflacion_largo_plazo_pen"]) / (1 + p["inflacion_largo_plazo_usd"]) - 1
    kd_neto = p["costo_deuda_pre_impuestos_pen"] * (1 - tasa_impuesto)
    we = 1 / (1 + d_e)
    wd = d_e / (1 + d_e)
    return ResultadoWACC(beta_l, ke_usd, ke_pen, kd_neto, we, wd, we * ke_pen + wd * kd_neto)


def proyectar(s: dict) -> pd.DataFrame:
    n = len(s["crecimiento_ventas"])
    anios = [s["anio_base"] + i for i in range(1, n + 1)]
    ventas = s["ventas_base"] * np.cumprod(1 + np.array(s["crecimiento_ventas"]))
    ventas_prev = np.concatenate([[s["ventas_base"]], ventas[:-1]])
    ebitda = ventas * np.array(s["margen_ebitda"])
    dya = ventas * s["dya_pct_ventas"]
    ebit = ebitda - dya
    nopat = ebit * (1 - s["tasa_impuesto"])
    capex = ventas * s["capex_pct_ventas"]
    delta_ct = (ventas - ventas_prev) * s["capital_trabajo_pct_ventas"]
    fcff = nopat + dya - capex - delta_ct
    return pd.DataFrame({
        "ventas": ventas, "ebitda": ebitda, "dya": dya, "ebit": ebit, "nopat": nopat,
        "capex": capex, "delta_capital_trabajo": delta_ct, "fcff": fcff,
    }, index=pd.Index(anios, name="anio"))


def valorizar(proy: pd.DataFrame, wacc: float, g: float, s: dict,
              metodo: str = "gordon") -> dict:
    t = np.arange(1, len(proy) + 1) - 0.5  # convención de medio año
    factor = 1 / (1 + wacc) ** t
    vp_flujos = float((proy["fcff"] * factor).sum())
    if metodo == "gordon":
        fcff_n1 = proy["fcff"].iloc[-1] * (1 + g)
        vt = fcff_n1 / (wacc - g)
    else:
        vt = proy["ebitda"].iloc[-1] * s["multiplo_salida_ev_ebitda"]
    vp_vt = vt / (1 + wacc) ** len(proy)
    ev = vp_flujos + vp_vt
    equity = ev - s["deuda_neta"] - s["intereses_minoritarios"]
    precio = equity / s["acciones_en_circulacion_mm"]
    return {"vp_flujos": vp_flujos, "valor_terminal": vt, "vp_valor_terminal": vp_vt,
            "enterprise_value": ev, "equity_value": equity, "precio_objetivo": precio,
            "pct_ev_terminal": vp_vt / ev,
            "upside": precio / s["precio_mercado"] - 1}


def sensibilidad(proy, s, wacc_c, g_c, paso_w=0.005, paso_g=0.005, n=2) -> pd.DataFrame:
    waccs = [wacc_c + paso_w * i for i in range(-n, n + 1)]
    gs = [g_c + paso_g * i for i in range(-n, n + 1)]
    tabla = pd.DataFrame(index=pd.Index([f"{w:.1%}" for w in waccs], name="WACC"),
                         columns=[f"{g:.1%}" for g in gs], dtype=float)
    for w in waccs:
        for g in gs:
            tabla.loc[f"{w:.1%}", f"{g:.1%}"] = valorizar(proy, w, g, s)["precio_objetivo"]
    return tabla.round(2)


def football_field(rangos: dict[str, tuple[float, float]], precio: float, ruta: Path):
    fig, ax = plt.subplots(figsize=(8, 3.5))
    for i, (nombre, (lo, hi)) in enumerate(rangos.items()):
        ax.barh(i, hi - lo, left=lo, color="#2E5C8A", height=0.5)
        ax.text(hi + 0.1, i, f"S/ {lo:.2f} – {hi:.2f}", va="center", fontsize=9)
    ax.axvline(precio, color="#C0392B", ls="--", label=f"Precio de mercado S/ {precio:.2f}")
    ax.set_yticks(range(len(rangos)), list(rangos))
    ax.set_xlabel("Precio por acción (S/)")
    ax.set_title("Football field: rango de valorización")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(ruta, dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--supuestos", default=AQUI / "supuestos.json")
    ap.add_argument("--excel", action="store_true")
    args = ap.parse_args()
    s = json.loads(Path(args.supuestos).read_text(encoding="utf-8"))
    SALIDA.mkdir(exist_ok=True)

    w = calcular_wacc(s["wacc"], s["tasa_impuesto"])
    proy = proyectar(s)
    g = s["crecimiento_perpetuo"]
    gordon = valorizar(proy, w.wacc, g, s, "gordon")
    multiplo = valorizar(proy, w.wacc, g, s, "multiplo")
    sens = sensibilidad(proy, s, w.wacc, g)

    print(f"\n{s['empresa']} — cifras en {s['moneda']}")
    print(f"Beta apalancado {w.beta_apalancado:.2f} | Ke (S/) {w.costo_capital_pen:.2%} | "
          f"Kd neto {w.costo_deuda_neto:.2%} | WACC {w.wacc:.2%}")
    print(proy.round(1).to_string())
    for nombre, r in [("Gordon", gordon), ("Múltiplo de salida", multiplo)]:
        print(f"\n[{nombre}] EV {r['enterprise_value']:,.0f} | Equity {r['equity_value']:,.0f} | "
              f"Precio objetivo S/ {r['precio_objetivo']:.2f} | Upside {r['upside']:+.1%} | "
              f"VT/EV {r['pct_ev_terminal']:.0%}")
    print("\nSensibilidad del precio objetivo (WACC vs g):")
    print(sens.to_string())

    proy.to_csv(SALIDA / "proyeccion.csv")
    sens.to_csv(SALIDA / "sensibilidad.csv")
    football_field({
        "DCF Gordon (sensibilidad)": (sens.values.min(), sens.values.max()),
        "DCF múltiplo salida ±1x": (
            valorizar(proy, w.wacc, g, {**s, "multiplo_salida_ev_ebitda": s["multiplo_salida_ev_ebitda"] - 1}, "multiplo")["precio_objetivo"],
            valorizar(proy, w.wacc, g, {**s, "multiplo_salida_ev_ebitda": s["multiplo_salida_ev_ebitda"] + 1}, "multiplo")["precio_objetivo"]),
    }, s["precio_mercado"], SALIDA / "football_field.png")

    if args.excel:
        with pd.ExcelWriter(SALIDA / "valorizacion.xlsx") as xw:
            proy.to_excel(xw, sheet_name="Proyeccion")
            pd.DataFrame([w.__dict__]).T.rename(columns={0: "valor"}).to_excel(xw, sheet_name="WACC")
            pd.DataFrame({"Gordon": gordon, "Multiplo": multiplo}).to_excel(xw, sheet_name="Valorizacion")
            sens.to_excel(xw, sheet_name="Sensibilidad")
        print(f"\nExcel guardado en {SALIDA / 'valorizacion.xlsx'}")


if __name__ == "__main__":
    main()
