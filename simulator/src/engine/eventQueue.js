// Cola de prioridad (montículo binario) ordenada por tiempo y, a igualdad, por orden de inserción.

export class EventQueue {
  constructor() {
    this.heap = [];
    this.seq = 0;
  }

  get size() {
    return this.heap.length;
  }

  push(time, fn) {
    const ev = { time, seq: this.seq++, fn };
    const h = this.heap;
    h.push(ev);
    let i = h.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (less(h[p], h[i])) break;
      [h[p], h[i]] = [h[i], h[p]];
      i = p;
    }
    return ev;
  }

  peek() {
    return this.heap[0];
  }

  pop() {
    const h = this.heap;
    if (!h.length) return undefined;
    const top = h[0];
    const last = h.pop();
    if (h.length) {
      h[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < h.length && less(h[l], h[m])) m = l;
        if (r < h.length && less(h[r], h[m])) m = r;
        if (m === i) break;
        [h[m], h[i]] = [h[i], h[m]];
        i = m;
      }
    }
    return top;
  }
}

function less(a, b) {
  return a.time < b.time || (a.time === b.time && a.seq < b.seq);
}
