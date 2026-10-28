// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import OwnerAppeals from './OwnerAppeals';
import { api } from '../api';

vi.mock('../api', async () => ({...await vi.importActual('../api'), api: vi.fn()}));
let root: Root, element: HTMLDivElement, messages: number;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const row = {id: 42, number: 'ОБ-000042', status: 'NEW', version: 1, photo_count: 1, organization_name: 'Организация',
  city: 'Сургут', address: 'Сквер', place: 'У входа', description: 'Мусор', category: 'WASTE', created_at: '2026-10-28T10:00:00Z', owner_note: '',
  preview_url: '/preview', photos: [{id: 'one', url: '/photo', preview_url: '/preview', original_url: '/original'}], task: null, can_manage: true, can_execute: false};
beforeEach(() => {
  messages = 2; vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (method === 'POST') {messages = 0; return {id: 3};}
    if (path.includes('/events')) return {items: [], has_more: false, can_comment: true};
    if (path.endsWith('/operators')) return [];
    if (path.includes('?page=')) return {items: [{...row, unanswered_comments: messages}], total: 1, page: 1, page_size: 20, can_manage: true};
    return {...row, unanswered_comments: messages};
  });
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
});
afterEach(async () => {await act(async () => root.unmount()); element.remove();});

it('keeps message notifications after opening and clears them after a reply without losing the drafted administrator answer', async () => {
  await act(async () => {root.render(<OwnerAppeals organization endpoint="/appeals"/>); await tick();});
  expect(element.textContent).toContain('Новые сообщения: 2'); expect(element.querySelector('img')?.getAttribute('src')).toBe('/preview');
  expect(element.textContent).not.toContain('Показать фото');
  expect(element.querySelector('button button')).toBeNull();
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  expect(element.textContent).toContain('Новые сообщения: 2');
  expect(element.querySelector('.owner-appeal-photos img')?.getAttribute('src')).toBe('/photo');
  expect(element.querySelector<HTMLAnchorElement>('.owner-appeal-photos .button')?.getAttribute('href')).toBe('/original');
  expect(element.textContent).not.toContain('Показать фото');
  const answer = [...element.querySelectorAll('textarea')].find(textarea => textarea.placeholder === 'Результат рассмотрения обращения')!;
  const chat = element.querySelector<HTMLTextAreaElement>('[aria-label="Сообщение по обращению"]')!;
  await act(async () => {
    for (const [field, text] of [[answer, 'Черновик ответа'], [chat, 'Проверяем']] as const) {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, text); field.dispatchEvent(new Event('input', {bubbles: true}));
    }
  });
  await act(async () => {element.querySelector<HTMLButtonElement>('.appeal-discussion-compose button')!.click(); await tick();});
  expect(element.textContent).not.toContain('Новые сообщения'); expect(answer.value).toBe('Черновик ответа');
  expect(chat.value).toBe('');
  messages = 1;
  await act(async () => {window.dispatchEvent(new Event('focus')); await tick();});
  expect(element.textContent).toContain('Новые сообщения: 1'); expect(answer.value).toBe('Черновик ответа');
});
