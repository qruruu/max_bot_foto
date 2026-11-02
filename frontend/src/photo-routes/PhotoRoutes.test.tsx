// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import PhotoRoutes from './PhotoRoutes';

vi.mock('../api', () => ({api: vi.fn(), query: (value: Record<string, string>) => new URLSearchParams(value).toString()}));
vi.mock('../App', () => ({useApp: () => ({user: {role: 'ADMIN_OPERATOR'}, meta: {today: '2026-11-02', yandex_maps_api_key: ''}, notify: vi.fn()}), ErrorBox: () => null}));
vi.mock('../theme', () => ({useTheme: () => ({theme: 'dark'})}));
vi.mock('../yandexMaps', () => ({loadYandexMaps: () => Promise.reject(new Error('Карта не нужна в проверке формы'))}));

(globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
const territory = {type: 'Feature', geometry: {type: 'Polygon', coordinates: []}, properties: {id: 1, name: 'Сквер', active: true}};
const plan = {district_id: 1, version: 1, enabled: true, chat_ids: [1], paths: [[[72.6, 61.1], [72.601, 61.1]]], buildings: [], buildings_source: 'manual', snap_m: 25, max_gap_minutes: 45};
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const element = document.createElement('div');
document.body.append(element);
let root = createRoot(element);
afterEach(async () => {await act(async () => root.unmount()); root = createRoot(element); vi.clearAllMocks();});

function catalogue(plans = [plan]) {
  vi.mocked(api).mockImplementation(async path => path === '/photo-routes'
    ? {plans, territories: [territory], chats: [{id: 1, name: 'Уборка'}, {id: 2, name: 'Другой чат'}]}
    : {version: 1, remaining_percent: 50, total_m: 100, covered_m: 50, remaining_m: 50, matched_photos: 2, photo_count: 2, unknown_time: 0, diagnostics: {}, photos: [], covered: {type: 'GeometryCollection', geometries: []}, remaining: {type: 'GeometryCollection', geometries: []}});
}

it('only offers enabled chats in the report and supports day and range modes', async () => {
  catalogue();
  await act(async () => {root.render(<MemoryRouter><PhotoRoutes/></MemoryRouter>); await tick();});
  await act(async () => {await tick();});
  const selects = element.querySelectorAll<HTMLSelectElement>('select');
  expect(selects[1].textContent).toContain('Уборка');
  expect(selects[1].textContent).not.toContain('Другой чат');
  expect(element.textContent).toContain('50%');
  expect(element.querySelectorAll('input[type=date]')).toHaveLength(1);
  await act(async () => {selects[2].value = 'period'; selects[2].dispatchEvent(new Event('change', {bubbles: true})); await tick();});
  expect(element.querySelectorAll('input[type=date]')).toHaveLength(2);
  expect(vi.mocked(api).mock.calls.some(([path]) => path.includes('date_from=2026-11-02&date_to=2026-11-02'))).toBe(true);
});

it('does not enable an existing plan until the administrator reviews buildings', async () => {
  catalogue();
  await act(async () => {root.render(<MemoryRouter><PhotoRoutes/></MemoryRouter>); await tick();});
  const button = (text: string) => [...element.querySelectorAll('button')].find(b => b.textContent?.includes(text))!;
  await act(async () => button('Настроить маршрут').click());
  expect(button('Сохранить').disabled).toBe(true);
  const review = [...element.querySelectorAll<HTMLLabelElement>('label')].find(l => l.textContent?.includes('Контуры домов и путь проверены'))!.querySelector('input')!;
  await act(async () => review.click());
  expect(button('Сохранить').disabled).toBe(false);
  await act(async () => button('Сохранить').click());
  expect(api).toHaveBeenCalledWith('/photo-routes/1', 'PUT', expect.objectContaining({chat_ids: [1], buildings_checked: true, version: 1}));
});

it('does not request coverage when the feature has not been configured', async () => {
  catalogue([]);
  await act(async () => {root.render(<MemoryRouter><PhotoRoutes/></MemoryRouter>); await tick();});
  expect(element.textContent).toContain('Маршрут ещё не включён');
  expect(vi.mocked(api).mock.calls.some(([path]) => path.includes('/coverage'))).toBe(false);
});
