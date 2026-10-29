// Switching photographs cancels obsolete work; only the latest response can play.
export class TraceLoader {
  constructor(fetcher = fetch) {
    // Browser fetch is a platform method: do not invoke it with this loader
    // as its receiver. Injected test fetchers still use the same call shape.
    this.fetcher = (...args) => fetcher(...args);
    this.revision = 0;
    this.controller = null;
  }

  async load(file) {
    this.controller?.abort();
    const revision = ++this.revision;
    const controller = new AbortController();
    this.controller = controller;
    const timer = setTimeout(() => controller.abort(), 12000);
    try {
      if (typeof file !== 'string' || !/^[\w.-]+\.json$/.test(file)) {
        throw new Error('Invalid example');
      }
      const response = await this.fetcher(`/traces/${file}`, { signal: controller.signal });
      if (!response.ok) throw new Error(`Example unavailable (${response.status})`);
      const trace = await response.json();
      if (revision !== this.revision) return null;
      if (!trace || !Array.isArray(trace.steps) || !trace.final ||
          typeof trace.final !== 'object' || trace.steps.some(step => !step || typeof step !== 'object')) {
        throw new Error('Invalid recorded investigation');
      }
      return trace;
    } catch (error) {
      if (revision !== this.revision) return null;
      throw error;
    } finally {
      clearTimeout(timer);
      if (revision === this.revision) this.controller = null;
    }
  }
}
