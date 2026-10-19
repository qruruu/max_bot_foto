import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Info } from 'lucide-react';
import './work-types.css';

export default function WorkTypeHint({name, description}: {name: string; description?: string}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({left: 0, top: 0});
  const trigger = useRef<HTMLButtonElement>(null), tooltip = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const text = description?.trim();

  function show() { clearTimeout(closeTimer.current); setOpen(true); }
  function hideSoon() { clearTimeout(closeTimer.current); closeTimer.current = setTimeout(() => setOpen(false), 150); }

  useLayoutEffect(() => {
    if (!open || !trigger.current || !tooltip.current) return;
    const rect = trigger.current.getBoundingClientRect(), box = tooltip.current.getBoundingClientRect();
    const below = window.innerHeight - rect.bottom - 12;
    const above = below < box.height && rect.top > below;
    setPosition({
      left: Math.max(12, Math.min(rect.right - box.width, window.innerWidth - box.width - 12)),
      top: Math.max(12, Math.min(above ? rect.top - box.height - 8 : rect.bottom + 8, window.innerHeight - box.height - 12)),
    });
  }, [open, text]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!trigger.current?.contains(event.target as Node) && !tooltip.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {if (event.key === 'Escape') setOpen(false);};
    const scroll = (event: Event) => {if (!tooltip.current?.contains(event.target as Node)) setOpen(false);};
    const resize = () => setOpen(false);
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    window.addEventListener('scroll', scroll, true);
    window.addEventListener('resize', resize);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', escape);
      window.removeEventListener('scroll', scroll, true);
      window.removeEventListener('resize', resize);
    };
  }, [open]);
  useEffect(() => () => clearTimeout(closeTimer.current), []);

  if (!text) return null;
  return <span className="work-type-hint">
    <button ref={trigger} type="button" className="work-type-hint-trigger" aria-label={'Описание вида работы «'+name+'»'}
      aria-describedby={open ? id : undefined} aria-expanded={open}
      onMouseEnter={show} onMouseLeave={hideSoon} onFocus={show} onBlur={hideSoon}
      onClick={event => {event.preventDefault(); event.stopPropagation(); show();}}
      onKeyDown={event => {if (event.key === 'Escape') {event.stopPropagation(); setOpen(false);}}}>
      <Info size={15} aria-hidden="true"/>
    </button>
    {open && createPortal(<div ref={tooltip} id={id} role="tooltip" className="work-type-tooltip" style={position}
      onMouseEnter={show} onMouseLeave={hideSoon}>
      <strong>{name}</strong><p>{text}</p>
    </div>, document.body)}
  </span>;
}
