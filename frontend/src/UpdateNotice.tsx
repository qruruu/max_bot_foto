import { useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { watchVersion } from './version';
import './update.css';

export default function UpdateNotice({beforeUpdate, disabled = false, hidden = false, citizen = false}: {
  beforeUpdate?: () => Promise<void>; disabled?: boolean; hidden?: boolean; citizen?: boolean;
} = {}) {
  const [available, setAvailable] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState('');
  const active = useRef(false);

  useEffect(() => {
    if (!import.meta.env.DEV) return watchVersion(__APP_VERSION__, setAvailable);
  }, []);

  async function update() {
    if (active.current || disabled) return;
    active.current = true; setUpdating(true); setError('');
    try {
      await beforeUpdate?.();
      window.location.reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Не удалось обновить страницу. Попробуйте ещё раз.');
      active.current = false; setUpdating(false);
    }
  }

  if (!available || hidden) return null;
  return <section className={'update-notice' + (citizen ? ' update-notice-citizen' : '')} role="status" aria-live="polite" aria-atomic="true">
    <strong>Доступна новая версия</strong>
    <button className="primary" type="button" disabled={updating || disabled} onClick={() => void update()}><RefreshCw size={16}/>{updating ? 'Обновляем…' : 'Обновить'}</button>
    {error && <p className="update-error" role="alert">{error}</p>}
  </section>;
}
