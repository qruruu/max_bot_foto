import {useEffect, useState} from 'react';
import type {FormEvent} from 'react';
import {api} from './api';
import {ErrorBox, useApp} from './App';

type Key = {id:string; name:string; cohort:string; scopes:string[]; expires_at:string; revoked_at:string|null; last_used_at:string|null};
const permissions = [
  ['photos:read', 'Фотографии'], ['geozones:read', 'Геозоны (микрорайоны)'],
  ['changes:read', 'Изменения и удаления'], ['originals:read', 'Скачивание оригиналов'],
];
export default function IntegrationKeys() {
  const {meta} = useApp();
  const [keys,setKeys] = useState<Key[]>([]), [name,setName] = useState(''), [days,setDays] = useState(90);
  const [scopes,setScopes] = useState(['photos:read','geozones:read','changes:read']);
  const [secret,setSecret] = useState(''), [error,setError] = useState(''), [busy,setBusy] = useState(false);
  async function load() {setKeys((await api<{items:Key[]}>('/integration-keys')).items);}
  useEffect(()=>{load().catch(e=>setError(e.message));},[]);
  async function action(task:()=>Promise<void>) {
    setBusy(true); setError('');
    try {await task(); await load();} catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function create(event:FormEvent) {
    event.preventDefault();
    await action(async()=>{
      const result = await api<{key:string}>('/integration-keys','POST',{name,scopes,expires_days:days});
      setSecret(result.key);setName('');
    });
  }
  const stamp = (value:string|null) => value ? new Date(value).toLocaleString('ru-RU') : 'Ещё не использовался';
  return <>
    <header className="page-header"><div><span className="eyebrow">ИНТЕГРАЦИИ</span><h1>API-ключи</h1>
      <p>Доступ приложений только к чтению данных организации «{meta.organization?.name}».</p></div></header>
    <ErrorBox error={error}/>
    {secret && <section className="panel" aria-label="Новый API-ключ"><h2>Сохраните ключ</h2>
      <p>Полное значение показывается один раз. Сохраните его в защищённых настройках приложения.</p>
      <label>API-ключ<textarea readOnly rows={3} value={secret} spellCheck={false}/></label>
      <button onClick={()=>navigator.clipboard.writeText(secret).catch(()=>setError('Не удалось скопировать. Выделите ключ и скопируйте вручную.'))}>Скопировать</button>{' '}
      <button onClick={()=>setSecret('')}>Ключ сохранён — скрыть</button></section>}
    <form className="panel account-form" onSubmit={create}><h2>Подключить приложение</h2>
      <label>Название приложения<input value={name} onChange={e=>setName(e.target.value)} required maxLength={100} placeholder="Например, отчёты компании"/></label>
      <label>Срок действия, дней<input type="number" min={1} max={365} required value={days} onChange={e=>setDays(Number(e.target.value))}/></label>
      <fieldset><legend>Разрешить чтение</legend>{permissions.map(([code,label])=><label className="checkbox" key={code}>
        <input type="checkbox" checked={scopes.includes(code)} onChange={e=>setScopes(current=>e.target.checked?[...current,code]:current.filter(s=>s!==code))}/>{label}</label>)}</fieldset>
      <p className="hint">Ключ закрепляется за текущим режимом: {meta.intake_cohort==='production'?'рабочие':'учебные'} фотографии. Ключ не позволяет изменять данные.</p>
      <button className="primary" disabled={busy||!scopes.length||!!secret}>Создать ключ</button>
    </form>
    <section className="panel"><h2>Подключённые приложения</h2>{!keys.length&&<p>Ключей пока нет.</p>}
      {keys.map(key=><article className="panel" key={key.id}><h3>{key.name}</h3>
        <p>{key.revoked_at?'Отозван':new Date(key.expires_at)<=new Date()?'Истёк':'Действует'} · {key.cohort==='production'?'Рабочие':'Учебные'} фото</p>
        <p>Права: {key.scopes.map(scope=>permissions.find(([code])=>code===scope)?.[1]||scope).join(', ')}</p>
        <p>Истекает: {stamp(key.expires_at)}. Последнее использование: {stamp(key.last_used_at)}.</p>
        {!key.revoked_at&&<><button disabled={busy||!!secret} onClick={()=>action(async()=>{
          const result=await api<{key:string}>(`/integration-keys/${key.id}/rotate`,'POST');setSecret(result.key);
        })}>Заменить ключ (старый отключится)</button>{' '}<button disabled={busy} onClick={()=>action(async()=>{await api(`/integration-keys/${key.id}`,'DELETE');})}>Отозвать</button></>}
      </article>)}
    </section>
  </>;
}
