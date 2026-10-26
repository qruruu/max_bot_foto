import { useEffect, useRef, useState } from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { api } from '../api';
import { AccountForm } from './Accounts';
import { OrganizationQR } from './QR';
import type { Agency, Inspector, MessagePage, Organization } from './types';
import './inspection.css';

export default function InspectionOwner({organizations}: {organizations: Organization[]}) {
  const [agencies,setAgencies]=useState<Agency[]>([]),[selected,setSelected]=useState('');
  const [accounts,setAccounts]=useState<Inspector[]>([]),[account,setAccount]=useState<Inspector|null>(null);
  const [grants,setGrants]=useState<Organization[]>([]),[messages,setMessages]=useState<MessagePage>({items:[],next_before_id:null});
  const [name,setName]=useState(''),[editing,setEditing]=useState(false),[create,setCreate]=useState(false),[active,setActive]=useState(true);
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[qrOrg,setQrOrg]=useState('');
  const [accountName,setAccountName]=useState(''),[password,setPassword]=useState('');
  const selectedRef=useRef(selected),detailGeneration=useRef(0);selectedRef.current=selected;
  async function load(){setAgencies(await api<Agency[]>('/platform/inspection/agencies'));}
  async function loadAccounts(){if(selected){const target=selected;const list=await api<Inspector[]>('/platform/inspection/agencies/'+target+'/accounts');if(selectedRef.current===target)setAccounts(list);}}
  async function details(a: Inspector) {
    const gen=++detailGeneration.current;
    setAccount(a);setAccountName(a.name);setPassword('');setGrants([]);setMessages({items:[],next_before_id:null});
    try {const [g,m]=await Promise.all([api<Organization[]>('/platform/inspection/accounts/'+a.id+'/grants'),api<MessagePage>('/platform/inspection/accounts/'+a.id+'/messages')]);if(gen===detailGeneration.current){setGrants(g);setMessages(m);}}
    catch(e){if(gen===detailGeneration.current)setError((e as Error).message);}
  }
  async function run(action:()=>Promise<void>){setBusy(true);setError('');try{await action();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  useEffect(()=>{void load().catch(e=>setError(e.message));},[]);
  useEffect(()=>{detailGeneration.current++;setAccounts([]);setAccount(null);void loadAccounts().catch(e=>setError(e.message));},[selected]);
  const agency=agencies.find(a=>a.id===selected);
  return <div className="inspection-owner"><header className="page-header"><div><span className="eyebrow">КАБИНЕТ ВЛАДЕЛЬЦА</span><h1>Проверяющие</h1><p>Проверяющие, аккаунты, доступ к организациям и переписки.</p></div>
    <div className="inspection-actions"><button onClick={()=>void run(async()=>{await load();await loadAccounts();if(account)await details(account);})} disabled={busy}><RefreshCw size={17}/>Обновить</button>
      <button className="primary" onClick={()=>{setName('');setActive(true);setCreate(true);setEditing(true);}}><Plus size={17}/>Создать проверяющих</button></div></header>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="organization-grid">{agencies.map(a=><article className="panel organization-card" key={a.id}><h2>{a.name}</h2><p>{a.active?'Работает':'Приостановлена'} · Аккаунтов: {a.accounts}</p>
      <button className={a.id===selected?'primary':''} onClick={()=>{setSelected(a.id);setEditing(false);}}>Открыть</button>
      <button onClick={()=>{setSelected(a.id);setName(a.name);setActive(a.active);setCreate(false);setEditing(true);}}>Настроить</button></article>)}</div>
    {!agencies.length && <p className="empty">Добавьте проверяющих.</p>}
    {editing && <form className="panel inspection-account-form" onSubmit={e=>{e.preventDefault();void run(async()=>{
      if(create){const a=await api<Agency>('/platform/inspection/agencies','POST',{name,active});setSelected(a.id);}
      else await api('/platform/inspection/agencies/'+selected,'PATCH',{name,active});setEditing(false);await load();});}}>
      <h2>{create?'Новые проверяющие':'Настройки проверяющих'}</h2><label>Название<input required maxLength={150} value={name} onChange={e=>setName(e.target.value)}/></label>
      <label className="checkbox"><input type="checkbox" checked={!active} onChange={e=>setActive(!e.target.checked)}/>Приостановить все аккаунты проверяющих</label>
      <button className="primary" disabled={busy}>Сохранить</button><button type="button" onClick={()=>setEditing(false)}>Отмена</button></form>}
    {agency && <section className="panel"><h2>{agency.name} · Аккаунты</h2><p className="hint">Аккаунты, созданные здесь, могут добавлять сотрудников. Их сотрудники создавать аккаунты не смогут.</p>
      <AccountForm key={selected} busy={busy} onSave={async body=>{setBusy(true);setError('');try{await api('/platform/inspection/agencies/'+selected+'/accounts','POST',body);await loadAccounts();await load();}catch(e){setError((e as Error).message);throw e;}finally{setBusy(false);}}}/>
      <div className="table-scroll"><table><thead><tr><th>Имя / логин</th><th>Создание аккаунтов</th><th>Статус</th><th/></tr></thead><tbody>{accounts.map(a=><tr key={a.id}><td>{a.name}<small>{a.login}</small></td><td>{a.can_create_accounts?'Разрешено владельцем':'Недоступно'}</td><td>{a.active?'Активен':'Приостановлен'}</td><td><button onClick={()=>void details(a)}>Управлять</button></td></tr>)}</tbody></table></div>
    </section>}
    {account && <section className="panel"><h2>{account.name}</h2><form className="inspection-account-form" onSubmit={e=>{e.preventDefault();void run(async()=>{
      const updated=await api<Inspector>('/platform/inspection/accounts/'+account.id,'PATCH',{name:accountName,...(password?{password}:{})});await loadAccounts();await details(updated);});}}>
      <label>Имя<input required maxLength={150} value={accountName} onChange={e=>setAccountName(e.target.value)}/></label>
      <label>Новый пароль<input type="password" minLength={12} maxLength={256} autoComplete="new-password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="Оставьте пустым, чтобы сохранить"/></label>
      <button disabled={busy}>Сохранить</button><button type="button" disabled={busy} onClick={()=>void run(async()=>{const updated=await api<Inspector>('/platform/inspection/accounts/'+account.id,'PATCH',{active:!account.active});await loadAccounts();await details(updated);})}>{account.active?'Приостановить аккаунт':'Возобновить аккаунт'}</button></form>
      <h3>Доступные организации</h3>{grants.map(g=><div className="inspection-grant" key={g.id}><span>{g.name}</span><button disabled={busy} onClick={()=>void run(async()=>{await api('/platform/inspection/accounts/'+account.id+'/grants/'+g.id,'DELETE');await details(account);})}>Отозвать доступ</button></div>)}{!grants.length && <p className="hint">Нет доступов. Проверяющий должен использовать QR каждой организации.</p>}
      <h3>Переписки</h3>{messages.next_before_id && <button disabled={busy} onClick={()=>void run(async()=>{const page=await api<MessagePage>('/platform/inspection/accounts/'+account.id+'/messages?before_id='+messages.next_before_id);setMessages({items:[...page.items,...messages.items],next_before_id:page.next_before_id});})}>Предыдущие сообщения</button>}
      <div className="inspection-message-list">{messages.items.map(m=><article key={m.id}><strong>{m.outgoing?account.name:m.peer_name} → {m.outgoing?m.peer_name:account.name}</strong><p>{m.body}</p><small>{new Date(m.created_at).toLocaleString('ru-RU')}</small></article>)}</div>
      {!messages.items.length && <p className="hint">Сообщений пока нет.</p>}
    </section>}
    <section className="panel"><h2>QR организации</h2><label>Организация<select value={qrOrg} onChange={e=>setQrOrg(e.target.value)}><option value="">Выберите организацию</option>{organizations.map(o=><option value={o.id} key={o.id}>{o.name}</option>)}</select></label>
      {qrOrg && <OrganizationQR key={qrOrg} endpoint={'/platform/inspection/organizations/'+qrOrg+'/qr'}/>}</section>
  </div>;
}
