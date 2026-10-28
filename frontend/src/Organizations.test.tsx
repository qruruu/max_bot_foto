// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import Organizations from './Organizations';
import { api } from './api';

vi.mock('./api', () => ({api: vi.fn()}));
vi.mock('./App', () => ({ErrorBox: () => null}));
vi.mock('./Login', () => ({default: () => null, signInDestination: () => '/'}));
vi.mock('./ConnectDisk', () => ({default: () => null}));
vi.mock('./control/Control', () => ({default: () => <div>Контроль сервиса</div>}));
vi.mock('./theme', () => ({useTheme: () => ({theme: 'dark', setTheme: vi.fn()})}));

it('requires confirmation before pausing an organization and keeps settings when cancelled', async () => {
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  const organization = {id: 'one', name: 'Демо', city: 'Сургут', status: 'ACTIVE', url: '/org/demo/', disk_account_id: null, stats: {photos: 0}};
  vi.mocked(api).mockImplementation(async path => path === '/auth/entry' ? {user: {id: 1, name: 'Владелец', is_platform_owner: true}}
    : path === '/platform/organizations' ? [organization] : path === '/platform/disk-accounts' ? {items: [], default_configured: false} : []);
  const element = document.createElement('div'); document.body.append(element); const root = createRoot(element);
  const tick = () => new Promise(resolve => setTimeout(resolve, 0));
  const button = (text: string) => [...element.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent?.includes(text))!;
  try {
    await act(async () => {root.render(<Organizations/>); await tick();});
    await act(async () => {button('Организации').click();});
    await act(async () => {button('Настроить').click();});
    await act(async () => {element.querySelector<HTMLInputElement>('input[type=checkbox]')!.click(); button('Сохранить').click(); await tick();});
    expect(element.querySelector('[role=alertdialog]')).not.toBeNull();
    expect(vi.mocked(api).mock.calls.filter(([, method]) => method === 'PATCH')).toHaveLength(0);
    await act(async () => {button('Вернуться к настройкам').click();});
    expect(element.querySelector<HTMLInputElement>('input[type=checkbox]')!.checked).toBe(true);
    await act(async () => {button('Сохранить').click(); await tick();});
    await act(async () => {button('Подтвердить приостановку').click(); await tick();});
    expect(api).toHaveBeenCalledWith('/platform/organizations/one', 'PATCH', expect.objectContaining({status: 'PAUSED'}));
  } finally {await act(async () => root.unmount()); element.remove();}
});
