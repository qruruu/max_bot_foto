import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { PointerEvent, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ListChecks, Reply, Share2 } from 'lucide-react';

export default function ChatMessageMenu({as: Tag, id, className, reply, forward, select, selected, children}: {
  as: 'li' | 'article'; id: number; className: string; reply?: () => void; forward?: () => void; select?: () => void; selected?: boolean; children: ReactNode;
}) {
  const message = useRef<HTMLElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const press = useRef<{timer: number; x: number; y: number} | null>(null);
  const blockClick = useRef(false);
  const lastTap = useRef<{time: number; x: number; y: number} | null>(null);
  const touchReplyAt = useRef(-Infinity);
  const selectingFromMenu = useRef(false);
  const [position, setPosition] = useState<{x: number; y: number} | null>(null);
  const selecting = selected !== undefined;
  const enabled = !selecting && !!(reply || forward || select);

  function cancelPress() {
    if (press.current) window.clearTimeout(press.current.timer);
    press.current = null;
  }

  function startPress(event: PointerEvent) {
    cancelPress();
    blockClick.current = false;
    if (!enabled || event.pointerType !== 'touch' || !event.currentTarget.contains(event.target as Node)) return;
    const {clientX: x, clientY: y} = event;
    press.current = {x, y, timer: window.setTimeout(() => {
      press.current = null;
      blockClick.current = true;
      setPosition({x, y});
    }, 500)};
  }

  useEffect(() => cancelPress, []);
  useLayoutEffect(() => {
    if (selecting && selectingFromMenu.current) {
      selectingFromMenu.current = false;
      message.current?.querySelector<HTMLInputElement>('.chat-select-checkbox')?.focus({preventScroll: true});
    }
  }, [selecting]);
  useLayoutEffect(() => {
    const element = menu.current;
    if (!position || !element) return;
    const edge = 8;
    const {width, height} = element.getBoundingClientRect();
    element.style.left = Math.max(edge, Math.min(position.x, window.innerWidth - width - edge)) + 'px';
    element.style.top = Math.max(edge, Math.min(position.y, window.innerHeight - height - edge)) + 'px';
    element.querySelector<HTMLElement>('[role="menuitem"]')?.focus({preventScroll: true});
  }, [position, enabled]);

  useEffect(() => {
    if (!position || !enabled) return;
    function outside(event: Event) {
      if (!menu.current?.contains(event.target as Node)) setPosition(null);
    }
    const close = () => {
      if (menu.current?.contains(document.activeElement)) message.current?.focus({preventScroll: true});
      setPosition(null);
    };
    document.addEventListener('pointerdown', outside);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('pointerdown', outside);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [position, enabled]);

  function dismiss() {
    setPosition(null);
    message.current?.focus({preventScroll: true});
  }

  return <Tag ref={node => {message.current = node;}} className={className + (selecting && select ? ' chat-message-selectable' : '')} data-message-id={id}
    data-selected={selected || undefined}
    onDoubleClick={event => {
      if (!reply || selecting || performance.now() - touchReplyAt.current < 450 || !event.currentTarget.contains(event.target as Node)
        || (event.target as HTMLElement).closest('a,button,input')) return;
      reply();
    }}
    onClick={event => {
      if (!selecting || !select || !event.currentTarget.contains(event.target as Node)
        || (event.target as HTMLElement).closest('input')) return;
      event.preventDefault();
      select();
    }}
    tabIndex={enabled ? 0 : -1} aria-haspopup={enabled ? 'menu' : undefined} aria-expanded={enabled ? !!position : undefined}
    aria-keyshortcuts={enabled ? 'Shift+F10 ContextMenu' : undefined}
    onContextMenu={event => {
      if (!enabled || !event.currentTarget.contains(event.target as Node)) return;
      event.preventDefault();
      cancelPress();
      if (typeof window.PointerEvent === 'function' && event.nativeEvent instanceof window.PointerEvent && event.nativeEvent.pointerType === 'touch') blockClick.current = true;
      setPosition({x: event.clientX, y: event.clientY});
    }}
    onKeyDown={event => {
      if (!enabled || event.target !== event.currentTarget || !(event.key === 'ContextMenu' || event.shiftKey && event.key === 'F10')) return;
      event.preventDefault();
      const bounds = event.currentTarget.getBoundingClientRect();
      setPosition({x: bounds.left + 12, y: bounds.top + 12});
    }}
    onPointerDown={startPress}
    onPointerMove={event => {
      const start = press.current;
      if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 10) cancelPress();
    }}
    onPointerUp={event => {
      const tap = press.current;
      cancelPress();
      if (!tap || !reply || selecting || (event.target as HTMLElement).closest('a,button,input')
        || Math.hypot(event.clientX - tap.x, event.clientY - tap.y) > 10) {
        lastTap.current = null;
        return;
      }
      const time = performance.now(), previous = lastTap.current;
      if (previous && time - previous.time < 320 && Math.hypot(tap.x - previous.x, tap.y - previous.y) < 24) {
        lastTap.current = null; touchReplyAt.current = time; blockClick.current = true;
        reply();
      } else {
        lastTap.current = {time, x: tap.x, y: tap.y};
      }
    }}
    onPointerCancel={cancelPress} onPointerLeave={cancelPress}
    onClickCapture={event => {
      if (!blockClick.current || menu.current?.contains(event.target as Node)) return;
      blockClick.current = false;
      event.preventDefault();
      event.stopPropagation();
    }}>
    {selecting && select && <input className="chat-select-checkbox" type="checkbox"
      aria-label={'Выбрать сообщение ' + id} checked={selected} onChange={select}/>}
    {children}
    {enabled && position && createPortal(<div ref={menu} className="chat-context-menu" role="menu" aria-label="Действия с сообщением"
      onKeyDown={event => {
        if (event.key === 'Escape' || event.key === 'Tab') {
          event.preventDefault();
          event.stopPropagation();
          dismiss();
          return;
        }
        const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));
        const index = items.indexOf(document.activeElement as HTMLElement);
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Home' || event.key === 'End') {
          event.preventDefault();
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
            : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
          items[next]?.focus();
        }
      }}>
      {reply && <button type="button" role="menuitem" tabIndex={-1} onClick={() => {dismiss(); reply();}}><Reply size={17}/>Ответить</button>}
      {forward && <button type="button" role="menuitem" tabIndex={-1} onClick={() => {dismiss(); forward();}}><Share2 size={16}/>Переслать</button>}
      {select && <button type="button" role="menuitem" tabIndex={-1} onClick={() => {selectingFromMenu.current = true; dismiss(); select();}}><ListChecks size={16}/>Выбрать</button>}
    </div>, document.body)}
  </Tag>;
}
