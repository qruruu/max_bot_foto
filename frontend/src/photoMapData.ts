import { api, dateLabel, photoLink, query, statusNames } from './api';
import type { Filters } from './types';
import { escapeMapLabel, type MapFeature } from './yandexMaps';

export type MapPhoto = {
  id: number; latitude: number; longitude: number; photo_date: string | null;
  photo_time: string | null; received_at: string; chat_name: string;
  status: string; work_type_name: string | null; preview_url: string | null;
};
export type MapSummary = {total: number; located: number; without_coordinates: number};
type MapBatch = {
  items: MapPhoto[]; summary: MapSummary | null; snapshot_id: number; next_after_id: number | null;
};

export async function loadMapPhotos(filters: Filters, signal: AbortSignal, progress: (count: number) => void) {
  const photos: MapPhoto[] = [];
  let after = 0, snapshot: number | undefined, summary: MapSummary | null = null;
  do {
    const params = {...filters, after_id: String(after), ...(snapshot === undefined ? {} : {snapshot_id: String(snapshot)})};
    const batch = await api<MapBatch>('/photos/map?' + query(params), 'GET', undefined, signal);
    signal.throwIfAborted();
    summary ??= batch.summary;
    snapshot = batch.snapshot_id;
    photos.push(...batch.items);
    progress(photos.length);
    if (batch.next_after_id === null) break;
    if (batch.next_after_id <= after) throw new Error('Не удалось загрузить следующую часть карты. Обновите карту.');
    after = batch.next_after_id;
  } while (!signal.aborted);
  if (!summary) throw new Error('Сервис не вернул данные карты. Обновите страницу.');
  return {photos, summary};
}

export function mapPhotoFeature(photo: MapPhoto, filters: Filters, timezone: string): MapFeature {
  const escape = escapeMapLabel;
  const received = new Date(photo.received_at).toLocaleString('ru-RU', {timeZone: timezone});
  const date = photo.photo_date ? `${dateLabel(photo.photo_date)} ${photo.photo_time || ''}` : 'Дата снимка не определена';
  // Construct local URLs ourselves; never interpolate an OCR string or an arbitrary image URL into HTML.
  const preview = photo.preview_url ? `<img class="map-photo-preview" src="/api/photos/${photo.id}/preview" alt="Фото №${photo.id}" loading="lazy"/>` : '';
  const href = photoLink(photo.id, {...filters, from_map: '1'}, false, filters.status === 'SPAM');
  return {
    type: 'Feature', id: photo.id,
    geometry: {type: 'Point', coordinates: [photo.longitude, photo.latitude]},
    properties: {
      hintContent: escape(`Фото №${photo.id} · ${photo.chat_name}`),
      clusterCaption: escape(`Фото №${photo.id} · ${date}`),
      balloonContentHeader: escape(`Фото №${photo.id}`),
      balloonContentBody: `<div class="map-photo-balloon">${preview}<strong>${escape(photo.chat_name)}</strong><div>${escape(date)}</div><div>Получено ${escape(received)}</div><div>${escape(photo.work_type_name || 'Вид работы не определён')}</div><div>${escape(statusNames[photo.status] || photo.status)}</div><a href="${escape(href)}">Открыть фотографию →</a></div>`,
    },
  };
}
