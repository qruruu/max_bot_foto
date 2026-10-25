import { useLayoutEffect } from 'react';
import type { RefObject } from 'react';

export default function useModal(root: RefObject<HTMLDivElement | null>) {
  useLayoutEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const scrollY = window.scrollY;
    const original = {overflow: document.body.style.overflow, position: document.body.style.position,
      top: document.body.style.top, width: document.body.style.width};
    previous?.blur();
    document.body.style.overflow = 'hidden';
    document.body.style.position = 'fixed'; document.body.style.top = `-${scrollY}px`; document.body.style.width = '100%';
    root.current?.querySelector<HTMLButtonElement>('button')?.focus({preventScroll: true});
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        root.current?.querySelector<HTMLButtonElement>('[data-modal-close]:not(:disabled)')?.click();
      }
      if (event.key !== 'Tab') return;
      const items = root.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');
      if (!items?.length) return;
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last.focus();}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first.focus();}
    };
    document.addEventListener('keydown', keydown);
    return () => {Object.assign(document.body.style, original); window.scrollTo(0, scrollY);
      document.removeEventListener('keydown', keydown); previous?.focus({preventScroll: true});};
  }, [root]);
}
