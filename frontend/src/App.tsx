import { ResponsePhotoDraftProvider, useResponsePhotoDraft } from './appeals/ResponsePhotoDraft';
import { usePresenceHeartbeat } from './UserPresence';
import { MAX_PHOTOS } from './appeals/TaskImageInput';
import PhotoContextMenu, { type PhotoMenuTarget } from './PhotoContextMenu';
import ForwardPhotos from './inspection/Forward';
import TaskPhotoSend, { sendTaskPhotos } from './appeals/TaskPhotoSend';
import { createContext, lazy, Suspense, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowDownToLine, ArchiveX, Camera, ChartNoAxesCombined, CheckCheck, ChevronLeft, ChevronRight, CircleCheck, ClipboardCheck, Layers, LogOut, Map, MapPin, MessageSquare, Newspaper, RefreshCw, ShieldCheck, Users } from 'lucide-react';
import { api, dateLabel, photoLink, query, reportPhotoLink, shiftDate, statusNames } from './api';
import type { Filters, Meta, PhotoPage, Report, User } from './types';
import PhotoDetail from './PhotoDetail';
import DistrictMap from './DistrictMap';
import PhotoMap from './PhotoMap';
import Administration from './Administration';
import Learning from './Learning';
import Exchange from './Exchange';
import Settings from './Settings';
import IntegrationKeys from './IntegrationKeys';
import WorkTypes from './WorkTypes';
import News from './News';
import Avatar from './Avatar';
import OperatorChats from './OperatorChats';
import { OperatorChatBadge, OperatorChatsProvider } from './OperatorChatsProvider';
import { NewsNotificationsProvider, NewsUnreadBadge } from './NewsNotificationsProvider';
import { hasPermission } from './permissions';
import { PhotoNotificationsProvider } from './PhotoNotifications';
import FilterBar from './FilterBar';
import { photoSortForUser } from './photoSorting';
import { capturePhotoListPosition, photoListAnchor, photoListPage, restorePhotoListPosition } from './photoNavigation';
import type { PhotoListPosition } from './photoNavigation';
import { canEditPhoto, updatePhotoDefect } from './photoWork';
import type { Photo } from './types';
import PhotoTable from './PhotoTable';
import PhotoNumberSearch from './PhotoNumberSearch';
import './photo-owner.css';
import useSidebar from './useSidebar';
import MobileNavigation from './MobileNavigation';
import { defaultSidebarOrder } from './sidebarOrder';
import SidebarNavigation from './SidebarNavigation';
import DayReviews from './DayReviews';
import ClosedDayUpdates from './ClosedDayUpdates';
import OperatorDayStatus from './OperatorDayStatus';
import WorkDistrictMatrix from './WorkDistrictMatrix';
import { dayReviewDate } from './dayReviewData';
import './organizations.css';
import { workspacePrefix } from './workspace';
import Login, { SignInRedirect } from './Login';
import { AppealNotice, useAppealNotifications } from './appeals/notifications';
const PhotoRoutes = lazy(() => import('./photo-routes/PhotoRoutes'));
const OwnerAppeals = lazy(() => import('./appeals/OwnerAppeals'));
const DailyReports = lazy(() => import('./daily-reports/DailyReports'));

const dailyLinks = ['/', '/appeals', '/messages', '/photos', '/review', '/days', '/daily-reports'];
const workspaceMenuOrder = [...dailyLinks, ...defaultSidebarOrder.filter(path => !dailyLinks.includes(path))];
const managementLinks = new Set(['/chats', '/work-types', '/users', '/audit', '/jobs', '/exchange', '/api-keys', '/learning']);

const Context = createContext<{ user: User; meta: Meta; refresh: () => Promise<void>; notify: (text: string) => void; updateUser: (user: User) => void }>(null!);
export const AppContextProvider = Context.Provider;
export const useApp = () => useContext(Context);
export const ErrorBox = ({ error }: { error: string }) => error ? <div className="error" role="alert">{error}</div> : null;
export const Empty = ({ children }: { children: ReactNode }) => <div className="empty"><Camera size={34}/><h3>Пока ничего нет</h3><p>{children}</p></div>;
export function StatusBadge({ value }: { value: string }) { return <span className={'badge status-' + value}>{statusNames[value] || value}</span>; }


export default function App() {
  const sidebar = useSidebar();
  const [user,setUser] = useState<User|null>(null), [meta,setMeta] = useState<Meta|null>(null), [loading,setLoading] = useState(true), [error,setError] = useState(''), [toast,setToast] = useState('');
  usePresenceHeartbeat(!!user);
  const appeals = useAppealNotifications(!!user && !!meta?.organization, user?.id);
  const navigate = useNavigate();
  const {pathname} = useLocation();
  async function refresh() { setMeta(await api<Meta>('/meta')); }
  useEffect(()=>{api<User>('/auth/me').then(setUser).catch(e=>{if(e.status!==401)setError(e.message);}).finally(()=>setLoading(false)); const handler=()=>{setUser(null);setMeta(null);}; window.addEventListener('session-expired',handler);return()=>window.removeEventListener('session-expired',handler);},[]);
  useEffect(()=>{if(user)refresh().catch(e=>setError(e.message));},[user]);
  useEffect(()=>{if(toast){const t=setTimeout(()=>setToast(''),5000);return()=>clearTimeout(t);}},[toast]);
  if(loading)return <div className="full-loading">Открываем рабочее пространство…</div>;
  if(!user&&workspacePrefix())return <SignInRedirect/>;
  if(!user)return <Login initialError={error} onLogin={u=>{setUser(u);setError('');}}/>;
  if(!meta)return <div className="full-loading"><ErrorBox error={error}/>{error?<button onClick={()=>refresh().then(()=>setError('')).catch(e=>setError(e.message))}>Повторить</button>:'Загружаем справочники…'}</div>;
  const admin=user.role==='ADMIN_OPERATOR';
  const links = [
    {to:'/', label:'Обзор', Icon:ChartNoAxesCombined, allowed:hasPermission(user,'reports_view')},
    {to:'/news', label:'Новости', Icon:Newspaper, allowed:hasPermission(user,'news_view')},
    {to:'/photos', label:'Фотографии', Icon:Camera, allowed:hasPermission(user,'photos_view')},
    {to:'/photo-map', label:'Карта фотографий', Icon:MapPin, allowed:hasPermission(user,'photos_view')},
    {to:'/photo-routes', label:'Маршруты по фото', Icon:Map, allowed:hasPermission(user,'photos_view')},
    {to:'/review', label:'Требуют проверки', Icon:ClipboardCheck, allowed:hasPermission(user,'photos_edit')},
    {to:'/days', label:'Проверка дней', Icon:CheckCheck, allowed:hasPermission(user,'days_review')},
    {to:'/daily-reports', label:'Ежедневные отчёты', Icon:ClipboardCheck, allowed:hasPermission(user,'daily_reports_view')},
    {to:'/spam', label:'Спам', Icon:ArchiveX, allowed:hasPermission(user,'spam_view')},
    {to:'/districts', label:'Микрорайоны', Icon:Map, allowed:hasPermission(user,'districts_view')},
    {to:'/appeals', label:admin ? 'Обращения' : 'Мои задачи', Icon:MessageSquare, allowed:!!meta.organization},
    {to:'/messages', label:'Чаты', Icon:MessageSquare, allowed:true},
    {to:'/chats', label:'Чаты MAX', Icon:MessageSquare, allowed:hasPermission(user,'chats_manage')},
    {to:'/work-types', label:'Виды работ', Icon:Layers, allowed:admin},
    {to:'/users', label:'Сотрудники', Icon:Users, allowed:admin},
    {to:'/audit', label:'Журнал действий', Icon:ShieldCheck, allowed:hasPermission(user,'audit_view')},
    {to:'/jobs', label:'Обработка', Icon:RefreshCw, allowed:hasPermission(user,'jobs_manage')},
    {to:'/exchange', label:'Фотоархив', Icon:ArrowDownToLine, allowed:hasPermission(user,'exchange_manage')},
    {to:'/api-keys', label:'API-ключи', Icon:ShieldCheck, allowed:admin && !!meta.organization},
    {to:'/learning', label:'Обучение нейросети', Icon:Layers, allowed:hasPermission(user,'learning_manage')},
  ].filter(link => link.allowed);
  const home = links.find(link => link.to !== '/news')?.to || '/news';
  const denied = <Navigate to={home} replace/>;
  const protectedPage = (code:string, element:ReactNode) => hasPermission(user,code) ? element : denied;
  return <Context.Provider value={{user,meta,refresh,notify:setToast,updateUser:setUser}}>
    <NewsNotificationsProvider key={user.id} enabled={hasPermission(user,'news_view')}>
    <OperatorChatsProvider key={user.id} additionalEndpoint={admin && meta.organization ? '/inspection-admin/unread' : undefined} ownerEndpoint={meta.organization ? '/inspection-admin/owners/unread' : undefined}>
    <PhotoNotificationsProvider key={user.id + ":" + meta.intake_cohort} userId={user.id} canViewPhotos={hasPermission(user,'photos_view')}>
    <ResponsePhotoDraftProvider key={user.id + '@' + meta.organization?.id}>
    <div className={'app ' + (sidebar.collapsed ? 'sidebar-collapsed' : 'sidebar-expanded')}>
      {!sidebar.collapsed&&<button type="button" className="sidebar-backdrop" aria-label="Закрыть боковую панель" onClick={sidebar.toggle}/>}
      <aside id="workspace-sidebar" ref={sidebar.sidebar} className="sidebar">
        <NavLink className="brand" onClick={sidebar.closeMenu} to={home} aria-label="Метка — главная"><span className="brand-mark"><Layers size={23}/></span><span className="brand-copy">Метка<small>Контроль городских работ</small></span></NavLink>
        <SidebarNavigation key={user.id} links={links.map(link=>({...link,group:managementLinks.has(link.to) ? 'management' : undefined,badge:link.to==='/messages'?<OperatorChatBadge/>:link.to==='/news'?<NewsUnreadBadge/>:link.to==='/appeals' && appeals.count ? <span className="count-pill appeal-count" aria-label={`Новых обращений: ${appeals.count}`}>{appeals.count}</span>:undefined}))}
          order={user.sidebar_order} resetOrder={workspaceMenuOrder} collapsed={sidebar.collapsed} toggle={sidebar.toggle} onNavigate={sidebar.closeMenu}
          onSaved={sidebar_order=>setUser(current=>current?.id===user.id?{...current,sidebar_order}:current)}/>
        <div className="sidebar-bottom">
          <NavLink to="/settings" onClick={sidebar.closeMenu} className="account-link" title="Настройки" aria-label="Настройки">
            <Avatar name={user.name} src={user.avatar_url}/>
            <span className="account-info"><strong>{user.name}</strong><small>{admin?'Администратор':'Оператор'}</small></span>
          </NavLink>
          <button title="Выйти" aria-label="Выйти" onClick={async()=>{try{await api('/auth/logout','POST');setUser(null);setMeta(null);navigate('/');}catch(e){setToast((e as Error).message);}}}><LogOut size={17}/></button>
        </div>
      </aside>
      <main className="workspace">
        <div className="topbar">
          <MobileNavigation button={sidebar.menuButton} open={sidebar.menuOpen} toggle={sidebar.toggle} updates={appeals.count > 0}/>
          <span className="workspace-identity"><span className="dot"/>{meta.organization?<><strong>{meta.organization.name}</strong>{user.is_platform_owner&&<a className="organization-switch" href="/">Все организации<ChevronRight size={13}/></a>}</>:<>Операторская панель</>}{meta.intake_cohort==='test'&&<span className="badge">Тестовый режим</span>}</span><span>{dateLabel(meta.today)} <span className="timezone">{meta.timezone}</span></span></div>
        <Routes>
          <Route path="/" element={protectedPage('reports_view',<Overview/>)}/>
          <Route path="/news" element={protectedPage('news_view',<News owner={!!user.is_platform_owner}/>)}/>
          <Route path="/news/:slug" element={protectedPage('news_view',<News owner={!!user.is_platform_owner}/>)}/>
          <Route path="/photos" element={protectedPage('photos_view',<PhotoList/>)}/>
          <Route path="/photo-map" element={protectedPage('photos_view',<PhotoMap/>)}/>
          <Route path="/photo-routes" element={protectedPage('photos_view',<Suspense fallback={<p>Открываем маршруты…</p>}><PhotoRoutes/></Suspense>)}/>
          <Route path="/review" element={protectedPage('photos_edit',<PhotoList review/>)}/>
          <Route path="/days" element={protectedPage('days_review',<DayReviews/>)}/>
          <Route path="/daily-reports" element={protectedPage('daily_reports_view',<Suspense fallback={<p className="loading">Открываем отчётность…</p>}><DailyReports/></Suspense>)}/>
          <Route path="/spam" element={protectedPage('spam_view',<PhotoList spam/>)}/>
          <Route path="/photos/:id" element={protectedPage('photos_view',<PhotoDetail/>)}/>
          <Route path="/districts" element={protectedPage('districts_view',<DistrictMap/>)}/>
          <Route path="/appeals" element={meta.organization ? <Suspense fallback={<p className="loading">Открываем обращения…</p>}><OwnerAppeals organization canAttachPhotos={hasPermission(user,'photos_view')}/></Suspense> : denied}/>
          <Route path="/inspectors" element={admin && meta.organization ? <LegacyInspectorLink/> : denied}/>
          <Route path="/messages" element={<OperatorChats includeInspectors={admin && !!meta.organization}/>}/>
          <Route path="/chats" element={protectedPage('chats_manage',<Administration key="chats" page="chats"/>)}/>
          <Route path="/work-types" element={admin?<WorkTypes/>:denied}/>
          <Route path="/users" element={admin?<Administration key="users" page="users"/>:denied}/>
          <Route path="/audit" element={protectedPage('audit_view',<Administration key="audit" page="audit"/>)}/>
          <Route path="/jobs" element={protectedPage('jobs_manage',<Administration key="jobs" page="jobs"/>)}/>
          <Route path="/learning" element={protectedPage('learning_manage',<Learning/>)}/>
          <Route path="/exchange" element={protectedPage('exchange_manage',<Exchange/>)}/>
          <Route path="/api-keys" element={admin && meta.organization ? <IntegrationKeys/> : denied}/>
          <Route path="/settings" element={<Navigate to="/settings/profile" replace/>}/>
          <Route path="/settings/:section" element={<Settings/>}/>
          <Route path="/account" element={<Navigate to="/settings" replace/>}/>
          <Route path="*" element={denied}/>
        </Routes>
      </main>
    </div>
    {pathname !== '/messages' && pathname !== '/appeals' && <AppealNotice count={appeals.notice} dismiss={appeals.dismiss}/>}
    {toast&&<div className="toast" role="status"><CircleCheck size={20}/>{toast}<button onClick={()=>setToast('')}>×</button></div>}
    </ResponsePhotoDraftProvider>
    </PhotoNotificationsProvider>
    </OperatorChatsProvider>
    </NewsNotificationsProvider>
  </Context.Provider>;
}

function LegacyInspectorLink() {
  const [params] = useSearchParams();
  const peer = params.get('with');
  return <Navigate replace to={peer ? '/messages?' + new URLSearchParams({with: peer}) : '/users?invite=inspector'}/>;
}

export function useFilters(review=false,spam=false,today=false,workOnly=false) {
  const {meta,user}=useApp(); const [params,setParams]=useSearchParams();
  const defaultDate=today?meta.today:shiftDate(meta.today,-1);
  const filters:Filters={...(workOnly?{work_only:'true'}:{}),...(!review&&!spam&&!params.has('date_from')&&!params.has('date_to')&&!params.has('all_dates')?{date_from:defaultDate,date_to:defaultDate}:{}),...Object.fromEntries(params),...(review?{status:'NEEDS_REVIEW'}:spam?{status:'SPAM'}:{})};
  Object.assign(filters,photoSortForUser(filters,user));
  delete filters.all_dates; delete filters.review; delete filters.spam; delete filters.from_map;
  delete filters.page; delete filters.anchor_id; delete filters.attach_task; delete filters.task_channel; delete filters.attach_reply;
  const change=(values:Filters)=>{const updated={...filters,...values};if('date_from' in values||'date_to' in values)delete updated.review_day;if('day_review' in values)delete updated.day_ai_only;Object.assign(updated,photoSortForUser(updated,user)); if(!updated.date_from&&!updated.date_to)updated.all_dates='1';setParams(Object.fromEntries(Object.entries({...updated, attach_task: params.get('attach_task') || '', task_channel: params.get('task_channel') || '', attach_reply: params.get('attach_reply') || ''}).filter(([,v])=>v!=='')));};
  return {filters,change};
}


function Overview() {
  const {user,meta}=useApp(); const canBrowse=hasPermission(user,'photos_view');
  const {filters:selection,change}=useFilters();const filters={...selection,work_only:'true'};const [report,setReport]=useState<Report|null>(null),[error,setError]=useState(''),[revision,setRevision]=useState(0);const navigate=useNavigate();const key=query(filters);
  useEffect(()=>{const c=new AbortController();setError('');setReport(null);api<Report>('/reports?'+key,'GET',undefined,c.signal).then(setReport).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>c.abort();},[key,revision]);
  function drill(values:Filters) {if(!canBrowse)return;navigate(reportPhotoLink(filters,values));}
  const counts=report?.counts||{};
  return <><header className="page-header"><div><h1>Обзор работ</h1></div><button className="icon-button" aria-label="Обновить отчёт" onClick={()=>setRevision(x=>x+1)}><RefreshCw size={18}/></button></header><FilterBar filters={filters} change={change} refreshKey={revision}/><ErrorBox error={error}/>{!report&&!error?<p className="loading">Собираем отчёт…</p>:report&&<><ClosedDayUpdates updates={report.day_updates}/><div className="stat-grid">{[['Всего в отчёте',report.total,'',Camera],['Принято системой',report.accepted,'',CircleCheck],['Требуют проверки',counts.NEEDS_REVIEW,'NEEDS_REVIEW',ClipboardCheck],['Отклонено',counts.REJECTED,'REJECTED',ShieldCheck]].map(([label,n,status,Icon],i)=>{const I=Icon as typeof Camera;return <button className={'stat-card stat-'+i} key={label as string} disabled={!canBrowse||!Number(n)} onClick={()=>drill(i===0?{}:i===1?{accepted_only:'true'}:{status:status as string})}><div><span>{label as string}</span><I size={19}/></div><strong>{Number(n).toLocaleString('ru-RU')}</strong><small>{i===0?'Без дублей и пересланных':i===1?'Включая ручную проверку':i===2?'Ожидают решения оператора':'За выбранный период'}</small></button>;})}</div><div className="minor-stats">{[['Дубли','DUPLICATE'],['Пересланные','FORWARDED'],['Ошибки обработки','ERROR'],['В обработке','PROCESSING'],['Ожидают обработки','RECEIVED']].map(([label,code])=><button key={code} disabled={!canBrowse||!counts[code]} onClick={()=>drill({status:code})}>{label}<strong>{counts[code]||0}</strong></button>)}</div><OperatorDayStatus day={dayReviewDate(selection.review_day||selection.date_to||selection.date_from,shiftDate(meta.today,-1))} refreshKey={revision} dateEditable={!selection.date_from||selection.date_from!==selection.date_to}/><WorkDistrictMatrix report={report} meta={meta} filters={filters} canBrowse={canBrowse} open={drill}/>{report.total===0?<Empty>В этой выборке нет фотографий для отчёта. Дубли и пересланные фотографии доступны по отдельным счётчикам.</Empty>:<><div className="two-columns"><section className="panel"><div className="section-title"><h2>По микрорайонам</h2><span>{report.districts.length} территорий</span></div><div className="bar-list">{report.districts.map(d=><button key={d.id} disabled={!canBrowse} onClick={()=>drill({district_id:String(d.id)})}><div><span>{d.name}</span><strong>{d.count}</strong></div><div className="bar"><i style={{width:(d.count/Math.max(...report.districts.map(x=>x.count))*100)+'%'}}/></div></button>)}</div></section><section className="panel"><div className="section-title"><h2>По чатам</h2><MessageSquare size={18}/></div>{report.chats.map(c=><button className="list-row" key={c.id} disabled={!canBrowse} onClick={()=>drill({chat_id:String(c.id)})}><span className="chat-icon"><MessageSquare size={18}/></span><span>{c.name}</span><strong>{c.count}</strong><ChevronRight size={16}/></button>)}</section></div><section className="panel"><div className="section-title"><h2>Чат × микрорайон</h2>{canBrowse&&<span>Нажмите на число, чтобы открыть фотографии</span>}</div><div className="table-scroll"><table><thead><tr><th>Чат</th>{report.districts.map(d=><th key={d.id}>{d.name}</th>)}<th>Всего</th></tr></thead><tbody>{report.chats.map(c=><tr key={c.id}><td>{c.name}</td>{report.districts.map(d=><td key={d.id}><button className="number-link" disabled={!canBrowse} onClick={()=>drill({chat_id:String(c.id),district_id:String(d.id)})}>{report.matrix.find(m=>m.chat_id===c.id&&m.district_id===d.id)?.count||0}</button></td>)}<td><strong>{c.count}</strong></td></tr>)}</tbody></table></div></section><section className="panel"><div className="section-title"><h2>Виды выполненных работ</h2><span>Фотографий</span></div>{report.work_types.map(w=><button className="list-row" key={w.id} disabled={!canBrowse} onClick={()=>drill({work_type:String(w.id)})}><span>{w.name}</span><strong>{w.count}</strong><ChevronRight size={16}/></button>)}</section></>}<p className="footnote">Если дата снимка ещё не распознана, в отчёте используется дата получения. Часовой пояс задан в настройках сервиса. Дубли, пересланные фотографии и спам не включены в отчёты о работах. Дубли и пересланные доступны по отдельным счётчикам.</p></>}</>;
}

export function PhotoList({review=false,spam=false}:{review?:boolean;spam?:boolean}) {
  const {user,notify,meta}=useApp();
  const {filters,change}=useFilters(review,spam,false,true);
  const [params,setParams]=useSearchParams();
  const location=useLocation();const navigate=useNavigate();
  type SelectedPhoto = Pick<Photo, 'id' | 'preview_url'>;
  const listState=location.state as {photoListPosition?:PhotoListPosition; selectedPhotos?:SelectedPhoto[]}|null;
  const position=listState?.photoListPosition;
  const requestedPage=photoListPage(params.get('page'));
  const anchorId=photoListAnchor(params.get('anchor_id'),position);
  const [data,setData]=useState<PhotoPage|null>(null),[error,setError]=useState(''),[revision,setRevision]=useState(0);
  const key=query({...filters,page:String(requestedPage),...(anchorId?{anchor_id:String(anchorId)}:{})});
  const loadedKey=useRef(''),restoredLocation=useRef('');
  const preserveRows=useRef(false);
  const [defectBusy,setDefectBusy]=useState<number|null>(null);
  const page=data?.page??requestedPage;
  useEffect(()=>{const refresh=()=>setRevision(value=>value+1);window.addEventListener('refresh-photo-list',refresh);return()=>window.removeEventListener('refresh-photo-list',refresh);},[]);
  useEffect(()=>{
    const c=new AbortController();if(!preserveRows.current)setData(null);preserveRows.current=false;setError('');
    api<PhotoPage>('/photos?'+key,'GET',undefined,c.signal).then(value=>{
      if(!c.signal.aborted){loadedKey.current=key;setData(value);}
    }).catch(e=>{if(e.name!=='AbortError')setError(e.message);});
    return()=>c.abort();
  },[key,revision]);
  useLayoutEffect(()=>{
    if(!data||loadedKey.current!==key||restoredLocation.current===location.key)return;
    restoredLocation.current=location.key;
    restorePhotoListPosition(data.focus_id??anchorId,position);
  },[data,key,location.key,anchorId,position]);
  function setPage(value:number){
    const updated=new URLSearchParams(params);updated.set('page',String(value));updated.delete('anchor_id');
    setParams(updated);
  }
  function openPhoto(id:number){
    const state={photoListPosition:capturePhotoListPosition(id), selectedPhotos:selected};
    // Save the position in the list's own history entry as well, for browser Back.
    const listParams=new URLSearchParams(params);listParams.set('page',String(page));listParams.set('anchor_id',String(id));
    navigate(location.pathname+'?'+listParams.toString(),{replace:true,state});
    navigate(photoLink(id,{...filters,page:String(page),
      ...(task ? {attach_task: String(task), task_channel: channel, ...(reply ? {attach_reply: '1'} : {})} : {})},review,spam),{state});
    window.scrollTo({top:0,behavior:'instant'});
  }
  async function markDefect(photo:Photo,checked:boolean){
    if(defectBusy!==null||!canEditPhoto(user,photo)||photo.is_spam)return;
    setDefectBusy(photo.id);setError('');
    try{
      const saved=await updatePhotoDefect(photo,checked);
      setData(value=>value?{...value,items:value.items.map(item=>item.id===photo.id?{...item,...saved,operator_name:user.name}:item)}:value);
      preserveRows.current=true;setRevision(value=>value+1);
      notify(checked?'Неисправность отмечена':'Отметка о неисправности снята');
    }catch(e){setError((e as Error).message);throw e;}
    finally{setDefectBusy(null);}
  }
  const canSendToTask = !!meta.organization;
  const target = Number(params.get('attach_task'));
  const task = !review && !spam && canSendToTask && Number.isSafeInteger(target) && target > 0 ? target : null;
  const channel = params.get('task_channel') === 'inspector' ? 'inspector' : 'executor';
  const draft = useResponsePhotoDraft();
  const reply = !!task && params.get('attach_reply') === '1';
  const response = reply && draft?.current?.appealId === task ? draft.current : null;
  const selectionLimit = reply ? response ? MAX_PHOTOS - response.files.length - response.operatorPhotos.length
    - response.sourcePhotos.filter(photo => photo.source === 'chat').length : 0 : MAX_PHOTOS;
  const [selected, setSelected] = useState<SelectedPhoto[]>(() => listState?.selectedPhotos || response?.sourcePhotos
    .filter(photo => photo.source === 'general').map(photo => ({id: Number(photo.id), preview_url: photo.url})) || []);
  const [destination, setDestination] = useState<{kind: 'chat' | 'task'; photos: SelectedPhoto[]} | null>(null);
  const [selecting, setSelecting] = useState(() => !!listState?.selectedPhotos?.length);
  const [menu, setMenu] = useState<PhotoMenuTarget | null>(null);
  const [sending, setSending] = useState(false);
  const attempt = useRef<{key: string; id: string} | null>(null);
  const selectionScope = JSON.stringify([task, review, spam, reply]);
  const previousScope = useRef(selectionScope);
  useEffect(() => {
    if (previousScope.current === selectionScope) return;
    previousScope.current = selectionScope;
    setSelected([]); setSelecting(false); setDestination(null); setMenu(null);
  }, [selectionScope]);
  const ids = selected.map(photo => photo.id);
  const returnToTask = () => navigate('/appeals?' + query({appeal: String(task), tab: channel}), {replace: true});
  function sent() {
    setSelected([]); setSelecting(false); setDestination(null); notify('Фотографии отправлены');
    if (task) returnToTask();
  }
  async function attach() {
    if (!task || sending) return;
    if (reply) {
      if (!draft || !response || selected.length > selectionLimit) return;
      draft.current = {...response, sourcePhotos: [
        ...response.sourcePhotos.filter(photo => photo.source !== 'general'),
        ...selected.flatMap(photo => photo.preview_url ? [{id: photo.id, url: photo.preview_url, source: 'general' as const}] : []),
      ]};
      returnToTask();
      return;
    }
    if (!ids.length) return;
    const key = JSON.stringify([task, channel, ids]);
    if (attempt.current?.key !== key) attempt.current = {key, id: crypto.randomUUID()};
    setSending(true); setError('');
    try {await sendTaskPhotos(task, ids, attempt.current.id, channel); sent();}
    catch (error) {setError((error as Error).message);}
    finally {setSending(false);}
  }
  function toggle(photo: Photo) {
    if (sending) return;
    setSelected(current => current.some(item => item.id === photo.id) ? current.filter(item => item.id !== photo.id)
      : current.length < selectionLimit ? [...current, photo] : current);
  }
  const contextEnabled = !review && !spam && !task;
  const selection = task || (contextEnabled && selecting) ? {ids: new Set(ids), toggle, limit: selectionLimit} : undefined;
  const sendControls = task && <section className="panel day-dialog-actions">
    <span>{reply && !response ? 'Черновик ответа недоступен' : `Выбрано фотографий ${ids.length} из ${selectionLimit}`}</span>
    <button disabled={sending} onClick={returnToTask}>{reply ? 'Вернуться к ответу' : 'Вернуться в задачу'}</button>
    <button className="primary" disabled={sending || (reply ? !response : !ids.length)} onClick={() => void attach()}>{reply ? 'Добавить в ответ' : sending ? 'Отправляем…' : 'Отправить в задачу'}</button>
  </section>;
  const menuPhotos = selected.length ? selected : menu?.photo.preview_url ? [menu.photo] : [];
  const dayTitle = filters.review_day && (review ? 'Требуют проверки' : filters.day_ai_only === 'true' ? 'Проверить за нейросетью'
    : filters.day_review === 'confirmed' ? 'Включены в закрытый день' : filters.day_review === 'pending' ? 'Ещё не включены в закрытый день' : 'Все фотографии дня');
  const dayChat = meta.chats.find(item => item.max_chat_id === filters.chat_id);
  const archiveTitle=filters.status==='DUPLICATE'?'Дубли':filters.status==='FORWARDED'?'Пересланные фотографии':null;
  return <>{dayTitle && <Link className="back-link" to={'/days?' + query({day: filters.review_day, chat_id: filters.chat_id || ''})}>К проверке дня</Link>}
  <header className="page-header"><div><h1>{dayTitle || (review?'Требуют проверки':spam?'Спам':archiveTitle||'Фотографии')}</h1>
    {dayTitle && <p>{dateLabel(filters.review_day)} · {dayChat?.name || 'Все доступные чаты'}</p>}</div><div className="photo-map-actions photo-list-actions"><button aria-label="Открыть на карте" title="Открыть на карте" onClick={()=>navigate('/photo-map?'+query({...filters,...(!filters.date_from&&!filters.date_to?{all_dates:'1'}:{})}))}><MapPin size={18}/><span>На карте</span></button><button onClick={()=>setRevision(x=>x+1)} aria-label="Обновить список"><RefreshCw size={18}/></button></div></header><FilterBar filters={filters} change={change} fixedStatus={review||spam} hideWork={spam} refreshKey={revision}/><PhotoNumberSearch owner={!!user.is_platform_owner} open={id=>task ? openPhoto(id) : navigate(`/photos/${id}?by_number=1&all_dates=1`)}/><ErrorBox error={error}/>{sendControls}
  {contextEnabled && menu && <PhotoContextMenu target={menu} count={menuPhotos.length} selecting={selecting}
    canSelect={!!menu.photo.preview_url && (selected.length < 10 || ids.includes(menu.photo.id))}
    canSendToTask={canSendToTask} close={() => setMenu(null)}
    select={() => {setSelecting(true); if (!ids.includes(menu.photo.id)) toggle(menu.photo);}}
    cancel={() => {setSelected([]); setSelecting(false);}}
    forward={kind => setDestination({kind, photos: menuPhotos})}/>}
  {destination?.kind === 'task' && <TaskPhotoSend ids={destination.photos.map(photo => photo.id)} close={() => setDestination(null)} sent={sent}/>}
  {destination?.kind === 'chat' && <ForwardPhotos photos={destination.photos.map(photo => ({...photo, organization_id: user.role === 'ADMIN_OPERATOR' ? meta.organization?.id : undefined}))}
    base={user.role === 'ADMIN_OPERATOR' && canSendToTask ? '/inspection-admin' : undefined}
    unified={user.role === 'ADMIN_OPERATOR' && canSendToTask} onClose={() => setDestination(null)} onSent={sent}/>}
  {data?<section className="panel photo-panel"><div className="section-title"><h2>{dayTitle || (review?'Очередь проверки':spam?'Спам':archiveTitle||'Все фотографии')} <span className="count-pill appeal-count">{data.total}</span></h2></div>{data.items.length===0?<Empty>{review?'В этой выборке нет фотографий, требующих проверки.':'Измените фильтры, чтобы найти нужные фотографии.'}</Empty>:<PhotoTable selection={selection} onPhotoMenu={contextEnabled ? setMenu : undefined} photos={data.items} openPhoto={openPhoto} focusId={data.focus_id??anchorId} defectBusy={defectBusy} onDefect={markDefect}/>}{data.total>data.page_size&&<div className="pagination"><span>Страница {page} из {Math.max(1,Math.ceil(data.total/data.page_size))}</span><button disabled={page<=1} onClick={()=>setPage(page-1)}><ChevronLeft size={16}/>Назад</button><button disabled={page*data.page_size>=data.total} onClick={()=>setPage(page+1)}>Далее<ChevronRight size={16}/></button></div>}</section>:!error&&<p className="loading">Загружаем фотографии…</p>}</>;
}
