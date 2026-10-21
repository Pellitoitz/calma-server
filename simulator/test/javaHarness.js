// Construye un programa Java con stubs mínimos de AnyLogic para compilar y
// ejecutar todo el código que el exportador incrusta en el .alp.
export function buildHarness(java, { steps = 2000 } = {}) {
  const { functions, variables, startup, codeChecks } = java;
  const decl = (v) => `${v[1]} ${v[0]} = ${v[2]};`;
  const fnSrc = ([name, ret, params, body]) => `${ret} ${name}(${params.map(([n, t]) => `${t} ${n}`).join(', ')}) {\n${body}\n}`;
  const checks = codeChecks.map((c, i) => {
    if (c.kind === 'cond') return `boolean chk${i}(Pieza agent) { return ${c.code}; }`;
    if (c.kind === 'delay') return `double chk${i}(Pieza agent) { return ${c.code}; }`;
    if (c.kind === 'choice') return `boolean chk${i}(Pieza agent, Agent unit) { return ${c.code}; }`;
    return `void chk${i}(Pieza agent) { ${c.code} }`;
  });
  return `import java.util.function.DoubleSupplier;
class Agent {}
class Source { void inject(int n) {} }
class Operario extends Agent {
  int idx; Operario(int idx) { this.idx = idx; }
  double fatigaH = 0, ultimoCambio = 0, finTarea = 0, ultimaPausa = -1, tiempoPausa = 0, metros = 0, ocupado = 0, maxFatiga = 1;
  int ubicacion = -1, tareas = 0;
  java.util.HashMap<String, Integer> repeticiones = new java.util.HashMap<String, Integer>();
}
class Pieza extends Agent { int producto = 0; double creada = 0; boolean defectuosa = false, primeraPasada = true; int retrabajos = 0; Operario operario = null; }
public class Main extends Agent {
  java.util.Random rnd = new java.util.Random(7);
  double now = 0;
  double uniform() { return rnd.nextDouble(); }
  double time() { return now; }
  void traceln(Object o) { System.out.println(o); }
  Source llegadas = new Source();
  ${variables.map(decl).join('\n  ')}
  ${functions.map(fnSrc).join('\n  ')}
  ${checks.join('\n  ')}
  void startup() { ${startup.join('\n')} }
  public static void main(String[] args) {
    Main m = new Main();
    m.startup();
    int nOps = m.opConsistencia.length;
    for (int i = 0; i < nOps; i++) m.nuevoOperario();
    double total = 0;
    for (int k = 0; k < ${steps}; k++) {
      m.now = k * 30.0;
      Pieza p = new Pieza();
      m.asignarProducto(p);
      m.cambiarWip(1);
      if (nOps > 0) p.operario = m.listaOperarios.get(k % nOps);
      for (int st = 0; st < m.distancia.length; st++) {
        m.necesitaSetup(p, st);
        total += m.runOps(p, st);
      }
      m.inspeccionOk(p, "x");
      m.registrarSalida(p, k % 50 != 0);
    }
    System.out.println("TOTAL=" + total);
    System.out.println(m.informe());
  }
  double runOps(Pieza p, int st) {
    double t = 0;
${functions.filter(([n]) => n.startsWith('op_')).map(([n]) => `    { double x = ${n}(p, st); if (!(x >= 0) || Double.isInfinite(x)) throw new RuntimeException("${n} devolvió " + x); t += x; }`).join('\n')}
    return t;
  }
}
`;
}
