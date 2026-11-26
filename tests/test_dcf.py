"""01 · Valorización DCF."""
import json

import numpy as np
import pytest
from conftest import RAIZ, cargar

dcf = cargar("01-valorizacion-dcf/dcf.py")
modelo_excel = cargar("01-valorizacion-dcf/modelo_excel.py")
S = json.loads((RAIZ / "01-valorizacion-dcf/supuestos.json").read_text(encoding="utf-8"))


def test_wacc_calculado_a_mano():
    w = dcf.calcular_wacc(S["wacc"], S["tasa_impuesto"])
    assert w.beta_apalancado == pytest.approx(0.70 * (1 + 0.705 * 0.45))            # Hamada
    assert w.costo_capital_usd == pytest.approx(0.043 + 0.922075 * 0.05 + 0.016)
    assert w.costo_capital_pen == pytest.approx(1.10510375 * 1.025 / 1.022 - 1)     # paridad de inflación
    assert w.costo_deuda_neto == pytest.approx(0.075 * 0.705)
    assert w.peso_capital + w.peso_deuda == pytest.approx(1)
    assert w.wacc == pytest.approx(0.0911, abs=1e-4)


def test_el_flujo_de_caja_cuadra():
    p = dcf.proyectar(S)
    assert p["ventas"].iloc[0] == pytest.approx(14000 * 1.05)
    np.testing.assert_allclose(p["fcff"], p["nopat"] + p["dya"] - p["capex"] - p["delta_capital_trabajo"])
    np.testing.assert_allclose(p["nopat"], (p["ebitda"] - p["dya"]) * (1 - S["tasa_impuesto"]))


def test_gordon_descuenta_todo_a_mitad_de_anio():
    p, wacc, g = dcf.proyectar(S), 0.09, 0.03
    r = dcf.valorizar(p, wacc, g, S, "gordon")
    n = len(p)
    flujos = sum(f / (1 + wacc) ** (t - 0.5) for t, f in enumerate(p["fcff"], start=1))
    terminal = p["fcff"].iloc[-1] * (1 + g) / (wacc - g) / (1 + wacc) ** (n - 0.5)
    assert r["enterprise_value"] == pytest.approx(flujos + terminal)
    assert r["equity_value"] == pytest.approx(r["enterprise_value"] - S["deuda_neta"])
    assert r["precio_objetivo"] == pytest.approx(r["equity_value"] / S["acciones_en_circulacion_mm"])


def test_los_dos_metodos_coinciden_con_el_supuesto_implicito():
    """Valorizar por Gordon con el g que implica el múltiplo de salida debe dar el mismo valor."""
    p, wacc = dcf.proyectar(S), 0.0911
    por_multiplo = dcf.valorizar(p, wacc, 0.03, S, "multiplo")
    por_gordon = dcf.valorizar(p, wacc, por_multiplo["g_implicito"], S, "gordon")
    assert por_gordon["enterprise_value"] == pytest.approx(por_multiplo["enterprise_value"])
    assert por_gordon["multiplo_ev_ebitda_implicito"] == pytest.approx(S["multiplo_salida_ev_ebitda"])


def test_sensibilidad_tiene_el_signo_correcto():
    p = dcf.proyectar(S)
    sens = dcf.sensibilidad(p, S, 0.09, 0.03)
    assert sens.iloc[2, 2] == pytest.approx(dcf.valorizar(p, 0.09, 0.03, S)["precio_objetivo"])
    assert (np.diff(sens.to_numpy(), axis=0) < 0).all()       # más WACC, menos valor
    assert (np.diff(sens.to_numpy(), axis=1) > 0).all()       # más crecimiento, más valor


def test_wacc_menor_que_g_no_tiene_sentido():
    with pytest.raises(ValueError):
        dcf.valorizar(dcf.proyectar(S), 0.03, 0.04, S, "gordon")



# ---------- el modelo en Excel ----------
def evaluar(ruta):
    """Calcula el libro con un motor de fórmulas independiente de Excel y devuelve un lector de celdas."""
    formulas = pytest.importorskip("formulas")
    solucion = formulas.ExcelModel().loads(str(ruta)).finish().calculate()

    def valor(referencia: str):
        hoja, celda = referencia.replace("$", "").replace("'", "").split("!")
        v = solucion[f"'[{ruta.name}]{hoja.upper()}'!{celda}"].value
        return v[0, 0] if hasattr(v, "shape") else v
    return valor


OTROS_SUPUESTOS = {"crecimiento_ventas": [0.08, 0.07, 0.06, 0.05, 0.04], "margen_ebitda": [0.10] * 5, "deuda_neta": 3000,
                   "intereses_minoritarios": 120, "crecimiento_perpetuo": 0.025, "multiplo_salida_ev_ebitda": 7.0}
TRES_ANIOS = {"crecimiento_ventas": [0.06, 0.05, 0.04], "margen_ebitda": [0.11, 0.12, 0.12]}


@pytest.mark.parametrize("cambios", [{}, OTROS_SUPUESTOS, TRES_ANIOS], ids=["publicados", "otros", "tres_anios"])
def test_el_modelo_en_excel_reproduce_el_calculo(tmp_path, cambios):
    """El libro no guarda resultados: con cualquier juego de supuestos, sus fórmulas dan lo que da Python."""
    s = {**json.loads(json.dumps(S)), **cambios}
    esperado = dcf.comprobacion(s)
    celdas = modelo_excel.construir(s, esperado, tmp_path / "modelo.xlsx")
    valor = evaluar(tmp_path / "modelo.xlsx")
    for clave, v in esperado.items():
        assert valor(celdas[clave]) == pytest.approx(v, rel=1e-9), clave
    assert valor(celdas["coincide"]) == "Sí"
    sens = dcf.sensibilidad(dcf.proyectar(s), s, esperado["wacc"], s["crecimiento_perpetuo"])
    en_excel = [[valor(f"Sensibilidad!{c}{f}") for c in "BCDEF"] for f in range(5, 10)]
    np.testing.assert_allclose(np.array(en_excel, dtype=float), sens.to_numpy(), rtol=1e-9)


def test_el_modelo_publicado_esta_al_dia():
    ruta = RAIZ / "01-valorizacion-dcf/resultados/modelo_dcf.xlsx"
    valor = evaluar(ruta)
    esperado = dcf.comprobacion(S)
    assert valor("'Valorización'!B19") == pytest.approx(esperado["precio_gordon"], rel=1e-9)
    assert valor("'Valorización'!C19") == pytest.approx(esperado["precio_multiplo"], rel=1e-9)


def test_las_hojas_de_calculo_no_tienen_cifras_escritas_a_mano(tmp_path):
    """Regla de modelos financieros: los supuestos viven en una sola hoja; lo demás son fórmulas."""
    from openpyxl import load_workbook
    modelo_excel.construir(S, dcf.comprobacion(S), tmp_path / "modelo.xlsx")
    libro = load_workbook(tmp_path / "modelo.xlsx")
    assert libro["Supuestos"]["B9"].value == S["ventas_base"] and libro["Supuestos"]["B9"].font.color.rgb.endswith("0000FF")
    for nombre in ("WACC", "Proyección", "Valorización", "Sensibilidad"):
        celdas = [c for fila in libro[nombre].iter_rows() for c in fila if c.value is not None]
        numeros = [c.coordinate for c in celdas if isinstance(c.value, (int, float))]
        assert numeros == (["C6"] if nombre == "Valorización" else []), (nombre, numeros)   # C6: el medio año inicial
        assert sum(str(c.value).startswith("=") for c in celdas) >= 7, nombre
