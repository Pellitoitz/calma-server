// Cliente de la API y guardado automático.
//
// Cada cambio se guarda solo, sin botón "Guardar":
//   1. se copia al instante en localStorage (no se pierde aunque se cierre la pestaña),
//   2. se envía al servidor tras una pausa breve de escritura,
//   3. si el servidor no responde, se reintenta y se recupera al volver a abrir.

export async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(data?.error || `Error ${res.status}`);
    err.status = res.status;
    err.details = data?.details;
    err.current = data?.current;
    throw err;
  }
  return data;
}

export async function waitJob(jobId, onProgress) {
  for (;;) {
    const j = await api('GET', `/api/jobs/${jobId}`);
    onProgress?.(j.progress || 0);
    if (j.status === 'done') return j.result;
    if (j.status === 'error') {
      const e = new Error(j.error);
      e.details = j.details;
      throw e;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
}

const PENDING_KEY = (id) => `umps:pending:${id}`;

export const local = {
  get(key, fallback = null) {
    try {
      const v = localStorage.getItem(key);
      return v === null ? fallback : JSON.parse(v);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* almacenamiento local no disponible */
    }
  },
  remove(key) {
    try {
      localStorage.removeItem(key);
    } catch {
      /* nada */
    }
  },
};

export class AutoSaver {
  constructor({ onStatus, onSaved, onConflict, delay = 700 }) {
    this.onStatus = onStatus;
    this.onSaved = onSaved;
    this.onConflict = onConflict;
    this.delay = delay;
    this.timer = null;
    this.pending = null;
    this.saving = false;
    this.retryTimer = null;
    window.addEventListener('beforeunload', () => this.flush(true));
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') this.flush(true);
    });
  }

  schedule(model) {
    this.pending = model;
    local.set(PENDING_KEY(model.id), { model, at: Date.now() });
    this.onStatus('pending');
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), this.delay);
  }

  async flush(unloading = false) {
    clearTimeout(this.timer);
    if (!this.pending) return;
    if (this.saving && !unloading) {
      this.timer = setTimeout(() => this.flush(), 200);
      return;
    }
    const model = this.pending;
    this.pending = null;
    const body = JSON.stringify({ model, expectedRevision: model.revision ?? null });
    if (unloading) {
      // keepalive permite terminar la petición aunque se cierre la página
      fetch(`/api/models/${model.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => {});
      return;
    }
    this.saving = true;
    this.onStatus('saving');
    try {
      const res = await fetch(`/api/models/${model.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body });
      const data = await res.json().catch(() => null);
      if (res.status === 409) {
        this.onStatus('conflict');
        this.onConflict?.(model, data?.current);
        return;
      }
      if (!res.ok) throw new Error(data?.error || `Error ${res.status}`);
      // solo se limpia la copia local si no ha habido cambios mientras se guardaba
      if (!this.pending) local.remove(PENDING_KEY(model.id));
      this.onSaved(data);
      this.onStatus(this.pending ? 'pending' : 'saved');
    } catch {
      this.pending = this.pending || model;
      this.onStatus('offline');
      clearTimeout(this.retryTimer);
      this.retryTimer = setTimeout(() => this.flush(), 5000);
    } finally {
      this.saving = false;
    }
  }

  /** Cambios locales que no llegaron al servidor (p. ej. se cerró sin conexión). */
  static recoverPending(id) {
    return local.get(PENDING_KEY(id));
  }

  static discardPending(id) {
    local.remove(PENDING_KEY(id));
  }
}
