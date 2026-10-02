import type { Filters } from './types';
export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(x => x.msg).join('; ') : (detail as {message?:string})?.message || 'Ошибка запроса');
  }
}
export function query(filters: Filters): string {
  return new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== '')).toString();
}
export async function api<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const csrf = document.cookie.split('; ').find(x => x.startsWith('csrf='))?.slice(5) || '';
  const response = await fetch('/api' + path, { method, credentials: 'same-origin', signal,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': decodeURIComponent(csrf) }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: 'Сервис временно недоступен' }));
    if (response.status === 401 && path !== '/auth/me' && path !== '/auth/login') window.dispatchEvent(new Event('session-expired'));
    throw new ApiError(response.status, data.detail);
  }
  return response.json();
}
export const statusNames: Record<string, string> = {RECEIVED:'Получено', PROCESSING:'Обработка', ACCEPTED:'Принято', NEEDS_REVIEW:'Требует проверки', REJECTED:'Отклонено', DUPLICATE:'Дубль', FORWARDED:'Переслано', ERROR:'Ошибка'};
export const reasonNames: Record<string,string> = {DATE_MISSING:'Не распознана дата', COORDINATES_MISSING:'Не распознаны координаты', OUTSIDE_DISTRICTS:'Точка вне микрорайонов', DISTRICT_OVERLAP:'Точка в пересечении границ', WORK_MULTIPLE:'Несколько видов работ', WORK_UNCERTAIN:'Вид работы не определён', UNSUPPORTED_FORMAT:'Неподдерживаемый формат', CORRUPT_IMAGE:'Изображение не читается'};
export function dateLabel(value: string | null) { return value ? new Date(value.length === 10 ? value + 'T12:00:00' : value).toLocaleDateString('ru-RU') : '—'; }
export function shiftDate(value: string, days: number) { const d = new Date(value + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0,10); }
