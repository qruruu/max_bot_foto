/** URLs select a workspace explicitly; React routes inside it stay relative to that workspace. */
export function workspacePrefix(pathname = typeof window === 'undefined' ? '' : window.location?.pathname || '') {
  return pathname.match(/^\/org\/[0-9a-f-]{36}(?=\/|$)/)?.[0] || '';
}

export const workspaceUrl = (path: string) => workspacePrefix() + path;
export const apiUrl = (path: string) => workspaceUrl('/api' + path);
export const workspaceStorageKey = (key: string) => workspacePrefix() ? `${key}:${workspacePrefix().slice(5)}` : key;
