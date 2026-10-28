// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Wall from './Wall';
import { publicRequest } from './requests';

vi.mock('./requests', () => ({publicRequest: vi.fn()}));
let root: Root, element: HTMLDivElement;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const organizations = [{id: 'one', city: 'Сургут', name: 'Уборка города', work_types: [], territories: [], color: '#2563eb'}];
const response = {total: 1, page: 1, page_size: 20, items: [{id: 1, number: 'ОБ-000001', organization_name: 'Уборка города', address: 'Ленина, 10',
  place: 'У входа', category: 'BIN_EMPTYING', status: 'RESOLVED', description: 'Мусор возле урны', created_at: new Date().toISOString(),
  contact: 'private-contact', owner_note: 'private-note', task: {instruction: 'private-instruction'}, photos: [],
  response: {comment: 'Урну очистили', at: new Date().toISOString(), photos: [{id: 'result', url: '/public-result', preview_url: '/public-preview'}]}}]};
beforeEach(() => {
  vi.clearAllMocks(); (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
  vi.mocked(publicRequest).mockResolvedValue(response);
});
afterEach(async () => {await act(async () => root.unmount()); element.remove();});

it('renders the complaint and public administrator result without personal or private task fields', async () => {
  await act(async () => {root.render(<Wall city="Сургут" organizations={organizations} revision={0}/>); await tick();});
  expect(element.textContent).toContain('Переполненная урна'); expect(element.textContent).toContain('Урну очистили');
  expect(element.textContent).not.toContain('private-');
  expect(element.querySelector('img')).toBeNull();
  await act(async () => {element.querySelector<HTMLButtonElement>('.appeal-photo-toggle')!.click(); await tick();});
  expect(element.querySelector<HTMLAnchorElement>('a')!.getAttribute('href')).toBe('/public-result');
  const select = element.querySelector<HTMLSelectElement>('select')!;
  await act(async () => {select.value = 'one'; select.dispatchEvent(new Event('change', {bubbles: true})); await tick();});
  const path = vi.mocked(publicRequest).mock.calls.at(-1)![0];
  expect(new URLSearchParams(path.split('?')[1]).get('organization_id')).toBe('one');
  expect(new URLSearchParams(path.split('?')[1]).get('city')).toBe('Сургут');
});

it('removes spam cards and their images when the wall refreshes', async () => {
  await act(async () => {root.render(<Wall city="Сургут" organizations={organizations} revision={0}/>); await tick();});
  vi.mocked(publicRequest).mockResolvedValue({...response, items: [], total: 0});
  await act(async () => {element.querySelector<HTMLButtonElement>('[aria-label="Обновить стену"]')!.click(); await tick();});
  expect(element.querySelector('.signal-wall-card')).toBeNull(); expect(element.querySelector('img')).toBeNull();
});

it('uses one search field for words and dates and keeps city and organization filters', async () => {
  await act(async () => {root.render(<Wall city="Сургут" organizations={organizations} revision={0}/>); await tick();});
  const input = element.querySelector<HTMLInputElement>('input[type=search]')!;
  expect(element.querySelector('input[type=date]')).toBeNull();
  for (const query of ['Мусор возле урны', '21 10 2026', '21.10.2026']) {
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, query);
      input.dispatchEvent(new Event('input', {bubbles: true}));
    });
    await act(async () => {element.querySelector('form[role=search]')!.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); await tick();});
    const params = new URLSearchParams(vi.mocked(publicRequest).mock.calls.at(-1)![0].split('?')[1]);
    expect(params.get('q')).toBe(query); expect(params.get('city')).toBe('Сургут'); expect(params.get('organization_id')).toBe('one'); expect(params.get('page')).toBe('1');
  }
  await act(async () => {element.querySelector<HTMLButtonElement>('[aria-label="Очистить поиск"]')!.click(); await tick();});
  expect(new URLSearchParams(vi.mocked(publicRequest).mock.calls.at(-1)![0].split('?')[1]).has('q')).toBe(false);
});
