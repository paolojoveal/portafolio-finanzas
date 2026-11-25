"""03 · VaR, Expected Shortfall y backtesting."""
import numpy as np
import pytest
from conftest import cargar
from scipy import stats

v = cargar("03-var-backtesting/var_backtesting.py")


def test_var_normal_contra_la_formula():
    rng = np.random.default_rng(0)
    z = rng.normal(size=5000)
    z = (z - z.mean()) / z.std(ddof=1)                    # media 0 y desviación 1 exactas
    var, es = v.var_normal(z)
    assert var == pytest.approx(2.3263, abs=1e-4)         # cuantil 99% de la normal estándar
    assert es == pytest.approx(2.6652, abs=1e-4)          # phi(2.3263) / 0.01


def test_var_historico_es_el_cuantil_empirico():
    x = -np.arange(1, 1001) / 1000                        # pérdidas de 0.1% a 100%
    var, es = v.var_historico(x)
    assert var == pytest.approx(0.99, abs=1e-3)
    assert es > var


def test_es_de_la_t_contra_una_simulacion():
    rng = np.random.default_rng(1)
    x = stats.t.rvs(5, loc=0.0005, scale=0.012, size=200_000, random_state=rng)
    var, es = v.var_t(x)
    q = np.quantile(x, 0.01)
    assert var == pytest.approx(-q, rel=0.03)
    assert es == pytest.approx(-x[x <= q].mean(), rel=0.03)
    assert es > var


def test_ewma_converge_a_la_volatilidad_constante():
    r = np.tile([0.01, -0.01], 500)
    sigma = v.volatilidad_ewma(r, semilla=10)
    assert sigma[-1] == pytest.approx(0.01, rel=1e-6)


def test_ewma_no_mira_el_retorno_del_dia():
    r = np.full(600, 0.01)
    r[550] = 0.20
    sigma = v.volatilidad_ewma(r)
    assert sigma[550] == pytest.approx(sigma[549])        # el salto de hoy no está en el pronóstico de hoy
    assert sigma[551] > sigma[550] * 2                    # recién se incorpora mañana


def test_historico_filtrado_sin_cambio_de_volatilidad_es_el_historico():
    rng = np.random.default_rng(2)
    x = rng.normal(0, 0.01, 500)
    assert v.var_historico_filtrado(x, np.full(500, 0.01), 0.01) == pytest.approx(v.var_historico(x))
    doble = v.var_historico_filtrado(x, np.full(500, 0.01), 0.02)
    assert doble[0] == pytest.approx(2 * v.var_historico(x)[0])


def test_kupiec_valores_conocidos():
    exactas = np.zeros(1000, dtype=bool); exactas[:10] = True       # 1% de excepciones: lo esperado
    assert v.kupiec(exactas)[0] == pytest.approx(0, abs=1e-9)
    diez_en_250 = np.zeros(250, dtype=bool); diez_en_250[::25] = True
    lr, p = v.kupiec(diez_en_250)
    assert lr == pytest.approx(-2 * (240 * np.log(0.99 / 0.96) + 10 * np.log(0.01 / 0.04)))
    assert lr == pytest.approx(12.955, abs=0.01) and p < 0.001
    assert v.kupiec(np.zeros(250, dtype=bool))[0] == pytest.approx(-2 * 250 * np.log(0.99))


def test_christoffersen_detecta_excepciones_agrupadas():
    agrupadas = np.zeros(1000, dtype=bool); agrupadas[500:510] = True
    dispersas = np.zeros(1000, dtype=bool); dispersas[50::100] = True
    assert v.christoffersen(agrupadas)[1] < 0.01
    assert v.christoffersen(dispersas)[1] > 0.10


def test_semaforo_de_basilea():
    assert [v.semaforo_basilea(n) for n in (0, 4, 5, 9, 10, 25)] == ["Verde", "Verde", "Amarillo", "Amarillo", "Rojo", "Rojo"]
