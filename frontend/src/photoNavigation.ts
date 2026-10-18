import { api, query } from './api';

export type PhotoListPosition = { photoId: number; rowOffset: number; scrollY: number; scrollLeft: number };

export function photoListPage(value: string | null): number {
  const page = Number(value);
  return Number.isSafeInteger(page) && page > 0 ? page : 1;
}

export function photoListBackLink(id: number, params: URLSearchParams): string {
  const peer = params.get('operator_chat');
  if (peer && /^[1-9]\d*$/.test(peer) && Number.isSafeInteger(Number(peer))) return '/messages?with=' + peer;
  const filters = new URLSearchParams(params);
  for (const key of ['review', 'spam', 'from_map', 'operator_chat']) filters.delete(key);
  const fromMap = params.get('from_map') === '1';
  const path = fromMap ? '/photo-map' : params.get('review') === '1' ? '/review' : params.get('spam') === '1' ? '/spam' : '/photos';
  if (fromMap) {
    filters.delete('anchor_id');
    filters.delete('page');
  } else if (Number.isSafeInteger(id) && id > 0) {
    filters.set('anchor_id', String(id));
  }
  return path + '?' + filters.toString();
}

export async function nextPhotoId(id: number, params: URLSearchParams): Promise<number | null> {
  const filters = Object.fromEntries(params);
  for (const key of ['review', 'spam', 'from_map', 'all_dates', 'page', 'page_size', 'anchor_id', 'operator_chat']) delete filters[key];

  if (params.get('review') === '1') {
    filters.status = 'NEEDS_REVIEW';
  }

  if (params.get('spam') === '1') filters.status = 'SPAM';
  const next = await api<{id: number | null}>(`/photos/${id}/next?${query(filters)}`);
  return next.id;
}
