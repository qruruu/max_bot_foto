import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { appealDecisions, appealStatuses, isFinalAppeal } from './statuses';
import { galleryPhoto } from './gallery';
import TaskImageInput, { pastedImages } from './TaskImageInput';

export type ResultPhoto = {id: string; url: string; preview_url: string};
export type AppealTask = {id: number; operator_id: number; operator_name: string; instruction?: string;
  status: string; result_comment: string; photos: ResultPhoto[]; created_at: string; due_date?: string | null; finished_at?: string | null};
export type TaskRelation = {id: number; number: string; subject: string; status: string; is_final: boolean; operator_name: string; due_date: string | null; result: string; operator_result: string};
export type WorkflowAppeal = {id: number; status: string; version: number; can_manage?: boolean; can_execute?: boolean;
  is_public?: boolean; is_final?: boolean; resolved_at?: string | null; archived_at?: string | null; can_set_task_status?: boolean; cancelled_by_inspector?: boolean;
  submitted_by_inspector_name?: string; inspector_due_date?: string | null; parent_id?: number | null;
  can_set_inspector_deadline?: boolean; files?: {id: string; name: string; url: string}[];
  parent?: TaskRelation | null; children?: TaskRelation[];
  task?: AppealTask | null; task_history?: AppealTask[]; public_response?: string; response_photos?: ResultPhoto[]};

export default function AppealActions({appeal, endpoint, readOnly, changed}: {
  appeal: WorkflowAppeal; endpoint: string; readOnly: boolean; changed: () => void;
}) {
  const [operators, setOperators] = useState<{id: number; name: string}[] | null>(null);
  const [operator, setOperator] = useState(''), [subtaskOperator, setSubtaskOperator] = useState('');
  const [instruction, setInstruction] = useState(''), [result, setResult] = useState(appeal.status), [comment, setComment] = useState('');
  const [dueDate, setDueDate] = useState(appeal.task?.due_date || '');
  const [inspectorDueDate, setInspectorDueDate] = useState(appeal.inspector_due_date || '');
  const [subtaskTitle, setSubtaskTitle] = useState(''), [subtaskDescription, setSubtaskDescription] = useState('');
  const [subtaskDue, setSubtaskDue] = useState('');
  const subtaskClient = useRef(crypto.randomUUID());
  const [files, setFiles] = useState<File[]>([]), [answer, setAnswer] = useState(''), [selectedPhotos, setSelectedPhotos] = useState<string[]>([]);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [preparing, setPreparing] = useState(false), sending = useRef(false);
  const [confirmClose, setConfirmClose] = useState(false);
  const decisionTrigger = useRef<HTMLButtonElement>(null);
  const [decision, setDecision] = useState('RESOLVED');
  const decisionText = appealDecisions[decision];
  const decisionAction = decisionText.verb + (decision === 'RESOLVED' && appeal.is_public === false ? ' обращение' : '')
    + (appeal.is_public === false ? ' и сохранить ответ' : ' и опубликовать ответ');
  const manage = !readOnly && appeal.can_manage !== false && !appeal.can_execute;
  const execute = !readOnly && appeal.can_execute;
  const final = isFinalAppeal(appeal);
  const showArchive = manage && (final || appeal.cancelled_by_inspector);
  const activeTask = !appeal.archived_at && !final;
  const canAssign = manage && activeTask && !appeal.cancelled_by_inspector && !appeal.children?.length;
  const canSplit = manage && activeTask && !!appeal.submitted_by_inspector_name && !appeal.parent_id && !appeal.cancelled_by_inspector;
  const resultReady = !!appeal.task && ['COMPLETED', 'REJECTED', 'CANCELLED'].includes(appeal.task.status);
  useEffect(() => {
    if (!canAssign && !canSplit) return;
    const abort = new AbortController();
    api<{id: number; name: string}[]>(endpoint + '/' + appeal.id + '/operators', 'GET', undefined, abort.signal)
      .then(setOperators).catch(reason => {if (!abort.signal.aborted) setError(reason.message);});
    return () => abort.abort();
  }, [appeal.id, endpoint, canAssign, canSplit]);
  useEffect(() => setResult(appeal.status), [appeal.status]);
  useEffect(() => setDueDate(appeal.task?.due_date || ''), [appeal.task?.id, appeal.task?.due_date]);
  useEffect(() => setInspectorDueDate(appeal.inspector_due_date || ''), [appeal.inspector_due_date]);
  useEffect(() => setSelectedPhotos([]), [appeal.task?.id]);

  async function send(path: string, body?: unknown) {
    if (sending.current) return;
    sending.current = true;
    setBusy(true); setError('');
    try {
      if (body instanceof FormData && body.has('photos')) {
        setPreparing(true);
        const photos = body.getAll('photos'); body.delete('photos');
        for (const [index, file] of photos.entries()) {
          const {blob} = await galleryPhoto(file as File);
          body.append('photos', blob, blob.type === 'image/jpeg' ? `result-${index + 1}.jpg` : (file as File).name);
        }
        setPreparing(false);
      }
      await api(endpoint + '/' + appeal.id + path, 'POST', body);
      if (path === '/assign') {setOperator(''); setInstruction('');}
      if (path === '/subtasks') {
        setSubtaskOperator(''); setSubtaskTitle(''); setSubtaskDescription(''); setSubtaskDue('');
        subtaskClient.current = crypto.randomUUID();
      }
      if (path === '/result') {setComment(''); setFiles([]);}
      if (path === '/close') {setConfirmClose(false); setAnswer(''); setSelectedPhotos([]); setFiles([]);}
      window.dispatchEvent(new Event('appeals-changed'));
      changed();
    }
    catch (reason) {setError((reason as Error).message);}
    finally {sending.current = false; setPreparing(false); setBusy(false);}
  }
  function updateFiles(next: File[]) {
    if (next.length > 3) {
      setError('Можно приложить до трёх фото или скриншотов');
      return;
    }
    setError('');
    setFiles(next);
  }

  function upload(metadata: object) {
    const form = new FormData(); form.append('metadata', JSON.stringify({...metadata, expected_version: appeal.version}));
    files.forEach(file => form.append('photos', file)); return form;
  }
  const reportable = ['ASSIGNED', 'IN_PROGRESS'].includes(appeal.status);
  const assignment = canAssign && <details className="appeal-task appeal-assign" open={!appeal.task || undefined}>
      <summary>{appeal.task ? 'Сменить исполнителя' : 'Назначить исполнителя'}</summary>
        <label>Исполнитель<select value={operator} disabled={busy} onChange={event => setOperator(event.target.value)}><option value="">Выберите исполнителя</option>{operators?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        {operators?.length === 0 && <p className="hint">Добавьте действующего оператора в этой организации.</p>}
        <details><summary>Добавить комментарий</summary><label>Комментарий исполнителю<textarea disabled={busy} value={instruction} maxLength={4000} onChange={event => setInstruction(event.target.value)} placeholder="Что нужно сделать исполнителю"/></label></details>

        <button type="button" className="primary" disabled={busy || !operator} onClick={() => void send('/assign', {operator_id: Number(operator), instruction, expected_version: appeal.version})}>Назначить</button>
    </details>;
  const tasks = <>
    {!!appeal.submitted_by_inspector_name && (readOnly || !!appeal.inspector_due_date || appeal.can_set_inspector_deadline) && <section className="appeal-task"><h3>{readOnly ? 'Срок задачи' : 'Срок от проверяющего'}</h3>
      <p>{appeal.inspector_due_date ? new Date(appeal.inspector_due_date + 'T00:00:00').toLocaleDateString('ru-RU') : 'Без срока'}</p>
      {appeal.can_set_inspector_deadline && !appeal.archived_at && !isFinalAppeal(appeal) && <details>
        <summary>Изменить срок</summary>
        <form onSubmit={event => {event.preventDefault(); void send('/deadline', {due_date: inspectorDueDate || null, expected_version: appeal.version});}}>
          <label>Выполнить до<input type="date" value={inspectorDueDate} onChange={event => setInspectorDueDate(event.target.value)} disabled={busy}/></label>
          <button disabled={busy || inspectorDueDate === (appeal.inspector_due_date || '')}>Сохранить срок</button>
        </form>
      </details>}
    </section>}
    {appeal.task && !readOnly && <section className="appeal-task"><h3>{execute ? 'Назначение' : 'Исполнитель'}</h3>
      {!execute && <p>{appeal.task.operator_name}</p>}
      <p className="appeal-task-deadline">Срок исполнения: <strong>{appeal.task.due_date ? new Date(appeal.task.due_date + 'T00:00:00').toLocaleDateString('ru-RU') : 'Не установлен'}</strong></p>
      {manage && !appeal.archived_at && !isFinalAppeal(appeal) && reportable && ['ASSIGNED', 'IN_PROGRESS'].includes(appeal.task.status) && <details><summary>Изменить срок</summary><form className="appeal-deadline-form" onSubmit={event => {event.preventDefault(); void send('/deadline', {due_date: dueDate || null, expected_version: appeal.version});}}>
        <label>Срок исполнения<input type="date" max={appeal.inspector_due_date || undefined} value={dueDate} disabled={busy} onChange={event => setDueDate(event.target.value)}/></label>

        <button className="primary" disabled={busy || dueDate === (appeal.task.due_date || '')}>Сохранить срок</button>
        {dueDate && <button type="button" disabled={busy} onClick={() => setDueDate('')}>Убрать дату</button>}
      </form></details>}
      {appeal.task.instruction && <><strong>Комментарий к задаче</strong><p className="owner-appeal-text">{appeal.task.instruction}</p></>}
      {appeal.task.result_comment && <><h4>Результат исполнителя</h4><p className="owner-appeal-text">{appeal.task.result_comment}</p></>}
      <div className="appeal-evidence">{appeal.task.photos.map(photo => <a key={photo.id} href={photo.url} target="_blank" rel="noreferrer"><img src={photo.preview_url} alt="Фото результата исполнителя"/></a>)}</div>
    </section>}
    {appeal.can_set_task_status && !appeal.archived_at && !isFinalAppeal(appeal) && <details className="appeal-task"><summary>Изменить статус</summary>
      <label>Статус<select disabled={busy} value={result} onChange={event => setResult(event.target.value)}>
        {!['COMPLETED', 'CANCELLED'].includes(appeal.status) && <option value={appeal.status} disabled>{appealStatuses[appeal.status]}</option>}
        <option value="COMPLETED">Выполнена</option><option value="CANCELLED">Отменена</option>
      </select></label><button className="primary" disabled={busy || result === appeal.status} onClick={() => void send('/task-status', {status: result, expected_version: appeal.version})}>{busy ? 'Сохраняем…' : 'Сохранить статус задачи'}</button>
    </details>}
    {execute && reportable && activeTask && <section className="appeal-task"><h3>Действия исполнителя</h3>
      <div className="appeal-next-actions">
        {appeal.status === 'ASSIGNED' && <button className="primary" type="button" disabled={busy} onClick={() => void send('/task-status', {status: 'IN_PROGRESS', expected_version: appeal.version})}>Взять в работу</button>}
        {['ASSIGNED', 'IN_PROGRESS'].includes(result) && <button type="button" disabled={busy} onClick={() => setResult('COMPLETED')}>Подготовить отчёт</button>}
      </div>
      <label>Состояние задачи<select disabled={busy} value={result} onChange={event => setResult(event.target.value)}><option value="ASSIGNED">Назначена</option><option value="IN_PROGRESS">В работе</option><option value="CANCELLED">Отменена</option><option value="COMPLETED">Выполнена</option></select></label>
      {['ASSIGNED', 'IN_PROGRESS'].includes(result) ? <button className="primary" disabled={busy || result === appeal.status} onClick={() => void send('/task-status', {status: result, expected_version: appeal.version})}>Сохранить статус задачи</button> : <>
        <label>Комментарий<textarea disabled={busy} value={comment} maxLength={4000} onPaste={event => {const images = pastedImages(event); if (images.length) updateFiles([...files, ...images]);}} onChange={event => setComment(event.target.value)} placeholder="Что сделано или почему задача отменена"/></label>
        <TaskImageInput disabled={busy} files={files} onChange={updateFiles}/>
        <button className="primary" disabled={busy || !comment.trim() || !files.length || files.length > 3} onClick={() => void send('/result', upload({status: result, comment}))}>{preparing ? 'Подготавливаем фото…' : busy ? 'Отправляем…' : 'Передать результат администратору'}</button>
      </>}
    </section>}
  </>;
  return <div className="appeal-workflow">
    {showArchive && <div className="appeal-archive-action">
      {appeal.cancelled_by_inspector && !final && <p>Проверяющий отменил задачу.</p>}
      <button type="button" disabled={busy} onClick={() => void send('/archive', {archived: !appeal.archived_at, expected_version: appeal.version})}>
        {appeal.archived_at ? 'Вернуть из архива' : 'Перенести в архив'}
      </button>
      {appeal.status === 'SPAM' && !appeal.archived_at && <p className="hint">На стене «Сигнала» он не появится.</p>}
    </div>}
    {!appeal.task && assignment}
    {tasks}
    {manage && activeTask && <details className="appeal-task appeal-close-form">
      <summary>{resultReady ? 'Рассмотреть результат' : appeal.is_public === false ? 'Закрыть задачу' : 'Закрыть обращение'}</summary>
        <label>Итог<select value={decision} disabled={busy} onChange={event => setDecision(event.target.value)}>{Object.entries(appealDecisions).map(([value, text]) => <option value={value} key={value}>{text.label}</option>)}</select></label>
        <p className="hint">{appeal.is_public === false ? 'Ответ останется внутри «Метки». Фотографии необязательны.' : 'Ответ появится на стене города. Фотографии необязательны.'}</p>
        <label>{appeal.is_public === false ? 'Ответ организации' : 'Публичный ответ организации'}<textarea value={answer} disabled={busy} maxLength={4000} onPaste={event => {const images = pastedImages(event); if (images.length) updateFiles([...files, ...images]);}} onChange={event => setAnswer(event.target.value)} placeholder="Результат рассмотрения обращения"/></label>
        {resultReady && appeal.task && appeal.task.photos.length > 0 && <div className="appeal-result-selection"><strong>Приложить фото исполнителя</strong>{appeal.task.photos.map(photo => <label key={photo.id}>
          <input type="checkbox" checked={selectedPhotos.includes(photo.id)} disabled={busy} onChange={event => setSelectedPhotos(current => event.target.checked ? [...current, photo.id] : current.filter(id => id !== photo.id))}/><img src={photo.preview_url} alt="Выбрать фотографию результата"/></label>)}</div>}
        <TaskImageInput disabled={busy} files={files} onChange={updateFiles}/>
        {!!appeal.children?.some(child => !child.is_final) && <p className="hint">При закрытии незавершённые подзадачи будут закрыты вместе с родительской задачей.</p>}
        <button className="primary" disabled={busy || !answer.trim() || selectedPhotos.length + files.length > 3}
          ref={decisionTrigger} onClick={() => {setError(''); setConfirmClose(true);}}>{decisionAction}</button>
    </details>}
    {!!appeal.task && assignment}
    {canSplit && <details className="appeal-task"><summary>Разделить на подзадачи</summary><p className="hint">Каждая подзадача назначается отдельно. Итоговый ответ сохраните после завершения всех подзадач. Прямое назначение родительской задачи будет отменено.</p>
      <label>Тема<input maxLength={80} value={subtaskTitle} disabled={busy} onChange={event => setSubtaskTitle(event.target.value)}/></label>
      <label>Что нужно сделать<textarea maxLength={4000} value={subtaskDescription} disabled={busy} onChange={event => setSubtaskDescription(event.target.value)}/></label>
      <label>Исполнитель<select value={subtaskOperator} disabled={busy} onChange={event => setSubtaskOperator(event.target.value)}><option value="">Выберите оператора</option>{operators?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>Срок подзадачи<input type="date" max={appeal.inspector_due_date || undefined} value={subtaskDue} disabled={busy} onChange={event => setSubtaskDue(event.target.value)}/></label>
      <button className="primary" disabled={busy || !subtaskOperator || !subtaskTitle.trim() || !subtaskDescription.trim()} onClick={() => void send('/subtasks', {subject: subtaskTitle, description: subtaskDescription, operator_id: Number(subtaskOperator), due_date: subtaskDue || null, client_id: subtaskClient.current, expected_version: appeal.version})}>Создать подзадачу и назначить</button>
    </details>}
    {manage && !!appeal.task_history?.length && <details><summary>История назначений ({appeal.task_history.length})</summary>{appeal.task_history.map(task => <section className="appeal-task" key={task.id}><strong>{task.operator_name} · {appealStatuses[task.status]}</strong>{task.due_date && <p>Срок: {new Date(task.due_date + 'T00:00:00').toLocaleDateString('ru-RU')}</p>}<p className="owner-appeal-text">{task.instruction}</p><p className="owner-appeal-text">{task.result_comment}</p></section>)}</details>}
    {error && !confirmClose && <p className="error" role="alert">{error}</p>}
    {confirmClose && <div className="modal-backdrop"><section className="modal appeal-confirm" role="alertdialog" aria-modal="true" aria-labelledby="appeal-close-title" onKeyDown={event => {if (event.key === 'Escape' && !busy) {setConfirmClose(false); decisionTrigger.current?.focus();}}}>
      <h2 id="appeal-close-title">{decisionText.question}</h2><p>{appeal.is_public === false ? 'Ответ и фотографии будут сохранены в «Метке».' : 'Ответ и выбранные фотографии будут опубликованы на стене «Сигнала».'}</p>
      <p className="hint">Можно закрыть без отчёта исполнителя. Незавершённые назначения будут остановлены; открытые подзадачи будут закрыты вместе с этой задачей.</p>
      <blockquote className="owner-appeal-text">{answer}</blockquote><p>Фотографий результата: {selectedPhotos.length + files.length}</p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="owner-appeal-header-actions"><button autoFocus disabled={busy} onClick={() => {setConfirmClose(false); decisionTrigger.current?.focus();}}>Продолжить редактирование</button><button className="primary" disabled={busy} onClick={() => void send('/close', upload({status: decision, comment: answer, operator_photo_ids: selectedPhotos}))}>{preparing ? 'Подготавливаем фото…' : busy ? 'Сохраняем…' : decisionText.confirm}</button></div>
    </section></div>}
  </div>;
}
