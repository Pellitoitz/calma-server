# Integración futura con AnyLogic (investigación; nada implementado)

No se ha inventado ninguna integración. Estrategias posibles, todas **TO VERIFY** contra la documentación
oficial y la licencia (PLE 8.9 tiene restricciones de uso y exportación):

| Estrategia | Idea | Estado |
|---|---|---|
| Plantilla parametrizada | Modelo AnyLogic hecho a mano con bloques genéricos; ISMS → fichero de parámetros (Excel/CSV/DB) que el modelo lee al arrancar | TO VERIFY (factible con la funcionalidad estándar de lectura de ficheros/BD de AnyLogic; confirmar en PLE) |
| Generación de `.alp` | El `.alp` es XML; generar/editar bloques programáticamente | TO VERIFY — formato propietario sin especificación pública conocida; riesgo de licencia y de compatibilidad entre versiones |
| Código Java | Generar clases Java para lógica custom dentro de una plantilla | TO VERIFY |
| AnyLogic Cloud API | Ejecutar experimentos sobre modelos subidos a AnyLogic Cloud vía su API | TO VERIFY (requiere cuenta/licencia Cloud; comprobar disponibilidad con PLE) |

Recomendación: empezar por **plantilla + fichero de parámetros** para el caso de soldadura selectiva y usarlo
como benchmark: mismo ISMS → SimForge vs. AnyLogic → comparar throughput/WIP/utilizaciones por escenario.
