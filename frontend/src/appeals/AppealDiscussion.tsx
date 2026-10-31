import { useEffect, useRef, useState } from 'react';
import { History, LockKeyhole, RefreshCw, Send } from 'lucide-react';
import { api, ApiError } from '../api';
import { appealStatuses } from './Wall';
import { galleryPhoto } from './gallery';

type AppealEvent = {id: number; kind: string; actor_name: string; actor_role: string; status: string;
  comment: string; visibility: string; created_at: string; files?: {id: string; name: string; url: string}[]};
type EventPage = {items: AppealEvent[]; has_more: boolean; can_comment: boolean; unanswered_comments?: number};
const kinds: Record<string, string> = {CREATED: 'Обращение создано', ASSIGNED: 'Назначен исполнитель',
  INSTRUCTION: 'Комментарий к задаче', STATUS: 'Изменён статус', RESULT: 'Получен результат исполнителя',
  CLOSED: 'Обращение закрыто', ARCHIVED: 'Перенесено в архив', RESTORED: 'Возвращено из архива',
  NOTE: 'Изменена внутренняя заметка', WORK_TYPE: 'Изменён вид работ', DEADLINE: 'Изменён срок исполнения', COMMENT: 'Сообщение в обсуждении', IMPORTED: 'Состояние до включения истории'};
const roles: Record<string, string> = {INSPECTOR: 'Проверяющий', ADMIN_OPERATOR: 'Администратор', OPERATOR: 'Оператор', CITIZEN: 'Житель'};
const date = (value: string) => new Date(value).toLocaleString('ru-RU', {dateStyle: 'short', timeStyle: 'short'});
const initials = (name: string) => (name.match(/[\p{L}\p{N}]+/gu) || []).slice(0, 2).map(part => part[0]).join('').toUpperCase();

export default function AppealDiscussion({endpoint, archived, channel, title = 'Внутреннее обсуждение', readonlyReason, onUnreadChange}: {endpoint: string; archived: boolean; channel?: 'inspector' | 'executor'; title?: string; readonlyReason?: string; onUnreadChange?: (count: number) => void}) {
  const eventsUrl = endpoint + '/events';
  const query = (suffix = '') => eventsUrl + (channel ? '?channel=' + channel + (suffix ? '&' + suffix : '') : suffix ? '?' + suffix : '');
  const [screenshots, setScreenshots] = useState<File[]>([]);
  const [encodedFiles, setEncodedFiles] = useState<string[] | null>(null);
  const [previews, setPreviews] = useState<string[]>([]);
  useEffect(() => {
    const urls = screenshots.map(file => URL.createObjectURL(file)); setPreviews(urls);
    return () => urls.forEach(url => URL.revokeObjectURL(url));
  }, [screenshots]);
  const [events, setEvents] = useState<AppealEvent[]>([]), [tab, setTab] = useState<'chat' | 'history'>('chat');
  const [loading, setLoading] = useState(true), [more, setMore] = useState(false), [allowed, setAllowed] = useState(!archived);
  const [text, setText] = useState(''), [busy, setBusy] = useState(false), [pending, setPending] = useState(false), [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
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
  }, [endpoint, revision, channel]);
  async function older() {
    if (busy) return; setBusy(true); setError('');
    try {merge(await api<EventPage>(query('before=' + oldest.current)), true);}
    catch (reason) {setError((reason as Error).message);} finally {if (active.current) setBusy(false);}
  }
  async function send() {
    if (sending.current || (!text.trim() && !screenshots.length)) return;
    sending.current = true; setBusy(true); setPending(true); setError('');
    try {
      let encoded = encodedFiles;
      if (!encoded) {
        encoded = [];
        for (const file of screenshots) {
          const {blob} = await galleryPhoto(file);
          encoded.push(await new Promise<string>((resolve, reject) => {const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(new Error('Не удалось прочитать скриншот')); reader.readAsDataURL(blob);}));
        }
        setEncodedFiles(encoded);
      }
      await api(endpoint + '/comments', 'POST', {comment: text.trim(), client_id: clientId.current, channel, screenshots: encoded});
      unreadCallback.current?.(0);
      window.dispatchEvent(new Event('appeal-discussion-changed'));
      if (!active.current) return;
      setText(''); setScreenshots([]); setEncodedFiles(null); setPending(false); clientId.current = crypto.randomUUID();
      merge(await api<EventPage>(query('after=' + newest.current)));
    } catch (reason) {
      if (reason instanceof ApiError && reason.status >= 400 && reason.status < 500) {setPending(false); setEncodedFiles(null);}
      if (active.current) setError((reason as Error).message);
    } finally {sending.current = false; if (active.current) setBusy(false);}
  }
  const visible = tab === 'chat' ? events.filter(item => item.kind === 'COMMENT') : events;
  return <section className="panel appeal-discussion" aria-label={title}>
    <h3>{title}</h3>
    <div className="appeal-discussion-toolbar"><div role="tablist" aria-label="Обсуждение и события"><button role="tab" aria-selected={tab === 'chat'} onClick={() => setTab('chat')}>Переписка</button><button role="tab" aria-selected={tab === 'history'} onClick={() => setTab('history')}><History size={15}/>История событий</button></div><button type="button" disabled={busy} aria-label="Обновить обсуждение" onClick={() => setRevision(value => value + 1)}><RefreshCw size={16}/></button></div>
    <p className="appeal-discussion-privacy" title={channel === 'inspector' ? 'Видно администратору и проверяющим' : 'Видно администратору и назначенному исполнителю'}><LockKeyhole size={12}/>{channel === 'inspector' ? 'Администратор и проверяющий' : 'Администратор и исполнитель'}</p>
    {more && <button disabled={busy} onClick={() => void older()}>Показать более ранние события</button>}
    <div className="appeal-event-list" role="log" aria-label={tab === 'chat' ? 'Сообщения по обращению' : 'События обращения'} aria-live="polite">
      {loading ? <p className="hint">Загружаем…</p> : !visible.length ? <p className="hint">{tab === 'chat' ? 'Здесь можно обсудить обращение.' : 'Событий пока нет.'}</p> : visible.map(item => <article key={item.id} className={'appeal-event ' + (item.kind === 'COMMENT' ? 'appeal-message' : '')}>
        <span className="appeal-message-avatar" aria-hidden="true">{initials(item.actor_name)}</span><div className="appeal-message-body"><header><strong title={roles[item.actor_role]}>{item.actor_name}</strong><time dateTime={item.created_at}>{date(item.created_at)}</time></header>
        {tab === 'history' && <p className="appeal-event-kind">{kinds[item.kind] || item.kind}{item.status && ' · ' + (appealStatuses[item.status] || item.status)}</p>}
        {item.comment && <p className="owner-appeal-text">{item.comment}</p>}<div className="appeal-evidence">{item.files?.map(file => <a key={file.id} href={file.url} target="_blank" rel="noreferrer"><img src={file.url} alt="Скриншот в переписке"/></a>)}</div>{item.visibility !== 'STAFF' && <small className="hint">{item.visibility === 'ADMIN' ? 'Только администраторам' : item.visibility === 'INSPECTOR' ? 'Администратору и проверяющему' : 'Администратору и исполнителю'}</small>}</div>
      </article>)}
    </div>
    {tab === 'chat' && (archived || !allowed ? <p className="hint appeal-discussion-readonly">{readonlyReason || 'Обсуждение в архиве доступно для чтения.'}</p> : <form className="appeal-discussion-compose" onSubmit={event => {event.preventDefault(); void send();}}>
      <textarea aria-label="Сообщение по обращению" maxLength={4000} rows={2} disabled={busy || pending} value={text} onPaste={event => {
        if (busy || pending) return;
        const images = [...event.clipboardData.files].filter(file => file.type.startsWith('image/'));
        if (!images.length) return;
        event.preventDefault();
        if (screenshots.length + images.length > 3 || images.some(file => file.size > 25 * 1024 * 1024)) {setError('Выберите до трёх изображений по 25 МБ'); return;}
        setScreenshots(current => [...current, ...images]); setEncodedFiles(null);
      }} onChange={event => setText(event.target.value)} placeholder="Напишите сообщение для сотрудников…"/>
      <label className="appeal-screenshot-input">Скриншоты <small>до 3 изображений</small><input type="file" accept="image/png,image/jpeg,image/webp" multiple disabled={busy || pending} onChange={event => {
        const selected = [...(event.target.files || [])];
        if (selected.length > 3 || selected.some(file => file.size > 25 * 1024 * 1024)) {setError('Выберите до трёх изображений по 25 МБ'); return;}
        setScreenshots(selected); setEncodedFiles(null);
      }}/>{screenshots.map((file, index) => <span className="hint" key={index}>{file.name}</span>)}</label>
      {!!screenshots.length && <div className="appeal-screenshot-previews">{screenshots.map((file, index) => <div key={index}><img src={previews[index]} alt={file.name}/><button type="button" aria-label={'Удалить скриншот ' + (index + 1)} disabled={busy || pending} onClick={() => {setScreenshots(current => current.filter((_, i) => i !== index)); setEncodedFiles(null);}}>Удалить</button></div>)}</div>}
      {pending && !busy && <p className="hint">Повторите отправку — сообщение не продублируется.</p>}
      <button className="primary" disabled={busy || (!text.trim() && !screenshots.length)} title={pending ? 'Повторить отправку' : 'Отправить сообщение'}><Send size={18}/><span>{busy ? 'Отправляем…' : pending ? 'Повторить отправку' : 'Отправить сообщение'}</span></button>
    </form>)}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
