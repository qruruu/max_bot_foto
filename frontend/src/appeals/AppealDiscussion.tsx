import { useEffect, useRef, useState } from 'react';
import { History, LockKeyhole, RefreshCw, Send } from 'lucide-react';
import { api, ApiError } from '../api';
import { appealStatuses } from './Wall';

type AppealEvent = {id: number; kind: string; actor_name: string; actor_role: string; status: string;
  comment: string; visibility: string; created_at: string};
type EventPage = {items: AppealEvent[]; has_more: boolean; can_comment: boolean};
const kinds: Record<string, string> = {CREATED: 'Обращение создано', ASSIGNED: 'Назначен исполнитель',
  INSTRUCTION: 'Комментарий к задаче', STATUS: 'Изменён статус', RESULT: 'Получен результат исполнителя',
  CLOSED: 'Обращение закрыто', ARCHIVED: 'Перенесено в архив', RESTORED: 'Возвращено из архива',
  NOTE: 'Изменена внутренняя заметка', COMMENT: 'Сообщение в обсуждении', IMPORTED: 'Состояние до включения истории'};
const roles: Record<string, string> = {INSPECTOR: 'Проверяющий', ADMIN_OPERATOR: 'Администратор', OPERATOR: 'Оператор', CITIZEN: 'Житель'};
const date = (value: string) => new Date(value).toLocaleString('ru-RU', {dateStyle: 'short', timeStyle: 'short'});
const initials = (name: string) => (name.match(/[\p{L}\p{N}]+/gu) || []).slice(0, 2).map(part => part[0]).join('').toUpperCase();

export default function AppealDiscussion({endpoint, archived}: {endpoint: string; archived: boolean}) {
  const [events, setEvents] = useState<AppealEvent[]>([]), [tab, setTab] = useState<'chat' | 'history'>('chat');
  const [loading, setLoading] = useState(true), [more, setMore] = useState(false), [allowed, setAllowed] = useState(!archived);
  const [text, setText] = useState(''), [busy, setBusy] = useState(false), [pending, setPending] = useState(false), [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const clientId = useRef<string>(crypto.randomUUID()), newest = useRef(0), oldest = useRef(0), active = useRef(true), sending = useRef(false);
  function merge(value: EventPage, older = false) {
    if (!active.current) return;
    setEvents(current => [...new Map([...current, ...value.items].map(item => [item.id, item])).values()].sort((a, b) => a.id - b.id));
    for (const item of value.items) {newest.current = Math.max(newest.current, item.id); oldest.current = oldest.current ? Math.min(oldest.current, item.id) : item.id;}
    if (older || !newest.current) setMore(value.has_more);
    setAllowed(value.can_comment); setLoading(false);
  }
  useEffect(() => {
    active.current = true; newest.current = oldest.current = 0; setError('');
    const controller = new AbortController(); let refreshing = false;
    api<EventPage>(endpoint + '/events', 'GET', undefined, controller.signal).then(value => {merge(value); setMore(value.has_more);})
      .catch(reason => {if (!controller.signal.aborted) {setError(reason.message); setLoading(false);}});
    async function refresh() {
      if (document.hidden || refreshing) return;
      refreshing = true;
      try {merge(await api<EventPage>(endpoint + '/events?after=' + newest.current, 'GET', undefined, controller.signal));}
      catch {} finally {refreshing = false;}
    }
    const timer = window.setInterval(() => void refresh(), 10_000);
    window.addEventListener('focus', refresh);
    return () => {active.current = false; controller.abort(); window.clearInterval(timer); window.removeEventListener('focus', refresh);};
  }, [endpoint, revision]);
  async function older() {
    if (busy) return; setBusy(true); setError('');
    try {merge(await api<EventPage>(endpoint + '/events?before=' + oldest.current), true);}
    catch (reason) {setError((reason as Error).message);} finally {if (active.current) setBusy(false);}
  }
  async function send() {
    if (sending.current || !text.trim()) return;
    sending.current = true; setBusy(true); setPending(true); setError('');
    try {
      await api(endpoint + '/comments', 'POST', {comment: text.trim(), client_id: clientId.current});
      if (!active.current) return;
      setText(''); setPending(false); clientId.current = crypto.randomUUID();
      merge(await api<EventPage>(endpoint + '/events?after=' + newest.current));
    } catch (reason) {
      if (reason instanceof ApiError && reason.status >= 400 && reason.status < 500) setPending(false);
      if (active.current) setError((reason as Error).message);
    } finally {sending.current = false; if (active.current) setBusy(false);}
  }
  const visible = tab === 'chat' ? events.filter(item => item.kind === 'COMMENT') : events;
  return <section className="panel appeal-discussion" aria-label="Обсуждение и история обращения">
    <div className="appeal-discussion-toolbar"><div role="tablist" aria-label="Обсуждение и события"><button role="tab" aria-selected={tab === 'chat'} onClick={() => setTab('chat')}>Обсуждение</button><button role="tab" aria-selected={tab === 'history'} onClick={() => setTab('history')}><History size={15}/>История событий</button></div><button type="button" disabled={busy} aria-label="Обновить обсуждение" onClick={() => setRevision(value => value + 1)}><RefreshCw size={16}/></button></div>
    <p className="appeal-discussion-privacy" title="Видно администратору, проверяющим и назначенному оператору. На стене «Сигнала» обсуждения нет."><LockKeyhole size={12}/>Внутреннее обсуждение</p>
    {more && <button disabled={busy} onClick={() => void older()}>Показать более ранние события</button>}
    <div className="appeal-event-list" role="log" aria-label={tab === 'chat' ? 'Сообщения по обращению' : 'События обращения'} aria-live="polite">
      {loading ? <p className="hint">Загружаем…</p> : !visible.length ? <p className="hint">{tab === 'chat' ? 'Здесь можно обсудить обращение.' : 'Событий пока нет.'}</p> : visible.map(item => <article key={item.id} className={'appeal-event ' + (item.kind === 'COMMENT' ? 'appeal-message' : '')}>
        <span className="appeal-message-avatar" aria-hidden="true">{initials(item.actor_name)}</span><div className="appeal-message-body"><header><strong title={roles[item.actor_role]}>{item.actor_name}</strong><time dateTime={item.created_at}>{date(item.created_at)}</time></header>
        {tab === 'history' && <p className="appeal-event-kind">{kinds[item.kind] || item.kind}{item.status && ' · ' + (appealStatuses[item.status] || item.status)}</p>}
        {item.comment && <p className="owner-appeal-text">{item.comment}</p>}{item.visibility !== 'STAFF' && <small className="hint">{item.visibility === 'ADMIN' ? 'Только администраторам' : 'Администратору и исполнителю'}</small>}</div>
      </article>)}
    </div>
    {tab === 'chat' && (archived || !allowed ? <p className="hint appeal-discussion-readonly">Обсуждение в архиве доступно для чтения.</p> : <form className="appeal-discussion-compose" onSubmit={event => {event.preventDefault(); void send();}}>
      <textarea aria-label="Сообщение по обращению" required maxLength={4000} rows={2} disabled={busy || pending} value={text} onChange={event => setText(event.target.value)} placeholder="Задать вопрос или написать ответ…"/>
      {pending && !busy && <p className="hint">Повторите отправку — сообщение не продублируется.</p>}
      <button className="primary" disabled={busy || !text.trim()} title={pending ? 'Повторить отправку' : 'Отправить сообщение'}><Send size={18}/><span className="appeal-sr-only">{busy ? 'Отправляем…' : pending ? 'Повторить отправку' : 'Отправить сообщение'}</span></button>
    </form>)}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
