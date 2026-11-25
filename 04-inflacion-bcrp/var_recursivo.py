"""VAR recursivo estimado por MCO, escrito con numpy para que cada paso sea visible.

    y_t = c + A_1·y_{t-1} + ... + A_p·y_{t-p} + u_t,      u_t ~ (0, Sigma)

Incluye lo necesario para el análisis del proyecto:
    - estimación ecuación por ecuación (MCO), con la opción de excluir observaciones atípicas
      (por ejemplo, los meses de cierre de 2020) como variable dependiente y como rezago
    - selección de rezagos por AIC y BIC sobre una misma muestra
    - funciones impulso-respuesta ortogonalizadas (Cholesky: el orden de las columnas importa)
    - bandas por bootstrap de residuos (percentiles)
    - pronóstico con bandas a partir de la matriz de error cuadrático medio

Las pruebas (tests/test_inflacion.py) comparan los coeficientes con los de statsmodels y
verifican las impulso-respuesta contra un VAR(1) de solución conocida.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class VAR:
    p: int                    # número de rezagos
    c: np.ndarray             # constante, (k,)
    A: np.ndarray             # coeficientes de los rezagos, (p, k, k): A[j] multiplica a y_{t-j-1}
    U: np.ndarray             # residuos, (n, k)
    Sigma: np.ndarray         # covarianza de los residuos (corregida por grados de libertad)
    nobs: int                 # filas usadas en la estimación

    @property
    def k(self) -> int:
        return self.A.shape[1]


def filas_validas(T: int, p: int, excluir: np.ndarray | None = None) -> np.ndarray:
    """Índices t (de p a T-1) en los que ni y_t ni sus p rezagos están marcados para excluir."""
    if excluir is None:
        return np.arange(p, T)
    ex = np.asarray(excluir, dtype=bool)
    return np.array([t for t in range(p, T) if not ex[t - p:t + 1].any()], dtype=int)


def estimar(Y: np.ndarray, p: int, excluir: np.ndarray | None = None,
            filas: np.ndarray | None = None) -> VAR:
    """MCO ecuación por ecuación. Y es (T, k); `excluir` es un vector booleano de largo T."""
    Y = np.asarray(Y, dtype=float)
    k = Y.shape[1]
    filas = filas_validas(len(Y), p, excluir) if filas is None else filas
    Z = np.hstack([np.ones((len(filas), 1))] + [Y[filas - j - 1] for j in range(p)])
    B, *_ = np.linalg.lstsq(Z, Y[filas], rcond=None)        # (1 + k·p, k)
    U = Y[filas] - Z @ B
    Sigma = U.T @ U / (len(filas) - Z.shape[1])
    A = np.stack([B[1 + j * k:1 + (j + 1) * k].T for j in range(p)])
    return VAR(p=p, c=B[0], A=A, U=U, Sigma=Sigma, nobs=len(filas))


def seleccionar_rezagos(Y: np.ndarray, max_p: int, excluir: np.ndarray | None = None) -> dict[str, dict[int, float]]:
    """AIC y BIC para p = 1..max_p, todos sobre la misma muestra (las filas válidas para max_p)."""
    Y = np.asarray(Y, dtype=float)
    k = Y.shape[1]
    filas = filas_validas(len(Y), max_p, excluir)
    n = len(filas)
    criterios: dict[str, dict[int, float]] = {"aic": {}, "bic": {}}
    for p in range(1, max_p + 1):
        m = estimar(Y, p, filas=filas)
        log_det = np.linalg.slogdet(m.U.T @ m.U / n)[1]      # covarianza de máxima verosimilitud
        n_par = k * (1 + k * p)
        criterios["aic"][p] = log_det + 2 * n_par / n
        criterios["bic"][p] = log_det + np.log(n) * n_par / n
    return criterios


def ma(modelo: VAR, horizonte: int) -> np.ndarray:
    """Coeficientes de la representación MA: Psi_0 = I, Psi_h = sum_j Psi_{h-j}·A_j. Forma (h+1, k, k)."""
    k, p = modelo.k, modelo.p
    psi = np.zeros((horizonte + 1, k, k))
    psi[0] = np.eye(k)
    for h in range(1, horizonte + 1):
        for j in range(1, min(h, p) + 1):
            psi[h] += psi[h - j] @ modelo.A[j - 1]
    return psi


def irf(modelo: VAR, horizonte: int) -> np.ndarray:
    """Impulso-respuesta ortogonalizadas. irf[h, i, j]: respuesta de la variable i, h periodos
    después de un choque de una desviación estándar en la variable j."""
    P = np.linalg.cholesky(modelo.Sigma)
    return ma(modelo, horizonte) @ P


def simular(modelo: VAR, y_ini: np.ndarray, U: np.ndarray) -> np.ndarray:
    """Genera una muestra con los coeficientes del modelo, condiciones iniciales y choques dados."""
    p = modelo.p
    Y = np.zeros((p + len(U), modelo.k))
    Y[:p] = y_ini
    for t in range(p, len(Y)):
        Y[t] = modelo.c + U[t - p] + sum(modelo.A[j] @ Y[t - j - 1] for j in range(p))
    return Y


def irf_bootstrap(Y: np.ndarray, p: int, horizonte: int, excluir: np.ndarray | None = None,
                  repeticiones: int = 1000, nivel: float = 0.90, semilla: int = 0):
    """Bandas de percentiles por bootstrap de residuos. Se remuestrean filas completas de
    residuos, lo que conserva su correlación contemporánea. Devuelve (punto, inferior, superior)."""
    Y = np.asarray(Y, dtype=float)
    base = estimar(Y, p, excluir)
    punto = irf(base, horizonte)
    rng = np.random.default_rng(semilla)
    U_c = base.U - base.U.mean(axis=0)
    sims = np.empty((repeticiones, *punto.shape))
    for r in range(repeticiones):
        U_b = U_c[rng.integers(0, len(U_c), len(U_c))]
        sims[r] = irf(estimar(simular(base, Y[:p], U_b), p), horizonte)
    cola = (1 - nivel) / 2
    return punto, np.quantile(sims, cola, axis=0), np.quantile(sims, 1 - cola, axis=0)


def pronosticar(modelo: VAR, Y: np.ndarray, pasos: int, z: float = 1.645):
    """Pronóstico dinámico desde el último dato de Y. Las bandas usan la matriz de error cuadrático
    medio sum_{i<h} Psi_i·Sigma·Psi_i' (no incluyen la incertidumbre de los parámetros)."""
    p, k = modelo.p, modelo.k
    hist = [np.asarray(Y, dtype=float)[-j - 1] for j in range(p)]     # hist[j] = y_{T-j}
    fc = np.zeros((pasos, k))
    for h in range(pasos):
        fc[h] = modelo.c + sum(modelo.A[j] @ hist[j] for j in range(p))
        hist = [fc[h], *hist[:-1]]
    psi = ma(modelo, pasos - 1)
    mse = np.cumsum([ps @ modelo.Sigma @ ps.T for ps in psi], axis=0)
    ee = np.sqrt(np.array([np.diag(m) for m in mse]))
    return fc, fc - z * ee, fc + z * ee
