import { useRef, useState } from 'react';
import { Paperclip } from 'lucide-react';

type AttachmentOption = {label: string; action: () => void; disabled?: boolean};

export default function AttachmentButton({label, disabled, action, options}: {
  label: string; disabled?: boolean; action?: () => void; options?: AttachmentOption[];
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return <div className="chat-attachment-control" onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }} onKeyDown={event => {
    if (event.key !== 'Escape' || !open) return;
    event.preventDefault();
    event.stopPropagation();
    setOpen(false);
    trigger.current?.focus();
  }}>
    <button ref={trigger} type="button" className="chat-attachment-trigger" title={label} aria-label={label}
      aria-expanded={options ? open : undefined} disabled={disabled}
      onClick={() => options ? setOpen(value => !value) : action?.()}><Paperclip size={19}/></button>
    {options && open && <div className="chat-attachment-options">
      {options.map(option => <button key={option.label} type="button" disabled={disabled || option.disabled} onClick={() => {
        setOpen(false);
        trigger.current?.focus();
        option.action();
      }}>{option.label}</button>)}
    </div>}
  </div>;
}
