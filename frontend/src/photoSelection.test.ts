import { afterEach, expect, it, vi } from 'vitest';
import { api } from './api';
import { selectFilteredPhotos } from './photoSelection';

vi.mock('./api', async () => ({...await vi.importActual('./api'), api: vi.fn()}));
afterEach(() => vi.clearAllMocks());

it('keeps at most fifty selected IDs, independently of list pagination', async () => {
  vi.mocked(api).mockResolvedValueOnce({count: 51, snapshot_id: 51, ids: Array.from({length: 51}, (_, index) => index + 1)});
  const signal = new AbortController().signal;
  const result = await selectFilteredPhotos({chat_id: '123', date_from: '2026-11-12', work_type: 'BIN_EMPTYING', page: '3', anchor_id: '99'}, signal);
  expect(result.count).toBe(50);
  expect(result.ids).toEqual(Array.from({length: 50}, (_, index) => index + 1));
  expect(api).toHaveBeenCalledExactlyOnceWith('/photos/selection', 'POST', {
    filters: {chat_id: '123', date_from: '2026-11-12', work_type: 'BIN_EMPTYING'},
  }, signal);
});

it('does not return a selection after cancellation', async () => {
  const controller = new AbortController();
  vi.mocked(api).mockImplementation(async () => {
    controller.abort();
    return {count: 1, snapshot_id: 1, ids: [1]};
  });
  await expect(selectFilteredPhotos({}, controller.signal)).rejects.toMatchObject({name: 'AbortError'});
});
