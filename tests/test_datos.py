"""Capa de datos: lectura de la API del BCRP y validación de descargas (sin conexión)."""
import numpy as np
import pandas as pd
import pytest

from common.data import SERIES_BCRP, ErrorDeDatos, _parse_periodo, serie_desde_json, validar_precios


def respuesta(nombre_oficial, periodos):
    return {"config": {"series": [{"name": nombre_oficial}]},
            "periods": [{"name": n, "values": [v]} for n, v in periodos]}


def test_periodos_mensuales_del_bcrp():
    assert _parse_periodo("Ene.2024") == pd.Timestamp("2024-01-01")
    assert _parse_periodo("Set.2019") == pd.Timestamp("2019-09-01")   # el BCRP ha usado «Set» y «Sep»
    assert _parse_periodo("Sep.2019") == pd.Timestamp("2019-09-01")
    assert _parse_periodo("Dic.2003") == pd.Timestamp("2003-12-01")


def test_periodo_no_mensual_falla_con_mensaje_claro():
    with pytest.raises(ErrorDeDatos):
        _parse_periodo("T1.2024")


def test_serie_con_dato_no_disponible():
    js = respuesta("Índice de precios Lima Metropolitana (var% 12 meses) - IPC",
                   [("Ene.2024", "3.02"), ("Feb.2024", "n.d."), ("Mar.2024", "3.05")])
    s = serie_desde_json(js, "ipc_var12m", "(var% 12 meses) - IPC")
    assert list(s.index) == list(pd.date_range("2024-01-01", periods=3, freq="MS"))
    assert s.iloc[0] == pytest.approx(3.02) and np.isnan(s.iloc[1]) and s.iloc[2] == pytest.approx(3.05)


def test_rechaza_una_serie_distinta_de_la_esperada():
    """El error original del repositorio: pedir inflación y recibir otra serie sin que nada falle."""
    otra = respuesta("Tasas de interés del Banco Central de Reserva - Tasa de Referencia de la Política Monetaria",
                     [("Ene.2024", "6.5")])
    with pytest.raises(ErrorDeDatos, match="no es la esperada"):
        serie_desde_json(otra, "ipc_var12m", "(var% 12 meses) - IPC")
    parecida = respuesta("Índice de precios Lima Metropolitana (var% 12 meses) - IPC Sin Alimentos", [("Ene.2024", "2.9")])
    with pytest.raises(ErrorDeDatos):
        serie_desde_json(parecida, "ipc_var12m", "(var% 12 meses) - IPC")


def test_codigos_del_bcrp_sin_repetir():
    codigos = [codigo for codigo, _, _ in SERIES_BCRP.values()]
    assert len(codigos) == len(set(codigos))


def test_precios_incompletos_no_pasan_la_validacion():
    fechas = pd.bdate_range("2024-01-01", periods=60)
    df = pd.DataFrame({"BAP": np.linspace(100, 110, 60), "SCCO": np.nan}, index=fechas)
    with pytest.raises(ErrorDeDatos, match="SCCO"):
        validar_precios(df, ["BAP", "SCCO"])
    with pytest.raises(ErrorDeDatos, match="EPU"):
        validar_precios(df[["BAP"]], ["BAP", "EPU"])
    validar_precios(df[["BAP"]], ["BAP"])
