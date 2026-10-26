import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Bell, X } from 'lucide-react';
import { api, ApiError } from '../api';

export type AppealNotifications = {new_count: number; latest_id: number};

export function watchAppealNotifications(load: (signal: AbortSignal) => Promise<AppealNotifications>, update: (value: AppealNotifications) => void) {
  let stopped = false, active: AbortController | null = null;
  async function check() {
    if (stopped || active || document.hidden) return;
    const controller = new AbortController(); active = controller;
    const timer = window.setTimeout(() => controller.abort(), 9_000);
    try {
      const value = await load(controller.signal);
      if (!stopped && !controller.signal.aborted && Number.isSafeInteger(value.new_count) && value.new_count >= 0
        && Number.isSafeInteger(value.latest_id) && value.latest_id >= 0) update(value);
    } catch (failure) {
      if (failure instanceof ApiError && [401, 403].includes(failure.status)) stop();
    } finally {window.clearTimeout(timer); if (active === controller) active = null;}
  }
  const checkNow = () => {void check();};
  const interval = window.setInterval(checkNow, 20_000);
  for (const event of ['online', 'focus', 'appeals-changed']) window.addEventListener(event, checkNow);
  document.addEventListener('visibilitychange', checkNow);
  function stop() {
    stopped = true; window.clearInterval(interval); active?.abort();
    for (const event of ['online', 'focus', 'appeals-changed']) window.removeEventListener(event, checkNow);
    document.removeEventListener('visibilitychange', checkNow);
  }
  checkNow(); return stop;
}

export function useAppealNotifications(enabled: boolean, userId?: number) {
  const [count, setCount] = useState(0), [notice, setNotice] = useState(0);
  useEffect(() => {
    setCount(0); setNotice(0);
    if (!enabled) return;
    let latest = -1;
    return watchAppealNotifications(signal => api<AppealNotifications>('/appeals/notifications', 'GET', undefined, signal), data => {
      setCount(data.new_count);
      if (!data.new_count) setNotice(0);
      else if (data.latest_id > latest) setNotice(data.new_count);
      latest = Math.max(latest, data.latest_id);
    });
  }, [enabled, userId]);
  return {count, notice, dismiss: () => setNotice(0)};
}

export function AppealNotice({count, dismiss}: {count: number; dismiss: () => void}) {
  if (!count) return null;
  return <section className="photo-notice appeal-notice" role="status" aria-live="polite">
    <span className="photo-notice-icon"><Bell size={21}/></span><div><strong>Новое обращение о нарушении</strong>
      <p>В вашей организации ожидают рассмотрения: {count}.</p>
      <Link to="/appeals" onClick={() => {dismiss(); window.dispatchEvent(new Event('refresh-appeals'));}}>Открыть обращения</Link></div>
    <button type="button" className="photo-notice-close" aria-label="Закрыть уведомление об обращениях" onClick={dismiss}><X size={17}/></button>
  </section>;
}
