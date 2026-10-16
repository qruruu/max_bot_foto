import { useState } from 'react';
import type { FormEvent } from 'react';
import { Bell, Monitor, Palette, ShieldCheck } from 'lucide-react';
import { Navigate, NavLink, useParams } from 'react-router-dom';
import { api } from './api';
import { ErrorBox } from './App';
import ThemeSettings from './ThemeSettings';
import NotificationSettings from './NotificationSettings';
import ActiveSessions from './ActiveSessions';

const sections = [
  {id: 'appearance', name: 'Оформление', Icon: Palette},
  {id: 'notifications', name: 'Уведомления', Icon: Bell},
  {id: 'security', name: 'Безопасность', Icon: ShieldCheck},
  {id: 'sessions', name: 'Активные сеансы', Icon: Monitor},
];

function SecuritySettings() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent) {
    event.preventDefault();
    setError('');
    setBusy(true);
    try {
      await api('/auth/password', 'POST', {current_password: currentPassword, new_password: newPassword});
      window.location.reload();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return <form className="panel account-form settings-security" aria-labelledby="security-title" onSubmit={save}>
    <h2 id="security-title">Смена пароля</h2>
    <ErrorBox error={error}/>
    <label>Текущий пароль<input required type="password" autoComplete="current-password"
      value={currentPassword} onChange={event => setCurrentPassword(event.target.value)}/></label>
    <label>Новый пароль<input required minLength={12} type="password" autoComplete="new-password"
      value={newPassword} onChange={event => setNewPassword(event.target.value)}/></label>
    <p className="hint">Минимум 12 символов. После смены пароля нужно войти снова.</p>
    <button className="primary" disabled={busy}>{busy ? 'Сохранение…' : 'Изменить пароль'}</button>
  </form>;
}

export default function Settings() {
  const {section} = useParams();
  if (!sections.some(item => item.id === section)) return <Navigate to="/settings/appearance" replace/>;

  return <>
    <header className="page-header"><div>
      <span className="eyebrow">ЛИЧНЫЕ НАСТРОЙКИ</span><h1>Настройки</h1>
      <p>Настройте оформление, уведомления и безопасность аккаунта.</p>
    </div></header>
    <div className="settings-layout">
      <nav className="settings-nav" aria-label="Разделы настроек">
        {sections.map(({id, name, Icon}) => <NavLink key={id} to={`/settings/${id}`} title={name} aria-label={name}>
          <Icon size={19} aria-hidden="true"/><span>{name}</span>
        </NavLink>)}
      </nav>
      <div className="settings-content">
        {section === 'appearance' && <ThemeSettings/>}
        {section === 'notifications' && <NotificationSettings/>}
        {section === 'security' && <SecuritySettings/>}
        {section === 'sessions' && <ActiveSessions/>}
      </div>
    </div>
  </>;
}
