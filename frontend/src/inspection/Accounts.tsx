import UserPresence, { usePresenceRefresh } from '../UserPresence';
import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Inspector } from './types';

export type AccountDraft = {name: string; login: string; password: string};
export function AccountForm({onSave,busy}: {onSave: (draft: AccountDraft) => Promise<void>; busy: boolean}) {
  const [name,setName]=useState(''),[login,setLogin]=useState(''),[password,setPassword]=useState('');
  return <form className="inspection-account-form" onSubmit={async e=>{e.preventDefault();try{await onSave({name,login,password});setName('');setLogin('');setPassword('');}catch{/* Error is shown by the parent. */}}}>
    <label>Имя<input required maxLength={150} value={name} onChange={e=>setName(e.target.value)}/></label>
    <label>Логин<input required minLength={3} maxLength={100} pattern="[A-Za-z0-9_.@\-]+" autoComplete="off" value={login} onChange={e=>setLogin(e.target.value)}/></label>
    <label>Пароль<input required type="password" minLength={12} maxLength={256} autoComplete="new-password" value={password} onChange={e=>setPassword(e.target.value)}/></label>
    <button className="primary" disabled={busy}>{busy?'Сохраняем…':'Создать аккаунт'}</button>
  </form>;
}

export default function InspectionAccounts() {
  const [items,setItems]=useState<Inspector[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function load(){setItems(await api<Inspector[]>('/inspection/accounts'));}
  useEffect(()=>{void load().catch(e=>setError(e.message));},[]);
  usePresenceRefresh(!busy, load);
  return <section className="panel"><h2>Создать аккаунт</h2><p className="hint">Новый сотрудник получит доступ к вашим подключённым организациям. Для остальных организаций нужен QR.</p>
    {error && <p className="error" role="alert">{error}</p>}
    <AccountForm busy={busy} onSave={async body=>{setBusy(true);setError('');try{await api('/inspection/accounts','POST',body);await load();}catch(e){setError((e as Error).message);throw e;}finally{setBusy(false);}}}/>
    {items.length ? <div className="table-scroll"><table><thead><tr><th>Имя</th><th>Логин</th><th>Доступ</th></tr></thead><tbody>{items.map(a=><tr key={a.id}><td>{a.name}<UserPresence lastSeen={a.last_seen_at} active={a.active}/></td><td>{a.login}</td><td>{a.active?'Активен':'Приостановлен'}</td></tr>)}</tbody></table></div> : <p className="hint">Аккаунтов пока нет.</p>}
  </section>;
}
