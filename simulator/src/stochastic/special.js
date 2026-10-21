// Funciones especiales necesarias para momentos, CDF y ajustes de distribuciones.

const LANCZOS = [
  676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059,
  12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7,
];

export function gammaLn(x) {
  if (x < 0.5) return Math.log(Math.PI / Math.abs(Math.sin(Math.PI * x))) - gammaLn(1 - x);
  x -= 1;
  let a = 0.99999999999980993;
  const t = x + 7.5;
  for (let i = 0; i < 8; i++) a += LANCZOS[i] / (x + i + 1);
  return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
}

export function gammaFn(x) {
  return Math.exp(gammaLn(x));
}

export function erf(x) {
  // Abramowitz-Stegun 7.1.26 mejorada con serie para |x| pequeño
  const sign = x < 0 ? -1 : 1;
  x = Math.abs(x);
  if (x < 0.5) {
    let sum = x;
    let term = x;
    for (let n = 1; n < 30; n++) {
      term *= (-x * x) / n;
      sum += term / (2 * n + 1);
    }
    return (sign * 2 * sum) / Math.sqrt(Math.PI);
  }
  // complementaria por fracción continua (Lentz)
  return sign * (1 - erfc(x));
}

function erfc(x) {
  // Chebyshev (Numerical Recipes erfcc), error < 1.2e-7
  const z = Math.abs(x);
  const t = 1 / (1 + 0.5 * z);
  const r =
    t *
    Math.exp(
      -z * z -
        1.26551223 +
        t *
          (1.00002368 +
            t *
              (0.37409196 +
                t *
                  (0.09678418 +
                    t *
                      (-0.18628806 +
                        t *
                          (0.27886807 +
                            t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))),
    );
  return x >= 0 ? r : 2 - r;
}

export function normalCdf(z) {
  return 0.5 * (1 + erf(z / Math.SQRT2));
}

/** Gamma incompleta inferior regularizada P(a, x). */
export function gammaP(a, x) {
  if (x <= 0) return 0;
  if (x < a + 1) {
    let sum = 1 / a;
    let del = sum;
    let ap = a;
    for (let n = 0; n < 500; n++) {
      ap += 1;
      del *= x / ap;
      sum += del;
      if (Math.abs(del) < Math.abs(sum) * 1e-14) break;
    }
    return sum * Math.exp(-x + a * Math.log(x) - gammaLn(a));
  }
  // fracción continua para Q(a, x)
  let b = x + 1 - a;
  let c = 1 / 1e-300;
  let d = 1 / b;
  let h = d;
  for (let i = 1; i < 500; i++) {
    const an = -i * (i - a);
    b += 2;
    d = an * d + b;
    if (Math.abs(d) < 1e-300) d = 1e-300;
    c = b + an / c;
    if (Math.abs(c) < 1e-300) c = 1e-300;
    d = 1 / d;
    const del = d * c;
    h *= del;
    if (Math.abs(del - 1) < 1e-14) break;
  }
  return 1 - Math.exp(-x + a * Math.log(x) - gammaLn(a)) * h;
}

/** Beta incompleta regularizada I_x(a, b). */
export function betaI(x, a, b) {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const bt = Math.exp(gammaLn(a + b) - gammaLn(a) - gammaLn(b) + a * Math.log(x) + b * Math.log(1 - x));
  if (x < (a + 1) / (a + b + 2)) return (bt * betaCf(x, a, b)) / a;
  return 1 - (bt * betaCf(1 - x, b, a)) / b;
}

function betaCf(x, a, b) {
  const qab = a + b;
  const qap = a + 1;
  const qam = a - 1;
  let c = 1;
  let d = 1 - (qab * x) / qap;
  if (Math.abs(d) < 1e-300) d = 1e-300;
  d = 1 / d;
  let h = d;
  for (let m = 1; m <= 300; m++) {
    const m2 = 2 * m;
    let aa = (m * (b - m) * x) / ((qam + m2) * (a + m2));
    d = 1 + aa * d;
    if (Math.abs(d) < 1e-300) d = 1e-300;
    c = 1 + aa / c;
    if (Math.abs(c) < 1e-300) c = 1e-300;
    d = 1 / d;
    h *= d * c;
    aa = (-(a + m) * (qab + m) * x) / ((a + m2) * (qap + m2));
    d = 1 + aa * d;
    if (Math.abs(d) < 1e-300) d = 1e-300;
    c = 1 + aa / c;
    if (Math.abs(c) < 1e-300) c = 1e-300;
    d = 1 / d;
    const del = d * c;
    h *= del;
    if (Math.abs(del - 1) < 1e-14) break;
  }
  return h;
}

/** Cuantil de la t de Student (bilateral) para el nivel de confianza dado. */
export function studentTQuantile(df, confidence = 0.95) {
  if (df <= 0) return NaN;
  const p = 1 - (1 - confidence) / 2;
  // búsqueda por bisección sobre la CDF de la t
  let lo = 0;
  let hi = 100;
  for (let i = 0; i < 100; i++) {
    const mid = (lo + hi) / 2;
    if (studentTCdf(mid, df) < p) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
}

export function studentTCdf(t, df) {
  const x = df / (df + t * t);
  const tail = 0.5 * betaI(x, df / 2, 0.5);
  return t >= 0 ? 1 - tail : tail;
}

/** p-valor asintótico de Kolmogorov-Smirnov. */
export function ksPValue(d, n) {
  const en = Math.sqrt(n);
  const lambda = (en + 0.12 + 0.11 / en) * d;
  if (lambda < 0.27) return 1;
  let sum = 0;
  for (let j = 1; j <= 100; j++) {
    const term = 2 * (j % 2 ? 1 : -1) * Math.exp(-2 * j * j * lambda * lambda);
    sum += term;
    if (Math.abs(term) < 1e-10) break;
  }
  return Math.min(1, Math.max(0, sum));
}
