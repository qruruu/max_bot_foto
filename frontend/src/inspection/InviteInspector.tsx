import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { OrganizationQR } from './QR';
import './inspection.css';

export default function InviteInspector({open, onClose}: {open: boolean; onClose: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (open && element && !element.open) element.showModal();
    if (!open && element?.open) element.close();
  }, [open]);

  return <dialog className="modal inspector-invite-dialog" ref={dialog} aria-labelledby="inspector-invite-title" onClose={() => {if (open) onClose();}}>
    <header className="section-title"><h2 id="inspector-invite-title">Пригласить проверяющего</h2>
      <button type="button" aria-label="Закрыть приглашение" onClick={onClose}><X size={18}/></button>
    </header>
    <OrganizationQR endpoint="/inspection-admin/qr" embedded/>
  </dialog>;
}
