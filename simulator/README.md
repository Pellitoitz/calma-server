# Universal Manual Process Simulator

Simulador estocástico de eventos discretos para procesos manuales e industriales
(montaje, atornillado, cableado, inspección, pruebas, máquinas, secados, embalaje,
setups, desplazamientos, transportes y retrabajos), con análisis de incertidumbre
y un generador automático de celdas 3D animadas.

Está en una carpeta propia dentro de `calma-server` y no depende de ese servidor.

```bash
cd simulator
npm install        # solo instala three.js (para el 3D sin internet)
npm start          # http://localhost:3100
npm test           # 35 tests, incluida la validación frente a teoría de colas
```

Variables: `PORT` (3100 por defecto) y `DATA_DIR` (carpeta de datos, `./data` por defecto).

## Guardado

No hay botón «Guardar»: todo lo que se introduce queda guardado.

| Qué | Dónde |
| --- | --- |
| Cada cambio de un campo | Copia inmediata en el navegador + envío al servidor a los 0,7 s |
| Sin conexión | Se queda en el navegador y se reintenta; al volver a abrir el modelo se recupera |
| Versiones anteriores | `data/history/<modelo>/` (botón **Historial** → Restaurar) |
| Dos pestañas a la vez | Control de revisión: avisa en lugar de pisar cambios |
| Plantillas reutilizables | **Biblioteca** de operaciones, operarios y máquinas (`data/library.json`) |
| Resultados | Últimos resultados, traza 3D y análisis de variabilidad por modelo (`data/results/`) |
| Interfaz | Pestaña activa, tarjetas abiertas y velocidad 3D se recuerdan por modelo |

Los modelos también se pueden **exportar/importar** en JSON.

## Arquitectura

```
src/
  stochastic/   rng.js            xoshiro128** con un flujo por fuente (números aleatorios comunes)
                distributions.js  12 distribuciones: muestreo, momentos, CDF, validación, truncado
                fitting.js        ajuste a datos cronometrados (MLE/momentos + Kolmogorov-Smirnov)
                variability.js    catálogo de 15 tipos de operación y composición del tiempo
                special.js        gamma, beta incompleta, erf, t de Student, p-valor KS
  engine/       simulator.js      motor de eventos discretos orientado a procesos (generadores)
  analytics/    kpis.js           KPIs por réplica
                experiment.js     réplicas + IC, análisis de contribución, comparación pareada
                stats.js          resúmenes, IC t, réplicas necesarias, histogramas
  model/        schema.js         valores por defecto, normalización y validación
                examples.js       célula de montaje ECU de ejemplo
  layout/       autoLayout.js     disposición en U / línea / L / manual y matriz de distancias
  storage/      store.js          persistencia JSON atómica, historial, biblioteca, resultados
  worker.js     las simulaciones corren en un hilo aparte (el servidor no se bloquea)
public/         interfaz web (sin framework) y visor 3D (three.js)
server.js       API REST con node:http, sin más dependencias
```

El mismo código de `src/` se usa en el servidor y en el navegador (vista previa de
distribuciones, ajuste de datos y validación instantánea).

## Parte I · Motor de variabilidad

Cada ejecución de una operación se calcula así:

```
t = x_base(consistencia del recurso) · f_producto · f_ritmo · f_aprendizaje · f_fatiga · f_máquina
    + distancia / velocidad                    (desplazamientos y transportes)
    + Σ interrupciones ~ Poisson(λ · t)        (microparadas, consultas, falta de material)
    + Σ averías ~ MTBF/MTTR                    (en tiempo de máquina en marcha)
```

| Fuente | Nivel | Modelo |
| --- | --- | --- |
| Tiempo base | operación | constante, uniforme, triangular, PERT, normal, lognormal, exponencial, gamma, Erlang, Weibull, beta, empírica; truncado opcional |
| Consistencia | operario / máquina | escala la dispersión alrededor de la media |
| Ritmo (actividad) | operario, por tipo u operación | 100 % estándar; 120 % ⇒ ×0,83 |
| Aprendizaje | operario u operación | curva de Wright con experiencia previa y unidades hasta el estándar |
| Fatiga | operario | saturación exponencial con horas trabajadas, recuperación exponencial en descansos y pausas; opcionalmente aumenta defectos |
| Interrupciones | operación | proceso de Poisson por hora de trabajo con duración aleatoria |
| Marcha | operario | velocidad aleatoria × distancia real de la planta |
| Transporte | operación | tiempo fijo + distancia / velocidad aleatoria |
| Averías | máquina | MTBF y MTTR con cualquier distribución (p. ej. Weibull), dependientes del uso |
| Mezcla de producto | producto | factores de tiempo globales, por tipo o por operación |
| Calidad | operación | probabilidad de defecto; inspección con detección imperfecta y falsos rechazos; retrabajo con eficacia limitada o desecho |
| Setups | estación | por cambio de referencia o cada N unidades, con su propia distribución |
| Llegadas | modelo | material siempre disponible o llegadas aleatorias por lotes |

Cada tipo de operación trae valores por defecto razonables y qué fuentes le aplican
(una máquina no se fatiga); todo se puede sobrescribir operación a operación.

**Ajuste desde datos**: se pegan tiempos cronometrados y se ajustan 8 familias,
ordenadas por el estadístico KS con su p-valor, o se usa la distribución empírica.

## Parte II · Indicadores e incertidumbre

Por réplica y agregados con **intervalo de confianza t de Student**:

- Producción, unidades, tiempo de ciclo real frente a takt, cumplimiento de demanda.
- Lead time: media, P50, P90, P95, máximo, dispersión e histograma combinado.
- WIP medio y máximo, cola de pedidos, curva de WIP para comprobar el calentamiento.
- Calidad: First Pass Yield, desecho, retrabajos por unidad, defectos escapados (ppm), falsos rechazos.
- Estaciones: trabajando / setup / avería / esperando recursos / bloqueada / sin material, buffers y CV de las salidas.
- **Cuello de botella** por el método del periodo activo y **probabilidad de ser cuello** entre réplicas.
- Operarios: utilización, valor añadido (Lean), metros andados por hora, tareas por hora, fatiga máxima, reparto por tipo de tarea.
- Máquinas: OEE = disponibilidad × rendimiento × calidad, disponibilidad técnica, averías, MTTR y MTBF observados.
- Operaciones: tiempo especificado frente a observado, CV, P90, interrupciones y factor de pérdida.
- Control de la propia simulación: precisión relativa de cada KPI, **réplicas necesarias** para la precisión objetivo y comprobación de la **ley de Little**.

Análisis adicionales:

- **¿Qué variabilidad cuesta más?**: anula cada fuente (tiempo de cada operación, interrupciones, aprendizaje, fatiga, averías, llegadas) y mide su efecto pareado sobre producción, lead time y WIP, con IC y significación.
- **Comparación de escenarios**: duplica el modelo, cámbialo y compáralo con las mismas semillas (diferencias pareadas, IC y veredicto de mejora/empeora).
- **Riesgo**: probabilidad de cumplir la demanda y percentiles de producción.

El motor se valida en los tests frente a resultados analíticos: M/M/1 (W = 180 s, L = 3),
línea determinista limitada por el cuello de botella y bloqueo con buffer cero.

## Parte III · Generador 3D

La pestaña **Vista 3D** construye la celda a partir del modelo, sin dibujar nada a mano:

- Disposición automática en U, línea o L (o coordenadas manuales); las mismas distancias alimentan los tiempos de marcha.
- Geometría según el tipo de estación: banco de trabajo, máquina, banco de pruebas, horno con sus huecos, mesa de embalaje o puesto de inspección iluminado; rack de buffer con su capacidad; cinta si hay transporte.
- Operarios articulados con su nombre y estado: andan entre puestos, mueven brazos según la tarea (atornillar, cablear, inspeccionar, setup) y se ven semitransparentes en las pausas.
- Piezas del color de su referencia que pasan por buffers, puestos y cintas.
- Balizas de máquina: verde en marcha, ámbar parada, rojo en avería.
- Reproducción sincronizada con el reloj de la simulación (réplica 1, primeras 2 h): play/pausa, ×1 a ×600 y barra de tiempo.

## Exportar a AnyLogic

Botón **Exportar a AnyLogic** (o `GET /api/models/:id/anylogic`): descarga el modelo
como proyecto `.alp` de AnyLogic 8.9 (Process Modeling Library). Ejemplo ya generado:
[`anylogic/Celula_montaje_ECU.alp`](anylogic/Celula_montaje_ECU.alp).

Se abre con **Archivo → Abrir** y se ejecuta con el experimento `Simulation`. Al
terminar, la consola muestra el informe (producción, lead time P50/P90/P95, WIP, FPY,
rechazos, retrabajos, utilización y metros por operario, averías por máquina) y los
mismos valores quedan en los *Outputs* de `Main`.

| Simulador | AnyLogic |
| --- | --- |
| Estación (puestos + buffer) | `Seize` del pool `puestosN` (su cola = buffer) → … → `Queue` salida → `Release` |
| Operación | `[Seize máquina] [Seize operario] Delay [Release operario] [Release máquina]` |
| Operarios compartidos | pool `operarios` (tipo `Operario`) con condición de elección `puedeHacer(...)` |
| Inspección / retrabajo / desecho | `SelectOutput` aceptada/rechazada → retrabajo que vuelve a inspección, o `Sink desecho` |
| Setup | `SelectOutput necesitaSetup(...)` → cadena de setup |
| Transporte | `Delay` con distancia de la planta / velocidad aleatoria |
| Llegadas | `Source` por `inject()` (material siempre disponible) o tiempo entre llegadas por lotes |
| Variabilidad | funciones Java `op_*` (una por operación) con el mismo motor: distribución, consistencia, ritmo, aprendizaje, fatiga, interrupciones, marcha, averías, producto, pausas, calidad |

Para cambiar un tiempo en AnyLogic se edita la primera línea `double base = …` de la
función `op_<operación>`; los parámetros de operarios y máquinas están en los arrays
`op*` y `maq*` de `Main`.

Diferencias con el simulador web: la cola de entrada mínima es 1 (AnyLogic no admite 0),
la regla de asignación es la de AnyLogic (no «el más cercano»), y durante el transporte
de salida se mantiene ocupado el puesto. Los tests comprueban que el XML es válido, que
cada puerto del diagrama está conectado y que todo el código Java compila y se ejecuta
con `javac`; la carga en el propio AnyLogic no se ha podido probar aquí.

## API

| Método | Ruta | Uso |
| --- | --- | --- |
| GET/POST | `/api/models` | listar / crear (`{template:'example'}`, `{model}` o vacío) |
| GET/PUT/DELETE | `/api/models/:id` | leer / guardar (`{model, expectedRevision}`) / borrar |
| POST | `/api/models/:id/duplicate` | duplicar como escenario |
| GET | `/api/models/:id/history` | versiones; `POST .../restore/:rev` para restaurar |
| POST | `/api/models/:id/simulate` | lanza réplicas → `{jobId}` |
| POST | `/api/models/:id/contribution` | análisis de fuentes de variabilidad → `{jobId}` |
| POST | `/api/compare` | `{a, b}` (ids o modelos) → `{jobId}` |
| GET | `/api/jobs/:id` | progreso y resultado |
| GET | `/api/models/:id/results` · `/trace` · `/contribution` | últimos resultados guardados |
| GET | `/api/models/:id/anylogic` | descarga el proyecto AnyLogic (.alp) |
| POST | `/api/fit` | `{samples}` → distribuciones ajustadas |
| GET/PUT | `/api/library` | biblioteca de plantillas |
| POST | `/api/validate` | errores y avisos del modelo |

## Límites actuales

- El flujo es una secuencia de estaciones; los rechazos se retrabajan en el mismo puesto (no hay rutas alternativas por producto ni estaciones de retrabajo separadas).
- Las pausas son comunes a todos los operarios.
- El 3D reproduce una réplica; no es un editor de layout por arrastre.
