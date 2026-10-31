import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../api';
import { appealDecisions, appealStatuses, hasAppealDecision, isFinalAppeal } from './statuses';
import { galleryPhoto } from './gallery';

export type ResultPhoto = {id: string; url: string; preview_url: string};
export type AppealTask = {id: number; operator_id: number; operator_name: string; instruction?: string;
  status: string; result_comment: string; photos: ResultPhoto[]; created_at: string; due_date?: string | null; finished_at?: string | null};
export type TaskRelation = {id: number; number: string; subject: string; status: string; is_final: boolean; operator_name: string; due_date: string | null; result: string; operator_result: string};
export type WorkflowAppeal = {id: number; status: string; version: number; can_manage?: boolean; can_execute?: boolean;
  is_public?: boolean; is_final?: boolean; resolved_at?: string | null; archived_at?: string | null; can_set_task_status?: boolean;
  submitted_by_inspector_name?: string; inspector_due_date?: string | null; parent_id?: number | null;
  can_set_inspector_deadline?: boolean; files?: {id: string; name: string; url: string}[];
  parent?: TaskRelation | null; children?: TaskRelation[];
  task?: AppealTask | null; task_history?: AppealTask[]; public_response?: string; response_photos?: ResultPhoto[]};

export default function AppealActions({appeal, endpoint, readOnly, changed, discussion, inspectorDiscussion, openTask, workspace = 'inspector'}: {
  appeal: WorkflowAppeal; endpoint: string; readOnly: boolean; changed: () => void; discussion?: ReactNode; inspectorDiscussion?: ReactNode; openTask?: (id: number) => void; workspace?: 'inspector' | 'executor';
}) {
  const [operators, setOperators] = useState<{id: number; name: string}[]>([]), [operator, setOperator] = useState('');
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
  const [decision, setDecision] = useState('RESOLVED');
  const decisionText = appealDecisions[decision];
  const decisionAction = decisionText.verb + (decision === 'RESOLVED' && appeal.is_public === false ? ' обращение' : '')
    + (appeal.is_public === false ? ' и сохранить ответ' : ' и опубликовать ответ');
  const manage = !readOnly && appeal.can_manage !== false && !appeal.can_execute;
  const execute = !readOnly && appeal.can_execute;
  useEffect(() => {
    if (!manage || isFinalAppeal(appeal)) return;
    const abort = new AbortController();
    api<{id: number; name: string}[]>(endpoint + '/' + appeal.id + '/operators', 'GET', undefined, abort.signal)
      .then(setOperators).catch(reason => {if (!abort.signal.aborted) setError(reason.message);});
    return () => abort.abort();
  }, [appeal.id, appeal.status, endpoint, manage]);
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
      await api(endpoint + '/' + appeal.id + path, 'POST', body); window.dispatchEvent(new Event('appeals-changed')); changed();
    }
    catch (reason) {setError((reason as Error).message);}
    finally {sending.current = false; setPreparing(false); setBusy(false);}
  }
  function upload(metadata: object) {
    const form = new FormData(); form.append('metadata', JSON.stringify({...metadata, expected_version: appeal.version}));
    files.forEach(file => form.append('photos', file)); return form;
  }
  const reportable = ['ASSIGNED', 'IN_PROGRESS'].includes(appeal.status);
  const tasks = <>
    {!!appeal.children?.length && <section className="appeal-task"><h3>Подзадачи · {appeal.children.length}</h3>{appeal.children.map(child => <article className="appeal-subtask-row" key={child.id}><button onClick={() => openTask?.(child.id)}>{child.number} · {child.subject}</button><p>{appealStatuses[child.status]} · {child.operator_name}</p><small className="hint">Срок: {child.due_date ? new Date(child.due_date + 'T00:00:00').toLocaleDateString('ru-RU') : 'Не установлен'}</small>{(child.result || child.operator_result) && <p className="owner-appeal-text">{child.result || child.operator_result}</p>}</article>)}</section>}
    {appeal.parent_id && !appeal.parent && <p className="hint">Подзадача обращения ОБ-{String(appeal.parent_id).padStart(6, '0')}</p>}
    {!!appeal.submitted_by_inspector_name && <section className="appeal-task"><h3>Срок проверяющего</h3><p>{appeal.inspector_due_date ? new Date(appeal.inspector_due_date + 'T00:00:00').toLocaleDateString('ru-RU') : 'Не установлен'}</p>
      {appeal.can_set_inspector_deadline && !appeal.archived_at && !isFinalAppeal(appeal) && <form onSubmit={event => {event.preventDefault(); void send('/deadline', {due_date: inspectorDueDate || null, expected_version: appeal.version});}}><label>Выполнить до<input type="date" value={inspectorDueDate} onChange={event => setInspectorDueDate(event.target.value)} disabled={busy}/></label><button className="primary" disabled={busy || inspectorDueDate === (appeal.inspector_due_date || '')}>Сохранить срок задачи</button></form>}
    </section>}
    {manage && !!appeal.submitted_by_inspector_name && !appeal.parent_id && !appeal.archived_at && !isFinalAppeal(appeal) && <details className="appeal-task"><summary>Разделить на подзадачи</summary><p className="hint">Каждая подзадача назначается отдельно. Итоговый ответ сохраните после завершения всех подзадач. Прямое назначение родительской задачи будет отменено.</p>
      <label>Тема<input maxLength={80} value={subtaskTitle} disabled={busy} onChange={event => setSubtaskTitle(event.target.value)}/></label>
      <label>Что нужно сделать<textarea maxLength={4000} value={subtaskDescription} disabled={busy} onChange={event => setSubtaskDescription(event.target.value)}/></label>
      <label>Исполнитель<select value={operator} disabled={busy} onChange={event => setOperator(event.target.value)}><option value="">Выберите оператора</option>{operators.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>Срок подзадачи<input type="date" max={appeal.inspector_due_date || undefined} value={subtaskDue} disabled={busy} onChange={event => setSubtaskDue(event.target.value)}/></label>
      <button className="primary" disabled={busy || !operator || !subtaskTitle.trim() || !subtaskDescription.trim()} onClick={() => void send('/subtasks', {subject: subtaskTitle, description: subtaskDescription, operator_id: Number(operator), due_date: subtaskDue || null, client_id: subtaskClient.current, expected_version: appeal.version})}>Создать подзадачу и назначить</button>
    </details>}
    {appeal.task && <section className="appeal-task"><h3>Исполнитель: {appeal.task.operator_name}</h3><p className="hint">{appealStatuses[appeal.task.status]}</p>
      <p className="appeal-task-deadline">Срок исполнения: <strong>{appeal.task.due_date ? new Date(appeal.task.due_date + 'T00:00:00').toLocaleDateString('ru-RU') : 'Не установлен'}</strong></p>
      {manage && !appeal.archived_at && !isFinalAppeal(appeal) && reportable && ['ASSIGNED', 'IN_PROGRESS'].includes(appeal.task.status) && <form className="appeal-deadline-form" onSubmit={event => {event.preventDefault(); void send('/deadline', {due_date: dueDate || null, expected_version: appeal.version});}}>
        <label>Срок исполнения<input type="date" max={appeal.inspector_due_date || undefined} value={dueDate} disabled={busy} onChange={event => setDueDate(event.target.value)}/></label>
        <p className="hint">До конца выбранного дня по времени организации. В «Сигнале» срок не показывается.</p>
        <button className="primary" disabled={busy || dueDate === (appeal.task.due_date || '')}>Сохранить срок</button>
        {dueDate && <button type="button" disabled={busy} onClick={() => setDueDate('')}>Убрать дату</button>}
      </form>}
      {appeal.task.instruction && <><strong>Комментарий к задаче</strong><p className="owner-appeal-text">{appeal.task.instruction}</p><small className="hint">Виден администратору и исполнителю.</small></>}
      {appeal.task.result_comment && <><h4>Результат исполнителя</h4><p className="owner-appeal-text">{appeal.task.result_comment}</p></>}
      <div className="appeal-evidence">{appeal.task.photos.map(photo => <a key={photo.id} href={photo.url} target="_blank" rel="noreferrer"><img src={photo.preview_url} alt="Фото результата исполнителя"/></a>)}</div>
    </section>}
    {appeal.can_set_task_status && !appeal.archived_at && !isFinalAppeal(appeal) && <section className="appeal-task"><h3>Статус задачи</h3>
      <label>Состояние задачи<select disabled={busy} value={result} onChange={event => setResult(event.target.value)}>
        {!['COMPLETED', 'CANCELLED'].includes(appeal.status) && <option value={appeal.status} disabled>{appealStatuses[appeal.status]}</option>}
        <option value="COMPLETED">Выполнена</option><option value="CANCELLED">Отменена</option>
      </select></label><button className="primary" disabled={busy || result === appeal.status} onClick={() => void send('/task-status', {status: result, expected_version: appeal.version})}>{busy ? 'Сохраняем…' : 'Сохранить статус задачи'}</button>
    </section>}
    {execute && reportable && <section className="appeal-task"><h3>Статус задачи</h3>
      <label>Состояние задачи<select disabled={busy} value={result} onChange={event => setResult(event.target.value)}><option value="ASSIGNED">Назначена</option><option value="IN_PROGRESS">В работе</option><option value="CANCELLED">Отменена</option><option value="COMPLETED">Выполнена</option></select></label>
      {['ASSIGNED', 'IN_PROGRESS'].includes(result) ? <button className="primary" disabled={busy || result === appeal.status} onClick={() => void send('/task-status', {status: result, expected_version: appeal.version})}>Сохранить статус задачи</button> : <>
        <label>Комментарий<textarea disabled={busy} value={comment} maxLength={4000} onChange={event => setComment(event.target.value)} placeholder="Что сделано или почему задача отменена"/></label>
        <PhotoInput disabled={busy} files={files} onChange={setFiles}/>
        <button className="primary" disabled={busy || !comment.trim() || !files.length || files.length > 3} onClick={() => void send('/result', upload({status: result, comment}))}>{preparing ? 'Подготавливаем фото…' : busy ? 'Отправляем…' : 'Передать результат администратору'}</button>
      </>}
    </section>}
    {manage && !appeal.children?.length && !isFinalAppeal(appeal) && <>
      <section className="appeal-task"><h3>{appeal.task ? 'Перенаправить задачу' : 'Назначить исполнителя'}</h3>
        <label>Оператор<select value={operator} disabled={busy} onChange={event => setOperator(event.target.value)}><option value="">Выберите исполнителя</option>{operators.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        {!operators.length && <p className="hint">Добавьте действующего оператора в этой организации.</p>}
        <label>Комментарий к задаче<textarea disabled={busy} value={instruction} maxLength={4000} onChange={event => setInstruction(event.target.value)} placeholder="Что нужно сделать исполнителю"/></label>
        <p className="hint">Этот комментарий виден только администратору и оператору.</p>
        <button disabled={busy || !operator} onClick={() => void send('/assign', {operator_id: Number(operator), instruction, expected_version: appeal.version})}>Назначить</button>
      </section>
    </>}
    {manage && !!appeal.task_history?.length && <details><summary>История назначений ({appeal.task_history.length})</summary>{appeal.task_history.map(task => <section className="appeal-task" key={task.id}><strong>{task.operator_name} · {appealStatuses[task.status]}</strong>{task.due_date && <p>Срок: {new Date(task.due_date + 'T00:00:00').toLocaleDateString('ru-RU')}</p>}<p className="owner-appeal-text">{task.instruction}</p><p className="owner-appeal-text">{task.result_comment}</p></section>)}</details>}
  </>;
  const decisions = <>
    {manage && !isFinalAppeal(appeal) && <>
      <section className="appeal-task"><h3>Решение по обращению</h3>
        <label>Решение<select value={decision} disabled={busy} onChange={event => setDecision(event.target.value)}>{Object.entries(appealDecisions).map(([value, text]) => <option value={value} key={value}>{text.label}</option>)}</select></label>
        <><p className="hint">{appeal.is_public === false ? 'Ответ останется внутри «Метки». Фотографии необязательны.' : 'Ответ появится на стене города. Фотографии необязательны.'}</p>
        <label>{appeal.is_public === false ? 'Ответ организации' : 'Публичный ответ организации'}<textarea value={answer} disabled={busy} maxLength={4000} onChange={event => setAnswer(event.target.value)} placeholder="Результат рассмотрения обращения"/></label>
        {appeal.task && ['COMPLETED', 'REJECTED', 'CANCELLED'].includes(appeal.task.status) && appeal.task.photos.length > 0 && <div className="appeal-result-selection"><strong>Приложить фото исполнителя</strong>{appeal.task.photos.map(photo => <label key={photo.id}>
          <input type="checkbox" checked={selectedPhotos.includes(photo.id)} disabled={busy} onChange={event => setSelectedPhotos(current => event.target.checked ? [...current, photo.id] : current.filter(id => id !== photo.id))}/><img src={photo.preview_url} alt="Выбрать фотографию результата"/></label>)}</div>}
        <PhotoInput disabled={busy} files={files} onChange={setFiles}/>
        {!!appeal.children?.some(child => !child.is_final) && <p className="hint">При закрытии незавершённые подзадачи будут закрыты вместе с родительской задачей.</p>}
        <button className="primary" disabled={busy || !answer.trim() || selectedPhotos.length + files.length > 3}
          onClick={() => setConfirmClose(true)}>{decisionAction}</button>
        </>
      </section>
    </>}
    {appeal.public_response && hasAppealDecision(appeal) && <section className="appeal-task"><h3>{appeal.is_public === false ? 'Ответ организации в «Метке»' : 'Ответ организации на стене'}</h3><p className="owner-appeal-text">{appeal.public_response}</p><div className="appeal-evidence">{appeal.response_photos?.map(photo => <a href={photo.url} key={photo.id} target="_blank" rel="noreferrer"><img src={photo.preview_url} alt="Результат рассмотрения"/></a>)}</div></section>}
    {manage && isFinalAppeal(appeal) && <section className="appeal-task"><button disabled={busy} onClick={() => void send('/archive', {archived: !appeal.archived_at, expected_version: appeal.version})}>{appeal.archived_at ? 'Вернуть из архива' : 'Перенести в архив'}</button><p className="hint">{appeal.status === 'SPAM' ? 'Спам будет убран из рабочего списка. На стене «Сигнала» он не появится.' : appeal.is_public === false ? 'Архив убирает обращение из рабочего списка. Ответ и фотографии сохраняются в «Метке».' : 'Архив убирает обращение из рабочего списка. Ответ жителю сохраняется на стене.'}</p></section>}
  </>;
  return <div className="appeal-workflow">
    {manage && inspectorDiscussion ? <>
      <div hidden={workspace !== 'inspector'}><div className="appeal-task-workspace"><div><section className="appeal-task"><h3>Срок проверяющего</h3><p>{appeal.inspector_due_date ? new Date(appeal.inspector_due_date + 'T00:00:00').toLocaleDateString('ru-RU') : 'Не установлен'}</p></section>{decisions}</div>{inspectorDiscussion}</div></div>
      <div hidden={workspace !== 'executor'}><div className="appeal-task-workspace"><div>{tasks}</div><div>{discussion}</div></div></div>
    </> : <div className="appeal-task-workspace"><div>{tasks}{decisions}</div><div>{inspectorDiscussion || discussion}</div></div>}
    {error && <p className="error" role="alert">{error}</p>}
    {confirmClose && <div className="modal-backdrop"><section className="modal appeal-confirm" role="alertdialog" aria-modal="true" aria-labelledby="appeal-close-title" onKeyDown={event => {if (event.key === 'Escape' && !busy) setConfirmClose(false);}}>
      <h2 id="appeal-close-title">{decisionText.question}</h2><p>{appeal.is_public === false ? 'Ответ и фотографии будут сохранены в «Метке».' : 'Ответ и выбранные фотографии будут опубликованы на стене «Сигнала».'}</p>
      <p className="hint">Можно закрыть без отчёта исполнителя. Незавершённые назначения будут остановлены; открытые подзадачи будут закрыты вместе с этой задачей.</p>
      <blockquote className="owner-appeal-text">{answer}</blockquote><p>Фотографий результата: {selectedPhotos.length + files.length}</p>
      <div className="owner-appeal-header-actions"><button autoFocus disabled={busy} onClick={() => setConfirmClose(false)}>Продолжить редактирование</button><button className="primary" disabled={busy} onClick={() => void send('/close', upload({status: decision, comment: answer, operator_photo_ids: selectedPhotos}))}>{preparing ? 'Подготавливаем фото…' : busy ? 'Сохраняем…' : decisionText.confirm}</button></div>
    </section></div>}
  </div>;
}

function PhotoInput({disabled, files, onChange}: {disabled: boolean; files: File[]; onChange: (files: File[]) => void}) {
  return <label>Свои фотографии результата <small>до 3 файлов по 25 МБ</small><input type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.jpg,.jpeg,.png,.webp,.heic,.heif" multiple disabled={disabled}
    onChange={event => onChange([...(event.target.files || [])])}/>{files.length > 0 && <span className="hint">Выбрано: {files.length}</span>}</label>;
}
