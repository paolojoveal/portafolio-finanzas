# 03 · VaR, Expected Shortfall y backtesting regulatorio

**Área:** Gestión de Riesgo de Mercado

Mide el riesgo diario de un portafolio de USD 1 millón en acciones peruanas (Credicorp, Southern Copper, Buenaventura) y el ETF MSCI Peru, y evalúa si los modelos de VaR "aciertan" como exigen Basilea y la SBS.

**Modelos** (VaR y ES al 99%, 1 día, ventana móvil de 500 días):

- Simulación histórica
- Paramétrico normal
- EWMA / RiskMetrics (λ = 0.94), que reacciona a los cambios de volatilidad
- Monte Carlo con t de Student, para colas pesadas

**Backtesting:**

- **Kupiec (POF):** ¿la cantidad de excepciones es la esperada?
- **Christoffersen:** ¿las excepciones llegan agrupadas? (un buen modelo no debería fallar varios días seguidos)
- **Cobertura condicional:** ambas pruebas juntas
- **Semáforo de Basilea** sobre los últimos 250 días (verde ≤ 4, amarillo 5 a 9, rojo ≥ 10)

## Cómo correrlo

```bash
python var_backtesting.py          # precios reales con yfinance
python var_backtesting.py --demo   # retornos simulados GARCH(1,1) con colas t
```

Salida: `resultados/backtesting.csv` y `resultados/var_excepciones.png`.

## Lectura típica de resultados

En la corrida de prueba con datos simulados, el VaR normal y el EWMA fallan más de lo esperado (subestiman las colas), mientras que el histórico y el Monte Carlo t pasan Kupiec pero no siempre la prueba de independencia: un ejemplo de por qué pasar una sola prueba no basta.

## Qué demuestra

Conocimiento de las metodologías de riesgo de mercado que usan bancos y AFP, y de su validación estadística según el marco de Basilea.
