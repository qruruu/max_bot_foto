import { useEffect, useState } from 'react';
import { Trash2, X } from 'lucide-react';
import { api } from './api';
import { ErrorBox } from './App';
import type { Photo } from './types';

export function canRemoveMissingPreview(photo: Pick<Photo,'processing_error'|'storage_status'>): boolean {
  return photo.processing_error==='ORIGINAL_MISSING' && photo.storage_status==='ERROR';
}

export default function RemoveMissingPreview({photo,onRemoved}:{photo:Photo;onRemoved:()=>void}){
  const [confirm,setConfirm]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{setConfirm(false);setError('');},[photo.id]);
  if(!canRemoveMissingPreview(photo))return null;
  async function remove(){
    setBusy(true);setError('');
    try{await api('/photos/'+photo.id+'/remove-missing-preview','POST',{version:photo.version});onRemoved();}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  return <><button className="remove-preview-button" type="button" disabled={busy} onClick={()=>setConfirm(true)}><Trash2 size={16}/>Убрать недоступное превью</button>{confirm&&<div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="remove-preview-title"><div className="section-title"><h2 id="remove-preview-title">Убрать превью фото #{photo.id}?</h2><button type="button" aria-label="Закрыть" disabled={busy} onClick={()=>setConfirm(false)}><X size={18}/></button></div><p>Оригинал не найден. Превью будет удалено с сервера, карточка исчезнет из списков и отчётов, а задачи синхронизации остановятся.</p><p className="hint">Файлы на Яндекс.Диске не затрагиваются. В истории и обмене с АРМ останется отметка об исключении фотографии.</p><ErrorBox error={error}/><div className="remove-preview-actions"><button type="button" disabled={busy} onClick={()=>setConfirm(false)}>Отмена</button><button className="remove-preview-button" type="button" disabled={busy} onClick={remove}><Trash2 size={16}/>{busy?'Проверяем и убираем…':'Подтвердить удаление превью'}</button></div></section></div>}</>;
}
