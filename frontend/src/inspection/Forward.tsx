import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Camera, Check, Search, Send, X } from 'lucide-react';
import { ApiError, api } from '../api';
import { ErrorBox } from '../App';
import type { Contact, InspectionPhoto, Message } from './types';
import type { ContactPage, OperatorMessage } from '../operatorChatData';
import '../operator-chats.css';

type Destination = {key: string; name: string; subtitle?: string | null};
type AppealForward = {endpoint: string; id: number; body: string; screenshots?: string[]; channel?: 'inspector' | 'executor'};
type ForwardPhoto = Pick<InspectionPhoto, 'id'> & {preview_url: string | null; organization_id?: string};
export default function InspectionForward({base='/inspection',photo,message,operatorMessage,appeal,onClose,onSent}: {
  base?: string; photo?: ForwardPhoto; message?: Message; operatorMessage?: OperatorMessage; appeal?: AppealForward; onClose: () => void; onSent: (peer: Destination) => void;
}) {
  const [contacts,setContacts]=useState<Destination[]>([]),[loading,setLoading]=useState(true),[peerKey,setPeerKey]=useState('');
  const [search, setSearch] = useState(''), [remoteSearch, setRemoteSearch] = useState('');
  useEffect(() => {
    if (!appeal) return;
    const timer = window.setTimeout(() => setRemoteSearch(search.trim()), 220);
    return () => window.clearTimeout(timer);
  }, [appeal?.endpoint, search]);
  const [body,setBody]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const form=useRef<HTMLFormElement>(null),pending=useRef(false);
  const attempt=useRef<{peer: string;body: string;clientId: string}|null>(null);
  const source = message || operatorMessage || appeal;
  const operatorChat = !!operatorMessage || !!photo && !photo.organization_id;
  const query = source ? new URLSearchParams({forward_message_id:String(source.id)}) : new URLSearchParams({
    ...(photo!.organization_id ? {photo_organization_id: photo!.organization_id} : {}), photo_id: String(photo!.id),
  });
  const term = search.trim().toLocaleLowerCase('ru-RU');
  const visible = appeal ? contacts : contacts.filter(item => [item.name, item.subtitle].join(' ').toLocaleLowerCase('ru-RU').includes(term));
  const searching = !!appeal && search.trim() !== remoteSearch;
  const selected = !searching && !loading ? visible.find(item => item.key === peerKey) : undefined;
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);setError('');setPeerKey('');
    const request = appeal ? api<{id: number; title: string}[]>(appeal.endpoint+'/forward-targets?'+new URLSearchParams({
        message_id: String(appeal.id), q: remoteSearch, ...(appeal.channel ? {channel: appeal.channel} : {}),
      }), 'GET', undefined, controller.signal).then(items => items.map(item => ({key: String(item.id), name: item.title})))
      : operatorChat ? api<ContactPage>('/operator-chats?'+query,'GET',undefined,controller.signal).then(page => page.items.filter(item => item.active)
        .map(item => ({key: String(item.id), name: item.name, subtitle: item.role === 'ADMIN_OPERATOR' ? 'Администратор' : 'Оператор'})))
      : api<Contact[]>(base+'/contacts?'+query,'GET',undefined,controller.signal).then(items => items.map(item => ({
        key: item.key, name: item.name, subtitle: item.organization_name || item.kind,
      })));
    request.then(value=>{if(!controller.signal.aborted)setContacts(value);})
      .catch(error=>{if(!controller.signal.aborted)setError(error.message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[base,query.toString(),appeal?.endpoint,appeal?.channel,remoteSearch,operatorChat]);
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null,overflow=document.body.style.overflow;
    document.body.style.overflow='hidden';form.current?.querySelector<HTMLInputElement>('input[type=search]')?.focus();
    return()=>{document.body.style.overflow=overflow;if(previous?.isConnected)previous.focus({preventScroll:true});};
  },[]);
  async function send(event:FormEvent){
    event.preventDefault();const peer=selected;if(!peer||pending.current)return;
    const text=body.trim();
    if(attempt.current?.peer!==peerKey||attempt.current.body!==text)attempt.current={peer:peerKey,body:text,clientId:crypto.randomUUID()};
    pending.current=true;setBusy(true);setError('');
    try{
      const path = appeal ? appeal.endpoint.slice(0, appeal.endpoint.lastIndexOf('/')) + '/' + peerKey + '/comments'
        : operatorChat ? '/operator-chats/'+peerKey+'/messages' : base+'/messages?'+new URLSearchParams({peer:peerKey});
      await api(path,'POST',{client_id:attempt.current.clientId,
        ...(source ? {forward_message_id:source.id, ...(appeal?.channel ? {channel: appeal.channel} : {})}
          : {body:text,photo_id:photo!.id,...(photo!.organization_id ? {photo_organization_id: photo!.organization_id} : {})})});
      onSent(peer);
    }catch(error){setError(error instanceof ApiError?error.message:'Не удалось подтвердить отправку. Повторите попытку — данные сохранены.');}
    finally{pending.current=false;setBusy(false);}
  }
  return <div className="modal-backdrop" onKeyDown={event=>{
    if(event.key==='Escape'&&!pending.current){event.stopPropagation();onClose();}
    if(event.key!=='Tab')return;
    const fields=form.current?.querySelectorAll<HTMLElement>('button:not(:disabled),select:not(:disabled),textarea:not(:disabled),input:not(:disabled)');
    const first=fields?.[0],last=fields?.[fields.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  }}><form ref={form} className="modal forward-photo-modal" role="dialog" aria-modal="true" aria-labelledby="inspection-forward-title" onSubmit={send}>
    <div className="section-title"><h2 id="inspection-forward-title">{source?'Переслать сообщение':'Переслать фото'}</h2><button type="button" aria-label="Закрыть пересылку" disabled={busy} onClick={onClose}><X size={18}/></button></div>
    {photo&&<div className="forward-photo-summary">{photo.preview_url ? <img src={photo.preview_url} alt={'Фотография №'+photo.id}/> : <Camera size={26}/>}<strong>Фотография #{photo.id}</strong></div>}
    {source&&<div className="inspection-forward-summary">{'photo' in source&&source.photo&&<strong>Фотография #{source.photo.id}</strong>}
      {!!source.screenshots?.length&&<strong>Скриншоты: {source.screenshots.length}</strong>}{source.body&&<p>{source.body}</p>}</div>}
    <ErrorBox error={error}/>
    <label className="forward-search"><Search size={16}/>{appeal ? 'Найти задачу' : 'Найти получателя'}
      <input type="search" value={search} disabled={busy} maxLength={200} placeholder={appeal ? 'Номер или название' : 'Имя или роль'}
        onChange={event => {setSearch(event.target.value); setPeerKey('');}}/></label>
    <div className="forward-destinations" role="group" aria-label={appeal ? 'Задачи' : 'Получатели'} aria-busy={searching || loading}>
      {searching || loading ? <p role="status">Загружаем…</p> : visible.map(item =>
        <button key={item.key} type="button" aria-pressed={item.key === peerKey} disabled={busy} onClick={() => setPeerKey(item.key)}>
          <span><strong>{item.name}</strong>{item.subtitle && <small>{item.subtitle}</small>}</span>
          {item.key === peerKey && <Check size={17}/>}
        </button>)}
      {!searching && !loading && !visible.length && !error && <p>{term ? 'По этому запросу ничего не найдено.' : appeal ? 'Нет доступных задач.' : 'Нет доступных получателей.'}</p>}
    </div>
    {!source&&<label>Комментарий (необязательно)<textarea rows={3} maxLength={4000} disabled={busy} value={body} onChange={event=>setBody(event.target.value)}/></label>}
    <button className="primary" disabled={busy || !selected}><Send size={17}/>{busy?'Отправляем…':'Переслать'}</button>
  </form></div>;
}
