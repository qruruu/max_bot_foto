import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ArrowUpRight, Building2, CalendarDays, Camera, ChevronDown, ChevronLeft, ChevronRight, Copy, FilterX, Inbox, LockKeyhole, MapPin, Maximize2, MessageCircle, Plus, RefreshCw, Search, SlidersHorizontal, UserRound, Users, X } from 'lucide-react';
import { api } from '../api';
import AppealActions from './AppealActions';
import AdminTaskForm from './AdminTaskForm';
import type { WorkflowAppeal } from './AppealActions';
import AppealDiscussion from './AppealDiscussion';
import AppealLocation from './AppealLocation';
import AppealStatistics from './AppealStatistics';
import AppealSourceFilter from './AppealSourceFilter';
import type { AppealSource } from './AppealSourceFilter';
import type { AppealFilterOptions } from './AppealStatistics';
import { SignalShare } from './AppealShare';
import { appealStatuses } from './Wall';
import { hasAppealDecision, isFinalAppeal } from './statuses';
import './owner-appeals.css';

type Status = 'NEW' | 'IN_REVIEW' | 'ASSIGNED' | 'IN_PROGRESS' | 'COMPLETED' | 'REJECTED' | 'CANCELLED' | 'RESOLVED' | 'DECLINED' | 'SPAM';
type Appeal = {id: number; number: string; city: string; address: string; place: string; category: string; subject?: string; description: string;
  organization_id: string | null; organization_name: string; work_type_name: string;
  organization_hint: string; contact: string; photo_count: number; status: Status; owner_note: string; version: number;
  created_at: string; updated_at: string; preview_url: string; source?: AppealSource; submitted_by_inspector_name?: string; unanswered_comments?: number;
  parent_id?: number | null; inspector_due_date?: string | null; child_count?: number; due_date?: string | null; operator_name?: string; overdue?: boolean};
type Photo = {id: string; url: string; preview_url: string; original_url: string; captured_at: string; latitude: number; longitude: number; accuracy: number};
type Detail = Appeal & WorkflowAppeal & {photos: Photo[]; cancelled_by_inspector?: boolean; latitude?: number; longitude?: number};
type Page = {items: Appeal[]; total: number; page: number; page_size: number; categories: Record<string, string>; public_url: string; yandex_maps_api_key?: string; can_manage?: boolean; can_execute?: boolean; filter_options?: AppealFilterOptions};
type WorkType = {code: string; name: string};
const statuses = appealStatuses;
const moment = (value: string) => new Date(value).toLocaleString('ru-RU', {dateStyle: 'short', timeStyle: 'short'});

export default function OwnerAppeals({organization = false, endpoint: customEndpoint, readOnly = false, refreshKey = 0, onCreate, composer, administrators = []}: {
  organization?: boolean; endpoint?: string; readOnly?: boolean; refreshKey?: number; onCreate?: () => void; composer?: ReactNode; administrators?: string[];
}) {
  const endpoint = customEndpoint || (organization ? '/appeals' : '/platform/appeals');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sharingOpen, setSharingOpen] = useState(false);
  const [creatingTask, setCreatingTask] = useState(false);
  const [data, setData] = useState<Page | null>(null), [status, setStatus] = useState(''), [page, setPage] = useState(1);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [params, setParams] = useSearchParams();
  const location = useLocation(), navigate = useNavigate();
  const appealParam = params.get('appeal') || '';
  const selected = /^[1-9]\d*$/.test(appealParam) && Number(appealParam) <= 2147483647 ? Number(appealParam) : null;
  const listPosition = useRef<{id: number; scrollY: number} | null>(null);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const focusedCard = useRef<number | null>(null);
  const [copyStatus, setCopyStatus] = useState('');
  const [nextStatus, setNextStatus] = useState<Status>('NEW'), [note, setNote] = useState('');
  const [workType, setWorkType] = useState(''), [workTypes, setWorkTypes] = useState<WorkType[] | null>(null);
  const [workTypesError, setWorkTypesError] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [revision, setRevision] = useState(0);
  const [archived, setArchived] = useState(false);
  const [showStatistics, setShowStatistics] = useState(false), [categoryFilter, setCategoryFilter] = useState(''), [operatorFilter, setOperatorFilter] = useState(''), [deadlineFilter, setDeadlineFilter] = useState('any');
  const [source, setSource] = useState<AppealSource>('all');
  const [filterOptions, setFilterOptions] = useState<AppealFilterOptions | null>(null);
  const [detailTab, setDetailTab] = useState<'request' | 'inspector' | 'executor'>('request');
  const [unread, setUnread] = useState({inspector:0, executor:0});
  useEffect(() => {setUnread({inspector:0, executor:0});}, [selected, endpoint]);
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const [requestedTab, setRequestedTab] = useState<typeof detailTab>('request');
  useEffect(() => {setDetailTab(requestedTab); setRequestedTab('request'); setDescriptionOpen(false); setCopyStatus('');}, [selected, endpoint]);
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
        if (source !== 'all') params.set('source', source);
        if (status) params.set('status', status);
        if (archived) params.set('archived', 'true');
        if (query) params.set('q', query);
        if (categoryFilter) params.set('category', categoryFilter);
        if (operatorFilter) params.set('operator', operatorFilter);
        if (deadlineFilter !== 'any') params.set('deadline', deadlineFilter);
        const result = await api<Page>(`${endpoint}?${params}`, 'GET', undefined, controller.signal);
        if (controller.signal.aborted) return;
        const lastPage = Math.max(1, Math.ceil(result.total / result.page_size));
        if (page > lastPage) setPage(lastPage);
        else {setData(result); if (result.filter_options) setFilterOptions(result.filter_options);}
      } catch (error) {if (!controller.signal.aborted && initial) setError((error as Error).message);}
      finally {refreshing = false;}
    }
    void refresh(true);
    const changed = () => {void refresh();}, timer = window.setInterval(changed, 10_000);
    for (const event of ['focus', 'online', 'appeal-discussion-changed']) window.addEventListener(event, changed);
    return () => {controller.abort(); window.clearInterval(timer); for (const event of ['focus', 'online', 'appeal-discussion-changed']) window.removeEventListener(event, changed);};
  }, [page, status, archived, query, revision, endpoint, refreshKey, categoryFilter, operatorFilter, deadlineFilter, source]);
  useEffect(() => {setPage(1); setSearch(''); setQuery(''); setCategoryFilter(''); setOperatorFilter(''); setDeadlineFilter('any'); setFilterOptions(null); setShowStatistics(false); setSource('all');}, [endpoint]);
  useEffect(() => {
    const refresh = () => {setRevision(value => value + 1);};
    window.addEventListener('refresh-appeals', refresh);
    return () => window.removeEventListener('refresh-appeals', refresh);
  }, []);
  useEffect(() => {
    if (selected === null) {setDetail(null); return;}
    const controller = new AbortController(); setError(''); setDetail(current => current?.id === selected ? current : null); setWorkTypes(null); setWorkTypesError('');
    api<Detail>(endpoint + '/' + selected, 'GET', undefined, controller.signal).then(item => {
      if (controller.signal.aborted) return;
      setDetail(item); setNextStatus(item.status); setNote(item.owner_note); setWorkType(item.category);
      if (!readOnly && item.can_manage !== false && !item.can_execute && !item.archived_at && item.organization_id) {
        void api<WorkType[]>(endpoint + '/' + selected + '/work-types', 'GET', undefined, controller.signal)
          .then(value => {if (!controller.signal.aborted) setWorkTypes(value);})
          .catch(error => {if (!controller.signal.aborted) setWorkTypesError(error.message);});
      }
    }).catch(error => {if (error.name !== 'AbortError') setError(error.message);});
    const timer = readOnly ? window.setInterval(async () => {
      if (document.hidden) return;
      try {
        const item = await api<Detail>(endpoint + '/' + selected, 'GET', undefined, controller.signal);
        if (!controller.signal.aborted) setDetail(current => !current || current.version !== item.version ? item : current);
      } catch { /* Keep the current card when a background refresh fails. */ }
    }, 10_000) : undefined;
    return () => {controller.abort(); window.clearInterval(timer);};
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
  async function archiveCancelledTask() {
    if (!detail || busy) return;
    setBusy(true);
    setError('');
    try {
      await api(endpoint + '/' + detail.id + '/archive', 'POST', {
        archived: !detail.archived_at,
        expected_version: detail.version,
      });
      closeTask();
      setRevision(value => value + 1);
      window.dispatchEvent(new Event('appeals-changed'));
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
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
  const filterCount = [status, categoryFilter, operatorFilter, deadlineFilter !== 'any', source !== 'all'].filter(Boolean).length;
  const canCreateTask = organization && !readOnly && data?.can_manage === true;
  const manageTask = !!detail && !readOnly && detail.can_manage !== false && !detail.can_execute;
  const canDiscussWithInspector = !!detail?.submitted_by_inspector_name && !detail.can_execute && (readOnly || manageTask);
  const showWork = !readOnly || canDiscussWithInspector;
  const inspectionTask = readOnly && !!detail?.submitted_by_inspector_name;
  const inspectorChatTitle = readOnly ? 'Чат с администраторами' : 'Чат с проверяющим';
  function openTask(id: number, tab: typeof detailTab = 'request') {
    if (id === selected) {setDetailTab(tab); return;}
    if (selected === null) listPosition.current = {id, scrollY: window.scrollY};
    const next = new URLSearchParams(params);
    next.set('appeal', String(id));
    setRequestedTab(tab);
    setParams(next, {replace: selected !== null, state: {appealFromList: selected === null || !!location.state?.appealFromList}});
  }
  function closeTask() {
    if (location.state?.appealFromList) {navigate(-1); return;}
    const next = new URLSearchParams(params);
    next.delete('appeal');
    setParams(next, {replace: true});
  }
  useLayoutEffect(() => {
    if (selected === null && data && listPosition.current) {
      const position = listPosition.current;
      listPosition.current = null;
      focusedCard.current = null;
      if (window.scrollY !== position.scrollY) window.scrollTo({top: position.scrollY, behavior: 'instant'});
      document.getElementById('appeal-row-' + position.id)?.focus({preventScroll: true});
    } else if (selected !== null && detail?.id === selected && focusedCard.current !== selected) {
      focusedCard.current = selected;
      if (window.scrollY) window.scrollTo({top: 0, behavior: 'instant'});
      detailHeading.current?.focus({preventScroll: true});
    }
  }, [selected, detail?.id, data]);
  async function copyTaskLink() {
    try {await navigator.clipboard.writeText(window.location.href); setCopyStatus('Ссылка скопирована');}
    catch {setCopyStatus('Скопируйте ссылку из адресной строки');}
  }
  return <section className={`owner-appeals${readOnly ? ' inspector-task-view' : ''}`}>
    {selected === null && <header className="page-header"><h1>{showStatistics ? 'Статистика обращений' : 'Обращения'}</h1>
      <div className="appeal-header-actions">
      {!showStatistics && data?.public_url && <button type="button" aria-expanded={sharingOpen} aria-controls="appeal-public-sharing"
        onClick={() => setSharingOpen(open => !open)}><Users size={16}/>Страница для жителей</button>}
      {onCreate && <button className="primary" onClick={onCreate}><Plus size={17}/>Создать задачу</button>}
      {canCreateTask && !creatingTask && <button className="primary" onClick={() => setCreatingTask(true)}><Plus size={17}/>Назначить задачу</button>}
      </div>
    </header>}
    {creatingTask && selected === null && <AdminTaskForm endpoint={endpoint + '/internal-tasks'}
      onClose={() => setCreatingTask(false)} onCreated={id => {
        setCreatingTask(false);
        openTask(id);
        setRevision(value => value + 1);
        window.dispatchEvent(new Event('appeals-changed'));
      }}/>}
    {composer}
    {error && <p className="error" role="alert">{error}</p>}
    {selected !== null ? <>
      <header className="appeal-detail-header">
        <button className="owner-appeal-back" disabled={busy} onClick={() => closeTask()}><ArrowLeft size={16}/>{readOnly ? 'К списку' : 'Все обращения'}</button>
        {detail?.id === selected && <><h1 ref={detailHeading} tabIndex={-1}><span>{detail.number}</span>{appealTitle(detail)}</h1><button type="button" className="appeal-copy-link" aria-label="Скопировать ссылку на обращение" title="Скопировать ссылку" onClick={() => void copyTaskLink()}><Copy size={16}/></button><AppealBadges status={detail.status} messages={data?.items.find(item => item.id === detail.id)?.unanswered_comments ?? detail.unanswered_comments}/>
          {detail.cancelled_by_inspector && !isFinalAppeal(detail) && detail.can_manage && !readOnly &&
            <button disabled={busy} onClick={() => void archiveCancelledTask()}>{detail.archived_at ? 'Вернуть из архива' : 'Перенести в архив'}</button>}</>}
      </header>
      {copyStatus && <p className="hint appeal-copy-status" role="status">{copyStatus}</p>}
      {!detail || detail.id !== selected ? !error && <p className="loading">Открываем обращение…</p> : <>
        <div className="appeal-detail-tabs" role="tablist" aria-label="Разделы обращения" onKeyDown={event => {
          if (showWork && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
            event.preventDefault(); const tabs: ('request' | 'inspector' | 'executor')[] = ['request', ...(canDiscussWithInspector ? ['inspector' as const] : []), ...(!readOnly ? ['executor' as const] : [])];
            const next = tabs[(tabs.indexOf(detailTab) + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]; setDetailTab(next);
            document.getElementById('appeal-tab-' + next)?.focus();
          }
        }}>
          <button id="appeal-tab-request" role="tab" aria-selected={detailTab === 'request'} aria-controls="appeal-panel-request" tabIndex={detailTab === 'request' ? 0 : -1} onClick={() => setDetailTab('request')}>{inspectionTask ? 'О задаче' : 'Заявка'}</button>
          {canDiscussWithInspector && <button id="appeal-tab-inspector" role="tab" aria-selected={detailTab === 'inspector'} aria-controls="appeal-panel-work" tabIndex={detailTab === 'inspector' ? 0 : -1} onClick={() => setDetailTab('inspector')}>{readOnly ? inspectorChatTitle : 'Работа с проверяющим'}{unread.inspector > 0 && <span className="appeal-tab-count" aria-label={'Сообщений без ответа: ' + unread.inspector}>{unread.inspector}</span>}</button>}
          {!readOnly && <button id="appeal-tab-executor" role="tab" aria-selected={detailTab === 'executor'} aria-controls="appeal-panel-work" tabIndex={detailTab === 'executor' ? 0 : -1} onClick={() => setDetailTab('executor')}>{detail.can_execute ? 'Выполнение задачи' : 'Работа с исполнителем'}{unread.executor > 0 && <span className="appeal-tab-count" aria-label={'Сообщений без ответа: ' + unread.executor}>{unread.executor}</span>}</button>}

        </div>
        <div id="appeal-panel-request" role="tabpanel" aria-labelledby="appeal-tab-request" hidden={showWork && detailTab !== 'request'} className="owner-appeal-detail appeal-request-layout">
          <div className="appeal-request-copy">
            <section className="panel appeal-description-panel"><h3>{detail.source === 'admin' || inspectionTask ? 'Описание задачи' : detail.submitted_by_inspector_name ? 'Описание проверяющего' : 'Описание жителя'}</h3>
              <p className="appeal-source-label">{sourceLabel(detail)}</p>
              <p className={'owner-appeal-text appeal-description' + (descriptionOpen ? ' is-expanded' : '')}>{detail.description}</p>
              {detail.description.length > 450 && <button className="appeal-description-toggle" aria-expanded={descriptionOpen} onClick={() => setDescriptionOpen(value => !value)}>{descriptionOpen ? 'Свернуть текст' : 'Показать весь текст'}<ChevronDown size={15}/></button>}
              <dl className="appeal-request-facts">
                <div><dt><MapPin size={18}/>Адрес:</dt><dd>{[detail.city, detail.address === 'Без территории' ? '' : detail.address].filter(Boolean).join(', ') || '—'}{detail.place && <small>{detail.place}</small>}</dd></div>
                <div><dt><Building2 size={17}/>{inspectionTask ? 'Кому передано' : 'Организация'}</dt><dd>{inspectionTask ? recipient(detail) : detail.organization_name || detail.organization_hint || 'Не назначена'}{inspectionTask && !!administrators.length && <small>{administrators.join(', ')}</small>}</dd></div>

                {inspectionTask && detail.inspector_due_date && <div><dt><CalendarDays size={17}/>Срок задачи</dt><dd>{deadlineLabel(detail.inspector_due_date)}</dd></div>}
                {detail.source !== 'admin' && !detail.submitted_by_inspector_name && !readOnly && detail.can_manage !== false && !detail.can_execute && <div><dt><UserRound size={18}/>Контакт:</dt><dd>{detail.contact || 'Не оставлен'}</dd></div>}
                <div><dt><CalendarDays size={18}/>Получено:</dt><dd>{moment(detail.created_at)}{detail.archived_at && <small>В архиве</small>}</dd></div>
              </dl>
            </section>
            {detail.public_response && hasAppealDecision(detail) && <section className="panel"><h3>Итоговый ответ администратора</h3><p className="owner-appeal-text">{detail.public_response}</p><div className="appeal-evidence">{detail.response_photos?.map(photo => <a key={photo.id} href={photo.url} target="_blank" rel="noreferrer"><img src={photo.preview_url} alt="Результат рассмотрения"/></a>)}</div></section>}
            {!!detail.files?.length && <section className="panel"><h3>Документы задачи</h3>{detail.files.map(file => <p key={file.id}><a href={file.url}>{file.name}</a></p>)}</section>}
            {(detail.parent || !!detail.children?.length) && <section className="panel"><h3>Связанные задачи</h3>{detail.parent && <button onClick={() => openTask(detail.parent!.id)}>Родительская задача {detail.parent.number}</button>}{detail.children?.map(child => <div className="appeal-task" key={child.id}><button onClick={() => openTask(child.id)}>{child.number} · {child.subject}</button><p>{appealStatuses[child.status]}{!readOnly && ' · ' + (child.operator_name || 'Без исполнителя')}{child.due_date ? ' · до ' + new Date(child.due_date + 'T00:00:00').toLocaleDateString('ru-RU') : ''}</p>{(child.result || child.operator_result) && <p className="owner-appeal-text">{child.result || child.operator_result}</p>}</div>)}</section>}
            {processingForm}
          </div>
          <div className="owner-appeal-photos">
            {detail.photos.length ? detail.photos.map((photo, index) => <section className="panel appeal-resident-photo" key={photo.id}>
              <header><h3>{detail.source === 'admin' ? 'Вложение к задаче' : detail.submitted_by_inspector_name ? 'Фотография от проверяющего' : 'Фотография от жителя'}{detail.photos.length > 1 && <span> · {index + 1} из {detail.photos.length}</span>}</h3></header>
              <div className="appeal-resident-photo-image"><a href={photo.url} target="_blank" rel="noreferrer"><img src={photo.url} alt={`Фотография обращения ${detail.number}, снимок ${index + 1}`}/></a>
                <a className="button" href={photo.original_url || photo.url} target="_blank" rel="noreferrer"><Maximize2 size={15}/>Открыть фотографию</a></div>
            </section>) : null}
            {detail.longitude != null && detail.latitude != null && <AppealLocation longitude={detail.longitude}
              latitude={detail.latitude} apiKey={data?.yandex_maps_api_key || ''}/>}
          </div>
        </div>
        {showWork && <div id="appeal-panel-work" role="tabpanel" aria-labelledby={'appeal-tab-' + (detailTab === 'inspector' ? 'inspector' : 'executor')} hidden={detailTab === 'request'}>
          <AppealActions key={detail.id} appeal={detail} workspace={detailTab === 'executor' ? 'executor' : 'inspector'} endpoint={endpoint} readOnly={readOnly} openTask={openTask} changed={() => setRevision(value => value + 1)}
            inspectorDiscussion={canDiscussWithInspector ? <AppealDiscussion key={detail.id + ':inspector'} endpoint={endpoint + '/' + detail.id} channel="inspector" forwardToContacts={organization && manageTask} visibleTab={detailTab === 'inspector'} onUnreadChange={count => setUnread(current => current.inspector === count ? current : {...current, inspector:count})} title={inspectorChatTitle} openTask={id => openTask(id, detailTab)} archived={!!detail.archived_at}/> : undefined}
            discussion={!readOnly && detail.children?.length ? <section className="panel"><h3>Переписка по подзадачам</h3><p className="hint">Откройте нужную подзадачу слева. У каждого исполнителя своя переписка, срок и результат.</p></section> : !readOnly ? <AppealDiscussion key={detail.id + ':executor'} endpoint={endpoint + '/' + detail.id} channel="executor" forwardToContacts={organization && manageTask} visibleTab={detailTab === 'executor'} onUnreadChange={count => setUnread(current => current.executor === count ? current : {...current, executor:count})} title={detail.can_execute ? 'Чат с администратором' : 'Чат с исполнителем'} openTask={id => openTask(id, detailTab)} readonlyReason={!detail.task ? 'Переписка откроется после назначения исполнителя. Для подзадач откройте нужную карточку.' : undefined} archived={!!detail.archived_at || (!!detail.submitted_by_inspector_name && !detail.task)}/> : undefined}/>
        </div>}
      </>}
    </> : <>
      {!showStatistics && data && data.public_url && <div id="appeal-public-sharing" hidden={!sharingOpen}><section className="panel owner-appeal-public">
        <Users className="appeal-public-icon" size={36}/><div className="appeal-public-copy"><h2>Страница для жителей</h2><p>Откройте форму подачи обращений для жителей. Скопируйте ссылку или поделитесь в социальных сетях.</p></div>
        <div className="owner-signal-share"><a className="button primary" href={data.public_url} target="_blank" rel="noreferrer"><ArrowUpRight size={17}/>Открыть форму</a><SignalShare url={data.public_url}/></div>
      </section></div>}
      <div className="appeal-folder-tabs" role="tablist" aria-label="Раздел обращений">{[false, true].map(value => <button key={String(value)} role="tab" aria-selected={!showStatistics && archived === value} onClick={() => {setShowStatistics(false); setArchived(value); setPage(1); setStatus('');}}>{value ? 'Архив' : 'Рабочий список'}{data && archived === value && <span className="appeal-folder-count">{data.total}</span>}</button>)}<button role="tab" aria-selected={showStatistics} onClick={() => setShowStatistics(true)}>Статистика</button></div>
      {showStatistics ? <AppealStatistics key={endpoint} endpoint={endpoint} includeAdmin={!readOnly} showAssignments={!readOnly} source={source} onSourceChange={setSource}/> : <>
      <div className="owner-appeal-toolbar">
        <form className="owner-appeal-search" role="search" onSubmit={event => {event.preventDefault(); setQuery(search.trim()); setPage(1);}}>
          <Search size={20} aria-hidden="true"/><input type="search" aria-label="Поиск обращений" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} placeholder="Поиск по тексту, номеру или дате"/>
          {search && <button type="button" aria-label="Очистить поиск" onClick={() => {setSearch(''); setQuery(''); setPage(1);}}><X size={18}/></button>}
        </form>
        <div className="appeal-list-tools">
          <button type="button" aria-expanded={filtersOpen} aria-controls="appeal-list-filters"
            onClick={() => setFiltersOpen(open => !open)}><SlidersHorizontal size={16}/>Фильтры{filterCount > 0 && <span className="appeal-folder-count">{filterCount}</span>}</button>
        <button className="appeal-list-refresh" type="button" aria-label="Сбросить фильтры" title="Сбросить фильтры" disabled={!filterCount && !search} onClick={() => {setStatus(''); setCategoryFilter(''); setOperatorFilter(''); setDeadlineFilter('any'); setSource('all'); setSearch(''); setQuery(''); setPage(1);}}><FilterX size={17} aria-hidden="true"/></button>
          <button className="appeal-list-refresh" type="button" disabled={busy} aria-label="Обновить обращения" title="Обновить обращения" onClick={() => setRevision(value => value + 1)}><RefreshCw size={17} aria-hidden="true"/></button>
          <span className="appeal-total hint">{data ? appealCount(data.total) : 'Загружаем…'}</span>
        </div>
      </div>
      <div id="appeal-list-filters" hidden={!filtersOpen}>
      <div className="appeal-list-filters">
        <AppealSourceFilter includeAdmin={!readOnly} value={source} onChange={value => {setSource(value); setPage(1);}}/>
        <label>Состояние<select name="status" value={status} onChange={event => {setStatus(event.target.value); setPage(1);}}><option value="">Все обращения</option>{Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>Вид работ<select value={categoryFilter} onChange={event => {setCategoryFilter(event.target.value); setPage(1);}}><option value="">Все виды</option>{filterOptions?.work_types.map(w => <option key={w.code} value={w.code}>{w.name}</option>)}</select></label>
        {!readOnly && <label>Исполнитель<select value={operatorFilter} onChange={event => {setOperatorFilter(event.target.value); setPage(1);}}><option value="">Все исполнители</option>{filterOptions?.operators.map(o => <option key={o.value} value={o.value}>{o.name}</option>)}</select></label>}
        {!readOnly && <label>Срок исполнения<select value={deadlineFilter} onChange={event => {setDeadlineFilter(event.target.value); setPage(1);}}><option value="any">Любой срок</option><option value="none">Не установлен</option><option value="overdue">Просрочено</option><option value="today">Сегодня</option><option value="week">Ближайшие 7 дней</option></select></label>}
      </div>
      </div>
      <div className="appeal-list-columns" aria-hidden="true"><span>Обращение</span><span>Вид работ</span><span>{readOnly ? 'Срок задачи' : 'Срок исполнения'}</span><span>{readOnly ? 'Кому передано' : 'Исполнитель'}</span><span>Состояние</span><span/></div>
      {!data ? !error && <p className="loading">Загружаем обращения…</p> : !data.items.length ? <div className="panel empty"><Inbox size={32}/><h3>{query ? 'Ничего не найдено' : 'Обращений пока нет'}</h3><p>{query ? 'Попробуйте другие слова, адрес, номер или дату.' : 'Новые анкеты жителей появятся здесь.'}</p></div> : <div className="owner-appeal-list">{data.items.map(item => <button className="panel owner-appeal-card owner-appeal-card-open" key={item.id} id={'appeal-row-' + item.id} onClick={() => openTask(item.id)}>
        <span className="appeal-list-main">
        <span className="appeal-list-photo">{item.preview_url ? <img src={item.preview_url} alt="" loading="lazy"/> : <Camera size={26}/>}</span>
        <span className="appeal-list-copy"><span className="owner-appeal-card-top"><strong>{item.number}</strong><span className="appeal-list-title">{appealTitle(item)}</span></span>
          <span className="appeal-list-meta"><span><MapPin size={17}/>{item.address}</span><span><CalendarDays size={17}/>{moment(item.created_at)}</span>{!readOnly && <span><Building2 size={17}/>{item.organization_name || 'Без назначенной организации'}</span>}</span>
          <span className="owner-appeal-source appeal-source-label">{(item.submitted_by_inspector_name || item.source === 'admin') && <LockKeyhole size={13}/>}{sourceLabel(item)}</span>
          {item.parent_id && <span className="owner-appeal-source">Подзадача ОБ-{String(item.parent_id).padStart(6, '0')}</span>}
          {!!item.child_count && <span className="owner-appeal-source">Подзадач: {item.child_count}</span>}
          <span className="owner-appeal-excerpt">{item.description}</span>
        </span>
        </span>
        <span className="appeal-list-field"><small>Вид работ</small>{item.work_type_name || 'Не указан'}</span>
        <span className={'appeal-list-field' + (item.overdue ? ' appeal-overdue' : '')}><small>{readOnly ? 'Срок задачи' : 'Срок исполнения'}</small>
          <span>{deadlineLabel(readOnly ? item.inspector_due_date || item.due_date : item.due_date)}</span>
          {!readOnly && item.inspector_due_date && <small>Срок от проверяющего: {deadlineLabel(item.inspector_due_date)}</small>}{item.overdue && <b>Просрочено</b>}</span>
        <span className="appeal-list-field"><small>{readOnly ? 'Кому передано' : 'Исполнитель'}</small>
          <span>{readOnly ? (item.submitted_by_inspector_name ? recipient(item) : item.organization_name || '—') : item.operator_name || 'Не назначен'}</span>
</span>
        <AppealBadges status={item.status} messages={item.unanswered_comments}/><ChevronRight className="appeal-card-chevron" size={22}/>
      </button>)}</div>}
      {data && data.total > data.page_size && <div className="owner-appeal-pagination"><button aria-label="Предыдущая страница обращений" disabled={page <= 1} onClick={() => setPage(value => value - 1)}><ChevronLeft size={17}/></button>
        <span>{page} / {Math.ceil(data.total / data.page_size)}</span><button aria-label="Следующая страница обращений" disabled={page * data.page_size >= data.total} onClick={() => setPage(value => value + 1)}><ChevronRight size={17}/></button></div>}
      </>}
    </>}
  </section>;
}

function recipient(appeal: Appeal) {
  const organization = appeal.organization_name || appeal.organization_hint;
  return organization ? `Администраторы «${organization}»` : 'Администраторы организации';
}
function deadlineLabel(value?: string | null) {
  return value ? new Date(value + 'T00:00:00').toLocaleDateString('ru-RU') : '—';
}

function sourceLabel(appeal: Appeal) {
  if (appeal.source === 'admin') return 'От администратора · внутренняя задача';
  if (appeal.submitted_by_inspector_name) return 'От проверяющего · ' + appeal.submitted_by_inspector_name;
  return 'Из Сигнала · обращение жителя';
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
