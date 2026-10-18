import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { workTypeLabel } from './photoWork';

type Props = {
  photoId: number;
  workTypeName: string;
  checked: boolean;
  disabled?: boolean;
  className?: string;
  inputLabel?: string;
  hideLabel?: boolean;
  saveImmediately?: boolean;
  onConfirm: (checked: boolean) => void | Promise<void>;
};

export default function DefectCheckbox({photoId, workTypeName, checked, disabled = false, className = '', inputLabel, hideLabel = false,
  saveImmediately = false, onConfirm}: Props) {
  const [pending, setPending] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const dialog = useRef<HTMLElement>(null);
  const busyRef = useRef(false);
  busyRef.current = busy;
  const titleId = useId(), descriptionId = useId();

  useEffect(() => {
    if (pending === null) return;
    const previousFocus = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.current?.querySelector<HTMLButtonElement>('[data-cancel]')?.focus();
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        if (!busyRef.current) setPending(null);
      }
      if (event.key === 'Tab') {
        const buttons = [...(dialog.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])];
        if (!buttons.length) {event.preventDefault(); return;}
        const first = buttons[0], last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last.focus();}
        else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first.focus();}
      }
    };
    window.addEventListener('keydown', keyboard);
    return () => {
      window.removeEventListener('keydown', keyboard);
      document.body.style.overflow = overflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({preventScroll: true});
    };
  }, [pending]);

  async function confirm() {
    if (pending === null || busyRef.current) return;
    busyRef.current = true;
    setBusy(true); setError('');
    try {await onConfirm(pending); setPending(null);}
    catch (e) {setError((e as Error).message);}
    finally {busyRef.current = false; setBusy(false);}
  }

  return <>
    <label className={'checkbox photo-defect-toggle ' + (hideLabel ? 'defect-icon-only ' : '') + className}>
      <input type="checkbox" aria-label={inputLabel} checked={checked} disabled={disabled}
        onChange={event => {setError(''); setPending(event.target.checked);}}/>
      {!hideLabel && <span>Неисправность</span>}
    </label>
    {pending !== null && createPortal(<div className="modal-backdrop">
      <section className="modal defect-confirmation" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} ref={dialog}>
        <div className="section-title"><h2 id={titleId}>{pending ? 'Отметить неисправность?' : 'Снять отметку о неисправности?'}</h2>
          <button type="button" aria-label="Закрыть" disabled={busy} onClick={() => setPending(null)}><X size={18}/></button>
        </div>
        <p id={descriptionId}>Вы уверены, что хотите {pending ? 'отметить неисправность' : 'снять отметку о неисправности'} на фото №{photoId}?</p>
        <p className="defect-confirm-preview">{workTypeLabel(workTypeName, pending)}</p>
        <p className="hint">{saveImmediately ? 'После подтверждения изменение сохранится сразу.' : 'Изменение сохранится вместе с остальными данными карточки.'}</p>
        {error && <div className="error" role="alert">{error}</div>}
        <div className="defect-confirm-actions">
          <button type="button" data-cancel disabled={busy} onClick={() => setPending(null)}>Отмена</button>
          <button type="button" className="primary" disabled={busy} onClick={() => void confirm()}>{busy ? 'Сохраняем…' : pending ? 'Да, отметить' : 'Да, снять отметку'}</button>
        </div>
      </section>
    </div>, document.body)}
  </>;
}
