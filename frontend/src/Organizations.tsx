import { lazy, Suspense, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowUpRight, Building2, Camera, Layers, LogOut, MessageSquare, Moon, Newspaper, Plus, RefreshCw, Settings2, ShieldCheck, Sun, Users, X } from 'lucide-react';
import { api } from './api';
import { ErrorBox } from './App';
import Login, { signInDestination } from './Login';
import ConnectDisk from './ConnectDisk';
import type { DiskAccounts, DiskAccount } from './ConnectDisk';
import type { User } from './types';
import { useTheme } from './theme';
import './organizations.css';
const NewsAdmin = lazy(() => import('./NewsAdmin'));
const OwnerAppeals = lazy(() => import('./appeals/OwnerAppeals'));

export type Organization = {
  id: string; name: string; city?: string | null; slug: string; status: 'ACTIVE' | 'PAUSED' | 'PROVISIONING' | 'ERROR' | 'IMPORTING';
  url: string; legacy: boolean; last_error: string | null; unavailable?: boolean;
  disk_account_id?: string | null;
  stats: {photos: number; operators: number; chats: number; work_types: number; model_ready: boolean; intake_cohort?: 'test' | 'production'} | null;
};
type Chat = {max_chat_id: string; name: string | null; organization_id: string | null; message_preview: string | null; waiting: number};
const statusNames = {ACTIVE: 'Работает', PAUSED: 'Приостановлена', PROVISIONING: 'Подготавливается', ERROR: 'Не удалось создать', IMPORTING: 'Перенос данных'};

export function OrganizationCard({item, edit, retry}: {item: Organization; edit: () => void; retry: () => void}) {
  const ready = item.status === 'ACTIVE' || item.status === 'PAUSED';
  return <article className="panel organization-card">
    <div className="organization-card-heading"><span className="organization-icon"><Building2 size={25}/></span>
      <span className={'badge ' + (item.status === 'ACTIVE' ? 'status-ACCEPTED' : 'status-NEEDS_REVIEW')}>{statusNames[item.status]}</span></div>
    <h2>{item.name}</h2>
    <p className="hint">{item.city || 'Укажите город в настройках, чтобы принимать обращения жителей.'}</p>
    {item.stats && <p className={'organization-mode ' + (item.stats.intake_cohort === 'production' ? 'production' : 'test')}>
      <span className="dot"/>{item.stats.intake_cohort === 'production' ? 'Рабочий режим' : 'Тестовый режим'}</p>}
    {item.stats ? <div className="organization-stats">
      <span><Camera size={17}/><strong>{item.stats.photos}</strong>фотографий</span>
      <span><Users size={17}/><strong>{item.stats.operators}</strong>операторов</span>
      <span><MessageSquare size={17}/><strong>{item.stats.chats}</strong>чатов MAX</span>
    </div> : <p className="hint">{item.unavailable ? 'Рабочее пространство временно недоступно.' : 'Готовим отдельное рабочее пространство.'}</p>}
    <p className="organization-model"><Layers size={16}/>{item.stats?.model_ready ? 'Своя обученная модель' : 'Модель видов работ ещё не обучена'}</p>
    {item.status === 'ERROR' && <p className="warning-text">Подготовка не завершилась. Данные других организаций сохранены. Можно повторить попытку.</p>}
    <div className="organization-actions">{ready ? <><a className="button primary" href={item.url}>Открыть<ArrowUpRight size={16}/></a>
      <button onClick={edit}><Settings2 size={16}/>Настроить</button></> : item.status === 'IMPORTING' ? <p className="hint">Завершите перенос перед открытием организации.</p> : <button onClick={retry}><RefreshCw size={16}/>Повторить подготовку</button>}</div>
  </article>;
}

export default function Organizations() {
  const [user, setUser] = useState<User | null>(null), [loading, setLoading] = useState(true);
  const [items, setItems] = useState<Organization[]>([]), [chats, setChats] = useState<Chat[]>([]);
  const [newsEditing,setNewsEditing]=useState(false);
  const [tab, setTab] = useState<'organizations' | 'chats' | 'news' | 'appeals'>(() => {
    const section = new URLSearchParams(window.location.search).get('section');
    return section === 'news' || section === 'appeals' ? section : 'organizations';
  });
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Organization | 'new' | null>(null);
  const [name, setName] = useState(''), [paused, setPaused] = useState(false);
  const [city, setCity] = useState('');
  const [disks, setDisks] = useState<DiskAccounts>({default_configured:false, items:[]});
  const [diskId, setDiskId] = useState(''), [connectingDisk, setConnectingDisk] = useState(false);
  const [binding, setBinding] = useState(false), [chatId, setChatId] = useState(''), [chatName, setChatName] = useState(''), [organizationId, setOrganizationId] = useState('');
  const {theme, setTheme} = useTheme();
  function signedIn(user: User) {
    if (user.is_platform_owner) setUser(user);
    else window.location.replace(signInDestination(user));
  }

  async function load() {
    const [organizations, groups, accounts] = await Promise.all([api<Organization[]>('/platform/organizations'), api<Chat[]>('/platform/chats'), api<DiskAccounts>('/platform/disk-accounts')]);
    setItems(organizations); setChats(groups); setDisks(accounts);
  }
  useEffect(() => {
    api<{user: User | null}>('/auth/entry').then(result => {if (result.user) signedIn(result.user);})
      .catch(e => {if (e.status !== 401) setError(e.message);}).finally(() => setLoading(false));
    const expired = () => {setUser(null); setItems([]); setChats([]);};
    window.addEventListener('session-expired', expired);
    return () => window.removeEventListener('session-expired', expired);
  }, []);
  useEffect(() => {if (user) void load().catch(e => setError(e.message));}, [user]);
  const ready = items.filter(item => ['ACTIVE', 'PAUSED'].includes(item.status));
  function open(item: Organization | 'new') {
    setError(''); setEditing(item); setName(item === 'new' ? '' : item.name);
    setCity(item === 'new' ? '' : item.city || '');
    setPaused(item !== 'new' && item.status === 'PAUSED');
    setDiskId(item === 'new' ? '' : item.disk_account_id || '');
  }
  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    let autoPaused = false;
    try {
      if (editing !== 'new' && editing && editing.status === 'ACTIVE' && (editing.disk_account_id || '') !== diskId && editing.stats?.photos === 0) {
        await api('/platform/organizations/' + editing.id, 'PATCH', {name: editing.name, status:'PAUSED'});
        autoPaused = true;
      }
      const saved = editing === 'new' ? await api<Organization>('/platform/organizations', 'POST', {name, city, disk_account_id: diskId || null}) :
        await api<Organization>('/platform/organizations/' + (editing as Organization).id, 'PATCH', {name, city, status: paused ? 'PAUSED' : 'ACTIVE', disk_account_id: diskId || null});
      setEditing(null); setTab('organizations'); await load();
      setNotice(saved.status === 'ERROR' ? 'Организация сохранена, но подготовку нужно повторить.' : editing === 'new' ? 'Организация создана. Откройте её, добавьте виды работ, микрорайоны и операторов. Чаты закрепляются в общем разделе «Чаты MAX».' : 'Настройки сохранены.');
    } catch (e) {
      if (autoPaused && editing && editing !== 'new') {
        setEditing({...editing, status:'PAUSED'}); setPaused(true);
        void load().catch(() => {});
      }
      setError((e as Error).message + (autoPaused ? ' Организация пока приостановлена. Исправьте настройку и сохраните снова.' : ''));
    } finally {setBusy(false);}
  }
  async function connectedDisk(account: DiskAccount) {
    setConnectingDisk(false); setDiskId(account.id);
    try {setDisks(await api<DiskAccounts>('/platform/disk-accounts'));}
    catch (error) {setError((error as Error).message);}
  }
  async function retry(id: string) {
    setBusy(true); setError('');
    try {await api('/platform/organizations/' + id + '/retry', 'POST'); await load();}
    catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  function openBinding(chat?: Chat) {
    setError(''); setBinding(true); setChatId(chat?.max_chat_id || '');
    setChatName(chat?.name || ''); setOrganizationId(chat?.organization_id || ready[0]?.id || '');
  }
  async function assign(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await api('/platform/organizations/' + organizationId + '/chats', 'POST', {max_chat_id: chatId, name: chatName});
      setBinding(false); await load(); setNotice('Чат закреплён. Новые фотографии будут попадать только в выбранную организацию.');
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  if (loading) return <div className="full-loading">Открываем кабинет владельца…</div>;
  if (!user) return <Login onLogin={signedIn} unified initialError={error}/>;

  return <main className="organizations-page">
    <header className="organizations-topbar"><a href="/" className="brand"><span className="brand-mark"><Layers size={25}/></span>MAX Фото</a>
      <div><span className="owner-account"><ShieldCheck size={17}/>{user.name}<small>Владелец сервиса</small></span>
        <button aria-label="Сменить оформление" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? <Sun size={18}/> : <Moon size={18}/>}</button>
        <button aria-label="Выйти" onClick={async () => {try {await api('/auth/logout', 'POST'); setUser(null);} catch(e) {setError((e as Error).message);}}}><LogOut size={18}/></button></div></header>
    {tab !== 'news' && tab !== 'appeals' && <header className="page-header"><div><span className="eyebrow">КАБИНЕТ ВЛАДЕЛЬЦА</span><h1>Организации</h1>
      <p>Отдельные фотографии, операторы, чаты и обучение для каждой компании.</p></div>
      <button className="primary" disabled={busy} onClick={() => open('new')}><Plus size={18}/>Создать организацию</button></header>}
    <nav className="organization-tabs" aria-label="Управление организациями">
      <button className={tab === 'organizations' ? 'selected' : ''} disabled={newsEditing} onClick={() => setTab('organizations')}><Building2 size={18}/>Организации <span>{items.length}</span></button>
      <button className={tab === 'chats' ? 'selected' : ''} disabled={newsEditing} onClick={() => setTab('chats')}><MessageSquare size={18}/>Чаты MAX{chats.some(c => !c.organization_id) && <span className="count-pill">{chats.filter(c => !c.organization_id).length} новых</span>}</button>
      <button className={tab === 'news' ? 'selected' : ''} onClick={() => setTab('news')}><Newspaper size={18}/>Новости</button>
      <button className={tab === 'appeals' ? 'selected' : ''} disabled={newsEditing} onClick={() => setTab('appeals')}><Camera size={18}/>Обращения граждан</button>
      <button className="organization-refresh" disabled={busy} aria-label="Обновить" onClick={() => load().catch(e => setError(e.message))}><RefreshCw size={17}/></button>
    </nav>
    {!editing && !binding && <ErrorBox error={error}/>}
    {notice && <p className="organization-notice" role="status">{notice}</p>}
    {tab === 'appeals' ? <Suspense fallback={<p className="loading">Открываем обращения…</p>}><OwnerAppeals/></Suspense> : tab === 'news' ? <Suspense fallback={<p className="loading">Открываем редактор…</p>}><NewsAdmin onEditingChange={setNewsEditing}/></Suspense> : tab === 'organizations' ? <div className="organization-grid">{items.map(item => <OrganizationCard key={item.id} item={item} edit={() => open(item)} retry={() => void retry(item.id)}/>)}</div> : <section className="panel organization-chats">
      <div className="section-title"><div><h2>Один бот — разные организации</h2><p className="hint">Закрепите каждый чат за своей компанией. Нераспределённые вложения ожидают назначения и ещё не обрабатываются.</p></div>
        <button disabled={!ready.length} onClick={() => openBinding()}><Plus size={17}/>Добавить чат по ID</button></div>
      <div className="table-scroll"><table><thead><tr><th>Чат</th><th>Организация</th><th>Ожидают доставки</th><th/></tr></thead><tbody>{chats.map(chat => {
        const organization = items.find(item => item.id === chat.organization_id);
        return <tr key={chat.max_chat_id}><td><strong>{chat.name || 'Новый чат'}</strong><small className="mono">{chat.max_chat_id}</small>{!organization && <small>{chat.message_preview}</small>}</td>
          <td>{organization?.name || <span className="warning-text">Не назначена</span>}</td><td>{chat.waiting}</td>
          <td>{organization ? <a className="button" href={organization.url + 'chats'}>Открыть настройки<ArrowUpRight size={15}/></a> : <button disabled={!ready.length} onClick={() => openBinding(chat)}>Назначить организацию</button>}</td></tr>;
      })}</tbody></table></div>{!chats.length && <p className="empty">Добавьте чат по ID или отправьте сообщение в группу с общим ботом MAX.</p>}</section>}
    {editing && <div className="modal-backdrop"><form className="modal organization-modal" onSubmit={save}>
      <div className="section-title"><h2>{editing === 'new' ? 'Новая организация' : 'Настройки организации'}</h2><button type="button" aria-label="Закрыть" disabled={busy} onClick={() => setEditing(null)}><X size={18}/></button></div>
      <ErrorBox error={error}/><label>Название<input autoFocus required maxLength={150} value={name} onChange={e => setName(e.target.value)}/></label>
      <label>Город<input required minLength={2} maxLength={150} autoComplete="address-level2" placeholder="Например, Сургут" value={city} onChange={e => setCity(e.target.value)}/></label>
      <p className="hint">Жители смогут выбрать только этот город и виды работ, добавленные внутри организации. Активные микрорайоны будут показаны на публичной карте.</p>
      {editing === 'new' ? <p className="hint">Фотографии, операторы и обучение начнутся с нуля. Виды работ и микрорайоны вы добавите внутри организации.</p> : <>
        <label className="checkbox"><input type="checkbox" checked={paused} onChange={e => setPaused(e.target.checked)}/>Приостановить работу организации</label>
        <p className="hint">Приостановка отключает вход операторов и обработку. Входящие вложения сохраняются в очереди до возобновления. Владелец сохраняет доступ к настройкам.</p></>}
      <label>Яндекс.Диск<select value={diskId} onChange={event => setDiskId(event.target.value)}>
        <option value="">Основной диск{disks.default_configured ? '' : ' — не подключён'}</option>
        {disks.items.map(disk => <option key={disk.id} value={disk.id}>{disk.name} · {disk.login}</option>)}
      </select></label>
      <button type="button" className="text-button" disabled={busy} onClick={() => setConnectingDisk(true)}><Plus size={16}/>Подключить Яндекс.Диск</button>
      <p className="hint">Этот диск можно использовать и для других организаций. Папки компаний останутся отдельными.</p>
      {editing !== 'new' && (editing.stats?.photos || 0) > 0 && <p className="hint">Для смены аккаунта с уже сохранёнными фото нужен перенос оригиналов. Текущий аккаунт можно переподключить.</p>}
      <button className="primary" disabled={busy}>{busy ? 'Подготавливаем…' : editing === 'new' ? 'Создать организацию' : 'Сохранить'}</button>
    </form></div>}
    {connectingDisk && <ConnectDisk onClose={() => setConnectingDisk(false)} onConnected={account => void connectedDisk(account)}/>}
    {binding && <div className="modal-backdrop"><form className="modal organization-modal" onSubmit={assign}>
      <div className="section-title"><h2>Закрепить чат</h2><button type="button" aria-label="Закрыть" disabled={busy} onClick={() => setBinding(false)}><X size={18}/></button></div>
      <ErrorBox error={error}/><label>Название чата<input autoFocus required maxLength={150} value={chatName} onChange={e => setChatName(e.target.value)}/></label>
      <label>MAX chat ID<input required pattern="-?[0-9]+" value={chatId} onChange={e => setChatId(e.target.value)}/></label>
      <label>Организация<select required value={organizationId} onChange={e => setOrganizationId(e.target.value)}>{ready.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <p className="hint">Фотографии этого чата будут доступны только выбранной компании. Перемещение чата вместе с историей выполняется отдельно.</p>
      <button className="primary" disabled={busy}>{busy ? 'Сохраняем…' : 'Закрепить чат'}</button>
    </form></div>}
  </main>;
}
