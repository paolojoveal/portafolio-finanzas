# 06 · Tablero macro-financiero del Perú

**Área:** transversal (Estudios Económicos, Asset Management, Tesorería)

Aplicación web en **Streamlit + Plotly** que reúne en una sola pantalla lo que un analista revisa cada mañana:

- **Indicadores clave:** inflación 12 meses, tasa de referencia, tipo de cambio y PBI, con su variación frente a hace un año.
- **Política monetaria:** inflación, tasa de referencia y tasa real ex post sobre el rango meta del BCRP.
- **Mercado:** desempeño relativo del MSCI Peru, Credicorp, Southern Copper y el cobre, más su volatilidad realizada.
- **Dependencia del cobre:** correlación móvil de 6 meses de los activos peruanos con el precio del cobre.

Los datos se descargan en vivo de la API del BCRP y de Yahoo Finance, con caché de 6 horas.

## Cómo correrlo

```bash
streamlit run 06-dashboard-macro/app.py              # datos reales
streamlit run 06-dashboard-macro/app.py -- --demo    # datos simulados
```

Se puede publicar gratis en [Streamlit Community Cloud](https://streamlit.io/cloud) conectando este repositorio, para compartir el enlace en el CV.

## Qué demuestra

Capacidad de convertir datos en una herramienta que otros usan: integración de APIs, caché, visualización interactiva y criterio para elegir qué indicadores importan.
