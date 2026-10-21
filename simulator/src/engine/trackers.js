// Acumuladores de estadísticas ponderadas en el tiempo, recortadas al periodo
// de observación [calentamiento, horizonte].

export class StateTracker {
  constructor(clock, window, initial = 'idle') {
    this.clock = clock;
    this.window = window;
    this.state = initial;
    this.since = clock.now;
    this.totals = {};
  }

  set(state) {
    if (state === this.state) return;
    this._accumulate();
    this.state = state;
  }

  _accumulate() {
    const now = this.clock.now;
    const from = Math.max(this.since, this.window.start);
    const to = Math.min(now, this.window.end);
    if (to > from) this.totals[this.state] = (this.totals[this.state] || 0) + (to - from);
    this.since = now;
  }

  finalize() {
    this._accumulate();
    return this.totals;
  }
}

export class TimeWeighted {
  constructor(clock, window, initial = 0) {
    this.clock = clock;
    this.window = window;
    this.value = initial;
    this.since = clock.now;
    this.area = 0;
    this.max = initial;
  }

  add(delta) {
    this.set(this.value + delta);
  }

  set(v) {
    const now = this.clock.now;
    const from = Math.max(this.since, this.window.start);
    const to = Math.min(now, this.window.end);
    if (to > from) this.area += this.value * (to - from);
    this.since = now;
    this.value = v;
    if (now >= this.window.start && v > this.max) this.max = v;
  }

  finalize() {
    this.set(this.value);
    const span = this.window.end - this.window.start;
    return { mean: span > 0 ? this.area / span : 0, max: this.max, final: this.value };
  }
}

/** Acumula observaciones (media, varianza y una muestra para cuantiles/histogramas). */
export class Tally {
  constructor(keep = 5000) {
    this.n = 0;
    this.sum = 0;
    this.sumSq = 0;
    this.min = Infinity;
    this.max = -Infinity;
    this.keep = keep;
    this.values = [];
  }

  add(x) {
    this.n++;
    this.sum += x;
    this.sumSq += x * x;
    if (x < this.min) this.min = x;
    if (x > this.max) this.max = x;
    if (this.values.length < this.keep) this.values.push(x);
    else {
      // muestreo de reservorio con un generador interno determinista
      this._r = (Math.imul(this._r || 0x9e3779b9, 1664525) + 1013904223) >>> 0;
      const j = Math.floor((this._r / 4294967296) * this.n);
      if (j < this.keep) this.values[j] = x;
    }
  }

  summary() {
    const mean = this.n ? this.sum / this.n : 0;
    const variance = this.n > 1 ? Math.max(0, (this.sumSq - this.n * mean * mean) / (this.n - 1)) : 0;
    return {
      n: this.n,
      mean,
      sd: Math.sqrt(variance),
      min: this.n ? this.min : 0,
      max: this.n ? this.max : 0,
    };
  }
}
