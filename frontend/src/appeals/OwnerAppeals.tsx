import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowDownToLine, ArrowLeft, ArrowUpRight, Camera, ChevronLeft, ChevronRight, Inbox, LockKeyhole, MessageCircle, Plus, RefreshCw, Search, X } from 'lucide-react';
import { api } from '../api';
import AppealActions from './AppealActions';
import type { WorkflowAppeal } from './AppealActions';
import AppealDiscussion from './AppealDiscussion';
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
type Page = {items: Appeal[]; total: number; page: number; page_size: number; categories: Record<string, string>; public_url: string; can_manage?: boolean; can_execute?: boolean};
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
  return <section className="owner-appeals">
    <header className="page-header"><div><span className="eyebrow">{organization ? 'ОБРАЩЕНИЯ В ВАШУ ОРГАНИЗАЦИЮ' : 'ОБРАЩЕНИЯ ВСЕХ ОРГАНИЗАЦИЙ'}</span><h1>Обращения</h1>
      <p>Нарушения от жителей и проверяющих: описание, фотографии и состояние рассмотрения.</p></div>
      <div className="owner-appeal-header-actions">{onCreate && <button className="primary" onClick={onCreate}><Plus size={17}/>Написать жалобу</button>}
        <button disabled={busy} aria-label="Обновить обращения" onClick={() => setRevision(value => value + 1)}><RefreshCw size={18}/></button></div></header>
    {composer}
    {error && <p className="error" role="alert">{error}</p>}
    {selected !== null ? <>
      <button className="owner-appeal-back" disabled={busy} onClick={() => setSelected(null)}><ArrowLeft size={16}/>Все обращения</button>
      {!detail ? !error && <p className="loading">Открываем обращение…</p> : <div className="owner-appeal-detail">
        <article className="panel"><div className="section-title"><h2>{detail.number}</h2><AppealBadges status={detail.status} messages={data?.items.find(item => item.id === detail.id)?.unanswered_comments ?? detail.unanswered_comments}/></div>
          <p className="hint">Получено {moment(detail.created_at)}{detail.archived_at && ' · В архиве'}</p>{detail.submitted_by_inspector_name && <p className="owner-appeal-source"><LockKeyhole size={14}/>От проверяющего: {detail.submitted_by_inspector_name} · Только в «Метке»</p>}
          <h3>{detail.subject || detail.work_type_name || data?.categories?.[detail.category] || detail.category || 'Вид работ не назначен'}</h3>
          {detail.subject && <p className="hint">Вид работ: {detail.work_type_name || data?.categories?.[detail.category] || detail.category || 'не назначен'}</p>}
          <dl><dt>Адрес</dt><dd>{detail.city}, {detail.address}</dd><dt>Место</dt><dd>{detail.place}</dd>
            <dt>Описание</dt><dd className="owner-appeal-text">{detail.description}</dd>
            <dt>Организация</dt><dd>{detail.organization_name || detail.organization_hint || 'Не назначена — обращение из прежней формы'}</dd>
            {!detail.submitted_by_inspector_name && !readOnly && detail.can_manage !== false && !detail.can_execute && <><dt>Контакт</dt><dd>{detail.contact || 'Не оставлен'}</dd></>}</dl>
          {!detail.archived_at && !readOnly && detail.can_manage !== false && !detail.can_execute && <div className="owner-appeal-edit">
            {detail.organization_id && <label>Вид работ<select name="work_type" disabled={busy || workTypes === null} value={workType} onChange={event => setWorkType(event.target.value)}>
              <option value="">Не назначен</option>
              {detail.category && !workTypes?.some(work => work.code === detail.category) && <option value={detail.category} disabled>{detail.work_type_name || detail.category}</option>}
              {workTypes?.map(work => <option key={work.code} value={work.code}>{work.name}</option>)}
            </select></label>}
            {workTypesError && <p className="error" role="alert">{workTypesError}</p>}
            <label>Состояние<select disabled={busy} value={nextStatus} onChange={event => setNextStatus(event.target.value as Status)}>
            {Object.entries(statuses).filter(([key]) => ['NEW','IN_REVIEW','SPAM'].includes(key) || key === detail.status).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label>Внутренняя заметка<textarea disabled={busy} rows={4} maxLength={4000} placeholder="Что проверено и что нужно сделать…" value={note} onChange={event => setNote(event.target.value)}/></label>
            <p className="hint">Заметка видна администраторам этой организации и владельцу сервиса.</p>
            <button className="primary" disabled={busy || (nextStatus === detail.status && note === detail.owner_note && workType === detail.category)} onClick={() => void save()}>{busy ? 'Сохраняем…' : 'Сохранить'}</button></div>}
          {detail.latitude != null && detail.longitude != null && <a className="button" href={'https://yandex.ru/maps/?' + new URLSearchParams({pt: detail.longitude + ',' + detail.latitude, z: '18', l: 'map'})} target="_blank" rel="noreferrer">Место проблемы на карте</a>}
          <AppealActions key={detail.id + ':' + detail.version} appeal={detail} endpoint={endpoint} readOnly={readOnly} changed={() => setRevision(value => value + 1)}/>
        </article>
        <div className="owner-appeal-photos">{detail.photos.map((photo, index) => <article className="panel" key={photo.id}>
          <a href={photo.url} target="_blank" rel="noreferrer"><img src={photo.url} alt={`Фотография обращения ${detail.number}, снимок ${index + 1}`}/></a>
          <div><strong>Фотография обращения</strong>
            <a className="button" href={photo.original_url} target="_blank" rel="noreferrer"><ArrowDownToLine size={15}/>Открыть фотографию</a></div>
        </article>)}
          <AppealDiscussion key={detail.id} endpoint={endpoint + '/' + detail.id} archived={!!detail.archived_at}/></div>
      </div>}
    </> : <>
      {data && !readOnly && data.can_manage !== false && !data.can_execute && <div className="panel owner-appeal-public"><div><strong>Страница для жителей</strong><p className="hint">Передайте ссылку или разместите её в объявлениях.</p></div>
        <div className="owner-signal-share"><a className="button" href={data.public_url} target="_blank" rel="noreferrer">Открыть форму<ArrowUpRight size={16}/></a><SignalShare url={data.public_url}/></div></div>}
      <div className="appeal-folder-tabs" role="tablist" aria-label="Раздел обращений">{[false, true].map(value => <button key={String(value)} role="tab" aria-selected={archived === value} onClick={() => {setArchived(value); setPage(1); setStatus('');}}>{value ? 'Архив' : 'Рабочий список'}</button>)}</div>
      <div className="owner-appeal-toolbar"><label>Состояние<select value={status} onChange={event => {setStatus(event.target.value); setPage(1);}}><option value="">Все обращения</option>
        {Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><span className="hint">{data ? `${data.total} обращений` : 'Загружаем…'}</span></div>
      <form className="owner-appeal-search" role="search" onSubmit={event => {event.preventDefault(); setQuery(search.trim()); setPage(1);}}>
        <Search size={19} aria-hidden="true"/><input type="search" aria-label="Поиск обращений" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} placeholder="Поиск по тексту, адресу, номеру или дате"/>
        {search && <button type="button" aria-label="Очистить поиск" onClick={() => {setSearch(''); setQuery(''); setPage(1);}}><X size={18}/></button>}
      </form>
      {!data ? !error && <p className="loading">Загружаем обращения…</p> : !data.items.length ? <div className="panel empty"><Inbox size={32}/><h3>{query ? 'Ничего не найдено' : 'Обращений пока нет'}</h3><p>{query ? 'Попробуйте другие слова, адрес, номер или дату.' : 'Новые анкеты жителей появятся здесь.'}</p></div> : <div className="owner-appeal-list">{data.items.map(item => <button className="panel owner-appeal-card owner-appeal-card-open" key={item.id} onClick={() => setSelected(item.id)}>
        <img src={item.preview_url} alt="" loading="lazy"/><div><div className="owner-appeal-card-top"><strong>{item.number}</strong><AppealBadges status={item.status} messages={item.unanswered_comments}/></div>
          {item.submitted_by_inspector_name && <span className="owner-appeal-source"><LockKeyhole size={13}/>От проверяющего · Только в «Метке»</span>}
          <h3>{item.subject || item.work_type_name || data.categories?.[item.category] || item.category || 'Вид работ не назначен'}</h3>{(!organization || readOnly) && <p>{item.organization_name || 'Без назначенной организации'}</p>}<p>{item.city}, {item.address}</p><p className="owner-appeal-excerpt">{item.description}</p>
          <small>{moment(item.created_at)}<span><Camera size={13}/>{item.photo_count}</span></small></div></button>)}</div>}
      {data && data.total > data.page_size && <div className="owner-appeal-pagination"><button disabled={page <= 1} onClick={() => setPage(value => value - 1)}><ChevronLeft size={17}/></button>
        <span>{page} / {Math.ceil(data.total / data.page_size)}</span><button disabled={page * data.page_size >= data.total} onClick={() => setPage(value => value + 1)}><ChevronRight size={17}/></button></div>}
    </>}
  </section>;
}

function AppealBadges({status, messages = 0}: {status: string; messages?: number}) {
  return <span className="appeal-badges"><span className={'badge appeal-status-' + status}>{statuses[status]}</span>
    {messages > 0 && <span className="appeal-message-notification" role="status"><MessageCircle size={16}/>Новые сообщения: {messages}</span>}</span>;
}
