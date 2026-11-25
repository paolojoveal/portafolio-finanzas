"""04 · Inflación y política monetaria: VAR propio, brecha del producto y regla de Taylor."""
import numpy as np
import pandas as pd
import pytest
from conftest import cargar

var = cargar("04-inflacion-bcrp/var_recursivo.py")
m = cargar("04-inflacion-bcrp/inflacion_bcrp.py")


def var_conocido(A, c=None, sigma=None):
    A = np.asarray(A, dtype=float)
    k = A.shape[-1]
    A = A.reshape(-1, k, k)
    return var.VAR(p=len(A), c=np.zeros(k) if c is None else np.asarray(c, dtype=float), A=A, U=np.zeros((1, k)),
                   Sigma=np.eye(k) if sigma is None else np.asarray(sigma, dtype=float), nobs=1)


def test_coincide_con_statsmodels():
    from statsmodels.tsa.api import VAR as VARsm
    rng = np.random.default_rng(0)
    verdadero = var_conocido([[[0.5, 0.1, 0.0], [0.0, 0.4, 0.2], [0.1, 0.0, 0.3]],
                              [[0.2, 0.0, 0.0], [0.0, 0.1, 0.0], [0.0, 0.0, 0.2]]], c=[0.1, 0.2, 0.3])
    Y = var.simular(verdadero, np.zeros((2, 3)), rng.normal(size=(400, 3)))
    propio, referencia = var.estimar(Y, 2), VARsm(Y).fit(2, trend="c")
    np.testing.assert_allclose(propio.c, referencia.intercept, atol=1e-8)
    np.testing.assert_allclose(propio.A, referencia.coefs, atol=1e-8)
    np.testing.assert_allclose(propio.Sigma, referencia.sigma_u, atol=1e-8)
    np.testing.assert_allclose(var.irf(propio, 12), referencia.irf(12).orth_irfs, atol=1e-8)


def test_impulso_respuesta_de_un_var1_conocido():
    A = np.array([[0.5, 0.1], [0.0, 0.3]])
    respuestas = var.irf(var_conocido(A), 6)               # con Sigma = I, la respuesta en h es A^h
    for h in range(7):
        np.testing.assert_allclose(respuestas[h], np.linalg.matrix_power(A, h), atol=1e-12)


def test_el_orden_de_cholesky_impide_el_efecto_contemporaneo():
    modelo = var_conocido([[0.5, 0.0], [0.0, 0.5]], sigma=[[1.0, 0.6], [0.6, 1.0]])
    impacto = var.irf(modelo, 0)[0]
    assert impacto[0, 1] == pytest.approx(0)               # la 2.ª variable no mueve a la 1.ª en el mismo periodo
    assert impacto[1, 0] == pytest.approx(0.6)


def test_el_pronostico_converge_a_la_media_incondicional():
    A, c = np.array([[0.5, 0.1], [0.0, 0.3]]), np.array([1.0, 2.0])
    fc, lo, hi = var.pronosticar(var_conocido(A, c), np.array([[10.0, -5.0]]), 200)
    np.testing.assert_allclose(fc[0], c + A @ np.array([10.0, -5.0]))
    np.testing.assert_allclose(fc[-1], np.linalg.solve(np.eye(2) - A, c), atol=1e-8)
    assert ((hi - lo)[1:] >= (hi - lo)[:-1] - 1e-12).all()   # la incertidumbre no baja con el horizonte


def test_las_filas_excluidas_no_entran_ni_como_rezago():
    excluir = np.zeros(20, dtype=bool); excluir[10] = True
    assert list(var.filas_validas(20, 2, excluir)) == [2, 3, 4, 5, 6, 7, 8, 9, 13, 14, 15, 16, 17, 18, 19]
    rng = np.random.default_rng(1)
    Y = rng.normal(size=(300, 2)).cumsum(axis=0) * 0.1
    sucio = Y.copy(); sucio[150] += 100                      # un dato absurdo
    marca = np.zeros(300, dtype=bool); marca[150] = True
    limpio, con_marca = var.estimar(np.delete(Y, 150, axis=0), 1), var.estimar(sucio, 1, marca)
    assert np.abs(con_marca.A - limpio.A).max() < 0.05       # excluirlo deja la estimación casi intacta
    assert np.abs(var.estimar(sucio, 1).A - limpio.A).max() > 0.05


def test_la_brecha_no_se_contamina_con_la_pandemia():
    fechas = pd.date_range("2005-01-01", "2026-09-01", freq="MS")
    tendencia = pd.Series(100 * np.exp(0.0035 * np.arange(len(fechas))), index=fechas)
    con_cierre = tendencia.copy()
    con_cierre.loc["2020-03-01":"2020-08-01"] *= np.exp(np.array([-15, -40, -30, -14, -7, -4]) / 100)
    brecha = m.brecha_producto(con_cierre)
    assert abs(brecha.loc["2019-06-01":"2020-02-01"]).max() < 0.5      # antes del cierre: sin brecha
    assert brecha.loc["2020-04-01"] == pytest.approx(-40, abs=1.0)
    from statsmodels.tsa.filters.hp_filter import hpfilter
    ingenua = hpfilter(np.log(con_cierre), lamb=14400)[0] * 100          # el filtro con los meses de cierre
    assert ingenua.loc["2020-02-01"] > 2                                 # inventa un auge previo


def test_la_regla_de_taylor_recupera_los_parametros_simulados():
    d = m.preparar(m.datos_demo(seed=11, pandemia=False))
    e = m.regla_taylor(d, "ipc_var12m")
    for nombre, verdadero in [("rho", m.DEMO["rho"]), ("phi_pi", m.DEMO["phi_pi"]), ("phi_y", m.DEMO["phi_y"]),
                              ("tasa_neutral", m.DEMO["tasa_real_neutral"] + m.META)]:
        estimado, error = e[nombre]
        assert abs(estimado - verdadero) < 3 * error + 0.05, f"{nombre}: {estimado:.2f} frente a {verdadero}"
    assert e["phi_pi"][0] > 1                                            # principio de Taylor


def test_el_var_le_gana_al_pronostico_ingenuo_en_la_economia_simulada():
    d = m.preparar(m.datos_demo())
    evaluacion = m.evaluar_pronostico(d, p=1)
    assert evaluacion.loc[12, "VAR / ingenuo"] < 1
    assert evaluacion.loc[1, "VAR / ingenuo, con 2020"] > evaluacion.loc[1, "VAR / ingenuo"]
