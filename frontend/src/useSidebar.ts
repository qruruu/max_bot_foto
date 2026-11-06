import { useEffect, useRef, useState } from 'react';

const STORAGE_KEY = 'max-photo-sidebar-collapsed';
const COMPACT_SCREEN = '(max-width: 850px)';
const MOBILE_SCREEN = '(max-width: 600px)';

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
  const [mobile, setMobile] = useState(() => window.matchMedia(MOBILE_SCREEN).matches);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null), sidebar = useRef<HTMLElement>(null);
  const collapsed = mobile ? !menuOpen : (preference ?? compactScreen);

  useEffect(() => {
    const media = window.matchMedia(COMPACT_SCREEN);
    const mobileMedia = window.matchMedia(MOBILE_SCREEN);
    const resize = () => setCompactScreen(media.matches);
    const resizeMobile = () => {setMobile(mobileMedia.matches); setMenuOpen(false);};
    const sync = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY || event.key === null) setPreference(savedPreference());
    };
    media.addEventListener('change', resize);
    mobileMedia.addEventListener('change', resizeMobile);
    window.addEventListener('storage', sync);
    return () => {
      media.removeEventListener('change', resize);
      mobileMedia.removeEventListener('change', resizeMobile);
      window.removeEventListener('storage', sync);
    };
  }, []);

  function closeMenu() {
    if (!menuOpen) return;
    setMenuOpen(false);
    menuButton.current?.focus();
  }

  useEffect(() => {
    if (!mobile || !menuOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const drawer = sidebar.current;
    drawer?.querySelector<HTMLElement>('.sidebar-toggle[aria-expanded]')?.focus();
    function keydown(event: KeyboardEvent) {
      if (event.key === 'Escape') {event.preventDefault(); closeMenu(); return;}
      if (event.key !== 'Tab') return;
      const controls = drawer?.querySelectorAll<HTMLElement>('a[href], button:not(:disabled)');
      const first = controls?.[0], last = controls?.[controls.length - 1];
      if (!first || !last) return;
      const current = document.activeElement;
      if (!drawer?.contains(current) || (event.shiftKey ? current === first : current === last)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    }
    document.addEventListener('keydown', keydown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', keydown);
    };
  }, [mobile, menuOpen]);

  function toggle() {
    if (mobile) {
      if (menuOpen) closeMenu();
      else setMenuOpen(true);
      return;
    }
    const next = !collapsed;
    setPreference(next);
    try {localStorage.setItem(STORAGE_KEY, String(next));}
    catch { /* The panel still toggles when saving browser preferences is unavailable. */ }
  }

  return {collapsed, toggle, menuOpen, menuButton, sidebar, closeMenu};
}
