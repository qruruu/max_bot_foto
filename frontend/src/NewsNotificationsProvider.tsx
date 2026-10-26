import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from './api';
import { watchNewsUnread } from './newsNotifications';
import type { NewsUnread } from './newsNotifications';

type NewsNotifications = {unread: number; markRead: (slug: string) => Promise<void>};
const Context = createContext<NewsNotifications | null>(null);

export function NewsNotificationsProvider({enabled, children}: {enabled: boolean; children: ReactNode}) {
  const [unread, setUnread] = useState(0);
  const watcher = useRef<ReturnType<typeof watchNewsUnread> | null>(null);
  useEffect(() => {
    setUnread(0);
    if (!enabled) return;
    const current = watchNewsUnread(signal => api<NewsUnread>('/news/unread', 'GET', undefined, signal), setUnread);
    watcher.current = current;
    return () => {current.stop(); if (watcher.current === current) watcher.current = null;};
  }, [enabled]);
  const markRead = useCallback(async (slug: string) => {
    if (!enabled) return;
    await api('/news/' + encodeURIComponent(slug) + '/read', 'POST');
    await watcher.current?.refresh();
  }, [enabled]);
  return <Context.Provider value={{unread: enabled ? unread : 0, markRead}}>{children}</Context.Provider>;
}

export function useNewsNotifications() {
  const context = useContext(Context);
  if (!context) throw new Error('NewsNotificationsProvider is required');
  return context;
}

export function NewsUnreadBadge() {
  const {unread} = useNewsNotifications();
  return unread > 0 ? <span className="operator-chat-badge news-unread-badge" aria-label={`Непрочитанных новостей: ${unread}`}>
    {unread > 99 ? '99+' : unread}
  </span> : null;
}
