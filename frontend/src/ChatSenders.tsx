import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Pencil, RefreshCw, UserRound, X } from 'lucide-react';
import { api, dateLabel } from './api';
import { ErrorBox, useApp } from './App';
import type { Chat, ChatSender } from './types';

export default function ChatSenders({chat, onClose}: {chat: Chat; onClose: () => void}) {
  const {notify} = useApp();
  const [items, setItems] = useState<ChatSender[] | null>(null);
  const [senderId, setSenderId] = useState(''), [name, setName] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const loadRevision = useRef(0);
  const pending = useRef(false);
  const path = `/chats/${chat.id}/senders`;

  async function load(signal?: AbortSignal) {
    const revision = ++loadRevision.current;
    setError('');
    try {
      const result = await api<ChatSender[]>(path, 'GET', undefined, signal);
      if (!signal?.aborted && revision === loadRevision.current) setItems(result);
    } catch (e) {
      if (!signal?.aborted && revision === loadRevision.current) setError((e as Error).message);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => {controller.abort(); loadRevision.current++;};
  }, [chat.id]);

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    formRef.current?.querySelector<HTMLInputElement>('input')?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);

  function reset() {setSenderId(''); setName(''); setEditing(false);}

  async function save(event: FormEvent) {
    event.preventDefault();
    if (pending.current) return;
    pending.current = true; setBusy(true); setError('');
    try {
      await api(path + '/' + senderId.trim(), 'PUT', {name: name.trim()});
      reset(); await load(); notify('Подпись отправителя сохранена');
    } catch (e) {setError((e as Error).message);}
    finally {pending.current = false; setBusy(false);}
  }

  async function remove(item: ChatSender) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError('');
    try {
      await api(path + '/' + item.sender_id, 'DELETE');
      if (senderId === item.sender_id) reset();
      await load(); notify('Подпись убрана. Фотографии сохранены.');
    } catch (e) {setError((e as Error).message);}
    finally {pending.current = false; setBusy(false);}
  }

  return <div className="modal-backdrop" onKeyDown={event => {
    if (event.key === 'Escape' && !pending.current) {event.stopPropagation(); onClose();}
    if (event.key === 'Tab') {
      const nodes = formRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), [tabindex="0"]');
      const first = nodes?.[0], last = nodes?.[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
      if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
    }
  }}><form ref={formRef} className="modal chat-senders-modal" role="dialog" aria-modal="true" aria-labelledby="chat-senders-title" onSubmit={save}>
    <div className="section-title"><div><h2 id="chat-senders-title"><UserRound size={20}/>Участники чата</h2><p>{chat.name}</p></div><button type="button" aria-label="Закрыть участников" disabled={busy} onClick={onClose}><X size={18}/></button></div>
    <p className="hint">Укажите ID пользователя MAX и подпись — имя, должность или бригаду. Она появится у всех его фотографий в этом чате, включая ранее полученные.</p>
    <ErrorBox error={error}/>
    <fieldset disabled={busy} className="sender-form"><label>ID пользователя MAX<input required inputMode="numeric" pattern="[0-9]+" autoComplete="off" value={senderId} disabled={editing} onChange={e => setSenderId(e.target.value)} placeholder="Например, 123456789"/></label><label>Подпись<input required maxLength={150} value={name} onChange={e => setName(e.target.value)} placeholder="Например, Иван · бригада № 2"/></label><div className="sender-form-actions"><button className="primary" type="submit">{busy?'Сохранение…':editing?'Сохранить подпись':'Добавить участника'}</button>{editing && <button type="button" onClick={reset}>Отмена</button>}</div></fieldset>
    <div className="section-title"><h3>Отправители фотографий</h3><button type="button" aria-label="Обновить участников" disabled={busy} onClick={() => void load()}><RefreshCw size={16}/></button></div>
    <p className="hint">Здесь также показаны ID тех, кто уже присылал фото. Нажмите «Подписать», чтобы добавить имя.</p>
    {items === null && !error && <p className="loading">Загружаем участников…</p>}
    {items?.length === 0 && <p className="empty">Пользователей пока нет. Добавьте участника по ID.</p>}
    {!!items?.length && <div className="table-scroll"><table className="chat-senders-table"><thead><tr><th>Участник / ID</th><th>Фотографии</th><th/></tr></thead><tbody>{items.map(item => <tr key={item.sender_id}>
      <td><strong>{item.name || 'Не подписан'}</strong><small className="mono">ID {item.sender_id}</small></td><td>{item.photo_count}<small>{item.last_photo_at ? 'Последнее фото '+dateLabel(item.last_photo_at) : 'Фото ещё не присылал'}</small></td><td><div className="sender-row-actions"><button type="button" disabled={busy} onClick={() => {setSenderId(item.sender_id); setName(item.name || ''); setEditing(true); formRef.current?.querySelector<HTMLInputElement>('input[maxlength]')?.focus();}}><Pencil size={14}/>{item.name?'Изменить':'Подписать'}</button>{item.name && <button className="text-button" type="button" disabled={busy} onClick={() => void remove(item)}>Убрать подпись</button>}</div></td>
    </tr>)}</tbody></table></div>}
  </form></div>;
}
