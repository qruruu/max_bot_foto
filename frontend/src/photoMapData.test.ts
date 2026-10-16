import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadMapPhotos, mapPhotoFeature, type MapPhoto } from './photoMapData';
import { api } from './api';
vi.mock('./api', async importOriginal => ({...await importOriginal<typeof import('./api')>(), api: vi.fn()}));
const photo: MapPhoto = {id: 7, latitude: 61.1, longitude: 72.6, photo_date: null, photo_time: null,
  received_at: '2026-10-15T21:00:00Z', chat_name: '<script>bad</script>', status: 'ACCEPTED',
  work_type_name: 'Урны', preview_url: 'https://untrusted.example/picture'};
afterEach(() => vi.resetAllMocks());
describe('photo map', () => {
  it('keeps longitude/latitude order, escapes content and uses authenticated local links', () => {
    const feature = mapPhotoFeature(photo, {chat_id:'123', date_from:'', date_to:''}, 'Asia/Yekaterinburg');
    expect(feature.geometry.coordinates).toEqual([72.6, 61.1]);
    expect(feature.properties.balloonContentBody).not.toContain('<script>');
    expect(feature.properties.balloonContentBody).not.toContain('untrusted.example');
    expect(feature.properties.balloonContentBody).toContain('/api/photos/7/preview');
    expect(feature.properties.balloonContentBody).toContain('from_map=1');
    expect(feature.properties.balloonContentBody).toContain('all_dates=1');
    expect(feature.properties.balloonContentBody).toContain('Дата снимка не определена');
    expect(feature.properties.balloonContentBody).toContain('16.10.2026');
  });
  it('loads every batch with a fixed upper ID and preserves filters', async () => {
    const summary = {total: 3, located: 2, without_coordinates: 1};
    vi.mocked(api).mockResolvedValueOnce({items: [photo], summary, snapshot_id: 9, next_after_id: 7})
      .mockResolvedValueOnce({items: [{...photo,id:9}], summary: null, snapshot_id: 9, next_after_id: null});
    const progress = vi.fn();
    const result = await loadMapPhotos({chat_id:'123'}, new AbortController().signal, progress);
    expect(result.photos.map(p => p.id)).toEqual([7,9]);
    expect(result.summary).toEqual(summary);
    expect(vi.mocked(api).mock.calls[1][0]).toBe('/photos/map?chat_id=123&after_id=7&snapshot_id=9');
    expect(progress).toHaveBeenLastCalledWith(2);
  });
  it('does not apply stale results after filters change', async () => {
    const controller = new AbortController();
    vi.mocked(api).mockImplementationOnce(async () => {controller.abort(); return {items: [photo]};});
    const progress = vi.fn();
    await expect(loadMapPhotos({}, controller.signal, progress)).rejects.toThrow();
    expect(progress).not.toHaveBeenCalled();
  });
  it('rejects a repeated cursor instead of looping forever', async () => {
    vi.mocked(api).mockResolvedValue({items:[photo],summary:{total:2,located:2,without_coordinates:0},snapshot_id:9,next_after_id:7});
    await expect(loadMapPhotos({}, new AbortController().signal, vi.fn())).rejects.toThrow('следующую часть');
    expect(api).toHaveBeenCalledTimes(2);
  });
});
