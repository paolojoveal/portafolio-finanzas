"""07 · Finanzas corporativas avanzadas: estructura de capital, LBO, venture capital y M&A."""
import numpy as np
import pytest
from conftest import cargar

ec = cargar("07-lse-fm350/estructura_capital.py")
lbo = cargar("07-lse-fm350/lbo.py")
vc = cargar("07-lse-fm350/venture_capital.py")
ma = cargar("07-lse-fm350/fusiones.py")


# ---------- estructura de capital ----------
def test_sin_deuda_el_valor_es_vu_y_el_wacc_es_ku():
    vu, ku, fcff_1 = ec.valor_sin_deuda()
    assert vu == pytest.approx(650 * 0.705 * 0.70 * 1.03 / (ku - 0.03))
    fila = ec.evaluar(0, vu, fcff_1)
    assert fila["apv"] == pytest.approx(vu) and fila["wacc_implicito"] == pytest.approx(ku)


def test_maximo_apv_y_minimo_wacc_son_el_mismo_nivel_de_deuda():
    t = ec.tabla_de_deuda()
    assert t["apv"].idxmax() == t["wacc_implicito"].idxmin()
    assert (t["cobertura"].diff().dropna() < 0).all()         # más deuda, menos cobertura
    assert (t["kd"].diff().dropna() >= 0).all()               # y un costo de deuda que no baja
    con_deuda = t.iloc[1:]
    np.testing.assert_allclose(con_deuda["apv"], ec.valor_sin_deuda()[0] + con_deuda["vp_escudo_fiscal"]
                               - con_deuda["vp_costos_quiebra"])


def test_el_escudo_fiscal_se_limita_al_ebit():
    vu, _, fcff_1 = ec.valor_sin_deuda()
    fila = ec.evaluar(20_000, vu, fcff_1)                     # intereses muy por encima del EBIT
    intereses = 20_000 * fila["kd"]
    assert fila["vp_escudo_fiscal"] == pytest.approx(ec.TASA_IMPUESTO * ec.EBIT / intereses * 20_000)


# ---------- LBO ----------
def test_fuentes_igual_a_usos_y_el_puente_cuadra():
    r = lbo.correr(lbo.S)
    assert sum(r["fuentes"].values()) == pytest.approx(sum(r["usos"].values()))
    partes = [v for k, v in r["puente"].items() if k != "Capital a la salida"]
    assert sum(partes) == pytest.approx(r["puente"]["Capital a la salida"])
    assert r["tir"] == pytest.approx(r["mom"] ** (1 / lbo.S["anios"]) - 1)
    assert r["mom"] == pytest.approx(2.86, abs=0.01) and r["tir"] == pytest.approx(0.234, abs=0.001)


def test_la_deuda_senior_baja_y_la_pik_se_capitaliza():
    p = lbo.correr(lbo.S)["proy"]
    assert (p["deuda_senior"].diff().dropna() < 0).all()
    np.testing.assert_allclose(p["deuda_sub"].iloc[-1], 150 * 1.12 ** 5)
    assert (p["caja"] >= lbo.S["caja_minima"]).all()


def test_sensibilidad_de_la_tir():
    s = lbo.sensibilidad(lbo.S)
    assert (np.diff(s.to_numpy(), axis=0) < 0).all()          # comprar más caro baja la TIR
    assert (np.diff(s.to_numpy(), axis=1) > 0).all()          # vender más caro la sube


# ---------- venture capital ----------
def test_cada_inversionista_alcanza_su_tir_objetivo():
    valor, tabla, cap = vc.metodo_vc()
    assert cap.sum() == pytest.approx(1) and cap["ESOP"] == pytest.approx(vc.ESOP_FINAL)
    for nombre, inversion, tir, anios in vc.RONDAS:
        assert cap[nombre] * valor == pytest.approx(inversion * (1 + tir) ** anios)
    assert tabla.loc["Serie A", "participacion_al_entrar"] == pytest.approx(0.2939, abs=1e-4)
    assert tabla.loc["Serie A", "post_money"] == pytest.approx(3_000_000 / tabla.loc["Serie A", "participacion_al_entrar"])
    assert tabla.loc["Serie B", "precio_accion"] > tabla.loc["Serie A", "precio_accion"]


def test_el_retorno_esperado_es_menor_que_la_tir_objetivo():
    valor, tabla, _ = vc.metodo_vc()
    a = tabla.loc["Serie A"]
    esperado, vpn, retorno = vc.vpn_escenarios(a["inversion"], a["participacion_final"], valor)
    assert esperado == pytest.approx(0.30 * valor + 0.40 * 0.25 * valor)
    assert retorno == pytest.approx(0.249, abs=0.001) and retorno < a["tir_objetivo"]
    assert vpn == pytest.approx(esperado * a["participacion_final"] / 1.2 ** 5 - a["inversion"])


def test_la_historia_del_capital_termina_en_las_participaciones_finales():
    _, tabla, cap = vc.metodo_vc()
    historia = vc.historia_del_capital(tabla)
    np.testing.assert_allclose(historia.sum(axis=1), 1)
    np.testing.assert_allclose(historia.iloc[-1][cap.index], cap)
    assert (historia["Fundadores"].diff().dropna() < 0).all()  # los fundadores se diluyen en cada evento


# ---------- fusiones ----------
def test_valor_de_sinergias_y_vpn():
    sv = ma.valor_sinergias()
    assert sv["total"] == pytest.approx(sv["costos"] + sv["ingresos"] + sv["integracion"])
    assert sv["total"] == pytest.approx(825, abs=1)
    assert sv["integracion"] < 0


def test_pagar_con_acciones_caras_diluye_sin_sinergias():
    pe_comprador = ma.COMPRADOR["precio"] / (ma.COMPRADOR["utilidad_neta"] / ma.COMPRADOR["acciones"])
    pe_pagado = ma.OBJETIVO["precio"] * (1 + ma.PRIMA) / (ma.OBJETIVO["utilidad_neta"] / ma.OBJETIVO["acciones"])
    assert pe_pagado > pe_comprador
    assert ma.accretion(ma.PRIMA, 1.0, 0)["accretion"] < 0
    barato = ma.accretion(-0.50, 1.0, 0)                       # si se pagara menos P/E que el propio, aumentaría
    assert barato["accretion"] > 0


def test_la_sinergia_de_equilibrio_deja_la_upa_igual():
    for pct in (0.0, 0.5, 1.0):
        s = ma.sinergia_de_equilibrio(ma.PRIMA, pct)
        assert ma.accretion(ma.PRIMA, pct, s)["accretion"] == pytest.approx(0, abs=1e-12)
    assert ma.sinergia_de_equilibrio(ma.PRIMA, 1.0) == pytest.approx(155, abs=1)
