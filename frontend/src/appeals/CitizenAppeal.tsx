import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowLeft, ArrowRight, CheckCircle2, ImagePlus, List, MapPin, Plus, Radio, ShieldCheck, Trash2, WifiOff } from 'lucide-react';
import { AppealRequestError, publicRequest } from './requests';
import { clearDraft, EMPTY_FORM, hasDraftContent, loadDraft, saveDraft } from './drafts';
import type { AppealDraft, ResumeSession, StoredPhoto } from './drafts';
import { availableRecipient, recipientFor, validRecipient } from './catalog';
import type { AppealCatalog } from './catalog';
import RecipientChoice from './RecipientChoice';
import { citizenWorkOption } from './workTypes';
import { galleryPhoto } from './gallery';
import Wall from './Wall';
import UpdateNotice from '../UpdateNotice';
import './citizen.css';
import './signal.css';

const ProblemMap = lazy(() => import('./ProblemMap'));
type LocalPhoto = StoredPhoto & {url: string};
export default function CitizenAppeal() {
  const [catalog, setCatalog] = useState<AppealCatalog | null>(null), [catalogError, setCatalogError] = useState('');
  const [catalogRevision, setCatalogRevision] = useState(0), [wallRevision, setWallRevision] = useState(0);
  const [tab, setTab] = useState<'wall' | 'create'>('wall'), [step, setStep] = useState(1);
  const [form, setForm] = useState(EMPTY_FORM), [photos, setPhotos] = useState<LocalPhoto[]>([]);
  const [busy, setBusy] = useState(false), [preparing, setPreparing] = useState(false), [error, setError] = useState('');
  const [receipt, setReceipt] = useState('');
  const [loaded, setLoaded] = useState(false), [restored, setRestored] = useState(false), [pending, setPending] = useState(false);
  const [storageError, setStorageError] = useState(false), [offline, setOffline] = useState(!navigator.onLine), [reloading, setReloading] = useState(false);
  const token = useRef<string | null>(null), requestActive = useRef(false), mounted = useRef(true), allowReload = useRef(false);
  const writes = useRef<Promise<void>>(Promise.resolve()), receiptRef = useRef(''), photoRef = useRef(photos);
  const snapshot = useRef<AppealDraft>({form, photos: [], token: null, pending: false, savedAt: Date.now()});
  const input = useRef<HTMLInputElement>(null);
  const main = useRef<HTMLElement>(null);
  const locked = busy || preparing || pending || reloading;
  const cities = useMemo(() => [...new Set(catalog?.organizations.map(item => item.city))].sort((a, b) => a.localeCompare(b, 'ru')), [catalog]);
  const cityOrganizations = useMemo(() => catalog?.organizations.filter(item => item.city === form.city) || [], [catalog, form.city]);
  const recipient = recipientFor(form, catalog), address = recipient?.addresses?.find(item => item.id === form.address_id);
  const located = !!address && form.latitude !== null && form.longitude !== null;
  photoRef.current = photos;
  snapshot.current = {form, photos: photos.map(({id, blob, preview, capture}) => ({id, blob, preview, capture})), token: token.current, pending, savedAt: Date.now()};

  function persist(draft = snapshot.current, required = false) {
    const operation = writes.current.catch(() => {}).then(async () => {
      if (receiptRef.current && !draft.receipt) return;
      if (draft.receipt || hasDraftContent(draft.form, draft.photos, draft.pending)) await saveDraft(draft);
      else await clearDraft();
    });
    writes.current = operation.catch(() => {if (mounted.current) setStorageError(true);});
    return required ? operation : writes.current;
  }
  async function prepareUpdate() {
    if (requestActive.current) throw new Error('Дождитесь окончания текущего действия.');
    requestActive.current = true; setReloading(true);
    try {
      await persist(receiptRef.current ? {form, photos: [], token: null, pending: false, receipt: receiptRef.current, savedAt: Date.now()} : snapshot.current, true);
      allowReload.current = true;
    } catch {requestActive.current = false; setReloading(false); throw new Error('Не удалось сохранить черновик. Не закрывайте страницу и попробуйте обновить ещё раз.');}
  }
  function complete(number: string) {
    receiptRef.current = number;
    void persist({form: {...EMPTY_FORM, city: form.city}, photos: [], token: null, pending: false, receipt: number, savedAt: Date.now()});
    if (!mounted.current) return;
    setReceipt(number); setPending(false); setError(''); token.current = null;
    photoRef.current.forEach(photo => URL.revokeObjectURL(photo.url)); setPhotos([]);
    setForm({...EMPTY_FORM, city: form.city}); setTab('wall'); setStep(1); setWallRevision(value => value + 1);
  }
  useEffect(() => {
    let active = true; setCatalogError('');
    publicRequest<AppealCatalog>('/catalog', {method: 'GET'}).then(value => {if (active) setCatalog(value);})
      .catch(failure => {if (active) setCatalogError(failure.message);});
    return () => {active = false;};
  }, [catalogRevision]);
  useEffect(() => {
    mounted.current = true; let active = true;
    loadDraft().then(draft => {
      if (!active || !draft) return;
      const hasContent = draft.photos.length || draft.form.description || draft.pending;
      if (hasContent) setForm({...EMPTY_FORM, ...draft.form});
      if (draft.receipt) {receiptRef.current = draft.receipt; setReceipt(draft.receipt); return;}
      if (!hasContent) return;
      setPhotos(draft.photos.map(photo => ({...photo, url: URL.createObjectURL(photo.preview)})));
      token.current = draft.token; setPending(draft.pending); setRestored(true);
      if (draft.photos.length || draft.form.description || draft.pending) {setTab('create'); setStep(2);}
    }).catch(() => {if (active) setStorageError(true);}).finally(() => {if (active) setLoaded(true);});
    return () => {active = false; mounted.current = false; photoRef.current.forEach(photo => URL.revokeObjectURL(photo.url));};
  }, []);
  useEffect(() => {
    if (!loaded || receiptRef.current) return;
    const timer = window.setTimeout(() => void persist(), 350);
    const hidden = () => {if (document.hidden) void persist();};
    document.addEventListener('visibilitychange', hidden); window.addEventListener('pagehide', hidden);
    return () => {window.clearTimeout(timer); document.removeEventListener('visibilitychange', hidden); window.removeEventListener('pagehide', hidden);};
  }, [loaded, form, photos, pending]);
  useEffect(() => {
    const online = () => setOffline(!navigator.onLine);
    window.addEventListener('online', online); window.addEventListener('offline', online);
    return () => {window.removeEventListener('online', online); window.removeEventListener('offline', online);};
  }, []);
  useEffect(() => {
    if (loaded && catalog && !locked) setForm(current => availableRecipient(current, catalog));
  }, [loaded, catalog, locked, form.city, form.organization_id, form.category, form.address_id]);
  useEffect(() => {
    main.current?.scrollIntoView?.({block: 'start'});
  }, [step, tab]);
  useEffect(() => {
    const leaving = (event: BeforeUnloadEvent) => {if (!allowReload.current && !receiptRef.current && (photoRef.current.length || form.description)) {event.preventDefault(); event.returnValue = '';}};
    window.addEventListener('beforeunload', leaving); return () => window.removeEventListener('beforeunload', leaving);
  }, [form.description]);

  async function addPhotos(files: FileList | null) {
    if (!files || requestActive.current || locked) return;
    requestActive.current = true; setPreparing(true); setError('');
    const added: LocalPhoto[] = [];
    try {
      if (files.length + photos.length > 3) throw new Error('Можно приложить до трёх фотографий');
      for (const file of [...files]) {
        const photo = await galleryPhoto(file); added.push({...photo, url: URL.createObjectURL(photo.preview)});
      }
      if (mounted.current) setPhotos(current => [...current, ...added]);
      else added.forEach(photo => URL.revokeObjectURL(photo.url));
    } catch (failure) {added.forEach(photo => URL.revokeObjectURL(photo.url)); setError((failure as Error).message);}
    finally {requestActive.current = false; setPreparing(false); if (input.current) input.current.value = '';}
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (requestActive.current) return;
    if (!photos.length || (!pending && (!located || !validRecipient(form, catalog)))) {setError('Выберите территорию и точку на карте, опишите проблему и приложите фото.'); return;}
    requestActive.current = true; setBusy(true); setError(''); let attempted = false;
    try {
      if (token.current) {
        try {
          const resumed = await publicRequest<ResumeSession>('/capture-sessions/resume', {method: 'POST', headers: {'X-Capture-Token': token.current}});
          if (resumed.submitted) {complete(resumed.submitted.number); return;}
          if (resumed.expired) token.current = null;
        } catch (failure) {
          if (failure instanceof AppealRequestError && failure.status === 409) token.current = null;
          else throw failure;
        }
      }
      if (!token.current) {
        const session = await publicRequest<{token: string}>('/sessions', {method: 'POST'}); token.current = session.token;
      }
      const legacy = pending && photos.every(photo => photo.capture) && !form.address_id;
      const data = new FormData();
      const {address_id, latitude, longitude, ...oldForm} = form;
      data.append('metadata', JSON.stringify(legacy ? {...oldForm, capture_source: 'camera', captures: photos.map(photo => photo.capture)}
        : {...form, capture_source: 'gallery', public_consent: true}));
      photos.forEach((photo, index) => data.append('photos', photo.blob, `photo-${index + 1}.${photo.blob.type.includes('hei') ? 'heic' : 'jpg'}`));
      setPending(true); await persist({...snapshot.current, token: token.current, pending: true}); attempted = true;
      const result = await publicRequest<{number: string}>(legacy ? '' : '/submissions', {method: 'POST', headers: {'X-Capture-Token': token.current}, body: data}, 120_000);
      complete(result.number);
    } catch (failure) {
      if (failure instanceof AppealRequestError && !failure.uncertain) setPending(false);
      else if (attempted) setPending(true);
      if (failure instanceof AppealRequestError && failure.status === 422) {setCatalogRevision(value => value + 1); setStep(1);}
      setError((failure as Error).message);
    } finally {requestActive.current = false; if (mounted.current) setBusy(false);}
  }
  function newAppeal() {if (locked) return; receiptRef.current = ''; setReceipt(''); setTab('create'); setStep(1);}
  if (!loaded) return <div className="citizen-app citizen-restoring" role="status">Открываем «Сигнал»…</div>;
  return <div className="citizen-app signal-app"><div className="signal-shell">
    <header className="signal-header"><a className="signal-brand" href="#" onClick={event => {event.preventDefault(); setTab('wall');}}><span><Radio size={22}/></span>Сигнал</a>
      {cities.length > 1 ? <label className="signal-city"><MapPin size={15}/><span className="signal-sr-only">Город</span><select name="city" value={form.city} disabled={locked} onChange={event => {setForm(current => ({...current, city: event.target.value, organization_id: '', category: '', address_id: '', address: '', latitude: null, longitude: null})); setStep(1);}}><option value="">Выберите город</option>{cities.map(city => <option key={city}>{city}</option>)}</select></label>
        : form.city && <span className="signal-city"><MapPin size={15}/>{form.city}</span>}</header>
    <main className="signal-main" ref={main}>
      {offline && <p className="signal-notice" role="status"><WifiOff size={18}/>Нет интернета. Черновик сохранится на телефоне.</p>}
      {catalogError && <div className="citizen-error" role="alert">{catalogError}<button onClick={() => setCatalogRevision(value => value + 1)}>Повторить загрузку</button></div>}
      {storageError && <p className="signal-notice">Не закрывайте вкладку до отправки: браузер не разрешил сохранить черновик.</p>}
      {receipt && <div className="signal-receipt" role="status"><CheckCircle2/><div><strong>Обращение {receipt} отправлено</strong><p>Оно появилось на стене города. Ответ организации появится в этой же карточке.</p></div></div>}
      {tab === 'wall' ? <Wall city={form.city} organizations={cityOrganizations} apiKey={catalog?.yandex_maps_api_key || ''} revision={wallRevision}/> : <>
        <div className="signal-compose-title"><span className="signal-eyebrow">НОВОЕ ОБРАЩЕНИЕ · ШАГ {step} ИЗ 2</span><h1>{step === 1 ? 'Выберите место' : 'Расскажите о проблеме'}</h1></div>
        <form className="citizen-form signal-form" onSubmit={event => void submit(event)}>
          {restored && <p className="signal-notice">Восстановили ваш черновик вместе с фотографиями.</p>}
          {pending && <p className="signal-notice" role="status">Проверяем, получено ли обращение. Повторная попытка не создаст дубль.</p>}
          {step === 1 ? <fieldset disabled={locked}>
            <RecipientChoice label="Организация" name="organization_id" options={cityOrganizations.map(item => ({value: item.id, label: item.name}))} value={form.organization_id} disabled={locked}
              onChange={id => setForm(current => ({...current, organization_id: id, category: '', address_id: '', address: '', latitude: null, longitude: null}))}/>
            {recipient && <><RecipientChoice label="Территория" name="address_id" placeholder="Выберите территорию" options={(recipient.addresses || []).map(item => ({value: item.id, label: item.label}))}
              value={form.address_id} disabled={locked} onChange={id => {const chosen = recipient.addresses?.find(item => item.id === id); setForm(current => ({...current, address_id: id, address: chosen?.label || '', latitude: null, longitude: null}));}}/>
              <p className="signal-address-rule"><ShieldCheck size={17}/>{recipient.addresses?.length ? 'Выберите территорию этой организации и отметьте на карте место проблемы.' : 'У организации пока нет активных территорий на карте.'}</p></>}
            {recipient && address && <Suspense fallback={<p>Загружаем карту…</p>}><ProblemMap key={recipient.id + address.id} organization={recipient} organizations={cityOrganizations} districtId={address.district_id} apiKey={catalog?.yandex_maps_api_key || ''}
              point={located ? [form.longitude!, form.latitude!] : null} disabled={locked} onPoint={point => setForm(current => ({...current, longitude: point[0], latitude: point[1]}))}/></Suspense>}
            {!catalog?.organizations.length && !catalogError && <p className="signal-notice">{catalog ? 'Пока нет организаций, готовых принимать обращения.' : 'Загружаем города и организации…'}</p>}
            <button type="button" className="citizen-primary signal-next" disabled={!located || locked} onClick={() => setStep(2)}>Далее<ArrowRight size={18}/></button>
          </fieldset> : <>
            <button type="button" className="signal-back" disabled={locked} onClick={() => setStep(1)}><ArrowLeft size={17}/>{form.address || 'Выбрать территорию и место'}</button>
            {!located && !pending && <p className="citizen-error">Сначала выберите территорию и отметьте место на карте.</p>}
            <fieldset disabled={locked || (!located && !pending)}>
              <RecipientChoice label="Что случилось?" name="category" placeholder="Выберите проблему" options={recipient?.work_types.filter(work => work.code !== 'DRAIN_CLEANING').map(citizenWorkOption) || []} value={form.category} disabled={locked}
                onChange={category => setForm(current => ({...current, category}))}/>
              <label>Описание<textarea required maxLength={4000} rows={4} placeholder="Что произошло и что нужно исправить?" value={form.description} onChange={event => setForm(current => ({...current, description: event.target.value}))}/></label>
              <label>Уточнение места <small>необязательно</small><input maxLength={300} placeholder="Например, рядом со вторым подъездом" value={form.place} onChange={event => setForm(current => ({...current, place: event.target.value}))}/></label>
              <div className="signal-section-title"><h2>Фотографии</h2><span>{photos.length} / 3</span></div>
              <div className="signal-upload-grid">{photos.map((photo, index) => <div className="signal-upload-photo" key={photo.id}><a href={photo.url} target="_blank" rel="noreferrer"><img src={photo.url} alt={`Фото ${index + 1}`}/></a>
                <button type="button" aria-label={`Удалить фото ${index + 1}`} onClick={() => {URL.revokeObjectURL(photo.url); setPhotos(current => current.filter(item => item.id !== photo.id));}}><Trash2 size={17}/></button></div>)}
                {photos.length < 3 && <button type="button" className="signal-add-photo" onClick={() => input.current?.click()}><ImagePlus size={26}/><span>{preparing ? 'Подготавливаем…' : 'Добавить фото'}</span></button>}</div>
              <input className="signal-file" ref={input} type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif" multiple onChange={event => void addPhotos(event.target.files)} aria-label="Фотографии с телефона"/>
              <label>Телефон или электронная почта <small>необязательно</small><input maxLength={200} placeholder="Для уточнения обращения" value={form.contact} onChange={event => setForm(current => ({...current, contact: event.target.value}))}/></label>
              <p className="signal-contact-rule"><ShieldCheck size={16}/>Контакты видны только администратору организации, на стене их не будет.</p>
              <p className="signal-contact-rule">Описание и фотографии появятся на стене города. Не добавляйте в них личные данные.</p>
              <label className="citizen-honeypot" aria-hidden="true">Сайт<input tabIndex={-1} autoComplete="off" value={form.website} onChange={event => setForm(current => ({...current, website: event.target.value}))}/></label>
            </fieldset>
            <div className="citizen-submit"><button className="citizen-primary" disabled={busy || preparing || reloading || !photos.length || (!pending && (!located || !validRecipient(form, catalog)))}>{busy ? 'Отправляем…' : pending ? 'Проверить отправку' : 'Отправить обращение'}<ArrowRight size={18}/></button></div>
          </>}
          {error && <p className="citizen-error" role="alert">{error}</p>}
        </form>
      </>}
    </main>
    <nav className="signal-bottom-nav" aria-label="Навигация Сигнала"><button aria-current={tab === 'wall' ? 'page' : undefined} onClick={() => setTab('wall')}><List size={23}/><span>Стена города</span></button>
      <button aria-current={tab === 'create' ? 'page' : undefined} onClick={newAppeal} disabled={locked}><Plus size={23}/><span>Сообщить о проблеме</span></button></nav>
  </div><UpdateNotice citizen beforeUpdate={prepareUpdate} disabled={busy || preparing}/></div>;
}
