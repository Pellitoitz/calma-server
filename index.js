require('dotenv').config();
const express = require('express');
const cors = require('cors');
const Anthropic = require('@anthropic-ai/sdk');

const app = express();
app.use(cors());
app.use(express.json());

if (!process.env.ANTHROPIC_API_KEY) {
  console.error(
    '\n⚠️  Falta ANTHROPIC_API_KEY. Copia .env.example a .env y añade tu clave.\n'
  );
  process.exit(1);
}

const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

const SYSTEM_PROMPT = `Eres un asistente dentro de una app de diario de ansiedad.
Recibes una entrada de diario escrita por el usuario y debes responder
SIEMPRE en JSON válido, sin texto adicional antes ni después, con esta forma
exacta:

{
  "pattern": "una o dos frases, en español, validando lo que el usuario describe y señalando con delicadeza un posible patrón (sin diagnosticar ni usar etiquetas clínicas)",
  "exercise": "nombre corto del ejercicio recomendado (ej. 'Respiración 4-7-8')",
  "exerciseSteps": ["paso 1", "paso 2", "paso 3", "..."]
}

Reglas:
- Nunca diagnostiques ni afirmes que el usuario tiene una condición concreta.
- Nunca uses lenguaje alarmista ni dramatices lo que cuenta.
- Si el texto sugiere riesgo de autolesión o ideación suicida, en vez del
  ejercicio, incluye en "pattern" una frase breve y cálida animando a
  contactar con una línea de ayuda profesional, y en "exercise" pon
  "Buscar apoyo ahora" con "exerciseSteps" recomendando contactar el 024
  (España) o el recurso de crisis correspondiente.
- El ejercicio debe ser concreto, corto (3-5 pasos) y realizable en menos
  de 2 minutos.`;

const CHAT_SYSTEM_PROMPT = `Eres el asistente conversacional de Calma, una
app de acompañamiento emocional cotidiano. Hablas en español, en tono
cercano, cálido y validante, nunca clínico ni robótico.

Reglas estrictas:
- NUNCA diagnostiques ni sugieras que el usuario tiene una condición
  clínica concreta.
- NUNCA afirmes ser un terapeuta, psicólogo o sustituto de uno.
- Escucha y valida antes de sugerir nada. No todas las respuestas
  necesitan un ejercicio o consejo — a veces solo hace falta escuchar.
- Haz como máximo una pregunta abierta por respuesta, no interrogues.
- Si detectas indicios de riesgo de autolesión, ideación suicida, abuso o
  violencia, interrumpe el tono conversacional normal y, con calma,
  anima explícitamente a contactar con una línea de ayuda profesional
  (en España: 024, línea de atención a la conducta suicida), sin
  sermonear ni alarmar.
- Nunca reafirmes creencias distorsionadas solo por validar en exceso
  (ej. si el usuario asume sin evidencia que alguien le odia, puedes
  validar la emoción sin confirmar la interpretación como hecho).
- Respuestas breves (2-4 frases). Esto es una conversación, no un
  ensayo.
- No inventes datos clínicos, estudios ni estadísticas.`;

app.post('/analyze', async (req, res) => {
  const { text } = req.body;

  if (!text || typeof text !== 'string') {
    return res.status(400).json({ error: 'Falta el texto a analizar' });
  }

  try {
    const message = await anthropic.messages.create({
      model: 'claude-sonnet-4-5',
      max_tokens: 500,
      system: SYSTEM_PROMPT,
      messages: [{ role: 'user', content: text }],
    });

    const rawText = message.content
      .filter((block) => block.type === 'text')
      .map((block) => block.text)
      .join('');

    const cleaned = rawText.replace(/```json|```/g, '').trim();
    const parsed = JSON.parse(cleaned);

    res.json(parsed);
  } catch (err) {
    console.error('Error llamando a la API de Claude:', err.message);
    res.status(500).json({ error: 'No se pudo analizar la entrada' });
  }
});

app.post('/chat', async (req, res) => {
  const { messages } = req.body;

  if (!Array.isArray(messages) || messages.length === 0) {
    return res.status(400).json({ error: 'Falta la conversación a analizar' });
  }

  try {
    const message = await anthropic.messages.create({
      model: 'claude-sonnet-4-5',
      max_tokens: 400,
      system: CHAT_SYSTEM_PROMPT,
      messages: messages.map((m) => ({ role: m.role, content: m.content })),
    });

    const rawText = message.content
      .filter((block) => block.type === 'text')
      .map((block) => block.text)
      .join('');

    res.json({ reply: rawText.trim() });
  } catch (err) {
    console.error('Error llamando a la API de Claude (chat):', err.message);
    res.status(500).json({ error: 'No se pudo generar respuesta' });
  }
});

app.get('/health', (req, res) => res.json({ ok: true }));

const PORT = process.env.PORT || 3001;
app.listen(PORT, '0.0.0.0', () => {
  console.log(`Servidor escuchando en http://0.0.0.0:${PORT}`);
});
