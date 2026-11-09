import { useLayoutEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { X } from 'lucide-react';

export default function AppealModal({title, close, busy, children}: {
  title: string; close: () => void; busy?: boolean; children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {dialog.current?.showModal();}, []);
  return <dialog ref={dialog} className="appeal-modal" aria-label={title}
    onCancel={event => {event.preventDefault(); if (!busy) close();}}>
    <header className="section-title"><h2>{title}</h2>
      <button type="button" aria-label="Закрыть окно" disabled={busy} onClick={close}><X size={18}/></button>
    </header>
    {children}
  </dialog>;
}
