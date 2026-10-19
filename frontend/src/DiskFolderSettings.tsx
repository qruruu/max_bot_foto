import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Folder, RefreshCw } from 'lucide-react';
import { api } from './api';
import { ErrorBox, useApp } from './App';
import { companyFolders } from './diskFolders';
import type { DiskFolderSettings as FolderSettings } from './diskFolders';
import './disk-folders.css';

export default function DiskFolderSettings({onSaved}: {onSaved: () => void}) {
  const {notify} = useApp();
  const [data,setData] = useState<FolderSettings|null>(null), [name,setName] = useState('');
  const [error,setError] = useState(''), [busy,setBusy] = useState(false), [revision,setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    api<FolderSettings>('/storage-folders','GET',undefined,controller.signal).then(value => {
      if (!controller.signal.aborted) {setData(value);setName(value.photo_root);}
    }).catch(e => {if (!controller.signal.aborted) setError(e.message);});
    return () => controller.abort();
  }, [revision]);
  const changed = data && name.trim() !== data.photo_root;
  const preview = changed ? companyFolders(name) : data;
  async function save(event: FormEvent) {
    event.preventDefault(); if (!data || busy || !changed) return;
    setBusy(true); setError('');
    try {
      const value = await api<FolderSettings>('/storage-folders','PUT',{photo_root:name.trim(),version:data.version});
      setData(value);setName(value.photo_root);onSaved();
      notify('Папки компании сохранены. Новые загрузки будут использовать эти названия.');
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <section className="panel disk-folder-settings" aria-labelledby="disk-folders-title">
    <div className="section-title"><h2 id="disk-folders-title"><Folder size={19} aria-hidden="true"/>Папки компании на Яндекс.Диске</h2>
      <button type="button" disabled={busy} onClick={() => setRevision(value => value+1)} aria-label="Обновить настройки папок"><RefreshCw size={16}/></button></div>
    <p className="hint">Общая настройка для этой компании. Изменять названия может только администратор.</p>
    <ErrorBox error={error}/>
    {!data ? !error && <p className="loading">Загружаем настройки папок…</p> : <form onSubmit={save}>
      <label>Название основной папки<input required maxLength={100} disabled={busy} value={name} onChange={event => setName(event.target.value)} placeholder="Например, MAX_ФОТО_СТРОЙДВОР" aria-describedby="disk-folder-name-help"/></label>
      <p className="hint" id="disk-folder-name-help">Укажите отдельное название для каждой компании. Остальные папки получат то же название с дополнением.</p>
      {preview && <dl className="disk-folder-preview">
        <div><dt>Рабочие фотографии</dt><dd>{preview.photo_root||'—'}</dd></div>
        <div><dt>Тестовые и учебные фото</dt><dd>{preview.training_root}</dd></div>
        <div><dt>Спам</dt><dd>{preview.spam_root}</dd></div>
        <div><dt>Обмен с АРМ</dt><dd>{preview.exchange_root}</dd></div>
      </dl>}
      <p className="hint disk-folder-scope">После сохранения новые загрузки пойдут в указанные папки. Уже сохранённые фотографии останутся в прежнем архиве и будут открываться по прежним ссылкам. Их исправление и перенос в спам продолжат использовать папки того архива. Если АРМ читает JSON, обновите в ней путь к новой папке обмена.</p>
      <button className="primary" type="submit" disabled={busy||!changed||!name.trim()}>{busy?'Проверяем и создаём папки…':'Сохранить названия папок'}</button>
    </form>}
  </section>;
}
