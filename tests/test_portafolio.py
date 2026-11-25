"""02 · Optimización de portafolio."""
import numpy as np
import pandas as pd
import pytest
from conftest import cargar

opt = cargar("02-optimizacion-portafolio/optimizacion.py")
ACTIVOS = list(opt.ACTIVOS)


@pytest.fixture(scope="module")
def r():
    return opt.datos_demo()


def test_pesos_validos_en_todas_las_estrategias(r):
    w = opt.pesos(r[ACTIVOS].iloc[:36])
    assert set(w) == set(opt.ESTRATEGIAS)
    for nombre, pesos in w.items():
        assert pesos.sum() == pytest.approx(1, abs=1e-6), nombre
        assert (pesos >= -1e-8).all(), nombre
    for nombre in ("Mín. varianza", "Máx. Sharpe", "Black-Litterman"):
        assert w[nombre].max() <= opt.PESO_MAX + 1e-6, nombre


def test_paridad_de_riesgo_iguala_las_contribuciones(r):
    cov = opt.covarianza(r[ACTIVOS].iloc[:36].to_numpy())
    w = opt.paridad_riesgo(np.zeros(len(ACTIVOS)), cov)
    contribucion = w * (cov @ w) / (w @ cov @ w)
    np.testing.assert_allclose(contribucion, 1 / len(ACTIVOS), atol=1e-4)


def test_minima_varianza_es_la_de_menor_varianza(r):
    hist = r[ACTIVOS].iloc[:36]
    cov = opt.covarianza(hist.to_numpy())
    w = opt.pesos(hist)
    varianza = {k: v @ cov @ v for k, v in w.items()}
    assert varianza["Mín. varianza"] <= min(varianza["1/N"], varianza["Máx. Sharpe"]) + 1e-10


def test_black_litterman_sin_vistas_devuelve_el_equilibrio(r):
    cov = opt.covarianza(r[ACTIVOS].iloc[:36].to_numpy())
    n = len(ACTIVOS)
    w = np.full(n, 1 / n)
    sin_vistas = opt.retornos_black_litterman(cov, w, np.zeros((0, n)), np.array([]))
    np.testing.assert_allclose(sin_vistas, 2.5 * cov @ w)


def test_una_vista_optimista_sube_el_retorno_esperado(r):
    cov = opt.covarianza(r[ACTIVOS].iloc[:36].to_numpy())
    n = len(ACTIVOS)
    w = np.full(n, 1 / n)
    previo = 2.5 * cov @ w
    P = np.zeros((1, n)); P[0, 0] = 1
    posterior = opt.retornos_black_litterman(cov, w, P, np.array([previo[0] + 0.01]))
    assert previo[0] < posterior[0] < previo[0] + 0.01       # se mueve hacia la vista sin alcanzarla


def test_el_backtest_no_usa_informacion_futura(r):
    """Cambiar los retornos del último año no puede alterar los resultados de los años anteriores."""
    alterado = r.copy()
    alterado.iloc[-12:] = alterado.iloc[-12:] * 3 - 0.05
    a, b = opt.backtest(r)["neto"], opt.backtest(alterado)["neto"]
    pd.testing.assert_frame_equal(a.iloc[:-12], b.iloc[:-12])
    assert not np.allclose(a.iloc[-12:], b.iloc[-12:])


def test_los_costos_reducen_el_retorno(r):
    sin_costo, con_costo = opt.backtest(r, costo_pb=0)["neto"], opt.backtest(r, costo_pb=50)["neto"]
    assert (con_costo[opt.ESTRATEGIAS].sum() < sin_costo[opt.ESTRATEGIAS].sum()).all()


def test_un_activo_nuevo_espera_a_tener_historia(r):
    tardio = r.copy()
    tardio.iloc[:60, tardio.columns.get_loc("IFS")] = np.nan       # empieza a cotizar en el mes 61
    bt = opt.backtest(tardio)
    assert np.isfinite(bt["neto"].to_numpy()).all()
    assert bt["pesos"].loc["IFS", "1/N"] == pytest.approx(1 / len(ACTIVOS))   # al final ya está en el universo


def test_se_descarta_el_mes_incompleto():
    dias = pd.bdate_range("2024-01-01", "2024-03-12")
    precios = pd.DataFrame({"A": np.linspace(100, 110, len(dias))}, index=dias)
    mensual = opt.a_mensual(precios)
    assert list(mensual.index.month) == [2]                         # enero es la base; marzo está incompleto
