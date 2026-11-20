# 04_GUIA_ESTILO_VISUAL — Biblia visual v01 (borrador para aprobación)

Fecha: 2026-11-20 · Responsables: dirección creativa, dirección artística, dirección de animación, fotografía, ingeniería de prompts.
Estado: **PROPUESTA**. Nada de este documento es definitivo hasta que exista una imagen maestra aprobada (`*_MASTER_V01`).

---

## 1. Principios del estilo: "Juguete artesanal 3D" (P-08)

**Definición en una frase:** animación 3D estilizada en la que el mundo parece hecho a mano con fieltro, lana, madera pintada y papel, iluminado por una luz de tarde suave.

| Principio | Qué significa en la práctica |
|---|---|
| **Consistencia > complejidad** | Pocos elementos, siempre iguales. Un plano sencillo que sale bien a la primera vale más que uno espectacular que exige 8 regeneraciones |
| **Formas redondas** | Ninguna arista afilada en personajes ni mobiliario; esquinas siempre biseladas |
| **Legibilidad** | Cada personaje se reconoce por su silueta en negro; la emoción se lee a tamaño de miniatura de móvil |
| **Calma visual** | Fondos con 1 punto de interés; saturación media-alta en personajes y media en fondos |
| **Tactilidad** | Texturas visibles pero finas (fibras de fieltro, veta de madera) que invitan a "tocar" |
| **Originalidad** | No imitar el aspecto distintivo de ningún estudio o serie. No usar nombres de estudios, series o artistas en los prompts |

**Por qué este estilo [HIPÓTESIS]:** (1) se distingue del 3D plástico brillante dominante y del 2D plano; (2) las texturas de fieltro disimulan pequeñas variaciones de superficie que la IA introduce entre planos; (3) es migrable a stop-motion real o 3D tradicional si la normativa sobre IA cambia (Plan B, `01` §4.3).

---

## 2. Paleta principal del mundo

| Nombre | HEX | Uso |
|---|---|---|
| Naranja Nilo | `#F28C38` | Protagonista, acentos cálidos |
| Turquesa Pañuelo | `#2BB3A8` | Pañuelo de Nilo, agua clara, acentos |
| Verde Musgo | `#7FA650` | Vegetación principal, caparazón de Tina |
| Verde Bosque | `#2F6B4F` | Sombras de vegetación, troncos lejanos |
| Crema Miel | `#FFF4E0` | Cielos de día, luces suaves |
| Amarillo Luciérnaga | `#FFD45C` | Momentos mágicos, pistas, mochila de Tina |
| Lila Lúa | `#B9A3D9` | Lúa, flores |
| Coral Suave | `#F47C6B` | Pañuelo de Lúa, flores, tejados |
| Marrón Corteza | `#8A5A3B` | Madera, Bruno |
| Azul Lechuza | `#2C3E6B` | Cielo nocturno |

**Reglas:** máximo 3 colores saturados por plano además de los personajes; nunca negro puro (`#1E2430` como color más oscuro) ni blanco puro (`#FFFBF3` como color más claro).

---

## 3. Personajes: paletas, proporciones y restricciones visuales

> Las fichas completas (25 puntos por personaje, vistas, expresiones, voces) se entregarán en `03_BIBLIA_PERSONAJES` (Fase 2). Aquí se fija lo que el estilo necesita.

### 3.1 Proporciones comunes
- Cabeza grande: relación cabeza/cuerpo ≈ **1 : 1,3** (cabeza casi tan grande como el cuerpo).
- Ojos grandes, separados, con **un único brillo blanco** arriba a la izquierda en todos los personajes (regla de continuidad de luz).
- Manos/patas simplificadas: **4 dedos redondeados** en patas delanteras de Nilo y Lúa; Tina con patas sin dedos marcados; Bruno con alas que hacen de "manos" (3 plumas-dedo).
- **Escala relativa (altura total, Nilo = 1,0):** Tina 0,6 · Lúa 1,0 (1,35 con orejas) · Bruno 1,15.

### 3.2 Tabla de color y rasgos fijos

| Personaje | Cuerpo | Secundario | Ojos | Accesorio permanente | Cambio propuesto |
|---|---|---|---|---|---|
| **Nilo** (zorro) | Naranja Nilo `#F28C38` | Hocico, pecho y punta de cola crema `#FFF4E0`; puntas de orejas y patas marrón chocolate `#5A3A2A` | Marrón oscuro `#3B2A20` | Pañuelo turquesa `#2BB3A8` anudado al cuello, nudo a su **izquierda** | — |
| **Tina** (tortuga) | Piel verde salvia claro `#A9C98A` | Caparazón **verde musgo `#7FA650`** con placas hexagonales en relieve marcadas con borde dorado `#D9B44A` | Avellana `#7A5A2E` | Mochila pequeña amarillo luciérnaga `#FFD45C`, **dos correas**, sobre el caparazón | **P-04:** caparazón turquesa → verde musgo (el turquesa ya es de Nilo) |
| **Lúa** (coneja) | Lila Lúa `#B9A3D9` | Interior de orejas y barriga rosa pálido `#F6D3DF`; cola pompón blanca | Violeta oscuro `#4A3466` | Pañuelo **coral `#F47C6B`** al cuello, nudo a su **derecha** | **P-04:** pañuelo amarillo → coral (el amarillo ya es de Tina) |
| **Bruno** (búho) | Marrón corteza `#8A5A3B` | Disco facial y pecho beige `#E8D3B0` con motas en "V"; penachos cortos | Ámbar `#E3A33B`, iris grande | Gafas redondas **montura gruesa color miel `#C98A3A`, sin reflejos** | **P-05:** sin lentes reflectantes |

### 3.3 Siluetas reconocibles (prueba en negro)
- **Nilo:** triángulo de orejas grandes + cola esponjosa en "S" más grande que la cabeza.
- **Tina:** cúpula baja y ancha + mochila como bulto superior.
- **Lúa:** dos orejas largas verticales (la izquierda ligeramente doblada en la punta — **siempre la izquierda**).
- **Bruno:** óvalo con dos penachos cortos + círculos de las gafas.

### 3.4 Restricciones visuales obligatorias (todas)
1. Número de extremidades fijo: Nilo, Lúa 4 patas + 1 cola; Tina 4 patas + cabeza + cola corta; Bruno 2 alas + 2 patas.
2. Ningún personaje lleva ropa adicional (salvo episodio especial aprobado: p. ej. bufanda de nieve en Ep. 11 → nuevo activo versionado).
3. Accesorios nunca se funden con el cuerpo; siempre visibles completos o claramente tapados.
4. Ojos siempre del mismo color y tamaño; sin pestañas exageradas; sin dientes visibles salvo un pequeño colmillo de Nilo al reír (opcional, decidir en `03`).
5. Nunca dos copias del mismo personaje en un plano.
6. Lado del nudo de los pañuelos fijo (Nilo: su izquierda; Lúa: su derecha) → detecta planos espejados por error.

---

## 4. Escenarios base: paletas y luz (detalle completo en `05_ESCENARIOS`)

Se proponen **4 localizaciones** para la Temporada 1 (máximo exigido). Todas visibles desde el Claro, con el Árbol Grande como referencia de orientación.

| ID | Nombre | Función | Paleta dominante | Luz habitual |
|---|---|---|---|---|
| `LOC_CLARO_V01` | **El Claro de las Casitas** | Hogar, inicio y cierre de episodios | Verde musgo, coral (tejados), crema, madera | Mañana dorada / atardecer |
| `LOC_ARBOL_V01` | **El Árbol Grande** (con la biblioteca de Bruno dentro del tronco) | Saber, preguntas, refugio | Marrón corteza, ámbar, verde bosque | Interior: luz cálida de faroles de luciérnaga; exterior: luz filtrada |
| `LOC_RIO_V01` | **El Río Brillante y el Puente de Madera** | Exploración, retos, agua | Turquesa, verde salvia, gris piedra cálido `#BFB3A3` | Luz de mediodía suave con destellos *lentos* en el agua |
| `LOC_COLINA_V01` | **La Colina de las Flores** | Cielo, arcoíris, estrellas, vistas | Lila, amarillo, coral, cielo crema-azul `#CFE6F0` | Atardecer amplio; noche estrellada |

**Cobertura de la Temporada 1 [ESTIMACIÓN]:** estos 4 escenarios cubren los episodios 1, 2, 3, 4, 5, 6, 8, 9 y 12 (con variaciones de luz/tiempo). Ep. 7 (montaña de los sonidos), 10 (robot) y 11 (nieve) necesitarán **variantes** o un 5º escenario — se decidirá en `06_TEMPORADA_1` para controlar coste.

**Mapa (esquema provisional):**
```
              [COLINA DE LAS FLORES]
                     (norte, alto)
                        |
  [ÁRBOL GRANDE] —— [CLARO DE LAS CASITAS] —— (sendero este, futuro)
   (oeste)              |
                  [RÍO BRILLANTE + PUENTE]
                     (sur, bajo)
```
Regla de continuidad geográfica: desde el Claro, el Árbol Grande siempre se ve a la **izquierda** del encuadre cuando miramos al norte (hacia la Colina).

---

## 5. Materiales y texturas

| Elemento | Material | Detalle de textura | Evitar |
|---|---|---|---|
| Pelaje (Nilo, Lúa) | Fieltro de lana suave, ligeramente aterciopelado | Fibras finas visibles solo en primer plano | Pelo fotorrealista, mechones individuales |
| Plumas (Bruno) | Fieltro con capas recortadas | Bordes de pluma redondeados, superpuestos | Plumas realistas |
| Piel de Tina | Fieltro liso mate | — | Escamas realistas |
| Caparazón de Tina | Madera pintada barnizada mate | Placas con relieve suave y borde dorado | Brillo plástico |
| Telas (pañuelos, mochila) | Algodón tejido | Trama visible en primer plano, costura simple | Satén brillante |
| Gafas de Bruno | Madera clara pulida | Sin cristal reflectante (se ve el ojo directamente) | Lentes con reflejos o distorsión |
| Árboles | Corteza de madera tallada | Vetas suaves | Corteza realista con musgo detallado |
| Hojas | Papel/fieltro recortado | Formas simples redondeadas | Hojas fotorrealistas |
| Agua | Resina translúcida turquesa | Ondas lentas, brillos suaves | Agua fotorrealista, espuma |
| Piedras | Arcilla mate | Redondeadas | Rocas afiladas |
| Casitas | Madera pintada + tejado de tela/teja redondeada | Pintura con leve desgaste | Arquitectura realista |

**Nivel de detalle por distancia:** primer plano → textura visible; plano medio → textura insinuada; fondo → color plano con ligera granulosidad.

---

## 6. Iluminación y sombras

| Parámetro | Norma |
|---|---|
| Luz principal | Sol bajo y cálido (≈ 4 000 K percibidos), desde **arriba a la izquierda** del encuadre por defecto |
| Relleno | Luz de cielo fría y suave desde el lado opuesto; contraste bajo (relación luz/sombra ≈ 2:1) |
| Contraluz | Borde dorado sutil en orejas y cola de los personajes (rim light) |
| Sombras | Suaves, difusas, de color (verde azulado o violeta, nunca grises/negras) |
| Oclusión | Sombra de contacto suave bajo los pies: evita que los personajes "floten" |
| Momentos mágicos | Brillo amarillo luciérnaga, partículas lentas (≤ 10 visibles), sin destellos intermitentes |
| Prohibido | Luz dura, sombras proyectadas negras, contraluz que deje caras oscuras, efectos estroboscópicos |

---

## 7. Profundidad de campo
- Planos generales: todo enfocado, leve neblina atmosférica al fondo.
- Planos medios: fondo ligeramente desenfocado (simula f/4).
- Primeros planos y planos detalle: fondo desenfocado con bokeh redondo suave (simula f/2).
- **Cambios de foco solo uno por plano y lentos (≥ 1,5 s).**

---

## 8. Vegetación
- Árboles con copas redondeadas tipo "nube", troncos ligeramente inclinados y gruesos.
- 4 tipos de flor recurrentes: campanilla de observación (amarilla, colgante), margarita coral, flor-estrella lila, trébol gigante.
- Hierba en mechones agrupados (no hierba fina individual).
- Setas: solo decorativas, color crema con puntos coral; **nunca** se comen en pantalla (seguridad: no fomentar comer setas silvestres).

## 9. Arquitectura
- Casitas pequeñas, redondeadas, de una planta, con puertas circulares, ventanas redondas con marco grueso y chimeneas torcidas.
- Cada personaje tiene su casa con su color de acento: Nilo (turquesa), Tina (amarillo), Lúa (coral), Bruno (vive en el Árbol Grande).
- Interiores: escasos en Temporada 1 (coste); solo la biblioteca de Bruno.

## 10. Objetos
- Escala ligeramente grande respecto a los personajes ("juguete").
- Objetos icónicos versionados: `PROP_LUPA_HOJA_V01`, `PROP_MOCHILA_TINA_V01`, `PROP_CAMPANILLA_V01`, `PROP_FAROL_LUCIERNAGA_V01`, `PROP_LIBRO_BRUNO_V01`.
- **Texto en objetos: prohibido** (libros con dibujos, no letras; carteles con símbolos). Facilita doblaje y evita texto ilegible generado por IA.

---

## 11. Encuadres

| Código | Encuadre | Uso narrativo | Riesgo IA |
|---|---|---|---|
| `GP` | Gran plano general | Establecer lugar (inicio de escena) | Bajo si no hay personajes o son pequeños |
| `PG` | Plano general | Acción con 1–2 personajes de cuerpo entero | Medio |
| `PM` | Plano medio (cintura) | Diálogo | Bajo-medio |
| `PP` | Primer plano | Emoción, reacción | Bajo (1 personaje) |
| `PD` | Plano detalle | Pistas, objetos, patas | Bajo |
| `POV` | Subjetivo de un personaje | Pausa de observación | Bajo |
| `2S` | Plano de dos | Conversación | Medio-alto |

**Reglas:** cámara a la **altura de los ojos de los personajes** (mundo a escala infantil); regla de tercios; mirada con aire en la dirección en que mira el personaje; respetar el eje de 180° en diálogos. **Máximo 2 personajes animados por plano (P-03).** Los grupos de 4 se resuelven con un `GP` casi estático o con montaje de reacciones individuales.

---

## 12. Expresiones faciales (hoja base, 8 expresiones)
Se generarán para cada personaje en `03` como `CHAR_<NOMBRE>_EXPR_<CÓDIGO>_V01`.

| Código | Expresión | Señales clave |
|---|---|---|
| `NEU` | Neutral amable | Boca cerrada en leve sonrisa, cejas relajadas |
| `ALE` | Alegría | Ojos achinados en arco, boca abierta redonda |
| `CUR` | Curiosidad | Una ceja alzada, cabeza inclinada, orejas hacia delante |
| `SOR` | Sorpresa suave | Ojos más abiertos, boca en "o" pequeña, **nunca** pupilas contraídas |
| `PEN` | Pensativo | Mirada arriba-lado, pata/ala en la barbilla |
| `TRI` | Tristeza leve | Cejas hacia arriba en el centro, orejas caídas, sin lágrimas abundantes |
| `PRE` | Preocupación | Boca ondulada, cuerpo encogido |
| `ORG` | Orgullo/satisfacción | Ojos cerrados sonrientes, pecho hacia fuera |

**Prohibidas:** ira intensa, terror, asco exagerado, expresiones burlonas o humillantes.

## 13. Animación corporal
- **Ritmo:** movimientos lentos-medios, con anticipación y asentamiento claros. Una acción principal por plano.
- **Personalidad del movimiento:** Nilo — enérgico, saltitos, cola que se mueve al hablar. Tina — lenta y deliberada, parpadeo lento. Lúa — rápida, ágil, orejas que reaccionan. Bruno — pausado, ajusta las gafas con un ala, vuelos cortos.
- **Acciones fiables para IA (preferir):** caminar en línea recta, girar la cabeza, señalar, asentir, saltar en el sitio, mover orejas/cola, parpadear, hablar sin gesticular mucho.
- **Acciones arriesgadas (evitar o dividir):** contacto físico entre personajes (abrazos, chocar manos), manipulación fina de objetos, correr y girar a la vez, vuelo complejo, personajes que se cruzan.

## 14. Movimientos de cámara y transiciones
| Movimiento | Uso | Velocidad |
|---|---|---|
| Estático | Diálogo, pausa de observación | — |
| Travelling lateral lento | Seguir a un personaje caminando | Muy lento |
| Acercamiento suave (push-in) | Descubrimiento, emoción | 3–6 s de duración |
| Alejamiento (pull-out) | Cierre de escena, revelar lugar | 4–8 s |
| Paneo vertical | Revelar el Árbol Grande o el cielo | Lento |
| **Prohibido** | Zoom rápido, cámara en mano temblorosa, giros de 360°, *whip-pan* | — |

**Transiciones:** corte directo (por defecto); fundido cruzado suave (cambio de lugar/tiempo, 0,5–1 s); "barrido de hojas" de marca (hojas de fieltro cruzan la pantalla, 1 s) solo entre actos. Nunca fundidos a blanco brillante ni a negro brusco.

---

## 15. Sistema de miniaturas (1280×720, 16:9)

**Plantilla:**
```
┌───────────────────────────────────────────┐
│ [Personaje protagonista del episodio,     │
│  PP o PM, ocupa 40–50 % del ancho,        │
│  emoción CUR / SOR / ALE]                 │
│                    [Objeto del misterio,  │
│                     grande, iluminado     │
│                     en amarillo]          │
│  [Fondo: escenario real del episodio,     │
│   desenfocado, saturación media]          │
│ Texto: máx. 3 palabras, abajo a la izq.   │
│ (evitar zona inferior derecha: duración)  │
└───────────────────────────────────────────┘
```
**Reglas:** escena y objeto deben existir en el episodio (honestidad); contorno blanco suave en el personaje; texto en tipografía de marca sobre fondo Crema Miel; sin flechas, círculos rojos, caras de terror ni lágrimas; legible a 168×94 px (prueba obligatoria); serie reconocible por el logo pequeño arriba a la derecha en todas.
**Versión sin texto** para la pista en inglés y otros idiomas (el texto se añade por idioma).

---

## 16. Prompts de identidad del canal y plantilla maestra

> Los prompts técnicos van en inglés. Sustituir `[...]`. Herramienta de imagen aún por decidir; sintaxis neutra. **Nunca** añadir nombres de series, estudios o artistas.

### 16.0 Bloque de estilo fijo (pegar en todos los prompts)
```
STYLE_BLOCK_V01:
stylized 3D animation still, handcrafted toy aesthetic, characters made of soft wool felt,
painted wood and woven cotton, rounded shapes, no sharp edges, soft warm golden-hour key light
from upper left, gentle cool sky fill, low contrast, soft colored shadows (teal and violet, never black),
subtle golden rim light, clean composition with one focal point, medium-high saturation on characters,
medium saturation on backgrounds, fine visible felt fibers in close-ups, cozy, calm, wholesome,
child-friendly, original character design
```

### 16.0b Bloque negativo fijo (si la herramienta lo admite)
```
NEGATIVE_BLOCK_V01:
photorealistic, realistic fur strands, glossy plastic, sharp teeth, scary, creepy, horror, dark shadows,
pure black, harsh light, extra limbs, extra fingers, missing limbs, fused objects, merged characters,
duplicate character, deformed face, asymmetrical eyes, text, letters, watermark, logo, signature,
lens flare, motion blur, glitch, strobe, clutter, busy background, realistic human, weapons
```

### 16.1 Logotipo (exploración de concepto; el final se vectoriza a mano)
```
Logo concept sketch for a children's animated series, the word "NILO" in big chunky rounded
hand-made letters, warm orange (#F28C38) with dark green (#2F6B4F) outline, the final letter O
shaped like a small magnifying glass whose lens is a green leaf, smaller second line of rounded
letters below, cream background (#FFF4E0), flat vector style, centered, high legibility,
simple shapes, no extra decorations
```
Nota: los generadores de imagen escriben mal el texto. Úsalo solo como inspiración de formas; tipografía y titularidad, a mano.

### 16.2 Avatar
```
Avatar portrait, 1:1, a young fox character named Nilo, three-quarter view of the head and shoulders,
warm orange felt fur (#F28C38), cream muzzle and chest, big dark brown eyes with a single white
highlight upper left, chocolate brown ear tips, one ear slightly tilted, gentle open smile,
turquoise cotton neckerchief (#2BB3A8) knotted on his left side, centered in a cream circle
(#FFF4E0) over a flat turquoise background, readable at very small size,
[STYLE_BLOCK_V01]
```

### 16.3 Banner
```
Wide panoramic illustration, 16:9 extended to 2560x1440, a cozy magical forest clearing at sunset,
small round wooden cottages with coral rounded roofs and round doors, a giant old tree with a
warm-lit round window on the far left, green felt hills, cream and pale blue sky,
on the right side of the central area four friendly animal characters peeking from behind a fallen log:
an orange young fox with turquoise neckerchief holding a leaf magnifying glass, a small turtle with
moss green wooden shell and yellow backpack, a lilac bunny with coral neckerchief and long ears
(left ear tip folded), a brown owl with thick honey-colored round glasses, empty calm space on the
left for a logo, all important content inside the central safe area, nothing important near edges,
[STYLE_BLOCK_V01]
```
Nota: 4 personajes en un mismo plano = alto riesgo. Alternativa recomendada: generar cada personaje por separado sobre el fondo y componer en un editor (Photopea/GIMP/Affinity).

### 16.4 Plantilla de prompt maestro de personaje (se completará en `09_PROMPTS_IMAGEN`)
```
[ASSET_ID] e.g. CHAR_NILO_MASTER_V01
Subject: [fixed character description from 03_BIBLIA_PERSONAJES — copy verbatim, never paraphrase]
Reference images: [approved masters, if any]
View: [front | 3/4 | profile | back], full body, neutral A-pose, standing
Expression: [code from §12]
Background: plain light warm grey (#EDE7DF), no environment
Lighting: [STYLE_BLOCK_V01 lighting]
Framing: centered, full body with margin, camera at character eye level
Aspect ratio: 1:1 (turnarounds) or 16:9 (scenes)
Continuity rules: [§3.4 list]
[STYLE_BLOCK_V01]
Negative: [NEGATIVE_BLOCK_V01]
```

---

## 17. Escenas nocturnas y formato de calma
- Paleta: Azul Lechuza `#2C3E6B` dominante, luces amarillo luciérnaga, lila de luna.
- Luz principal: luna fría suave desde arriba-derecha + faroles cálidos como luz práctica. **Las caras siempre iluminadas** y legibles.
- Nunca oscuridad total; nunca sombras que formen "figuras".
- Estrellas: puntos suaves fijos o titilación **muy lenta** (ciclo ≥ 2 s, sin parpadeo).
- Ritmo: planos más largos (6–12 s), movimientos de cámara más lentos aún.
- Variantes de escenario versionadas: `LOC_CLARO_NOCHE_V01`, `LOC_COLINA_NOCHE_V01`.

## 18. Gestión de versiones y nomenclatura
```
CHAR_<NOMBRE>_MASTER_V01             imagen maestra aprobada (vista 3/4, neutral)
CHAR_<NOMBRE>_TURN_<VISTA>_V01       FRONT | 34 | SIDE | BACK
CHAR_<NOMBRE>_EXPR_<CÓDIGO>_V01      §12
LOC_<NOMBRE>_[NOCHE_]V01             escenario
PROP_<NOMBRE>_V01                    objeto
EP<NN>_SC<NNN>_SH<NNN>_V<NN>         plano (p. ej. EP01_SC001_SH003_V02)
BRAND_<ELEMENTO>_V01                 LOGO | AVATAR | BANNER | THUMB_TEMPLATE
```
- Un activo `MASTER` **no se modifica**: cualquier cambio crea `V02` y se registra en `17_CAMBIOS_Y_VERSIONES.md` con motivo y documentos afectados.
- Guardar junto a cada imagen: prompt exacto, herramienta, versión del modelo, semilla (si existe), fecha y licencia aplicable.

## 19. Seguridad visual (control crítico)
- Sin destellos ni parpadeos (ningún cambio de brillo grande más de 3 veces por segundo — criterio habitual de fotosensibilidad [VALIDAR norma de referencia]).
- Sin patrones de rayas de alto contraste en movimiento.
- Sin cortes de plano más rápidos de 2 s salvo excepción justificada.
- Revisión obligatoria fotograma a fotograma en los momentos mágicos y de transición.
- Cualquier artefacto anatómico visible → plano rechazado (bloqueo `01` §4.2).

---

### Pendiente de aprobación en este documento
P-03 (máx. 2 personajes animados por plano), P-04 (colores Tina/Lúa), P-05 (gafas Bruno), P-08 (estilo juguete artesanal), escalas relativas §3.1, lados de los nudos §3.4, los 4 escenarios §4.
