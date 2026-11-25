# 07 · Finanzas corporativas avanzadas (inspirado en LSE FM350)

**Área:** Banca de Inversión · Private Equity · Finanzas Corporativas

Cuatro modelos sobre los temas que estudié en **FM350 Advanced Corporate Finance** (LSE Summer School, agosto 2026): estructura de capital, private equity, venture capital y fusiones. Los modelos, el código y los supuestos son míos y están adaptados a empresas peruanas. No incluyen material ni casos del curso.

| Script | Pregunta que responde | Conceptos |
|---|---|---|
| [`estructura_capital.py`](estructura_capital.py) | ¿Cuánta deuda debería tomar una empresa sin apalancamiento? | Modigliani-Miller con impuestos, trade-off estático, **APV**, rating sintético por cobertura de intereses, costos esperados de quiebra, beta de Hamada |
| [`lbo.py`](lbo.py) | ¿Qué TIR obtiene un fondo de PE comprando la empresa con deuda? | Fuentes y usos, deuda senior con *cash sweep*, deuda subordinada PIK, TIR y MoM, **puente de creación de valor** (crecimiento, múltiplo, desapalancamiento) |
| [`venture_capital.py`](venture_capital.py) | ¿Qué participación debe pedir un VC en una fintech limeña? | **Método VC**, TIR objetivo, valor pre y post-money, dilución por rondas futuras y pool de opciones (ESOP), *cap table*, contraste con VPN por escenarios |
| [`fusiones.py`](fusiones.py) | ¿Crea valor la adquisición de un competidor y cómo afecta la UPA? | Valor de sinergias (costos vs. ingresos, con tasas distintas), prima de control, **accretion/dilution** según forma de pago, sinergia de equilibrio |

## Cómo correrlos

```bash
python 07-lse-fm350/estructura_capital.py
python 07-lse-fm350/lbo.py
python 07-lse-fm350/venture_capital.py
python 07-lse-fm350/fusiones.py
```

No necesitan conexión a internet. Todos los supuestos están al inicio de cada script y son ilustrativos.

## Resultados principales (supuestos ilustrativos)

- **Estructura de capital:** el APV crece con la deuda hasta S/ 3 250 mm (rating BB), pero mantenerse en grado de inversión (BBB, D/V 58%) sacrifica solo 2.8% de valor. Es el tipo de juicio que el modelo de trade-off no captura por sí solo: flexibilidad financiera y acceso al mercado.
- **LBO:** compra a 8.0x EBITDA con 5.0x de deuda: **TIR 23.4%, MoM 2.86x** a 5 años, explicado sobre todo por crecimiento de EBITDA y desapalancamiento (sin expansión de múltiplo).
- **Venture capital:** para una TIR objetivo de 50%, la Serie A de USD 3 mm requiere 29% hoy (21% a la salida, después de la dilución), con un post-money de USD 10.2 mm.
- **M&A:** las sinergias valen S/ 825 mm frente a una prima de S/ 450 mm (VPN +375). Pagando 100% en acciones la operación diluye la UPA (−1.6%) aunque cree valor: **accretion no es lo mismo que creación de valor**.

## Qué demuestra

Que puedo pasar de la teoría de finanzas corporativas a modelos que responden preguntas de negocio concretas, con la mecánica que se usa en banca de inversión y private equity.
