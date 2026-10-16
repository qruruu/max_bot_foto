/** Notify about a different deployed build, without interrupting the current page. */
export function watchVersion(currentVersion: string, onChange: (available: boolean) => void): () => void {
  let stopped = false;
  let active: AbortController | null = null;
  let timeout: number | undefined;

  async function check() {
    if (stopped || document.hidden || active) return;
    const controller = new AbortController();
    active = controller;
    timeout = window.setTimeout(() => controller.abort(), 10_000);
    try {
      const response = await fetch('/version.json?check=' + Date.now(), {
        cache: 'no-store',
        credentials: 'same-origin',
        headers: {Accept: 'application/json'},
        signal: controller.signal,
      });
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return;
      const data: unknown = await response.json();
      if (typeof data !== 'object' || data === null || !('version' in data)) return;
      if (typeof data.version !== 'string' || !/^[a-zA-Z0-9._-]{1,128}$/.test(data.version)) return;
      if (!stopped && !controller.signal.aborted) onChange(data.version !== currentVersion);
    } catch {
      // A deployment, offline browser or timeout must not break the working page.
    } finally {
      window.clearTimeout(timeout);
      timeout = undefined;
      active = null;
    }
  }

  const checkNow = () => { void check(); };
  const interval = window.setInterval(checkNow, 60_000);
  document.addEventListener('visibilitychange', checkNow);
  window.addEventListener('focus', checkNow);
  window.addEventListener('online', checkNow);
  checkNow();

  return () => {
    stopped = true;
    window.clearInterval(interval);
    window.clearTimeout(timeout);
    active?.abort();
    document.removeEventListener('visibilitychange', checkNow);
    window.removeEventListener('focus', checkNow);
    window.removeEventListener('online', checkNow);
  };
}
