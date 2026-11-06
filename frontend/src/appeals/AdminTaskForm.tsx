import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import TaskImageInput, { MAX_PHOTOS, pastedImages } from './TaskImageInput';
import { galleryPhoto } from './gallery';

type Operator = {id: number; name: string};

export default function AdminTaskForm({endpoint, onClose, onCreated}: {
  endpoint: string;
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const [operators, setOperators] = useState<Operator[] | null>(null);
  const [subject, setSubject] = useState('');
  const [description, setDescription] = useState('');
  const [operatorId, setOperatorId] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [dueDate, setDueDate] = useState('');
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  const clientId = useRef(crypto.randomUUID());

  useEffect(() => {
    const abort = new AbortController();
    api<Operator[]>(endpoint + '/options', 'GET', undefined, abort.signal)
      .then(items => {if (!abort.signal.aborted) setOperators(items);})
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
    if (sending.current || !subject.trim() || !description.trim() || !operatorId) return;
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
      }));
      for (const file of files) {
        const {blob} = await galleryPhoto(file);
        body.append('photos', blob, file.name);
      }
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
    <h3>Новая задача</h3>
    <p className="hint">Задача появится в кабинете выбранного оператора и останется внутри «Метки».</p>
    {error && <p className="error" role="alert">{error}</p>}
    <fieldset disabled={busy}>
      <label>Название<input required maxLength={80} value={subject} onChange={event => setSubject(event.target.value)}/></label>
      <label>Описание<textarea required rows={4} maxLength={4000} value={description}
        onPaste={event => {const images = pastedImages(event); if (images.length) updateFiles([...files, ...images]);}} onChange={event => setDescription(event.target.value)}/></label>
      <div className="appeal-edit-fields">
        <label>Исполнитель<select required value={operatorId} disabled={!operators?.length} onChange={event => setOperatorId(event.target.value)}>
          <option value="">{operators ? 'Выберите оператора' : 'Загружаем операторов…'}</option>
          {operators?.map(operator => <option key={operator.id} value={operator.id}>{operator.name}</option>)}
        </select></label>
        <label>Срок (необязательно)<input type="date" value={dueDate} onChange={event => setDueDate(event.target.value)}/></label>
      </div>
      <TaskImageInput disabled={busy} files={files} onChange={updateFiles}/>
    </fieldset>
    {operators?.length === 0 && <p className="hint">В организации нет активных операторов для назначения.</p>}
    <footer>
      <button type="button" disabled={busy} onClick={onClose}>Отмена</button>
      {!operators && error && <button type="button" onClick={() => {setError(''); setRetry(value => value + 1);}}>Повторить загрузку</button>}
      <button className="primary" type="submit" disabled={busy || !operatorId || !subject.trim() || !description.trim()}>
        {busy ? 'Назначаем…' : 'Назначить задачу'}
      </button>
    </footer>
  </form>;
}
