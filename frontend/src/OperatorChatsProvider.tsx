import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from './api';

const Context = createContext<{unread: number; refreshUnread: () => Promise<void>}>(null!);
export const useOperatorChats = () => useContext(Context);

export function OperatorChatsProvider({children, endpoint = '/operator-chats/unread', additionalEndpoint}: {children: ReactNode; endpoint?: string; additionalEndpoint?: string}) {
  const [unread, setUnread] = useState(0);
  const counts = useRef<Record<string, number>>({});
  const request = useRef<AbortController | null>(null);
  const refreshUnread = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const endpoints = additionalEndpoint ? [endpoint, additionalEndpoint] : [endpoint];
    const results = await Promise.allSettled(endpoints.map(path => api<{unread: number}>(path, 'GET', undefined, controller.signal)));
    if (controller.signal.aborted) return;
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') counts.current[endpoints[index]] = result.value.unread;
    });
    setUnread(endpoints.reduce((total, path) => total + (counts.current[path] || 0), 0));
  }, [endpoint, additionalEndpoint]);

  useEffect(() => {
    const refresh = () => {if (!document.hidden) void refreshUnread();};
    refresh();
    const timer = window.setInterval(refresh, 10000);
    document.addEventListener('visibilitychange', refresh);
    window.addEventListener('focus', refresh);
    return () => {
      window.clearInterval(timer); request.current?.abort();
      document.removeEventListener('visibilitychange', refresh);
      window.removeEventListener('focus', refresh);
    };
  }, [refreshUnread]);

  return <Context.Provider value={{unread, refreshUnread}}>{children}</Context.Provider>;
}

export function OperatorChatBadge() {
  const {unread} = useOperatorChats();
  return unread > 0 ? <span className="operator-chat-badge" aria-label={`Непрочитанных сообщений: ${unread}`}>
    {unread > 99 ? '99+' : unread}
  </span> : null;
}
