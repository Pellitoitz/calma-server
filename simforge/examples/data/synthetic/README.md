# SYNTHETIC TEST DATA

Todos los archivos de esta carpeta son **datos sintéticos** generados por `examples/data/make_synthetic_data.py` a partir de distribuciones conocidas y semillas fijas.
**No son medidas de planta** y no deben presentarse como tales.

| Archivo | Caso | Generado con |
|---|---|---|
| SYNTHETIC_A_constant.csv | A. tiempos aproximadamente constantes | N(120, 0.8) s, n=40 |
| SYNTHETIC_B_skewed.csv | B. tiempos sesgados positivos (separador ;) | lognormal media 45 s, sd 15 s, n=150 |
| SYNTHETIC_C_arrivals.csv | C. llegadas exponenciales con marca de tiempo | Exp(media 90 s), n=200 |
| SYNTHETIC_D_missing.csv | D. vacíos, 'n/a', '-', negativo, cero | Gamma(k=9, θ=5) s, n=60 |
| SYNTHETIC_E_outliers.csv | E. outliers (240, 300, 5 s) | N(60, 5) s, n=80 |
| SYNTHETIC_F_decimal_comma.csv | F. CSV europeo: ';' y coma decimal, minutos | Gamma(k=16, θ=0.1) min, n=50 |
| SYNTHETIC_G_multisheet.xlsx | G. XLSX con varias hojas, fórmula, unidades por fila | ver hojas |
| SYNTHETIC_H_operator_product.csv | H. por operario/producto/turno | Gamma(25, 2) s, B ×1.3, Y +20 s |
| tiempos_montaje.xlsx | ejemplo end-to-end (hoja LEEME lo indica) | Gamma(k=16, θ=1.875) s/circuito, n=87 + incidencias |
