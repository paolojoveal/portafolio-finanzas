"""Método de valorización de venture capital con varias rondas y dilución.

Una fintech limeña levanta su Serie A hoy y espera una Serie B en dos años.
    1. Valor a la salida (año 5) = utilidad esperada × P/E de comparables
    2. Participación que cada inversionista necesita a la salida para alcanzar su TIR objetivo
    3. Participación que debe pedir hoy, corregida por la dilución de las rondas posteriores y
       del pool de opciones para empleados (ESOP)
    4. Acciones nuevas, precio por acción y valor pre y post-money de cada ronda
    5. Contraste con un VPN por escenarios: la TIR objetivo es alta porque el flujo «de éxito»
       no incluye la probabilidad de fracaso

    python venture_capital.py
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

# Supuestos ilustrativos (USD)
UTILIDAD_SALIDA = 6_000_000      # utilidad neta esperada en el año 5, en el escenario de éxito
PE_COMPARABLES = 18
ANIOS_SALIDA = 5
ACCIONES_FUNDADORES = 4_000_000
RONDAS = [  # (nombre, inversión, TIR objetivo, años hasta la salida)
    ("Serie A", 3_000_000, 0.50, 5),
    ("Serie B", 8_000_000, 0.35, 3),
]
ESOP_FINAL = 0.10                # pool de opciones al momento de la salida
ESCENARIOS = {"Éxito": (0.30, 1.0), "Mediocre": (0.40, 0.25), "Fracaso": (0.30, 0.0)}   # (probabilidad, fracción del valor)
COSTO_CAPITAL_DIVERSIFICADO = 0.20


def metodo_vc(rondas=RONDAS, esop: float = ESOP_FINAL, valor_salida: float = UTILIDAD_SALIDA * PE_COMPARABLES):
    """Devuelve (valor a la salida, tabla por ronda, participaciones a la salida)."""
    finales = {n: inv * (1 + r) ** t / valor_salida for n, inv, r, t in rondas}
    filas, retencion = [], 1 - esop                       # fracción que conserva quien entra en esa ronda
    for nombre, inv, r, _ in reversed(rondas):
        hoy = finales[nombre] / retencion
        filas.append({"ronda": nombre, "inversion": inv, "tir_objetivo": r, "participacion_final": finales[nombre],
                      "retencion": retencion, "participacion_al_entrar": hoy})
        retencion *= 1 - hoy
    filas.reverse()

    acciones = ACCIONES_FUNDADORES
    for f in filas:
        nuevas = acciones * f["participacion_al_entrar"] / (1 - f["participacion_al_entrar"])
        f["acciones_nuevas"] = nuevas
        f["precio_accion"] = f["inversion"] / nuevas
        f["post_money"] = f["precio_accion"] * (acciones + nuevas)
        f["pre_money"] = f["post_money"] - f["inversion"]
        acciones += nuevas
    total = acciones / (1 - esop)
    cap = pd.Series({"Fundadores": ACCIONES_FUNDADORES, **{f["ronda"]: f["acciones_nuevas"] for f in filas},
                     "ESOP": total - acciones}) / total
    return valor_salida, pd.DataFrame(filas).set_index("ronda"), cap


def historia_del_capital(tabla: pd.DataFrame, esop: float = ESOP_FINAL) -> pd.DataFrame:
    """Participaciones después de cada evento: fundación, cada ronda y la creación del ESOP."""
    partes = pd.Series({"Fundadores": 1.0})
    historia = {"Fundación": partes}
    for ronda, f in tabla.iterrows():
        partes = pd.concat([partes * (1 - f["participacion_al_entrar"]), pd.Series({ronda: f["participacion_al_entrar"]})])
        historia[f"Tras la {ronda}"] = partes
    historia["Salida (con ESOP)"] = pd.concat([partes * (1 - esop), pd.Series({"ESOP": esop})])
    orden = ["Fundadores", *tabla.index, "ESOP"]            # el orden fija el color de cada grupo
    return pd.DataFrame(historia).T.reindex(columns=orden).fillna(0.0)


def vpn_escenarios(inversion: float, participacion_final: float, valor_salida: float) -> tuple[float, float, float]:
    """Valor esperado a la salida, VPN al costo de capital diversificado y retorno anual esperado."""
    esperado = sum(p * fraccion * valor_salida for p, fraccion in ESCENARIOS.values())
    cobro = esperado * participacion_final
    return (esperado, cobro / (1 + COSTO_CAPITAL_DIVERSIFICADO) ** ANIOS_SALIDA - inversion,
            (cobro / inversion) ** (1 / ANIOS_SALIDA) - 1)


def figura(historia: pd.DataFrame, pie: str):
    fig, ax = plt.subplots(figsize=(9, 3.9))
    izquierda = pd.Series(0.0, index=historia.index)
    for parte, color in zip(historia.columns, estilo.SERIE):
        ancho = historia[parte] * 100
        ax.barh(historia.index, ancho, left=izquierda, height=0.5, color=color, edgecolor=estilo.SUPERFICIE,
                linewidth=2, label=parte)
        for y, (x0, w) in enumerate(zip(izquierda, ancho)):
            if w >= 7:
                ax.text(x0 + w / 2, y, f"{w:.0f}%", ha="center", va="center", fontsize=9.5,
                        color="#0b0b0b" if color == estilo.AMARILLO else "#ffffff")
        izquierda += ancho
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    estilo.formato_pct(ax, "x")
    ax.grid(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=len(historia.columns))
    estilo.titulo(ax, "Cómo se diluyen los fundadores ronda a ronda", "Participación en el capital después de cada evento")
    return estilo.guardar(fig, SALIDA / "venture_capital.png", pie)


def main():
    estilo.aplicar()
    pd.set_option("display.width", 200)
    valor, tabla, cap = metodo_vc()
    print(f"Valor a la salida (año {ANIOS_SALIDA}): USD {valor:,.0f}\n")
    fmt = tabla.copy()
    for c in ["tir_objetivo", "participacion_final", "retencion", "participacion_al_entrar"]:
        fmt[c] = fmt[c].map("{:.1%}".format)
    for c in ["inversion", "acciones_nuevas", "post_money", "pre_money"]:
        fmt[c] = fmt[c].map("{:,.0f}".format)
    fmt["precio_accion"] = fmt["precio_accion"].map("{:.3f}".format)
    print(fmt.T.to_string())
    print("\nParticipaciones a la salida:")
    print(cap.map("{:.1%}".format).to_string())
    a = tabla.loc["Serie A"]
    esperado, vpn, retorno = vpn_escenarios(a["inversion"], a["participacion_final"], valor)
    print(f"\nContraste por escenarios para la Serie A: valor esperado a la salida USD {esperado:,.0f}; "
          f"VPN al {COSTO_CAPITAL_DIVERSIFICADO:.0%} = USD {vpn:,.0f}; retorno esperado {retorno:.1%} anual.")
    print(f"La TIR objetivo de {a['tir_objetivo']:.0%} es el retorno si todo sale bien. Ponderando por la probabilidad\n"
          "de éxito, el retorno esperado es la mitad: la TIR objetivo alta es la forma de cobrar el riesgo de fracaso.")
    SALIDA.mkdir(exist_ok=True)
    historia = historia_del_capital(tabla)
    figura(historia, "Supuestos ilustrativos (al inicio del script). Elaboración propia.")
    tabla.to_csv(SALIDA / "venture_capital_rondas.csv")
    historia.round(4).to_csv(SALIDA / "venture_capital_participaciones.csv")


if __name__ == "__main__":
    main()
