import { useEffect, useLayoutEffect, useState } from 'react';
import { ArrowLeft, ArrowUpRight, ChevronLeft, ChevronRight, MapPin, RefreshCw, Share2 } from 'lucide-react';
import { api, dateLabel } from '../api';
import { ErrorBox, StatusBadge, useApp } from '../App';
import InspectionForward from './Forward';
import type { InspectionPhoto } from './types';

export type InspectionPhotoPosition = {scrollY: number; focus: HTMLElement | null; chatScrollTop?: number; tableScrollLeft?: number};

export default function InspectionPhotoDetail({org, id, filters, onClose, onMove, fromChat}: {
  org: string; id: number; filters: string; onClose: () => void; onMove: (id: number) => void;
  fromChat: boolean;
}) {
  const {meta, notify} = useApp();
  const [photo, setPhoto] = useState<InspectionPhoto | null>(null), [error, setError] = useState('');
  const [navigation, setNavigation] = useState<{previous: number | null; next: number | null}>({previous:null,next:null});
  const [revision, setRevision] = useState(0), [forwarding, setForwarding] = useState(false);
  useLayoutEffect(() => {
    window.scrollTo(0,0);
  }, []);
  useEffect(() => {
    const controller = new AbortController(); setPhoto(null); setError(''); setForwarding(false); setNavigation({previous:null,next:null});
    api<InspectionPhoto>(`/inspection/organizations/${org}/photos/${id}`, 'GET', undefined, controller.signal).then(value=>{if(!controller.signal.aborted)setPhoto(value);}).catch(error => {if (!controller.signal.aborted) setError(error.message);});
    api<typeof navigation>(`/inspection/organizations/${org}/photos/${id}/navigation?${filters}`, 'GET', undefined, controller.signal).then(value=>{if(!controller.signal.aborted)setNavigation(value);}).catch(()=>{});
    return () => controller.abort();
  }, [org,id,filters,revision]);
  return <section className="inspection-photo-detail">
    <button className="back-link" onClick={onClose}><ArrowLeft size={16}/>{fromChat ? 'К переписке' : 'Все фотографии'}</button>
    <header className="page-header"><div><span className="eyebrow">КАРТОЧКА ФОТОГРАФИИ</span><h1>Фотография #{id}</h1>{photo && <p>Получена {dateLabel(photo.received_at)}</p>}</div><div className="inspection-actions">{photo && <StatusBadge value="ACCEPTED"/>}<button aria-label="Обновить карточку" onClick={()=>setRevision(value=>value+1)}><RefreshCw size={17}/></button></div></header>
    <ErrorBox error={error}/>
    {!photo && !error && <p className="loading">Открываем фотографию…</p>}
    {photo && <div className="review-layout"><div className="review-image-column"><div className="review-image"><a href={photo.preview_url} target="_blank" rel="noreferrer"><img src={photo.preview_url} alt={'Фотография №'+photo.id}/></a></div>
      <div className="image-caption"><span>Изображение для просмотра</span>{photo.original_available && <a href={`/api/inspection/organizations/${org}/photos/${id}/original`} target="_blank" rel="noreferrer">Открыть оригинал<ArrowUpRight size={15}/></a>}</div></div>
      <div><section className="panel review-form"><div className="section-title"><h2>Данные фотографии</h2><span className="count-pill">#{photo.id}</span></div>
        <div className="form-grid"><label>Дата фотографии<input type="date" value={photo.photo_date||''} readOnly/></label><label>Время<input type="time" step="1" value={photo.photo_time||''} readOnly/></label>
          <label>Широта<input value={photo.latitude??''} readOnly/></label><label>Долгота<input value={photo.longitude??''} readOnly/></label></div>
        <label>Микрорайон<input value={photo.district_name||'Не определён'} readOnly/></label><label>Вид работы<input value={photo.work_type_name||'Не определён'} readOnly/></label>
        <label className="checkbox"><input type="checkbox" checked={photo.is_defect} disabled/>Неисправность</label>
        {[photo.detected_city,photo.detected_address].some(Boolean) && <p>{[photo.detected_city,photo.detected_address].filter(Boolean).join(', ')}</p>}
        <p className="hint">Получено {new Date(photo.received_at).toLocaleString('ru-RU',{timeZone:meta.timezone})}</p>
        {photo.latitude!==null && photo.longitude!==null && <a className="text-button" href={`https://yandex.ru/maps/?pt=${photo.longitude},${photo.latitude}&z=17&l=map`} target="_blank" rel="noreferrer"><MapPin size={16}/>Посмотреть точку на карте</a>}
        <p className="hint">Доступен только просмотр фотографии.</p>
        <button type="button" className="photo-forward-button" onClick={()=>setForwarding(true)}><Share2 size={17}/>Переслать фото</button>
      </section></div></div>}
    <footer className="inspection-photo-navigation"><button disabled={!navigation.previous} onClick={()=>navigation.previous&&onMove(navigation.previous)}><ChevronLeft size={17}/>Предыдущая</button>
      <button onClick={onClose}>{fromChat?'К переписке':'К списку'}</button><button disabled={!navigation.next} onClick={()=>navigation.next&&onMove(navigation.next)}>Следующая<ChevronRight size={17}/></button></footer>
    {photo && forwarding && <InspectionForward photo={{...photo,organization_id:org}} onClose={()=>setForwarding(false)} onSent={peer=>{setForwarding(false);notify('Фотография отправлена: '+peer.name);}}/>}
  </section>;
}
