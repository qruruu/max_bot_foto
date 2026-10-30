import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowLeft, ArrowRight, ArrowUpRight, Building2, CalendarDays, Camera, ChevronDown, ChevronLeft, ChevronRight, FileText, Inbox, Info, LockKeyhole, MapPin, Maximize2, MessageCircle, Plus, RefreshCw, Search, UserRound, Users, X } from 'lucide-react';
import { api } from '../api';
import AppealActions from './AppealActions';
import type { WorkflowAppeal } from './AppealActions';
import AppealDiscussion from './AppealDiscussion';
import AppealLocation from './AppealLocation';
import { SignalShare } from './AppealShare';
import { appealStatuses } from './Wall';
import './owner-appeals.css';

type Status = 'NEW' | 'IN_REVIEW' | 'ASSIGNED' | 'IN_PROGRESS' | 'COMPLETED' | 'REJECTED' | 'CANCELLED' | 'RESOLVED' | 'DECLINED' | 'SPAM';
type Appeal = {id: number; number: string; city: string; address: string; place: string; category: string; subject?: string; description: string;
  organization_id: string | null; organization_name: string; work_type_name: string;
  organization_hint: string; contact: string; photo_count: number; status: Status; owner_note: string; version: number;
  created_at: string; updated_at: string; preview_url: string; submitted_by_inspector_name?: string; unanswered_comments?: number};
type Photo = {id: string; url: string; preview_url: string; original_url: string; captured_at: string; latitude: number; longitude: number; accuracy: number};
type Detail = Appeal & WorkflowAppeal & {photos: Photo[]; latitude?: number; longitude?: number};
type Page = {items: Appeal[]; total: number; page: number; page_size: number; categories: Record<string, string>; public_url: string; yandex_maps_api_key?: string; can_manage?: boolean; can_execute?: boolean};
type WorkType = {code: string; name: string};
const statuses = appealStatuses;
const moment = (value: string) => new Date(value).toLocaleString('ru-RU', {dateStyle: 'short', timeStyle: 'short'});

export default function OwnerAppeals({organization = false, endpoint: customEndpoint, readOnly = false, refreshKey = 0, onCreate, composer}: {
  organization?: boolean; endpoint?: string; readOnly?: boolean; refreshKey?: number; onCreate?: () => void; composer?: ReactNode;
}) {
  const endpoint = customEndpoint || (organization ? '/appeals' : '/platform/appeals');
  const [data, setData] = useState<Page | null>(null), [status, setStatus] = useState(''), [page, setPage] = useState(1);
  const [detail, setDetail] = useState<Detail | null>(null), [selected, setSelected] = useState<number | null>(null);
  const [nextStatus, setNextStatus] = useState<Status>('NEW'), [note, setNote] = useState('');
  const [workType, setWorkType] = useState(''), [workTypes, setWorkTypes] = useState<WorkType[] | null>(null);
  const [workTypesError, setWorkTypesError] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [revision, setRevision] = useState(0);
  const [archived, setArchived] = useState(false);
  const [detailTab, setDetailTab] = useState<'request' | 'work'>('request');
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  useEffect(() => {setDetailTab('request'); setDescriptionOpen(false);}, [selected, endpoint]);
  const [search, setSearch] = useState(''), [query, setQuery] = useState('');
  const active = useRef(true);
  useEffect(() => {active.current = true; return () => {active.current = false;};}, []);
  useEffect(() => {
    const timer = window.setTimeout(() => {setQuery(search.trim()); setPage(1);}, 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  useEffect(() => {
    const controller = new AbortController(); setError(''); setData(null); let refreshing = false;
    async function refresh(initial = false) {
      if (refreshing || document.hidden && !initial) return;
      refreshing = true;
      try {
        const params = new URLSearchParams({page: String(page)});
        if (status) params.set('status', status);
        if (archived) params.set('archived', 'true');
        if (query) params.set('q', query);
        const result = await api<Page>(`${endpoint}?${params}`, 'GET', undefined, controller.signal);
        if (controller.signal.aborted) return;
        const lastPage = Math.max(1, Math.ceil(result.total / result.page_size));
        if (page > lastPage) setPage(lastPage);
        else setData(result);
      } catch (error) {if (!controller.signal.aborted && initial) setError((error as Error).message);}
      finally {refreshing = false;}
    }
    void refresh(true);
    const changed = () => {void refresh();}, timer = window.setInterval(changed, 10_000);
    for (const event of ['focus', 'online', 'appeal-discussion-changed']) window.addEventListener(event, changed);
    return () => {controller.abort(); window.clearInterval(timer); for (const event of ['focus', 'online', 'appeal-discussion-changed']) window.removeEventListener(event, changed);};
  }, [page, status, archived, query, revision, endpoint, refreshKey]);
  useEffect(() => {setSelected(null); setPage(1); setSearch(''); setQuery('');}, [endpoint]);
  useEffect(() => {
    const refresh = () => {setSelected(null); setStatus(''); setSearch(''); setQuery(''); setPage(1); setRevision(value => value + 1);};
    window.addEventListener('refresh-appeals', refresh);
    return () => window.removeEventListener('refresh-appeals', refresh);
  }, []);
  useEffect(() => {
    if (selected === null) {setDetail(null); return;}
    const controller = new AbortController(); setError(''); setDetail(null); setWorkTypes(null); setWorkTypesError('');
    api<Detail>(endpoint + '/' + selected, 'GET', undefined, controller.signal).then(item => {
      if (controller.signal.aborted) return;
      setDetail(item); setNextStatus(item.status); setNote(item.owner_note); setWorkType(item.category);
      if (!readOnly && item.can_manage !== false && !item.can_execute && !item.archived_at && item.organization_id) {
        void api<WorkType[]>(endpoint + '/' + selected + '/work-types', 'GET', undefined, controller.signal)
          .then(value => {if (!controller.signal.aborted) setWorkTypes(value);})
          .catch(error => {if (!controller.signal.aborted) setWorkTypesError(error.message);});
      }
    }).catch(error => {if (error.name !== 'AbortError') setError(error.message);});
    return () => controller.abort();
  }, [selected, revision, endpoint, refreshKey, readOnly]);

  async function save() {
    if (!detail || readOnly) return;
    setBusy(true); setError('');
    try {
      await api(endpoint + '/' + detail.id, 'PATCH', {status: nextStatus, owner_note: note, expected_version: detail.version,
        ...(workType !== detail.category ? {category: workType} : {})});
      window.dispatchEvent(new Event('appeals-changed'));
      if (active.current) setRevision(value => value + 1);
    } catch (error) {if (active.current) setError((error as Error).message);}
    finally {if (active.current) setBusy(false);}
  }
  const manageDetail = !!detail && !detail.archived_at && !readOnly && detail.can_manage !== false && !detail.can_execute;
  const processingForm = detail && manageDetail ? <section className="panel owner-appeal-edit">
    <h3>Обработка обращения</h3><div className="appeal-edit-fields">
      {detail.organization_id && <label>Вид работ<select name="work_type" disabled={busy || workTypes === null} value={workType} onChange={event => setWorkType(event.target.value)}>
        <option value="">Не назначен</option>
        {detail.category && !workTypes?.some(work => work.code === detail.category) && <option value={detail.category} disabled>{detail.work_type_name || detail.category}</option>}
        {workTypes?.map(work => <option key={work.code} value={work.code}>{work.name}</option>)}
      </select></label>}
      <label>Состояние<select disabled={busy} value={nextStatus} onChange={event => setNextStatus(event.target.value as Status)}>
        {Object.entries(statuses).filter(([key]) => ['NEW','IN_REVIEW','SPAM'].includes(key) || key === detail.status).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></label>
    </div>
    {workTypesError && <p className="error" role="alert">{workTypesError}</p>}
    <label>Внутренняя заметка<textarea disabled={busy} rows={3} maxLength={4000} placeholder="Введите заметку по обращению…" value={note} onChange={event => setNote(event.target.value)}/></label>
    <footer><p className="hint">Только для администраторов и владельца сервиса.</p><button className="primary" disabled={busy || (nextStatus === detail.status && note === detail.owner_note && workType === detail.category)} onClick={() => void save()}>{busy ? 'Сохраняем…' : 'Сохранить'}</button></footer>
  </section> : null;
  return <section className="owner-appeals">
    {selected === null && <header className="page-header"><div><h1>Обращения</h1><p>Обращения жителей и проверяющих</p></div>
      {onCreate && <button className="primary" onClick={onCreate}><Plus size={17}/>Написать жалобу</button>}</header>}
    {composer}
    {error && <p className="error" role="alert">{error}</p>}
    {selected !== null ? <>
      <header className="appeal-detail-header">
        <button className="owner-appeal-back" disabled={busy} onClick={() => setSelected(null)}><ArrowLeft size={16}/>Все обращения</button>
        {detail && <><h1>{detail.number} · {appealTitle(detail)}</h1><AppealBadges status={detail.status} messages={data?.items.find(item => item.id === detail.id)?.unanswered_comments ?? detail.unanswered_comments}/>
          {detailTab === 'request' && <button className="primary appeal-go-work" onClick={() => setDetailTab('work')}>Перейти к обработке<ArrowRight size={17}/></button>}</>}
      </header>
      {!detail ? !error && <p className="loading">Открываем обращение…</p> : <>
        <div className="appeal-detail-tabs" role="tablist" aria-label="Разделы обращения" onKeyDown={event => {
          if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            event.preventDefault(); const next = detailTab === 'request' ? 'work' : 'request'; setDetailTab(next);
            document.getElementById('appeal-tab-' + next)?.focus();
          }
        }}>
          <button id="appeal-tab-request" role="tab" aria-selected={detailTab === 'request'} aria-controls="appeal-panel-request" tabIndex={detailTab === 'request' ? 0 : -1} onClick={() => setDetailTab('request')}>Заявка</button>
          <button id="appeal-tab-work" role="tab" aria-selected={detailTab === 'work'} aria-controls="appeal-panel-work" tabIndex={detailTab === 'work' ? 0 : -1} onClick={() => setDetailTab('work')}>Работа с обращением</button>
        </div>
        <div id="appeal-panel-request" role="tabpanel" aria-labelledby="appeal-tab-request" hidden={detailTab !== 'request'} className="owner-appeal-detail appeal-request-layout">
          <div className="appeal-request-copy">
            <section className="panel appeal-subject-panel"><h3>Тема обращения</h3><h2>{appealTitle(detail)}</h2></section>
            <section className="panel appeal-description-panel"><h3>{detail.submitted_by_inspector_name ? 'Описание проверяющего' : 'Описание жителя'}</h3>
              {detail.submitted_by_inspector_name && <p className="owner-appeal-source"><LockKeyhole size={14}/>От проверяющего: {detail.submitted_by_inspector_name} · Только в «Метке»</p>}
              <p className={'owner-appeal-text appeal-description' + (descriptionOpen ? ' is-expanded' : '')}>{detail.description}</p>
              {detail.description.length > 450 && <button className="appeal-description-toggle" aria-expanded={descriptionOpen} onClick={() => setDescriptionOpen(value => !value)}>{descriptionOpen ? 'Свернуть текст' : 'Показать весь текст'}<ChevronDown size={15}/></button>}
              <dl className="appeal-request-facts">
                <div><dt><MapPin size={18}/>Адрес:</dt><dd>{detail.city}, {detail.address}{detail.place && <small>{detail.place}</small>}</dd></div>
                <div><dt><Building2 size={18}/>Организация:</dt><dd>{detail.organization_name || detail.organization_hint || 'Не назначена'}</dd></div>
                {!detail.submitted_by_inspector_name && !readOnly && detail.can_manage !== false && !detail.can_execute && <div><dt><UserRound size={18}/>Контакт:</dt><dd>{detail.contact || 'Не оставлен'}</dd></div>}
                <div><dt><CalendarDays size={18}/>Получено:</dt><dd>{moment(detail.created_at)}{detail.archived_at && <small>В архиве</small>}</dd></div>
              </dl>
            </section>
            {processingForm}
          </div>
          <div className="owner-appeal-photos">
            {detail.photos.length ? detail.photos.map((photo, index) => <section className="panel appeal-resident-photo" key={photo.id}>
              <header><h3>{detail.submitted_by_inspector_name ? 'Фотография от проверяющего' : 'Фотография от жителя'}{detail.photos.length > 1 && <span> · {index + 1} из {detail.photos.length}</span>}</h3></header>
              <div className="appeal-resident-photo-image"><a href={photo.url} target="_blank" rel="noreferrer"><img src={photo.url} alt={`Фотография обращения ${detail.number}, снимок ${index + 1}`}/></a>
                <a className="button" href={photo.original_url || photo.url} target="_blank" rel="noreferrer"><Maximize2 size={15}/>Открыть фотографию</a></div>
            </section>) : <section className="panel appeal-photo-empty"><Camera size={30}/><p>Фотографии не приложены</p></section>}
            <AppealLocation longitude={detail.longitude} latitude={detail.latitude} apiKey={data?.yandex_maps_api_key || ''}/>
          </div>
        </div>
        <div id="appeal-panel-work" role="tabpanel" aria-labelledby="appeal-tab-work" hidden={detailTab !== 'work'}>
          <div className="appeal-work-context"><span><MapPin size={17}/><small>Адрес:</small>{detail.city}, {detail.address}</span><span><FileText size={16}/><small>Тема:</small>{appealTitle(detail)}</span></div>
          <AppealActions key={detail.id + ':' + detail.version} appeal={detail} endpoint={endpoint} readOnly={readOnly} changed={() => setRevision(value => value + 1)}
            discussion={<AppealDiscussion key={detail.id} endpoint={endpoint + '/' + detail.id} archived={!!detail.archived_at}/>}/>
        </div>
      </>}
    </> : <>
      {data && data.public_url && !readOnly && data.can_manage !== false && !data.can_execute && <section className="panel owner-appeal-public">
        <Users className="appeal-public-icon" size={36}/><div className="appeal-public-copy"><h2>Страница для жителей</h2><p>Откройте форму подачи обращений для жителей. Скопируйте ссылку или поделитесь в социальных сетях.</p></div>
        <div className="owner-signal-share"><a className="button primary" href={data.public_url} target="_blank" rel="noreferrer"><ArrowUpRight size={17}/>Открыть форму</a><SignalShare url={data.public_url}/></div>
      </section>}
      <div className="appeal-folder-tabs" role="tablist" aria-label="Раздел обращений">{[false, true].map(value => <button key={String(value)} role="tab" aria-selected={archived === value} onClick={() => {setArchived(value); setPage(1); setStatus('');}}>{value ? 'Архив' : 'Рабочий список'}{data && archived === value && <span className="appeal-folder-count">{data.total}</span>}</button>)}</div>
      <div className="owner-appeal-toolbar">
        <label>Состояние<select value={status} onChange={event => {setStatus(event.target.value); setPage(1);}}><option value="">Все обращения</option>{Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <form className="owner-appeal-search" role="search" onSubmit={event => {event.preventDefault(); setQuery(search.trim()); setPage(1);}}>
          <Search size={20} aria-hidden="true"/><input type="search" aria-label="Поиск обращений" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} placeholder="Поиск по тексту, номеру или дате"/>
          {search && <button type="button" aria-label="Очистить поиск" onClick={() => {setSearch(''); setQuery(''); setPage(1);}}><X size={18}/></button>}
        </form>
        <span className="appeal-total hint">{data ? appealCount(data.total) : 'Загружаем…'}</span><button className="appeal-list-refresh" disabled={busy} aria-label="Обновить обращения" onClick={() => setRevision(value => value + 1)}><RefreshCw size={20}/></button>
      </div>
      <p className="appeal-list-hint"><Info size={18}/>Откройте обращение, чтобы увидеть заявку и работу по нему.</p>
      {!data ? !error && <p className="loading">Загружаем обращения…</p> : !data.items.length ? <div className="panel empty"><Inbox size={32}/><h3>{query ? 'Ничего не найдено' : 'Обращений пока нет'}</h3><p>{query ? 'Попробуйте другие слова, адрес, номер или дату.' : 'Новые анкеты жителей появятся здесь.'}</p></div> : <div className="owner-appeal-list">{data.items.map(item => <button className="panel owner-appeal-card owner-appeal-card-open" key={item.id} onClick={() => setSelected(item.id)}>
        <span className="appeal-list-photo">{item.preview_url ? <img src={item.preview_url} alt="" loading="lazy"/> : <Camera size={26}/>}</span>
        <span className="appeal-list-copy"><span className="owner-appeal-card-top"><strong>{item.number}</strong><span className="appeal-list-title">{appealTitle(item)}</span></span>
          <span className="appeal-list-meta"><span><MapPin size={17}/>{item.address}</span><span><CalendarDays size={17}/>{moment(item.created_at)}</span><span><Building2 size={17}/>{item.organization_name || 'Без назначенной организации'}</span></span>
          {item.submitted_by_inspector_name && <span className="owner-appeal-source"><LockKeyhole size={13}/>От проверяющего · Только в «Метке»</span>}
          <span className="owner-appeal-excerpt">{item.description}</span>
        </span>
        <AppealBadges status={item.status} messages={item.unanswered_comments}/><ChevronRight className="appeal-card-chevron" size={22}/>
      </button>)}</div>}
      {data && data.total > data.page_size && <div className="owner-appeal-pagination"><button aria-label="Предыдущая страница обращений" disabled={page <= 1} onClick={() => setPage(value => value - 1)}><ChevronLeft size={17}/></button>
        <span>{page} / {Math.ceil(data.total / data.page_size)}</span><button aria-label="Следующая страница обращений" disabled={page * data.page_size >= data.total} onClick={() => setPage(value => value + 1)}><ChevronRight size={17}/></button></div>}
    </>}
  </section>;
}

function appealTitle(item: Appeal) {
  return item.subject || item.description.split('\n')[0].slice(0, 100) || 'Обращение жителя';
}
function appealCount(count: number) {
  const mod = count % 100, digit = count % 10;
  return `${count} ${mod >= 11 && mod <= 14 ? 'обращений' : digit === 1 ? 'обращение' : digit >= 2 && digit <= 4 ? 'обращения' : 'обращений'}`;
}
function AppealBadges({status, messages = 0}: {status: string; messages?: number}) {
  return <span className="appeal-badges"><span className={'badge appeal-status-' + status}>{statuses[status]}</span>
    {messages > 0 && <span className="appeal-message-notification" role="status"><MessageCircle size={14}/><span className="appeal-message-copy">Новые сообщения: </span>{messages}</span>}</span>;
}
