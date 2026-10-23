import { api, query } from './api';

export type PhotoListPosition = { photoId: number; rowOffset: number; scrollY: number; scrollLeft: number };

export function photoListAnchor(value: string | null, position?: PhotoListPosition): number | undefined {
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : position?.photoId;
}

export function capturePhotoListPosition(id: number): PhotoListPosition {
  return {photoId: id, rowOffset: document.getElementById('photo-row-' + id)?.getBoundingClientRect().top ?? 0,
    scrollY: window.scrollY, scrollLeft: document.querySelector('.photo-panel .table-scroll')?.scrollLeft ?? 0};
}

export function restorePhotoListPosition(anchorId?: number, position?: PhotoListPosition) {
  const row = anchorId === undefined ? null : document.getElementById('photo-row-' + anchorId);
  const table = document.querySelector<HTMLElement>('.photo-panel .table-scroll');
  if (table && position) table.scrollLeft = position.scrollLeft;
  if (row) {
    const bounds = row.getBoundingClientRect();
    const offset = position?.rowOffset ?? Math.max(20, (window.innerHeight - bounds.height) / 2);
    window.scrollTo({top: Math.max(0, window.scrollY + bounds.top - offset), behavior: 'instant'});
    row.querySelector<HTMLButtonElement>('.photo-thumb')?.focus({preventScroll: true});
  } else if (position) window.scrollTo({top: position.scrollY, behavior: 'instant'});
}

export function photoListPage(value: string | null): number {
  const page = Number(value);
  return Number.isSafeInteger(page) && page > 0 ? page : 1;
}

export function photoListBackLink(id: number, params: URLSearchParams): string {
  const day = params.get('from_day');
  if (day && /^\d{4}-\d{2}-\d{2}$/.test(day)) {
    return '/days?' + query({day, view: params.get('day_review') === 'confirmed' ? 'confirmed' : 'pending', work: params.get('work_type') || '', page: params.get('page') || '1', ...(Number.isSafeInteger(id) && id > 0 ? {anchor_id: String(id)} : {})});
  }
  const peer = params.get('operator_chat');
  if (peer && /^[1-9]\d*$/.test(peer) && Number.isSafeInteger(Number(peer))) return '/messages?with=' + peer;
  const filters = new URLSearchParams(params);
  for (const key of ['review', 'spam', 'from_map', 'operator_chat', 'by_number']) filters.delete(key);
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
  for (const key of ['review', 'spam', 'from_map', 'from_day', 'all_dates', 'page', 'page_size', 'anchor_id', 'operator_chat', 'by_number']) delete filters[key];

  if (params.get('review') === '1') {
    filters.status = 'NEEDS_REVIEW';
  }

  if (params.get('spam') === '1') filters.status = 'SPAM';
  const next = await api<{id: number | null}>(`/photos/${id}/next?${query(filters)}`);
  return next.id;
}
