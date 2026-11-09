import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import { X } from 'lucide-react';
import TaskImageInput, { MAX_PHOTOS, pastedImages } from './TaskImageInput';
import { galleryPhoto } from './gallery';
import type { PublicOrganization } from './catalog';
import './signal.css';

const ProblemMap = lazy(() => import('./ProblemMap'));

type Operator = {id: number; name: string};

export default function AdminTaskForm({endpoint, onClose, onCreated}: {
  endpoint: string;
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const [operators, setOperators] = useState<Operator[] | null>(null);
  const [catalog, setCatalog] = useState<{organization: PublicOrganization; yandex_maps_api_key: string} | null>(null);
  const [addressId, setAddressId] = useState('');
  const [point, setPoint] = useState<[number, number] | null>(null);
  const [place, setPlace] = useState('');
  const [category, setCategory] = useState('');
  const address = catalog?.organization.addresses?.find(item => item.id === addressId);
  const [subject, setSubject] = useState('');
  const [description, setDescription] = useState('');
  const [operatorId, setOperatorId] = useState('');
  const [documents, setDocuments] = useState<File[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [dueDate, setDueDate] = useState('');
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  const clientId = useRef(crypto.randomUUID());

  useEffect(() => {
    const abort = new AbortController();
    Promise.all([
      api<Operator[]>(endpoint + '/options', 'GET', undefined, abort.signal),
      api<NonNullable<typeof catalog>>(endpoint + '/location', 'GET', undefined, abort.signal),
    ]).then(([items, location]) => {
      if (!abort.signal.aborted) {setOperators(items); setCatalog(location);}
    })
      .catch(reason => {if (!abort.signal.aborted) setError(reason.message);});
    return () => abort.abort();
  }, [endpoint, retry]);

  function updateFiles(next: File[]) {
    if (next.length > MAX_PHOTOS) {
      setError(`Можно приложить до ${MAX_PHOTOS} фото или скриншотов`);
      return;
    }
    setError('');
    setFiles(next);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sending.current || !subject.trim() || !description.trim() || !operatorId || (address && !point)) return;
    sending.current = true;
    setBusy(true);
    setError('');
    try {
      const body = new FormData();
      body.append('metadata', JSON.stringify({
        client_id: clientId.current,
        subject: subject.trim(),
        description: description.trim(),
        operator_id: Number(operatorId),
        due_date: dueDate || null,
        address_id: address?.id || null,
        address: address?.label || '',
        latitude: point?.[1] ?? null,
        longitude: point?.[0] ?? null,
        place: place.trim(),
        category,
      }));
      for (const file of files) {
        const {blob} = await galleryPhoto(file);
        body.append('photos', blob, file.name);
      }
      documents.forEach(file => body.append('documents', file));
      const task = await api<{id: number}>(endpoint, 'POST', body);
      onCreated(task.id);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  return <form className="panel owner-appeal-edit admin-task-form" onSubmit={event => void submit(event)}>
    <header className="section-title"><h2>Новая задача</h2>
      <button type="button" aria-label="Закрыть форму" disabled={busy} onClick={onClose}><X size={18}/></button>
    </header>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="admin-task-fields">
    <fieldset disabled={busy}>
      <label>Исполнитель<select required value={operatorId} disabled={!operators?.length} onChange={event => setOperatorId(event.target.value)}>
        <option value="">{operators ? 'Выберите оператора' : 'Загружаем операторов…'}</option>
        {operators?.map(operator => <option key={operator.id} value={operator.id}>{operator.name}</option>)}
      </select></label>
      <label>Территория (необязательно)<select value={addressId} onChange={event => {setAddressId(event.target.value); setPoint(null);}}>
        <option value="">Без территории</option>
        {catalog?.organization.addresses?.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>
      {catalog && address && <Suspense fallback={<p>Загружаем карту…</p>}>
        <ProblemMap organization={catalog.organization} districtId={address.district_id} apiKey={catalog.yandex_maps_api_key}
          point={point} disabled={busy} onPoint={setPoint}/>
      </Suspense>}
    </fieldset>
    <fieldset disabled={busy}>
      <label>Вид работ (необязательно)<select value={category} onChange={event => setCategory(event.target.value)}>
        <option value="">Без вида работ</option>
        {catalog?.organization.work_types.map(work => <option key={work.code} value={work.code}>{work.name}</option>)}
      </select></label>
      <label>Срок задачи (необязательно)<input type="date" value={dueDate} onChange={event => setDueDate(event.target.value)}/></label>
      <label>Название<input required maxLength={80} value={subject} onChange={event => setSubject(event.target.value)}/></label>
      <label>Описание задачи<textarea required rows={4} maxLength={4000} value={description}
        onPaste={event => {const images = pastedImages(event); if (images.length) updateFiles([...files, ...images]);}} onChange={event => setDescription(event.target.value)}/></label>
      <label>Уточнение места (необязательно)<input value={place} maxLength={300} onChange={event => setPlace(event.target.value)}/></label>
      <TaskImageInput disabled={busy} files={files} onChange={updateFiles}/>
      <label>Документы <small>до 5 файлов Word, Excel или PDF по 25 МБ</small>
        <input type="file" accept=".doc,.docx,.xls,.xlsx,.pdf" multiple onChange={event => {
          const added = [...(event.target.files || [])];
          event.target.value = '';
          if (added.length + documents.length > 5 || added.some(file => file.size > 25 * 1024 * 1024)) {
            setError('Можно приложить до пяти документов по 25 МБ'); return;
          }
          setError(''); setDocuments(current => [...current, ...added]);
        }}/>
      </label>
      {documents.map((file, index) => <p key={index}>{file.name} <button type="button" aria-label={'Удалить ' + file.name}
        onClick={() => setDocuments(current => current.filter((_, item) => item !== index))}><X size={16}/></button></p>)}
    </fieldset>
    </div>
    {operators?.length === 0 && <p className="hint">В организации нет активных операторов для назначения.</p>}
    <footer>
      <button type="button" disabled={busy} onClick={onClose}>Отмена</button>
      {!operators && error && <button type="button" onClick={() => {setError(''); setRetry(value => value + 1);}}>Повторить загрузку</button>}
      <button className="primary" type="submit" disabled={busy || !operatorId || !subject.trim() || !description.trim() || (!!address && !point)}>
        {busy ? 'Назначаем…' : 'Назначить задачу'}
      </button>
    </footer>
  </form>;
}
