// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { watchAppealNotifications } from './notifications';
import { ApiError } from '../api';

let stop = () => {};
beforeEach(() => {vi.useFakeTimers(); Object.defineProperty(document, 'hidden', {configurable: true, value: false});});
afterEach(() => {stop(); vi.useRealTimers(); vi.restoreAllMocks();});

it('delivers the existing backlog and new arrivals, retries network errors, and cancels on logout', async () => {
  const load = vi.fn().mockResolvedValueOnce({new_count: 2, latest_id: 10}).mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce({new_count: 3, latest_id: 11}).mockRejectedValueOnce(new ApiError(401, 'Войдите'));
  const update = vi.fn(); stop = watchAppealNotifications(load, update);
  await vi.advanceTimersByTimeAsync(0); expect(update).toHaveBeenLastCalledWith({new_count: 2, latest_id: 10});
  await vi.advanceTimersByTimeAsync(20_000); expect(update).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(20_000); expect(update).toHaveBeenLastCalledWith({new_count: 3, latest_id: 11});
  await vi.advanceTimersByTimeAsync(60_000); expect(load).toHaveBeenCalledTimes(4);
});

it('refreshes after review and returning to the page and ignores malformed responses', async () => {
  const load = vi.fn().mockResolvedValueOnce({new_count: -1, latest_id: 10}).mockResolvedValue({new_count: 0, latest_id: 10});
  const update = vi.fn(); stop = watchAppealNotifications(load, update);
  await vi.advanceTimersByTimeAsync(0); expect(update).not.toHaveBeenCalled();
  window.dispatchEvent(new Event('appeals-changed')); await vi.advanceTimersByTimeAsync(0);
  expect(update).toHaveBeenLastCalledWith({new_count: 0, latest_id: 10});
  stop(); window.dispatchEvent(new Event('focus')); await vi.advanceTimersByTimeAsync(20_000);
  expect(load).toHaveBeenCalledTimes(2);
});
