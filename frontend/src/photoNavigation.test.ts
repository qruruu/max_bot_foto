import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextPhotoId } from './photoNavigation';

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal('document', {cookie: ''});
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

function respond(value: unknown) {
  fetchMock.mockResolvedValue({ok: true, json: async () => value});
}

describe('next photo in the current list', () => {
  it('advances accepted photos with the same filters across table pages', async () => {
    respond({id: 38});
    const params = new URLSearchParams('review=0&spam=0&status=ACCEPTED&district_id=0&chat_id=123&work_type=SWEEPING&operator_id=2&date_from=2026-10-16&date_to=2026-10-17&date_basis=received&page=3&page_size=30');
    expect(await nextPhotoId(42, params)).toBe(38);
    const url = new URL(fetchMock.mock.calls[0][0], 'http://test');
    expect(url.pathname).toBe('/api/photos/42/next');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      status: 'ACCEPTED', district_id: '0', chat_id: '123', work_type: 'SWEEPING',
      operator_id: '2', date_from: '2026-10-16', date_to: '2026-10-17', date_basis: 'received',
    });
    expect(params.get('page')).toBe('3');
  });

  it('returns null at the end and keeps all-dates map navigation in the original URL', async () => {
    respond({id: null});
    const params = new URLSearchParams('from_map=1&all_dates=1&district_id=0');
    expect(await nextPhotoId(42, params)).toBeNull();
    expect(fetchMock.mock.calls[0][0]).toBe('/api/photos/42/next?district_id=0');
    expect(params.toString()).toBe('from_map=1&all_dates=1&district_id=0');
  });

  it('keeps the review queue behavior and skips the current photo', async () => {
    respond({items: [{id: 42}, {id: 38}]});
    expect(await nextPhotoId(42, new URLSearchParams('review=1&status=ACCEPTED&page=3'))).toBe(38);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/photos?status=NEEDS_REVIEW&page_size=2');
    respond({items: [{id: 42}]});
    expect(await nextPhotoId(42, new URLSearchParams('review=1'))).toBeNull();
  });

  it('preserves the separate spam list', async () => {
    respond({id: 38});
    expect(await nextPhotoId(42, new URLSearchParams('spam=1'))).toBe(38);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/photos/42/next?status=SPAM');
  });

  it('surfaces navigation failures before saving can begin', async () => {
    fetchMock.mockResolvedValue({ok: false, status: 403, json: async () => ({detail: 'Нет доступа'})});
    await expect(nextPhotoId(42, new URLSearchParams())).rejects.toThrow('Нет доступа');
  });
});
