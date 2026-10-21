// Modelo de ejemplo: célula en U de montaje de unidades de control electrónicas.
// Tiempos en segundos. Sirve como plantilla y como caso de prueba.

export function exampleModel() {
  return {
    id: 'ejemplo-celula-ecu',
    name: 'Célula de montaje ECU (ejemplo)',
    description: 'Célula en U con 6 estaciones, 3 operarios compartidos, prensa y banco de pruebas con averías, horno de secado, inspección con retrabajo y 2 referencias con setup.',
    settings: {
      horizonHours: 8,
      warmupHours: 0.5,
      replications: 10,
      seed: 2026,
      layout: 'u',
      spacing: 3.5,
      demandPerHour: 30,
    },
    arrivals: { mode: 'push', batchSize: 10 },
    products: [
      { id: 'ECU-A', name: 'ECU estándar', mix: 0.7, color: '#2a78d6' },
      { id: 'ECU-B', name: 'ECU premium', mix: 0.3, color: '#eb6834', timeFactorsByType: { wiring: 1.3, inspection: 1.2 } },
    ],
    operators: [
      { id: 'OP1', name: 'Ana', performance: { default: 100 }, homeStationId: 'S1' },
      { id: 'OP2', name: 'Bruno', performance: { default: 105, byType: { wiring: 115 } }, homeStationId: 'S3' },
      {
        id: 'OP3',
        name: 'Carla (nueva)',
        performance: { default: 95 },
        consistency: 1.3,
        learning: { rate: 0.85, experienceUnits: 20, standardUnits: 500 },
        homeStationId: 'S6',
      },
    ],
    machines: [
      { id: 'M1', name: 'Prensa de remaches', failures: { enabled: true, mtbf: { type: 'weibull', shape: 1.4, scale: 3 * 3600 }, mttr: { type: 'lognormal', mean: 420, sd: 180 } } },
      { id: 'M2', name: 'Banco de pruebas', failures: { enabled: true, mtbf: { type: 'exponential', mean: 5 * 3600 }, mttr: { type: 'lognormal', mean: 900, sd: 400 } } },
    ],
    operations: [
      { id: 'carga', name: 'Carga de carcasa', type: 'loading', duration: { type: 'triangular', min: 8, mode: 10, max: 16 } },
      { id: 'montaje', name: 'Montaje de placa base', type: 'manual_assembly', duration: { type: 'lognormal', mean: 55, sd: 8 }, quality: { defectProb: 0.01 } },
      { id: 'atornillado', name: 'Atornillado de tapa (6 tornillos)', type: 'screwing', duration: { type: 'lognormal', mean: 35, sd: 4 }, quality: { defectProb: 0.005 } },
      { id: 'remachado', name: 'Remachado automático', type: 'machining', duration: { type: 'normal', mean: 22, sd: 0.8, truncate: { min: 0 } } },
      { id: 'cableado', name: 'Cableado del mazo', type: 'wiring', duration: { type: 'lognormal', mean: 88, sd: 18 }, quality: { defectProb: 0.02 } },
      { id: 'carga-test', name: 'Carga en banco', type: 'loading', duration: { type: 'triangular', min: 6, mode: 8, max: 14 } },
      {
        id: 'test',
        name: 'Test funcional EOL',
        type: 'auto_test',
        duration: { type: 'normal', mean: 45, sd: 1.5, truncate: { min: 0 } },
        quality: { detectionProb: 0.98, falseRejectProb: 0.005, onReject: 'rework', reworkOperationId: 'retrabajo', maxReworks: 2, repairProb: 0.9 },
      },
      { id: 'retrabajo', name: 'Diagnóstico y retrabajo', type: 'rework', duration: { type: 'lognormal', mean: 150, sd: 60 } },
      { id: 'secado', name: 'Curado de barniz', type: 'drying', duration: { type: 'uniform', min: 280, max: 340 } },
      {
        id: 'inspeccion',
        name: 'Inspección visual final',
        type: 'inspection',
        duration: { type: 'gamma', mean: 25, sd: 5 },
        quality: { detectionProb: 0.9, falseRejectProb: 0.01, onReject: 'rework', reworkOperationId: 'retrabajo', maxReworks: 1 },
      },
      { id: 'embalaje', name: 'Embalaje y etiquetado', type: 'packing', duration: { type: 'lognormal', mean: 40, sd: 6 } },
      { id: 'setup', name: 'Cambio de referencia', type: 'setup', duration: { type: 'pert', min: 240, mode: 360, max: 720, lambda: 4 } },
      { id: 'cinta', name: 'Cinta al horno', type: 'transport', duration: { type: 'constant', value: 2 } },
      { id: 'andar', name: 'Desplazamiento', type: 'walking' },
    ],
    stations: [
      { id: 'S1', name: 'Montaje base', operationIds: ['carga', 'montaje'], operatorIds: ['OP1'], bufferCapacity: 3, setup: { operationId: 'setup', trigger: 'changeover' } },
      { id: 'S2', name: 'Atornillado y remachado', operationIds: ['atornillado', 'remachado'], operatorIds: ['OP1', 'OP2'], machineId: 'M1', bufferCapacity: 2 },
      { id: 'S3', name: 'Cableado', operationIds: ['cableado'], operatorIds: ['OP2'], bufferCapacity: 2 },
      { id: 'S4', name: 'Test EOL', operationIds: ['carga-test', 'test'], operatorIds: ['OP2', 'OP3'], machineId: 'M2', bufferCapacity: 2, transportOperationId: 'cinta' },
      { id: 'S5', name: 'Horno de curado', operationIds: ['secado'], workplaces: 6, bufferCapacity: 4 },
      { id: 'S6', name: 'Inspección y embalaje', operationIds: ['inspeccion', 'embalaje'], operatorIds: ['OP3'], bufferCapacity: 3 },
    ],
  };
}
