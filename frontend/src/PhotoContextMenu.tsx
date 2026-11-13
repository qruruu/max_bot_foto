import { useEffect, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Download, ListChecks, Share2, X } from 'lucide-react';
import type { Photo } from './types';
import { MAX_DOWNLOAD_PHOTOS } from './photoLimits';
import { MAX_PHOTOS } from './appeals/TaskImageInput';

export type PhotoMenuTarget = {photo: Photo; x: number; y: number; row: HTMLTableRowElement};

export default function PhotoContextMenu({target, count, canSelect, selecting, canSendToTask, downloading, download, close, select, cancel, forward}: {
  target: PhotoMenuTarget; count: number; canSelect: boolean; selecting: boolean; canSendToTask: boolean;
  downloading: boolean; download: () => void;
  close: () => void; select: () => void; cancel: () => void; forward: (destination: 'chat' | 'task') => void;
}) {
  const menu = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = menu.current;
    if (!element) return;
    const {width, height} = element.getBoundingClientRect();
    element.style.left = Math.max(8, Math.min(target.x, window.innerWidth - width - 8)) + 'px';
    element.style.top = Math.max(8, Math.min(target.y, window.innerHeight - height - 8)) + 'px';
    element.querySelector<HTMLElement>('[role="menuitem"]:not(:disabled)')?.focus({preventScroll: true});
  }, [target]);

  useEffect(() => {
    const outside = (event: Event) => {if (!menu.current?.contains(event.target as Node)) close();};
    document.addEventListener('pointerdown', outside);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('pointerdown', outside);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [close]);

  function run(action: () => void) {
    close();
    target.row.focus({preventScroll: true});
    action();
  }

  return createPortal(<div ref={menu} className="chat-context-menu" role="menu" aria-label="Действия с фотографиями"
    onKeyDown={event => {
      if (event.key === 'Escape' || event.key === 'Tab') {
        event.preventDefault();
        event.stopPropagation();
        close();
        target.row.focus({preventScroll: true});
      }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
      event.preventDefault();
      const items = [...event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]:not(:disabled)')];
      const index = items.indexOf(document.activeElement as HTMLElement);
      items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
    }}>
    {canSelect && <button type="button" role="menuitem" tabIndex={-1} onClick={() => run(select)}><ListChecks size={16}/>Выбрать</button>}
    {selecting && <button type="button" role="menuitem" tabIndex={-1} onClick={() => run(cancel)}><X size={16}/>Отменить выбор</button>}
    {count <= MAX_PHOTOS && <button type="button" role="menuitem" tabIndex={-1} disabled={!count} onClick={() => run(() => forward('chat'))}><Share2 size={16}/>Переслать в чат</button>}
    {count <= MAX_PHOTOS && canSendToTask && <button type="button" role="menuitem" tabIndex={-1} disabled={!count} onClick={() => run(() => forward('task'))}><Share2 size={16}/>Переслать в задачу</button>}
    <button type="button" role="menuitem" tabIndex={-1} disabled={!count || downloading || count > MAX_DOWNLOAD_PHOTOS}
      onClick={() => run(download)}><Download size={16}/>{count > 1 ? 'Скачать выбранные фотографии' : 'Скачать изображение'}</button>
  </div>, document.body);
}
