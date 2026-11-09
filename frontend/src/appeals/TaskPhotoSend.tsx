import { useEffect, useRef, useState } from 'react';
import { api } from '../api';

export type TaskChannel = 'inspector' | 'executor';
type Task = {id: number; number: string; subject: string; submitted_by_inspector_name?: string; operator_id?: number};

export function sendTaskPhotos(task: number, ids: number[], clientId: string, channel?: TaskChannel) {
  return api('/appeals/' + task + '/photo-comments', 'POST', {photo_ids: ids, client_id: clientId, channel});
}

export default function TaskPhotoSend({ids, close, sent}: {ids: number[]; close: () => void; sent: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const attempt = useRef<{task: number; channel: TaskChannel; id: string} | null>(null);
  const [search, setSearch] = useState(''), [tasks, setTasks] = useState<Task[]>([]);
  const [selected, setSelected] = useState<Task | null>(null), [channel, setChannel] = useState<TaskChannel>('executor');
  const [canManage, setCanManage] = useState(false);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [error, setError] = useState('');
  useEffect(() => {dialog.current?.showModal();}, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    const timer = window.setTimeout(() => {
      api<{items: Task[]; can_manage: boolean}>('/appeals?' + new URLSearchParams({q: search.trim()}), 'GET', undefined, controller.signal)
        .then(value => {if (controller.signal.aborted) return;
          setCanManage(value.can_manage);
          setTasks(value.items.filter(task => task.operator_id || (value.can_manage && task.submitted_by_inspector_name)));})
        .catch(error => {if (!controller.signal.aborted) setError(error.message);})
        .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    }, 200);
    return () => {controller.abort(); window.clearTimeout(timer);};
  }, [search]);

  async function send() {
    if (!selected || busy) return;
    if (attempt.current?.task !== selected.id || attempt.current.channel !== channel) {
      attempt.current = {task: selected.id, channel, id: crypto.randomUUID()};
    }
    setBusy(true); setError('');
    try {
      await sendTaskPhotos(selected.id, ids, attempt.current.id, channel);
      sent();
    } catch (error) {setError((error as Error).message);}
    finally {setBusy(false);}
  }

  return <dialog ref={dialog} className="modal" onCancel={event => {event.preventDefault(); if (!busy) close();}}>
    <h2>Переслать в задачу</h2>
    <label>Поиск по номеру или названию<input type="search" value={search} maxLength={200} disabled={busy} onChange={event => {setSearch(event.target.value); setSelected(null);}}/></label>
    <label>Задача<select value={selected?.id || ''} disabled={busy || loading} onChange={event => {
      const task = tasks.find(task => task.id === Number(event.target.value));
      setSelected(task || null);
      setChannel(task && !task.operator_id ? 'inspector' : 'executor');
    }}><option value="">{loading ? 'Загружаем…' : 'Выберите задачу'}</option>
      {tasks.map(task => <option key={task.id} value={task.id}>{task.number} · {task.subject}</option>)}
    </select></label>
    {canManage && selected?.submitted_by_inspector_name && selected.operator_id && <label>Переписка<select value={channel} disabled={busy} onChange={event => setChannel(event.target.value as TaskChannel)}>
      <option value="executor">С исполнителем</option><option value="inspector">С проверяющим</option>
    </select></label>}
    {error && <p className="error" role="alert">{error}</p>}
    <div className="day-dialog-actions"><button disabled={busy} onClick={close}>Отмена</button>
      <button className="primary" disabled={busy || !selected || loading} onClick={() => void send()}>{busy ? 'Отправляем…' : 'Переслать'}</button>
    </div>
  </dialog>;
}
