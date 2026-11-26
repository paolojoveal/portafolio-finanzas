"""Valorización por flujo de caja descontado (DCF) de una empresa listada en la BVL.

    1. WACC en soles: CAPM con beta reapalancado (Hamada) y prima por riesgo país, convertido de
       dólares a soles por diferencial de inflación.
    2. Proyección del flujo de caja libre de la firma (FCFF) a cinco años.
    3. Valor terminal por dos métodos que se controlan entre sí: crecimiento perpetuo (Gordon) y
       múltiplo de salida EV/EBITDA. Cada uno reporta el supuesto que implica en el otro.
    4. Sensibilidad del precio objetivo al WACC y al crecimiento perpetuo, y gráfico de rangos.
    5. Con --excel, el mismo modelo como libro de Excel con fórmulas vivas (`modelo_excel.py`).

Uso:
    python dcf.py                              # usa supuestos.json
    python dcf.py --supuestos otro.json --excel
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))

import modelo_excel  # noqa: E402
from common import estilo  # noqa: E402

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
    """CAPM con prima por riesgo país, llevado a soles por paridad de inflación (Fisher)."""
    d_e = p["deuda_sobre_capital"]
    beta_l = p["beta_desapalancado"] * (1 + (1 - tasa_impuesto) * d_e)             # Hamada
    ke_usd = p["tasa_libre_riesgo_usd"] + beta_l * p["prima_riesgo_mercado"] + p["riesgo_pais_embig"]
    ke_pen = (1 + ke_usd) * (1 + p["inflacion_largo_plazo_pen"]) / (1 + p["inflacion_largo_plazo_usd"]) - 1
    kd_neto = p["costo_deuda_pre_impuestos_pen"] * (1 - tasa_impuesto)
    we, wd = 1 / (1 + d_e), d_e / (1 + d_e)
    return ResultadoWACC(beta_l, ke_usd, ke_pen, kd_neto, we, wd, we * ke_pen + wd * kd_neto)


def proyectar(s: dict) -> pd.DataFrame:
    """FCFF = NOPAT + D&A - capex - variación del capital de trabajo."""
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
    return pd.DataFrame({
        "ventas": ventas, "ebitda": ebitda, "dya": dya, "ebit": ebit, "nopat": nopat,
        "capex": capex, "delta_capital_trabajo": delta_ct, "fcff": nopat + dya - capex - delta_ct,
    }, index=pd.Index(anios, name="anio"))


def valorizar(proy: pd.DataFrame, wacc: float, g: float, s: dict, metodo: str = "gordon") -> dict:
    """Valor de la firma y precio por acción.

    Convención de medio año: el flujo del año t se descuenta t - 0.5 años. El valor terminal de
    Gordon es una perpetuidad de flujos que también llegan a mitad de año, así que se descuenta
    N - 0.5 años. El de múltiplo de salida es el precio de una venta al cierre del año N y se
    descuenta N años. Descontar ambos N años subestima el valor de Gordon en (1 + WACC)^0.5.
    """
    n = len(proy)
    t = np.arange(1, n + 1) - 0.5
    vp_flujos = float((proy["fcff"] / (1 + wacc) ** t).sum())
    fcff_n, ebitda_n = float(proy["fcff"].iloc[-1]), float(proy["ebitda"].iloc[-1])
    medio = (1 + wacc) ** 0.5
    if metodo == "gordon":
        if wacc <= g:
            raise ValueError(f"El WACC ({wacc:.2%}) debe ser mayor que el crecimiento perpetuo ({g:.2%}).")
        vt = fcff_n * (1 + g) / (wacc - g)
        vp_vt = vt / (1 + wacc) ** (n - 0.5)
        multiplo_implicito, g_implicito = vt * medio / ebitda_n, g
    elif metodo == "multiplo":
        vt = ebitda_n * s["multiplo_salida_ev_ebitda"]
        vp_vt = vt / (1 + wacc) ** n
        multiplo_implicito = s["multiplo_salida_ev_ebitda"]
        g_implicito = (vt * wacc - fcff_n * medio) / (vt + fcff_n * medio)
    else:
        raise ValueError("metodo debe ser 'gordon' o 'multiplo'")
    ev = vp_flujos + vp_vt
    equity = ev - s["deuda_neta"] - s["intereses_minoritarios"]
    precio = equity / s["acciones_en_circulacion_mm"]
    return {"vp_flujos": vp_flujos, "valor_terminal": vt, "vp_valor_terminal": vp_vt,
            "enterprise_value": ev, "equity_value": equity, "precio_objetivo": precio,
            "pct_ev_terminal": vp_vt / ev, "upside": precio / s["precio_mercado"] - 1,
            "multiplo_ev_ebitda_implicito": multiplo_implicito, "g_implicito": g_implicito}


def sensibilidad(proy: pd.DataFrame, s: dict, wacc_c: float, g_c: float,
                 paso_w: float = 0.005, paso_g: float = 0.005, n: int = 2) -> pd.DataFrame:
    """Precio objetivo (Gordon) para WACC y g alrededor del caso base. Índice y columnas numéricos."""
    waccs = [wacc_c + paso_w * i for i in range(-n, n + 1)]
    gs = [g_c + paso_g * i for i in range(-n, n + 1)]
    tabla = pd.DataFrame([[valorizar(proy, w, g, s)["precio_objetivo"] for g in gs] for w in waccs],
                         index=pd.Index(waccs, name="WACC"), columns=pd.Index(gs, name="g"))
    return tabla


# ---------- figuras ----------
def figura_rangos(rangos: dict[str, tuple[float, float, float]], precio: float, ruta: Path, pie: str):
    """Gráfico de rangos (football field). Cada fila: (mínimo, caso base, máximo)."""
    fig, ax = plt.subplots(figsize=(9, 1.5 + 0.75 * len(rangos)))
    for i, (lo, base, hi) in enumerate(rangos.values()):
        ax.barh(i, hi - lo, left=lo, height=0.32, color=estilo.AZUL)
        ax.plot([base], [i], "o", ms=8, color=estilo.SUPERFICIE, mec=estilo.TINTA, mew=1.5, zorder=4)
        estilo.etiqueta(ax, hi, i, f"S/ {lo:.2f} a {hi:.2f}  ·  base {base:.2f}")
    ax.axvline(precio, color=estilo.TINTA_2, lw=1.2, ls=(0, (4, 3)))
    estilo.etiqueta(ax, precio, -0.68, f"Precio de mercado: S/ {precio:.2f}", dx=6, fontsize=8.5)
    ax.set_yticks(range(len(rangos)), list(rangos))
    ax.set_ylim(len(rangos) - 0.45, -0.95)            # eje invertido: el primer método queda arriba
    lo_min, hi_max = min(v[0] for v in rangos.values()), max(v[2] for v in rangos.values())
    ax.set_xlim(min(lo_min, precio) - 0.8, hi_max + 0.42 * (hi_max - lo_min) + 1.5)
    ax.set_xlabel("Precio por acción (S/)")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    estilo.titulo(ax, "Rango de valorización por método", "El círculo marca el caso base de cada método")
    return estilo.guardar(fig, ruta, pie)


def figura_sensibilidad(sens: pd.DataFrame, precio: float, ruta: Path, pie: str):
    """Tabla de sensibilidad coloreada por signo: azul si el precio objetivo supera al de mercado."""
    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    amplitud = max(abs(sens.to_numpy() - precio).max(), 1e-9)
    ax.imshow(sens.to_numpy(), cmap=estilo.MAPA_DIVERGENTE.reversed(), vmin=precio - amplitud,
              vmax=precio + amplitud, aspect="auto")
    for i in range(sens.shape[0]):
        for j in range(sens.shape[1]):
            v = sens.iat[i, j]
            oscuro = abs(v - precio) / amplitud > 0.55
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=10,
                    color="#ffffff" if oscuro else estilo.TINTA,
                    fontweight="bold" if (i, j) == (sens.shape[0] // 2, sens.shape[1] // 2) else "normal")
    c = sens.shape[0] // 2
    ax.add_patch(plt.Rectangle((c - 0.5, c - 0.5), 1, 1, fill=False, ec=estilo.TINTA, lw=1.8))
    ax.set_xticks(range(sens.shape[1]), [f"{g:.1%}" for g in sens.columns])
    ax.set_yticks(range(sens.shape[0]), [f"{w:.1%}" for w in sens.index])
    ax.set_xlabel("Crecimiento perpetuo (g)")
    ax.set_ylabel("WACC")
    ax.grid(False)
    ax.tick_params(length=0)
    for lado in ax.spines.values():
        lado.set_visible(False)
    estilo.titulo(ax, "Precio objetivo según WACC y crecimiento perpetuo",
                  f"S/ por acción. Azul: sobre el precio de mercado (S/ {precio:.2f}); rojo: debajo. Recuadro: caso base")
    return estilo.guardar(fig, ruta, pie)


def comprobacion(s: dict) -> dict[str, float]:
    """Los valores que la hoja «Comprobación» del Excel compara con sus fórmulas."""
    w = calcular_wacc(s["wacc"], s["tasa_impuesto"])
    proy = proyectar(s)
    gordon = valorizar(proy, w.wacc, s["crecimiento_perpetuo"], s, "gordon")
    multiplo = valorizar(proy, w.wacc, s["crecimiento_perpetuo"], s, "multiplo")
    return {"wacc": w.wacc, **{f"fcff_{i}": float(v) for i, v in enumerate(proy["fcff"], start=1)},
            "ev_gordon": gordon["enterprise_value"], "precio_gordon": gordon["precio_objetivo"],
            "precio_multiplo": multiplo["precio_objetivo"],
            "multiplo_implicito": gordon["multiplo_ev_ebitda_implicito"], "g_implicito": multiplo["g_implicito"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--supuestos", default=AQUI / "supuestos.json", help="archivo JSON con los supuestos")
    ap.add_argument("--excel", action="store_true", help="escribe también resultados/modelo_dcf.xlsx, con fórmulas")
    args = ap.parse_args()
    s = json.loads(Path(args.supuestos).read_text(encoding="utf-8"))
    estilo.aplicar()
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
    for nombre, r in [("Crecimiento perpetuo (Gordon)", gordon), ("Múltiplo de salida", multiplo)]:
        print(f"\n[{nombre}] EV {r['enterprise_value']:,.0f} | Patrimonio {r['equity_value']:,.0f} | "
              f"Precio objetivo S/ {r['precio_objetivo']:.2f} | Potencial {r['upside']:+.1%} | "
              f"VT/EV {r['pct_ev_terminal']:.0%}")
    print(f"\nControl cruzado: Gordon con g = {g:.1%} equivale a vender a {gordon['multiplo_ev_ebitda_implicito']:.1f}x EBITDA; "
          f"salir a {s['multiplo_salida_ev_ebitda']:.1f}x EBITDA equivale a g = {multiplo['g_implicito']:.1%}.")
    imprimible = sens.copy()
    imprimible.index = [f"{x:.1%}" for x in sens.index]
    imprimible.columns = [f"{x:.1%}" for x in sens.columns]
    print("\nSensibilidad del precio objetivo (filas: WACC; columnas: g):")
    print(imprimible.round(2).to_string())

    m = s["multiplo_salida_ev_ebitda"]
    por_multiplo = [valorizar(proy, w.wacc, g, {**s, "multiplo_salida_ev_ebitda": x}, "multiplo")["precio_objetivo"]
                    for x in (m - 1, m + 1)]
    pie = "Supuestos ilustrativos de una empresa ficticia (supuestos.json). Elaboración propia."
    centro = sens.iloc[1:-1, 1:-1].to_numpy()          # WACC y g a medio punto del caso base
    figura_rangos({
        "DCF, crecimiento perpetuo\n(WACC ±0.5 pp, g ±0.5 pp)": (float(centro.min()), gordon["precio_objetivo"],
                                                                float(centro.max())),
        f"DCF, múltiplo de salida\n({m - 1:.0f}x a {m + 1:.0f}x EBITDA)": (por_multiplo[0], multiplo["precio_objetivo"],
                                                                        por_multiplo[1]),
    }, s["precio_mercado"], SALIDA / "rangos_valorizacion.png", pie)
    figura_sensibilidad(sens, s["precio_mercado"], SALIDA / "sensibilidad.png", pie)
    proy.round(2).to_csv(SALIDA / "proyeccion.csv")
    imprimible.round(2).to_csv(SALIDA / "sensibilidad.csv", index_label="WACC")
    if args.excel:
        modelo_excel.construir(s, comprobacion(s), SALIDA / "modelo_dcf.xlsx")
        print(f"\nModelo con fórmulas guardado en {(SALIDA / 'modelo_dcf.xlsx').relative_to(AQUI.parent)}")


if __name__ == "__main__":
    main()
