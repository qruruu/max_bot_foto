import { ApiError } from './api';

export type NewsUnread = {unread: number};

export function watchNewsUnread(load: (signal: AbortSignal) => Promise<NewsUnread>, update: (count: number) => void) {
  let stopped = false, active: AbortController | null = null;
  async function refresh() {
    if (stopped || document.hidden) return;
    active?.abort();
    const controller = new AbortController();
    active = controller;
    const timeout = window.setTimeout(() => controller.abort(), 9_000);
    try {
      const result = await load(controller.signal);
      if (!stopped && !controller.signal.aborted && Number.isSafeInteger(result.unread) && result.unread >= 0) {
        update(result.unread);
      }
    } catch (error) {
      if (!controller.signal.aborted && error instanceof ApiError && [401, 403].includes(error.status)) stop();
    } finally {
      window.clearTimeout(timeout);
      if (active === controller) active = null;
    }
  }
  const check = () => {void refresh();};
  const interval = window.setInterval(check, 10_000);
  for (const event of ['focus', 'online', 'news-changed']) window.addEventListener(event, check);
  document.addEventListener('visibilitychange', check);
  function stop() {
    stopped = true;
    active?.abort();
    window.clearInterval(interval);
    for (const event of ['focus', 'online', 'news-changed']) window.removeEventListener(event, check);
    document.removeEventListener('visibilitychange', check);
  }
  check();
  return {refresh, stop};
}
