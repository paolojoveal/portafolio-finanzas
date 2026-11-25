"""Genera docs/banner.svg. Las dos líneas del banner son datos reales del BCRP: la inflación a
12 meses y la tasa de referencia desde 2004 (se leen de la caché que deja el proyecto 04).

    python 04-inflacion-bcrp/inflacion_bcrp.py   # descarga los datos
    python docs/hacer_banner.py
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from common.data import bcrp_series  # noqa: E402

ANCHO, ALTO = 1280, 320
X0, X1, Y0, Y1 = 610, 1216, 86, 240          # área del gráfico
FONDO, TEXTO, TEXTO_2, GUIA = "#0f1e33", "#f4f3ef", "#a9b4c4", "#2a3b55"
AZUL, NARANJA = "#5a9cf0", "#f08a5d"
FUENTE = "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


def main() -> None:
    d = bcrp_series(["ipc_var12m", "tasa_referencia"], start="2003-1").dropna().loc["2004-01-01":]
    maximo = 9.0
    x = lambda i: X0 + (X1 - X0) * i / (len(d) - 1)
    y = lambda v: Y1 - (Y1 - Y0) * v / maximo
    puntos = lambda s: " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(s))
    anios = [a for a in (2005, 2010, 2015, 2020, 2025)]
    marcas = "".join(
        f'<text x="{x(list(d.index.year).index(a)):.0f}" y="{Y1 + 22}" text-anchor="middle" font-size="12" fill="{TEXTO_2}">{a}</text>'
        for a in anios)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ANCHO} {ALTO}" width="{ANCHO}" height="{ALTO}" role="img"
     aria-label="Portafolio de finanzas, macroeconomía y riesgos. Paolo Jove.">
  <rect width="{ANCHO}" height="{ALTO}" rx="14" fill="{FONDO}"/>
  <g font-family="{FUENTE}">
    <text x="64" y="112" font-size="15" font-weight="600" letter-spacing="2.2" fill="{AZUL}">PAOLO JOVE · PUCP</text>
    <text x="64" y="162" font-size="38" font-weight="700" fill="{TEXTO}">Finanzas, macroeconomía</text>
    <text x="64" y="208" font-size="38" font-weight="700" fill="{TEXTO}">y riesgos</text>
    <text x="64" y="250" font-size="17" fill="{TEXTO_2}">Siete proyectos en Python aplicados al mercado peruano</text>
    <rect x="{X0}" y="{y(3):.1f}" width="{X1 - X0}" height="{y(1) - y(3):.1f}" fill="#1baf7a" opacity="0.16"/>
    <line x1="{X0}" y1="{Y1}" x2="{X1}" y2="{Y1}" stroke="{GUIA}" stroke-width="1"/>
    <polyline points="{puntos(d['tasa_referencia'])}" fill="none" stroke="{NARANJA}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
    <polyline points="{puntos(d['ipc_var12m'])}" fill="none" stroke="{AZUL}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
    {marcas}
    <g font-size="12.5" fill="{TEXTO_2}">
      <line x1="{X0}" y1="62" x2="{X0 + 22}" y2="62" stroke="{AZUL}" stroke-width="2.4" stroke-linecap="round"/>
      <text x="{X0 + 30}" y="66">Inflación a 12 meses</text>
      <line x1="{X0 + 178}" y1="62" x2="{X0 + 200}" y2="62" stroke="{NARANJA}" stroke-width="2.4" stroke-linecap="round"/>
      <text x="{X0 + 208}" y="66">Tasa de referencia del BCRP</text>
      <rect x="{X0 + 400}" y="56" width="22" height="12" fill="#1baf7a" opacity="0.3"/>
      <text x="{X0 + 430}" y="66">Rango meta</text>
    </g>
    <text x="{X1}" y="{ALTO - 20}" text-anchor="end" font-size="11.5" fill="{TEXTO_2}">Datos: BCRP, {d.index[0]:%Y} a {d.index[-1]:%m/%Y}</text>
  </g>
</svg>
'''
    (RAIZ / "docs" / "banner.svg").write_text(svg, encoding="utf-8")
    print("docs/banner.svg generado con datos hasta", f"{d.index[-1]:%m/%Y}")


if __name__ == "__main__":
    main()
