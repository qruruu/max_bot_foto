import LinkedText from '../LinkedText';
import { useEffect, useRef, useState } from 'react';
import { Check, CheckCheck, LockKeyhole, X } from 'lucide-react';
import { api, ApiError } from '../api';
import ChatComposer from '../ChatComposer';
import { ChatMessageContent, revealMessage } from '../ChatMessageContent';
import ChatMessageMenu from '../ChatMessageMenu';
import { ChatSelectionBar, useChatSelection } from '../ChatSelection';
import { encodeScreenshots, useChatExtras } from '../chatContent';
import type { ChatContent } from '../chatContent';
import Forward from '../inspection/Forward';

type AppealEvent = ChatContent & {id: number; kind: string; actor_name: string; actor_role: string; status: string;
  comment: string; outgoing?: boolean; read_at?: string | null; visibility: string; created_at: string; files?: {id: string; name: string; url: string}[]};
type EventPage = {items: AppealEvent[]; has_more: boolean; can_comment: boolean; unanswered_comments?: number; read_ids?: number[]};
const roles: Record<string, string> = {INSPECTOR: 'Проверяющий', ADMIN_OPERATOR: 'Администратор', OPERATOR: 'Оператор', CITIZEN: 'Житель'};
const date = (value: string) => new Date(value).toLocaleString('ru-RU', {dateStyle: 'short', timeStyle: 'short'});
const initials = (name: string) => (name.match(/[\p{L}\p{N}]+/gu) || []).slice(0, 2).map(part => part[0]).join('').toUpperCase();

export default function AppealDiscussion({endpoint, archived, channel, title = 'Внутреннее обсуждение', readonlyReason, onUnreadChange, openTask, visibleTab = true, forwardToContacts = false, attachFromArchive}: {endpoint: string; archived: boolean; channel?: 'inspector' | 'executor'; title?: string; readonlyReason?: string; onUnreadChange?: (count: number) => void; openTask?: (id: number) => void; visibleTab?: boolean; forwardToContacts?: boolean; attachFromArchive?: () => void}) {
  const eventsUrl = endpoint + '/events';
  const query = (suffix = '') => eventsUrl + (channel ? '?channel=' + channel + (suffix ? '&' + suffix : '') : suffix ? '?' + suffix : '');
  const {extras, update, clearSent} = useChatExtras(endpoint + ':' + channel);
  const [encodedFiles, setEncodedFiles] = useState<string[] | null>(null);
  const [forwardNotice, setForwardNotice] = useState('');
  const [forwarding, setForwarding] = useState<AppealEvent[] | null>(null);
  const selection = useChatSelection(endpoint + ':' + channel);
  const [receipts, setReceipts] = useState<Set<number>>(() => new Set());
  const markedThrough = useRef(0), marking = useRef(false);
  const log = useRef<HTMLDivElement>(null), stickToBottom = useRef(true);
  const [events, setEvents] = useState<AppealEvent[]>([]);
  const [loading, setLoading] = useState(true), [more, setMore] = useState(false), [allowed, setAllowed] = useState(!archived);
  const [text, setText] = useState(''), [busy, setBusy] = useState(false), [pending, setPending] = useState(false), [error, setError] = useState('');
  useEffect(() => {
    if (stickToBottom.current && log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [events]);
  const unreadCallback = useRef(onUnreadChange); unreadCallback.current = onUnreadChange;
  const clientId = useRef<string>(crypto.randomUUID()), newest = useRef(0), oldest = useRef(0), active = useRef(true), sending = useRef(false);
  function merge(value: EventPage, older = false) {
    if (!active.current) return;
    if (value.read_ids?.length) setReceipts(current => new Set([...current, ...value.read_ids!]));
    if (value.unanswered_comments !== undefined) unreadCallback.current?.(value.unanswered_comments);
    setEvents(current => [...new Map([...current, ...value.items].map(item => [item.id, item])).values()].sort((a, b) => a.id - b.id));
    for (const item of value.items) {newest.current = Math.max(newest.current, item.id); oldest.current = oldest.current ? Math.min(oldest.current, item.id) : item.id;}
    if (older || !newest.current) setMore(value.has_more);
    setAllowed(value.can_comment); setLoading(false);
  }
  useEffect(() => {
    active.current = true; newest.current = oldest.current = markedThrough.current = 0; setError(''); setEvents([]); setReceipts(new Set());
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
  useEffect(() => {
    if (!visibleTab) return;
    const controller = new AbortController();
    async function acknowledge() {
      if (document.hidden || !stickToBottom.current || marking.current) return;
      const through = events.filter(item => item.kind === 'COMMENT' && item.outgoing === false && !item.read_at).at(-1)?.id || 0;
      if (through <= markedThrough.current) return;
      marking.current = true;
      try {
        await api(eventsUrl + '/read', 'POST', {through_id: through, channel}, controller.signal);
        if (!controller.signal.aborted) markedThrough.current = through;
      } catch {} finally {marking.current = false;}
    }
    void acknowledge();
    document.addEventListener('visibilitychange', acknowledge);
    log.current?.addEventListener('scroll', acknowledge);
    const element = log.current;
    return () => {
      controller.abort();
      document.removeEventListener('visibilitychange', acknowledge);
      element?.removeEventListener('scroll', acknowledge);
    };
  }, [events, channel, eventsUrl, visibleTab]);
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
        encoded = await encodeScreenshots(extras.files, 35 * 1024 * 1024, 75 * 1024 * 1024);
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
  const visible = events.filter(item => item.kind === 'COMMENT');
  const visibleMessageIds = new Set(visible.map(item => item.id));
  return <section className="panel appeal-discussion" aria-label={title}>
    <div className="appeal-discussion-heading"><h3>{title}</h3><span title={channel === 'inspector'
      ? 'Доступно администратору и проверяющему' : 'Доступно администратору и исполнителю'}><LockKeyhole size={15}/></span></div>
    {forwardNotice && <div className="chat-forwarded-notice"><span role="status">{forwardNotice}</span><button type="button" className="chat-forwarded-close" aria-label="Скрыть подтверждение" onClick={() => setForwardNotice('')}><X size={15}/></button></div>}
    {more && <button disabled={busy} onClick={() => void older()}>Показать более ранние сообщения</button>}
    <div className={`appeal-event-list${!loading && !visible.length ? ' is-empty' : ''}`} ref={log} onScroll={event => {
      const element = event.currentTarget;
      stickToBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 90;
    }} role="log" aria-label="Сообщения по обращению" aria-live="polite">
      {loading ? <p className="hint">Загружаем…</p> : !visible.length ? <p className="hint">Сообщений пока нет.</p>
        : visible.map(item => <ChatMessageMenu as="article" key={item.id} id={item.id} className="appeal-event appeal-message"
          reply={!archived && allowed && !pending
            ? () => update({reply: {id: item.id, author: item.actor_name, body: item.comment.slice(0, 180) || 'Скриншот'}}) : undefined}
          forward={openTask ? () => setForwarding([item]) : undefined}
          select={openTask ? () => selection.toggle(item.id) : undefined}
          selected={selection.ids.length ? selection.ids.includes(item.id) : undefined}>
          <span className="appeal-message-avatar" aria-hidden="true">{initials(item.actor_name)}</span>
          <div className="appeal-message-body">
            <header><strong title={roles[item.actor_role]}>{item.actor_name}</strong><span className="appeal-message-meta"><time dateTime={item.created_at}>{date(item.created_at)}</time>
              {item.outgoing && (item.read_at || receipts.has(item.id)
                ? <span className="message-read" aria-label="Прочитано участником" title="Прочитано участником"><CheckCheck size={16}/></span>
                : <span aria-label="Отправлено" title="Отправлено"><Check size={16}/></span>)}</span></header>
            <ChatMessageContent message={{...item, forwarded: !!item.forwarded_name, screenshots: item.files?.map(file => file.url)}} jump={item.reply && visibleMessageIds.has(item.reply.id) ? id => revealMessage(log.current, id) : undefined}/>
            {item.comment && <p className="owner-appeal-text"><LinkedText>{item.comment}</LinkedText></p>}
          </div>
        </ChatMessageMenu>)}
    </div>
    {selection.ids.length > 0 && <ChatSelectionBar count={selection.ids.length} cancel={selection.clear}
      forward={() => setForwarding(visible.filter(item => selection.ids.includes(item.id)))}/>}
    <div hidden={selection.ids.length > 0}>{archived || !allowed ? <p className="hint appeal-discussion-readonly">{readonlyReason || 'Переписка доступна для чтения.'}</p>
      : <ChatComposer label="Сообщение по обращению" draft={text} changeDraft={value => {setText(value); setError('');}}
        extras={extras} changeExtras={values => {update(values); setEncodedFiles(null); setError('');}}
        attachFromArchive={attachFromArchive} send={() => void send()} sending={busy} pending={pending} error={error}/>}</div>
    {error && (archived || !allowed) && <p className="error" role="alert">{error}</p>}
    {!!forwarding?.length && <Forward appeal={{endpoint, channel, personal: forwardToContacts, messages: forwarding.map(item => ({
      id: item.id, body: item.comment, screenshots: item.files?.map(file => file.url),
    }))}}
      onClose={() => setForwarding(null)} onSent={(peer, count) => {
        selection.clear(); setForwarding(null);
        window.dispatchEvent(new Event('appeal-discussion-changed'));
        if (!count && peer.key.startsWith('task:')) openTask?.(Number(peer.key.slice(5)));
        else setForwardNotice(count ? 'Переслано в чаты · ' + count : 'Переслано · ' + peer.name);
      }}/>}
  </section>;
}
