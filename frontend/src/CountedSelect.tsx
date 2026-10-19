import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Info } from 'lucide-react';
import WorkTypeHint from './WorkTypeHint';
import './counted-select.css';

type Option = {value: string; label: string; count?: number; description?: string; name?: string};

export default function CountedSelect({label, value, options, onChange}: {
  label: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false), [active, setActive] = useState(0);
  const [position, setPosition] = useState({left: 0, top: 0, width: 0, maxHeight: 0});
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null), menu = useRef<HTMLDivElement>(null);
  const search = useRef({text: '', at: 0});
  const selected = options.findIndex(option => option.value === value);
  const current = options[selected] || options[0];

  function show(index = Math.max(0, selected)) {setActive(index); setOpen(true); search.current = {text:'', at:0};}
  function choose(index: number) {
    if (!options[index]) return;
    onChange(options[index].value); setOpen(false); trigger.current?.focus();
  }

  useLayoutEffect(() => {
    if (!open || !trigger.current) return;
    const rect = trigger.current.getBoundingClientRect();
    const below = window.innerHeight - rect.bottom - 12, above = rect.top - 12;
    const upwards = below < Math.min(240, options.length * 34) && above > below;
    const maxHeight = Math.max(34, Math.min(520, upwards ? above : below));
    const height = Math.min(maxHeight, options.length * 34 + 8);
    const width = Math.min(Math.max(rect.width, 240), window.innerWidth - 16);
    setPosition({left:Math.max(8,Math.min(rect.left, window.innerWidth-width-8)), top:upwards?rect.top-height-4:rect.bottom+4, width, maxHeight});
  }, [open, options.length]);

  useLayoutEffect(() => {
    if (open) menu.current?.querySelectorAll<HTMLElement>('[role="option"]')[active]?.scrollIntoView({block:'nearest'});
  }, [open, active]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node) && !menu.current?.contains(event.target as Node)) setOpen(false);
    };
    const resized = () => setOpen(false);
    const scrolled = (event: Event) => {if (!menu.current?.contains(event.target as Node)) setOpen(false);};
    const focused = (event: FocusEvent) => {
      if (!root.current?.contains(event.target as Node) && !menu.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('focusin', focused);
    window.addEventListener('resize', resized);
    window.addEventListener('scroll', scrolled, true);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('focusin', focused);
      window.removeEventListener('resize', resized);
      window.removeEventListener('scroll', scrolled, true);
    };
  }, [open]);

  function keyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
      event.preventDefault();
      if (event.key === 'Home') show(0);
      else if (event.key === 'End') show(options.length-1);
      else if (!open) show();
      else setActive(index => (index + (event.key==='ArrowDown'?1:-1) + options.length) % options.length);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault(); if (open) choose(active); else show();
    } else if (event.key === 'Escape' && open) {
      event.preventDefault(); event.stopPropagation(); setOpen(false);
    } else if (event.key === 'Tab') setOpen(false);
    else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      const at = Date.now(), character = event.key.toLocaleLowerCase('ru');
      const text = at-search.current.at>700 ? character : search.current.text+character;
      search.current = {text,at};
      const prefix = [...text].every(letter => letter===character) ? character : text;
      const start = open ? active : Math.max(0,selected);
      const index = options.findIndex((_,offset) => options[(start+offset+1)%options.length].label.toLocaleLowerCase('ru').startsWith(prefix));
      if (index >= 0) {setActive((start+index+1)%options.length); setOpen(true);}
    }
  }

  return <div className="counted-select" ref={root}>
    <div className="counted-select-heading"><span id={id+'-label'} className="counted-select-label">{label}</span><WorkTypeHint name={current?.name||current?.label||label} description={current?.description}/></div>
    <button ref={trigger} type="button" role="combobox" aria-labelledby={id+'-label'} aria-expanded={open}
      aria-haspopup="listbox" aria-controls={id+'-list'} aria-activedescendant={open?id+'-option-'+active:undefined}
      className={'counted-select-trigger'+((current?.count??0)>0?' has-photos':'')}
      onClick={() => {if (open) setOpen(false); else show();}} onKeyDown={keyDown}
    ><span>{current?.label}</span><ChevronDown size={14} aria-hidden="true"/></button>
    {open && createPortal(<div ref={menu} id={id+'-list'} role="listbox" aria-labelledby={id+'-label'} className="counted-select-options" style={position}>
      {options.map((option,index) => <div key={option.value} id={id+'-option-'+index} role="option" aria-selected={option.value===value}
        className={'counted-select-option'+((option.count??0)>0?' has-photos':'')} data-highlighted={active===index}
        title={option.description || undefined} aria-description={option.description || undefined}
        onPointerDown={event => event.preventDefault()} onMouseEnter={() => setActive(index)} onClick={() => choose(index)}>
        <span className="counted-select-check">{option.value===value && <Check size={14} aria-hidden="true"/>}</span><span>{option.label}</span>
        {option.description && <span className="work-option-info" aria-hidden="true"><Info size={14}/></span>}
      </div>)}
    </div>,document.body)}
  </div>;
}
