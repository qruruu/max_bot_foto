import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { ImagePlus, Trash2 } from 'lucide-react';
import { api } from './api';
import type { User } from './types';
import { ErrorBox, useApp } from './App';
import Avatar from './Avatar';

const maxFileBytes = 5 * 1024 * 1024;

export default function ProfileSettings({authBase = '/auth'}: {authBase?: string}) {
  const {user, updateUser, notify} = useApp();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');

  useEffect(() => {
    if (!file) {setPreview(null); return;}
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function choose(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0];
    if (!selected) return;
    setError('');
    if (selected.size > maxFileBytes) {
      setError('Размер фотографии должен быть не больше 5 МБ.');
      event.target.value = '';
      return;
    }
    setFile(selected);
  }

  function clearSelection() {
    setFile(null);
    if (input.current) input.current.value = '';
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true); setError('');
    try {
      updateUser(await api<User>(authBase + '/avatar', 'PUT', file));
      clearSelection();
      notify('Аватарка сохранена');
    } catch (error) {setError((error as Error).message);}
    finally {setBusy(false);}
  }

  async function remove() {
    setBusy(true); setError('');
    try {
      updateUser(await api<User>(authBase + '/avatar', 'DELETE'));
      clearSelection();
      notify('Аватарка удалена');
    } catch (error) {setError((error as Error).message);}
    finally {setBusy(false);}
  }

  return <form className="panel profile-settings" aria-labelledby="profile-title" onSubmit={save}>
    <h2 id="profile-title">Профиль</h2>
    <ErrorBox error={error}/>
    <div className="profile-identity">
      <Avatar name={user.name} src={preview || user.avatar_url} className="profile-avatar"/>
      <div><strong>{user.name}</strong><span>{user.login}</span></div>
    </div>
    <h3>Аватарка</h3>
    <p className="hint">Выберите фотографию для профиля. Она появится рядом с вашим именем в боковой панели.</p>
    <input ref={input} type="file" accept="image/jpeg,image/png,image/webp,image/gif" aria-label="Выберите аватарку" hidden disabled={busy} onChange={choose}/>
    <div className="profile-avatar-actions">
      <button type="button" disabled={busy} onClick={() => input.current?.click()}><ImagePlus size={16}/>{user.avatar_url ? 'Заменить фото' : 'Выбрать фото'}</button>
      {user.avatar_url && <button type="button" disabled={busy} onClick={remove}><Trash2 size={16}/>Удалить аватарку</button>}
    </div>
    <p className="hint profile-avatar-hint">JPG, PNG, WEBP или GIF, до 5 МБ. Изображение будет обрезано по центру до квадрата.</p>
    {file && <div className="profile-avatar-selection">
      <p className="hint">Выбрано: {file.name}</p>
      <div className="profile-avatar-actions">
        <button className="primary" disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить аватарку'}</button>
        <button type="button" disabled={busy} onClick={clearSelection}>Отменить</button>
      </div>
    </div>}
  </form>;
}
