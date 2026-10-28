import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { CheckCircle2, ImagePlus, LockKeyhole, Send, Trash2 } from 'lucide-react';
import { api, ApiError } from '../api';
import { availableRecipient } from '../appeals/catalog';
import type { PublicOrganization } from '../appeals/catalog';
import { clearDraft, EMPTY_FORM, hasDraftContent, loadDraft, saveDraft } from '../appeals/drafts';
import type { AppealDraft, StoredPhoto } from '../appeals/drafts';
import { galleryPhoto } from '../appeals/gallery';
import RecipientChoice from '../appeals/RecipientChoice';
import './appeals.css';

const ProblemMap = lazy(() => import('../appeals/ProblemMap'));
type Catalog = {organization: PublicOrganization; yandex_maps_api_key: string};
type Receipt = {id: number; number: string; is_public: false};
type Photo = StoredPhoto & {url: string};

export default function InspectionAppealForm({organizationId, inspectorId, created}: {
  organizationId: string; inspectorId: number; created: () => void;
}) {
  const endpoint = '/inspection/organizations/' + organizationId + '/appeals';
  const storageKey = 'inspector:' + inspectorId + ':' + organizationId;
  const [catalog, setCatalog] = useState<Catalog | null>(null), [form, setForm] = useState(EMPTY_FORM);
  const [photos, setPhotos] = useState<Photo[]>([]), [loaded, setLoaded] = useState(false), [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false), [preparing, setPreparing] = useState(false), [error, setError] = useState('');
  const [storageError, setStorageError] = useState(false), [receipt, setReceipt] = useState<Receipt | null>(null);
  const [revision, setRevision] = useState(0);
  const clientId = useRef<string>(crypto.randomUUID()), active = useRef(true), sending = useRef(false), completed = useRef(false);
  const photosRef = useRef(photos), writes = useRef<Promise<void>>(Promise.resolve()), input = useRef<HTMLInputElement>(null);
  const snapshot = useRef<AppealDraft>({form, photos: [], token: null, pending: false, savedAt: Date.now()});
  photosRef.current = photos;
  snapshot.current = {form, photos: photos.map(({id, blob, preview}) => ({id, blob, preview})), token: null, pending, clientId: clientId.current, savedAt: Date.now()};
  const locked = busy || preparing || pending;
  const organization = catalog?.organization, address = organization?.addresses?.find(item => item.id === form.address_id);
  const located = !!address && form.longitude !== null && form.latitude !== null;

  function persist(draft = snapshot.current) {
    writes.current = writes.current.catch(() => {}).then(async () => {
      if (completed.current) return;
      if (hasDraftContent(draft.form, draft.photos, draft.pending)) await saveDraft(draft, storageKey);
    }).catch(() => {if (active.current) setStorageError(true);});
    return writes.current;
  }
  function finish(value: Receipt) {
    completed.current = true;
    writes.current = writes.current.catch(() => {}).then(() => clearDraft(storageKey)).catch(() => {});
    if (!active.current) return;
    photosRef.current.forEach(photo => URL.revokeObjectURL(photo.url)); setPhotos([]);
    setReceipt(value); setPending(false); setError(''); created();
  }
  useEffect(() => {
    active.current = true; let current = true;
    loadDraft(storageKey).then(draft => {
      if (!current || !draft) return;
      setForm({...EMPTY_FORM, ...draft.form, contact: ''});
      setPhotos(draft.photos.map(photo => ({...photo, url: URL.createObjectURL(photo.preview)})));
      if (draft.clientId) clientId.current = draft.clientId;
      setPending(draft.pending);
    }).catch(() => {if (current) setStorageError(true);}).finally(() => {if (current) setLoaded(true);});
    return () => {current = false; active.current = false; photosRef.current.forEach(photo => URL.revokeObjectURL(photo.url));};
  }, [storageKey]);
  useEffect(() => {
    const abort = new AbortController(); setError('');
    api<Catalog>(endpoint + '/catalog', 'GET', undefined, abort.signal).then(value => setCatalog(value))
      .catch(reason => {if (!abort.signal.aborted) setError(reason.message);});
    return () => abort.abort();
  }, [endpoint, revision]);
  useEffect(() => {
    if (!loaded || !catalog || locked || receipt) return;
    setForm(current => availableRecipient({...current, city: catalog.organization.city || '', organization_id: organizationId},
      {organizations: [catalog.organization], yandex_maps_api_key: catalog.yandex_maps_api_key}));
  }, [loaded, catalog, locked, receipt, form.address_id, form.category, organizationId]);
  useEffect(() => {
    if (loaded && !completed.current) void persist();
    const hidden = () => {if (document.hidden && loaded) void persist();};
    document.addEventListener('visibilitychange', hidden);
    return () => document.removeEventListener('visibilitychange', hidden);
  }, [loaded, form, photos, pending]);
  useEffect(() => {
    const leaving = (event: BeforeUnloadEvent) => {
      if (!completed.current && (photosRef.current.length || snapshot.current.form.description || snapshot.current.pending)) {
        void persist(); event.preventDefault(); event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', leaving); return () => window.removeEventListener('beforeunload', leaving);
  }, [storageKey]);

  async function addPhotos(files: FileList | null) {
    if (!files || sending.current || locked) return;
    sending.current = true; setPreparing(true); setError('');
    const added: Photo[] = [];
    try {
      if (photos.length + files.length > 3) throw new Error('Можно приложить до трёх фотографий');
      for (const file of [...files]) {const photo = await galleryPhoto(file); added.push({...photo, url: URL.createObjectURL(photo.preview)});}
      if (active.current) setPhotos(current => [...current, ...added]); else added.forEach(photo => URL.revokeObjectURL(photo.url));
    } catch (reason) {added.forEach(photo => URL.revokeObjectURL(photo.url)); if (active.current) setError((reason as Error).message);}
    finally {sending.current = false; if (active.current) setPreparing(false); if (input.current) input.current.value = '';}
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (sending.current) return;
    if (!pending && (!located || !photos.length || !organization?.work_types.some(work => work.code === form.category))) return;
    sending.current = true; setBusy(true); setError(''); let attempted = false;
    try {
      if (pending) {
        try {finish(await api<Receipt>(endpoint + '/submissions/' + clientId.current)); return;}
        catch (reason) {if (!(reason instanceof ApiError) || reason.status !== 404) throw reason;}
      }
      const {contact: _contact, ...fields} = form;
      const body = new FormData(); body.append('metadata', JSON.stringify({...fields, client_id: clientId.current}));
      photos.forEach((photo, index) => body.append('photos', photo.blob, 'photo-' + (index + 1) + (photo.blob.type.includes('hei') ? '.heic' : '.jpg')));
      setPending(true); await persist({...snapshot.current, pending: true, clientId: clientId.current}); attempted = true;
      finish(await api<Receipt>(endpoint, 'POST', body));
    } catch (reason) {
      if (reason instanceof ApiError && reason.status >= 400 && reason.status < 500) setPending(false);
      else if (attempted) setPending(true);
      if (active.current) setError((reason as Error).message);
    } finally {sending.current = false; if (active.current) setBusy(false);}
  }
  function another() {
    completed.current = false; clientId.current = crypto.randomUUID(); setReceipt(null); setForm(EMPTY_FORM); setPhotos([]); setPending(false);
  }
  return <section className="panel inspector-appeal-form"><div className="section-title"><h2>Жалоба проверяющего</h2><span className="badge"><LockKeyhole size={14}/>Только в «Метке»</span></div>
    <p className="hint">Обращение, фотографии и ответ организации будут видны в «Метке». На стене «Сигнала» они не появятся.</p>
    {error && <div className="error" role="alert">{error}{!catalog && <button onClick={() => setRevision(value => value + 1)}>Повторить загрузку</button>}</div>}
    {storageError && <p className="hint">Не закрывайте вкладку до отправки: браузер не разрешил сохранить черновик.</p>}
    {receipt ? <div className="inspector-appeal-receipt" role="status"><CheckCircle2/><h3>Обращение {receipt.number} передано организации</h3><p>Оно доступно в списке ниже. Результат рассмотрения останется внутри «Метки».</p><button onClick={another}>Написать ещё одну жалобу</button></div>
      : !loaded || !catalog ? !error && <p className="loading">Загружаем форму…</p> : <form onSubmit={event => void submit(event)}>
        {pending && <p className="hint" role="status">Проверяем отправку. Повторная попытка не создаст дубль.</p>}
        <fieldset disabled={locked}>
          <p><strong>{organization?.name}</strong>{organization?.city ? ' · ' + organization.city : ''}</p>
          <RecipientChoice label="Улица и адрес" name="address_id" placeholder="Выберите адрес" options={(organization?.addresses || []).map(item => ({value: item.id, label: item.label}))}
            value={form.address_id} disabled={locked} onChange={id => {const selected = organization?.addresses?.find(item => item.id === id); setForm(current => ({...current, address_id: id, address: selected?.label || '', latitude: null, longitude: null}));}}/>
          <p className="hint">{!organization?.city ? 'У организации не указан город. Его должен добавить владелец сервиса.' : organization?.addresses?.length
            ? 'Для этой организации можно выбрать только адрес из списка обслуживаемых ею адресов.' : 'Организация пока не добавила обслуживаемые адреса.'}</p>
          {organization && address && <Suspense fallback={<p>Загружаем карту…</p>}><ProblemMap organization={organization} districtId={address.district_id} apiKey={catalog.yandex_maps_api_key}
            point={located ? [form.longitude!, form.latitude!] : null} disabled={locked} onPoint={point => setForm(current => ({...current, longitude: point[0], latitude: point[1]}))}/></Suspense>}
        </fieldset>
        <fieldset disabled={locked || !located}>
          <RecipientChoice label="Вид работ" name="category" placeholder="Выберите вид работ" options={(organization?.work_types || []).map(work => ({value: work.code, label: work.name}))}
            value={form.category} disabled={locked} onChange={category => setForm(current => ({...current, category}))}/>
          <label>Описание нарушения<textarea required maxLength={4000} rows={4} value={form.description} onChange={event => setForm(current => ({...current, description: event.target.value}))}/></label>
          <label>Уточнение места <small>необязательно</small><input maxLength={300} value={form.place} onChange={event => setForm(current => ({...current, place: event.target.value}))}/></label>
          <label>Фотографии <small>от 1 до 3</small><input ref={input} type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif" multiple onChange={event => void addPhotos(event.target.files)}/></label>
          <div className="inspector-appeal-photos">{photos.map((photo, index) => <div key={photo.id}><a href={photo.url} target="_blank" rel="noreferrer"><img src={photo.url} alt={'Фото нарушения ' + (index + 1)}/></a><button type="button" aria-label={'Удалить фото ' + (index + 1)} onClick={() => {URL.revokeObjectURL(photo.url); setPhotos(current => current.filter(item => item.id !== photo.id));}}><Trash2 size={16}/></button></div>)}</div>
          {preparing && <p className="hint"><ImagePlus size={16}/>Подготавливаем фотографии…</p>}
        </fieldset>
        <button className="primary" disabled={busy || preparing || (!pending && (!located || !photos.length || !form.category || !organization?.city))}><Send size={16}/>{busy ? 'Отправляем…' : pending ? 'Проверить отправку' : 'Отправить жалобу организации'}</button>
      </form>}
  </section>;
}
