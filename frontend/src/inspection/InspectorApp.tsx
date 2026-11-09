import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { usePresenceHeartbeat } from '../UserPresence';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Building2, Camera, ChevronLeft, ChevronRight, Layers, LogOut, Map, MapPin, MessageSquare, QrCode, RefreshCw, Users } from 'lucide-react';
import { api } from '../api';
import Login, { signInDestination } from '../Login';
import type { Meta, User } from '../types';
import { AppContextProvider } from '../App';
import useSidebar from '../useSidebar';
import MobileNavigation from '../MobileNavigation';
import SidebarNavigation from '../SidebarNavigation';
import Settings from '../Settings';
import DistrictMap from '../DistrictMap';
import InspectionAppeals from './Appeals';
import { useAppealNotifications } from '../appeals/notifications';
import { PhotoNotificationsProvider } from '../PhotoNotifications';
import { OperatorChatBadge, OperatorChatsProvider } from '../OperatorChatsProvider';
import InspectionChats from './Chats';
import InspectionPhotoDetail from './PhotoDetail';
import type { InspectionPhotoPosition } from './PhotoDetail';
import InspectionAccounts from './Accounts';
import InspectionPhotoTable from './PhotoTable';
import PhotoNumberSearch from '../PhotoNumberSearch';
import { capturePhotoListPosition, photoListAnchor, photoListPage, restorePhotoListPosition } from '../photoNavigation';
import type { PhotoListPosition } from '../photoNavigation';
import InspectionPhotoMap from './Maps';
import InspectionFilters, { inspectionFilterKeys } from './FilterBar';
import Avatar from '../Avatar';
import { invitationToken, QRScanner } from './QR';
import type { InspectionMeta, Inspector, Organization, PhotoPage } from './types';
import './inspection.css';

const tabs=[{id:'photos',label:'Фотографии',Icon:Camera},
  {id:'photo-map',label:'Карта фотографий',Icon:MapPin},{id:'districts',label:'Микрорайоны',Icon:Map},
  {id:'appeals',label:'Обращения',Icon:MessageSquare},{id:'messages',label:'Чаты',Icon:MessageSquare}];
const menuOrder=['/inspectors','/photos','/photo-map','/districts','/appeals','/messages','/users'];
const menuKeys:Record<string,string>={photos:'/photos','photo-map':'/photo-map',districts:'/districts',appeals:'/appeals',messages:'/messages',accounts:'/users'};
const emptyMeta:InspectionMeta={districts:[],work_types:[],today:new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Yekaterinburg',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()),timezone:'Asia/Yekaterinburg',yandex_maps_api_key:''};

export default function InspectorApp() {
  const [user,setUser]=useState<Inspector|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[notice,setNotice]=useState('');
  usePresenceHeartbeat(!!user, "/inspection/presence");
  const sidebar=useSidebar();
  const [organizations,setOrganizations]=useState<Organization[]>([]),[scanner,setScanner]=useState(false),[busy,setBusy]=useState(false);
  const [params,setParams]=useSearchParams(),navigate=useNavigate();
  const [photos,setPhotos]=useState<PhotoPage>({items:[],total:0,page:1,page_size:40});
  const [meta,setMeta]=useState<InspectionMeta>(emptyMeta);
  const [revision,setRevision]=useState(0),[dataLoading,setDataLoading]=useState(false);
  const invitation=useRef<string|null>(null),redeeming=useRef(false),openedHere=useRef(false);
  const location=useLocation(),photoPosition=useRef<InspectionPhotoPosition|null>(null);
  const listPosition=useRef<PhotoListPosition|undefined>(undefined);
  const lastListPhoto=useRef<{context:string;id:number}|null>(null);
  const loadedPhotoQuery=useRef('');
  const restoredLocation=useRef('');
  const pathPhoto=location.pathname.match(/^\/inspection\/photos\/([1-9]\d*)$/)?.[1];
  const org=params.get('org') || '',tab=params.get('tab')==='reports'?'photos':params.get('tab') || 'photos',photoId=Number(pathPhoto||params.get('photo'));
  const viewingPhoto=!!org&&Number.isSafeInteger(photoId)&&photoId>0;
  const page=photoListPage(params.get('page')),orgInfo=organizations.find(o=>o.id===org);
  const filters=new URLSearchParams();for(const key of inspectionFilterKeys){const value=params.get(key);if(value)filters.set(key,value);}
  if(tab==='photo-map'&&!params.has('all_dates')&&!filters.has('date_from')&&!filters.has('date_to')){
    filters.set('date_from',meta.today);filters.set('date_to',meta.today);
  }
  const filterQuery=filters.toString(),base='/inspection/organizations/'+org;
  const anchorId=photoListAnchor(params.get('anchor_id'));
  const listParams=new URLSearchParams(filters);
  listParams.set('page',String(page));
  const listContext=base+'/photos?'+listParams;
  const listQuery=listContext+(anchorId?'&anchor_id='+anchorId:'');
  const appealOrganization = org || organizations[0]?.id || '';
  const appeals = useAppealNotifications(!!user && organizations.length > 0, user?.id, '/inspection/appeals/notifications');
  useEffect(()=>{if(params.get('tab')==='reports')setParams(previous=>{const next=new URLSearchParams(previous);next.set('tab','photos');return next;},{replace:true});},[params,setParams]);
  useLayoutEffect(()=>{if(!viewingPhoto&&photoPosition.current){const previous=photoPosition.current;photoPosition.current=null;window.scrollTo(0,previous.scrollY);const log=document.querySelector<HTMLElement>('.operator-message-list'),table=document.querySelector<HTMLElement>('.inspection-photos .table-scroll');if(log&&previous.chatScrollTop!==undefined)log.scrollTop=previous.chatScrollTop;if(table&&previous.tableScrollLeft!==undefined)table.scrollLeft=previous.tableScrollLeft;if(previous.focus?.isConnected)previous.focus.focus({preventScroll:true});}},[viewingPhoto]);
  // The list's history entry can still point at the first photo after Previous/Next.
  useLayoutEffect(()=>{
    if(viewingPhoto){
      lastListPhoto.current=tab==='photos'?{context:listContext,id:photoId}:null;
      return;
    }
    openedHere.current=false;
    const last=lastListPhoto.current;
    lastListPhoto.current=null;
    if(last&&last.context!==listContext)listPosition.current=undefined;
    if(tab==='photos'&&last?.context===listContext&&last.id!==anchorId){
      const next=new URLSearchParams(params);
      next.set('anchor_id',String(last.id));
      restoredLocation.current=location.key;
      setParams(next,{replace:true});
    }
  },[viewingPhoto,tab,photoId,listContext,anchorId,location.key,params,setParams]);
  useLayoutEffect(()=>{
    if(viewingPhoto||tab!=='photos'||!anchorId||loadedPhotoQuery.current!==listQuery||restoredLocation.current===location.key)return;
    restoredLocation.current=location.key;
    restorePhotoListPosition(photos.focus_id??undefined,listPosition.current);
    listPosition.current=undefined;
  },[viewingPhoto,tab,anchorId,listQuery,location.key,photos]);
  function signedIn(account: User) {if(account.role==='INSPECTOR')setUser(account as Inspector);else window.location.replace(signInDestination(account));}
  async function loadOrganizations(){const list=await api<Organization[]>('/inspection/organizations');setOrganizations(list);return list;}
  useEffect(()=>{
    const token=new URLSearchParams(window.location.hash.slice(1)).get('invite');
    if(token){try{invitation.current=invitationToken(token);sessionStorage.setItem('inspection-pending-invite',invitation.current);}catch{}window.history.replaceState(window.history.state,'',window.location.pathname+window.location.search);}
    else invitation.current=sessionStorage.getItem('inspection-pending-invite');
    api<Inspector>('/inspection/me').then(setUser).catch(e=>{if(e.status!==401)setError(e.message);}).finally(()=>setLoading(false));
    const expired=()=>{setUser(null);setOrganizations([]);setPhotos({items:[],total:0,page:1,page_size:40});};
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
    loadedPhotoQuery.current='';
    setPhotos({items:[],total:0,page:1,page_size:40});setDataLoading(false);
    if(!user||!org||tab!=='photos')return;
    const abort=new AbortController();setDataLoading(true);setError('');
    const request=api<PhotoPage>(listQuery,'GET',undefined,abort.signal).then(value=>{
      if(!abort.signal.aborted){loadedPhotoQuery.current=listQuery;setPhotos(value);}
    });
    request.catch(e=>{if(!abort.signal.aborted)setError(e.message);}).finally(()=>{if(!abort.signal.aborted)setDataLoading(false);});return()=>abort.abort();
  },[user?.id,org,tab,listQuery,revision]);
  useEffect(()=>{const refresh=()=>setRevision(v=>v+1);window.addEventListener('refresh-photo-list',refresh);return()=>window.removeEventListener('refresh-photo-list',refresh);},[]);
  function update(key:string,value:string){const next=new URLSearchParams(params);value?next.set(key,value):next.delete(key);next.delete('photo');next.delete('anchor_id');if(key!=='page')next.delete('page');setParams(next);}
  function change(values:Record<string,string>){const next=new URLSearchParams(params);if(tab==='photo-map')for(const [key,value] of filters)next.set(key,value);for(const [key,value] of Object.entries(values)){value?next.set(key,value):next.delete(key);}if(tab==='photo-map'&&('date_from' in values||'date_to' in values)){if(next.has('date_from')||next.has('date_to'))next.delete('all_dates');else next.set('all_dates','1');}next.delete('page');next.delete('photo');next.delete('anchor_id');setParams(next);}
  function rememberPhotoPosition(){photoPosition.current={scrollY:window.scrollY,focus:document.activeElement as HTMLElement|null,chatScrollTop:document.querySelector<HTMLElement>('.operator-message-list')?.scrollTop,tableScrollLeft:document.querySelector<HTMLElement>('.inspection-photos .table-scroll')?.scrollLeft};}
  function openPhoto(id:number,replace=false){
    const next=new URLSearchParams(params);next.delete('photo');
    if(tab==='photo-map')for(const [key,value] of filters)next.set(key,value);
    if(!replace){
      openedHere.current=true;rememberPhotoPosition();
      listPosition.current=tab==='photos'?capturePhotoListPosition(id):undefined;
    }
    navigate('/inspection/photos/'+id+'?'+next,{replace});
  }
  function closePhoto(){
    if(openedHere.current){openedHere.current=false;navigate(-1);}
    else {const next=new URLSearchParams(params);next.delete('photo');next.delete('inspection_chat');navigate('/inspection?'+next,{replace:true});}
  }
  if(loading)return <div className="full-loading">Открываем кабинет проверяющего…</div>;
  if(!user)return <Login unified onLogin={signedIn} initialError={error}/>;
  const independent=['messages','accounts','settings'].includes(tab);
  const choosingOrganization = !org && !independent;
  const title=tab==='accounts'?'Аккаунты':!org&&!independent?'Организации':tabs.find(t=>t.id===tab)?.label || 'Фотографии';
  function sectionLink(section:string,extra:Record<string,string>={}) {
    const next=new URLSearchParams(params);next.set('tab',section);next.delete('page');next.delete('photo');next.delete('anchor_id');next.delete('section');next.delete('appeal');
    if(tab==='photo-map'&&(section==='photos'||section==='photo-map'))for(const [key,value] of filters)next.set(key,value);
    for(const [key,value] of Object.entries(extra))value?next.set(key,value):next.delete(key);
    return '/inspection?'+next;
  }
  const links=[{to:'/inspectors',label:'Организации',Icon:Building2,href:'/inspection',active:!org&&!independent},
    ...tabs.filter(t=>org||t.id==='messages').map(t=>({to:menuKeys[t.id],label:t.label,Icon:t.Icon,href:sectionLink(t.id),active:tab===t.id,badge:t.id==='messages'?<OperatorChatBadge/>:t.id==='appeals' && appeals.count ? <span className="count-pill appeal-count">{appeals.count}</span>:undefined})),
    ...(user.can_create_accounts?[{to:'/users',label:'Аккаунты',Icon:Users,href:sectionLink('accounts'),active:tab==='accounts'}]:[])];
  const appMeta:Meta={...meta,permission_catalog:[],statuses:['ACCEPTED'],chats:[],operators:[],organization:orgInfo||null};
  const notificationOrg=org||organizations[0]?.id;
  return <AppContextProvider value={{user,meta:appMeta,refresh:async()=>{setRevision(v=>v+1);},notify:setNotice,updateUser:account=>setUser(account as Inspector)}}>
    <OperatorChatsProvider key={user.id} endpoint="/inspection/unread">
    <PhotoNotificationsProvider key={user.id} userId={-user.id} canViewPhotos={!!notificationOrg}
      endpoint={'/inspection/organizations/'+notificationOrg+'/photos/arrivals'} photoLink={id=>sectionLink('photos',{org:notificationOrg||'',...(id?{photo:String(id)}:{})})}>
    <div className={'app inspection-app '+(sidebar.collapsed?'sidebar-collapsed':'sidebar-expanded')}>
      {!sidebar.collapsed&&<button className="sidebar-backdrop" aria-label="Закрыть боковую панель" onClick={sidebar.toggle}/>}
      <aside id="workspace-sidebar" ref={sidebar.sidebar} className="sidebar">
        <Link className="brand" onClick={sidebar.closeMenu} to="/inspection" aria-label="Метка — главная"><span className="brand-mark"><Layers size={23}/></span><span className="brand-copy">Метка<small>Контроль городских работ</small></span></Link>
        <SidebarNavigation key={user.id} links={links} order={user.sidebar_order?.length?user.sidebar_order:menuOrder}
          collapsed={sidebar.collapsed} toggle={sidebar.toggle} onNavigate={sidebar.closeMenu} saveEndpoint="/inspection/sidebar-order" resetOrder={menuOrder}
          onSaved={sidebar_order=>setUser(current=>current?{...current,sidebar_order}:current)}/>
        <div className="sidebar-bottom"><Link onClick={sidebar.closeMenu} to={sectionLink('settings',{section:'profile'})} className={'account-link'+(tab==='settings'?' active':'')} title="Настройки" aria-label="Настройки">
          <Avatar name={user.name} src={user.avatar_url||null}/><span className="account-info"><strong>{user.name}</strong><small>Проверяющий</small></span></Link>
          <button aria-label="Выйти" title="Выйти" onClick={()=>void api('/inspection/logout','POST').then(()=>{setUser(null);setOrganizations([]);setParams({});}).catch(e=>setError(e.message))}><LogOut size={17}/></button>
        </div>
      </aside>
      <main className="workspace inspection-workspace">
        <div className="topbar inspection-context">
          <MobileNavigation button={sidebar.menuButton} open={sidebar.menuOpen} toggle={sidebar.toggle} updates={appeals.count > 0}/>
          <span className="workspace-identity"><span className="dot"/><strong>{orgInfo?.name||user.agency_name}</strong><span className="timezone">Кабинет проверяющего</span></span>
          {!!org&&!independent&&organizations.length>1&&<label className="inspection-organization-select"><span>Организация</span><select value={org} onChange={e=>{
            setParams({org:e.target.value,tab});
          }}>{organizations.map(o=><option value={o.id} key={o.id}>{o.name}</option>)}</select></label>}
        </div>
        {notice&&<div className="organization-notice" role="status">{notice}<button className="text-button" aria-label="Закрыть уведомление" onClick={()=>setNotice('')}>×</button></div>}
        {tab !== 'appeals' && appeals.notice > 0 && <div className="organization-notice" role="status">Новых обращений: {appeals.notice}. <Link to={sectionLink('appeals', {org: appeals.organizationId || appealOrganization})} onClick={appeals.dismiss}>Открыть обращения</Link><button onClick={appeals.dismiss} aria-label="Закрыть уведомление об обращениях">×</button></div>}
        <div hidden={viewingPhoto}>
        {tab!=='settings'&&(!org||!['districts','appeals'].includes(tab))&&<header className="page-header"><div><h1>{title}</h1>
          {choosingOrganization && <p>Выберите организацию или подключите новую по QR.</p>}</div>
          <div className="inspection-actions"><button type="button" aria-label="Обновить" title="Обновить" disabled={busy||dataLoading} onClick={()=>{setRevision(v=>v+1);void loadOrganizations().catch(e=>setError(e.message));}}><RefreshCw size={17}/></button>
            {choosingOrganization && <button type="button" className="primary" disabled={busy} onClick={()=>setScanner(v=>!v)}><QrCode size={18}/>Добавить по QR</button>}</div></header>}
        {error&&<p className="error" role="alert">{error}</p>}
        {scanner&&<QRScanner onScan={token=>void redeem(token)} onClose={()=>setScanner(false)}/>}
        {tab==='settings'?<Settings authBase="/inspection" selectedSection={params.get('section')||'profile'} sectionLink={section=>sectionLink('settings',{section})}/>:
        tab==='messages'?<InspectionChats active={!viewingPhoto} revision={revision} timezone={meta.timezone} openPhotoLink={url=>{openedHere.current=true;rememberPhotoPosition();navigate(url);}}/>:
        tab==='accounts'&&user.can_create_accounts?<InspectionAccounts/>:
        !org?<><div className="organization-grid">{organizations.map(o=><article key={o.id} className="panel organization-card"><Building2 size={25}/><h2>{o.name}</h2><p>{o.city}</p><button className="primary" onClick={()=>setParams({org:o.id,tab:'photos'})}>Открыть<ChevronRight size={17}/></button></article>)}</div>
          {!organizations.length&&<p className="empty">Нет доступных организаций. Отсканируйте новый QR организации.</p>}</>:
        tab==='districts'?<><button className="inspection-district-refresh" aria-label="Обновить микрорайоны" onClick={()=>setRevision(v=>v+1)}><RefreshCw size={17}/></button><DistrictMap key={org+':'+revision} endpoint={base+'/districts'} readOnly/></>:
        tab==='appeals'?<InspectionAppeals key={org} organizationId={org} inspectorId={user.id} refreshKey={revision}/>:
        <>
          {['photos','photo-map'].includes(tab)&&<InspectionFilters meta={meta} filters={Object.fromEntries(filters)} change={change}/>}
          {tab==='photos'&&<PhotoNumberSearch owner={false} endpoint={base+'/photos'} open={openPhoto} description="Поиск среди фотографий закрытых дней этой организации, независимо от даты и фильтров."/>}
          {dataLoading&&<p className="loading">Загружаем данные…</p>}
          {tab==='photos'&&<>
            <section className="panel photo-panel inspection-photos"><div className="section-title"><h2>Все фотографии <span className="count-pill appeal-count">{photos.total}</span></h2><span>Закрытые дни</span></div>
              {photos.items.length>0&&<InspectionPhotoTable photos={photos.items} openPhoto={openPhoto} focusId={photos.focus_id} workTypes={meta.work_types}/>}
              {!photos.items.length&&!dataLoading&&<p className="empty">За выбранный период нет фотографий закрытых дней.</p>}
              {photos.total>photos.page_size&&<div className="pagination"><span>Страница {photos.page} из {Math.max(1,Math.ceil(photos.total/photos.page_size))}</span><button disabled={photos.page<=1} onClick={()=>update('page',String(photos.page-1))}><ChevronLeft size={16}/>Назад</button><button disabled={photos.page*photos.page_size>=photos.total} onClick={()=>update('page',String(photos.page+1))}>Далее<ChevronRight size={16}/></button></div>}
            </section></>}
          {tab==='photo-map'&&<InspectionPhotoMap key={org} base={base} filters={filterQuery} meta={meta} revision={revision} active={!viewingPhoto} openPhoto={openPhoto} mapLink={sectionLink('photo-map')} listLink={sectionLink('photos')}/>}
        </>}
        </div>
        {viewingPhoto&&<InspectionPhotoDetail org={org} id={photoId} filters={filterQuery} fromChat={tab==='messages'} fromMap={tab==='photo-map'} onClose={closePhoto} onMove={id=>openPhoto(id,true)}/>}

      </main>
    </div></PhotoNotificationsProvider></OperatorChatsProvider>
  </AppContextProvider>;
}
