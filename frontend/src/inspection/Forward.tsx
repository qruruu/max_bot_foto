import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Camera, Check, Search, Send, X } from 'lucide-react';
import { ApiError, api } from '../api';
import { ErrorBox } from '../App';
import Avatar from '../Avatar';
import type { Contact, InspectionPhoto, Message } from './types';
import type { ContactPage, OperatorMessage } from '../operatorChatData';
import '../operator-chats.css';

type Destination = {key: string; name: string; subtitle?: string | null};
type Recipient = Destination & {avatar?: string | null; recent?: string | null; kind: 'staff' | 'inspector' | 'task'};
type PersonalMessage = Message | OperatorMessage;
type SourceMessage = Pick<PersonalMessage, 'id' | 'body' | 'screenshots'>;
type AppealForward = {endpoint: string; messages: SourceMessage[]; personal?: boolean; channel?: 'inspector' | 'executor'};
type ForwardPhoto = Pick<InspectionPhoto, 'id'> & {preview_url: string | null; organization_id?: string};

const operatorMessage = (message: PersonalMessage) => 'sender_id' in message;
function forwardField(operatorSource: boolean, operatorTarget: boolean) {
  if (operatorSource === operatorTarget) return 'forward_message_id';
  return operatorSource ? 'forward_operator_message_id' : 'forward_inspection_message_id';
}

async function loadRecipients(base: string, operatorTarget: boolean, query: URLSearchParams, signal: AbortSignal): Promise<Recipient[]> {
  if (operatorTarget) {
    const page = await api<ContactPage>('/operator-chats?' + query, 'GET', undefined, signal);
    return page.items.filter(item => item.active).map(item => ({
      key: String(item.id), name: item.name, subtitle: item.role === 'ADMIN_OPERATOR' ? 'Администратор' : 'Оператор',
      avatar: item.avatar_url, recent: item.last_message?.created_at, kind: 'staff',
    }));
  }
  const items = await api<Contact[]>(base + '/contacts?' + query, 'GET', undefined, signal);
  return items.map(item => ({key: item.key, name: item.name, subtitle: item.organization_name ? item.kind + ' · ' + item.organization_name : item.kind,
    avatar: item.avatar_url, recent: item.last_message_at, kind: item.key.startsWith('i:') ? 'inspector' : 'staff'}));
}

async function taskRecipients(base: string, appeal: AppealForward, search: string, signal: AbortSignal) {
  const messageId = String(appeal.messages[0].id);
  const tasks = api<{id: number; title: string}[]>(appeal.endpoint + '/forward-targets?' + new URLSearchParams({
    message_id: messageId, q: search, ...(appeal.channel ? {channel: appeal.channel} : {}),
  }), 'GET', undefined, signal).then(items => items.map(item => ({
    key: 'task:' + item.id, name: item.title, subtitle: 'Чат задачи', kind: 'task' as const,
  })));
  if (!appeal.personal) return tasks;
  const query = new URLSearchParams({forward_task_message_id: messageId});
  const personal = await Promise.all([loadRecipients(base, true, query, signal), loadRecipients(base, false, query, signal), tasks]);
  return personal.flat();
}

async function personalRecipients(base: string, messages: PersonalMessage[], photo: ForwardPhoto | undefined, unified: boolean, signal: AbortSignal) {
  const operatorSource = messages.length ? operatorMessage(messages[0]) : !photo?.organization_id;
  // One text message establishes the same eligible contacts as the other text messages in this conversation.
  const filters = messages.filter(message => message.photo);
  if (!filters.length && messages.length) filters.push(messages[0]);
  async function recipients(operatorTarget: boolean) {
    if (photo) return loadRecipients(base, operatorTarget, new URLSearchParams({
      ...(photo.organization_id ? {photo_organization_id: photo.organization_id} : {}), photo_id: String(photo.id),
    }), signal);
    const field = forwardField(operatorSource, operatorTarget);
    const [first, ...others] = await Promise.all(filters.map(message => loadRecipients(base, operatorTarget, new URLSearchParams({[field]: String(message.id)}), signal)));
    const allowed = others.map(items => new Set(items.map(item => item.key)));
    return first.filter(item => allowed.every(keys => keys.has(item.key)));
  }
  if (!unified) return recipients(operatorSource);
  const lists = await Promise.all([recipients(true), recipients(false)]);
  return lists.flat().sort((a, b) => (b.recent || '').localeCompare(a.recent || '') || a.name.localeCompare(b.name, 'ru'));
}

export default function InspectionForward({base: endpoint, photo, message, operatorMessage: operator, messages, appeal, unified = false, onClose, onSent}: {
  base?: string; photo?: ForwardPhoto; message?: Message; operatorMessage?: OperatorMessage; messages?: PersonalMessage[];
  appeal?: AppealForward; unified?: boolean; onClose: () => void; onSent: (peer: Destination, count?: number) => void;
}) {
  const base = endpoint || (appeal?.personal ? '/inspection-admin' : '/inspection');
  const personal = messages || (message ? [message] : operator ? [operator] : []);
  const sources = appeal?.messages || personal;
  const [contacts, setContacts] = useState<Recipient[]>([]), [loading, setLoading] = useState(true);
  const [selection, setSelection] = useState<Recipient[]>([]);
  const [search, setSearch] = useState(''), [remoteSearch, setRemoteSearch] = useState('');
  const [filter, setFilter] = useState<'all' | 'recent' | 'staff' | 'inspector' | 'task'>('all');
  const [body, setBody] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0), [locked, setLocked] = useState(false);
  const form = useRef<HTMLFormElement>(null), pending = useRef(false);
  const attempt = useRef<{signature: string; completed: number; ids: string[]} | null>(null);
  const sourceKey = sources.map(item => item.id).join(',');
  useEffect(() => {
    if (!appeal) return;
    const timer = window.setTimeout(() => setRemoteSearch(search.trim()), 220);
    return () => window.clearTimeout(timer);
  }, [appeal?.endpoint, search]);

  const term = search.trim().toLocaleLowerCase('ru-RU');
  const visible = contacts.filter(item => (filter === 'all' || (filter === 'recent' ? item.recent : item.kind === filter))
    && (item.kind === 'task' || [item.name, item.subtitle].join(' ').toLocaleLowerCase('ru-RU').includes(term)));
  const searching = !!appeal && search.trim() !== remoteSearch;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    const request = appeal ? taskRecipients(base, appeal, remoteSearch, controller.signal)
      : personalRecipients(base, personal, photo, unified, controller.signal);
    request.then(value => {if (!controller.signal.aborted) setContacts(value);})
      .catch(error => {if (!controller.signal.aborted) setError(error.message);})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [base, sourceKey, photo?.id, photo?.organization_id, appeal?.endpoint, appeal?.channel, appeal?.personal, remoteSearch, unified]);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null, overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    form.current?.querySelector<HTMLInputElement>('input[type=search]')?.focus();
    return () => {document.body.style.overflow = overflow; if (previous?.isConnected) previous.focus({preventScroll: true});};
  }, []);

  function toggle(recipient: Recipient) {
    setSelection(current => current.some(item => item.key === recipient.key) ? current.filter(item => item.key !== recipient.key)
      : photo || (appeal && !appeal.personal) ? [recipient] : [...current, recipient]);
  }
  async function send(event: FormEvent) {
    event.preventDefault();
    if (!selection.length || pending.current || searching || loading) return;
    const text = body.trim();
    const signature = JSON.stringify([selection.map(item => item.key), text]);
    const count = selection.length * (sources.length || 1);
    if (attempt.current?.signature !== signature) attempt.current = {signature, completed: 0, ids: Array.from({length: count}, () => crypto.randomUUID())};
    const current = attempt.current;
    pending.current = true; setBusy(true); setError('');
    if (count > 1) setLocked(true);
    try {
      for (let index = current.completed; index < count; index++) {
        const peer = selection[Math.floor(index / (sources.length || 1))];
        const sourceIndex = index % (sources.length || 1), source = sources[sourceIndex];
        const operatorTarget = peer.kind === 'staff' && /^\d+$/.test(peer.key);
        const taskTarget = !!appeal && peer.kind === 'task';
        const path = taskTarget ? appeal.endpoint.slice(0, appeal.endpoint.lastIndexOf('/')) + '/' + peer.key.slice(5) + '/comments'
          : operatorTarget ? '/operator-chats/' + peer.key + '/messages' : base + '/messages?' + new URLSearchParams({peer: peer.key});
        await api(path, 'POST', {client_id: current.ids[index],
          ...(source ? {[taskTarget ? 'forward_message_id' : appeal ? 'forward_task_message_id' : forwardField(operatorMessage(personal[sourceIndex]), operatorTarget)]: source.id,
            ...(taskTarget && appeal.channel ? {channel: appeal.channel} : {})}
            : {body: text, photo_id: photo!.id, ...(photo!.organization_id ? {photo_organization_id: photo!.organization_id} : {})})});
        current.completed++;
        setProgress(current.completed);
      }
      const {key, name, subtitle} = selection[0];
      const peer = subtitle ? {key, name, subtitle} : {key, name};
      if (selection.length === 1) onSent(peer);
      else onSent(peer, selection.length);
    } catch (error) {
      setError(error instanceof ApiError ? error.message : 'Не удалось подтвердить отправку. Повторите попытку.');
    } finally {
      pending.current = false; setBusy(false);
    }
  }

  const title = photo ? 'Переслать фото' : sources.length === 1 ? 'Переслать сообщение' : 'Переслать сообщения';
  const source = sources[0];
  const firstPhoto = personal[0]?.photo;
  const total = selection.length * (sources.length || 1);
  return <div className="modal-backdrop" onKeyDown={event => {
    if (event.key === 'Escape' && !pending.current) {event.stopPropagation(); onClose();}
    if (event.key !== 'Tab') return;
    const fields = form.current?.querySelectorAll<HTMLElement>('button:not(:disabled),textarea:not(:disabled),input:not(:disabled)');
    const first = fields?.[0], last = fields?.[fields.length - 1];
    if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
    if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
  }}><form ref={form} className="modal forward-photo-modal" role="dialog" aria-modal="true" aria-labelledby="inspection-forward-title" onSubmit={send}>
    <div className="section-title"><h2 id="inspection-forward-title">{title}</h2><button type="button" aria-label="Закрыть пересылку" disabled={busy} onClick={onClose}><X size={20}/></button></div>
    {photo && <div className="forward-photo-summary">{photo.preview_url ? <img src={photo.preview_url} alt={'Фотография №' + photo.id}/> : <Camera size={26}/>}<strong>Фотография #{photo.id}</strong></div>}
    {source && <div className="inspection-forward-summary">
      {sources.length > 1 ? <strong>Выбрано сообщений: {sources.length}</strong> : <>
        {firstPhoto && <strong>Фотография #{firstPhoto.id}</strong>}
        {!!source.screenshots?.length && <strong>Скриншоты: {source.screenshots.length}</strong>}
        {source.body && <p>{source.body}</p>}
      </>}
    </div>}
    <ErrorBox error={error}/>
    {progress > 0 && total > 1 && <p role="status" className="hint">Отправлено {progress} из {total}</p>}
    <label className="forward-search"><Search size={18} aria-hidden="true"/>
      <input type="search" aria-label={appeal && !appeal.personal ? 'Найти задачу' : 'Найти получателя'} value={search} disabled={busy || locked}
        maxLength={200} placeholder={appeal?.personal ? 'Имя получателя или номер задачи' : appeal ? 'Номер или название задачи' : 'Найти чат по имени или роли'}
        onChange={event => setSearch(event.target.value)}/></label>
    {(!appeal || appeal.personal) && !photo && <div className="forward-filters" role="group" aria-label="Список чатов">
      <button type="button" aria-pressed={filter === 'all'} disabled={busy || locked} onClick={() => setFilter('all')}>Все</button>
      <button type="button" aria-pressed={filter === 'recent'} disabled={busy || locked} onClick={() => setFilter('recent')}>Недавние</button>
      {(unified || appeal?.personal) && <>
        <button type="button" aria-pressed={filter === 'staff'} disabled={busy || locked} onClick={() => setFilter('staff')}>Коллеги</button>
        <button type="button" aria-pressed={filter === 'inspector'} disabled={busy || locked} onClick={() => setFilter('inspector')}>Проверяющие</button>
      </>}
      {appeal?.personal && <button type="button" aria-pressed={filter === 'task'} disabled={busy || locked} onClick={() => setFilter('task')}>Задачи</button>}
    </div>}
    <div className="forward-destinations" role="group" aria-label={appeal && !appeal.personal ? 'Задачи' : 'Получатели'} aria-busy={searching || loading}>
      {searching || loading ? <p role="status">Загружаем…</p> : visible.map(item => {
        const selected = selection.some(peer => peer.key === item.key);
        return <button key={item.key} type="button" aria-pressed={selected} disabled={busy || locked} onClick={() => toggle(item)}>
          <Avatar name={item.name} src={item.avatar || null}/>
          <span className="forward-recipient"><strong>{item.name}</strong>{item.subtitle && <small>{item.subtitle}</small>}</span>
          <span className="forward-select-mark" aria-hidden="true">{selected && <Check size={14}/>}</span>
        </button>;
      })}
      {!searching && !loading && !visible.length && !error && <p>{term ? 'По этому запросу ничего не найдено.' : appeal ? 'Нет доступных задач.' : 'В этом списке пока нет чатов.'}</p>}
    </div>
    {photo && <label>Комментарий (необязательно)<textarea rows={3} maxLength={4000} disabled={busy} value={body} onChange={event => setBody(event.target.value)}/></label>}
    {selection.length > 0 && <div className="forward-selected" aria-label="Выбранные получатели">{selection.map(peer => <button key={peer.key} type="button"
      disabled={busy || locked} aria-label={'Убрать из получателей: ' + peer.name} onClick={() => toggle(peer)}>{peer.name}<X size={14}/></button>)}</div>}
    <button className="primary" disabled={busy || !selection.length || loading || searching}><Send size={17}/>{busy ? 'Отправляем…' : locked ? 'Повторить отправку' : selection.length > 1 ? 'Переслать · ' + selection.length : 'Переслать'}</button>
  </form></div>;
}
