"""06 · Tablero: la aplicación de Streamlit corre completa en modo demo, sin navegador ni conexión."""
import sys

from conftest import RAIZ


def test_el_tablero_corre_en_modo_demo(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(sys, "argv", ["app.py", "--demo"])
    app = AppTest.from_file(str(RAIZ / "06-dashboard-macro" / "app.py"), default_timeout=120).run()
    assert not app.exception
    assert len(app.metric) == 5
    assert app.title[0].value == "Perú: tablero macro-financiero"
