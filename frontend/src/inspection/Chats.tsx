import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { Camera, RefreshCw } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { ApiError, api } from '../api';
import ChatPanel from '../ChatPanel';
import { useOperatorChats } from '../OperatorChatsProvider';
import InspectionForward from './Forward';
import type { Contact, Message, ConversationPage as MessagePage } from './types';

const labels = {contacts: 'Собеседники', search: 'Найти собеседника', loading: 'Загружаем собеседников…',
  none: 'Собеседников не найдено.', empty: 'Пока нет доступных собеседников. Администраторы появятся после получения доступа к организации.',
  back: 'К списку собеседников', message: 'Сообщение'};
const merge = (current: Message[], incoming: Message[]) => [...new Map([...current, ...incoming].map(message => [message.id, message])).values()].sort((a, b) => a.id - b.id);

export default function InspectionChats({base = '/inspection', revision = 0, timezone = 'Asia/Yekaterinburg', openPhotoLink, active=true}: {base?: string; revision?: number; timezone?: string; openPhotoLink?: (url: string) => void; active?: boolean}) {
  const notifications = useOperatorChats();
  const [params, setParams] = useSearchParams(), peerKey = params.get('with') || '';
  const [contacts, setContacts] = useState<Contact[]>([]), [contactLoading, setContactLoading] = useState(true), [contactError, setContactError] = useState('');
  const [items, setItems] = useState<Message[]>([]), [before, setBefore] = useState<number | null>(null);
  const [loading, setLoading] = useState(false), [loadingOlder, setLoadingOlder] = useState(false), [readThrough, setReadThrough] = useState(0);
  const [drafts, setDrafts] = useState<Record<string, string>>({}), [sendError, setSendError] = useState(''), [historyError, setHistoryError] = useState('');
  const [sendingPeer, setSendingPeer] = useState(''), [refreshKey, setRefreshKey] = useState(0);
  const [forwarding,setForwarding]=useState<Message|null>(null);
  const retry = useRef<{body: string; peer: string; id: string} | null>(null);
  const list = useRef<HTMLDivElement>(null), stickToBottom = useRef(true), scrollAnchor = useRef<{height: number; top: number} | null>(null);
  const currentPeer = useRef(peerKey), olderRequest = useRef<AbortController | null>(null);
  const refreshContacts = useRef<() => Promise<void>>(async () => {}), refreshMessages = useRef<() => Promise<void>>(async () => {});
  currentPeer.current = peerKey;
  const chatVisible=useRef(active);chatVisible.current=active;
  const contact = contacts.find(item => item.key === peerKey), draft = drafts[peerKey] || '';
  function select(key: string) {setParams(previous => {const next = new URLSearchParams(previous); key ? next.set('with', key) : next.delete('with'); return next;});}

  useEffect(() => {
    const controller = new AbortController();
    let busy = false;
    const refresh = async () => {
      if (busy || document.hidden || !chatVisible.current) return;
      busy = true;
      try {
        const result = await api<Contact[]>(base + '/contacts', 'GET', undefined, controller.signal);
        if (controller.signal.aborted) return;
        setContacts(result); setContactError('');
        if (currentPeer.current && !result.some(item => item.key === currentPeer.current)) select('');
      } catch (error) {
        if (!controller.signal.aborted) {setContactError((error as Error).message); if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {setContacts([]); select('');}}
      } finally {busy = false; if (!controller.signal.aborted) setContactLoading(false);}
    };
    refreshContacts.current = refresh;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000), visible = () => {void refresh();};
    document.addEventListener('visibilitychange', visible);
    return () => {controller.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', visible);};
  }, [base]);

  useEffect(() => {
    setItems([]); setBefore(null); setHistoryError(''); setSendError(''); setReadThrough(0); setLoadingOlder(false);
    scrollAnchor.current = null; stickToBottom.current = true;
    if (!peerKey) {setLoading(false); refreshMessages.current = async () => {}; return;}
    const controller = new AbortController();
    let busy = false, initial = true, cursor = 0, acknowledged = 0;
    setLoading(true);
    const refresh = async () => {
      if (busy || document.hidden || !chatVisible.current) return;
      busy = true;
      try {
        // Fetch new messages in order, including bursts larger than one page.
        for (let page = 0; page < 5; page++) {
          const result = await api<MessagePage>(base + '/messages?' + new URLSearchParams({peer: peerKey, ...(!initial ? {after_id: String(cursor)} : {})}), 'GET', undefined, controller.signal);
          if (controller.signal.aborted || !chatVisible.current) return;
          const first = initial, element = list.current;
          if (result.items.length) {
            const added=initial||result.items.some(message=>message.id>cursor);
            stickToBottom.current = added && (initial || !element || element.scrollHeight - element.scrollTop - element.clientHeight < 90);
            setItems(previous => first ? result.items : merge(previous, result.items));
            cursor = Math.max(cursor, ...result.items.map(message => message.id));
          }
          if (initial) setBefore(result.next_before_id);
          initial = false; setReadThrough(result.peer_read_through_id); setHistoryError(''); setLoading(false);
          if (cursor > acknowledged && !document.hidden && chatVisible.current) {
            await api(base + '/messages/read?' + new URLSearchParams({peer: peerKey}), 'POST', {through_id: cursor}, controller.signal);
            if (controller.signal.aborted) return;
            acknowledged = cursor;
            setContacts(previous => previous.map(item => item.key === peerKey ? {...item, unread: 0} : item));
            void notifications?.refreshUnread();
          }
          if (!result.has_newer) break;
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setHistoryError((error as Error).message); setLoading(false);
          if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {setItems([]); select(''); void refreshContacts.current();}
        }
      } finally {busy = false;}
    };
    refreshMessages.current = refresh;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000), visible = () => {void refresh();};
    document.addEventListener('visibilitychange', visible);
    return () => {controller.abort(); olderRequest.current?.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', visible);};
  }, [base, peerKey]);

  useEffect(() => {if(active){void refreshContacts.current(); void refreshMessages.current();}}, [revision, refreshKey, active]);
  useLayoutEffect(() => {
    const element = list.current;
    if (!element) return;
    if (scrollAnchor.current) {element.scrollTop = scrollAnchor.current.top + element.scrollHeight - scrollAnchor.current.height; scrollAnchor.current = null;}
    else if (stickToBottom.current) element.scrollTop = element.scrollHeight;
  }, [items]);

  async function older() {
    if (!peerKey || !before || loadingOlder) return;
    const target = peerKey, controller = new AbortController(); olderRequest.current = controller; setLoadingOlder(true);
    try {
      const page = await api<MessagePage>(base + '/messages?' + new URLSearchParams({peer: target, before_id: String(before)}), 'GET', undefined, controller.signal);
      if (controller.signal.aborted || currentPeer.current !== target) return;
      if (list.current) scrollAnchor.current = {height: list.current.scrollHeight, top: list.current.scrollTop};
      setItems(previous => merge(previous, page.items)); setBefore(page.next_before_id);
    } catch (error) {if (!controller.signal.aborted && currentPeer.current === target) setHistoryError((error as Error).message);}
    finally {if (!controller.signal.aborted && currentPeer.current === target) setLoadingOlder(false);}
  }
  async function send(event?: FormEvent) {
    event?.preventDefault(); const body = draft.trim();
    if (!peerKey || !contact || !body || sendingPeer || loading) return;
    const target = peerKey, attempt = retry.current?.peer === target && retry.current.body === body ? retry.current : {peer: target, body, id: crypto.randomUUID()};
    retry.current = attempt; setSendingPeer(target); setSendError('');
    try {
      const message = await api<Message>(base + '/messages?' + new URLSearchParams({peer: target}), 'POST', {body, client_id: attempt.id});
      if (currentPeer.current === target) {stickToBottom.current = true; setItems(previous => merge(previous, [message]));}
      setDrafts(previous => previous[target]?.trim() === body ? {...previous, [target]: ''} : previous);
      if (retry.current === attempt) retry.current = null;
      void refreshContacts.current();
    } catch (error) {if (currentPeer.current === target) setSendError(error instanceof ApiError ? error.message : 'Не удалось подтвердить отправку. Повторите попытку — текст сохранён.');}
    finally {setSendingPeer('');}
  }
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); void send();}
  }
  return <>
    {base !== '/inspection' && <div className="section-title"><h2>Чаты</h2><button aria-label="Обновить чаты" onClick={() => setRefreshKey(value => value + 1)}><RefreshCw size={18}/></button></div>}
    <ChatPanel contacts={contacts.map(item => ({key: item.key, name: item.name, avatar_url: item.avatar_url, active: true, unread: item.unread,
      subtitle: [item.kind, item.organization_name].filter(Boolean).join(' · '), organization: item.organization_name,
      preview: item.last_message ? (item.last_message_outgoing ? 'Вы: ' : '') + item.last_message : null, preview_at: item.last_message_at}))}
      selected={peerKey} select={select} contactLoading={contactLoading} contactError={contactError} messages={items.map(item => ({...item, read: !!item.read_at || item.id <= readThrough,
        canForward: !item.photo || item.photo.available,
        attachment: item.photo && (item.photo.available && item.photo.detail_url ? (base==='/inspection' ? <Link className="operator-message-photo" to={item.photo.detail_url} onClick={event=>{if(openPhotoLink){event.preventDefault();openPhotoLink(item.photo!.detail_url!);}}}>
          {item.photo.preview_url?<img src={item.photo.preview_url} loading="lazy" alt={'Фотография №'+item.photo.id}/>:<span className="operator-message-photo-placeholder"><Camera size={30}/></span>}<span>Фотография #{item.photo.id}<small>{item.photo.organization_name} · Открыть карточку</small></span>
        </Link> : <a className="operator-message-photo" href={item.photo.detail_url} target="_blank" rel="noreferrer">
          {item.photo.preview_url&&<img src={item.photo.preview_url} loading="lazy" alt={'Фотография №'+item.photo.id}/>}<span>Фотография #{item.photo.id}<small>{item.photo.organization_name} · Открыть карточку</small></span>
        </a>) : <div className="operator-message-photo-unavailable">Фотография #{item.photo.id} недоступна</div>)}))}
      historyError={historyError} loading={loading} hasOlder={!!before} loadingOlder={loadingOlder} older={older} listRef={list}
      draft={draft} changeDraft={value => {setDrafts(previous => ({...previous, [peerKey]: value})); setSendError('');}}
      send={send} keyDown={keyDown} sending={!!sendingPeer} sendError={sendError} timezone={timezone} labels={labels}
      forward={id=>setForwarding(items.find(item=>item.id===id)||null)}/>
    {forwarding&&<InspectionForward key={forwarding.id} base={base} message={forwarding} onClose={()=>setForwarding(null)} onSent={peer=>{setForwarding(null);select(peer.key);void refreshContacts.current();void refreshMessages.current();}}/>}
  </>;
}
