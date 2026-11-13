import { api, ApiError } from './api';
import type { PhotoSelectionSpec } from './photoSelection';

export type DownloadState = 'queued' | 'streaming' | 'finished';
const LIFETIME = 11 * 60_000;

export async function downloadPhotos(selection: PhotoSelectionSpec, onError: (message: string) => void = () => {},
  onState: (state: DownloadState) => void = () => {}) {
  const {url, status_url: statusUrl} = await api<{url: string; status_url: string}>('/photos/downloads', 'POST', selection);
  // Each transfer gets its own context. Starting another must not cancel it.
  const frame = document.createElement('iframe');
  frame.hidden = true;
  frame.title = 'Скачивание фотографий';
  let stopped = false;
  let poll: number | undefined;
  let lifetime: number | undefined;
  let lastState: DownloadState | undefined;
  function state(next: DownloadState) {
    if (next !== lastState) {lastState = next; onState(next);}
  }
  function stop(error?: string) {
    if (stopped) return;
    stopped = true;
    window.clearTimeout(poll); window.clearTimeout(lifetime);
    frame.remove();
    if (error) onError(error);
  }
  frame.onload = () => {
    try {
      const document = frame.contentDocument;
      const text = document?.querySelector('pre')?.textContent || document?.body?.textContent;
      if (text) {
        const response = JSON.parse(text) as {detail?: string};
        if (response.detail) stop(response.detail);
      }
    } catch { /* Attachment downloads do not expose an HTML document. */ }
  };
  async function check() {
    if (stopped) return;
    try {
      const result = await api<{state: DownloadState | 'failed'}>(statusUrl);
      if (stopped) return;
      if (result.state === 'failed') {stop('Скачивание прервано. Попробуйте ещё раз.'); return;}
      state(result.state);
      if (result.state === 'finished') {stop(); return;}
    } catch (error) {
      if (stopped) return;
      if (error instanceof ApiError && [401, 403, 404, 410].includes(error.status)) {
        stop(error.message); return;
      }
      // Short-lived API contention must not cancel a healthy native transfer.
    }
    if (!stopped) poll = window.setTimeout(() => void check(), 3000);
  }
  state('queued');
  frame.src = url;
  document.body.append(frame);
  poll = window.setTimeout(() => void check(), 3000);
  lifetime = window.setTimeout(() => stop('Время ожидания скачивания истекло.'), LIFETIME);
}
