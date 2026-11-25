# 02 · Optimización de portafolio: Perú + diversificadores globales

**Área:** Asset Management · Inversiones

Compara cinco formas de construir un portafolio con acciones peruanas listadas en NYSE (Credicorp, Southern Copper, Buenaventura, Intercorp Financial) y diversificadores globales (S&P 500, emergentes, bonos y oro), contra el ETF MSCI Peru (EPU).

| Estrategia | Idea |
|---|---|
| 1/N | Pesos iguales, referencia ingenua difícil de vencer |
| Mínima varianza | Solo usa la matriz de covarianzas |
| Máximo Sharpe | Markowitz clásico con tope de 35% por activo |
| Paridad de riesgo | Cada activo aporta el mismo riesgo al portafolio |
| Black-Litterman | Equilibrio de mercado + vistas del analista (ej. cobre supera al S&P 500) |

**Metodología:** ventana móvil de 36 meses, rebalanceo mensual y evaluación **fuera de muestra** (los pesos de cada mes se estiman solo con información disponible hasta ese momento, sin sesgo de anticipación). Métricas: retorno y volatilidad anualizados, Sharpe y máximo drawdown.

## Cómo correrlo

```bash
python optimizacion.py          # descarga precios reales con yfinance
python optimizacion.py --demo   # datos simulados, para probar sin conexión
```

Genera en `resultados/`: `backtest.png`, `frontera.png`, `metricas.csv` y `pesos_actuales.csv`.

## Qué demuestra

Teoría moderna de portafolios aplicada con disciplina de backtesting, manejo de estimación de covarianzas y la capacidad de traducir una tesis de inversión (vistas) en pesos mediante Black-Litterman.
