"""05 · Scorecard de riesgo de crédito."""
import numpy as np
import pandas as pd
import pytest
from conftest import cargar
from sklearn.linear_model import LogisticRegression

sc = cargar("05-riesgo-credito/scorecard.py")


def test_woe_calculado_a_mano():
    tramo = pd.Series(["bajo"] * 100 + ["alto"] * 100)
    y = pd.Series([0] * 90 + [1] * 10 + [0] * 60 + [1] * 40)
    t = sc.tabla_woe(tramo, y)
    buenos, malos = 150 + 1.0, 50 + 1.0                      # totales con el suavizado de 0.5 por celda
    assert t.loc["bajo", "woe"] == pytest.approx(np.log((90.5 / buenos) / (10.5 / malos)))
    assert t.loc["alto", "woe"] == pytest.approx(np.log((60.5 / buenos) / (40.5 / malos)))
    assert t.loc["bajo", "woe"] > 0 > t.loc["alto", "woe"]   # WoE positivo = mejor que el promedio
    assert t.loc["bajo", "tasa_default"] == pytest.approx(0.10)
    assert t["iv"].sum() > 0


def test_el_iv_separa_variables_utiles_de_ruido():
    df = sc.datos_simulados(8000, seed=3)
    df["ruido"] = np.random.default_rng(0).normal(size=len(df))
    iv = sc.TransformadorWoE().fit(df[["deuda_ingreso", "ruido"]], df["default"]).iv
    assert iv["deuda_ingreso"] > 0.10
    assert iv["ruido"] < sc.IV_MINIMO


def test_faltantes_y_categorias():
    X = pd.DataFrame({"ingreso": [1000, 2000, np.nan, 4000, 5000, np.nan] * 50,
                      "region": ["Lima", "Lima", "Cusco", None, "Lima", "Cusco"] * 50})
    y = pd.Series([0, 0, 1, 0, 0, 1] * 50)
    woe = sc.TransformadorWoE().fit(X, y)
    assert "Faltante" in woe.tablas["ingreso"].index and "Faltante" in woe.tablas["region"].index
    transformado = woe.transform(X)
    assert not transformado.isna().any().any()
    nuevo = woe.transform(pd.DataFrame({"ingreso": [3000.0], "region": ["Tacna"]}))    # categoría no vista
    assert nuevo["region"].iloc[0] == pytest.approx(woe.tablas["region"]["woe"].get("Otros", 0.0))


def test_escala_del_puntaje():
    assert sc.a_puntaje(1 / 51) == pytest.approx(600)        # 50 buenos por cada malo
    assert sc.a_puntaje(1 / 101) == pytest.approx(620)       # el doble de buenos por malo: 20 puntos más
    assert sc.a_puntaje(1 / 26) == pytest.approx(580)


def test_la_tarjeta_reproduce_el_puntaje_del_modelo():
    df = sc.datos_simulados(6000, seed=1)
    variables = ["deuda_ingreso", "atrasos_12m", "utilizacion_tc", "num_entidades"]
    woe = sc.TransformadorWoE().fit(df[variables], df["default"])
    modelo = LogisticRegression(max_iter=1000).fit(woe.transform(df[variables]), df["default"])
    pd_modelo = modelo.predict_proba(woe.transform(df[variables]))[:, 1]
    base, tarjeta = sc.tarjeta_puntaje(woe, modelo, variables)
    por_tarjeta = sc.puntaje_por_tarjeta(woe.tramos_de(df[variables]), base, tarjeta)
    np.testing.assert_allclose(por_tarjeta, sc.a_puntaje(pd_modelo), atol=1e-8)
    peor, mejor = tarjeta[tarjeta["variable"] == "atrasos_12m"].sort_values("tasa_default").iloc[[-1, 0]]["puntos"]
    assert mejor > peor                                       # menos atrasos, más puntos


def test_ks_y_psi():
    y = np.array([0] * 50 + [1] * 50)
    assert sc.ks(y, np.linspace(0, 1, 100)) == pytest.approx(1.0)        # separación perfecta
    rng = np.random.default_rng(0)
    a, b = rng.beta(2, 8, 5000), rng.beta(2, 8, 5000)
    assert sc.psi(a, b) < 0.01
    assert sc.psi(a, rng.beta(4, 6, 5000)) > 0.25                        # la población cambió
