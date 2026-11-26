"""El modelo de valorización como libro de Excel con fórmulas vivas.

    `dcf.py` calcula la valorización en Python. Este módulo escribe el mismo modelo en Excel, pero
    cada cifra es una fórmula: quien lo abre puede cambiar un supuesto y ver cómo se mueve el
    precio objetivo. La hoja «Comprobación» pone lado a lado lo que calcula Excel y lo que calculó
    Python, y dice si coinciden.

    Convención de los modelos financieros: azul para los supuestos, negro para las fórmulas.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

AZUL, TINTA = "0000FF", "000000"
PCT, PCT2, NUM, NUM2, ENTERO, VECES = "0.0%", "0.00%", "#,##0", "#,##0.00", "0", '0.0"x"'
RELLENO = PatternFill("solid", fgColor="184F95")
SUAVE = PatternFill("solid", fgColor="EEF3FA")
LINEA = Border(top=Side(style="thin", color="52514E"))

S, W, P, V = "Supuestos", "WACC", "'Proyección'", "'Valorización'"


def _hoja(libro: Workbook, titulo: str, subtitulo: str, anchos: list[float]):
    hoja = libro.create_sheet(titulo)
    hoja["A1"] = titulo
    hoja["A1"].font = Font(bold=True, size=14)
    hoja["A2"] = subtitulo
    hoja["A2"].font = Font(italic=True, color="52514E")
    for i, ancho in enumerate(anchos, start=1):
        hoja.column_dimensions[get_column_letter(i)].width = ancho
    hoja.sheet_view.showGridLines = False
    return hoja


def _encabezado(hoja, fila: int, textos: list, desde: int = 1) -> None:
    for j, texto in enumerate(textos, start=desde):
        c = hoja.cell(fila, j, texto)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), RELLENO
        c.alignment = Alignment(horizontal="left" if j == 1 else "right")


def _seccion(hoja, fila: int, texto: str, columnas: int) -> None:
    for j in range(1, columnas + 1):
        hoja.cell(fila, j).fill = SUAVE
    hoja.cell(fila, 1, texto).font = Font(bold=True)


def _fila(hoja, fila: int, etiqueta: str, valores, formato: str, columna: int = 2, entrada: bool = False,
          negrita: bool = False, linea: bool = False) -> None:
    """Escribe una etiqueta y una o varias celdas. Las entradas van en azul; las fórmulas, en negro."""
    hoja.cell(fila, 1, etiqueta).font = Font(bold=negrita)
    if linea:
        hoja.cell(fila, 1).border = LINEA
    for j, valor in enumerate(valores if isinstance(valores, (list, tuple)) else [valores], start=columna):
        c = hoja.cell(fila, j, valor)
        c.number_format = formato
        c.font = Font(color=AZUL if entrada else TINTA, bold=negrita)
        c.alignment = Alignment(horizontal="right")
        if linea:
            c.border = LINEA


def construir(s: dict, comprobacion: dict[str, float], ruta: Path) -> dict[str, str]:
    """Escribe el libro y devuelve las celdas clave, por nombre.

    `comprobacion` trae los valores calculados en Python, con las claves `wacc`, `fcff_1`...`fcff_n`,
    `ev_gordon`, `precio_gordon`, `precio_multiplo`, `multiplo_implicito` y `g_implicito`.
    """
    n = len(s["crecimiento_ventas"])
    anios = [get_column_letter(3 + i) for i in range(n)]          # columnas C, D, ... de los años proyectados
    ultimo = anios[-1]
    libro = Workbook()
    libro.remove(libro.active)

    # ---------- Supuestos ----------
    h = _hoja(libro, "Supuestos", "En azul, lo que se puede cambiar. Todo lo demás del libro son fórmulas.",
              [46] + [13] * max(n, 2))
    h["A4"], h["B4"] = "Empresa", s["empresa"]
    h["A5"], h["B5"] = "Cifras en", s["moneda"]
    h["B4"].font = h["B5"].font = Font(color=AZUL)
    _seccion(h, 7, "Operación", n + 1)
    _fila(h, 8, "Año base", s["anio_base"], ENTERO, entrada=True)
    _fila(h, 9, "Ventas del año base", s["ventas_base"], NUM, entrada=True)
    _fila(h, 10, "Tasa de impuesto a la renta", s["tasa_impuesto"], PCT, entrada=True)
    _fila(h, 11, "Depreciación y amortización, % de las ventas", s["dya_pct_ventas"], PCT, entrada=True)
    _fila(h, 12, "Capex, % de las ventas", s["capex_pct_ventas"], PCT, entrada=True)
    _fila(h, 13, "Capital de trabajo, % de las ventas", s["capital_trabajo_pct_ventas"], PCT, entrada=True)
    _seccion(h, 15, "Proyección por año", n + 1)
    _fila(h, 16, "Año", [f"=B8+{i}" for i in range(1, n + 1)], ENTERO, negrita=True)
    _fila(h, 17, "Crecimiento de las ventas", list(s["crecimiento_ventas"]), PCT, entrada=True)
    _fila(h, 18, "Margen EBITDA", list(s["margen_ebitda"]), PCT, entrada=True)
    _seccion(h, 20, "Valor terminal y puente al patrimonio", n + 1)
    _fila(h, 21, "Crecimiento perpetuo (g)", s["crecimiento_perpetuo"], PCT, entrada=True)
    _fila(h, 22, "Múltiplo de salida EV/EBITDA", s["multiplo_salida_ev_ebitda"], VECES, entrada=True)
    _fila(h, 23, "Deuda neta", s["deuda_neta"], NUM, entrada=True)
    _fila(h, 24, "Intereses minoritarios", s["intereses_minoritarios"], NUM, entrada=True)
    _fila(h, 25, "Acciones en circulación (millones)", s["acciones_en_circulacion_mm"], NUM, entrada=True)
    _fila(h, 26, "Precio de mercado (S/ por acción)", s["precio_mercado"], NUM2, entrada=True)
    _seccion(h, 28, "Costo de capital", n + 1)
    w = s["wacc"]
    _fila(h, 29, "Beta desapalancado", w["beta_desapalancado"], NUM2, entrada=True)
    _fila(h, 30, "Deuda / capital propio (D/E)", w["deuda_sobre_capital"], NUM2, entrada=True)
    _fila(h, 31, "Tasa libre de riesgo, en dólares", w["tasa_libre_riesgo_usd"], PCT, entrada=True)
    _fila(h, 32, "Prima por riesgo de mercado", w["prima_riesgo_mercado"], PCT, entrada=True)
    _fila(h, 33, "Riesgo país (EMBIG)", w["riesgo_pais_embig"], PCT, entrada=True)
    _fila(h, 34, "Inflación de largo plazo, soles", w["inflacion_largo_plazo_pen"], PCT, entrada=True)
    _fila(h, 35, "Inflación de largo plazo, dólares", w["inflacion_largo_plazo_usd"], PCT, entrada=True)
    _fila(h, 36, "Costo de la deuda antes de impuestos, soles", w["costo_deuda_pre_impuestos_pen"], PCT, entrada=True)

    # ---------- WACC ----------
    h = _hoja(libro, "WACC", "CAPM con riesgo país, llevado de dólares a soles por diferencial de inflación.", [50, 14])
    _fila(h, 4, "Beta apalancado (Hamada)", f"={S}!B29*(1+(1-{S}!B10)*{S}!B30)", NUM2)
    _fila(h, 5, "Costo del capital propio, en dólares", f"={S}!B31+B4*{S}!B32+{S}!B33", PCT2)
    _fila(h, 6, "Costo del capital propio, en soles", f"=(1+B5)*(1+{S}!B34)/(1+{S}!B35)-1", PCT2)
    _fila(h, 7, "Costo de la deuda después de impuestos", f"={S}!B36*(1-{S}!B10)", PCT2)
    _fila(h, 8, "Peso del capital propio", f"=1/(1+{S}!B30)", PCT)
    _fila(h, 9, "Peso de la deuda", f"={S}!B30/(1+{S}!B30)", PCT)
    _fila(h, 10, "WACC", "=B8*B6+B9*B7", PCT2, negrita=True, linea=True)
    wacc = f"{W}!$B$10"

    # ---------- Proyección ----------
    h = _hoja(libro, "Proyección", "Flujo de caja libre de la firma: NOPAT + depreciación - capex - variación del capital de trabajo.",
              [46] + [13] * (n + 1))
    _encabezado(h, 4, ["Año", f"={S}!B8"] + [f"={get_column_letter(1 + i)}4+1" for i in range(1, n + 1)])
    for j in range(2, n + 3):
        h.cell(4, j).number_format = ENTERO
    origen = [get_column_letter(2 + i) for i in range(n)]         # columnas B, C, ... de la hoja de supuestos
    previo = ["B"] + anios[:-1]
    _fila(h, 5, "Crecimiento de las ventas", [f"={S}!{c}17" for c in origen], PCT, columna=3)
    _fila(h, 6, "Ventas", [f"={S}!B9"] + [f"={a}6*(1+{c}5)" for a, c in zip(previo, anios)], NUM, negrita=True)
    _fila(h, 7, "Margen EBITDA", [f"={S}!{c}18" for c in origen], PCT, columna=3)
    _fila(h, 8, "EBITDA", [f"={c}6*{c}7" for c in anios], NUM, columna=3)
    _fila(h, 9, "Depreciación y amortización", [f"={c}6*{S}!$B$11" for c in anios], NUM, columna=3)
    _fila(h, 10, "EBIT", [f"={c}8-{c}9" for c in anios], NUM, columna=3)
    _fila(h, 11, "Impuesto sobre el EBIT", [f"={c}10*{S}!$B$10" for c in anios], NUM, columna=3)
    _fila(h, 12, "NOPAT", [f"={c}10-{c}11" for c in anios], NUM, columna=3)
    _fila(h, 13, "Capex", [f"={c}6*{S}!$B$12" for c in anios], NUM, columna=3)
    _fila(h, 14, "Variación del capital de trabajo", [f"=({c}6-{a}6)*{S}!$B$13" for a, c in zip(previo, anios)], NUM, columna=3)
    _fila(h, 15, "Flujo de caja libre de la firma (FCFF)", [f"={c}12+{c}9-{c}13-{c}14" for c in anios], NUM, columna=3,
          negrita=True, linea=True)

    # ---------- Valorización ----------
    h = _hoja(libro, "Valorización", "Convención de medio año: el flujo del año t llega, en promedio, en t - 0.5.",
              [46] + [16] * (n + 1))
    _encabezado(h, 4, ["Año", ""] + [f"={P}!{c}4" for c in anios])
    for j in range(3, n + 3):
        h.cell(4, j).number_format = ENTERO
    _fila(h, 5, "Flujo de caja libre de la firma (FCFF)", [f"={P}!{c}15" for c in anios], NUM, columna=3)
    _fila(h, 6, "Años hasta el flujo", [0.5] + [f"={a}6+1" for a in anios[:-1]], "0.0", columna=3)
    _fila(h, 7, "Factor de descuento", [f"=1/(1+{wacc})^{c}6" for c in anios], "0.0000", columna=3)
    _fila(h, 8, "Valor presente del flujo", [f"={c}5*{c}7" for c in anios], NUM, columna=3)
    _encabezado(h, 10, ["Valor terminal por", "Crecimiento perpetuo", "Múltiplo de salida"])
    medio = f"(1+{wacc})^0.5"
    _fila(h, 11, "Valor presente de los flujos", [f"=SUM(C8:{ultimo}8)", "=B11"], NUM)
    _fila(h, 12, "Valor terminal", [f"={ultimo}5*(1+{S}!B21)/({wacc}-{S}!B21)", f"={P}!{ultimo}8*{S}!B22"], NUM)
    _fila(h, 13, "Valor presente del valor terminal", [f"=B12/(1+{wacc})^{ultimo}6", f"=C12/(1+{wacc})^({ultimo}6+0.5)"], NUM)
    _fila(h, 14, "Valor de la firma (EV)", ["=B11+B13", "=C11+C13"], NUM, negrita=True, linea=True)
    _fila(h, 15, "Deuda neta", [f"={S}!B23", f"={S}!B23"], NUM)
    _fila(h, 16, "Intereses minoritarios", [f"={S}!B24", f"={S}!B24"], NUM)
    _fila(h, 17, "Valor del patrimonio", ["=B14-B15-B16", "=C14-C15-C16"], NUM, negrita=True, linea=True)
    _fila(h, 18, "Acciones en circulación (millones)", [f"={S}!B25", f"={S}!B25"], NUM)
    _fila(h, 19, "Precio objetivo (S/ por acción)", ["=B17/B18", "=C17/C18"], NUM2, negrita=True)
    _fila(h, 20, "Precio de mercado (S/ por acción)", [f"={S}!B26", f"={S}!B26"], NUM2)
    _fila(h, 21, "Potencial frente al precio de mercado", ["=B19/B20-1", "=C19/C20-1"], PCT)
    _fila(h, 22, "Valor terminal como parte del EV", ["=B13/B14", "=C13/C14"], PCT)
    _seccion(h, 24, "Control cruzado: lo que cada método supone en el otro", 3)
    _fila(h, 25, "Múltiplo EV/EBITDA de salida", [f"=B12*{medio}/{P}!{ultimo}8", f"={S}!B22"], VECES)
    _fila(h, 26, "Crecimiento perpetuo", [f"={S}!B21", f"=(C12*{wacc}-{ultimo}5*{medio})/(C12+{ultimo}5*{medio})"], PCT2)

    # ---------- Sensibilidad ----------
    h = _hoja(libro, "Sensibilidad", "Precio objetivo (crecimiento perpetuo) según el WACC, en filas, y el crecimiento perpetuo, en columnas.",
              [16] + [12] * 5)
    pasos = [-0.010, -0.005, 0.0, 0.005, 0.010]
    _encabezado(h, 4, ["WACC \\ g"] + [f"={S}!$B$21{paso:+.3f}" for paso in pasos])
    for j in range(2, 7):
        h.cell(4, j).number_format = PCT
    flujos = "+".join(f"{V}!${c}$5/(1+$A{{f}})^{V}!${c}$6" for c in anios)
    terminal = f"{V}!${ultimo}$5*(1+{{c}}$4)/($A{{f}}-{{c}}$4)/(1+$A{{f}})^{V}!${ultimo}$6"
    for i, paso in enumerate(pasos):
        f = 5 + i
        h.cell(f, 1, f"={wacc}{paso:+.3f}").number_format = PCT2
        h.cell(f, 1).font = Font(bold=True)
        for j in range(5):
            c = get_column_letter(2 + j)
            formula = f"=({flujos}+{terminal}-{S}!$B$23-{S}!$B$24)/{S}!$B$25".replace("{f}", str(f)).replace("{c}", c)
            h.cell(f, 2 + j, formula).number_format = NUM2
    h.cell(7, 4).font = Font(bold=True)
    h.conditional_formatting.add("B5:F9", ColorScaleRule(start_type="min", start_color="EF8F8E", mid_type="percentile",
                                                         mid_value=50, mid_color="F0EFEC", end_type="max",
                                                         end_color="6DA7EC"))

    # ---------- Comprobación ----------
    h = _hoja(libro, "Comprobación", "Lo que calcula Excel con las fórmulas frente a lo que calculó Python (dcf.py) con los supuestos originales.",
              [46, 16, 16, 14])
    _encabezado(h, 4, ["Concepto", "Python", "Excel", "Diferencia"])
    celdas = {"wacc": wacc, **{f"fcff_{i + 1}": f"{P}!{c}15" for i, c in enumerate(anios)},
              "ev_gordon": f"{V}!B14", "precio_gordon": f"{V}!B19", "precio_multiplo": f"{V}!C19",
              "multiplo_implicito": f"{V}!B25", "g_implicito": f"{V}!C26"}
    etiquetas = {"wacc": ("WACC", "0.0000%"), "ev_gordon": ("Valor de la firma, crecimiento perpetuo", NUM2),
                 "precio_gordon": ("Precio objetivo, crecimiento perpetuo", "0.0000"),
                 "precio_multiplo": ("Precio objetivo, múltiplo de salida", "0.0000"),
                 "multiplo_implicito": ("Múltiplo de salida implícito", "0.0000"),
                 "g_implicito": ("Crecimiento perpetuo implícito", "0.0000%"),
                 **{f"fcff_{i + 1}": (f"FCFF del año {i + 1}", NUM2) for i in range(n)}}
    fila = 5
    for clave, celda in celdas.items():
        etiqueta, formato = etiquetas[clave]
        h.cell(fila, 1, etiqueta)
        h.cell(fila, 2, float(comprobacion[clave])).number_format = formato
        h.cell(fila, 3, f"={celda}").number_format = formato
        h.cell(fila, 4, f"=C{fila}-B{fila}").number_format = "0.000000"
        fila += 1
    h.cell(fila + 1, 1, "¿Las fórmulas reproducen el cálculo de Python?").font = Font(bold=True)
    h.cell(fila + 1, 2, f'=IF(SUMPRODUCT(ABS(D5:D{fila - 1}))<0.000001,"Sí","No")').font = Font(bold=True)
    h.cell(fila + 2, 1, "Si cambias un supuesto, las diferencias dejan de ser cero: Python usó los originales.").font = Font(
        italic=True, color="52514E")
    celdas["coincide"] = f"'Comprobación'!B{fila + 1}"

    libro.calculation.fullCalcOnLoad = True                # Excel recalcula todo al abrir el archivo
    ruta.parent.mkdir(parents=True, exist_ok=True)
    libro.save(ruta)
    return celdas
