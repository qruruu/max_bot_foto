import { createContext, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Bell, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from './api';
import { createNotificationSound } from './notificationSound';
import { notificationKey, playArrivalSound, readNotificationPreferences, saveNotificationPreferences, watchPhotoArrivals } from './photoArrivals';
import type { ArrivalSnapshot, NotificationPreferences } from './photoArrivals';

type NotificationContextValue = {
  preferences: NotificationPreferences;
  setPreference: (key: keyof NotificationPreferences, enabled: boolean) => void;
  canViewPhotos: boolean;
};
const NotificationContext = createContext<NotificationContextValue | null>(null);

export function PhotoNotificationsProvider({userId, canViewPhotos, children, endpoint = '/photos/arrivals', photoLink}: {
  userId: number; canViewPhotos: boolean; children: ReactNode; endpoint?: string; photoLink?: (id?: number) => string;
}) {
  const [preferences, setPreferences] = useState(() => readNotificationPreferences(userId));
  const [notice, setNotice] = useState<{count: number; photoId: number; revision: number} | null>(null);
  const currentPreferences = useRef(preferences);
  currentPreferences.current = preferences;
  const sound = useRef<ReturnType<typeof createNotificationSound> | null>(null);
  const enabled = canViewPhotos && (preferences.popup || preferences.sound);

  useEffect(() => {
    const chime = createNotificationSound();
    sound.current = chime;
    const activate = () => { if (canViewPhotos && currentPreferences.current.sound) void chime.unlock(); };
    window.addEventListener('pointerdown', activate);
    window.addEventListener('keydown', activate);
    return () => {
      window.removeEventListener('pointerdown', activate);
      window.removeEventListener('keydown', activate);
      chime.dispose();
      sound.current = null;
    };
  }, [canViewPhotos]);

  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === notificationKey(userId) || event.key === null) {
        setPreferences(readNotificationPreferences(userId));
      }
    };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, [userId]);

  useEffect(() => {
    if (!enabled) return;
    return watchPhotoArrivals(signal => api<ArrivalSnapshot>(endpoint, 'GET', undefined, signal), ids => {
      if (currentPreferences.current.popup) {
        setNotice(previous => ({count: (previous?.count || 0) + ids.length, photoId: ids[ids.length - 1], revision: (previous?.revision || 0) + 1}));
      }
      if (currentPreferences.current.sound) {
        void playArrivalSound(userId, ids, () => currentPreferences.current.sound && !!sound.current?.play(), endpoint);
      }
    });
  }, [enabled, userId, endpoint]);

  useEffect(() => {
    if (!preferences.popup || !canViewPhotos) setNotice(null);
  }, [preferences.popup, canViewPhotos]);

  useEffect(() => {setNotice(null);}, [endpoint]);

  useEffect(() => {
    if (!notice) return;
    let timeout: number | undefined;
    const restart = () => {
      window.clearTimeout(timeout);
      if (!document.hidden) timeout = window.setTimeout(() => setNotice(null), 12_000);
    };
    document.addEventListener('visibilitychange', restart);
    restart();
    return () => { window.clearTimeout(timeout); document.removeEventListener('visibilitychange', restart); };
  }, [notice]);

  function setPreference(key: keyof NotificationPreferences, value: boolean) {
    // Save the exact new value, also when React schedules more than one change in a frame.
    const next = {...currentPreferences.current, [key]: value};
    currentPreferences.current = next;
    saveNotificationPreferences(userId, next);
    setPreferences(next);
    if (key === 'sound' && value) void sound.current?.unlock();
  }

  return <NotificationContext.Provider value={{preferences, setPreference, canViewPhotos}}>
    {children}
    {notice && <section className="photo-notice" role="status" aria-live="polite" aria-atomic="true">
      <span className="photo-notice-icon" aria-hidden="true"><Bell size={21}/></span>
      <div><strong>{notice.count === 1 ? 'Поступила фотография' : `Новые фотографии: ${notice.count}`}</strong>
        <p>{notice.count === 1 ? `Фотография №${notice.photoId} поступила в сервис.` : 'Новые снимки поступили в сервис.'}</p>
        <Link to={photoLink ? photoLink(notice.count === 1 ? notice.photoId : undefined) : notice.count === 1 ? `/photos/${notice.photoId}` : '/photos?all_dates=1&date_basis=received'} onClick={() => {
          setNotice(null);
          window.dispatchEvent(new Event('refresh-photo-list'));
        }}>
          {notice.count === 1 ? 'Открыть фотографию' : 'Открыть фотографии'}
        </Link>
      </div>
      <button type="button" className="photo-notice-close" aria-label="Закрыть уведомление о фотографиях" onClick={() => setNotice(null)}><X size={17}/></button>
    </section>}
  </NotificationContext.Provider>;
}

export function usePhotoNotifications() {
  const context = useContext(NotificationContext);
  if (!context) throw new Error('PhotoNotificationsProvider is required');
  return context;
}
