import { api, dateLabel, statusNames } from './api';
import { escapeMapLabel } from './yandexMaps';
import { apiUrl } from './workspace';

export type MapPhoto = {
  id: number; latitude: number; longitude: number;
  photo_date: string | null; photo_time: string | null; received_at: string;
  work_type_name: string | null; preview_url: string | null;
  chat_name?: string; district_name?: string | null; status?: string;
};

export type MapPage = {items: MapPhoto[]; next_after_id: number | null};

export function viewportBounds(bounds: number[][] | undefined) {
  if (!bounds) return '';
  const [[left, bottom], [right, top]] = bounds;
  const round = 100_000;
  const longitude = (value: number) => ((value + 180) % 360 + 360) % 360 - 180;
  const west = right - left >= 360 ? -180 : longitude(Math.floor(left * round) / round);
  const east = right - left >= 360 ? 180 : longitude(Math.ceil(right * round) / round);
  const south = Math.max(-90, Math.floor(bottom * round) / round);
  const north = Math.min(90, Math.ceil(top * round) / round);
  return [west, south, east, north].map(value => value.toFixed(5)).join(',');
}

export function mapPreviewUrl(endpoint: string, id: number) {
  return apiUrl(endpoint.replace(/\/map$/, '/' + id + '/preview'));
}

export function previewMarkerProperties(photo: MapPhoto, preview: string, href: string, timezone: string) {
  const escape = escapeMapLabel;
  const label = 'Фото №' + photo.id;
  const captured = photo.photo_date ? dateLabel(photo.photo_date) + ' ' + (photo.photo_time || '') : 'Дата снимка не определена';
  const received = new Date(photo.received_at).toLocaleString('ru-RU', {timeZone: timezone});
  const image = preview ? `<img class="map-photo-preview" src="${escape(preview)}" alt="${label}"/>` : '';
  return {
    photoLabel: label,
    photoPreviewUrl: preview,
    hintContent: escape(label + (photo.chat_name ? ' · ' + photo.chat_name : '')),
    clusterCaption: escape(label + ' · ' + captured),
    balloonContentHeader: label,
    balloonContentBody: `<div class="map-photo-balloon">${image}<strong>${escape(photo.chat_name || '')}</strong><div>${escape(captured)}</div><div>Получено ${escape(received)}</div><div>${escape(photo.work_type_name || 'Вид работы не определён')}</div><div>${escape(photo.status ? statusNames[photo.status] || photo.status : '')}</div><a href="${escape(href)}">Открыть фотографию →</a></div>`,
  };
}

export async function loadPhotoMap(endpoint: string, filters: string, bounds: string, after: number, signal: AbortSignal) {
  const params = new URLSearchParams(filters);
  params.delete('snapshot_id');
  params.set('bounds', bounds);
  params.set('after_id', String(after));
  const page = await api<MapPage>(endpoint + '?' + params, 'GET', undefined, signal);
  signal.throwIfAborted();
  return page;
}
