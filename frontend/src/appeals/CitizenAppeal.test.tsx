// @vitest-environment jsdom
import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import CitizenAppeal from './CitizenAppeal';
import { AppealRequestError, publicRequest } from './requests';
import { EMPTY_FORM, loadDraft, saveDraft } from './drafts';
import type { AppealDraft } from './drafts';

vi.mock('./requests', async () => ({...await vi.importActual('./requests'), publicRequest: vi.fn()}));
vi.mock('./drafts', async () => ({...await vi.importActual('./drafts'), loadDraft: vi.fn(), saveDraft: vi.fn(async () => {}), clearDraft: vi.fn(async () => {})}));
vi.mock('./TerritoryMap', () => ({default: () => null}));
const organizationId = '11111111-1111-4111-8111-111111111111';
const catalog = {yandex_maps_api_key: '', organizations: [
  {id: organizationId, name: 'Уборка города', city: 'Сургут', color: '#2563eb', work_types: [{code: 'waste', name: 'Вывоз мусора'}], territories: []},
  {id: '22222222-2222-4222-8222-222222222222', name: 'Дороги города', city: 'Сургут', color: '#d97706', work_types: [{code: 'roads', name: 'Ремонт дорог'}], territories: []},
  {id: '33333333-3333-4333-8333-333333333333', name: 'Свет', city: 'Тюмень', color: '#15803d', work_types: [{code: 'light', name: 'Освещение'}], territories: []},
]};
let root: Root, element: HTMLDivElement;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
function draft(pending = false): AppealDraft {
  return {form: {...EMPTY_FORM, city: 'Сургут', organization_id: organizationId, address: 'Ленина, 10', place: 'У входа', category: 'waste', description: 'Мусор возле урны', contact: 'Контакт жителя'},
    token: 'restored-camera-token', pending, savedAt: Date.now(), photos: [{id: 'one', blob: new Blob(['frame'], {type: 'image/jpeg'}), preview: new Blob(['preview'], {type: 'image/jpeg'}),
      capture: {captured_at: new Date().toISOString(), position_at: new Date().toISOString(), latitude: 61.1, longitude: 72.5, accuracy: 8}}]};
}
const resumed = () => ({token: 'restored-camera-token', server_time: new Date().toISOString(), expires_at: new Date(Date.now() + 1800_000).toISOString(), timezone: 'Asia/Yekaterinburg', expired: false, submitted: null});
const button = () => element.querySelector<HTMLButtonElement>('.citizen-submit button')!;
async function mount(value: AppealDraft | null) {
  vi.mocked(loadDraft).mockResolvedValue(value);
  await act(async () => {root.render(<StrictMode><CitizenAppeal/></StrictMode>); await tick();});
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(publicRequest).mockResolvedValue(catalog);
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
  Object.defineProperty(URL, 'createObjectURL', {configurable: true, value: vi.fn(() => 'blob:restored-frame')});
  Object.defineProperty(URL, 'revokeObjectURL', {configurable: true, value: vi.fn()});
});
afterEach(async () => {await act(async () => {root.unmount(); await tick();}); element.remove(); vi.restoreAllMocks();});

it('restores a camera-only draft with its original token after a mobile tab reload', async () => {
  await mount(draft());
  expect(element.textContent).toContain('Восстановили ваш черновик');
  expect(element.querySelector<HTMLSelectElement>('select[autocomplete="address-level2"]')!.value).toBe('Сургут');
  expect(element.querySelectorAll('.citizen-photo img')).toHaveLength(1);
  expect(element.querySelector('input[type=file]')).toBeNull(); expect(button().disabled).toBe(false);
});

it('freezes an uncertain upload and confirms its receipt without creating another submission', async () => {
  let uploaded = false;
  vi.mocked(publicRequest).mockImplementation(async path => {
    if (path === '/catalog') return catalog;
    if (path.endsWith('/resume')) return uploaded ? {...resumed(), submitted: {number: 'ОБ-000042'}} : resumed();
    uploaded = true; throw new AppealRequestError('Соединение прервалось');
  });
  await mount(draft());
  await act(async () => {button().click(); await tick();});
  expect(button().textContent).toContain('Проверить отправку');
  expect(element.querySelector('fieldset')!.disabled).toBe(true);
  const uploads = vi.mocked(publicRequest).mock.calls.filter(call => call[0] === '').length;
  expect(uploads).toBe(1);
  await act(async () => {button().click(); await tick();});
  expect(element.textContent).toContain('Ваше обращение получено'); expect(element.textContent).toContain('ОБ-000042');
  expect(vi.mocked(publicRequest).mock.calls.filter(call => call[0] === '')).toHaveLength(1);
  const saved = vi.mocked(saveDraft).mock.calls.at(-1)![0];
  expect(saved.photos).toEqual([]); expect(saved.form.contact).toBe(''); expect(saved.receipt).toBe('ОБ-000042');
});

it('restores an interrupted upload locked and retries exactly the same camera photos', async () => {
  vi.mocked(publicRequest).mockImplementation(async path => path === '/catalog' ? catalog : path.endsWith('/resume') ? resumed() : {number: 'ОБ-000043'});
  await mount(draft(true));
  expect(element.querySelector('fieldset')!.disabled).toBe(true);
  await act(async () => {button().click(); await tick();});
  const upload = vi.mocked(publicRequest).mock.calls.find(call => call[0] === '')!;
  expect(upload[1].headers).toEqual({'X-Capture-Token': 'restored-camera-token'});
  const form = upload[1].body as FormData;
  expect(JSON.parse(form.get('metadata') as string).capture_source).toBe('camera');
  expect(form.getAll('photos')).toHaveLength(1);
});

it('unlocks a definitely rejected upload and retains the questionnaire and photo', async () => {
  vi.mocked(publicRequest).mockImplementation(async path => {
    if (path === '/catalog') return catalog;
    if (path.endsWith('/resume')) return resumed();
    throw new AppealRequestError('Уточните анкету', 422);
  });
  await mount(draft()); await act(async () => {button().click(); await tick();});
  expect(element.querySelector('fieldset')!.disabled).toBe(false);
  expect(element.querySelectorAll('.citizen-photo img')).toHaveLength(1);
  expect(element.textContent).toContain('Уточните анкету');
});

it('only offers registered cities and resets work type when selecting another organization', async () => {
  await mount(draft());
  const selects = () => element.querySelectorAll<HTMLSelectElement>('.citizen-fields select');
  expect([...selects()[0].options].map(option => option.value)).toEqual(['', 'Сургут', 'Тюмень']);
  expect([...selects()[1].options].map(option => option.text)).toEqual(['Выберите организацию', 'Уборка города', 'Дороги города']);
  expect([...selects()[2].options].map(option => option.value)).toEqual(['', 'waste']);
  await act(async () => {selects()[1].value = catalog.organizations[1].id; selects()[1].dispatchEvent(new Event('change', {bubbles: true}));});
  expect(selects()[2].value).toBe(''); expect([...selects()[2].options].map(option => option.value)).toEqual(['', 'roads']);
  expect(button().disabled).toBe(true);
  await act(async () => {selects()[0].value = 'Тюмень'; selects()[0].dispatchEvent(new Event('change', {bubbles: true}));});
  expect(selects()[1].value).toBe(''); expect(selects()[2].disabled).toBe(true);
  expect(element.querySelectorAll('.citizen-photo img')).toHaveLength(1);
  expect(element.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe('Мусор возле урны');
});

it('requires correcting an old unavailable recipient without discarding text or camera photos', async () => {
  const old = draft(); old.form.city = 'Несуществующий город';
  await mount(old);
  expect(button().disabled).toBe(true);
  expect(element.querySelector<HTMLSelectElement>('select[autocomplete="address-level2"]')!.selectedOptions[0].text).toContain('недоступен');
  expect(element.querySelectorAll('.citizen-photo img')).toHaveLength(1);
});
