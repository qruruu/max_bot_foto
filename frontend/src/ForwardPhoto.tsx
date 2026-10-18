import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Camera, Send, X } from 'lucide-react';
import { ApiError, api } from './api';
import { ErrorBox } from './App';
import type { Photo } from './types';
import type { ContactPage, OperatorContact } from './operatorChatData';
import './operator-chats.css';

export default function ForwardPhoto({photo, onClose, onSent}: {
  photo: Photo; onClose: () => void; onSent: (peer: OperatorContact) => void;
}) {
  const [contacts, setContacts] = useState<OperatorContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [peerId, setPeerId] = useState('');
  const [body, setBody] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const pending = useRef(false);
  const attempt = useRef<{peerId: string; body: string; clientId: string} | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api<ContactPage>('/operator-chats?photo_id=' + photo.id, 'GET', undefined, controller.signal)
      .then(result => {if (!controller.signal.aborted) setContacts(result.items);})
      .catch(error => {if (!controller.signal.aborted) setError(error.message);})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [photo.id]);
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const select = form.current?.querySelector<HTMLSelectElement>('select');
    if (select && !select.disabled) select.focus();
    else form.current?.querySelector<HTMLButtonElement>('button')?.focus();
    return () => {document.body.style.overflow = overflow; if (previousFocus?.isConnected) previousFocus.focus();};
  }, []);

  async function send(event: FormEvent) {
    event.preventDefault();
    const peer = contacts.find(contact => String(contact.id) === peerId);
    if (!peer || pending.current) return;
    const text = body.trim();
    if (attempt.current?.peerId !== peerId || attempt.current.body !== text) {
      attempt.current = {peerId, body: text, clientId: crypto.randomUUID()};
    }
    pending.current = true; setBusy(true); setError('');
    try {
      await api(`/operator-chats/${peerId}/messages`, 'POST', {
        photo_id: photo.id, body: text, client_id: attempt.current.clientId,
      });
      onSent(peer);
    } catch (error) {
      setError(error instanceof ApiError ? error.message : 'Не удалось подтвердить отправку. Повторите попытку — комментарий сохранён.');
    } finally {pending.current = false; setBusy(false);}
  }

  return <div className="modal-backdrop" onKeyDown={event => {
    if (event.key === 'Escape' && !pending.current) {event.stopPropagation(); onClose();}
    if (event.key !== 'Tab') return;
    const fields = form.current?.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), textarea:not(:disabled)');
    const first = fields?.[0], last = fields?.[fields.length - 1];
    if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
    if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
  }}><form ref={form} className="modal forward-photo-modal" role="dialog" aria-modal="true" aria-labelledby="forward-photo-title" onSubmit={send}>
    <div className="section-title"><h2 id="forward-photo-title">Переслать фото</h2><button type="button" aria-label="Закрыть пересылку" disabled={busy} onClick={onClose}><X size={18}/></button></div>
    <div className="forward-photo-summary">{photo.preview_url ? <img src={photo.preview_url} alt={'Фотография №' + photo.id}/> : <Camera size={28}/>}<strong>Фотография #{photo.id}</strong></div>
    <ErrorBox error={error}/>
    <label>Оператор<select aria-label="Оператор" required value={peerId} disabled={busy || loading} onChange={event => setPeerId(event.target.value)}>
      <option value="">{loading ? 'Загружаем операторов…' : 'Выберите оператора'}</option>
      {contacts.map(contact => <option key={contact.id} value={contact.id}>{contact.name}</option>)}
    </select></label>
    {!loading && !contacts.length && !error && <p className="hint">Нет доступных получателей. У получателя должен быть доступ к этой фотографии.</p>}
    <label>Комментарий (необязательно)<textarea rows={3} maxLength={4000} disabled={busy} placeholder="Какой вид работ тут выбрать?" value={body} onChange={event => setBody(event.target.value)}/></label>
    <p className="hint">Фото появится в личной переписке. Коллега сможет открыть его карточку и ответить в чате.</p>
    <button className="primary" disabled={busy || loading || !peerId}><Send size={17}/>{busy ? 'Отправляем…' : 'Переслать фото'}</button>
  </form></div>;
}
