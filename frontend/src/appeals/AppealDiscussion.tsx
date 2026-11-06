import { useEffect, useRef, useState } from 'react';
import { History, LockKeyhole } from 'lucide-react';
import { api, ApiError } from '../api';
import { appealStatuses } from './Wall';
import ChatComposer from '../ChatComposer';
import { ChatMessageActions, ChatMessageContent, revealMessage } from '../ChatMessageContent';
import { encodeScreenshots, useChatExtras } from '../chatContent';
import type { ChatContent } from '../chatContent';
import Forward from '../inspection/Forward';

type AppealEvent = ChatContent & {id: number; kind: string; actor_name: string; actor_role: string; status: string;
  comment: string; visibility: string; created_at: string; files?: {id: string; name: string; url: string}[]};
type EventPage = {items: AppealEvent[]; has_more: boolean; can_comment: boolean; unanswered_comments?: number};
const kinds: Record<string, string> = {CREATED: 'Обращение создано', ASSIGNED: 'Назначен исполнитель',
  INSTRUCTION: 'Комментарий к задаче', STATUS: 'Изменён статус', RESULT: 'Получен результат исполнителя',
  CLOSED: 'Обращение закрыто', ARCHIVED: 'Перенесено в архив', RESTORED: 'Возвращено из архива',
  NOTE: 'Изменена внутренняя заметка', WORK_TYPE: 'Изменён вид работ', DEADLINE: 'Изменён срок исполнения', COMMENT: 'Сообщение в обсуждении', IMPORTED: 'Состояние до включения истории'};
const roles: Record<string, string> = {INSPECTOR: 'Проверяющий', ADMIN_OPERATOR: 'Администратор', OPERATOR: 'Оператор', CITIZEN: 'Житель'};
const date = (value: string) => new Date(value).toLocaleString('ru-RU', {dateStyle: 'short', timeStyle: 'short'});
const initials = (name: string) => (name.match(/[\p{L}\p{N}]+/gu) || []).slice(0, 2).map(part => part[0]).join('').toUpperCase();

export default function AppealDiscussion({endpoint, archived, channel, title = 'Внутреннее обсуждение', readonlyReason, onUnreadChange, openTask}: {endpoint: string; archived: boolean; channel?: 'inspector' | 'executor'; title?: string; readonlyReason?: string; onUnreadChange?: (count: number) => void; openTask?: (id: number) => void}) {
  const eventsUrl = endpoint + '/events';
  const query = (suffix = '') => eventsUrl + (channel ? '?channel=' + channel + (suffix ? '&' + suffix : '') : suffix ? '?' + suffix : '');
  const {extras, update, clearSent} = useChatExtras(endpoint + ':' + channel);
  const [encodedFiles, setEncodedFiles] = useState<string[] | null>(null);
  const [forwarding, setForwarding] = useState<AppealEvent | null>(null);
  const log = useRef<HTMLDivElement>(null), stickToBottom = useRef(true);
  const [events, setEvents] = useState<AppealEvent[]>([]), [tab, setTab] = useState<'chat' | 'history'>('chat');
  const [loading, setLoading] = useState(true), [more, setMore] = useState(false), [allowed, setAllowed] = useState(!archived);
  const [text, setText] = useState(''), [busy, setBusy] = useState(false), [pending, setPending] = useState(false), [error, setError] = useState('');
  useEffect(() => {
    if (stickToBottom.current && log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [events, tab]);
  const unreadCallback = useRef(onUnreadChange); unreadCallback.current = onUnreadChange;
  const clientId = useRef<string>(crypto.randomUUID()), newest = useRef(0), oldest = useRef(0), active = useRef(true), sending = useRef(false);
  function merge(value: EventPage, older = false) {
    if (!active.current) return;
    if (value.unanswered_comments !== undefined) unreadCallback.current?.(value.unanswered_comments);
    setEvents(current => [...new Map([...current, ...value.items].map(item => [item.id, item])).values()].sort((a, b) => a.id - b.id));
    for (const item of value.items) {newest.current = Math.max(newest.current, item.id); oldest.current = oldest.current ? Math.min(oldest.current, item.id) : item.id;}
    if (older || !newest.current) setMore(value.has_more);
    setAllowed(value.can_comment); setLoading(false);
  }
  useEffect(() => {
    active.current = true; newest.current = oldest.current = 0; setError(''); setEvents([]);
    const controller = new AbortController(); let refreshing = false;
    api<EventPage>(query(), 'GET', undefined, controller.signal).then(value => {merge(value); setMore(value.has_more);})
      .catch(reason => {if (!controller.signal.aborted) {setError(reason.message); setLoading(false);}});
    async function refresh() {
      if (document.hidden || refreshing) return;
      refreshing = true;
      try {merge(await api<EventPage>(query('after=' + newest.current), 'GET', undefined, controller.signal));}
      catch {} finally {refreshing = false;}
    }
    const timer = window.setInterval(() => void refresh(), 10_000);
    window.addEventListener('focus', refresh);
    return () => {active.current = false; controller.abort(); window.clearInterval(timer); window.removeEventListener('focus', refresh);};
  }, [endpoint, channel]);
  async function older() {
    if (busy) return; stickToBottom.current = false; setBusy(true); setError('');
    try {merge(await api<EventPage>(query('before=' + oldest.current)), true);}
    catch (reason) {setError((reason as Error).message);} finally {if (active.current) setBusy(false);}
  }
  async function send() {
    if (sending.current || (!text.trim() && !extras.files.length)) return;
    sending.current = true; setBusy(true); setPending(true); setError('');
    try {
      let encoded = encodedFiles;
      if (!encoded) {
        encoded = await encodeScreenshots(extras.files, 35 * 1024 * 1024);
        setEncodedFiles(encoded);
      }
      await api(endpoint + '/comments', 'POST', {comment: text.trim(), client_id: clientId.current, channel, screenshots: encoded, ...(extras.reply ? {reply_to_id: extras.reply.id} : {})});
      unreadCallback.current?.(0);
      window.dispatchEvent(new Event('appeal-discussion-changed'));
      if (!active.current) return;
      stickToBottom.current = true; setText(''); clearSent(extras); setEncodedFiles(null); setPending(false); clientId.current = crypto.randomUUID();
      merge(await api<EventPage>(query('after=' + newest.current)));
    } catch (reason) {
      if (reason instanceof ApiError && reason.status >= 400 && reason.status < 500) {setPending(false); setEncodedFiles(null); clientId.current = crypto.randomUUID();}
      if (active.current) setError((reason as Error).message);
    } finally {sending.current = false; if (active.current) setBusy(false);}
  }
  const visible = tab === 'chat' ? events.filter(item => item.kind === 'COMMENT') : events;
  const visibleMessageIds = new Set(visible.map(item => item.id));
  return <section className="panel appeal-discussion" aria-label={title}>
    <div className="appeal-discussion-heading"><h3>Переписка</h3><span title={channel === 'inspector'
      ? 'Доступно администратору и проверяющему' : 'Доступно администратору и исполнителю'}><LockKeyhole size={15}/></span></div>
    <div className="appeal-discussion-toolbar"><div role="tablist" aria-label="Обсуждение и события"><button role="tab" aria-selected={tab === 'chat'} onClick={() => setTab('chat')}>Сообщения</button><button role="tab" aria-selected={tab === 'history'} onClick={() => setTab('history')}><History size={15}/>История</button></div></div>
    {more && <button disabled={busy} onClick={() => void older()}>Показать более ранние события</button>}
    <div className={`appeal-event-list${!loading && !visible.length ? ' is-empty' : ''}`} ref={log} onScroll={event => {
      const element = event.currentTarget;
      stickToBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 90;
    }} role="log" aria-label={tab === 'chat' ? 'Сообщения по обращению' : 'События обращения'} aria-live="polite">
      {loading ? <p className="hint">Загружаем…</p> : !visible.length ? <p className="hint">{tab === 'chat' ? 'Сообщений пока нет.' : 'Событий пока нет.'}</p>
        : visible.map(item => <article key={item.id} data-message-id={item.id} tabIndex={-1} className={'appeal-event ' + (item.kind === 'COMMENT' ? 'appeal-message' : '')}>
          <span className="appeal-message-avatar" aria-hidden="true">{initials(item.actor_name)}</span>
          <div className="appeal-message-body">
            <header><strong title={roles[item.actor_role]}>{item.actor_name}</strong><time dateTime={item.created_at}>{date(item.created_at)}</time></header>
            {tab === 'history' && <p className="appeal-event-kind">{kinds[item.kind] || item.kind}{item.status && ' · ' + (appealStatuses[item.status] || item.status)}</p>}
            <ChatMessageContent message={{...item, forwarded: !!item.forwarded_name, screenshots: item.files?.map(file => file.url)}} jump={item.reply && visibleMessageIds.has(item.reply.id) ? id => revealMessage(log.current, id) : undefined}/>
            {item.comment && <p className="owner-appeal-text">{item.comment}</p>}
            {item.kind === 'COMMENT' && tab === 'chat' && <ChatMessageActions id={item.id}
              reply={!archived && allowed && !pending ? () => update({reply: {id: item.id, author: item.actor_name, body: item.comment.slice(0, 180) || 'Скриншот'}}) : undefined}
              forward={openTask ? () => setForwarding(item) : undefined}/>}
          </div>
        </article>)}
    </div>
    {tab === 'chat' && (archived || !allowed ? <p className="hint appeal-discussion-readonly">{readonlyReason || 'Переписка доступна для чтения.'}</p>
      : <ChatComposer label="Сообщение по обращению" draft={text} changeDraft={value => {setText(value); setError('');}}
        extras={extras} changeExtras={values => {update(values); setEncodedFiles(null); setError('');}}
        send={() => void send()} sending={busy} pending={pending} error={error}/>)}
    {error && (tab === 'history' || archived || !allowed) && <p className="error" role="alert">{error}</p>}
    {forwarding && <Forward key={forwarding.id} appeal={{endpoint, channel, id: forwarding.id, body: forwarding.comment, screenshots: forwarding.files?.map(file => file.url)}}
      onClose={() => setForwarding(null)} onSent={peer => {
        setForwarding(null);
        window.dispatchEvent(new Event('appeal-discussion-changed'));
        openTask?.(Number(peer.key));
      }}/>}
  </section>;
}
