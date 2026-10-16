import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { watchVersion } from './version';

const fetchMock = vi.fn<typeof fetch>();
const notify = vi.fn<(available: boolean) => void>();
let page: EventTarget & {hidden: boolean};
let browser: EventTarget;
let stop: () => void;
let serverVersion: string;

beforeEach(() => {
  vi.useFakeTimers();
  page = Object.assign(new EventTarget(), {hidden: false});
  browser = Object.assign(new EventTarget(), {
    setInterval, clearInterval, setTimeout, clearTimeout,
  });
  vi.stubGlobal('document', page);
  vi.stubGlobal('window', browser);
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
  notify.mockReset();
  serverVersion = 'build-a';
  fetchMock.mockImplementation(async () => Response.json({version: serverVersion}));
  stop = () => {};
});

afterEach(() => {
  stop();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('deployed version checks', () => {
  it('detects a deployed build and clears the notice if the server rolls back to the open version', async () => {
    stop = watchVersion('build-a', notify);
    await vi.advanceTimersByTimeAsync(0);
    expect(notify).toHaveBeenLastCalledWith(false);
    serverVersion = 'build-b';
    await vi.advanceTimersByTimeAsync(60_000);
    expect(notify).toHaveBeenLastCalledWith(true);
    serverVersion = 'build-a';
    browser.dispatchEvent(new Event('focus'));
    await vi.advanceTimersByTimeAsync(0);
    expect(notify).toHaveBeenLastCalledWith(false);
  });

  it('bypasses browser caches when checking a release', async () => {
    stop = watchVersion('build-a', notify);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/^\/version.json\?check=\d+$/), expect.objectContaining({
      cache: 'no-store', credentials: 'same-origin', signal: expect.any(AbortSignal),
    }));
  });

  it.each([
    () => new Response('Unavailable', {status: 503}),
    () => new Response('<html>Old installation</html>', {headers: {'content-type': 'text/html'}}),
    () => Response.json({}),
    () => Response.json({version: ''}),
    () => Response.json({version: 123}),
    () => Response.json({version: ' '}),
    () => new Response('{', {headers: {'content-type': 'application/json'}}),
  ])('ignores a failed, missing or malformed version file', async response => {
    fetchMock.mockImplementation(async () => response());
    stop = watchVersion('build-a', notify);
    await vi.advanceTimersByTimeAsync(0);
    expect(notify).not.toHaveBeenCalled();
  });

  it('keeps the working state during a network failure and recovers on reconnect', async () => {
    stop = watchVersion('build-a', notify);
    await vi.advanceTimersByTimeAsync(0);
    notify.mockClear();
    fetchMock.mockRejectedValueOnce(new TypeError('Offline'));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(notify).not.toHaveBeenCalled();
    serverVersion = 'build-b';
    browser.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(0);
    expect(notify).toHaveBeenLastCalledWith(true);
  });

  it('pauses in hidden tabs and immediately checks on returning', async () => {
    page.hidden = true;
    stop = watchVersion('build-a', notify);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(fetchMock).not.toHaveBeenCalled();
    page.hidden = false;
    page.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('prevents overlapping checks and cancels requests, timers and listeners when unmounted', async () => {
    let signal: AbortSignal | undefined;
    fetchMock.mockImplementation((_url, options) => {
      signal = options?.signal as AbortSignal;
      return new Promise((_resolve, reject) => signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))));
    });
    stop = watchVersion('build-a', notify);
    browser.dispatchEvent(new Event('focus'));
    browser.dispatchEvent(new Event('online'));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    stop();
    expect(signal?.aborted).toBe(true);
    browser.dispatchEvent(new Event('focus'));
    page.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(120_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(notify).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('recovers after a timed-out request', async () => {
    fetchMock.mockImplementationOnce((_url, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }));
    stop = watchVersion('build-a', notify);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(notify).not.toHaveBeenCalled();
    serverVersion = 'build-b';
    browser.dispatchEvent(new Event('focus'));
    await vi.advanceTimersByTimeAsync(0);
    expect(notify).toHaveBeenLastCalledWith(true);
  });
});
