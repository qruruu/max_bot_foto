import { useState } from 'react';
import type { FormEvent } from 'react';
import { ExternalLink, X } from 'lucide-react';
import { api } from './api';

export type DiskAccount = {id: string; name: string; login: string};
export type DiskAccounts = {default_configured: boolean; items: DiskAccount[]};

export default function ConnectDisk({onClose, onConnected}: {onClose: () => void; onConnected: (account: DiskAccount) => void}) {
  const [name, setName] = useState(''), [token, setToken] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {const account = await api<DiskAccount>('/platform/disk-accounts', 'POST', {name, token}); setToken(''); onConnected(account);}
    catch (error) {setError((error as Error).message);} finally {setBusy(false);}
  }
  return <div className="modal-backdrop disk-connect-backdrop"><form className="modal organization-modal" onSubmit={submit}>
    <div className="section-title"><h2>Подключить Яндекс.Диск</h2><button type="button" disabled={busy} aria-label="Закрыть подключение диска" onClick={onClose}><X size={18}/></button></div>
    {error && <div className="error" role="alert">{error}</div>}
    <label>Название диска<input autoFocus required maxLength={150} placeholder="Например: Мой архив организаций" value={name} onChange={event => setName(event.target.value)}/></label>
    <label>Токен Яндекс.Диска<input type="password" required autoComplete="off" minLength={10} maxLength={4096} value={token} onChange={event => setToken(event.target.value)}/></label>
    <p className="hint">Нужен доступ к чтению и записи файлов. Программа проверит аккаунт перед сохранением.</p>
    <a className="text-button" href="https://yandex.ru/dev/disk/rest/" target="_blank" rel="noreferrer">Получение токена в Яндексе<ExternalLink size={15}/></a>
    <p className="hint">Один подключённый диск можно выбрать для нескольких организаций. Их фотографии будут храниться в отдельных папках.</p>
    <button className="primary" disabled={busy}>{busy ? 'Проверяем подключение…' : 'Подключить диск'}</button>
  </form></div>;
}
