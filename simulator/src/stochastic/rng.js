// Generador pseudoaleatorio reproducible (xoshiro128**) con flujos independientes.
//
// Cada fuente de variabilidad (operación, operario, máquina, llegadas...) usa su
// propio flujo derivado de (semilla, réplica, clave). Así, al comparar escenarios
// se aplican "números aleatorios comunes": cambiar una operación no altera la
// secuencia aleatoria de las demás, lo que reduce mucho la varianza de las
// diferencias entre escenarios.

export function hashString(str) {
  // FNV-1a 32 bits
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

function splitmix32(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x9e3779b9) >>> 0;
    let z = s;
    z = Math.imul(z ^ (z >>> 16), 0x85ebca6b);
    z = Math.imul(z ^ (z >>> 13), 0xc2b2ae35);
    return (z ^ (z >>> 16)) >>> 0;
  };
}

export class RandomStream {
  constructor(seed) {
    const sm = splitmix32(seed);
    this.s = new Uint32Array([sm(), sm(), sm(), sm()]);
    if (!(this.s[0] | this.s[1] | this.s[2] | this.s[3])) this.s[0] = 1;
    this._spare = null;
  }

  nextUint32() {
    const s = this.s;
    const result = Math.imul(rotl(Math.imul(s[1], 5), 7), 9) >>> 0;
    const t = s[1] << 9;
    s[2] ^= s[0];
    s[3] ^= s[1];
    s[1] ^= s[2];
    s[0] ^= s[3];
    s[2] ^= t;
    s[3] = rotl(s[3], 11);
    return result;
  }

  /** Uniforme en [0, 1). */
  random() {
    return this.nextUint32() / 4294967296;
  }

  /** Uniforme en (0, 1): segura para logaritmos. */
  randomOpen() {
    let u;
    do u = this.random();
    while (u === 0);
    return u;
  }

  /** Normal estándar (Box-Muller polar, reutiliza el segundo valor). */
  normal() {
    if (this._spare !== null) {
      const v = this._spare;
      this._spare = null;
      return v;
    }
    let u, v, s;
    do {
      u = this.random() * 2 - 1;
      v = this.random() * 2 - 1;
      s = u * u + v * v;
    } while (s >= 1 || s === 0);
    const m = Math.sqrt((-2 * Math.log(s)) / s);
    this._spare = v * m;
    return u * m;
  }

  bernoulli(p) {
    return this.random() < p;
  }

  /** Número de sucesos de Poisson con media lambda. */
  poisson(lambda) {
    if (lambda <= 0) return 0;
    if (lambda > 50) {
      return Math.max(0, Math.round(lambda + Math.sqrt(lambda) * this.normal()));
    }
    const L = Math.exp(-lambda);
    let k = 0;
    let p = 1;
    do {
      k++;
      p *= this.random();
    } while (p > L);
    return k - 1;
  }

  /** Elige un índice según pesos no negativos. */
  weightedIndex(weights) {
    const total = weights.reduce((a, b) => a + Math.max(0, b), 0);
    if (total <= 0) return 0;
    let r = this.random() * total;
    for (let i = 0; i < weights.length; i++) {
      r -= Math.max(0, weights[i]);
      if (r < 0) return i;
    }
    return weights.length - 1;
  }
}

function rotl(x, k) {
  return ((x << k) | (x >>> (32 - k))) >>> 0;
}

/** Fábrica de flujos: un flujo estable por clave para una réplica dada. */
export class StreamFactory {
  constructor(baseSeed, replication) {
    this.baseSeed = baseSeed >>> 0;
    this.replication = replication;
    this.streams = new Map();
  }

  get(key) {
    let s = this.streams.get(key);
    if (!s) {
      const seed = hashString(`${this.baseSeed}|${this.replication}|${key}`);
      s = new RandomStream(seed);
      this.streams.set(key, s);
    }
    return s;
  }
}
