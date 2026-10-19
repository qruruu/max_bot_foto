import { useEffect, useState } from 'react';

const STORAGE_KEY = 'max-photo-sidebar-collapsed';
const COMPACT_SCREEN = '(max-width: 850px)';

function savedPreference(): boolean | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === 'true' ? true : value === 'false' ? false : null;
  } catch {
    return null;
  }
}

export default function useSidebar() {
  const [preference, setPreference] = useState(savedPreference);
  const [compactScreen, setCompactScreen] = useState(() => window.matchMedia(COMPACT_SCREEN).matches);
  const collapsed = preference ?? compactScreen;

  useEffect(() => {
    const media = window.matchMedia(COMPACT_SCREEN);
    const resize = () => setCompactScreen(media.matches);
    const sync = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY || event.key === null) setPreference(savedPreference());
    };
    media.addEventListener('change', resize);
    window.addEventListener('storage', sync);
    return () => {
      media.removeEventListener('change', resize);
      window.removeEventListener('storage', sync);
    };
  }, []);

  function toggle() {
    const next = !collapsed;
    setPreference(next);
    try {localStorage.setItem(STORAGE_KEY, String(next));}
    catch { /* The panel still toggles when saving browser preferences is unavailable. */ }
  }

  return {collapsed, toggle};
}
