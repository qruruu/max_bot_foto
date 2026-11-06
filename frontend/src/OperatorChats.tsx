import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Camera, RefreshCw } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { ApiError, api } from './api';
import { useApp } from './App';
import ChatPanel from './ChatPanel';
import type { ChatContact } from './ChatPanel';
import { encodeScreenshots, useChatExtras } from './chatContent';
import type { ChatExtras } from './chatContent';
import Forward from './inspection/Forward';
import type { Contact, ConversationPage, Message } from './inspection/types';
import { useOperatorChats } from './OperatorChatsProvider';
import { mergeMessages, messagePreview, operatorPhotoLink } from './operatorChatData';
import type { ContactPage, MessagePage, OperatorMessage } from './operatorChatData';

const inspectionBase = '/inspection-admin';
type WorkspaceMessage = (OperatorMessage | Message);
const isInspector = (key: string) => /^i:[1-9]\d*$/.test(key);
const chatKey = (value: string) => /^([1-9]\d*|i:[1-9]\d*)$/.test(value) ? value : '';
function messagePath(key: string, filters: Record<string, string> = {}) {
  const path = isInspector(key) ? inspectionBase + '/messages' : `/operator-chats/${key}/messages`;
  const query = new URLSearchParams(isInspector(key) ? {peer: key, ...filters} : filters);
  return query.size ? path + '?' + query : path;
}
function readPath(key: string) {
  return isInspector(key) ? inspectionBase + '/messages/read?' + new URLSearchParams({peer: key}) : `/operator-chats/${key}/read`;
}

export default function OperatorChats({includeInspectors = false}: {includeInspectors?: boolean}) {
  const {user, meta} = useApp();
  const {refreshUnread} = useOperatorChats();
  const [params, setParams] = useSearchParams();
  const selected = chatKey(params.get('with') || '');
  const peerKey = !includeInspectors && isInspector(selected) ? '' : selected;
  const currentPeer = useRef(peerKey);
  currentPeer.current = peerKey;
  const [contacts, setContacts] = useState<ChatContact[]>([]);
  const [contactError, setContactError] = useState(''), [contactLoading, setContactLoading] = useState(true);
  const [messages, setMessages] = useState<WorkspaceMessage[]>([]), [historyError, setHistoryError] = useState('');
  const [loading, setLoading] = useState(false), [hasOlder, setHasOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false), [readThrough, setReadThrough] = useState(0);
  const [drafts, setDrafts] = useState<Record<string, string>>({}), [sendError, setSendError] = useState('');
  const [sending, setSending] = useState(false), [revision, setRevision] = useState(0);
  const [forwarding, setForwarding] = useState<{messages: WorkspaceMessage[]; sent: () => void} | null>(null);
  const [forwardedTo, setForwardedTo] = useState<{key: string; name: string} | null>(null);
  const {extras, update, clearSent} = useChatExtras(peerKey);
  const pending = useRef<{key: string; body: string; extras: ChatExtras; clientId: string} | null>(null);
  const sendingNow = useRef(false);
  const list = useRef<HTMLDivElement>(null), stickToBottom = useRef(true);
  const scrollAnchor = useRef<{height: number; top: number} | null>(null);
  const olderRequest = useRef<AbortController | null>(null);
  const peer = contacts.find(contact => contact.key === peerKey);
  const draft = drafts[peerKey] || '';
  function select(key: string) {setForwardedTo(null); setParams(key ? {with: key} : {});}

  useEffect(() => {
    const controller = new AbortController();
    let busy = false;
    const refresh = async () => {
      if (busy || document.hidden) return;
      busy = true;
      const requests = [
        api<ContactPage>('/operator-chats', 'GET', undefined, controller.signal).then(page => page.items.map(contact => ({
          key: String(contact.id), name: contact.name, avatar_url: contact.avatar_url, active: contact.active, unread: contact.unread,
          subtitle: !contact.active ? 'Аккаунт отключён' : contact.role === 'ADMIN_OPERATOR' ? 'Администратор' : 'Оператор',
          preview: contact.last_message ? (contact.last_message.sender_id === user.id ? 'Вы: ' : '') + messagePreview(contact.last_message) : null,
          preview_at: contact.last_message?.created_at,
        }))),
        ...(includeInspectors ? [api<Contact[]>(inspectionBase + '/contacts', 'GET', undefined, controller.signal).then(items => items.map(contact => ({
          key: contact.key, name: contact.name, avatar_url: contact.avatar_url, active: true, unread: contact.unread,
          subtitle: contact.kind, organization: contact.organization_name,
          preview: contact.last_message ? (contact.last_message_outgoing ? 'Вы: ' : '') + contact.last_message : null,
          preview_at: contact.last_message_at,
        })))] : []),
      ];
      const results = await Promise.allSettled(requests);
      busy = false;
      if (controller.signal.aborted) return;
      setContactLoading(false);
      const failed = results.find(result => result.status === 'rejected');
      setContactError(failed ? (failed.reason as Error).message : '');
      setContacts(previous => results.flatMap((result, index) => result.status === 'fulfilled'
        ? result.value : previous.filter(contact => isInspector(contact.key) === (index === 1)))
        .sort((a, b) => (b.preview_at || '').localeCompare(a.preview_at || '') || a.name.localeCompare(b.name, 'ru')));
    };
    const visible = () => {void refresh();};
    visible();
    const timer = window.setInterval(visible, 5000);
    document.addEventListener('visibilitychange', visible);
    return () => {controller.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', visible);};
  }, [revision, includeInspectors, user.id]);

  async function load(key: string, filters: Record<string, string>, signal: AbortSignal) {
    const path = messagePath(key, filters);
    if (isInspector(key)) {
      const page = await api<ConversationPage>(path, 'GET', undefined, signal);
      return {items: page.items, has_older: !!page.next_before_id, peer_read_through_id: page.peer_read_through_id};
    }
    return api<MessagePage>(path, 'GET', undefined, signal);
  }

  useEffect(() => {
    setMessages([]); setHistoryError(''); setSendError(''); setHasOlder(false); setReadThrough(0);
    setLoadingOlder(false); scrollAnchor.current = null; stickToBottom.current = true;
    if (!peerKey) {setLoading(false); return;}
    const controller = new AbortController();
    let busy = false, cursor = 0, acknowledged = 0, initial = true;
    setLoading(true);
    const refresh = async () => {
      if (busy || document.hidden) return;
      busy = true;
      try {
        const result = await load(peerKey, initial ? {} : {after_id: String(cursor)}, controller.signal);
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
          await api(readPath(peerKey), 'POST', {through_id: cursor}, controller.signal);
          acknowledged = cursor;
          if (!controller.signal.aborted) {
            setContacts(previous => previous.map(contact => contact.key === peerKey ? {...contact, unread: 0} : contact));
            void refreshUnread();
          }
        }
      } catch (error) {if (!controller.signal.aborted) {setHistoryError((error as Error).message); setLoading(false);}}
      finally {busy = false;}
    };
    const visible = () => {void refresh();};
    visible();
    const timer = window.setInterval(visible, 3000);
    document.addEventListener('visibilitychange', visible);
    return () => {
      controller.abort(); olderRequest.current?.abort(); window.clearInterval(timer);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [peerKey, revision, refreshUnread]);

  useLayoutEffect(() => {
    const element = list.current;
    if (!element) return;
    if (scrollAnchor.current) {
      element.scrollTop = scrollAnchor.current.top + element.scrollHeight - scrollAnchor.current.height;
      scrollAnchor.current = null;
    } else if (stickToBottom.current) element.scrollTop = element.scrollHeight;
  }, [messages]);

  async function older() {
    if (!peerKey || !messages.length || loadingOlder) return;
    const target = peerKey, controller = new AbortController();
    olderRequest.current = controller;
    setLoadingOlder(true);
    try {
      const result = await load(target, {before_id: String(messages[0].id)}, controller.signal);
      if (currentPeer.current !== target || controller.signal.aborted) return;
      if (list.current) scrollAnchor.current = {height: list.current.scrollHeight, top: list.current.scrollTop};
      setMessages(previous => mergeMessages(previous, result.items)); setHasOlder(result.has_older);
    } catch (error) {if (!controller.signal.aborted && currentPeer.current === target) setHistoryError((error as Error).message);}
    finally {if (!controller.signal.aborted && currentPeer.current === target) setLoadingOlder(false);}
  }

  async function send() {
    const body = draft.trim();
    if (!peerKey || !peer?.active || (!body && !extras.files.length) || sendingNow.current || loading) return;
    const target = peerKey;
    const attempt = pending.current?.key === target && pending.current.body === body && pending.current.extras === extras
      ? pending.current : {key: target, body, extras, clientId: crypto.randomUUID()};
    pending.current = attempt;
    sendingNow.current = true;
    setSending(true); setSendError('');
    try {
      const screenshots = await encodeScreenshots(extras.files);
      const message = await api<WorkspaceMessage>(messagePath(target), 'POST', {body, client_id: attempt.clientId,
        ...(screenshots.length ? {screenshots} : {}), ...(extras.reply ? {reply_to_id: extras.reply.id} : {})});
      if (currentPeer.current === target) {
        stickToBottom.current = true;
        setMessages(previous => mergeMessages(previous, [message]));
      }
      setDrafts(previous => previous[target]?.trim() === body ? {...previous, [target]: ''} : previous);
      clearSent(extras);
      if (pending.current === attempt) pending.current = null;
      setContacts(previous => previous.map(contact => contact.key === target ? {...contact,
        preview: 'Вы: ' + ('sender_id' in message ? messagePreview(message) : message.body || 'Скриншот'),
        preview_at: message.created_at} : contact));
    } catch (error) {
      if (currentPeer.current === target) setSendError(error instanceof ApiError ? error.message
        : navigator.onLine && error instanceof Error && extras.files.length ? error.message : 'Не удалось подтвердить отправку. Повторите попытку.');
    } finally {sendingNow.current = false; setSending(false);}
  }

  return <>
    <header className="page-header"><h1>Чаты</h1><button onClick={() => setRevision(value => value + 1)} aria-label="Обновить чаты" title="Обновить чаты"><RefreshCw size={17}/></button></header>
    <ChatPanel contacts={contacts} selected={peerKey} select={select}
      contactLoading={contactLoading} contactError={contactError} historyError={historyError} loading={loading}
      messages={messages.map(message => {
        const outgoing = 'sender_id' in message ? message.sender_id === user.id : message.outgoing;
        const photo = message.photo;
        const url = photo?.available ? ('detail_url' in photo ? photo.detail_url : operatorPhotoLink(photo.id, Number(peerKey))) : null;
        const href = url?.replace(/^\/org\/[0-9a-f-]{36}(?=\/)/, '');
        return {...message, outgoing, author: outgoing ? user.name : peer?.name || 'Собеседник',
          canForward: !photo || photo.available, read: !!message.read_at || message.id <= readThrough,
          attachment: photo && (href ? <Link className="operator-message-photo" to={href} state={{conversation: peerKey}} aria-label={'Открыть фотографию №' + photo.id}>
            {photo.preview_url ? <img src={photo.preview_url} loading="lazy" alt={'Фотография №' + photo.id}/> : <span className="operator-message-photo-placeholder"><Camera size={30}/></span>}
            <span>Фотография #{photo.id}<small>Открыть карточку</small></span>
          </Link> : <div className="operator-message-photo-unavailable">Фотография #{photo.id} недоступна</div>)};
      })}
      hasOlder={hasOlder} loadingOlder={loadingOlder} older={older} listRef={list} draft={draft}
      changeDraft={value => {if (peerKey) setDrafts(previous => ({...previous, [peerKey]: value})); setSendError('');}}
      send={send} extras={extras} changeExtras={update} reply={value => update({reply: value})}
      sending={sending} sendError={sendError} timezone={meta.timezone}
      forwardedTo={forwardedTo} dismissForwarded={() => setForwardedTo(null)}
      forward={(ids, sent) => setForwarding({messages: messages.filter(message => ids.includes(message.id)), sent})}/>
    {!!forwarding?.messages.length && <Forward base={inspectionBase} messages={forwarding.messages} unified={includeInspectors}
      onClose={() => setForwarding(null)} onSent={(peer, count) => {
        forwarding.sent(); setForwarding(null); setForwardedTo(count === undefined ? peer : {key: peerKey, name: 'Чатов: ' + count});
      }}/>}
  </>;
}
