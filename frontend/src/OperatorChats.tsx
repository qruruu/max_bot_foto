import { Fragment, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { ArrowLeft, Camera, Check, CheckCheck, MessageCircle, RefreshCw, Search, Send } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { ApiError, api } from './api';
import { ErrorBox, useApp } from './App';
import Avatar from './Avatar';
import { useOperatorChats } from './OperatorChatsProvider';
import { mergeMessages, messageDay, messagePreview, messageTime, operatorPhotoLink } from './operatorChatData';
import type { ContactPage, MessagePage, OperatorContact, OperatorMessage } from './operatorChatData';
import './operator-chats.css';

export default function OperatorChats() {
  const {user, meta} = useApp();
  const {refreshUnread} = useOperatorChats();
  const [params, setParams] = useSearchParams();
  const selected = params.get('with') || '';
  const peerId = /^[1-9]\d*$/.test(selected) ? Number(selected) : null;
  const currentPeer = useRef(peerId);
  currentPeer.current = peerId;
  const [contacts, setContacts] = useState<OperatorContact[]>([]), [search, setSearch] = useState('');
  const [contactError, setContactError] = useState(''), [contactLoading, setContactLoading] = useState(true);
  const [messages, setMessages] = useState<OperatorMessage[]>([]), [historyError, setHistoryError] = useState('');
  const [loading, setLoading] = useState(false), [hasOlder, setHasOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false), [readThrough, setReadThrough] = useState(0);
  const [drafts, setDrafts] = useState<Record<number, string>>({}), [sendError, setSendError] = useState('');
  const [sendingPeer, setSendingPeer] = useState<number | null>(null), [revision, setRevision] = useState(0);
  const pending = useRef<{peerId: number; body: string; clientId: string} | null>(null);
  const list = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const scrollAnchor = useRef<{height: number; top: number} | null>(null);
  const olderRequest = useRef<AbortController | null>(null);
  const peer = contacts.find(contact => contact.id === peerId);
  const draft = peerId ? drafts[peerId] || '' : '';

  useEffect(() => {
    const controller = new AbortController();
    let busy = false;
    const refresh = async () => {
      if (busy || document.hidden) return;
      busy = true;
      try {
        const result = await api<ContactPage>('/operator-chats', 'GET', undefined, controller.signal);
        if (!controller.signal.aborted) {setContacts(result.items); setContactError('');}
      } catch (error) {if (!controller.signal.aborted) setContactError((error as Error).message);}
      finally {busy = false; if (!controller.signal.aborted) setContactLoading(false);}
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    const visible = () => {void refresh();};
    document.addEventListener('visibilitychange', visible);
    return () => {controller.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', visible);};
  }, [revision]);

  useEffect(() => {
    setMessages([]); setHistoryError(''); setSendError(''); setHasOlder(false); setReadThrough(0);
    setLoadingOlder(false); scrollAnchor.current = null; stickToBottom.current = true;
    if (!peerId) {setLoading(false); return;}
    const controller = new AbortController();
    let busy = false, cursor = 0, acknowledged = 0, initial = true;
    setLoading(true);
    const refresh = async () => {
      if (busy || document.hidden) return;
      busy = true;
      try {
        const result = await api<MessagePage>(`/operator-chats/${peerId}/messages${initial ? '' : '?after_id=' + cursor}`, 'GET', undefined, controller.signal);
        if (controller.signal.aborted) return;
        const firstPage = initial;
        if (result.items.length) {
          const element = list.current;
          stickToBottom.current = initial || !element || element.scrollHeight - element.scrollTop - element.clientHeight < 90;
          setMessages(previous => firstPage ? result.items : mergeMessages(previous, result.items));
          cursor = Math.max(cursor, ...result.items.map(message => message.id));
        }
        if (initial) setHasOlder(result.has_older);
        initial = false;
        setReadThrough(result.peer_read_through_id); setHistoryError(''); setLoading(false);
        if (cursor > acknowledged && !document.hidden) {
          await api(`/operator-chats/${peerId}/read`, 'POST', {through_id: cursor}, controller.signal);
          acknowledged = cursor;
          if (!controller.signal.aborted) {
            setContacts(previous => previous.map(contact => contact.id === peerId ? {...contact, unread: 0} : contact));
            void refreshUnread();
          }
        }
      } catch (error) {if (!controller.signal.aborted) {setHistoryError((error as Error).message); setLoading(false);}}
      finally {busy = false;}
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    const visible = () => {void refresh();};
    document.addEventListener('visibilitychange', visible);
    return () => {
      controller.abort(); olderRequest.current?.abort(); window.clearInterval(timer);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [peerId, revision, refreshUnread]);

  useLayoutEffect(() => {
    const element = list.current;
    if (!element) return;
    if (scrollAnchor.current) {
      element.scrollTop = scrollAnchor.current.top + element.scrollHeight - scrollAnchor.current.height;
      scrollAnchor.current = null;
    } else if (stickToBottom.current) element.scrollTop = element.scrollHeight;
  }, [messages]);

  async function older() {
    if (!peerId || !messages.length || loadingOlder) return;
    const target = peerId, controller = new AbortController();
    olderRequest.current = controller;
    setLoadingOlder(true);
    try {
      const result = await api<MessagePage>(`/operator-chats/${target}/messages?before_id=${messages[0].id}`, 'GET', undefined, controller.signal);
      if (currentPeer.current !== target || controller.signal.aborted) return;
      if (list.current) scrollAnchor.current = {height: list.current.scrollHeight, top: list.current.scrollTop};
      setMessages(previous => mergeMessages(previous, result.items)); setHasOlder(result.has_older);
    } catch (error) {if (!controller.signal.aborted && currentPeer.current === target) setHistoryError((error as Error).message);}
    finally {if (currentPeer.current === target) setLoadingOlder(false);}
  }

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const body = draft.trim();
    if (!peerId || !peer?.active || !body || sendingPeer || loading) return;
    const target = peerId;
    const attempt = pending.current?.peerId === target && pending.current.body === body
      ? pending.current : {peerId: target, body, clientId: crypto.randomUUID()};
    pending.current = attempt;
    setSendingPeer(target); setSendError('');
    try {
      const message = await api<OperatorMessage>(`/operator-chats/${target}/messages`, 'POST', {body, client_id: attempt.clientId});
      if (currentPeer.current === target) {
        stickToBottom.current = true;
        setMessages(previous => mergeMessages(previous, [message]));
      }
      setDrafts(previous => previous[target]?.trim() === body ? {...previous, [target]: ''} : previous);
      if (pending.current === attempt) pending.current = null;
      setContacts(previous => previous.map(contact => contact.id === target ? {...contact, last_message: message} : contact));
    } catch (error) {
      if (currentPeer.current === target) setSendError(error instanceof ApiError ? error.message : 'Не удалось подтвердить отправку. Повторите попытку — текст сохранён.');
    } finally {setSendingPeer(null);}
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); void send();}
  }

  const filtered = contacts.filter(contact => contact.name.toLocaleLowerCase('ru-RU').includes(search.toLocaleLowerCase('ru-RU')));
  return <>
    <header className="page-header"><div><span className="eyebrow">ОБЩЕНИЕ В КОМАНДЕ</span><h1>Чаты операторов</h1><p>Личная переписка с коллегами внутри панели.</p></div>
      <button onClick={() => setRevision(value => value + 1)} aria-label="Обновить чаты"><RefreshCw size={18}/></button>
    </header>
    <section className={`panel operator-chats ${peerId ? 'conversation-open' : ''}`}>
      <aside className="operator-chat-contacts" aria-label="Операторы для переписки">
        <label className="operator-chat-search"><Search size={16} aria-hidden="true"/><input aria-label="Найти оператора" placeholder="Найти оператора…" value={search} onChange={event => setSearch(event.target.value)}/></label>
        <ErrorBox error={contactError}/>
        <div className="operator-chat-contact-list">
          {contactLoading && <p className="operator-chat-note">Загружаем операторов…</p>}
          {!contactLoading && !filtered.length && <p className="operator-chat-note">{search ? 'Операторов не найдено.' : 'Другие операторы пока не добавлены.'}</p>}
          {filtered.map(contact => <button type="button" key={contact.id} className={`operator-chat-contact ${peerId === contact.id ? 'selected' : ''}`} onClick={() => setParams({with: String(contact.id)})} aria-pressed={peerId === contact.id}>
            <Avatar name={contact.name} src={contact.avatar_url}/>
            <span className="operator-chat-contact-copy"><strong>{contact.name}</strong><span>{contact.last_message ? `${contact.last_message.sender_id === user.id ? 'Вы: ' : ''}${messagePreview(contact.last_message)}` : contact.active ? 'Начать переписку' : 'Аккаунт отключён'}</span></span>
            <span className="operator-chat-contact-meta">{contact.last_message && <time dateTime={contact.last_message.created_at}>{messageTime(contact.last_message.created_at, meta.timezone)}</time>}{contact.unread > 0 && <span className="operator-chat-unread" aria-label={`Непрочитанных: ${contact.unread}`}>{contact.unread > 99 ? '99+' : contact.unread}</span>}</span>
          </button>)}
        </div>
      </aside>
      <div className="operator-conversation">
        {!peerId ? <div className="operator-chat-empty"><MessageCircle size={44}/><h2>Выберите коллегу</h2><p>Откройте диалог из списка операторов, чтобы начать переписку.</p></div> : <>
          <div className="operator-conversation-header"><button type="button" className="operator-chat-back" aria-label="К списку операторов" onClick={() => setParams({})}><ArrowLeft size={18}/></button><Avatar name={peer?.name || 'Оператор'} src={peer?.avatar_url || null}/><div><strong>{peer?.name || 'Переписка'}</strong><span>{peer ? peer.active ? peer.role === 'ADMIN_OPERATOR' ? 'Администратор' : 'Оператор' : 'Аккаунт отключён' : 'Загружаем…'}</span></div></div>
          <ErrorBox error={historyError}/>
          <div className="operator-message-list" ref={list}>
            {hasOlder && <button type="button" className="operator-chat-older" onClick={older} disabled={loadingOlder}>{loadingOlder ? 'Загружаем…' : 'Более ранние сообщения'}</button>}
            {loading && <p className="operator-chat-note">Загружаем переписку…</p>}
            {!loading && !messages.length && !historyError && <div className="operator-chat-empty"><MessageCircle size={36}/><p>Сообщений пока нет. Напишите коллеге первым.</p></div>}
            <ol role="log" aria-label="Сообщения" aria-live="polite" aria-relevant="additions">
              {messages.map((message, index) => {
                const own = message.sender_id === user.id;
                const day = messageDay(message.created_at, meta.timezone);
                const read = !!message.read_at || message.id <= readThrough;
                return <Fragment key={message.id}>
                  {(index === 0 || messageDay(messages[index - 1].created_at, meta.timezone) !== day) && <li className="operator-message-day">{day}</li>}
                  <li className={`operator-message ${own ? 'own' : ''}`}><div className="operator-message-bubble">{message.photo && (message.photo.available ? <Link className="operator-message-photo" to={operatorPhotoLink(message.photo.id, peerId)} aria-label={'Открыть фотографию №' + message.photo.id}>
                      {message.photo.preview_url ? <img src={message.photo.preview_url} loading="lazy" alt={'Фотография №' + message.photo.id}/> : <span className="operator-message-photo-placeholder"><Camera size={30}/></span>}
                      <span>Фотография #{message.photo.id}<small>Открыть карточку</small></span>
                    </Link> : <div className="operator-message-photo-unavailable">Фотография #{message.photo.id} недоступна</div>)}{message.body && <p>{message.body}</p>}<div className="operator-message-meta"><time dateTime={message.created_at}>{messageTime(message.created_at, meta.timezone)}</time>{own && <span className={read ? 'message-read' : ''} aria-label={read ? 'Прочитано' : 'Отправлено'} title={read ? 'Прочитано' : 'Отправлено'}>{read ? <CheckCheck size={14} aria-hidden="true"/> : <Check size={14} aria-hidden="true"/>}</span>}</div></div></li>
                </Fragment>;
              })}
            </ol>
          </div>
          <form className="operator-chat-compose" onSubmit={send}>
            <ErrorBox error={sendError}/>
            <div><textarea aria-label="Сообщение оператору" placeholder={peer && !peer.active ? 'Аккаунт оператора отключён' : 'Напишите сообщение…'} maxLength={4000} rows={2} value={draft} disabled={!peer?.active || loading || sendingPeer === peerId} onChange={event => {setDrafts(previous => ({...previous, [peerId]: event.target.value})); setSendError('');}} onKeyDown={keyDown}/><button className="primary" aria-label="Отправить сообщение" disabled={!peer?.active || !draft.trim() || loading || !!sendingPeer}><Send size={19}/></button></div>
            <p className="hint">{sendingPeer === peerId ? 'Отправляем…' : 'Enter — отправить, Shift + Enter — новая строка.'}</p>
          </form>
        </>}
      </div>
    </section>
  </>;
}
