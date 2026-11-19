import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ListChecks, Send, X } from 'lucide-react';
import { api } from '../api';
import AppealModal from './AppealModal';

export const MAX_SHARED_TASKS = 50;
type Recipient = {id: number; name: string; agency: string};
export type AppealMenuTarget = {id: number; anchor: HTMLButtonElement; x: number; y: number};

export function AppealForwardMenu({target, selecting, close, select, cancel, forward}: {
  target: AppealMenuTarget; selecting: boolean; close: () => void; select: () => void; cancel: () => void; forward: () => void;
}) {
  const menu = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = menu.current!;
    const {width, height} = element.getBoundingClientRect();
    element.style.left = Math.max(8, Math.min(target.x, window.innerWidth - width - 8)) + 'px';
    element.style.top = Math.max(8, Math.min(target.y, window.innerHeight - height - 8)) + 'px';
    element.querySelector('button')?.focus({preventScroll: true});
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
    close(); target.anchor.focus({preventScroll: true}); action();
  }
  return createPortal(<div ref={menu} className="chat-context-menu" role="menu" aria-label="Действия с задачами" onKeyDown={event => {
    if (event.key === 'Escape' || event.key === 'Tab') {event.preventDefault(); run(close);}
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const items = [...event.currentTarget.querySelectorAll('button')];
      const index = items.indexOf(document.activeElement as HTMLButtonElement);
      items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
    }
  }}>
    <button type="button" role="menuitem" tabIndex={-1} onClick={() => run(select)}><ListChecks size={16}/>Выбрать</button>
    <button type="button" role="menuitem" tabIndex={-1} onClick={() => run(forward)}><Send size={16}/>Переслать</button>
    {selecting && <button type="button" role="menuitem" tabIndex={-1} onClick={() => run(cancel)}><X size={16}/>Отменить выбор</button>}
  </div>, document.body);
}

export default function AppealForward({endpoint, ids, close, sent}: {
  endpoint: string; ids: number[]; close: () => void; sent: () => void;
}) {
  const [search, setSearch] = useState(''), [recipients, setRecipients] = useState<Recipient[]>([]);
  const [recipient, setRecipient] = useState<Recipient | null>(null);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const sending = useRef(false);
  const attempt = useRef<{recipient: number; key: string} | null>(null);
  const organization = endpoint === '/appeals';
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    const timer = window.setTimeout(() => {
      api<Recipient[]>(endpoint + (organization ? '/sharing/recipients?' : '/share-recipients?') + new URLSearchParams({q: search.trim()}), 'GET', undefined, controller.signal)
        .then(items => {if (!controller.signal.aborted) setRecipients(items);})
        .catch(error => {if (!controller.signal.aborted) setError(error.message);})
        .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    }, search ? 220 : 0);
    return () => {controller.abort(); window.clearTimeout(timer);};
  }, [endpoint, organization, search]);
  return <AppealModal title={ids.length === 1 ? 'Переслать задачу' : 'Переслать задачи'} close={close} busy={busy}>
    <form onSubmit={async event => {
      event.preventDefault();
      if (!recipient || sending.current) return;
      sending.current = true; setBusy(true); setError('');
      try {
        if (attempt.current?.recipient !== recipient.id) attempt.current = {recipient: recipient.id, key: crypto.randomUUID()};
        await api(endpoint + (organization ? '/sharing/send' : '/share'), 'POST', {
          appeal_ids: ids, inspector_id: recipient.id, client_id: attempt.current.key,
        });
        sent();
      } catch (error) {setError((error as Error).message);}
      finally {sending.current = false; setBusy(false);}
    }}>
      {ids.length > 1 && <p>Выбрано задач: {ids.length}</p>}
      <label>Кому переслать<input type="search" autoFocus maxLength={200} disabled={busy} value={search}
        onChange={event => {setRecipient(null); setSearch(event.target.value);}}/></label>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="forward-destinations" role="group" aria-label="Получатели" aria-busy={loading}>
        {loading ? <p role="status">Загружаем…</p> : recipients.map(item => <button type="button" key={item.id}
          disabled={busy} aria-pressed={recipient?.id === item.id} onClick={() => setRecipient(item)}>
          <span className="forward-recipient"><strong>{item.name}</strong><small>{item.agency}</small></span>
        </button>)}
        {!loading && !recipients.length && !error && <p>Проверяющие не найдены.</p>}
      </div>
      <button className="primary" disabled={busy || loading || !recipient}><Send size={16}/>{busy ? 'Отправляем…' : 'Переслать'}</button>
    </form>
  </AppealModal>;
}
