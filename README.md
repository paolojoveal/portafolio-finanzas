# Portafolio de Finanzas, Macroeconomía y Programación

Proyectos aplicados al mercado peruano, desarrollados en Python, que cubren las áreas de **Banca de Inversión, Finanzas Corporativas, Asset Management, Gestión de Riesgos y Estudios Económicos**. Cada proyecto tiene su propio README con la metodología, cómo correrlo y qué resultados produce.

| # | Proyecto | Área | Técnicas |
|---|---|---|---|
| 01 | [Valorización DCF de una empresa de la BVL](01-valorizacion-dcf) | Banca de Inversión · Finanzas Corporativas | FCFF, WACC con riesgo país, Gordon y múltiplos, sensibilidades, Excel |
| 02 | [Optimización de portafolio](02-optimizacion-portafolio) | Asset Management | Markowitz, paridad de riesgo, Black-Litterman, backtest fuera de muestra |
| 03 | [VaR, Expected Shortfall y backtesting](03-var-backtesting) | Riesgo de Mercado | Histórico, EWMA, Monte Carlo t, Kupiec, Christoffersen, semáforo de Basilea |
| 04 | [Inflación y política monetaria del BCRP](04-inflacion-bcrp) | Estudios Económicos | API del BCRP, regla de Taylor, filtro HP, VAR, impulso-respuesta, pronóstico |
| 05 | [Scorecard de riesgo de crédito](05-riesgo-credito) | Riesgo de Crédito | WoE/IV, regresión logística, Gini, KS, PSI, pérdida esperada |
| 06 | [Tablero macro-financiero del Perú](06-dashboard-macro) | Transversal | Streamlit, Plotly, APIs en vivo, caché |
| 07 | [Finanzas corporativas avanzadas (LSE FM350)](07-lse-fm350) | Banca de Inversión · Private Equity | Estructura de capital óptima, APV, LBO, accretion/dilution, opciones reales |

## Instalación

```bash
git clone https://github.com/paolojoveal/portafolio-finanzas.git
cd portafolio-finanzas
python -m venv .venv && source .venv/bin/activate   # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Los proyectos 02, 03 y 04 aceptan `--demo` para correr con datos simulados sin conexión. Sin esa opción descargan datos reales del BCRP y de Yahoo Finance y los guardan en `data/`.

## Estructura

```
common/data.py            Descarga de series del BCRP y precios de mercado
01-valorizacion-dcf/      Modelo DCF + supuestos.json
02-optimizacion-portafolio/
03-var-backtesting/
04-inflacion-bcrp/
05-riesgo-credito/
06-dashboard-macro/       App de Streamlit
07-lse-fm350/             Proyectos de finanzas corporativas avanzadas
```

## Sobre mí

**Paolo Jove** · Estudiante de 8.º semestre (por iniciar el 9.º) en la **Pontificia Universidad Católica del Perú (PUCP)**. Cursé **FM350 Advanced Corporate Finance** en el **LSE Summer School** (London School of Economics).

Busco prácticas pre-profesionales en Banca de Inversión, Asset Management, Finanzas Corporativas, Estudios Económicos y Gestión de Riesgos en Lima.

[LinkedIn](https://www.linkedin.com/in/paolo-jove-085647127)
