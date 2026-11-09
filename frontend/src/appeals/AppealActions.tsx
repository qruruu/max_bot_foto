import { useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../api';
import AppealModal from './AppealModal';
import ClosePhotoPicker from './ClosePhotoPicker';
import type { ClosePhoto, ResponsePhotoDraft } from './ResponsePhotoDraft';
import { appealDecisions, appealStatuses, hasAppealDecision, isFinalAppeal } from './statuses';
import { galleryPhoto } from './gallery';
import TaskImageInput, { MAX_PHOTOS, pastedImages } from './TaskImageInput';

export type ResultPhoto = {id: string; url: string; preview_url: string};
export type AppealTask = {id: number; operator_id: number; operator_name: string; instruction?: string;
  status: string; result_comment: string; photos: ResultPhoto[]; created_at: string; due_date?: string | null; finished_at?: string | null};
export type TaskRelation = {id: number; number: string; subject: string; status: string; is_final: boolean; operator_name: string; due_date: string | null; result: string; operator_result: string};
export type WorkflowAppeal = {id: number; status: string; version: number; can_manage?: boolean; can_execute?: boolean;
  can_archive?: boolean; personal_archived?: boolean; is_public?: boolean; is_final?: boolean; resolved_at?: string | null; archived_at?: string | null; can_set_task_status?: boolean;
  submitted_by_inspector_name?: string; inspector_due_date?: string | null; parent_id?: number | null;
  can_set_inspector_deadline?: boolean; files?: {id: string; name: string; url: string}[];
  parent?: TaskRelation | null; children?: TaskRelation[];
  task?: AppealTask | null; task_history?: AppealTask[]; public_response?: string; response_photos?: ResultPhoto[]};

export default function AppealActions({appeal, endpoint, readOnly, changed, discussion, inspectorDiscussion, openTask, workspace = 'inspector', taskContext, chooseGeneral, resumedDraft, consumeDraft}: {
  appeal: WorkflowAppeal; endpoint: string; readOnly: boolean; changed: () => void; discussion?: ReactNode; inspectorDiscussion?: ReactNode; openTask?: (id: number) => void; workspace?: 'inspector' | 'executor'; taskContext?: ReactNode; chooseGeneral?: (draft: ResponsePhotoDraft) => void;
  resumedDraft?: ResponsePhotoDraft; consumeDraft?: () => void;
}) {
  const answerId = useId();
  const [operators, setOperators] = useState<{id: number; name: string}[]>([]), [operator, setOperator] = useState('');
  const [instruction, setInstruction] = useState(''), [result, setResult] = useState(appeal.status), [comment, setComment] = useState('');
  const [dueDate, setDueDate] = useState(appeal.task?.due_date || appeal.inspector_due_date || '');
  const [inspectorDueDate, setInspectorDueDate] = useState(appeal.inspector_due_date || '');
  const [subtaskTitle, setSubtaskTitle] = useState(''), [subtaskDescription, setSubtaskDescription] = useState('');
  const [subtaskDue, setSubtaskDue] = useState('');
  const subtaskClient = useRef(crypto.randomUUID());
  const [files, setFiles] = useState<File[]>(resumedDraft?.files || []);
  const [answer, setAnswer] = useState(resumedDraft?.answer || '');
  const [selectedPhotos, setSelectedPhotos] = useState<string[]>(resumedDraft?.operatorPhotos || []);
  const taskId = useRef(appeal.task?.id);
  const [responseVersion, setResponseVersion] = useState(resumedDraft?.version ?? appeal.version);
  const [sourcePhotos, setSourcePhotos] = useState<ClosePhoto[]>(resumedDraft?.sourcePhotos || []);
  const photoCount = selectedPhotos.length + files.length + sourcePhotos.length;
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [preparing, setPreparing] = useState(false), sending = useRef(false);
  const [confirmClose, setConfirmClose] = useState(!!resumedDraft);
  const [assignmentOpen, setAssignmentOpen] = useState(false);
  const inspectorDeadlineEditor = useRef<HTMLDetailsElement>(null);
  const [decision, setDecision] = useState(resumedDraft?.decision || 'RESOLVED');
  const decisionText = appealDecisions[decision];
  const manage = !readOnly && appeal.can_manage !== false && !appeal.can_execute;
  const execute = !readOnly && appeal.can_execute;
  useEffect(() => {
    if (!manage || isFinalAppeal(appeal)) return;
    const abort = new AbortController();
    api<{id: number; name: string}[]>(endpoint + '/' + appeal.id + '/operators', 'GET', undefined, abort.signal)
      .then(setOperators).catch(reason => {if (!abort.signal.aborted) setError(reason.message);});
    return () => abort.abort();
  }, [appeal.id, appeal.status, endpoint, manage]);
  useEffect(() => setResult(appeal.status), [appeal.status]);
  useEffect(() => setDueDate(appeal.task?.due_date || appeal.inspector_due_date || ''), [appeal.task?.id, appeal.task?.due_date, appeal.inspector_due_date]);
  useEffect(() => setInspectorDueDate(appeal.inspector_due_date || ''), [appeal.inspector_due_date]);
  useEffect(() => {
    if (taskId.current === appeal.task?.id) return;
    taskId.current = appeal.task?.id;
    setSelectedPhotos([]);
  }, [appeal.task?.id]);
  useEffect(() => {if (resumedDraft) consumeDraft?.();}, [resumedDraft, consumeDraft]);

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
      if (path === '/deadline') {inspectorDeadlineEditor.current?.removeAttribute('open');}
      if (path === '/assign') {setAssignmentOpen(false); setOperator(''); setInstruction('');}
      if (path === '/subtasks') {
        setOperator(''); setSubtaskTitle(''); setSubtaskDescription(''); setSubtaskDue('');
        subtaskClient.current = crypto.randomUUID();
      }
      if (path === '/result') {setComment(''); setFiles([]);}
      if (path === '/close') {setConfirmClose(false); setSourcePhotos([]); setAnswer(''); setSelectedPhotos([]); setFiles([]);}
      window.dispatchEvent(new Event('appeals-changed'));
      changed();
    }
    catch (reason) {setError((reason as Error).message);}
    finally {sending.current = false; setPreparing(false); setBusy(false);}
  }
  function updateFiles(next: File[]) {
    if (next.length + sourcePhotos.length + selectedPhotos.length > MAX_PHOTOS && next.length >= files.length) {
      setError(`Можно приложить до ${MAX_PHOTOS} фото или скриншотов`);
      return;
    }
    setError('');
    setFiles(next);
  }

  function upload(metadata: object) {
    const form = new FormData(); form.append('metadata', JSON.stringify({expected_version: appeal.version, ...metadata}));
    files.forEach(file => form.append('photos', file)); return form;
  }
  const assignmentOperator = operator || operators.find(item => item.id === appeal.task?.operator_id)?.id || '';
  const reportable = ['ASSIGNED', 'IN_PROGRESS'].includes(appeal.status);
  const canDecide = manage && !appeal.archived_at && !isFinalAppeal(appeal);
  const canAssign = canDecide && !appeal.children?.length;
  const assignmentTitle = appeal.task ? 'Перенаправить задачу' : 'Назначить исполнителя';
  const workflowActions = (allowRedirect = true) => canDecide && <div className="appeal-work-actions">
    <button className="primary" disabled={busy} onClick={() => {
      setError(''); setResponseVersion(appeal.version); setConfirmClose(true);
    }}>Закрыть обращение</button>
    {canAssign && (allowRedirect || !appeal.task) && <button className="primary" disabled={busy} onClick={() => {
      setError(''); setAssignmentOpen(true);
    }}>{assignmentTitle}</button>}
  </div>;
  const tasks = <>
    {taskContext}
    {!!appeal.children?.length && <section className="appeal-task"><h3>Подзадачи · {appeal.children.length}</h3>{appeal.children.map(child => <article className="appeal-subtask-row" key={child.id}><button onClick={() => openTask?.(child.id)}>{child.number} · {child.subject}</button><p>{appealStatuses[child.status]}{!readOnly && ' · ' + child.operator_name}</p>{!readOnly && child.due_date && <small className="hint">Срок: {new Date(child.due_date + 'T00:00:00').toLocaleDateString('ru-RU')}</small>}{(child.result || child.operator_result) && <p className="owner-appeal-text">{child.result || child.operator_result}</p>}</article>)}</section>}
    {appeal.parent_id && !appeal.parent && <p className="hint">Подзадача обращения ОБ-{String(appeal.parent_id).padStart(6, '0')}</p>}
    {!execute && !!appeal.submitted_by_inspector_name && <section className="appeal-task"><h3>{readOnly ? 'Срок задачи' : 'Срок от проверяющего'}</h3>
      <p>{appeal.inspector_due_date ? new Date(appeal.inspector_due_date + 'T00:00:00').toLocaleDateString('ru-RU') : 'Без срока'}</p>
      {appeal.can_set_inspector_deadline && !appeal.archived_at && !isFinalAppeal(appeal) && <details ref={inspectorDeadlineEditor}>
        <summary>Изменить срок</summary>
        <form onSubmit={event => {event.preventDefault(); void send('/deadline', {due_date: inspectorDueDate || null, expected_version: appeal.version});}}>
          <label>Выполнить до<input type="date" value={inspectorDueDate} onChange={event => setInspectorDueDate(event.target.value)} disabled={busy}/></label>
          <button disabled={busy || inspectorDueDate === (appeal.inspector_due_date || '')}>Сохранить срок</button>
        </form>
      </details>}
    </section>}
    {manage && !!appeal.submitted_by_inspector_name && !appeal.parent_id && !appeal.archived_at && !isFinalAppeal(appeal) && <details className="appeal-task"><summary>Разделить на подзадачи</summary><p className="hint">Каждая подзадача назначается отдельно. Итоговый ответ сохраните после завершения всех подзадач. Прямое назначение родительской задачи будет отменено.</p>
      <label>Тема<input maxLength={80} value={subtaskTitle} disabled={busy} onChange={event => setSubtaskTitle(event.target.value)}/></label>
      <label>Что нужно сделать<textarea maxLength={4000} value={subtaskDescription} disabled={busy} onChange={event => setSubtaskDescription(event.target.value)}/></label>
      <label>Исполнитель<select value={operator} disabled={busy} onChange={event => setOperator(event.target.value)}><option value="">Выберите оператора</option>{operators.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>Срок подзадачи<input type="date" max={appeal.inspector_due_date || undefined} value={subtaskDue} disabled={busy} onChange={event => setSubtaskDue(event.target.value)}/></label>
      <button className="primary" disabled={busy || !operator || !subtaskTitle.trim() || !subtaskDescription.trim()} onClick={() => void send('/subtasks', {subject: subtaskTitle, description: subtaskDescription, operator_id: Number(operator), due_date: subtaskDue || null, client_id: subtaskClient.current, expected_version: appeal.version})}>Создать подзадачу и назначить</button>
    </details>}
    {appeal.task && <section className="panel appeal-work-card">{!execute && <><h3>Исполнитель: {appeal.task.operator_name}</h3><p className="hint">{appealStatuses[appeal.task.status]}</p></>}
      <p className="appeal-task-deadline">Срок исполнения: <strong>{appeal.task.due_date ? new Date(appeal.task.due_date + 'T00:00:00').toLocaleDateString('ru-RU') : 'Не установлен'}</strong></p>
      {appeal.task.instruction && <><strong>Комментарий к задаче</strong><p className="owner-appeal-text">{appeal.task.instruction}</p>{!execute && <small className="hint">Виден администратору и исполнителю.</small>}</>}
      {appeal.task.result_comment && <><h4>Результат исполнителя</h4><p className="owner-appeal-text">{appeal.task.result_comment}</p></>}
      {!!appeal.task.photos.length && <div className="appeal-evidence">{appeal.task.photos.map(photo => <a key={photo.id} href={photo.url} target="_blank" rel="noreferrer"><img src={photo.preview_url} alt="Фото результата исполнителя"/></a>)}</div>}
    </section>}
    {workflowActions()}
    {appeal.can_set_task_status && !appeal.archived_at && !isFinalAppeal(appeal) && <details className="appeal-task"><summary>Изменить статус</summary>
      <label>Статус<select disabled={busy} value={result} onChange={event => setResult(event.target.value)}>
        {!['COMPLETED', 'CANCELLED'].includes(appeal.status) && <option value={appeal.status} disabled>{appealStatuses[appeal.status]}</option>}
        <option value="COMPLETED">Выполнена</option><option value="CANCELLED">Отменена</option>
      </select></label><button className="primary" disabled={busy || result === appeal.status} onClick={() => void send('/task-status', {status: result, expected_version: appeal.version})}>{busy ? 'Сохраняем…' : 'Сохранить статус задачи'}</button>
    </details>}
    {execute && reportable && <section className="appeal-task"><h3>Статус задачи</h3>
      <label>Состояние задачи<select disabled={busy} value={result} onChange={event => setResult(event.target.value)}><option value="ASSIGNED">Назначена</option><option value="IN_PROGRESS">В работе</option><option value="CANCELLED">Отменена</option><option value="COMPLETED">Выполнена</option></select></label>
      {['ASSIGNED', 'IN_PROGRESS'].includes(result) ? <button className="primary" disabled={busy || result === appeal.status} onClick={() => void send('/task-status', {status: result, expected_version: appeal.version})}>Сохранить статус задачи</button> : <>
        <label>Комментарий<textarea disabled={busy} value={comment} maxLength={4000} onPaste={event => {const images = pastedImages(event); if (images.length) updateFiles([...files, ...images]);}} onChange={event => setComment(event.target.value)} placeholder="Что сделано или почему задача отменена"/></label>
        <TaskImageInput disabled={busy} files={files} onChange={updateFiles}/>
        <button className="primary" disabled={busy || !comment.trim() || !files.length || files.length > MAX_PHOTOS} onClick={() => void send('/result', upload({status: result, comment}))}>{preparing ? 'Подготавливаем фото…' : busy ? 'Отправляем…' : 'Передать результат администратору'}</button>
      </>}
    </section>}
    {manage && !!appeal.task_history?.length && <details><summary>История назначений ({appeal.task_history.length})</summary>{appeal.task_history.map(task => <section className="appeal-task" key={task.id}><strong>{task.operator_name} · {appealStatuses[task.status]}</strong>{task.due_date && <p>Срок: {new Date(task.due_date + 'T00:00:00').toLocaleDateString('ru-RU')}</p>}<p className="owner-appeal-text">{task.instruction}</p><p className="owner-appeal-text">{task.result_comment}</p></section>)}</details>}
  </>;
  const decisions = <>
    {appeal.public_response && hasAppealDecision(appeal) && <section className="appeal-task"><h3>{appeal.is_public === false ? 'Ответ организации в «Метке»' : 'Ответ организации на стене'}</h3><p className="owner-appeal-text">{appeal.public_response}</p><div className="appeal-evidence">{appeal.response_photos?.map(photo => <a href={photo.url} key={photo.id} target="_blank" rel="noreferrer"><img src={photo.preview_url} alt="Результат рассмотрения"/></a>)}</div></section>}
  </>;
  return <div className="appeal-workflow">
    {manage && inspectorDiscussion ? <>
      <div hidden={workspace !== 'inspector'}><div className="appeal-task-workspace"><div>{taskContext}<section className="appeal-task"><h3>Срок проверяющего</h3><p>{appeal.inspector_due_date ? new Date(appeal.inspector_due_date + 'T00:00:00').toLocaleDateString('ru-RU') : 'Не установлен'}</p></section>{workflowActions(false)}{decisions}</div>{inspectorDiscussion}</div></div>
      <div hidden={workspace !== 'executor'}><div className="appeal-task-workspace"><div>{tasks}</div><div>{discussion}</div></div></div>
    </> : <div className="appeal-task-workspace"><div>{tasks}{decisions}</div><div>{inspectorDiscussion || discussion}</div></div>}
    {error && <p className="error" role="alert">{error}</p>}
    {assignmentOpen && canAssign && <AppealModal title={assignmentTitle} close={() => setAssignmentOpen(false)} busy={busy}>
      {error && <p className="error" role="alert">{error}</p>}
      <section className="appeal-work-card">
        <label>Оператор<select value={assignmentOperator}
          disabled={busy} onChange={event => setOperator(event.target.value)}>
          <option value="">Выберите исполнителя</option>{operators.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        {!operators.length && <p className="hint">Добавьте действующего оператора в этой организации.</p>}
        <label>Срок исполнения<input type="date" max={appeal.inspector_due_date || undefined} value={dueDate}
          disabled={busy} onChange={event => setDueDate(event.target.value)}/></label>
        <label>Комментарий к задаче<textarea disabled={busy} value={instruction} maxLength={4000} onChange={event => setInstruction(event.target.value)} placeholder="Что нужно сделать исполнителю"/></label>
        <p className="hint">Этот комментарий виден только администратору и оператору.</p>
        <button disabled={busy || !assignmentOperator}
          onClick={() => void send('/assign', {operator_id: Number(assignmentOperator), instruction,
            due_date: dueDate || null, expected_version: appeal.version})}>Назначить</button>
      </section>
    </AppealModal>}
    {confirmClose && <AppealModal title="Закрытие обращения" close={() => setConfirmClose(false)} busy={busy}>
      {error && <p className="error" role="alert">{error}</p>}
      <form className="appeal-close-form" onSubmit={event => {
        event.preventDefault();
        if (answer.trim() && photoCount <= MAX_PHOTOS) {
          void send('/close', upload({expected_version: responseVersion, status: decision, comment: answer, operator_photo_ids: selectedPhotos,
            chat_photo_ids: sourcePhotos.filter(photo => photo.source === 'chat').map(photo => photo.id),
            photo_ids: sourcePhotos.filter(photo => photo.source === 'general').map(photo => photo.id)}));
        }
      }}>
        <label>Решение<select value={decision} disabled={busy} onChange={event => setDecision(event.target.value)}>{Object.entries(appealDecisions).map(([value, text]) => <option value={value} key={value}>{text.label}</option>)}</select></label>
        <p className="hint">{appeal.is_public === false ? 'Ответ останется внутри «Метки». Фотографии необязательны.' : 'Ответ появится на стене города. Фотографии необязательны.'}</p>
        <label htmlFor={answerId}>{appeal.is_public === false ? 'Ответ организации' : 'Публичный ответ организации'}</label>
        <TaskImageInput disabled={busy} files={files} onChange={updateFiles} picker={openFiles =>
          <ClosePhotoPicker endpoint={endpoint + '/' + appeal.id} selected={sourcePhotos}
            chooseGeneral={chooseGeneral ? () => chooseGeneral({appealId: appeal.id, version: responseVersion,
              decision, answer, files, operatorPhotos: selectedPhotos, sourcePhotos}) : undefined}
            change={setSourcePhotos} remaining={MAX_PHOTOS - photoCount} disabled={busy} openFiles={openFiles}
            answerField={<textarea id={answerId} value={answer} disabled={busy} maxLength={4000}
              onPaste={event => {const images = pastedImages(event); if (images.length) updateFiles([...files, ...images]);}}
              onChange={event => setAnswer(event.target.value)} placeholder="Результат рассмотрения обращения"/>}
            resultPhotos={appeal.task && ['COMPLETED', 'REJECTED', 'CANCELLED'].includes(appeal.task.status) && !!appeal.task.photos.length
              ? <div className="appeal-result-selection">{appeal.task.photos.map(photo => <label key={photo.id}>
                <input type="checkbox" aria-label="Выбрать фотографию результата" checked={selectedPhotos.includes(photo.id)}
                  disabled={busy || (!selectedPhotos.includes(photo.id) && photoCount >= MAX_PHOTOS)}
                  onChange={event => setSelectedPhotos(current => event.target.checked ? [...current, photo.id] : current.filter(id => id !== photo.id))}/>
                <img src={photo.preview_url} alt=""/>
              </label>)}</div> : undefined}/>}/>
        {!!selectedPhotos.length && <div className="appeal-close-picked" aria-label="Выбранные фото исполнителя">
          {appeal.task?.photos.filter(photo => selectedPhotos.includes(photo.id)).map(photo => <button type="button" key={photo.id}
            disabled={busy} aria-label="Убрать фото исполнителя" onClick={() => setSelectedPhotos(current => current.filter(id => id !== photo.id))}>
            <img src={photo.preview_url} alt=""/> ×
          </button>)}
        </div>}
        {!!appeal.children?.some(child => !child.is_final) && <p className="hint">При закрытии незавершённые подзадачи будут закрыты вместе с родительской задачей.</p>}
        {photoCount > 0 && <p className="hint">Всего фото в ответе {photoCount} из {MAX_PHOTOS}.</p>}
        <div className="owner-appeal-header-actions">
          <button type="button" disabled={busy} onClick={() => setConfirmClose(false)}>Отмена</button>
          <button type="submit" className="primary" disabled={busy || !answer.trim() || photoCount > MAX_PHOTOS}>
            {preparing ? 'Подготавливаем фото…' : busy ? 'Сохраняем…' : decisionText.confirm}
          </button>
        </div>
      </form>
    </AppealModal>}
  </div>;
}
