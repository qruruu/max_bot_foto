import { useEffect, useRef } from 'react';
import { api } from './api';
import './user-presence.css';

const heartbeatMs = 60_000;
const onlineMs = 120_000;

export function usePresenceHeartbeat(enabled: boolean, endpoint = '/auth/presence') {
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let last = 0;
    function beat() {
      if (document.hidden || Date.now() - last < heartbeatMs - 1000) return;
      last = Date.now();
      void api(endpoint, 'POST', undefined, controller.signal).catch(() => {});
    }
    beat();
    const timer = window.setInterval(beat, heartbeatMs);
    document.addEventListener('visibilitychange', beat);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', beat);
    };
  }, [enabled, endpoint]);
}

export function usePresenceRefresh(enabled: boolean, refresh: () => Promise<void>) {
  const current = useRef(refresh);
  current.current = refresh;
  useEffect(() => {
    if (!enabled) return;
    let pending = false;
    async function update() {
      if (document.hidden || pending) return;
      pending = true;
      try {await current.current();} catch {} finally {pending = false;}
    }
    const timer = window.setInterval(update, heartbeatMs);
    document.addEventListener('visibilitychange', update);
    return () => {window.clearInterval(timer); document.removeEventListener('visibilitychange', update);};
  }, [enabled]);
}

export default function UserPresence({lastSeen, active = true, timezone}: {lastSeen?: string | null; active?: boolean; timezone?: string}) {
  if (lastSeen === undefined) return null;
  const online = active && !!lastSeen && Date.now() - Date.parse(lastSeen) < onlineMs;
  return <small className={'user-presence' + (online ? ' is-online' : '')}>
    {online ? 'В сети' : lastSeen ? <>Был(а) в сети <time dateTime={lastSeen}>{new Date(lastSeen).toLocaleString('ru-RU',
      {dateStyle: 'short', timeStyle: 'short', timeZone: timezone})}</time></> : 'Вне сети'}
  </small>;
}
