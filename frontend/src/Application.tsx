import { lazy, Suspense, useEffect, useState } from 'react';
import App from './App';
import { api } from './api';
import Organizations from './Organizations';
import { workspacePrefix } from './workspace';
const InspectorApp = lazy(() => import('./inspection/InspectorApp'));

export default function Application() {
  const inspection = /^\/inspection(?:\/|$)/.test(window.location.pathname);
  const [enabled, setEnabled] = useState<boolean | null>(workspacePrefix() || inspection ? false : null);
  const [error, setError] = useState('');
  async function load() {
    setError('');
    try { setEnabled((await api<{enabled: boolean}>('/platform/status')).enabled); }
    catch (error) { setError((error as Error).message); }
  }
  useEffect(() => {if (!workspacePrefix() && !inspection) void load();}, []);
  if (inspection) return <Suspense fallback={<div className="full-loading">Открываем кабинет проверяющего…</div>}><InspectorApp/></Suspense>;
  if (enabled === null) return <div className="full-loading">{error || 'Открываем Метку…'}{error && <button onClick={load}>Повторить</button>}</div>;
  return enabled ? <Organizations/> : <App/>;
}
