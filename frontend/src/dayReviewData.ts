import { photoLink, query } from './api';
import type { Filters } from './types';

export type DaySummary = {
  day: string; total: number; confirmed: number; pending: number; new: number; changed: number;
  blocked: number; closed_before: boolean; last_confirmation_at: string | null; can_close: boolean; snapshot: string;
  ai_pending: number; manual_pending: number;
  work_types: {code: string; name: string; confirmed: number; pending: number}[];
};

export function dayReviewDate(value: string | null, fallback: string): string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return fallback;
  const parsed = new Date(value + 'T12:00:00Z');
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : fallback;
}

export function dayPhotoFilters(day: string, work = '', page = 1): Filters {
  return {review_day: day, day_review: 'pending', day_ai_only: 'true',
    work_only: 'true', date_basis: 'photo', sort_order: 'desc', work_type: work,
    page: String(page), page_size: '24'};
}

export function dayPhotoLink(id: number, day: string, filters: Filters): string {
  return photoLink(id, {...filters, from_day: day});
}

export function confirmedDayReportLink(day: string): string {
  return '/?' + query({date_from: day, date_to: day, date_basis: 'photo', sort_order: 'desc', review_day: day, day_review: 'confirmed'});
}
