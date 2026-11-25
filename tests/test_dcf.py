"""01 · Valorización DCF."""
import json

import numpy as np
import pytest
from conftest import RAIZ, cargar

dcf = cargar("01-valorizacion-dcf/dcf.py")
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
