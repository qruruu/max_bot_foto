import { useEffect, useRef } from 'react';

let backNavigation: Promise<void> | null = null;

/** Android/system Back closes an open camera or preview before leaving the form. */
export default function useOverlayHistory(open: boolean, close: () => void) {
  const closeRef = useRef(close); closeRef.current = close;
  useEffect(() => {
    if (!open) return;
    const id = 'appeal-' + Math.random().toString(36).slice(2);
    let active = true, added = false;
    const entered = () => {
      if (!active) return;
      window.history.pushState({...window.history.state, citizenOverlay: id}, ''); added = true;
    };
    if (backNavigation) void backNavigation.then(entered);
    else entered();
    const changed = () => {if (added && window.history.state?.citizenOverlay !== id) closeRef.current();};
    window.addEventListener('popstate', changed);
    return () => {
      active = false; window.removeEventListener('popstate', changed);
      if (!added || window.history.state?.citizenOverlay !== id) return;
      backNavigation = new Promise<void>(resolve => {
        window.addEventListener('popstate', () => {backNavigation = null; resolve();}, {once: true});
        window.history.back();
      });
    };
  }, [open]);
}
