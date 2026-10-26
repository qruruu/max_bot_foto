import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { ArrowRight, Camera, Check, CheckCircle2, Leaf, LoaderCircle, MapPin, Trash2, WifiOff } from 'lucide-react';
import CitizenCamera from './LiveCamera';
import PhotoPreview from './PhotoPreview';
import { MAX_PHOTOS, serverNow } from './camera';
import type { CameraPhoto, CaptureSession } from './camera';
import { AppealRequestError, publicRequest } from './requests';
import { clearDraft, EMPTY_FORM, hasDraftContent, loadDraft, saveDraft } from './drafts';
import type { AppealDraft, ResumeSession } from './drafts';
import useOverlayHistory from './useOverlayHistory';
import { recipientFor, validRecipient } from './catalog';
import type { AppealCatalog } from './catalog';
import './citizen.css';

const TerritoryMap = lazy(() => import('./TerritoryMap'));
export default function CitizenAppeal() {
  const [catalog, setCatalog] = useState<AppealCatalog | null>(null), [catalogError, setCatalogError] = useState('');
  const [catalogRevision, setCatalogRevision] = useState(0);
  const [form, setForm] = useState(EMPTY_FORM), [photos, setPhotos] = useState<CameraPhoto[]>([]);
  const [session, setSession] = useState<CaptureSession | null>(null), [cameraOpen, setCameraOpen] = useState(false);
  const [busy, setBusy] = useState(false), [preparing, setPreparing] = useState(false), [error, setError] = useState('');
  const [receipt, setReceipt] = useState('');
  const [preview, setPreview] = useState<CameraPhoto | null>(null);
  useOverlayHistory(cameraOpen || !!preview, () => {setCameraOpen(false); setPreview(null);});
  const [loaded, setLoaded] = useState(false), [restored, setRestored] = useState(false), [pending, setPending] = useState(false);
  const [storageError, setStorageError] = useState(false), [offline, setOffline] = useState(!navigator.onLine);
  const photoRef = useRef(photos), sessionRef = useRef(session), tokenRef = useRef<string | null>(null), receiptRef = useRef('');
  const requestActive = useRef(false), mounted = useRef(true), writes = useRef<Promise<void>>(Promise.resolve());
  const snapshot = useRef<AppealDraft>({form, photos: [], token: null, pending: false, savedAt: Date.now()});
  const cities = useMemo(() => [...new Set(catalog?.organizations.map(item => item.city))].sort((a, b) => a.localeCompare(b, 'ru')), [catalog]);
  const cityOrganizations = useMemo(() => catalog?.organizations.filter(item => item.city === form.city) || [], [catalog, form.city]);
  const recipient = recipientFor(form, catalog);
  photoRef.current = photos; sessionRef.current = session;
  snapshot.current = {form, photos: photos.map(({id, blob, preview, capture}) => ({id, blob, preview, capture})),
    token: tokenRef.current, pending, savedAt: Date.now()};

  function persist(draft = snapshot.current) {
    writes.current = writes.current.catch(() => {}).then(async () => {
      if (receiptRef.current && !draft.receipt) return;
      if (draft.receipt || hasDraftContent(draft.form, draft.photos, draft.pending)) await saveDraft(draft);
      else await clearDraft();
    }).catch(() => {if (mounted.current) setStorageError(true);});
    return writes.current;
  }
  function complete(number: string) {
    receiptRef.current = number;
    void persist({form: EMPTY_FORM, photos: [], token: null, pending: false, receipt: number, savedAt: Date.now()});
    if (!mounted.current) return;
    setReceipt(number); setPending(false); setError(''); setForm(EMPTY_FORM); setSession(null); tokenRef.current = null;
    photoRef.current.forEach(photo => URL.revokeObjectURL(photo.url)); setPhotos([]);
  }
  useEffect(() => {
    let active = true;
    setCatalogError('');
    publicRequest<AppealCatalog>('/catalog', {method: 'GET'}).then(value => {if (active) setCatalog(value);})
      .catch(failure => {if (active) setCatalogError(failure.message);});
    return () => {active = false;};
  }, [catalogRevision]);
  useEffect(() => {
    mounted.current = true;
    let active = true;
    loadDraft().then(draft => {
      if (!active || !draft) return;
      if (draft.receipt) {receiptRef.current = draft.receipt; setReceipt(draft.receipt); return;}
      setForm({...EMPTY_FORM, ...draft.form}); setPhotos(draft.photos.map(photo => ({...photo, url: URL.createObjectURL(photo.preview)})));
      tokenRef.current = draft.token; setPending(draft.pending); setRestored(true);
    }).catch(() => {if (active) setStorageError(true);}).finally(() => {if (active) setLoaded(true);});
    return () => {active = false; mounted.current = false; photoRef.current.forEach(photo => URL.revokeObjectURL(photo.url));};
  }, []);
  useEffect(() => {
    if (!loaded || receipt) return;
    const timer = window.setTimeout(() => void persist(), 350);
    const hidden = () => {if (document.hidden) void persist();};
    document.addEventListener('visibilitychange', hidden);
    window.addEventListener('pagehide', hidden);
    return () => {window.clearTimeout(timer); document.removeEventListener('visibilitychange', hidden); window.removeEventListener('pagehide', hidden);};
  }, [loaded, form, photos, session, pending, receipt]);
  useEffect(() => {
    const online = () => setOffline(!navigator.onLine);
    window.addEventListener('online', online); window.addEventListener('offline', online);
    return () => {window.removeEventListener('online', online); window.removeEventListener('offline', online);};
  }, []);
  useEffect(() => {
    const handle = (event: BeforeUnloadEvent) => {if (!receiptRef.current && (photoRef.current.length || form.description)) {event.preventDefault(); event.returnValue = '';}};
    window.addEventListener('beforeunload', handle); return () => window.removeEventListener('beforeunload', handle);
  }, [form.description, receipt]);

  function removePhoto(id: string) {
    setPhotos(current => {const removed = current.find(photo => photo.id === id); if (removed) URL.revokeObjectURL(removed.url); return current.filter(photo => photo.id !== id);});
  }
  async function resumeSession(): Promise<ResumeSession | null> {
    if (!tokenRef.current) return null;
    const resumed = await publicRequest<ResumeSession>('/capture-sessions/resume', {method: 'POST', headers: {'X-Capture-Token': tokenRef.current}});
    if (resumed.submitted) {complete(resumed.submitted.number); return resumed;}
    const current = {...resumed, receivedAt: performance.now()}; sessionRef.current = current; setSession(current);
    return resumed;
  }
  async function openCamera() {
    if (requestActive.current || pending) return;
    requestActive.current = true;
    setPreparing(true); setError('');
    try {
      let current = sessionRef.current;
      if (tokenRef.current) {
        try {
          const resumed = await resumeSession();
          if (resumed?.submitted) return;
          current = sessionRef.current;
        } catch (failure) {
          if (!(failure instanceof AppealRequestError) || failure.status !== 409) throw failure;
          tokenRef.current = null; sessionRef.current = null; setSession(null);
        }
      }
      if (!current || serverNow(current) >= Date.parse(current.expires_at) - 30_000) {
        const created = await publicRequest<Omit<CaptureSession, 'receivedAt'>>('/capture-sessions', {method: 'POST'});
        if (photos.length) {
          photos.forEach(photo => URL.revokeObjectURL(photo.url)); setPhotos([]);
          setError('Время предыдущей съёмки истекло. Снимки нужно сделать заново; анкета сохранена.');
        }
        current = {...created, receivedAt: performance.now()}; setSession(current); sessionRef.current = current; tokenRef.current = current.token;
      }
      setCameraOpen(true);
    } catch (error) {setError((error as Error).message);}
    finally {requestActive.current = false; if (mounted.current) setPreparing(false);}
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); setError('');
    if (requestActive.current) return;
    if (!photos.length || !tokenRef.current) {setError('Сделайте хотя бы один снимок через камеру.'); return;}
    requestActive.current = true;
    setBusy(true);
    let attempted = false;
    try {
      const resumed = await resumeSession();
      if (resumed?.submitted) return;
      if (resumed?.expired) {setPending(false); throw new AppealRequestError('Время съёмки истекло. Сделайте новые снимки; анкета сохранена.', 409);}
      if (!pending && !validRecipient(form, catalog)) throw new AppealRequestError('Выберите разрешённый город, организацию и её вид работ из списка.', 422);
      const data = new FormData();
      data.append('metadata', JSON.stringify({...form, capture_source: 'camera', captures: photos.map(photo => photo.capture)}));
      photos.forEach((photo, index) => data.append('photos', photo.blob, `camera-${index + 1}.jpg`));
      setPending(true);
      await persist({...snapshot.current, token: tokenRef.current, pending: true});
      attempted = true;
      const result = await publicRequest<{number: string}>('', {method: 'POST', headers: {'X-Capture-Token': tokenRef.current!}, body: data}, 120_000);
      complete(result.number);
    } catch (failure) {
      if (failure instanceof AppealRequestError && !failure.uncertain) setPending(false);
      else if (attempted) setPending(true);
      if (failure instanceof AppealRequestError && failure.status === 422) setCatalogRevision(value => value + 1);
      setError((failure as Error).message);
    } finally {requestActive.current = false; if (mounted.current) setBusy(false);}
  }
  const field = (key: keyof typeof EMPTY_FORM) => ({value: form[key], onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setForm(current => ({...current, [key]: event.target.value}))});
  function chooseOrganization(id: string) {
    const selected = cityOrganizations.find(item => item.id === id);
    if (selected && !locked) setForm(current => ({...current, organization_id: id,
      category: current.organization_id === id ? current.category : ''}));
  }
  const locked = busy || preparing || pending;
  if (!loaded) return <div className="citizen-app citizen-restoring" role="status">Открываем форму…</div>;

  return <div className="citizen-app"><div inert={cameraOpen || !!preview}>
    <header className="citizen-header"><a href="/appeals" className="citizen-brand"><span><Leaf size={23}/></span>Город рядом</a><span className="citizen-header-caption">Обращения жителей</span></header>
    {receipt ? <main className="citizen-success"><span className="citizen-success-mark"><CheckCircle2 size={42}/></span>
      <span className="citizen-kicker">СПАСИБО ЗА УЧАСТИЕ</span><h1>Ваше обращение получено</h1>
      <p>Описание и фотографии переданы администраторам выбранной организации.</p>
      <div className="citizen-receipt"><small>Номер обращения</small><strong>{receipt}</strong><span>Сохраните его для уточнений</span></div>
      <button className="citizen-primary" onClick={() => {receiptRef.current = ''; setReceipt(''); setRestored(false);}}>Сообщить о другой проблеме<ArrowRight size={18}/></button>
    </main> : <main className="citizen-main">
      <div className="citizen-intro"><span className="citizen-kicker">ПОМОЖЕМ ГОРОДУ ВМЕСТЕ</span><h1>Заметили проблему?<br/><span>Покажите её нам.</span></h1>
        <p>Выберите город и организацию, которая обслуживает территорию. Расскажите о нарушении и сделайте фото на месте.</p>
        <div className="citizen-steps"><span><i>1</i>Место и описание</span><span><i>2</i>Фото с камеры</span><span><i>3</i>Отправка</span></div>
        <aside className="citizen-aside"><MapPin size={22}/><div><strong>Координаты определятся сами</strong><p>Вручную отмечать место на карте не нужно. При съёмке разрешите доступ к камере и геолокации.</p></div></aside>
      </div>
      <form className="citizen-form" onSubmit={event => void submit(event)}>
        {offline && <p className="citizen-notice" role="status"><WifiOff size={18}/>Нет связи с интернетом. Продолжайте заполнять анкету — отправить её можно после подключения.</p>}
        {restored && <p className="citizen-notice" role="status">{photos.length ? 'Восстановили ваш черновик вместе со снимками.' : 'Восстановили ваш черновик.'}</p>}
        {storageError && <p className="citizen-notice" role="status">Браузер не разрешает сохранить черновик на устройстве. До отправки не закрывайте эту вкладку.</p>}
        {pending && <p className="citizen-notice" role="status">Проверяем, получено ли обращение. Анкета зафиксирована, чтобы повторная попытка не создала дубль. Нажмите «Проверить отправку».</p>}
        {catalogError && <div className="citizen-notice" role="status"><p>{catalogError}</p><button type="button" disabled={locked} onClick={() => setCatalogRevision(value => value + 1)}>Обновить список организаций</button></div>}
        {!catalog && !catalogError && <p className="citizen-help" role="status">Загружаем города и организации…</p>}
        {catalog && !catalog.organizations.length && <p className="citizen-notice" role="status">Пока нет организаций, готовых принимать обращения. Попробуйте позже.</p>}
        <fieldset disabled={locked}><div className="citizen-section-heading"><span>01</span><div><h2>Где и что произошло</h2><p>Обращение получат администраторы выбранной организации.</p></div></div>
          <div className="citizen-fields"><label className="citizen-wide">Город<select required autoComplete="address-level2" value={form.city} onChange={event => setForm(current => ({...current, city: event.target.value, organization_id: '', category: ''}))}>
            <option value="">Выберите город</option>{form.city && !cities.includes(form.city) && <option value={form.city} disabled>{form.city} — недоступен</option>}{cities.map(city => <option key={city} value={city}>{city}</option>)}
          </select></label>
          </div>
          {cityOrganizations.length > 0 && <Suspense fallback={<p className="citizen-help">Открываем территории…</p>}><TerritoryMap key={form.city} organizations={cityOrganizations} selected={form.organization_id}
            apiKey={catalog?.yandex_maps_api_key || ''} disabled={locked} onChoose={chooseOrganization}/></Suspense>}
          <div className="citizen-fields">
            <label className="citizen-wide">Организация<select required value={form.organization_id} disabled={!form.city || !cityOrganizations.length} onChange={event => chooseOrganization(event.target.value)}>
              <option value="">Выберите организацию</option>{form.organization_id && !recipient && <option value={form.organization_id} disabled>Ранее выбранная организация недоступна</option>}
              {cityOrganizations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <label className="citizen-wide">Вид работ<select required {...field('category')} disabled={!recipient}>
              <option value="">Выберите вид работ</option>{form.category && !recipient?.work_types.some(work => work.code === form.category) && <option value={form.category} disabled>Ранее выбранный вид работ недоступен</option>}
              {recipient?.work_types.map(work => <option key={work.code} value={work.code}>{work.name}</option>)}</select></label>
            <label className="citizen-wide">Улица и дом<input required minLength={5} maxLength={300} autoComplete="street-address" placeholder="Улица, номер дома или ближайший адрес" {...field('address')}/></label>
            <label className="citizen-wide">Где именно<input required minLength={2} maxLength={300} placeholder="Например, тротуар у второго подъезда" {...field('place')}/></label>
            <label className="citizen-wide">Описание<textarea required minLength={10} maxLength={4000} rows={4} placeholder="Что не так и что нужно исправить?" {...field('description')}/></label>
          </div>
        </fieldset>
        <fieldset disabled={locked}><div className="citizen-section-heading"><span>02</span><div><h2>Фотографии с места</h2><p>Нужен хотя бы один новый снимок. Можно сделать до трёх.</p></div></div>
          <div className="citizen-photo-grid">{photos.map((photo, index) => <article className="citizen-photo" key={photo.id}><button type="button" className="citizen-photo-preview" onClick={() => setPreview(photo)} aria-label={`Посмотреть снимок ${index + 1}`}><img src={photo.url} alt={`Снимок проблемы ${index + 1}`}/></button>
            <button type="button" onClick={() => removePhoto(photo.id)} aria-label={`Удалить снимок ${index + 1}`}><Trash2 size={17}/></button><span><Check size={14}/>Снято сейчас</span></article>)}
            {photos.length < MAX_PHOTOS && <button type="button" className="citizen-add-photo" disabled={!validRecipient(form, catalog)} onClick={() => void openCamera()}><Camera size={28}/><strong>{preparing ? 'Включаем…' : photos.length ? 'Ещё снимок' : 'Открыть камеру'}</strong><span>Дата и координаты — автоматически</span></button>}
          </div><p className="citizen-help">Снимите общий план, чтобы было понятно место, и при необходимости — проблему крупнее.</p>
        </fieldset>
        <fieldset disabled={locked}><div className="citizen-section-heading"><span>03</span><div><h2>Как с вами связаться</h2><p>Необязательно. Только если потребуется уточнение.</p></div></div>
          <label>Телефон или электронная почта<input maxLength={200} placeholder="Контакт для обратной связи" {...field('contact')}/></label>
          <label className="citizen-honeypot" aria-hidden="true">Сайт<input tabIndex={-1} autoComplete="off" {...field('website')}/></label>
        </fieldset>
        {error && <p className="citizen-error" role="alert">{error}</p>}
        <div className="citizen-submit"><p>Обращение и фотографии получат администраторы выбранной организации. Они также доступны владельцу сервиса и не публикуются на сайте. Черновик хранится в этом браузере до суток и очищается после отправки.</p>
          <button className="citizen-primary" disabled={busy || preparing || !photos.length || (!pending && !validRecipient(form, catalog))}>{busy ? <><LoaderCircle className="citizen-spinner" size={18}/>Проверяем и отправляем…</>
            : <>{pending ? 'Проверить отправку' : 'Отправить обращение'}<ArrowRight size={18}/></>}</button></div>
      </form>
    </main>}
    <footer className="citizen-footer">Забота о городе начинается с внимания.</footer></div>
    {preview && <PhotoPreview photo={preview} onClose={() => setPreview(null)} onRetake={() => {removePhoto(preview.id); setPreview(null); void openCamera();}}/>}
    {cameraOpen && session && <CitizenCamera session={session} onResume={async () => {
      const resumed = await resumeSession();
      if (resumed?.submitted) return null;
      if (resumed?.expired) throw new AppealRequestError('Время съёмки истекло. Закройте камеру и сделайте новые снимки; анкета сохранена.', 409);
      return sessionRef.current;
    }} onClose={() => setCameraOpen(false)} onCapture={photo => {setPhotos(current => [...current, photo]); setCameraOpen(false);}}/>}
  </div>;
}
