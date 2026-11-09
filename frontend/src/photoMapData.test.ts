import { afterEach, expect, it, vi } from 'vitest';
import { loadPhotoMap, viewportBounds } from './photoMapData';
import { api } from './api';

vi.mock('./api', async importOriginal => ({...await importOriginal<typeof import('./api')>(), api: vi.fn()}));
afterEach(() => vi.resetAllMocks());

it('loads one page for the current viewport without following its cursor', async () => {
  const page = {items: [{id: 7}], next_after_id: 7};
  vi.mocked(api).mockResolvedValueOnce(page);
  const controller = new AbortController();
  const bounds = viewportBounds([[72.5, 61], [72.7, 61.2]]);
  expect(await loadPhotoMap('/photos/map', 'chat_id=123', bounds, 0, controller.signal)).toEqual(page);
  expect(api).toHaveBeenCalledTimes(1);
  const params = new URLSearchParams(vi.mocked(api).mock.calls[0][0].split('?')[1]);
  expect(Object.fromEntries(params)).toEqual({chat_id: '123', bounds: '72.50000,61.00000,72.70000,61.20000', after_id: '0'});
});

it('ignores the result of an aborted viewport query', async () => {
  const controller = new AbortController();
  vi.mocked(api).mockImplementationOnce(async () => {controller.abort(); return {items: []};});
  await expect(loadPhotoMap('/photos/map', '', '72,61,73,62', 0, controller.signal)).rejects.toThrow();
});

it('wraps a viewport crossing the date line and clamps a whole-world view', () => {
  expect(viewportBounds([[170, -85], [190, 85]])).toBe('170.00000,-85.00000,-170.00000,85.00000');
  expect(viewportBounds([[-181, -91], [181, 91]])).toBe('-180.00000,-90.00000,180.00000,90.00000');
});
