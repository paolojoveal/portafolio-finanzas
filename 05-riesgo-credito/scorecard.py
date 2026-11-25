"""Scorecard de riesgo de crédito de consumo: probabilidad de incumplimiento, puntaje y pérdida esperada.

    1. Agrupamiento de cada variable y cálculo de WoE (Weight of Evidence) e IV (Information Value).
       Admite variables numéricas, categóricas y datos faltantes (que forman su propio tramo).
    2. Regresión logística sobre las variables transformadas a WoE, seleccionadas por IV.
    3. Validación en una muestra que el modelo no vio: AUC, Gini, KS y PSI.
    4. Escalamiento a puntaje (600 puntos = 50 buenos por cada malo; 20 puntos duplican esa razón)
       y tarjeta de puntos por tramo, que suma exactamente el puntaje del modelo.
    5. Pérdida esperada EL = PD × LGD × EAD por banda de puntaje.

Uso:
    python scorecard.py                                   # cartera simulada de 20 000 clientes
    python scorecard.py --csv cartera.csv                 # datos propios; la columna objetivo es 'default'
    python scorecard.py --csv datos.csv --objetivo mora --saldo exposicion
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import train_test_split

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))

from common import estilo  # noqa: E402

SALIDA = AQUI / "resultados"
PUNTOS_BASE, ODDS_BASE, PDO = 600, 50, 20
FACTOR = PDO / np.log(2)
DESPLAZAMIENTO = PUNTOS_BASE - FACTOR * np.log(ODDS_BASE)
LGD = 0.65                 # consumo sin garantía
IV_MINIMO = 0.02           # por debajo, la variable no discrimina
BANDAS = ["E (peor)", "D", "C", "B", "A (mejor)"]


def datos_simulados(n: int = 20_000, seed: int = 42) -> pd.DataFrame:
    """Cartera de consumo simulada: el incumplimiento depende de las variables por un modelo logístico conocido."""
    rng = np.random.default_rng(seed)
    edad = rng.integers(21, 70, n)
    ingreso = np.round(rng.lognormal(np.log(3500), 0.55, n), -1)       # S/ mensuales
    deuda_ingreso = np.clip(rng.beta(2, 5, n) * 1.2, 0, 1.2)
    antiguedad_laboral = np.clip(rng.exponential(5, n), 0, 40)
    atrasos_12m = rng.poisson(0.4, n)
    num_entidades = rng.integers(1, 7, n)                               # entidades con deuda en la central de riesgos
    utilizacion_tc = np.clip(rng.beta(2, 3, n), 0, 1)
    logit = (-4.3 + 2.4 * deuda_ingreso + 0.55 * atrasos_12m + 1.3 * utilizacion_tc
             + 0.18 * num_entidades - 0.04 * antiguedad_laboral - 0.015 * (edad - 40)
             - 0.35 * np.log(ingreso / 3500))
    return pd.DataFrame({
        "edad": edad, "ingreso": ingreso, "deuda_ingreso": deuda_ingreso,
        "antiguedad_laboral": antiguedad_laboral, "atrasos_12m": atrasos_12m,
        "num_entidades": num_entidades, "utilizacion_tc": utilizacion_tc,
        "saldo": np.round(ingreso * rng.uniform(1, 6, n), -1),
        "default": rng.binomial(1, 1 / (1 + np.exp(-logit))),
    })


# ---------- WoE / IV ----------
def tabla_woe(tramo: pd.Series, y: pd.Series) -> pd.DataFrame:
    """WoE = ln(% de buenos / % de malos) por tramo. Se suma 0.5 a cada celda para evitar ln(0)."""
    t = pd.crosstab(tramo, y).reindex(columns=[0, 1], fill_value=0) + 0.5
    t.columns = ["buenos", "malos"]
    t["dist_buenos"] = t["buenos"] / t["buenos"].sum()
    t["dist_malos"] = t["malos"] / t["malos"].sum()
    t["woe"] = np.log(t["dist_buenos"] / t["dist_malos"])
    t["iv"] = (t["dist_buenos"] - t["dist_malos"]) * t["woe"]
    t["tasa_default"] = (t["malos"] - 0.5) / (t["buenos"] + t["malos"] - 1)
    return t


class TransformadorWoE:
    """Agrupa cada variable en tramos y la reemplaza por el WoE del tramo.

    Numéricas: tramos por cuantiles. Categóricas: una categoría por tramo; las que tienen menos de
    `frecuencia_minima` de los casos se juntan en «Otros». Los faltantes forman el tramo «Faltante».
    Un valor que no apareció al entrenar recibe WoE 0 (neutral).
    """

    FALTANTE, OTROS = "Faltante", "Otros"

    def __init__(self, tramos: int = 6, frecuencia_minima: float = 0.05):
        self.tramos, self.frecuencia_minima = tramos, frecuencia_minima

    def _definir(self, x: pd.Series):
        if pd.api.types.is_numeric_dtype(x):
            cortes = np.unique(np.quantile(x.dropna(), np.linspace(0, 1, self.tramos + 1)))
            cortes[0], cortes[-1] = -np.inf, np.inf
            return ("numerica", cortes)
        frecuencias = x.value_counts(normalize=True)
        return ("categorica", set(frecuencias[frecuencias >= self.frecuencia_minima].index))

    def _asignar(self, x: pd.Series, regla) -> pd.Series:
        tipo, detalle = regla
        if tipo == "numerica":
            g = pd.cut(x, detalle).astype(object)
        else:
            g = x.where(x.isin(detalle), self.OTROS).astype(object)
        return g.where(x.notna(), self.FALTANTE).astype(str)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "TransformadorWoE":
        self.reglas = {c: self._definir(X[c]) for c in X}
        self.tablas = {c: tabla_woe(self._asignar(X[c], self.reglas[c]), y) for c in X}
        self.iv = pd.Series({c: t["iv"].sum() for c, t in self.tablas.items()}).sort_values(ascending=False)
        return self

    def tramos_de(self, X: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({c: self._asignar(X[c], self.reglas[c]) for c in X}, index=X.index)

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        g = self.tramos_de(X)
        return pd.DataFrame({c: g[c].map(self.tablas[c]["woe"]).fillna(0.0).astype(float) for c in X}, index=X.index)


# ---------- métricas ----------
def ks(y, p) -> float:
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


def psi(esperado, actual, tramos: int = 10) -> float:
    """Population Stability Index entre dos distribuciones de PD. Menos de 0.10: estable."""
    cortes = np.unique(np.quantile(esperado, np.linspace(0, 1, tramos + 1)))
    cortes[0], cortes[-1] = -np.inf, np.inf
    e = np.histogram(esperado, cortes)[0] / len(esperado) + 1e-6
    a = np.histogram(actual, cortes)[0] / len(actual) + 1e-6
    return float(np.sum((a - e) * np.log(a / e)))


def a_puntaje(pd_):
    """Puntaje = desplazamiento + factor · ln(buenos / malos)."""
    return DESPLAZAMIENTO + FACTOR * np.log((1 - pd_) / pd_)


def tarjeta_puntaje(woe: TransformadorWoE, modelo: LogisticRegression, variables: list[str]):
    """Puntos por tramo y puntos base. Para cualquier cliente, base + sus puntos = puntaje del modelo:
    ln(buenos/malos) = -(intercepto + suma de coef·WoE), y el puntaje es lineal en esa cantidad."""
    base = DESPLAZAMIENTO - FACTOR * float(modelo.intercept_[0])
    filas = []
    for c, coef in zip(variables, modelo.coef_[0]):
        for tramo, f in woe.tablas[c].iterrows():
            filas.append({"variable": c, "tramo": tramo, "tasa_default": f["tasa_default"],
                          "woe": f["woe"], "puntos": -coef * f["woe"] * FACTOR})
    return base, pd.DataFrame(filas)


def puntaje_por_tarjeta(tramos: pd.DataFrame, base: float, tarjeta: pd.DataFrame) -> pd.Series:
    total = pd.Series(base, index=tramos.index)
    for c, puntos in tarjeta.groupby("variable"):
        total += tramos[c].map(puntos.set_index("tramo")["puntos"]).fillna(0.0)
    return total


# ---------- figuras ----------
def figura_validacion(y, pd_modelo, resumen: pd.DataFrame, metricas: dict, pie: str):
    fig, (a, b) = plt.subplots(1, 2, figsize=estilo.DOBLE)
    fpr, tpr, _ = roc_curve(y, pd_modelo)
    a.plot([0, 1], [0, 1], color=estilo.CONTEXTO, lw=1.2, label="Modelo sin poder predictivo")
    a.plot(fpr, tpr, color=estilo.AZUL, label="Scorecard")
    a.fill_between(fpr, fpr, tpr, color=estilo.AZUL, alpha=0.10, lw=0)
    a.text(0.97, 0.06, f"AUC {metricas['AUC']:.2f}\nGini {metricas['Gini']:.2f}\nKS {metricas['KS']:.2f}",
           transform=a.transAxes, ha="right", va="bottom", fontsize=10, color=estilo.TINTA, linespacing=1.5)
    a.set_xlabel("Buenos clasificados como malos")
    a.set_ylabel("Malos detectados")
    estilo.formato_pct(a, "x", factor=100)
    estilo.formato_pct(a, "y", factor=100)
    a.grid(axis="x", visible=True)
    estilo.titulo(a, "Poder de discriminación", "Curva ROC en la muestra de prueba")
    a.legend(loc="upper left")

    x = np.arange(len(resumen))
    b.bar(x, resumen["tasa_default_real"] * 100, width=0.42, color=estilo.AZUL, label="Incumplimiento observado")
    b.plot(x, resumen["pd_media"] * 100, "o", ms=9, color=estilo.SUPERFICIE, mec=estilo.TINTA, mew=1.6,
           label="PD media del modelo", zorder=4)
    b.set_xticks(x, resumen.index.astype(str))
    b.set_xlabel("Banda de puntaje (quintiles)")
    estilo.formato_pct(b)
    estilo.titulo(b, "Calibración", "El modelo acierta el nivel de riesgo de cada banda")
    b.legend(loc="upper right")
    return estilo.guardar(fig, SALIDA / "validacion.png", pie)


def figura_iv(iv: pd.Series, pie: str):
    fig, ax = plt.subplots(figsize=(8.2, 0.9 + 0.42 * len(iv)))
    y = np.arange(len(iv))
    ax.barh(y, iv.to_numpy(), height=0.42, color=[estilo.AZUL if v >= IV_MINIMO else estilo.CONTEXTO for v in iv])
    for i, v in enumerate(iv):
        estilo.etiqueta(ax, v, i, f"{v:.3f}" + ("" if v >= IV_MINIMO else "  ·  descartada"))
    ax.axvline(IV_MINIMO, color=estilo.TINTA_2, lw=1.2, ls=(0, (4, 3)))
    estilo.etiqueta(ax, IV_MINIMO, -0.72, f"Mínimo para entrar al modelo: {IV_MINIMO}", dx=6, fontsize=8.5)
    ax.set_yticks(y, iv.index)
    ax.set_ylim(len(iv) - 0.5, -0.95)
    ax.set_xlim(0, iv.max() * 1.35)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    estilo.titulo(ax, "Poder predictivo de cada variable", "Information Value (IV) en la muestra de entrenamiento")
    return estilo.guardar(fig, SALIDA / "information_value.png", pie)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv", help="archivo con los datos; sin esta opción se simula una cartera")
    ap.add_argument("--objetivo", default="default", help="columna 0/1 que marca el incumplimiento")
    ap.add_argument("--saldo", default="saldo", help="columna con la exposición (EAD); opcional")
    args = ap.parse_args()
    estilo.aplicar()
    pd.set_option("display.width", 200)
    df = pd.read_csv(args.csv) if args.csv else datos_simulados()
    if args.objetivo not in df:
        sys.exit(f"No existe la columna objetivo '{args.objetivo}'. Columnas: {', '.join(df.columns)}")
    if set(df[args.objetivo].dropna().unique()) - {0, 1}:
        sys.exit(f"La columna '{args.objetivo}' debe contener solo 0 (cumple) y 1 (incumple).")
    df = df.dropna(subset=[args.objetivo]).astype({args.objetivo: int})
    con_saldo = args.saldo in df
    variables = [c for c in df.columns if c not in (args.objetivo, args.saldo)]
    SALIDA.mkdir(exist_ok=True)

    tr, te = train_test_split(df, test_size=0.3, stratify=df[args.objetivo], random_state=0)
    woe = TransformadorWoE().fit(tr[variables], tr[args.objetivo])
    print(f"Clientes: {len(df):,} (70% entrenamiento, 30% prueba). Tasa de incumplimiento: {df[args.objetivo].mean():.1%}")
    print("\nInformation Value por variable:")
    print(woe.iv.round(3).to_string())
    seleccion = woe.iv[woe.iv >= IV_MINIMO].index.tolist()
    if not seleccion:
        sys.exit("Ninguna variable alcanza el IV mínimo: los datos no permiten construir un scorecard.")

    modelo = LogisticRegression(max_iter=1000).fit(woe.transform(tr[seleccion]), tr[args.objetivo])
    pd_tr = modelo.predict_proba(woe.transform(tr[seleccion]))[:, 1]
    pd_te = modelo.predict_proba(woe.transform(te[seleccion]))[:, 1]
    auc = roc_auc_score(te[args.objetivo], pd_te)
    metricas = {"AUC": auc, "Gini": 2 * auc - 1, "KS": ks(te[args.objetivo], pd_te),
                "PSI (entrenamiento vs. prueba)": psi(pd_tr, pd_te)}
    print("\nValidación en la muestra de prueba:")
    for k, v in metricas.items():
        print(f"  {k:32s} {v:.3f}")

    base, tarjeta = tarjeta_puntaje(woe, modelo, seleccion)
    diferencia = (puntaje_por_tarjeta(woe.tramos_de(te[seleccion]), base, tarjeta) - a_puntaje(pd_te)).abs().max()
    print(f"\nTarjeta de puntaje: {base:.0f} puntos base más los puntos de cada tramo "
          f"(diferencia máxima con el puntaje del modelo: {diferencia:.1e}).")

    te = te.assign(pd=pd_te, puntaje=a_puntaje(pd_te), ead=te[args.saldo] if con_saldo else 1.0)
    te["el"] = te["pd"] * LGD * te["ead"]
    te["banda"] = pd.qcut(te["puntaje"], 5, labels=BANDAS)
    por_banda = te.groupby("banda", observed=True)
    resumen = por_banda.agg(clientes=("pd", "size"), puntaje_min=("puntaje", "min"), pd_media=("pd", "mean"),
                            tasa_default_real=(args.objetivo, "mean"), ead=("ead", "sum"),
                            perdida_esperada=("el", "sum"))
    resumen["el_sobre_ead"] = resumen["perdida_esperada"] / resumen["ead"]
    print(f"\nPérdida esperada por banda (LGD = {LGD:.0%}" + ("" if con_saldo else "; sin columna de saldo, EAD = 1 por cliente") + "):")
    print(resumen.to_string(formatters={"puntaje_min": "{:.0f}".format, "pd_media": "{:.1%}".format,
                                        "tasa_default_real": "{:.1%}".format, "ead": "{:,.0f}".format,
                                        "perdida_esperada": "{:,.0f}".format, "el_sobre_ead": "{:.1%}".format}))
    print(f"\nPérdida esperada total: {te['el'].sum():,.0f} ({te['el'].sum() / te['ead'].sum():.2%} de la exposición)")

    pie = (f"Datos de {Path(args.csv).name}." if args.csv else "Cartera simulada de 20 000 clientes.") + " Elaboración propia."
    figura_validacion(te[args.objetivo], pd_te, resumen, metricas, pie)
    figura_iv(woe.iv, pie)
    resumen.to_csv(SALIDA / "perdida_esperada.csv")
    tarjeta.assign(puntos=tarjeta["puntos"].round(1)).round(4).to_csv(SALIDA / "tarjeta_puntaje.csv", index=False)
    (SALIDA / "tarjeta_puntaje.txt").write_text(
        f"Puntos base: {base:.0f}\n" + "".join(
            f"\n{c}\n" + t[["tramo", "puntos"]].assign(puntos=t["puntos"].round(0).astype(int)).to_string(index=False) + "\n"
            for c, t in tarjeta.groupby("variable", sort=False)), encoding="utf-8")
    print(f"\nFiguras y tablas en {SALIDA.relative_to(AQUI.parent)}/")


if __name__ == "__main__":
    main()
