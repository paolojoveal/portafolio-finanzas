# 04 · Inflación y política monetaria del BCRP

**Área:** Estudios Económicos

Analiza cómo reacciona el BCRP a la inflación y a la actividad, y pronostica la inflación a 12 meses, usando directamente la **API de series estadísticas del BCRP**.

1. **Regla de Taylor con suavizamiento**, estimada por MCO con errores robustos (HAC):
   `i_t = ρ·i_{t-1} + (1-ρ)·[r* + φπ·(π_t − 2%) + φy·brecha_t]`.
   Se reportan los parámetros de largo plazo y se verifica el **principio de Taylor** (φπ > 1).
2. **Brecha del producto** con filtro de Hodrick-Prescott (λ = 14 400, datos mensuales).
3. **Modelo VAR** con PBI, depreciación del sol, inflación y tasa de referencia:
   selección de rezagos por AIC, pruebas ADF, **funciones impulso-respuesta** (choque de política monetaria → inflación) y **pronóstico** con bandas de 90%.
4. Gráfico de la tasa observada contra la tasa sugerida por la regla, con el rango meta de 1% a 3%.

## Cómo correrlo

```bash
python inflacion_bcrp.py          # descarga las series de la API del BCRP
python inflacion_bcrp.py --demo   # datos simulados con dinámica similar a la peruana
```

Los códigos de las series están en [`common/data.py`](../common/data.py). Verifícalos en el [portal de series del BCRP](https://estadisticas.bcrp.gob.pe/estadisticas/series/) antes de la primera corrida.

Salida: `resultados/regla_taylor.png`, `resultados/pronostico_inflacion.png`, `resultados/irf_tasa_inflacion.png` y `resultados/pronostico_var.csv`.

## Qué demuestra

Manejo de datos oficiales, econometría de series de tiempo y la capacidad de conectar los resultados con la lectura de la política monetaria que hace un área de estudios económicos de banco o de AFP.
