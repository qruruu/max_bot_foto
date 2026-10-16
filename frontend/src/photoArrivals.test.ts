import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './api';
import { notificationKey, parseNotificationPreferences, playArrivalSound, readNotificationPreferences, saveNotificationPreferences, watchPhotoArrivals } from './photoArrivals';
import type { ArrivalSnapshot } from './photoArrivals';

let page: EventTarget;
let browser: EventTarget;
let storage: Map<string, string>;
let stop: () => void;
const load = vi.fn<(signal: AbortSignal) => Promise<ArrivalSnapshot>>();
const notify = vi.fn<(ids: number[]) => void>();

beforeEach(() => {
  vi.useFakeTimers();
  page = new EventTarget();
  browser = Object.assign(new EventTarget(), {setInterval, clearInterval, setTimeout, clearTimeout});
  storage = new Map();
  vi.stubGlobal('document', page);
  vi.stubGlobal('window', browser);
  vi.stubGlobal('localStorage', {getItem: (key: string) => storage.get(key) || null, setItem: (key: string, value: string) => storage.set(key, value)});
  load.mockReset().mockResolvedValue({photo_ids: [1, 2]});
  notify.mockReset();
  stop = () => {};
});
afterEach(() => { stop(); vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('new photo notifications', () => {
  it('silently initializes the baseline and notifies once per batch, including late lower IDs', async () => {
    stop = watchPhotoArrivals(load, notify);
    await vi.advanceTimersByTimeAsync(0);
    expect(notify).not.toHaveBeenCalled();
    load.mockResolvedValue({photo_ids: [1, 2, 5]});
    await vi.advanceTimersByTimeAsync(10_000);
    expect(notify).toHaveBeenLastCalledWith([5]);
    load.mockResolvedValue({photo_ids: [1, 2, 3, 4, 5]});
    await vi.advanceTimersByTimeAsync(10_000);
    expect(notify).toHaveBeenLastCalledWith([3, 4]);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(notify).toHaveBeenCalledTimes(2);
  });

  it('groups all 500 new photos into one notification', async () => {
    stop = watchPhotoArrivals(load, notify);
    await vi.advanceTimersByTimeAsync(0);
    const batch = Array.from({length: 500}, (_, i) => i + 3);
    load.mockResolvedValue({photo_ids: [1, 2, ...batch]});
    await vi.advanceTimersByTimeAsync(10_000);
    expect(notify).toHaveBeenCalledExactlyOnceWith(batch);
  });

  it('does not repeat photos that were temporarily hidden, edited or restored', async () => {
    stop = watchPhotoArrivals(load, notify);
    await vi.advanceTimersByTimeAsync(0);
    load.mockResolvedValue({photo_ids: []});
    await vi.advanceTimersByTimeAsync(10_000);
    load.mockResolvedValue({photo_ids: [1, 2]});
    await vi.advanceTimersByTimeAsync(10_000);
    expect(notify).not.toHaveBeenCalled();
  });

  it('keeps the baseline after a failure and catches up on reconnect', async () => {
    stop = watchPhotoArrivals(load, notify);
    await vi.advanceTimersByTimeAsync(0);
    load.mockRejectedValueOnce(new TypeError('Offline'));
    await vi.advanceTimersByTimeAsync(10_000);
    load.mockResolvedValue({photo_ids: [1, 2, 3]});
    browser.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(0);
    expect(notify).toHaveBeenCalledExactlyOnceWith([3]);
  });

  it.each([null, {}, {photo_ids: null}, {photo_ids: [0, -2]}, {photo_ids: ['7']}, {photo_ids: [1.5]}])('ignores malformed responses without losing the initial baseline', async value => {
    load.mockResolvedValueOnce(value as ArrivalSnapshot);
    stop = watchPhotoArrivals(load, notify);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(notify).not.toHaveBeenCalled();
    load.mockResolvedValue({photo_ids: [1, 2, 3, 3]});
    await vi.advanceTimersByTimeAsync(10_000);
    expect(notify).toHaveBeenCalledExactlyOnceWith([3]);
  });

  it.each([401, 403])('stops checking when the user loses access (%i)', async status => {
    load.mockRejectedValue(new ApiError(status, 'No access'));
    stop = watchPhotoArrivals(load, notify);
    await vi.advanceTimersByTimeAsync(60_000);
    browser.dispatchEvent(new Event('focus'));
    expect(load).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('prevents overlapping requests and cleans up on logout or disable', async () => {
    let signal: AbortSignal | undefined;
    load.mockImplementation(s => {
      signal = s;
      return new Promise((_resolve, reject) => s.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))));
    });
    stop = watchPhotoArrivals(load, notify);
    browser.dispatchEvent(new Event('focus'));
    expect(load).toHaveBeenCalledTimes(1);
    stop();
    expect(signal?.aborted).toBe(true);
    page.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(load).toHaveBeenCalledTimes(1);
    expect(notify).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('times out a hung request and retries', async () => {
    load.mockImplementationOnce(s => new Promise((_resolve, reject) => s.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))));
    stop = watchPhotoArrivals(load, notify);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(load).toHaveBeenCalledTimes(2);
    expect(notify).not.toHaveBeenCalled();
  });
});

describe('personal notification preferences and sound', () => {
  it('stores independent popup and sound preferences separately per user', () => {
    saveNotificationPreferences(1, {popup: false, sound: true});
    saveNotificationPreferences(2, {popup: true, sound: false});
    expect(notificationKey(1)).not.toBe(notificationKey(2));
    expect(readNotificationPreferences(1)).toEqual({popup: false, sound: true});
    expect(readNotificationPreferences(2)).toEqual({popup: true, sound: false});
  });

  it.each([null, '{', 'null', '[]', '{"popup":"no","sound":123}'])('uses defaults for missing or damaged settings', value => {
    expect(parseNotificationPreferences(value)).toEqual({popup: true, sound: true});
  });

  it('keeps working when local storage is unavailable', async () => {
    vi.stubGlobal('localStorage', {getItem: () => { throw new Error('Blocked'); }, setItem: () => { throw new Error('Blocked'); }});
    expect(readNotificationPreferences(1)).toEqual({popup: true, sound: true});
    expect(() => saveNotificationPreferences(1, {popup: false, sound: false})).not.toThrow();
    expect(await playArrivalSound(1, [3], () => true)).toBe(true);
  });

  it('sounds once for multiple tabs of one user and does not consume a blocked signal', async () => {
    const play = vi.fn(() => true);
    expect(await playArrivalSound(1, [3, 4], play)).toBe(true);
    expect(await playArrivalSound(1, [3, 4], play)).toBe(false);
    expect(play).toHaveBeenCalledTimes(1);
    expect(await playArrivalSound(1, [5], () => false)).toBe(false);
    expect(await playArrivalSound(1, [5], play)).toBe(true);
    expect(await playArrivalSound(2, [3, 4], play)).toBe(true);
  });

  it('uses a browser lock to coordinate sound across tabs', async () => {
    const request = vi.fn(async (_key: string, callback: () => boolean) => callback());
    Object.assign(browser, {navigator: {locks: {request}}});
    expect(await playArrivalSound(1, [3], () => true)).toBe(true);
    expect(request).toHaveBeenCalledWith(`${notificationKey(1)}:played`, expect.any(Function));
  });

  it('still plays when the browser denies access to Web Locks', async () => {
    Object.assign(browser, {navigator: {locks: {request: vi.fn().mockRejectedValue(new Error('Blocked'))}}});
    expect(await playArrivalSound(1, [3], () => true)).toBe(true);
    expect(await playArrivalSound(1, [3], () => true)).toBe(false);
  });
});
