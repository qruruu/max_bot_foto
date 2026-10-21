import { ApiError } from './api';
import { workspaceStorageKey } from './workspace';

export type NotificationPreferences = {popup: boolean; sound: boolean};
export type ArrivalSnapshot = {photo_ids: number[]};
export const notificationKey = (userId: number) => workspaceStorageKey(`max-photo-notifications:${userId}`);

export function parseNotificationPreferences(raw: string | null): NotificationPreferences {
  try {
    const value = JSON.parse(raw || 'null');
    return {
      popup: typeof value?.popup === 'boolean' ? value.popup : true,
      sound: typeof value?.sound === 'boolean' ? value.sound : true,
    };
  } catch {
    return {popup: true, sound: true};
  }
}

export function readNotificationPreferences(userId: number): NotificationPreferences {
  try { return parseNotificationPreferences(localStorage.getItem(notificationKey(userId))); }
  catch { return parseNotificationPreferences(null); }
}

export function saveNotificationPreferences(userId: number, value: NotificationPreferences) {
  try { localStorage.setItem(notificationKey(userId), JSON.stringify(value)); }
  catch { /* Preferences still work for this open page if storage is unavailable. */ }
}

/** A photo batch should sound once even if several tabs of the same account are open. */
export async function playArrivalSound(userId: number, ids: number[], play: () => boolean): Promise<boolean> {
  const key = `${notificationKey(userId)}:played`;
  function claim() {
    let previous: number[] = [];
    try {
      const value: unknown = JSON.parse(localStorage.getItem(key) || '[]');
      if (Array.isArray(value)) previous = value.filter(id => Number.isSafeInteger(id) && id > 0);
    } catch { /* Sound also works without persistent storage. */ }
    const seen = new Set(previous);
    if (!ids.some(id => !seen.has(id)) || !play()) return false;
    try { localStorage.setItem(key, JSON.stringify([...new Set([...previous, ...ids])].slice(-2_000))); }
    catch { /* Cross-tab deduplication is unavailable in this browser. */ }
    return true;
  }
  try {
    return window.navigator?.locks ? await window.navigator.locks.request(key, claim) : claim();
  } catch { return claim(); }
}

/** Baseline first; retain seen IDs across edits, deletions and reconnects within the arrival window. */
export function watchPhotoArrivals(
  load: (signal: AbortSignal) => Promise<ArrivalSnapshot>,
  onArrivals: (ids: number[]) => void,
): () => void {
  const seen = new Map<number, number>();
  let initialized = false;
  let stopped = false;
  let active: AbortController | null = null;
  let timeout: number | undefined;

  async function check() {
    if (stopped || active) return;
    const controller = new AbortController();
    active = controller;
    const requestTimeout = window.setTimeout(() => controller.abort(), 9_000);
    timeout = requestTimeout;
    try {
      const data = await load(controller.signal);
      if (stopped || controller.signal.aborted || !Array.isArray(data?.photo_ids)
        || !data.photo_ids.every(id => Number.isSafeInteger(id) && id > 0)) return;
      const instant = Date.now();
      const ids = [...new Set(data.photo_ids)];
      const fresh = initialized ? ids.filter(id => !seen.has(id)) : [];
      for (const id of ids) seen.set(id, instant);
      for (const [id, lastSeen] of seen) {
        if (instant - lastSeen > 86_400_000) seen.delete(id);
      }
      initialized = true;
      if (fresh.length) onArrivals(fresh);
    } catch (error) {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) stop();
      // A network failure preserves the baseline. The next check catches up.
    } finally {
      window.clearTimeout(requestTimeout);
      timeout = undefined;
      active = null;
    }
  }

  const checkNow = () => { void check(); };
  const interval = window.setInterval(checkNow, 10_000);
  window.addEventListener('online', checkNow);
  window.addEventListener('focus', checkNow);
  document.addEventListener('visibilitychange', checkNow);

  function stop() {
    stopped = true;
    window.clearInterval(interval);
    window.clearTimeout(timeout);
    active?.abort();
    window.removeEventListener('online', checkNow);
    window.removeEventListener('focus', checkNow);
    document.removeEventListener('visibilitychange', checkNow);
  }
  checkNow();
  return stop;
}
