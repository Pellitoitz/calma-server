// Código Java que se incrusta en el modelo AnyLogic: generadores de variables
// aleatorias (solo dependen de uniform() de AnyLogic, así el modelo usa la semilla
// del experimento) y el motor de variabilidad equivalente al del simulador web.

/** [nombre, tipoRetorno, [[param, tipo]...], cuerpo] */
export const HELPER_FUNCTIONS = [
  ['u01', 'double', [], `double x;
do { x = uniform(); } while (x <= 0 || x >= 1);
return x;`],
  ['nStd', 'double', [], `return Math.sqrt(-2 * Math.log(u01())) * Math.cos(2 * Math.PI * u01());`],
  ['gammaStd', 'double', [['k', 'double']], `if (k < 1) return gammaStd(k + 1) * Math.pow(u01(), 1 / k);
double d = k - 1.0 / 3, c = 1 / Math.sqrt(9 * d);
while (true) {
	double x, v;
	do { x = nStd(); v = 1 + c * x; } while (v <= 0);
	v = v * v * v;
	double u = u01();
	if (u < 1 - 0.0331 * x * x * x * x) return d * v;
	if (Math.log(u) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v;
}`],
  ['dUniforme', 'double', [['a', 'double'], ['b', 'double']], `return a + (b - a) * uniform();`],
  ['dTriangular', 'double', [['a', 'double'], ['moda', 'double'], ['b', 'double']], `double u = uniform();
double fc = (moda - a) / (b - a);
return u < fc ? a + Math.sqrt(u * (b - a) * (moda - a)) : b - Math.sqrt((1 - u) * (b - a) * (b - moda));`],
  ['dPert', 'double', [['a', 'double'], ['moda', 'double'], ['b', 'double'], ['lambda', 'double']], `double r = b - a;
double x = gammaStd(1 + lambda * (moda - a) / r), y = gammaStd(1 + lambda * (b - moda) / r);
return a + r * x / (x + y);`],
  ['dNormal', 'double', [['media', 'double'], ['sd', 'double']], `return media + sd * nStd();`],
  ['dLognormal', 'double', [['media', 'double'], ['sd', 'double']], `if (sd <= 0) return media;
double s2 = Math.log(1 + sd * sd / (media * media));
return Math.exp(Math.log(media) - s2 / 2 + Math.sqrt(s2) * nStd());`],
  ['dExponencial', 'double', [['media', 'double']], `return -media * Math.log(u01());`],
  ['dGamma', 'double', [['media', 'double'], ['sd', 'double']], `if (sd <= 0) return media;
double k = (media / sd) * (media / sd);
return gammaStd(k) * media / k;`],
  ['dErlang', 'double', [['media', 'double'], ['k', 'int']], `double p = 1;
for (int i = 0; i < k; i++) p *= u01();
return -media / k * Math.log(p);`],
  ['dWeibull', 'double', [['forma', 'double'], ['escala', 'double'], ['loc', 'double']], `return loc + escala * Math.pow(-Math.log(u01()), 1 / forma);`],
  ['dBeta', 'double', [['alfa', 'double'], ['beta', 'double'], ['min', 'double'], ['max', 'double']], `double x = gammaStd(alfa), y = gammaStd(beta);
return min + (max - min) * x / (x + y);`],
  ['dEmpirica', 'double', [['valores', 'double[]']], `return valores[(int) (uniform() * valores.length)];`],
  ['dTruncar', 'double', [['f', 'DoubleSupplier'], ['lo', 'double'], ['hi', 'double']], `for (int i = 0; i < 200; i++) {
	double x = f.getAsDouble();
	if (x >= lo && x <= hi) return x;
}
return Math.min(hi, Math.max(lo, f.getAsDouble()));`],
  ['dPoisson', 'int', [['lambda', 'double']], `if (lambda <= 0) return 0;
if (lambda > 50) return Math.max(0, (int) Math.round(lambda + Math.sqrt(lambda) * nStd()));
double L = Math.exp(-lambda), p = 1;
int k = 0;
do { k++; p *= uniform(); } while (p > L);
return k - 1;`],
  ['nuevoOperario', 'Operario', [], `Operario o = new Operario(contadorOperarios++);
listaOperarios.add(o);
return o;`],
  ['enObservacion', 'boolean', [], `return time() >= calentamientoH * 3600;`],
  ['recuperar', 'void', [['o', 'Operario']], `double ociosoH = (time() - o.ultimoCambio) / 3600;
if (ociosoH > 0) {
	o.fatigaH *= Math.exp(-ociosoH / opRecuperacionH[o.idx]);
	o.ultimoCambio = time();
}`],
  ['fatiga', 'double', [['o', 'Operario']], `double tau = opFatigaTauH[o.idx] > 0 ? opFatigaTauH[o.idx] : 3;
double f = 1 + opFatigaMax[o.idx] * (1 - Math.exp(-o.fatigaH / tau));
if (f > o.maxFatiga) o.maxFatiga = f;
return f;`],
  ['aprendizaje', 'double', [['o', 'Operario'], ['opId', 'String'], ['tasa', 'double'], ['experiencia', 'double'], ['estandar', 'double'], ['meseta', 'double']], `if (tasa >= 1 || tasa <= 0) return 1;
int reps = o.repeticiones.getOrDefault(opId, 0);
double b = Math.log(tasa) / Math.log(2);
double nEff = Math.max(1, experiencia + reps + 1);
return Math.max(meseta, Math.pow(nEff / Math.max(1, estandar), b));`],
  ['interrupciones', 'double', [['porHora', 'double'], ['trabajo', 'double'], ['duracion', 'DoubleSupplier']], `if (porHora <= 0) return 0;
int n = dPoisson(porHora * trabajo / 3600);
double t = 0;
for (int i = 0; i < n; i++) t += Math.max(0, duracion.getAsDouble());
return t;`],
  ['caminar', 'double', [['o', 'Operario'], ['st', 'int']], `if (o.ubicacion < 0) o.ubicacion = opCasa[o.idx];
double d = distancia[o.ubicacion][st];
o.ubicacion = st;
if (d < 0.05) return 0;
double v = Math.max(0.05, velocidadMarcha(o.idx));
if (enObservacion()) o.metros += d;
return d / v * fatiga(o);`],
  ['pausaPendiente', 'double', [['o', 'Operario']], `// Pausas del turno: si el operario estaba ocupado al empezar la pausa, la hace
// al terminar su tarea (como en el simulador web).
double espera = 0;
double ahora = time();
for (double inicioTurno = 0; inicioTurno <= ahora; inicioTurno += turnoH * 3600) {
	for (int b = 0; b < pausaInicioH.length; b++) {
		double ini = inicioTurno + pausaInicioH[b] * 3600;
		if (ini <= o.ultimaPausa || ini > ahora) continue;
		double comienzo = Math.max(ini, o.finTarea);
		double fin = comienzo + pausaMin[b] * 60;
		espera = Math.max(espera, fin - ahora);
		o.ultimaPausa = ini;
		if (enObservacion()) o.tiempoPausa += pausaMin[b] * 60;
	}
}
return Math.max(0, espera);`],
  ['averias', 'double', [['m', 'int'], ['trabajo', 'double']], `// Averías según tiempo de marcha (MTBF) y reparación (MTTR)
if (m < 0 || !maqAverias[m]) return 0;
double extra = 0, resto = trabajo;
while (resto > maqUptime[m]) {
	resto -= maqUptime[m];
	double rep = Math.max(1, mttr(m));
	extra += rep;
	if (enObservacion()) { maqFallos[m]++; maqTiempoCaido[m] += rep; }
	maqUptime[m] = Math.max(1, mtbf(m));
}
maqUptime[m] -= resto;
return extra;`],
  ['registrarTrabajo', 'void', [['o', 'Operario'], ['opId', 'String'], ['total', 'double'], ['espera', 'double']], `o.repeticiones.merge(opId, 1, Integer::sum);
o.fatigaH += (total - espera) / 3600;
o.finTarea = time() + total;
o.ultimoCambio = o.finTarea;
if (enObservacion()) { o.ocupado += total - espera; o.tareas++; }`],
  ['cambiarWip', 'void', [['delta', 'int']], `double desde = Math.max(wipT, calentamientoH * 3600);
if (time() > desde) wipArea += wip * (time() - desde);
wipT = time();
wip += delta;`],
  ['asignarProducto', 'void', [['p', 'Pieza']], `if (loteRestante <= 0) {
	loteProducto = elegirProducto();
	loteRestante = tamanoLote;
}
loteRestante--;
p.producto = loteProducto;
p.creada = time();
if (enObservacion()) creadas++;`],
  ['necesitaSetup', 'boolean', [['p', 'Pieza'], ['st', 'int']], `boolean necesita = false;
if (setupModo[st] == 1) necesita = ultimoProducto[st] >= 0 && ultimoProducto[st] != p.producto;
else if (setupModo[st] == 2) necesita = setupCadaN[st] > 0 && desdeSetup[st] >= setupCadaN[st];
if (necesita) { desdeSetup[st] = 0; if (enObservacion()) setups++; }
ultimoProducto[st] = p.producto;
desdeSetup[st]++;
return necesita;`],
  ['trasOperacion', 'void', [['p', 'Pieza'], ['opId', 'String']], `double prob = probDefecto(opId);
if (prob <= 0) return;
if (p.operario != null && opSensCalidad[p.operario.idx] > 0) prob *= 1 + opSensCalidad[p.operario.idx] * (fatiga(p.operario) - 1);
if (uniform() < Math.min(1, prob)) {
	p.defectuosa = true;
	if (enObservacion()) defectosCreados++;
}`],
  ['inspeccionOk', 'boolean', [['p', 'Pieza'], ['opId', 'String']], `boolean ok;
if (p.defectuosa) ok = uniform() >= probDeteccion(opId);
else {
	ok = uniform() >= probFalsoRechazo(opId);
	if (!ok && enObservacion()) falsosRechazos++;
}
if (!ok) { p.primeraPasada = false; if (enObservacion()) rechazos++; }
return ok;`],
  ['puedeRetrabajar', 'boolean', [['p', 'Pieza'], ['opId', 'String']], `if (!retrabajaSiRechaza(opId) || p.retrabajos >= maxRetrabajos(opId)) return false;
p.retrabajos++;
if (enObservacion()) retrabajos++;
return true;`],
  ['reparar', 'void', [['p', 'Pieza'], ['opId', 'String']], `if (p.defectuosa && uniform() < eficaciaRetrabajo(opId)) p.defectuosa = false;`],
  ['registrarSalida', 'void', [['p', 'Pieza'], ['terminada', 'boolean']], `cambiarWip(-1);
if (!enObservacion()) return;
if (terminada) {
	terminadas++;
	leadTimes.add(time() - p.creada);
	if (p.primeraPasada) primeraPasada++;
	if (p.defectuosa) escapados++;
} else desechadas++;`],
  ['percentil', 'double', [['q', 'double']], `if (leadTimes.isEmpty()) return 0;
java.util.ArrayList<Double> s = new java.util.ArrayList<Double>(leadTimes);
java.util.Collections.sort(s);
double pos = (s.size() - 1) * q;
int lo = (int) Math.floor(pos), hi = (int) Math.ceil(pos);
return s.get(lo) + (s.get(hi) - s.get(lo)) * (pos - lo);`],
  ['horasObservadas', 'double', [], `return Math.max(1e-9, (time() - calentamientoH * 3600) / 3600);`],
  ['produccionHora', 'double', [], `return terminadas / horasObservadas();`],
  ['leadTimeMedio', 'double', [], `double s = 0;
for (double x : leadTimes) s += x;
return leadTimes.isEmpty() ? 0 : s / leadTimes.size();`],
  ['wipMedio', 'double', [], `cambiarWip(0);
return wipArea / (horasObservadas() * 3600);`],
  ['fpy', 'double', [], `return terminadas == 0 ? 0 : (double) primeraPasada / terminadas;`],
  ['informe', 'String', [], `StringBuilder sb = new StringBuilder();
double obs = horasObservadas() * 3600;
sb.append("===== RESULTADOS (sin calentamiento de " + calentamientoH + " h) =====\\n");
sb.append(String.format("Producción: %.2f uds/h  (terminadas %d, desechadas %d)%n", produccionHora(), terminadas, desechadas));
sb.append(String.format("Lead time: media %.1f s · P50 %.1f · P90 %.1f · P95 %.1f%n", leadTimeMedio(), percentil(0.5), percentil(0.9), percentil(0.95)));
sb.append(String.format("WIP medio: %.2f uds%n", wipMedio()));
sb.append(String.format("FPY: %.1f %% · rechazos %d (falsos %d) · retrabajos %d · defectos escapados %d · setups %d%n", 100 * fpy(), rechazos, falsosRechazos, retrabajos, escapados, setups));
for (Operario o : listaOperarios) {
	double disp = Math.max(1, obs - o.tiempoPausa);
	sb.append(String.format("Operario %s: utilización %.1f %% · %d tareas · %.0f m andados · fatiga máx +%.1f %%%n", nombreOperario(o.idx), 100 * o.ocupado / disp, o.tareas, o.metros, 100 * (o.maxFatiga - 1)));
}
for (int m = 0; m < maqFallos.length; m++) {
	sb.append(String.format("Máquina %s: %d averías · %.1f min parada%n", nombreMaquina(m), maqFallos[m], maqTiempoCaido[m] / 60));
}
return sb.toString();`],
  ['imprimirInforme', 'double', [], `traceln(informe());
return produccionHora();`],
];
