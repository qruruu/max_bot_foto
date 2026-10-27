import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Send, X } from 'lucide-react';
import { ApiError, api } from '../api';
import { ErrorBox } from '../App';
import type { Contact, InspectionPhoto, Message } from './types';
import '../operator-chats.css';

type ForwardPhoto = Pick<InspectionPhoto,'id'|'preview_url'> & {organization_id: string};
export default function InspectionForward({base='/inspection',photo,message,onClose,onSent}: {
  base?: string; photo?: ForwardPhoto; message?: Message; onClose: () => void; onSent: (peer: Contact) => void;
}) {
  const [contacts,setContacts]=useState<Contact[]>([]),[loading,setLoading]=useState(true),[peerKey,setPeerKey]=useState('');
  const [body,setBody]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const form=useRef<HTMLFormElement>(null),pending=useRef(false);
  const attempt=useRef<{peer: string;body: string;clientId: string}|null>(null);
  const query = message ? new URLSearchParams({forward_message_id:String(message.id)}) : new URLSearchParams({photo_organization_id:photo!.organization_id,photo_id:String(photo!.id)});
  useEffect(()=>{
    const controller=new AbortController();
    api<Contact[]>(base+'/contacts?'+query,'GET',undefined,controller.signal).then(value=>{if(!controller.signal.aborted)setContacts(value);})
      .catch(error=>{if(!controller.signal.aborted)setError(error.message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[base,query.toString()]);
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null,overflow=document.body.style.overflow;
    document.body.style.overflow='hidden';form.current?.querySelector<HTMLButtonElement>('button')?.focus();
    return()=>{document.body.style.overflow=overflow;if(previous?.isConnected)previous.focus({preventScroll:true});};
  },[]);
  async function send(event:FormEvent){
    event.preventDefault();const peer=contacts.find(item=>item.key===peerKey);if(!peer||pending.current)return;
    const text=body.trim();
    if(attempt.current?.peer!==peerKey||attempt.current.body!==text)attempt.current={peer:peerKey,body:text,clientId:crypto.randomUUID()};
    pending.current=true;setBusy(true);setError('');
    try{
      await api(base+'/messages?'+new URLSearchParams({peer:peerKey}),'POST',{client_id:attempt.current.clientId,
        ...(message?{forward_message_id:message.id}:{body:text,photo_id:photo!.id,photo_organization_id:photo!.organization_id})});
      onSent(peer);
    }catch(error){setError(error instanceof ApiError?error.message:'Не удалось подтвердить отправку. Повторите попытку — данные сохранены.');}
    finally{pending.current=false;setBusy(false);}
  }
  return <div className="modal-backdrop" onKeyDown={event=>{
    if(event.key==='Escape'&&!pending.current){event.stopPropagation();onClose();}
    if(event.key!=='Tab')return;
    const fields=form.current?.querySelectorAll<HTMLElement>('button:not(:disabled),select:not(:disabled),textarea:not(:disabled)');
    const first=fields?.[0],last=fields?.[fields.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }}><form ref={form} className="modal forward-photo-modal" role="dialog" aria-modal="true" aria-labelledby="inspection-forward-title" onSubmit={send}>
    <div className="section-title"><h2 id="inspection-forward-title">{message?'Переслать сообщение':'Переслать фото'}</h2><button type="button" aria-label="Закрыть пересылку" disabled={busy} onClick={onClose}><X size={18}/></button></div>
    {photo&&<div className="forward-photo-summary"><img src={photo.preview_url} alt={'Фотография №'+photo.id}/><strong>Фотография #{photo.id}</strong></div>}
    {message&&<div className="inspection-forward-summary">{message.photo&&<strong>Фотография #{message.photo.id}</strong>}{message.body&&<p>{message.body}</p>}</div>}
    <ErrorBox error={error}/>
    <label>Получатель<select aria-label="Получатель" required value={peerKey} disabled={busy||loading} onChange={event=>setPeerKey(event.target.value)}>
      <option value="">{loading?'Загружаем получателей…':'Выберите получателя'}</option>{contacts.map(item=><option key={item.key} value={item.key}>{item.name} · {item.organization_name||item.kind}</option>)}
    </select></label>
    {!loading&&!contacts.length&&!error&&<p className="hint">Нет доступных получателей. Для пересылки фото у получателя должен быть свой доступ к организации.</p>}
    {!message&&<label>Комментарий (необязательно)<textarea rows={3} maxLength={4000} disabled={busy} value={body} onChange={event=>setBody(event.target.value)}/></label>}
    <p className="hint">{message?'Сообщение появится в личной переписке выбранного получателя.':'Фото появится в личной переписке. Получатель сможет открыть карточку и ответить в чате.'}</p>
    <button className="primary" disabled={busy||loading||!peerKey}><Send size={17}/>{busy?'Отправляем…':'Переслать'}</button>
  </form></div>;
}
