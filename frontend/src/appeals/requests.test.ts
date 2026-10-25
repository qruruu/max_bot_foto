import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppealRequestError, publicRequest } from './requests';

afterEach(() => {vi.unstubAllGlobals(); vi.useRealTimers();});
describe('mobile requests', () => {
  it('distinguishes a confirmed rejection from an uncertain server failure', async () => {
    vi.stubGlobal('window', globalThis);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({detail: 'Ошибка анкеты'}), {status: 422})));
    try {await publicRequest('', {method: 'POST'});} catch (error) {
      expect(error).toBeInstanceOf(AppealRequestError); expect((error as AppealRequestError).uncertain).toBe(false);
    }
    vi.stubGlobal('fetch', vi.fn(async () => new Response('Service unavailable', {status: 503})));
    await expect(publicRequest('', {method: 'POST'})).rejects.toMatchObject({status: 503, uncertain: true});
  });
  it('limits waiting time and preserves an uncertain result for a safe retry', async () => {
    vi.useFakeTimers(); vi.stubGlobal('window', globalThis);
    vi.stubGlobal('fetch', vi.fn((_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    })));
    const result = publicRequest('', {method: 'POST'}, 10_000);
    const check = expect(result).rejects.toMatchObject({status: 0, uncertain: true});
    await vi.advanceTimersByTimeAsync(10_001); await check;
  });
  it('rejects a broken success response instead of losing the draft', async () => {
    vi.stubGlobal('window', globalThis); vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>Proxy error</html>')));
    await expect(publicRequest('', {method: 'POST'})).rejects.toMatchObject({uncertain: true});
  });
});
