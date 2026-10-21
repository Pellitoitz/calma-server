// Hilo de trabajo: ejecuta simulaciones sin bloquear el servidor web.

import { parentPort } from 'node:worker_threads';
import { runExperiment, contributionAnalysis, compareScenarios } from './analytics/experiment.js';

parentPort.on('message', ({ task, args }) => {
  try {
    const onProgress = (p) => parentPort.postMessage({ progress: p });
    let result;
    if (task === 'simulate') result = runExperiment(args.model, { ...args.options, onProgress });
    else if (task === 'contribution') result = contributionAnalysis(args.model, { ...args.options, onProgress });
    else if (task === 'compare') result = compareScenarios(args.a, args.b, args.options);
    else throw new Error(`Tarea desconocida: ${task}`);
    parentPort.postMessage({ result });
  } catch (e) {
    parentPort.postMessage({ error: e.message, details: e.details });
  }
});
