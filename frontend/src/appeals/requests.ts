export class AppealRequestError extends Error {
  constructor(message: string, public status = 0) {super(message);}
  get uncertain() {return this.status === 0 || this.status >= 500;}
}

export async function publicRequest<T>(path: string, init: RequestInit, timeoutMs = 15_000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch('/api/public/appeals' + path, {...init, credentials: 'omit', signal: controller.signal,
      headers: {'X-Appeal-Request': 'form', ...init.headers}});
    const result = await response.json().catch(() => null);
    if (!response.ok) throw new AppealRequestError(typeof result?.detail === 'string' ? result.detail
      : response.status === 413 ? 'Фотографии слишком большие. Выберите файлы поменьше и попробуйте ещё раз.'
      : response.status === 429 ? 'Слишком много попыток. Подождите немного; анкета и снимки сохранены.'
      : 'Сервер временно недоступен. Анкета и снимки сохранены — повторите попытку.', response.status);
    if (!result) throw new AppealRequestError('Не удалось получить подтверждение сервера. Повторите попытку.');
    return result as T;
  } catch (error) {
    if (error instanceof AppealRequestError) throw error;
    throw new AppealRequestError(controller.signal.aborted
      ? 'Ответ сервера задерживается. Анкета и снимки сохранены — повторите попытку.'
      : 'Не удалось связаться с сервером. Проверьте интернет и повторите попытку — анкета и снимки сохранены.');
  } finally {window.clearTimeout(timer);}
}
