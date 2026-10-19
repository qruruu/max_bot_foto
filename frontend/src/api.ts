import type { Filters } from './types';
export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(x => x.msg).join('; ') : (detail as {message?:string})?.message || 'Ошибка запроса');
  }
}
export function query(filters: Filters): string {
  return new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== '')).toString();
}
export function reportPhotoLink(filters: Filters, group: Filters = {}): string {
  // The report includes duplicates and forwarded photos unless explicitly restricted.
  // Make that scope explicit so the list's default does not change the selection.
  const params: Filters = { ...filters, ...group, work_only: filters.work_only || 'false' };
  if (!params.date_from && !params.date_to) params.all_dates = '1';
  for (const key of ['page', 'anchor_id', 'review', 'spam', 'from_map', 'operator_chat']) delete params[key];
  return `/photos?${query(params)}`;
}
export function photoLink(id: number, filters: Filters, review = false, spam = false): string {
  const params: Filters = { ...filters, review: review ? '1' : '0', spam: spam ? '1' : '0' };
  // Preserve an explicit all-dates choice when returning from a photo to the list.
  if (!filters.date_from && !filters.date_to) params.all_dates = '1';
  return `/photos/${id}?${query(params)}`;
}
export async function api<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const csrf = document.cookie.split('; ').find(x => x.startsWith('csrf='))?.slice(5) || '';
  const upload = body instanceof Blob;
  const response = await fetch('/api' + path, { method, credentials: 'same-origin', signal,
    headers: { 'Content-Type': upload ? body.type || 'application/octet-stream' : 'application/json', 'X-CSRF-Token': decodeURIComponent(csrf) }, body: body === undefined ? undefined : upload ? body : JSON.stringify(body) });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: 'Сервис временно недоступен' }));
    if (response.status === 401 && path !== '/auth/me' && path !== '/auth/login') window.dispatchEvent(new Event('session-expired'));
    throw new ApiError(response.status, data.detail);
  }
  return response.json();
}
export const statusNames: Record<string, string> = {RECEIVED:'Получено', PROCESSING:'Обработка', ACCEPTED:'Принято', NEEDS_REVIEW:'Требует проверки', REJECTED:'Отклонено', DUPLICATE:'Дубль', FORWARDED:'Переслано', ERROR:'Ошибка', SPAM:'Спам'};
export const reasonNames: Record<string,string> = {DATE_MISSING:'Не распознана дата', COORDINATES_MISSING:'Не распознаны координаты', OUTSIDE_DISTRICTS:'Точка вне микрорайонов', DISTRICT_OVERLAP:'Точка в пересечении границ', WORK_MULTIPLE:'Несколько видов работ', WORK_UNCERTAIN:'Вид работы не определён', UNSUPPORTED_FORMAT:'Неподдерживаемый формат', CORRUPT_IMAGE:'Изображение не читается'};
export function dateLabel(value: string | null) { return value ? new Date(value.length === 10 ? value + 'T12:00:00' : value).toLocaleDateString('ru-RU') : '—'; }
export function shiftDate(value: string, days: number) { const d = new Date(value + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0,10); }

export function processingErrorLabel(code: string | null): string {
  if(code==='ORIGINAL_MISSING')return 'Оригинал не найден на Яндекс.Диске. Автоматические повторы остановлены. Восстановите файл из корзины Диска по прежнему пути и нажмите «Проверить снова».';
  const labels: Record<string, string> = {
    LEGACY_TEST_TREE_HAS_PENDING_PHOTOS: 'В старой учебной папке остались фото с незавершённым переносом. Перенос всей папки отложен.',
    LEGACY_EXCHANGE_UNMANAGED_FILE: 'В старой папке обмена есть файл, принадлежность которого сервису не подтверждена. Другие шаги очистки продолжаются.',
    LEGACY_EXCHANGE_FILE_CHANGED: 'Содержимое старого JSON изменилось. Его удаление остановлено.',
    LEGACY_EXCHANGE_INVALID_DOCUMENT: 'Не удалось подтвердить формат или источник старого JSON. Его удаление остановлено.',
    LEGACY_EXCHANGE_CONTAINS_ORIGINAL_REFERENCE: 'В старой папке обмена найден путь к оригиналу фото. Удаление папки остановлено.',
    YANDEX_FOLDER_MOVE_CONFLICT: 'Целевая папка переноса уже существует. Остальные шаги очистки продолжаются.',
    YANDEX_OPERATION_PENDING: 'Яндекс.Диск ещё выполняет операцию. Сервис проверит результат при повторной попытке.',
  };
  if (code && labels[code]) return labels[code];
  return code||'—';
}
