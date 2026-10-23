import type { Filters } from './types';
import { apiUrl, workspacePrefix } from './workspace';

let platformOwner = false;
export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(x => x.msg).join('; ') : (detail as {message?:string})?.message || 'Ошибка запроса');
  }
}
export function query(filters: Filters): string {
  return new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== '')).toString();
}
export function reportPhotoLink(filters: Filters, group: Filters = {}): string {
  // Match the work breakdowns even when opening a report saved with the old scope.
  // Explicit DUPLICATE/FORWARDED statuses still open their separate archives.
  const params: Filters = { ...filters, ...group, work_only: 'true' };
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
  const prefix = workspacePrefix();
  const csrfName = path === '/auth/choose-organization' ? 'login_choice_csrf' : platformOwner ? 'platform_csrf' : prefix ? 'workspace_csrf' : 'csrf';
  const csrf = document.cookie.split('; ').find(x => x.startsWith(csrfName + '='))?.slice(csrfName.length + 1) || '';
  const upload = body instanceof Blob;
  const response = await fetch(apiUrl(path), { method, credentials: 'same-origin', signal,
    headers: { 'Content-Type': upload ? body.type || 'application/octet-stream' : 'application/json', 'X-CSRF-Token': decodeURIComponent(csrf) }, body: body === undefined ? undefined : upload ? body : JSON.stringify(body) });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: 'Сервис временно недоступен' }));
    if (response.status === 401 && path !== '/auth/me' && path !== '/auth/login') window.dispatchEvent(new Event('session-expired'));
    throw new ApiError(response.status, data.detail);
  }
  const data = await response.json();
  if (path === '/auth/me' || path === '/auth/login' || path === '/auth/choose-organization') platformOwner = data.is_platform_owner === true;
  if (path === '/auth/entry') platformOwner = data.user?.is_platform_owner === true;
  // Owner profile writes are handled by the global account; retain the local audit/chat actor id.
  if (prefix && data.is_platform_owner && data.organization === null) return api<T>('/auth/me');
  return data;
}
export const statusNames: Record<string, string> = {RECEIVED:'Получено', PROCESSING:'Обработка', ACCEPTED:'Принято', NEEDS_REVIEW:'Требует проверки', REJECTED:'Отклонено', DUPLICATE:'Дубль', FORWARDED:'Переслано', ERROR:'Ошибка', SPAM:'Спам'};
export const reasonNames: Record<string,string> = {DATE_MISSING:'Не распознана дата', COORDINATES_MISSING:'Не распознаны координаты', OUTSIDE_DISTRICTS:'Точка вне микрорайонов', DISTRICT_OVERLAP:'Точка в пересечении границ', WORK_MULTIPLE:'Несколько видов работ', WORK_UNCERTAIN:'Вид работы не определён', UNSUPPORTED_FORMAT:'Неподдерживаемый формат', CORRUPT_IMAGE:'Изображение не читается'};
export function dateLabel(value: string | null) { return value ? new Date(value.length === 10 ? value + 'T12:00:00' : value).toLocaleDateString('ru-RU') : '—'; }
export function shiftDate(value: string, days: number) { const d = new Date(value + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0,10); }

export function processingErrorLabel(code: string | null): string {
  if(code==='ORIGINAL_MISSING')return 'Оригинал не найден по сохранённому пути на подключённом Яндекс.Диске. Автоматические повторы остановлены. Проверьте выбранный Диск и расположение файла. Если файл удалён, восстановите его из корзины, затем нажмите «Проверить снова».';
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
