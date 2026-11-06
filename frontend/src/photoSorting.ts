import { hasPermission } from './permissions';
import type { Filters, User } from './types';

export const photoSortOptions = [
  {value: 'photo_desc', label: 'Сначала поздние фотографии'},
  {value: 'photo_asc', label: 'Сначала ранние фотографии'},
] as const;

export function photoSortValue(filters: Filters): string {
  return filters.sort_order === 'asc' ? 'photo_asc' : 'photo_desc';
}

export function photoSortFilters(value: string): Filters {
  return {date_basis: 'photo', sort_order: value === 'photo_asc' ? 'asc' : 'desc'};
}

export function photoSortForUser(filters: Filters, user: User): Filters {
  return photoSortFilters(hasPermission(user, 'photos_sort') ? photoSortValue(filters) : 'photo_desc');
}
