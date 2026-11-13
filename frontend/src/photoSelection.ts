import { api } from './api';
import { apiUrl } from './workspace';
import type { Filters, Photo } from './types';
import { MAX_DOWNLOAD_PHOTOS } from './photoLimits';

export type SelectedPhoto = Pick<Photo, 'id' | 'preview_url'>;
export type PhotoSelectionSpec = {filters: Record<string, string | number>; excluded_ids?: number[]} | {ids: number[]};
export type FilteredPhotoSelection = {filters: Filters; snapshot_id: number; count: number; ids: number[]};
type SelectionSummary = {snapshot_id: number; count: number; ids: number[]};

export function selectionSummary(selection: PhotoSelectionSpec, signal?: AbortSignal) {
  return api<SelectionSummary>('/photos/selection', 'POST', selection, signal);
}

export async function selectFilteredPhotos(filters: Filters, signal: AbortSignal): Promise<FilteredPhotoSelection> {
  const params = {...filters};
  for (const key of ['page', 'page_size', 'anchor_id', 'after_id', 'snapshot_id']) delete params[key];
  for (const key of Object.keys(params)) if (params[key] === '') delete params[key];
  const result = await selectionSummary({filters: params}, signal);
  signal.throwIfAborted();
  const ids = result.ids.slice(0, MAX_DOWNLOAD_PHOTOS);
  return {...result, count: ids.length, ids, filters: params};
}

export function selectionPhotos(ids: number[]): SelectedPhoto[] {
  return ids.map(id => ({id, preview_url: apiUrl(`/photos/${id}/preview`)}));
}
