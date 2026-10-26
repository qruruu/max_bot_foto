import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Building2, ChevronRight, Layers, ShieldCheck } from 'lucide-react';
import { api } from './api';
import type { User } from './types';

export type LoginResult = User | {requires_organization: true; choices: {id: string; name: string}[]};

export function signInDestination(user: User) {
  return user.role === 'INSPECTOR' ? '/inspection' : user.is_platform_owner ? '/' : user.organization ? '/org/' + user.organization.id + '/' : '/';
}

export function SignInRedirect() {
  useEffect(() => {window.location.replace('/');}, []);
  return <div className="full-loading">Открываем общую страницу входа…</div>;
}

export default function Login({onLogin, unified = false, initialError = ''}: {
  onLogin: (user: User) => void; unified?: boolean; initialError?: string;
}) {
  const [login, setLogin] = useState(''), [password, setPassword] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [choices, setChoices] = useState<{id: string; name: string}[]>([]);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = await api<LoginResult>('/auth/login', 'POST', {login, password});
      if ('requires_organization' in result) {setChoices(result.choices); setPassword('');}
      else onLogin(result);
    } catch (error) {setError((error as Error).message);} finally {setBusy(false);}
  }
  async function choose(id: string) {
    setBusy(true); setError('');
    try {onLogin(await api<User>('/auth/choose-organization', 'POST', {organization_id: id}));}
    catch (error) {setError((error as Error).message);} finally {setBusy(false);}
  }
  return <main className="login-page"><div className="login-art">
    <div className="brand"><span className="brand-mark"><Layers/></span>Метка</div>
    <div><span className="eyebrow">ГОРОД ПОД КОНТРОЛЕМ</span><h1>Каждая работа.<br/>На своём месте.</h1>
      <p>Фотографии из чатов, выполненные работы и карта микрорайонов — в одном пространстве.</p></div>
    <span className="login-caption">Система учёта и контроля городских работ</span></div>
    <form className="login-form" onSubmit={submit}>
      <span className="eyebrow">{unified ? 'ЕДИНЫЙ ВХОД' : 'ОПЕРАТОРСКАЯ ПАНЕЛЬ'}</span>
      <h2>{choices.length ? 'Выберите организацию' : 'С возвращением'}</h2>
      <p className="muted">{choices.length ? 'Эти данные подходят к нескольким вашим аккаунтам. Выберите, где продолжить работу.' : 'Войдите, чтобы продолжить работу.'}</p>
      {(error || initialError) && <div className="error" role="alert">{error || initialError}</div>}
      {choices.length ? <><div className="login-organizations">{choices.map(item =>
        <button key={item.id} type="button" disabled={busy} onClick={() => choose(item.id)}><Building2 size={20}/>{item.name}<ChevronRight size={18}/></button>)}</div>
        <button type="button" disabled={busy} onClick={() => {setChoices([]); setError('');}}>Вернуться ко входу</button></> : <>
        <label>Логин<input autoFocus autoComplete="username" value={login} onChange={e => setLogin(e.target.value)} required/></label>
        <label>Пароль<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required/></label>
        <button className="primary" disabled={busy}>{busy ? 'Входим…' : 'Войти в систему'}<ChevronRight size={18}/></button>
        <p className="hint"><ShieldCheck size={16}/>{unified ? 'Откроется кабинет вашей организации, проверяющего или владельца сервиса.' : 'Доступ выдаёт администратор вашей организации.'}</p></>}
    </form></main>;
}
