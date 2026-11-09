import { hasPermission } from './permissions';
import type { Filters, User } from './types';

export const photoSortOptions = [
  {value: 'photo_desc', label: 'Сначала поздние фотографии'},
  {value: 'photo_asc', label: 'Сначала ранние фотографии'},
  {value: 'received_desc', label: 'Сначала поздние поступления'},
  {value: 'received_asc', label: 'Сначала ранние поступления'},
] as const;

export function photoSortValue(filters: Filters): string {
  if (filters.sort_order === 'received_asc' || filters.sort_order === 'received_desc') return filters.sort_order;
  return filters.sort_order === 'desc' ? 'photo_desc' : 'photo_asc';
}

export function photoSortFilters(value: string): Filters {
  return {date_basis: 'photo', sort_order: value === 'photo_asc' ? 'asc' : value === 'photo_desc' ? 'desc' : value};
}

export function photoSortForUser(filters: Filters, user: User): Filters {
  return photoSortFilters(hasPermission(user, 'photos_sort') ? photoSortValue(filters) : 'photo_asc');
}
