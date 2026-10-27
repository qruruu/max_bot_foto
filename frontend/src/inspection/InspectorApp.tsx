import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Building2, Camera, ChartNoAxesCombined, ChevronLeft, ChevronRight, Layers, LogOut, Map, MapPin, MessageSquare, QrCode, RefreshCw, Users } from 'lucide-react';
import { api } from '../api';
import Login, { signInDestination } from '../Login';
import type { Meta, User } from '../types';
import { AppContextProvider } from '../App';
import useSidebar from '../useSidebar';
import SidebarNavigation from '../SidebarNavigation';
import Settings from '../Settings';
import DistrictMap from '../DistrictMap';
import OwnerAppeals from '../appeals/OwnerAppeals';
import { PhotoNotificationsProvider } from '../PhotoNotifications';
import { OperatorChatBadge, OperatorChatsProvider } from '../OperatorChatsProvider';
import InspectionChats from './Chats';
import InspectionPhotoDetail from './PhotoDetail';
import type { InspectionPhotoPosition } from './PhotoDetail';
import InspectionAccounts from './Accounts';
import InspectionPhotoTable from './PhotoTable';
import PhotoNumberSearch from '../PhotoNumberSearch';
import InspectionPhotoMap from './Maps';
import InspectionFilters, { inspectionFilterKeys } from './FilterBar';
import InspectionOverview from './Report';
import Avatar from '../Avatar';
import { invitationToken, QRScanner } from './QR';
import type { InspectionMeta, InspectionReport, Inspector, Organization, PhotoPage } from './types';
import './inspection.css';

const tabs=[{id:'photos',label:'Фотографии',Icon:Camera},{id:'reports',label:'Отчёты',Icon:ChartNoAxesCombined},
  {id:'photo-map',label:'Карта фотографий',Icon:MapPin},{id:'districts',label:'Микрорайоны',Icon:Map},
  {id:'appeals',label:'Обращения граждан',Icon:MessageSquare},{id:'messages',label:'Чаты',Icon:MessageSquare}];
const menuOrder=['/inspectors','/','/photos','/photo-map','/districts','/appeals','/messages','/users'];
const menuKeys:Record<string,string>={reports:'/',photos:'/photos','photo-map':'/photo-map',districts:'/districts',appeals:'/appeals',messages:'/messages',accounts:'/users'};
const emptyMeta:InspectionMeta={districts:[],work_types:[],today:new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Yekaterinburg',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()),timezone:'Asia/Yekaterinburg',yandex_maps_api_key:''};

export default function InspectorApp() {
  const [user,setUser]=useState<Inspector|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const sidebar=useSidebar();
  const [organizations,setOrganizations]=useState<Organization[]>([]),[scanner,setScanner]=useState(false),[busy,setBusy]=useState(false);
  const [params,setParams]=useSearchParams(),navigate=useNavigate();
  const [photos,setPhotos]=useState<PhotoPage>({items:[],total:0,page:1,page_size:40}),[report,setReport]=useState<InspectionReport|null>(null);
  const [meta,setMeta]=useState<InspectionMeta>(emptyMeta);
  const [revision,setRevision]=useState(0),[dataLoading,setDataLoading]=useState(false);
  const invitation=useRef<string|null>(null),redeeming=useRef(false),openedHere=useRef(false);
  const location=useLocation(),photoPosition=useRef<InspectionPhotoPosition|null>(null);
  const pathPhoto=location.pathname.match(/^\/inspection\/photos\/([1-9]\d*)$/)?.[1];
  const org=params.get('org') || '',tab=params.get('tab') || 'photos',photoId=Number(pathPhoto||params.get('photo'));
  const viewingPhoto=!!org&&Number.isSafeInteger(photoId)&&photoId>0;
  const page=Math.max(1,Number(params.get('page'))||1),orgInfo=organizations.find(o=>o.id===org);
  const filters=new URLSearchParams();for(const key of inspectionFilterKeys){const value=params.get(key);if(value)filters.set(key,value);}
  const filterQuery=filters.toString(),base='/inspection/organizations/'+org;
  useEffect(()=>{if(params.has('work_type'))setParams(previous=>{const next=new URLSearchParams(previous);next.delete('work_type');return next;},{replace:true});},[params,setParams]);
  useLayoutEffect(()=>{if(!viewingPhoto&&photoPosition.current){const previous=photoPosition.current;photoPosition.current=null;window.scrollTo(0,previous.scrollY);const log=document.querySelector<HTMLElement>('.operator-message-list'),table=document.querySelector<HTMLElement>('.inspection-photos .table-scroll');if(log&&previous.chatScrollTop!==undefined)log.scrollTop=previous.chatScrollTop;if(table&&previous.tableScrollLeft!==undefined)table.scrollLeft=previous.tableScrollLeft;if(previous.focus?.isConnected)previous.focus.focus({preventScroll:true});}},[viewingPhoto]);
  function signedIn(account: User) {if(account.role==='INSPECTOR')setUser(account as Inspector);else window.location.replace(signInDestination(account));}
  async function loadOrganizations(){const list=await api<Organization[]>('/inspection/organizations');setOrganizations(list);return list;}
  useEffect(()=>{
    const token=new URLSearchParams(window.location.hash.slice(1)).get('invite');
    if(token){try{invitation.current=invitationToken(token);sessionStorage.setItem('inspection-pending-invite',invitation.current);}catch{}window.history.replaceState(window.history.state,'',window.location.pathname+window.location.search);}
    else invitation.current=sessionStorage.getItem('inspection-pending-invite');
    api<Inspector>('/inspection/me').then(setUser).catch(e=>{if(e.status!==401)setError(e.message);}).finally(()=>setLoading(false));
    const expired=()=>{setUser(null);setOrganizations([]);setPhotos({items:[],total:0,page:1,page_size:40});setReport(null);};
    window.addEventListener('session-expired',expired);return()=>window.removeEventListener('session-expired',expired);
  },[]);
  async function redeem(token: string) {
    if(redeeming.current)return;redeeming.current=true;setBusy(true);setError('');setNotice('');setScanner(false);
    try{const result=await api<Organization>('/inspection/redeem','POST',{token});await loadOrganizations();setParams({org:result.id,tab:'photos'});setNotice('Открыт доступ к организации «'+result.name+'». QR использован.');}
    catch(e){setError((e as Error).message);}finally{redeeming.current=false;setBusy(false);invitation.current=null;sessionStorage.removeItem('inspection-pending-invite');}
  }
  useEffect(()=>{if(!user)return;void loadOrganizations().catch(e=>setError(e.message));if(invitation.current)void redeem(invitation.current);},[user?.id]);
  useEffect(()=>{setMeta(emptyMeta);if(!user||!org)return;
    const abort=new AbortController();api<InspectionMeta>(base+'/meta','GET',undefined,abort.signal).then(value=>setMeta({...emptyMeta,...value})).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return()=>abort.abort();
  },[user?.id,org,revision]);
  useEffect(()=>{
    setPhotos({items:[],total:0,page:1,page_size:40});setReport(null);setDataLoading(false);
    if(!user||!org||!['photos','reports'].includes(tab))return;
    const abort=new AbortController();setDataLoading(true);setError('');
    const suffix='?'+filterQuery+(filterQuery?'&':'')+'page='+page;
    const request=tab==='photos'?api<PhotoPage>(base+'/photos'+suffix,'GET',undefined,abort.signal).then(setPhotos):
      api<InspectionReport>(base+'/reports'+suffix,'GET',undefined,abort.signal).then(setReport);
    request.catch(e=>{if(!abort.signal.aborted)setError(e.message);}).finally(()=>{if(!abort.signal.aborted)setDataLoading(false);});return()=>abort.abort();
  },[user?.id,org,tab,filterQuery,page,revision]);
  useEffect(()=>{const refresh=()=>setRevision(v=>v+1);window.addEventListener('refresh-photo-list',refresh);return()=>window.removeEventListener('refresh-photo-list',refresh);},[]);
  function update(key:string,value:string){const next=new URLSearchParams(params);value?next.set(key,value):next.delete(key);next.delete('photo');if(key!=='page')next.delete('page');setParams(next);}
  function change(values:Record<string,string>){const next=new URLSearchParams(params);for(const [key,value] of Object.entries(values)){value?next.set(key,value):next.delete(key);}next.delete('page');next.delete('photo');setParams(next);}
  function rememberPhotoPosition(){photoPosition.current={scrollY:window.scrollY,focus:document.activeElement as HTMLElement|null,chatScrollTop:document.querySelector<HTMLElement>('.operator-message-list')?.scrollTop,tableScrollLeft:document.querySelector<HTMLElement>('.inspection-photos .table-scroll')?.scrollLeft};}
  function openPhoto(id:number,replace=false){
    const next=new URLSearchParams(params);next.delete('photo');
    if(!replace){openedHere.current=true;rememberPhotoPosition();}
    navigate('/inspection/photos/'+id+'?'+next,{replace});
  }
  function closePhoto(){
    if(openedHere.current){openedHere.current=false;navigate(-1);}
    else {const next=new URLSearchParams(params);next.delete('photo');next.delete('inspection_chat');navigate('/inspection?'+next,{replace:true});}
  }
  if(loading)return <div className="full-loading">Открываем кабинет проверяющего…</div>;
  if(!user)return <Login unified onLogin={signedIn} initialError={error}/>;
  const independent=['messages','accounts','settings'].includes(tab);
  const title=tab==='accounts'?'Аккаунты':!org&&!independent?'Организации':tabs.find(t=>t.id===tab)?.label || 'Фотографии';
  function sectionLink(section:string,extra:Record<string,string>={}) {
    const next=new URLSearchParams(params);next.set('tab',section);next.delete('page');next.delete('photo');next.delete('section');
    for(const [key,value] of Object.entries(extra))value?next.set(key,value):next.delete(key);
    return '/inspection?'+next;
  }
  const links=[{to:'/inspectors',label:'Организации',Icon:Building2,href:'/inspection',active:!org&&!independent},
    ...tabs.filter(t=>org||t.id==='messages').map(t=>({to:menuKeys[t.id],label:t.label,Icon:t.Icon,href:sectionLink(t.id),active:tab===t.id,badge:t.id==='messages'?<OperatorChatBadge/>:undefined})),
    ...(user.can_create_accounts?[{to:'/users',label:'Аккаунты',Icon:Users,href:sectionLink('accounts'),active:tab==='accounts'}]:[])];
  const appMeta:Meta={...meta,permission_catalog:[],statuses:['ACCEPTED'],chats:[],operators:[],organization:orgInfo||null};
  const notificationOrg=org||organizations[0]?.id;
  return <AppContextProvider value={{user,meta:appMeta,refresh:async()=>{setRevision(v=>v+1);},notify:setNotice,updateUser:account=>setUser(account as Inspector)}}>
    <OperatorChatsProvider key={user.id} endpoint="/inspection/unread">
    <PhotoNotificationsProvider key={user.id} userId={-user.id} canViewPhotos={!!notificationOrg}
      endpoint={'/inspection/organizations/'+notificationOrg+'/photos/arrivals'} photoLink={id=>sectionLink('photos',{org:notificationOrg||'',...(id?{photo:String(id)}:{})})}>
    <div className={'app inspection-app '+(sidebar.collapsed?'sidebar-collapsed':'sidebar-expanded')}>
      {!sidebar.collapsed&&<button className="sidebar-backdrop" aria-label="Закрыть боковую панель" onClick={sidebar.toggle}/>}
      <aside className="sidebar">
        <Link className="brand" to="/inspection" aria-label="Метка — главная"><span className="brand-mark"><Layers size={23}/></span><span className="brand-copy">Метка<small>Контроль городских работ</small></span></Link>
        <SidebarNavigation key={user.id} links={links} order={user.sidebar_order?.length?user.sidebar_order:menuOrder}
          collapsed={sidebar.collapsed} toggle={sidebar.toggle} saveEndpoint="/inspection/sidebar-order" resetOrder={menuOrder}
          onSaved={sidebar_order=>setUser(current=>current?{...current,sidebar_order}:current)}/>
        <div className="sidebar-bottom"><Link to={sectionLink('settings',{section:'profile'})} className={'account-link'+(tab==='settings'?' active':'')} title="Настройки" aria-label="Настройки">
          <Avatar name={user.name} src={user.avatar_url||null}/><span className="account-info"><strong>{user.name}</strong><small>Проверяющий</small></span></Link>
          <button aria-label="Выйти" title="Выйти" onClick={()=>void api('/inspection/logout','POST').then(()=>{setUser(null);setOrganizations([]);setParams({});}).catch(e=>setError(e.message))}><LogOut size={17}/></button>
        </div>
      </aside>
      <main className="workspace inspection-workspace">
        <div className="topbar inspection-context"><span className="workspace-identity"><span className="dot"/><strong>{orgInfo?.name||user.agency_name}</strong><span className="timezone">Кабинет проверяющего</span></span>
          {!!org&&!independent&&organizations.length>1&&<label className="inspection-organization-select"><span>Организация</span><select value={org} onChange={e=>{
            setParams({org:e.target.value,tab});
          }}>{organizations.map(o=><option value={o.id} key={o.id}>{o.name}</option>)}</select></label>}
        </div>
        {notice&&<div className="organization-notice" role="status">{notice}<button className="text-button" aria-label="Закрыть уведомление" onClick={()=>setNotice('')}>×</button></div>}
        <div hidden={viewingPhoto}>
        {tab!=='settings'&&(!org||!['districts','appeals'].includes(tab))&&<header className="page-header"><div><span className="eyebrow">{tab==='photos'&&org?'АРХИВ ФОТОГРАФИЙ':tab==='reports'?'ЕЖЕДНЕВНЫЙ ОТЧЁТ':'КАБИНЕТ ПРОВЕРЯЮЩЕГО'}</span><h1>{title}</h1>
          <p>{tab==='photos'&&org?'Фотографии выполненных работ после закрытия дня в Метке.':tab==='reports'?'Выполненные работы в цифрах и фотографиях.':tab==='photo-map'?'География снимков за выбранный период.':tab==='messages'?'Личные переписки с администраторами организаций и коллегами.':tab==='accounts'?'Сотрудники вашей администрации.':'Выберите организацию или отсканируйте QR для получения доступа.'}</p></div>
          <div className="inspection-actions"><button disabled={busy||dataLoading} onClick={()=>{setRevision(v=>v+1);void loadOrganizations().catch(e=>setError(e.message));}}><RefreshCw size={17}/>Обновить</button>
            {tab==='photos'&&org&&<button onClick={()=>change({tab:'photo-map'})}><MapPin size={17}/>На карте</button>}
            <button className={!org?'primary':''} disabled={busy} onClick={()=>setScanner(v=>!v)}><QrCode size={18}/>Сканировать QR</button></div></header>}
        {error&&<p className="error" role="alert">{error}</p>}
        {scanner&&<QRScanner onScan={token=>void redeem(token)} onClose={()=>setScanner(false)}/>}
        {tab==='settings'?<Settings authBase="/inspection" selectedSection={params.get('section')||'profile'} sectionLink={section=>sectionLink('settings',{section})}/>:
        tab==='messages'?<InspectionChats active={!viewingPhoto} revision={revision} timezone={meta.timezone} openPhotoLink={url=>{openedHere.current=true;rememberPhotoPosition();navigate(url);}}/>:
        tab==='accounts'&&user.can_create_accounts?<InspectionAccounts/>:
        !org?<><div className="organization-grid">{organizations.map(o=><article key={o.id} className="panel organization-card"><Building2 size={25}/><h2>{o.name}</h2><p>{o.city}</p><button className="primary" onClick={()=>setParams({org:o.id,tab:'photos'})}>Открыть<ChevronRight size={17}/></button></article>)}</div>
          {!organizations.length&&<p className="empty">Нет доступных организаций. Отсканируйте новый QR организации.</p>}</>:
        tab==='districts'?<><button className="inspection-district-refresh" aria-label="Обновить микрорайоны" onClick={()=>setRevision(v=>v+1)}><RefreshCw size={17}/></button><DistrictMap key={org+':'+revision} endpoint={base+'/districts'} readOnly/></>:
        tab==='appeals'?<OwnerAppeals organization endpoint={base+'/appeals'} readOnly refreshKey={revision}/>:
        <>
          {tab==='photos'&&<PhotoNumberSearch owner={false} endpoint={base+'/photos'} open={openPhoto} description="Поиск среди фотографий закрытых дней этой организации, независимо от даты и фильтров."/>}
          {['photos','reports','photo-map'].includes(tab)&&<InspectionFilters meta={meta} filters={Object.fromEntries(filters)} base={base} change={change}/>}
          {dataLoading&&<p className="loading">Загружаем данные…</p>}
          {tab==='photos'&&<>
            <section className="panel photo-panel inspection-photos"><div className="section-title"><h2>Все фотографии <span className="count-pill">{photos.total}</span></h2><span>Закрытые дни</span></div>
              {photos.items.length>0&&<InspectionPhotoTable photos={photos.items} openPhoto={openPhoto} workTypes={meta.work_types}/>}
              {!photos.items.length&&!dataLoading&&<p className="empty">За выбранный период нет фотографий закрытых дней.</p>}
              {photos.total>0&&<div className="pagination"><span>Страница {photos.page} из {Math.max(1,Math.ceil(photos.total/photos.page_size))}</span><button disabled={photos.page<=1} onClick={()=>update('page',String(photos.page-1))}><ChevronLeft size={16}/>Назад</button><button disabled={photos.page*photos.page_size>=photos.total} onClick={()=>update('page',String(photos.page+1))}>Далее<ChevronRight size={16}/></button></div>}
            </section></>}
          {tab==='reports'&&report&&<InspectionOverview report={report} meta={meta} filters={Object.fromEntries(filters)} open={values=>change({...values,tab:'photos'})}/>}
          {tab==='photo-map'&&<InspectionPhotoMap key={org} base={base} filters={filterQuery} meta={meta} revision={revision} openPhoto={openPhoto} photoLink={id=>sectionLink('photo-map',{photo:String(id)})} showList={()=>change({tab:'photos'})}/>}
        </>}
        </div>
        {viewingPhoto&&<InspectionPhotoDetail org={org} id={photoId} filters={filterQuery} fromChat={tab==='messages'} onClose={closePhoto} onMove={id=>openPhoto(id,true)}/>}

      </main>
    </div></PhotoNotificationsProvider></OperatorChatsProvider>
  </AppContextProvider>;
}
