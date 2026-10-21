import { useEffect, useState } from 'react';
import App from './App';
import { api } from './api';
import Organizations from './Organizations';
import { workspacePrefix } from './workspace';

export default function Application() {
  const [enabled, setEnabled] = useState<boolean | null>(workspacePrefix() ? false : null);
  const [error, setError] = useState('');
  async function load() {
    setError('');
    try { setEnabled((await api<{enabled: boolean}>('/platform/status')).enabled); }
    catch (error) { setError((error as Error).message); }
  }
  useEffect(() => {if (!workspacePrefix()) void load();}, []);
  if (enabled === null) return <div className="full-loading">{error || 'Открываем MAX Фото…'}{error && <button onClick={load}>Повторить</button>}</div>;
  return enabled ? <Organizations/> : <App/>;
}
