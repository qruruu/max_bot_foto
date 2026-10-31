// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import OwnerAppeals from './OwnerAppeals';
import { api, ApiError } from '../api';

vi.mock('../api', async () => ({...await vi.importActual('../api'), api: vi.fn()}));
let root: Root, element: HTMLDivElement, messages: number;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const row = {id: 42, number: 'ОБ-000042', status: 'NEW', version: 1, photo_count: 1, organization_name: 'Организация', organization_id: 'organization-one', work_type_name: '',
  city: 'Сургут', address: 'Сквер', place: 'У входа', description: 'Мусор', category: 'WASTE', created_at: '2026-10-28T10:00:00Z', owner_note: '',
  preview_url: '/preview', photos: [{id: 'one', url: '/photo', preview_url: '/preview', original_url: '/original'}], task: null, can_manage: true, can_execute: false};
let current: typeof row & {archived_at?: string};
beforeEach(() => {
  messages = 2; current = {...row}; vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (method === 'PATCH') {
      const fields = body as {category?: string};
      current = {...current, ...fields, work_type_name: fields.category === 'BIN_EMPTYING' ? 'УРНЫ' : fields.category === '' ? '' : current.work_type_name, version: current.version + 1};
      return current;
    }
    if (method === 'POST') {messages = 0; return {id: 3};}
    if (path.includes('/events')) return {items: [], has_more: false, can_comment: true};
    if (path.endsWith('/operators')) return [];
    if (path.endsWith('/work-types')) return [{code: 'BIN_EMPTYING', name: 'УРНЫ'}, {code: 'CUSTOM', name: 'Особая работа организации'}];
    if (path.includes('?page=')) return {items: [{...current, unanswered_comments: messages}], total: 1, page: 1, page_size: 20, can_manage: current.can_manage};
    return {...current, unanswered_comments: messages};
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

it.each(['/appeals', '/platform/appeals'])('assigns original organization work types and can clear them through %s', async endpoint => {
  current.category = '';
  await act(async () => {root.render(<OwnerAppeals organization endpoint={endpoint}/>); await tick();});
  expect(element.querySelector('.appeal-list-title')!.textContent).toBe('Мусор');
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  let select = element.querySelector<HTMLSelectElement>('select[name=work_type]')!;
  expect([...select.options].map(option => option.text)).toEqual(['Не назначен', 'УРНЫ', 'Особая работа организации']);
  expect(element.textContent).not.toContain('Переполненная урна');
  await act(async () => {select.value = 'BIN_EMPTYING'; select.dispatchEvent(new Event('change', {bubbles: true}));});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-edit button')!.click(); await tick();});
  expect(api).toHaveBeenCalledWith(endpoint + '/42', 'PATCH', {category: 'BIN_EMPTYING', status: 'NEW', owner_note: '', expected_version: 1});
  expect(element.querySelector<HTMLSelectElement>('select[name=work_type]')!.value).toBe('BIN_EMPTYING');
  expect(element.querySelector('.appeal-subject-panel h2')!.textContent).toBe('Мусор');
  select = element.querySelector<HTMLSelectElement>('select[name=work_type]')!;
  await act(async () => {select.value = ''; select.dispatchEvent(new Event('change', {bubbles: true}));});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-edit button')!.click(); await tick();});
  expect(api).toHaveBeenCalledWith(endpoint + '/42', 'PATCH', {category: '', status: 'NEW', owner_note: '', expected_version: 2});
  expect(element.querySelector<HTMLSelectElement>('select[name=work_type]')!.value).toBe('');
});

it.each(['operator', 'inspector', 'archived'])('does not offer work type editing for %s', async role => {
  if (role === 'operator') current = {...current, can_manage: false, can_execute: true};
  if (role === 'archived') current = {...current, archived_at: '2026-10-29T12:00:00Z'};
  await act(async () => {root.render(<OwnerAppeals organization endpoint="/appeals" readOnly={role === 'inspector'}/>); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  expect(element.querySelector('select[name=work_type]')).toBeNull();
  expect(vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/work-types'))).toBe(false);
});

it('keeps the selected work type and note after a version conflict', async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, method, ...args) => {
    if (method === 'PATCH') throw new ApiError(409, 'Обращение изменилось. Обновите карточку.');
    return original(path, method, ...args);
  });
  await act(async () => {root.render(<OwnerAppeals organization endpoint="/appeals"/>); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  const select = element.querySelector<HTMLSelectElement>('select[name=work_type]')!;
  const note = element.querySelector<HTMLTextAreaElement>('.owner-appeal-edit textarea')!;
  await act(async () => {
    select.value = 'BIN_EMPTYING'; select.dispatchEvent(new Event('change', {bubbles: true}));
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(note, 'Проверить урну');
    note.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-edit button')!.click(); await tick();});
  expect(element.textContent).toContain('Обращение изменилось');
  expect(select.value).toBe('BIN_EMPTYING'); expect(note.value).toBe('Проверить урну');
});

it.each([
  ['administrator', '/appeals', false], ['operator', '/appeals', false],
  ['inspector', '/inspection/organizations/one/appeals', true], ['owner', '/platform/appeals', false],
] as const)('searches appeal text and dates for the %s and preserves archive and status filters', async (_role, endpoint, readOnly) => {
  await act(async () => {root.render(<OwnerAppeals organization endpoint={endpoint} readOnly={readOnly}/>); await tick();});
  const input = element.querySelector<HTMLInputElement>('input[type=search]')!;
  const submit = async (query: string) => {
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, query);
      input.dispatchEvent(new Event('input', {bubbles: true}));
    });
    await act(async () => {element.querySelector('form[role=search]')!.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); await tick();});
  };
  const lastSearch = () => vi.mocked(api).mock.calls.filter(([path]) => path.startsWith(endpoint + '?')).at(-1)![0];
  for (const query of ['Мусор у входа', '21 10 2026', 'ОБ-000042']) {
    await submit(query);
    expect(new URLSearchParams(lastSearch().split('?')[1]).get('q')).toBe(query);
    expect(new URLSearchParams(lastSearch().split('?')[1]).get('page')).toBe('1');
  }
  await act(async () => {element.querySelectorAll<HTMLButtonElement>('[role=tab]')[1].click(); await tick();});
  await act(async () => {
    const status = element.querySelector<HTMLSelectElement>('.appeal-list-filters select')!;
    status.value = 'SPAM'; status.dispatchEvent(new Event('change', {bubbles: true})); await tick();
  });
  expect(Object.fromEntries(new URLSearchParams(lastSearch().split('?')[1]))).toMatchObject({q: 'ОБ-000042', archived: 'true', status: 'SPAM', page: '1'});
  await act(async () => {element.querySelector<HTMLButtonElement>('[aria-label="Очистить поиск"]')!.click(); await tick();});
  const params = new URLSearchParams(lastSearch().split('?')[1]);
  expect(params.has('q')).toBe(false); expect(params.get('status')).toBe('SPAM'); expect(params.get('archived')).toBe('true');
});

it('keeps the request separate from processing and retains all drafts when switching tabs', async () => {
  await act(async () => {root.render(<OwnerAppeals organization endpoint="/appeals"/>); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  const request = element.querySelector<HTMLElement>('#appeal-panel-request')!;
  const work = element.querySelector<HTMLElement>('#appeal-panel-work')!;
  expect(request.hidden).toBe(false); expect(work.hidden).toBe(true);
  expect(request.textContent).toContain('Описание жителя');
  expect(request.querySelector('.appeal-request-copy > .owner-appeal-edit')).not.toBeNull();
  expect(work.querySelector('.owner-appeal-edit')).toBeNull();
  await act(async () => {element.querySelector<HTMLButtonElement>('.appeal-go-work')!.click();});
  expect(request.hidden).toBe(true); expect(work.hidden).toBe(false);
  const fields = [
    [element.querySelector<HTMLTextAreaElement>('.owner-appeal-edit textarea')!, 'Черновик внутренней заметки'],
    [element.querySelector<HTMLTextAreaElement>('[placeholder="Результат рассмотрения обращения"]')!, 'Черновик публичного ответа'],
    [element.querySelector<HTMLTextAreaElement>('[aria-label="Сообщение по обращению"]')!, 'Неотправленное сообщение'],
  ] as const;
  await act(async () => {
    for (const [field, text] of fields) {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, text);
      field.dispatchEvent(new Event('input', {bubbles: true}));
    }
  });
  await act(async () => {element.querySelector<HTMLButtonElement>('#appeal-tab-request')!.click();});
  expect(request.hidden).toBe(false); expect(work.hidden).toBe(true);
  await act(async () => {element.querySelector<HTMLButtonElement>('#appeal-tab-work')!.click();});
  for (const [field, text] of fields) {expect(field.isConnected).toBe(true); expect(field.value).toBe(text);}
  expect(vi.mocked(api).mock.calls.filter(([, method]) => method === 'POST')).toHaveLength(0);
});
