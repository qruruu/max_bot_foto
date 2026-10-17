import { api, query } from './api';
import type { PhotoPage } from './types';

export async function nextPhotoId(id: number, params: URLSearchParams): Promise<number | null> {
  const filters = Object.fromEntries(params);
  for (const key of ['review', 'spam', 'from_map', 'all_dates', 'page', 'page_size']) delete filters[key];

  if (params.get('review') === '1') {
    filters.status = 'NEEDS_REVIEW';
    const page = await api<PhotoPage>('/photos?' + query({...filters, page_size: '2'}));
    return page.items.find(photo => photo.id !== id)?.id ?? null;
  }

  if (params.get('spam') === '1') filters.status = 'SPAM';
  const next = await api<{id: number | null}>(`/photos/${id}/next?${query(filters)}`);
  return next.id;
}
