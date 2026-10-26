import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { Camera, RefreshCw } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { ApiError, api } from './api';
import { useApp } from './App';
import ChatPanel from './ChatPanel';
import { useOperatorChats } from './OperatorChatsProvider';
import { mergeMessages, messagePreview, operatorPhotoLink } from './operatorChatData';
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
  const [contacts, setContacts] = useState<OperatorContact[]>([]);
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

  return <>
    <header className="page-header"><div><span className="eyebrow">ОБЩЕНИЕ В КОМАНДЕ</span><h1>Чаты операторов</h1><p>Личная переписка с коллегами внутри панели.</p></div>
      <button onClick={() => setRevision(value => value + 1)} aria-label="Обновить чаты"><RefreshCw size={18}/></button>
    </header>
    <ChatPanel contacts={contacts.map(contact => ({key: String(contact.id), name: contact.name, avatar_url: contact.avatar_url,
      active: contact.active, unread: contact.unread, subtitle: !contact.active ? 'Аккаунт отключён' : contact.role === 'ADMIN_OPERATOR' ? 'Администратор' : 'Оператор',
      preview: contact.last_message ? `${contact.last_message.sender_id === user.id ? 'Вы: ' : ''}${messagePreview(contact.last_message)}` : null,
      preview_at: contact.last_message?.created_at}))} selected={peerId ? String(peerId) : ''} select={key => setParams(key ? {with: key} : {})}
      contactLoading={contactLoading} contactError={contactError} historyError={historyError} loading={loading}
      messages={messages.map(message => ({...message, outgoing: message.sender_id === user.id, read: !!message.read_at || message.id <= readThrough,
        attachment: message.photo && (message.photo.available ? <Link className="operator-message-photo" to={operatorPhotoLink(message.photo.id, peerId!)} aria-label={'Открыть фотографию №' + message.photo.id}>
          {message.photo.preview_url ? <img src={message.photo.preview_url} loading="lazy" alt={'Фотография №' + message.photo.id}/> : <span className="operator-message-photo-placeholder"><Camera size={30}/></span>}
          <span>Фотография #{message.photo.id}<small>Открыть карточку</small></span>
        </Link> : <div className="operator-message-photo-unavailable">Фотография #{message.photo.id} недоступна</div>)}))}
      hasOlder={hasOlder} loadingOlder={loadingOlder} older={older} listRef={list} draft={draft}
      changeDraft={value => {if (peerId) setDrafts(previous => ({...previous, [peerId]: value})); setSendError('');}}
      send={send} keyDown={keyDown} sending={!!sendingPeer} sendError={sendError} timezone={meta.timezone}/>
  </>;
}
