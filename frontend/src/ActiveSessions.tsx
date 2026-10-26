import { useEffect, useState } from 'react';
import { HelpCircle, Monitor, RefreshCw, Smartphone, Tablet, X } from 'lucide-react';
import { api, ApiError } from './api';
import { ErrorBox, useApp } from './App';

type Session = {
  id: string; current: boolean; device: string; device_type: string; browser: string; os: string | null;
  ip_address: string | null; created_at: string | null; last_seen_at: string | null; expires_at: string;
};
type Sessions = {items: Session[]; session_hours: number};
type Confirmation = {kind: 'one'; session: Session} | {kind: 'others'};

export default function ActiveSessions({authBase = '/auth'}: {authBase?: string}) {
  const {meta, notify} = useApp();
  const [data, setData] = useState<Sessions | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let stopped = false;
    let active: AbortController | null = null;
    setLoading(true);
    async function load() {
      if (active) return;
      const controller = new AbortController();
      active = controller;
      const timeout = window.setTimeout(() => controller.abort(), 10_000);
      try {
        const response = await api<Sessions>(authBase + '/sessions', 'GET', undefined, controller.signal);
        if (!stopped) { setData(response); setError(''); }
      } catch (error) {
        if (!stopped) setError(controller.signal.aborted ? 'Не удалось обновить сеансы. Повторите попытку.' : (error as Error).message);
      } finally {
        window.clearTimeout(timeout);
        active = null;
        if (!stopped) setLoading(false);
      }
    }
    const check = () => { void load(); };
    const timer = window.setInterval(check, 30_000);
    window.addEventListener('focus', check);
    window.addEventListener('online', check);
    check();
    return () => {
      stopped = true;
      window.clearInterval(timer);
      active?.abort();
      window.removeEventListener('focus', check);
      window.removeEventListener('online', check);
    };
  }, [revision, authBase]);

  function date(value: string | null) {
    return value ? new Date(value).toLocaleString('ru-RU', {timeZone: meta.timezone, day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : 'Не сохранено';
  }

  function row(session: Session) {
    const Icon = session.device_type === 'phone' ? Smartphone : session.device_type === 'tablet' ? Tablet : session.device_type === 'unknown' ? HelpCircle : Monitor;
    return <div className="session-row" key={session.id}>
      <span className="session-device-icon" aria-hidden="true"><Icon size={23}/></span>
      <div className="session-details">
        <div className="session-device-name"><strong>{session.device}</strong>{session.current && <span className="badge status-ACCEPTED">Текущий сеанс</span>}</div>
        <p>{session.browser}{session.os ? ` · ${session.os}` : ''}</p>
        <p className="session-address">{session.ip_address ? `IP: ${session.ip_address}` : 'IP-адрес не сохранён'}</p>
        <p className="hint">Последняя активность: {date(session.last_seen_at)}</p>
        <p className="hint">Вход: {date(session.created_at)}</p>
      </div>
      {!session.current && <button type="button" className="session-revoke session-action" disabled={busy} onClick={() => { setError(''); setConfirmation({kind: 'one', session}); }}>Завершить сеанс</button>}
    </div>;
  }

  async function revoke() {
    if (!confirmation || busy) return;
    setBusy(true);
    setError('');
    try {
      if (confirmation.kind === 'others') {
        const response = await api<{revoked: number}>(authBase + '/sessions/revoke-others', 'POST');
        notify(response.revoked ? 'Другие сеансы завершены' : 'Других активных сеансов нет');
      } else {
        await api(`${authBase}/sessions/${confirmation.session.id}`, 'DELETE');
        notify('Сеанс завершён');
      }
      setConfirmation(null);
      setRevision(value => value + 1);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setConfirmation(null);
        setRevision(value => value + 1);
        notify('Этот сеанс уже завершён');
      } else setError((error as Error).message);
    } finally { setBusy(false); }
  }

  const current = data?.items.find(session => session.current);
  const others = data?.items.filter(session => !session.current) || [];
  return <div className="active-sessions">
    <div className="section-title"><h2>Активные сеансы</h2><button type="button" aria-label="Обновить сеансы" disabled={loading || busy} onClick={() => setRevision(value => value + 1)}><RefreshCw size={17}/></button></div>
    {!confirmation && <ErrorBox error={error}/>}
    {!data && loading && <p className="loading">Загружаем сеансы…</p>}
    {data && <>
      {current && <><h3 className="sessions-label">Это устройство</h3><section className="panel session-panel">
        {row(current)}
        <button type="button" className="session-revoke revoke-other-sessions" disabled={!others.length || busy} onClick={() => { setError(''); setConfirmation({kind: 'others'}); }}>Завершить все другие сеансы</button>
        <p className="hint">Вы останетесь в системе на этом устройстве.</p>
      </section></>}
      <h3 className="sessions-label">Другие устройства{others.length ? ` · ${others.length}` : ''}</h3>
      <section className="panel session-panel">{others.length ? others.map(row) : <p className="muted">Других активных сеансов нет.</p>}</section>
      <p className="hint sessions-footnote">Сеанс автоматически завершается через {data.session_hours} ч после входа. Время указано для {meta.timezone}.</p>
    </>}
    {confirmation && <div className="modal-backdrop"><section className="modal session-confirmation" role="dialog" aria-modal="true" aria-labelledby="revoke-session-title">
      <div className="section-title"><h2 id="revoke-session-title">{confirmation.kind === 'others' ? 'Завершить другие сеансы?' : 'Завершить этот сеанс?'}</h2><button type="button" aria-label="Закрыть подтверждение завершения сеанса" disabled={busy} onClick={() => setConfirmation(null)}><X size={18}/></button></div>
      <p>{confirmation.kind === 'others' ? 'На других устройствах потребуется войти заново. Текущий сеанс сохранится.' : `${confirmation.session.device} · ${confirmation.session.browser}. Для доступа с этого устройства потребуется войти заново.`}</p>
      <ErrorBox error={error}/>
      <div className="session-confirmation-actions"><button type="button" disabled={busy} onClick={() => setConfirmation(null)}>Отмена</button><button type="button" className="session-revoke" disabled={busy} onClick={() => void revoke()}>{busy ? 'Завершаем…' : 'Завершить'}</button></div>
    </section></div>}
  </div>;
}
