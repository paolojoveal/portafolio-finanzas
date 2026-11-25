"""Scorecard de riesgo de crédito para consumo: PD, puntaje y pérdida esperada.

Flujo (el estándar de la industria bancaria):
    1. Agrupamiento por cuantiles y cálculo de WoE (Weight of Evidence) e IV (Information Value)
    2. Selección de variables por IV y regresión logística sobre variables WoE
    3. Validación: AUC, Gini, KS en muestra de prueba y PSI (estabilidad)
    4. Escalamiento a puntaje (600 puntos = odds 50:1, PDO = 20)
    5. Pérdida esperada EL = PD × LGD × EAD por cartera y por banda de puntaje

Uso:
    python scorecard.py                   # datos simulados de cartera de consumo
    python scorecard.py --csv cartera.csv # tu propio dataset (columna objetivo: 'default')
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import train_test_split

AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "resultados"
OBJETIVO = "default"
PUNTOS_BASE, ODDS_BASE, PDO = 600, 50, 20


def datos_simulados(n=20_000, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    edad = rng.integers(21, 70, n)
    ingreso = np.round(rng.lognormal(np.log(3500), 0.55, n), -1)       # S/ mensuales
    deuda_ingreso = np.clip(rng.beta(2, 5, n) * 1.2, 0, 1.2)           # ratio
    antiguedad_laboral = np.clip(rng.exponential(5, n), 0, 40)
    atrasos_12m = rng.poisson(0.4, n)
    num_entidades = rng.integers(1, 7, n)                               # bancos con deuda (RCC)
    utilizacion_tc = np.clip(rng.beta(2, 3, n), 0, 1)
    logit = (-4.3 + 2.4 * deuda_ingreso + 0.55 * atrasos_12m + 1.3 * utilizacion_tc
             + 0.18 * num_entidades - 0.04 * antiguedad_laboral - 0.015 * (edad - 40)
             - 0.35 * np.log(ingreso / 3500))
    default = rng.binomial(1, 1 / (1 + np.exp(-logit)))
    saldo = np.round(ingreso * rng.uniform(1, 6, n), -1)
    return pd.DataFrame({
        "edad": edad, "ingreso": ingreso, "deuda_ingreso": deuda_ingreso,
        "antiguedad_laboral": antiguedad_laboral, "atrasos_12m": atrasos_12m,
        "num_entidades": num_entidades, "utilizacion_tc": utilizacion_tc,
        "saldo": saldo, OBJETIVO: default,
    })


# ---------- WoE / IV ----------
def bins_por_cuantiles(x: pd.Series, q=6) -> np.ndarray:
    cortes = np.unique(np.quantile(x, np.linspace(0, 1, q + 1)))
    cortes[0], cortes[-1] = -np.inf, np.inf
    return cortes


def tabla_woe(x: pd.Series, y: pd.Series, cortes) -> pd.DataFrame:
    g = pd.cut(x, cortes)
    t = pd.crosstab(g, y).reindex(columns=[0, 1], fill_value=0) + 0.5  # suavizado
    t.columns = ["buenos", "malos"]
    t["dist_buenos"] = t["buenos"] / t["buenos"].sum()
    t["dist_malos"] = t["malos"] / t["malos"].sum()
    t["woe"] = np.log(t["dist_buenos"] / t["dist_malos"])
    t["iv"] = (t["dist_buenos"] - t["dist_malos"]) * t["woe"]
    t["tasa_default"] = t["malos"] / (t["buenos"] + t["malos"])
    return t


class TransformadorWoE:
    def fit(self, X: pd.DataFrame, y: pd.Series):
        self.cortes, self.tablas = {}, {}
        for c in X:
            self.cortes[c] = bins_por_cuantiles(X[c])
            self.tablas[c] = tabla_woe(X[c], y, self.cortes[c])
        self.iv = pd.Series({c: t["iv"].sum() for c, t in self.tablas.items()}).sort_values(ascending=False)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        out = {}
        for c in X:
            g = pd.cut(X[c], self.cortes[c])
            out[c] = g.map(self.tablas[c]["woe"]).astype(float)
        return pd.DataFrame(out, index=X.index)


def ks(y, p):
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


def psi(esperado, actual, bins=10):
    cortes = np.unique(np.quantile(esperado, np.linspace(0, 1, bins + 1)))
    cortes[0], cortes[-1] = -np.inf, np.inf
    e = np.histogram(esperado, cortes)[0] / len(esperado) + 1e-6
    a = np.histogram(actual, cortes)[0] / len(actual) + 1e-6
    return float(np.sum((a - e) * np.log(a / e)))


def a_puntaje(pd_):
    factor = PDO / np.log(2)
    offset = PUNTOS_BASE - factor * np.log(ODDS_BASE)
    return offset + factor * np.log((1 - pd_) / pd_)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    args = ap.parse_args()
    df = pd.read_csv(args.csv) if args.csv else datos_simulados()
    SALIDA.mkdir(exist_ok=True)

    variables = [c for c in df.columns if c not in (OBJETIVO, "saldo")]
    tr, te = train_test_split(df, test_size=0.3, stratify=df[OBJETIVO], random_state=0)
    woe = TransformadorWoE().fit(tr[variables], tr[OBJETIVO])
    print("Information Value por variable:")
    print(woe.iv.round(3).to_string())
    seleccion = woe.iv[woe.iv >= 0.02].index.tolist()  # IV < 0.02: poder predictivo nulo

    modelo = LogisticRegression(max_iter=1000)
    modelo.fit(woe.transform(tr[seleccion]), tr[OBJETIVO])
    pd_tr = modelo.predict_proba(woe.transform(tr[seleccion]))[:, 1]
    pd_te = modelo.predict_proba(woe.transform(te[seleccion]))[:, 1]

    auc = roc_auc_score(te[OBJETIVO], pd_te)
    metricas = {"AUC": auc, "Gini": 2 * auc - 1, "KS": ks(te[OBJETIVO], pd_te),
                "PSI (entrenamiento vs prueba)": psi(pd_tr, pd_te)}
    print("\nValidación en muestra de prueba:")
    for k, v in metricas.items():
        print(f"  {k:30s} {v:.3f}")

    # Pérdida esperada: LGD por tipo de producto de consumo sin garantía, EAD = saldo
    te = te.assign(pd=pd_te, puntaje=a_puntaje(pd_te), lgd=0.65, ead=te["saldo"])
    te["el"] = te["pd"] * te["lgd"] * te["ead"]
    te["banda"] = pd.qcut(te["puntaje"], 5, labels=["E (peor)", "D", "C", "B", "A (mejor)"])
    resumen = te.groupby("banda", observed=True).agg(
        clientes=("pd", "size"), pd_media=("pd", "mean"), tasa_default_real=(OBJETIVO, "mean"),
        ead=("ead", "sum"), perdida_esperada=("el", "sum"))
    resumen["el_sobre_ead"] = resumen["perdida_esperada"] / resumen["ead"]
    resumen.insert(1, "puntaje_min", te.groupby("banda", observed=True)["puntaje"].min().round(0))
    print("\nPérdida esperada por banda de puntaje (S/):")
    print(resumen.round(3).to_string(float_format=lambda x: f'{x:,.3f}' if abs(x) < 10 else f'{x:,.0f}'))
    print(f"\nPérdida esperada total: S/ {te['el'].sum():,.0f} "
          f"({te['el'].sum() / te['ead'].sum():.2%} de la exposición)")

    coef = pd.Series(modelo.coef_[0], index=seleccion)
    puntos = {}
    factor = PDO / np.log(2)
    for c in seleccion:
        t = woe.tablas[c]
        puntos[c] = (-coef[c] * t["woe"] * factor).round(0)  # contribución por tramo
    with open(SALIDA / "tarjeta_puntaje.txt", "w", encoding="utf-8") as f:
        for c, s in puntos.items():
            f.write(f"\n{c}\n{s.to_string()}\n")

    fpr, tpr, _ = roc_curve(te[OBJETIVO], pd_te)
    fig, axs = plt.subplots(1, 2, figsize=(11, 4))
    axs[0].plot(fpr, tpr, color="#2E5C8A", label=f"AUC {auc:.3f} · Gini {2*auc-1:.3f}")
    axs[0].plot([0, 1], [0, 1], "k--", lw=0.8)
    axs[0].set_title("Curva ROC (prueba)"); axs[0].set_xlabel("Falsos positivos"); axs[0].set_ylabel("Verdaderos positivos")
    axs[0].legend()
    axs[1].bar(resumen.index.astype(str), resumen["tasa_default_real"], color="#2E5C8A", label="Default observado")
    axs[1].plot(resumen.index.astype(str), resumen["pd_media"], "o-", color="#C0392B", label="PD del modelo")
    axs[1].set_title("Calibración por banda de puntaje"); axs[1].legend()
    fig.tight_layout(); fig.savefig(SALIDA / "validacion.png", dpi=150); plt.close(fig)
    resumen.to_csv(SALIDA / "perdida_esperada.csv")


if __name__ == "__main__":
    main()
