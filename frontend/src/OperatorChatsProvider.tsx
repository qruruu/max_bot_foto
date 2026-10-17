import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from './api';

const Context = createContext<{unread: number; refreshUnread: () => Promise<void>}>(null!);
export const useOperatorChats = () => useContext(Context);

export function OperatorChatsProvider({children}: {children: ReactNode}) {
  const [unread, setUnread] = useState(0);
  const request = useRef<AbortController | null>(null);
  const refreshUnread = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    try {
      const result = await api<{unread: number}>('/operator-chats/unread', 'GET', undefined, controller.signal);
      if (!controller.signal.aborted) setUnread(result.unread);
    } catch { /* Keep the last count during a temporary network interruption. */ }
  }, []);

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
