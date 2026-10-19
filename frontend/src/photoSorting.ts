import { hasPermission } from './permissions';
import type { Filters, User } from './types';

export const photoSortOptions = [
  {value: 'photo_asc', label: 'Сначала ранние фотографии', basis: 'photo', order: 'asc'},
  {value: 'photo_desc', label: 'Сначала поздние фотографии', basis: 'photo', order: 'desc'},
  {value: 'received_asc', label: 'Сначала ранние получения', basis: 'received', order: 'asc'},
  {value: 'received_desc', label: 'Сначала поздние получения', basis: 'received', order: 'desc'},
] as const;

export function photoSortValue(filters: Filters): string {
  // Older links used received_desc independently of the date filter.
  if (!filters.sort_order || filters.sort_order === 'received_desc') return 'received_desc';
  const value = `${filters.date_basis || 'photo'}_${filters.sort_order}`;
  return photoSortOptions.some(option => option.value === value) ? value : 'received_desc';
}

export function photoSortFilters(value: string): Filters {
  const option = photoSortOptions.find(option => option.value === value) || photoSortOptions[3];
  return {date_basis: option.basis, sort_order: option.order};
}

export function photoSortForUser(filters: Filters, user: User): Filters {
  return photoSortFilters(hasPermission(user, 'photos_sort') ? photoSortValue(filters) : 'photo_desc');
}
