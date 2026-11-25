# 05 · Scorecard de riesgo de crédito y pérdida esperada

**Área:** Gestión de Riesgo de Crédito · Banca

Construye una tarjeta de puntaje para créditos de consumo con la metodología que usan los bancos peruanos para admisión y para provisiones:

1. **WoE e Information Value** para medir el poder predictivo de cada variable (ratio deuda/ingreso, atrasos, número de entidades en la central de riesgos, utilización de tarjeta, edad, ingreso).
2. **Regresión logística** sobre variables transformadas a WoE, que da coeficientes estables e interpretables.
3. **Validación** fuera de muestra: AUC, **Gini**, **KS** y **PSI** (estabilidad de la población).
4. **Escalamiento a puntaje** (600 puntos = odds 50:1, PDO = 20) y tarjeta de puntos por tramo.
5. **Pérdida esperada** `EL = PD × LGD × EAD` por banda de riesgo, la base para provisiones y pricing.

## Cómo correrlo

```bash
python scorecard.py                     # cartera simulada de 20 000 clientes
python scorecard.py --csv cartera.csv   # tu propio dataset con columna 'default'
```

Funciona con datasets públicos como *Give Me Some Credit* o *German Credit* (renombrando la variable objetivo a `default`).

## Resultado con la cartera simulada

| Métrica | Valor |
|---|---|
| AUC | 0.67 |
| Gini | 0.34 |
| KS | 0.26 |
| PSI | 0.003 (estable) |

La PD del modelo queda bien calibrada en las cinco bandas (la tasa de default observada sube de 4% en la banda A a 21% en la E), y la pérdida esperada total es 6.4% de la exposición.

## Qué demuestra

Dominio del ciclo completo de un modelo de riesgo de crédito, desde la ingeniería de variables hasta la métrica de negocio, con las pruebas de validación que pide un área de riesgos o de validación de modelos.
