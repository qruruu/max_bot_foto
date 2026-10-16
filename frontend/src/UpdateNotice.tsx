import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { watchVersion } from './version';

export default function UpdateNotice() {
  const [available, setAvailable] = useState(false);
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    if (!import.meta.env.DEV) return watchVersion(__APP_VERSION__, setAvailable);
  }, []);

  if (!available) return null;
  return <section className="update-notice" role="status" aria-live="polite" aria-atomic="true">
    <strong>Доступна новая версия</strong>
    <button className="primary" type="button" disabled={updating} onClick={() => {
      setUpdating(true);
      window.location.reload();
    }}><RefreshCw size={16}/>{updating ? 'Обновляем…' : 'Обновить'}</button>
  </section>;
}
