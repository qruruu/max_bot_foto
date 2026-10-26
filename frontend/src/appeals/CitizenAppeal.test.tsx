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
vi.mock('../version', () => ({watchVersion: vi.fn((_version: string, onChange: (available: boolean) => void) => {onChange(true); return () => {};})}));
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
afterEach(async () => {await act(async () => {root.unmount(); await tick();}); element.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs();});

function enableReleaseNotice() {
  vi.stubEnv('DEV', false);
  const browser = window, reload = vi.fn();
  vi.stubGlobal('window', new Proxy(browser, {get(target, key) {
    if (key === 'location') return {reload};
    const value = Reflect.get(target, key, target);
    return typeof value === 'function' ? value.bind(target) : value;
  }}));
  return reload;
}

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
  expect(selects()).toHaveLength(2);
  expect(element.querySelector('[data-field="category"]')!.textContent).toContain('Вывоз мусора');
  await act(async () => {selects()[1].value = catalog.organizations[1].id; selects()[1].dispatchEvent(new Event('change', {bubbles: true}));});
  expect(element.querySelector('[data-field="category"]')!.textContent).toContain('Ремонт дорог');
  expect(button().disabled).toBe(false);
  await act(async () => {selects()[0].value = 'Тюмень'; selects()[0].dispatchEvent(new Event('change', {bubbles: true}));});
  expect(selects()).toHaveLength(1);
  expect(element.querySelector('[data-field="organization_id"]')!.textContent).toContain('Свет');
  expect(element.querySelector('[data-field="category"]')!.textContent).toContain('Освещение');
  expect(element.querySelectorAll('.citizen-photo img')).toHaveLength(1);
  expect(element.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe('Мусор возле урны');
});

it('requires correcting an old unavailable recipient without discarding text or camera photos', async () => {
  const old = draft(); old.form.city = 'Несуществующий город';
  await mount(old);
  expect(button().disabled).toBe(true);
  expect(element.querySelector<HTMLSelectElement>('select[autocomplete="address-level2"]')!.value).toBe('');
  expect(element.textContent).not.toContain('Несуществующий город');
  expect(element.querySelector('select[name="organization_id"]')).toBeNull();
  expect(element.querySelectorAll('.citizen-photo img')).toHaveLength(1);
});

it('automatically fills a sole city, organization and work type and submits those exact identifiers', async () => {
  const single = {...catalog, organizations: [catalog.organizations[0]]};
  vi.mocked(publicRequest).mockImplementation(async path => path === '/catalog' ? single : path.endsWith('/resume') ? resumed() : {number: 'ОБ-000044'});
  const restored = draft(); restored.form = {...restored.form, city: '', organization_id: '', category: ''};
  await mount(restored);
  expect(element.querySelectorAll('select')).toHaveLength(0);
  expect(element.querySelector('[data-field="city"]')!.textContent).toBe('ГородСургут');
  expect(element.querySelector('[data-field="organization_id"]')!.textContent).toContain('Уборка города');
  expect(element.querySelector('[data-field="category"]')!.textContent).toContain('Вывоз мусора');
  expect(button().disabled).toBe(false);
  await act(async () => {button().click(); await tick();});
  const upload = vi.mocked(publicRequest).mock.calls.find(call => call[0] === '')!;
  const metadata = JSON.parse((upload[1].body as FormData).get('metadata') as string);
  expect(metadata).toMatchObject({city: 'Сургут', organization_id: organizationId, category: 'waste'});
});

it('shows a selector only for work types when a sole organization has several', async () => {
  const single = {...catalog, organizations: [{...catalog.organizations[0], work_types: [
    ...catalog.organizations[0].work_types, {code: 'cleaning', name: 'Уборка территории'},
  ]}]};
  vi.mocked(publicRequest).mockResolvedValue(single);
  await mount(null);
  const select = element.querySelector<HTMLSelectElement>('select[name="category"]')!;
  expect(element.querySelectorAll('select')).toHaveLength(1);
  expect([...select.options].map(option => option.value)).toEqual(['', 'waste', 'cleaning']);
  expect(select.value).toBe('');
  expect(element.querySelector<HTMLButtonElement>('.citizen-add-photo')!.disabled).toBe(true);
  await act(async () => {select.value = 'cleaning'; select.dispatchEvent(new Event('change', {bubbles: true}));});
  expect(element.querySelector<HTMLButtonElement>('.citizen-add-photo')!.disabled).toBe(false);
});

it('does not rewrite the frozen recipient when only another organization is now available', async () => {
  const single = {...catalog, organizations: [catalog.organizations[2]]};
  vi.mocked(publicRequest).mockImplementation(async path => path === '/catalog' ? single : path.endsWith('/resume') ? resumed() : {number: 'ОБ-000045'});
  await mount(draft(true));
  await act(async () => {button().click(); await tick();});
  const upload = vi.mocked(publicRequest).mock.calls.find(call => call[0] === '')!;
  expect(JSON.parse((upload[1].body as FormData).get('metadata') as string)).toMatchObject({city: 'Сургут', organization_id: organizationId, category: 'waste'});
});

it('does not render empty city, organization or work selectors before they exist', async () => {
  vi.mocked(publicRequest).mockResolvedValue({...catalog, organizations: []});
  await mount(null);
  expect(element.querySelectorAll('select')).toHaveLength(0);
  expect(element.textContent).toContain('Пока нет организаций');
  expect(button().disabled).toBe(true);
});

it('introduces choices when the refreshed catalog gains cities, organizations and work types', async () => {
  const expanded = {...catalog, organizations: [{...catalog.organizations[0], work_types: [
    ...catalog.organizations[0].work_types, {code: 'cleaning', name: 'Уборка территории'},
  ]}, ...catalog.organizations.slice(1)]};
  let changed = false;
  vi.mocked(publicRequest).mockImplementation(async path => {
    if (path === '/catalog') return changed ? expanded : {...catalog, organizations: [catalog.organizations[0]]};
    if (path.endsWith('/resume')) return resumed();
    changed = true; throw new AppealRequestError('Справочник изменился', 422);
  });
  await mount(draft());
  expect(element.querySelectorAll('select')).toHaveLength(0);
  await act(async () => {button().click(); await tick();});
  expect(element.querySelectorAll('select')).toHaveLength(3);
  expect(element.querySelector<HTMLSelectElement>('select[name="city"]')!.value).toBe('Сургут');
  expect(element.querySelector<HTMLSelectElement>('select[name="organization_id"]')!.value).toBe(organizationId);
  expect(element.querySelector<HTMLSelectElement>('select[name="category"]')!.value).toBe('waste');
  expect(element.querySelectorAll('.citizen-photo img')).toHaveLength(1);
});

it('waits for the complete frozen draft to be saved before loading a new release', async () => {
  const reload = enableReleaseNotice(), original = draft(true);
  await mount(original);
  let finishSaving!: () => void;
  vi.mocked(saveDraft).mockImplementationOnce(() => new Promise<void>(resolve => {finishSaving = resolve;}));
  const update = element.querySelector<HTMLButtonElement>('.update-notice button')!;
  expect(update.textContent).toBe('Обновить');
  await act(async () => {update.click(); update.click(); await tick();});
  expect(update.disabled).toBe(true); expect(reload).not.toHaveBeenCalled();
  const saved = vi.mocked(saveDraft).mock.calls.at(-1)![0];
  expect(saved.form).toEqual(original.form); expect(saved.photos).toEqual(original.photos);
  expect(saved.pending).toBe(true); expect(saved.token).toBe(original.token);
  await act(async () => {finishSaving(); await tick();});
  expect(reload).toHaveBeenCalledTimes(1);
  const leaving = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(leaving);
  expect(leaving.defaultPrevented).toBe(false);
});

it('keeps the form and photo open when saving before an update fails and permits retry', async () => {
  const reload = enableReleaseNotice();
  await mount(draft());
  vi.mocked(saveDraft).mockRejectedValueOnce(new Error('Storage full'));
  const update = () => element.querySelector<HTMLButtonElement>('.update-notice button')!;
  await act(async () => {update().click(); await tick();});
  expect(reload).not.toHaveBeenCalled(); expect(update().disabled).toBe(false);
  expect(element.querySelector('.update-error')!.textContent).toContain('Не удалось сохранить черновик');
  expect(element.querySelectorAll('.citizen-photo img')).toHaveLength(1);
  expect(element.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe('Мусор возле урны');
  const leaving = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(leaving);
  expect(leaving.defaultPrevented).toBe(true);
  await act(async () => {update().click(); await tick();});
  expect(reload).toHaveBeenCalledTimes(1);
});
