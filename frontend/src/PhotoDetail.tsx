import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ArrowUpRight, Camera, ChevronRight, MapPin, RefreshCw, Share2, UserRound } from 'lucide-react';
import { api, dateLabel, reasonNames, processingErrorLabel } from './api';
import { ErrorBox, StatusBadge, useApp } from './App';
import type { Photo } from './types';
import RemoveMissingPreview from './RemoveMissingPreview';
import { hasPermission } from './permissions';
import { nextPhotoId, photoListBackLink } from './photoNavigation';
import { canEditPhoto, workTypeLabel } from './photoWork';
import DefectCheckbox from './DefectCheckbox';
import WorkTypeChoices from './WorkTypeChoices';
import ForwardPhoto from './ForwardPhoto';

export default function PhotoDetail() {
  const {id}=useParams();const [params]=useSearchParams();const navigate=useNavigate();const {meta,notify,user}=useApp();
  const [photo,setPhoto]=useState<Photo|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[form,setForm]=useState<Record<string,string>>({});
  const review=params.get('review')==='1';
  const location=useLocation();
  const [isDefect,setIsDefect]=useState(false);
  const [forwarding,setForwarding]=useState(false);
  const loadRevision = useRef(0);
  async function load() {
    const revision = ++loadRevision.current;
    setError('');
    try {
      const value = await api<Photo>('/photos/' + id);
      if (revision !== loadRevision.current) return;
      setPhoto(value);
      setIsDefect(!!value.is_defect);
      setForm({
        photo_date: value.photo_date || '',
        photo_time: value.photo_time || '',
        latitude: value.latitude === null ? '' : String(value.latitude),
        longitude: value.longitude === null ? '' : String(value.longitude),
        work_type: value.is_spam ? 'SPAM' : value.work_type || '',
        district_id: value.district_source === 'OPERATOR' && value.district_id !== null ? String(value.district_id) : '',
      });
    } catch (e) {
      if (revision === loadRevision.current) setError((e as Error).message);
    }
  }
  useEffect(() => {
    setPhoto(null);
    setForwarding(false);
    void load();
    return () => { loadRevision.current++; };
  }, [id]);
  const back=()=>navigate(photoListBackLink(Number(id),params),{state:location.state});
  const field=(name:string,value:string)=>setForm(f=>({...f,[name]:value}));
  async function save(e:FormEvent){e.preventDefault();if(!photo||busy)return;setBusy(true);setError('');try{
    const advance=review||(e.nativeEvent as SubmitEvent).submitter?.getAttribute('value')!=='save';
    const nextId=advance?await nextPhotoId(photo.id,params):null;
    const result=await api<{status:string}>('/photos/'+id,'PATCH',form.work_type==='SPAM'?{version:photo.version,is_spam:true}:{version:photo.version,is_spam:false,is_defect:isDefect,photo_date:form.photo_date||null,photo_time:form.photo_time||null,latitude:form.latitude===''?null:Number(form.latitude),longitude:form.longitude===''?null:Number(form.longitude),work_type:form.work_type||null,district_id:form.district_id?Number(form.district_id):null});
    notify(result.status==='SPAM'?'Фотография перемещена в спам. Файл будет синхронизирован.':result.status==='ACCEPTED'?'Фотография принята. Файл будет синхронизирован.':'Изменения сохранены. Остались вопросы для проверки.');
    if(advance){if(nextId!==null)navigate(`/photos/${nextId}?${params.toString()}`,{state:location.state});else back();}else await load();
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  if(!photo)return <><ErrorBox error={error}/><p className="loading">{error?'Не удалось открыть фотографию':'Открываем фотографию…'}</p><button onClick={back}>Вернуться к списку</button></>;
  const canEdit=hasPermission(user,'photos_edit');
  const editable=canEditPhoto(user,photo);
  return <><button className="back-link" onClick={back}><ArrowLeft size={16}/>{params.get('operator_chat')?'К переписке':params.get('from_map')==='1'?'Карта фотографий':review?'Очередь проверки':params.get('spam')==='1'?'Спам':'Все фотографии'}</button><header className="page-header"><div><span className="eyebrow">КАРТОЧКА ФОТОГРАФИИ</span><h1>Фотография #{photo.id}</h1><p>{photo.chat_name} · Получена {dateLabel(photo.received_at)}</p><div className="photo-sender"><UserRound size={18}/><span>Прислал: <strong>{photo.sender_name||(photo.sender_id?'ID '+photo.sender_id:'Отправитель не указан')}</strong>{photo.sender_name&&photo.sender_id&&<small className="mono">ID {photo.sender_id}</small>}</span></div></div><StatusBadge value={photo.status}/></header><ErrorBox error={error}/>{error&&<button onClick={load}><RefreshCw size={16}/>Обновить карточку</button>}<div className="review-layout"><div className="review-image-column"><div className="review-image">{photo.preview_url?<a href={photo.preview_url} target="_blank" rel="noreferrer"><img src={photo.preview_url} alt={'Фотография №'+photo.id}/></a>:<div className="empty"><Camera size={48}/><p>Превью недоступно</p></div>}</div><div className="image-caption"><span>Изображение для просмотра</span>{hasPermission(user,'originals_view')&&photo.yandex_disk_path&&photo.processing_error!=='ORIGINAL_MISSING'&&<a href={'/api/photos/'+photo.id+'/original'} target="_blank" rel="noreferrer">Открыть оригинал<ArrowUpRight size={15}/></a>}</div>{photo.review_reason.length>0&&<div className="review-reasons"><h3>Что нужно проверить</h3>{photo.review_reason.map(r=><span key={r}>{reasonNames[r]||r}</span>)}</div>}<section className="panel metadata"><h2>Данные обработки</h2><dl><dt>Режим обмена</dt><dd>{photo.cohort==='production'?'Рабочее фото':'Тестовое фото — не передаётся в рабочую АРМ'}</dd><dt>MAX message ID</dt><dd className="mono">{photo.max_message_id}</dd><dt>Микрорайон</dt><dd>{photo.district_name||'Не определён'}{photo.district_source==='OPERATOR'&&' · выбран вручную'}</dd><dt>Источник классификации</dt><dd>{photo.work_type_source==='AI'?'Локальная нейросеть':photo.work_type_source==='OPERATOR'?'Оператор':photo.work_type_source==='CHAT_FIXED'?'Настройка чата':'—'}</dd><dt>Уверенность нейросети</dt><dd>{photo.ai_confidence===null?'—':Math.round(photo.ai_confidence*100)+'%'}</dd><dt>Варианты нейросети</dt><dd>{photo.ai_alternatives.map(a=>meta.work_types.find(w=>w.code===a)?.name||a).join('; ')||'—'}</dd><dt>Яндекс.Диск</dt><dd className="mono">{photo.yandex_disk_path||'Ожидает загрузки'}</dd><dt>Синхронизация</dt><dd>{({SYNCED:'Завершена',PENDING:'Ожидает',ERROR:'Ошибка',NOT_REQUIRED:'Не требуется'} as Record<string,string>)[photo.storage_status]}</dd></dl>{photo.processing_error&&<><ErrorBox error={processingErrorLabel(photo.processing_error)}/>{canEdit&&<button onClick={async()=>{try{await api('/photos/'+id+'/retry','POST');notify('Повторная обработка поставлена в очередь');}catch(e){setError((e as Error).message);}}}><RefreshCw size={15}/>{photo.processing_error==='ORIGINAL_MISSING'?'Проверить снова':'Повторить обработку'}</button>}</>}<RemoveMissingPreview photo={photo} onRemoved={()=>{notify('Недоступное превью убрано. Задачи синхронизации остановлены.');back();}}/><details><summary>Распознанный текст</summary><pre>{photo.ocr_raw_text||'Текст не распознан'}</pre></details><details><summary>Исходный результат нейросети</summary><pre>{JSON.stringify(photo.ai_result,null,2)}</pre></details></section></div><div><form className="panel review-form" onSubmit={save}><div className="section-title"><h2>Данные фотографии</h2><span className="count-pill">#{photo.id}</span></div><fieldset disabled={!editable||busy}><fieldset disabled={form.work_type==='SPAM'}><div className="form-grid"><label>Дата фотографии<input type="date" value={form.photo_date} onChange={e=>field('photo_date',e.target.value)}/></label><label>Время<input type="time" step="1" value={form.photo_time} onChange={e=>field('photo_time',e.target.value)}/></label><label>Широта<input type="number" min="-90" max="90" step="any" value={form.latitude} onChange={e=>field('latitude',e.target.value)} placeholder="Не указана"/></label><label>Долгота<input type="number" min="-180" max="180" step="any" value={form.longitude} onChange={e=>field('longitude',e.target.value)} placeholder="Не указана"/></label></div>{photo.latitude!==null&&photo.longitude!==null&&<a className="text-button" href={`https://yandex.ru/maps/?pt=${photo.longitude},${photo.latitude}&z=17&l=map`} target="_blank" rel="noreferrer">Посмотреть точку на карте<ArrowUpRight size={15}/></a>}<label>Микрорайон<select value={form.district_id||''} onChange={e=>field('district_id',e.target.value)}><option value="">Определять по координатам</option>{meta.districts.filter(d=>d.active||(photo.district_source==='OPERATOR'&&d.id===photo.district_id)).map(d=><option key={d.id} value={d.id}>{d.name}{!d.active?' (неактивен)':''}</option>)}</select></label><p className="hint"><MapPin size={15}/>{form.district_id?'Микрорайон выбран вручную. Координаты можно оставить пустыми.':'Микрорайон определяется по координатам после сохранения. Если координат нет или результат неверный, выберите микрорайон вручную.'}</p></fieldset><label>Категория фотографии<select value={form.work_type} onChange={e=>field('work_type',e.target.value)}><option value="">Не определён</option>{hasPermission(user,'spam_view')&&<option value="SPAM">Спам — случайное или неподходящее фото</option>}{meta.work_types.map(w=><option key={w.code} value={w.code}>{workTypeLabel(w.name,isDefect)}</option>)}</select></label><DefectCheckbox className="defect-control" photoId={photo.id} workTypeName={meta.work_types.find(w=>w.code===form.work_type)?.name||'Не определён'} checked={isDefect&&form.work_type!=='SPAM'} disabled={!editable||busy||form.work_type==='SPAM'} onConfirm={setIsDefect}/>{isDefect&&form.work_type!=='SPAM'&&<p className="defect-summary" aria-live="polite">{workTypeLabel(meta.work_types.find(w=>w.code===form.work_type)?.name||'Не определён',true)}</p>}{hasPermission(user,'spam_view')&&<button type="button" className={'spam-option '+(form.work_type==='SPAM'?'selected':'')} aria-pressed={form.work_type==='SPAM'} onClick={()=>field('work_type','SPAM')}>Спам — случайное или неподходящее фото</button>}{form.work_type==='SPAM'&&<p className="hint">После сохранения фото уйдёт в раздел «Спам» и отдельную папку спама рядом с основным архивом на Диске. Оно не попадёт в отчёты о работах и обучение. Чтобы вернуть его, выберите вид работы и сохраните.</p>}</fieldset><WorkTypeChoices items={meta.work_types} value={form.work_type} isDefect={isDefect} disabled={!editable||busy} onChange={code=>field('work_type',code)}/><fieldset disabled={!editable||busy}>{canEdit&&<div className="photo-save-actions"><button type="submit" name="action" value="next" className="primary save-button" disabled={busy}>{busy?'Сохраняем…':form.work_type==='SPAM'?'В спам и перейти дальше':'Сохранить и перейти дальше'}<ChevronRight size={16}/></button>{!review&&<button type="submit" name="action" value="save" className="save-button" disabled={busy}>{form.work_type==='SPAM'?'Переместить в спам':'Сохранить изменения'}</button>}</div>}</fieldset>{!editable&&<p className="hint">{canEdit?'Редактирование доступно после первичной обработки оригинала.':'Доступен только просмотр фотографии.'}</p>}<button type="button" className="photo-forward-button" disabled={busy} onClick={()=>setForwarding(true)}><Share2 size={17}/>Переслать фото</button></form><section className="panel history"><h2>История изменений</h2>{photo.history.length===0?<p className="muted">Изменений ещё не было</p>:photo.history.map(h=><details key={h.id}><summary>{dateLabel(h.at)} · {h.action} · {h.user_id?meta.operators.find(o=>o.id===h.user_id)?.name||h.user_id:'Система'}</summary><pre>{JSON.stringify({до:h.old_value,после:h.new_value},null,2)}</pre></details>)}</section></div></div>{forwarding&&<ForwardPhoto key={photo.id} photo={photo} onClose={()=>setForwarding(false)} onSent={peer=>{setForwarding(false);notify('Фотография отправлена: '+peer.name);}}/>}</>;
}
