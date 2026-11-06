import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { api } from './api';
import { ErrorBox, useApp } from './App';
import DiskFolderSettings from './DiskFolderSettings';

type Cohort = 'test' | 'production';
type State = {intake_cohort: Cohort; organizing: string | null; counts: Record<Cohort, number>;
  photo_root: string; training_root: string; spam_root: string};
const organizationStatus: Record<string, string> = {DONE: 'Завершено', RUNNING: 'Выполняется', PENDING: 'В очереди', RETRY: 'Ожидает повтора'};

export default function Exchange() {
  const {notify, user, refresh} = useApp();
  const [data, setData] = useState<State | null>(null), [error, setError] = useState('');
  const [busy, setBusy] = useState(false), [switching, setSwitching] = useState(false);
  async function load() {
    setError('');
    try {setData(await api<State>('/exchange'));}
    catch (reason) {setError((reason as Error).message);}
  }
  useEffect(() => {void load();}, []);
  const next = data?.intake_cohort === 'test' ? 'production' : 'test';
  const nextMode = next === 'production' ? 'рабочий' : 'тестовый';
  async function changeMode() {
    setBusy(true); setError('');
    try {
      await api('/exchange/mode', 'PUT', {cohort: next});
      setSwitching(false); await load(); await refresh();
      notify('Режим приёма фотографий изменён');
    } catch (reason) {setError((reason as Error).message);}
    finally {setBusy(false);}
  }
  async function organize() {
    setBusy(true); setError('');
    try {
      await api('/exchange/organize', 'POST');
      await load(); notify('Обновление папок поставлено в очередь');
    } catch (reason) {setError((reason as Error).message);}
    finally {setBusy(false);}
  }
  return <>
    <header className="page-header"><h1>Фотоархив</h1>
      <button type="button" aria-label="Обновить состояние" title="Обновить состояние" disabled={busy} onClick={() => void load()}><RefreshCw size={17}/></button>
    </header>
    <ErrorBox error={error}/>
    {user.role === 'ADMIN_OPERATOR' && <DiskFolderSettings onSaved={() => void load()}/>}
    {data && <>
      <section className="panel metadata">
        <h2>Приём фотографий</h2>
        <p>Текущий режим: <strong>{data.intake_cohort === 'test' ? 'тестовый' : 'рабочий'}</strong></p>
        <p className="hint">Тестовые фото: {data.counts.test} · Рабочие фото: {data.counts.production}</p>
        {switching ? <div className="archive-mode-actions"><p>Режим изменится для новых фотографий.</p>
          <button className="primary" disabled={busy} onClick={() => void changeMode()}>Включить {nextMode} режим</button>
          <button disabled={busy} onClick={() => setSwitching(false)}>Отмена</button></div>
          : <button disabled={busy} onClick={() => setSwitching(true)}>Перейти в {nextMode} режим</button>}
      </section>
      <section className="panel metadata">
        <h2>Структура папок</h2>
        {user.role !== 'ADMIN_OPERATOR' && <dl><dt>Рабочие фотографии</dt><dd>{data.photo_root}</dd>
          <dt>Тестовые фотографии</dt><dd>{data.training_root}</dd><dt>Спам</dt><dd>{data.spam_root}</dd></dl>}
        <p className="hint">Фотографии распределяются по дате и микрорайону.</p>
        <p>{data.organizing ? organizationStatus[data.organizing] || data.organizing : 'Обновление ещё не запускалось'}</p>
        <button disabled={busy || ['RUNNING', 'PENDING'].includes(data.organizing || '')} onClick={() => void organize()}>Обновить структуру папок</button>
      </section>
    </>}
  </>;
}
