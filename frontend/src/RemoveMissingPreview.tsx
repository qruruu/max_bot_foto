import { useEffect, useState } from 'react';
import { Trash2, X } from 'lucide-react';
import { api } from './api';
import { ErrorBox, useApp } from './App';
import { hasPermission } from './permissions';
import type { Photo } from './types';

export function canRemoveMissingPreview(photo: Pick<Photo,'processing_error'|'storage_status'>): boolean {
  return photo.processing_error==='ORIGINAL_MISSING' && photo.storage_status==='ERROR';
}

type RemovalPhoto = Pick<Photo, 'id' | 'version' | 'processing_error' | 'storage_status'>;
type Props = { onRemoved: () => void; buttonLabel?: string } & (
  { photo: RemovalPhoto; photoId?: never } | { photo?: never; photoId: number }
);

export default function RemoveMissingPreview({photo,photoId,onRemoved,buttonLabel='Убрать недоступное превью'}:Props){
  const {user} = useApp();
  const id = photo?.id ?? photoId;
  const [confirm,setConfirm]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [loadedPhoto, setLoadedPhoto] = useState<RemovalPhoto | null>(null);
  useEffect(()=>{setConfirm(false);setError('');setLoadedPhoto(null);},[id]);
  if(!hasPermission(user,'previews_remove') || (photo && !canRemoveMissingPreview(photo)))return null;
  async function openConfirmation() {
    setBusy(true);
    setError('');
    try {
      const current = photo ?? await api<RemovalPhoto>('/photos/' + id);
      if (!canRemoveMissingPreview(current)) {
        throw new Error('Состояние фотографии изменилось. Обновите список задач.');
      }
      setLoadedPhoto(current);
      setConfirm(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function remove(){
    if (!loadedPhoto) return;
    setBusy(true);setError('');
    try{
      await api('/photos/'+loadedPhoto.id+'/remove-missing-preview','POST',{version:loadedPhoto.version});
      setConfirm(false);
      onRemoved();
    }
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  return <><button className="remove-preview-button" type="button" disabled={busy} onClick={openConfirmation}><Trash2 size={16}/>{busy&&!confirm?'Проверяем…':buttonLabel}</button>{!confirm&&<ErrorBox error={error}/>} {confirm&&<div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby={'remove-preview-title-'+id}><div className="section-title"><h2 id={'remove-preview-title-'+id}>Убрать превью фото #{id}?</h2><button type="button" aria-label="Закрыть" disabled={busy} onClick={()=>setConfirm(false)}><X size={18}/></button></div><p>Оригинал не найден. Превью будет удалено с сервера, карточка исчезнет из списков и отчётов, а задачи синхронизации остановятся.</p><p className="hint">Файлы на Яндекс.Диске не затрагиваются. В истории и обмене с АРМ останется отметка об исключении фотографии.</p><ErrorBox error={error}/><div className="remove-preview-actions"><button type="button" disabled={busy} onClick={()=>setConfirm(false)}>Отмена</button><button className="remove-preview-button" type="button" disabled={busy} onClick={remove}><Trash2 size={16}/>{busy?'Проверяем и убираем…':'Подтвердить удаление превью'}</button></div></section></div>}</>;
}
