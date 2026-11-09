// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AppealDiscussion from './AppealDiscussion';
import { api } from '../api';

vi.mock('../api', async () => ({...await vi.importActual('../api'), api: vi.fn()}));
let root: Root, element: HTMLDivElement;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const event = {id: 1, kind: 'STATUS', actor_name: 'Администратор', actor_role: 'ADMIN_OPERATOR', status: 'ASSIGNED', comment: '', visibility: 'STAFF', created_at: new Date().toISOString()};
beforeEach(() => {
  vi.clearAllMocks(); vi.mocked(api).mockResolvedValue({items: [event], has_more: false, can_comment: true});
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
});
afterEach(async () => {await act(async () => root.unmount()); element.remove();});
async function mount(archived = false) {await act(async () => {root.render(<AppealDiscussion endpoint="/inspection/organizations/one/appeals/42" archived={archived}/>); await tick();});}

it('shows only discussion messages and retries messages with the same identifier', async () => {
  await mount(); let sent = false;
  vi.mocked(api).mockImplementation(async (_path, method) => {
    if (method === 'POST' && !sent) {sent = true; throw new TypeError('Connection lost');}
    return method === 'POST' ? {id: 2} : {items: [{...event, id: 2, kind: 'COMMENT', comment: 'Проверяю на месте'}], has_more: false, can_comment: true};
  });
  const input = element.querySelector('textarea')!;
  await act(async () => {Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, 'Проверяю на месте'); input.dispatchEvent(new Event('input', {bubbles: true}));});
  const send = () => element.querySelector<HTMLButtonElement>('form button[type=submit]')!;
  await act(async () => {send().click(); await tick();});
  expect(input.disabled).toBe(true); expect(send().getAttribute('aria-label')).toContain('Повторить');
  await act(async () => {send().click(); await tick();});
  const posts = vi.mocked(api).mock.calls.filter(([, method]) => method === 'POST');
  expect(posts[0][2]).toEqual(posts[1][2]);
  expect(posts[0][0]).toBe('/inspection/organizations/one/appeals/42/comments');
  expect(element.querySelector('[role=log]')!.textContent).toContain('Проверяю на месте');
  expect(element.querySelector('[role=log]')!.textContent).not.toContain('Назначен исполнитель');
  expect(element.textContent).not.toContain('История');
});

it('keeps archived discussions readable without a send form', async () => {
  await mount(true); expect(element.querySelector('form')).toBeNull();
  expect(element.textContent).toContain('доступна для чтения');
});
