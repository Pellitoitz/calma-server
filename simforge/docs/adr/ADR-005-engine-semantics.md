# ADR-005: Semántica del motor
**Decisión:** bloqueo tras servicio; asignación de recursos compartidos al final del instante (compiten todas las peticiones simultáneas); carriers antes que operarios; averías por calendario con reanudación; eventos en t = horizonte cuentan; ventana (warm-up, horizonte]; RNG por (semilla, nodo, propósito).
**Consecuencias:** fijadas por golden models; cualquier cambio sube `ENGINE_VERSION` e invalida la caché.
