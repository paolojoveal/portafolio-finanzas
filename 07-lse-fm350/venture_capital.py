"""Método de valorización de Venture Capital con varias rondas y dilución.

Una startup fintech limeña levanta Serie A hoy y espera una Serie B en 2 años.
    1. Valor terminal a la salida (año 5) = utilidad esperada × P/E de comparables
    2. Valor post-money hoy = valor terminal / (1 + TIR objetivo)^años
    3. Participación requerida por cada inversionista, ajustada por la dilución
       de rondas futuras y del pool de opciones para empleados (ESOP)
    4. Precio por acción y número de acciones nuevas en cada ronda
    5. Comparación con un VPN por escenarios (éxito / mediocre / fracaso), para
       mostrar por qué la TIR objetivo del VC es tan alta: incorpora la probabilidad
       de fracaso que no está en el flujo "de éxito".

    python venture_capital.py
"""
from __future__ import annotations

import pandas as pd

# Supuestos ilustrativos (USD)
UTILIDAD_SALIDA = 6_000_000      # utilidad neta esperada en el año 5 (escenario de éxito)
PE_COMPARABLES = 18
ANIOS_SALIDA = 5
ACCIONES_FUNDADORES = 4_000_000

RONDAS = [  # (nombre, inversión, TIR objetivo, años hasta la salida)
    ("Serie A", 3_000_000, 0.50, 5),
    ("Serie B", 8_000_000, 0.35, 3),
]
ESOP_FINAL = 0.10                 # pool de opciones al momento de la salida

ESCENARIOS = {"Éxito": (0.30, 1.0), "Mediocre": (0.40, 0.25), "Fracaso": (0.30, 0.0)}
COSTO_CAPITAL_DIVERSIFICADO = 0.20


def metodo_vc():
    valor_terminal = UTILIDAD_SALIDA * PE_COMPARABLES
    # Participación final requerida por cada ronda (sobre el capital a la salida)
    finales = {n: inv * (1 + r) ** t / valor_terminal for n, inv, r, t in RONDAS}
    # Retención: cada ronda se diluye por las rondas posteriores y por el ESOP
    filas, retencion = [], 1 - ESOP_FINAL
    for nombre, inv, r, t in reversed(RONDAS):
        retencion_ronda = retencion
        actual = finales[nombre] / retencion_ronda
        filas.append({"ronda": nombre, "inversion": inv, "tir_objetivo": r,
                      "participacion_final": finales[nombre], "retencion": retencion_ronda,
                      "participacion_actual": actual})
        retencion *= 1 - actual
    filas.reverse()

    # Acciones y precios, de la primera a la última ronda
    acciones = ACCIONES_FUNDADORES
    for f in filas:
        nuevas = acciones * f["participacion_actual"] / (1 - f["participacion_actual"])
        f["acciones_nuevas"] = nuevas
        f["precio_accion"] = f["inversion"] / nuevas
        f["post_money"] = f["precio_accion"] * (acciones + nuevas)
        f["pre_money"] = f["post_money"] - f["inversion"]
        acciones += nuevas
    esop = acciones * ESOP_FINAL / (1 - ESOP_FINAL)
    total = acciones + esop
    tabla = pd.DataFrame(filas).set_index("ronda")
    cap = pd.Series({"Fundadores": ACCIONES_FUNDADORES,
                     **{f["ronda"]: f["acciones_nuevas"] for f in filas}, "ESOP": esop}) / total
    return valor_terminal, tabla, cap


def vpn_escenarios(inversion, participacion, valor_terminal):
    esperado = sum(p * mult * valor_terminal for p, mult in ESCENARIOS.values())
    vp = esperado * participacion / (1 + COSTO_CAPITAL_DIVERSIFICADO) ** ANIOS_SALIDA
    return esperado, vp - inversion


def main():
    vt, tabla, cap = metodo_vc()
    print(f"Valor terminal (año {ANIOS_SALIDA}): USD {vt:,.0f}\n")
    fmt = tabla.copy()
    for c in ["tir_objetivo", "participacion_final", "retencion", "participacion_actual"]:
        fmt[c] = fmt[c].map("{:.1%}".format)
    for c in ["inversion", "acciones_nuevas", "post_money", "pre_money"]:
        fmt[c] = fmt[c].map("{:,.0f}".format)
    fmt["precio_accion"] = fmt["precio_accion"].map("{:.3f}".format)
    print(fmt.T.to_string())
    print("\nCap table a la salida:")
    print(cap.map("{:.1%}".format).to_string())

    a = tabla.loc["Serie A"]
    esperado, vpn = vpn_escenarios(a["inversion"], a["participacion_final"], vt)
    print(f"\nChequeo por escenarios para la Serie A: valor esperado a la salida USD {esperado:,.0f}, "
          f"VPN al {COSTO_CAPITAL_DIVERSIFICADO:.0%} = USD {vpn:,.0f}")
    print("Si el VPN es cercano a cero, la TIR objetivo de 50% es coherente con ~30% de probabilidad de éxito.")


if __name__ == "__main__":
    main()
