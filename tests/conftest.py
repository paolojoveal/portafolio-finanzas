"""Carga los scripts de cada proyecto como módulos. Las carpetas empiezan con un número
(01-valorizacion-dcf), así que no se pueden importar con `import`."""
import importlib.util
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def cargar(ruta_relativa: str):
    ruta = RAIZ / ruta_relativa
    if str(ruta.parent) not in sys.path:
        sys.path.insert(0, str(ruta.parent))
    if ruta.stem in sys.modules:
        return sys.modules[ruta.stem]
    spec = importlib.util.spec_from_file_location(ruta.stem, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[ruta.stem] = modulo
    spec.loader.exec_module(modulo)
    return modulo
