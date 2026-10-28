import type { CaptureMetadata, CaptureSession } from './camera';

export type AppealForm = {city: string; organization_id: string; address: string; place: string; category: string; description: string;
  contact: string; website: string; address_id: string; latitude: number | null; longitude: number | null};
export const EMPTY_FORM: AppealForm = {city: '', organization_id: '', address: '', address_id: '', latitude: null, longitude: null,
  place: '', category: '', description: '', contact: '', website: ''};
export type StoredPhoto = {id: string; blob: Blob; preview: Blob; capture?: CaptureMetadata};
export type AppealDraft = {form: AppealForm; photos: StoredPhoto[]; token: string | null; pending: boolean; savedAt: number; receipt?: string; clientId?: string};
const DATABASE = 'citizen-appeal-drafts', STORE = 'drafts', KEY = 'current';
const MAX_AGE = 24 * 60 * 60 * 1000;

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error('Хранилище черновиков недоступно'));
  });
}

async function transaction<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await database();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const request = action(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error || new Error('Не удалось сохранить черновик'));
    });
  } finally {db.close();}
}

export function clearDraft(key = KEY): Promise<void> {
  return transaction('readwrite', store => store.delete(key)).then(() => undefined);
}

export function saveDraft(draft: AppealDraft, key = KEY): Promise<void> {
  return transaction('readwrite', store => store.put(draft, key)).then(() => undefined);
}

export async function loadDraft(key = KEY): Promise<AppealDraft | null> {
  const draft = await transaction<AppealDraft | undefined>('readonly', store => store.get(key));
  if (!draft) return null;
  if (!draftIsFresh(draft.savedAt)) {await clearDraft(key); return null;}
  // Keep text/photos from the earlier owner-only form; require choosing a registered recipient.
  const form = Object.fromEntries(Object.entries(EMPTY_FORM).map(([key, value]) => [key, draft.form[key as keyof AppealForm] ?? value])) as AppealForm;
  return {...draft, form};
}

export function draftIsFresh(savedAt: number, current = Date.now()) {
  return Number.isFinite(savedAt) && savedAt <= current + 60_000 && current - savedAt < MAX_AGE;
}

export function hasDraftContent(form: AppealForm, photos: StoredPhoto[], pending: boolean) {
  return photos.length > 0 || pending || Object.values(form).some(value => typeof value === 'string' && value.trim().length > 0);
}

export type ResumeSession = Omit<CaptureSession, 'receivedAt'> & {expired: boolean; submitted: {number: string} | null};
