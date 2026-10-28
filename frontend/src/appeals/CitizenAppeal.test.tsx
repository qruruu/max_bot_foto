// @vitest-environment jsdom
import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import CitizenAppeal from './CitizenAppeal';
import { AppealRequestError, publicRequest } from './requests';
import { EMPTY_FORM, loadDraft, saveDraft } from './drafts';
import type { AppealDraft } from './drafts';
import { galleryPhoto } from './gallery';

vi.mock('./requests', async () => ({...await vi.importActual('./requests'), publicRequest: vi.fn()}));
vi.mock('./drafts', async () => ({...await vi.importActual('./drafts'), loadDraft: vi.fn(), saveDraft: vi.fn(async () => {}), clearDraft: vi.fn(async () => {})}));
vi.mock('./gallery', () => ({galleryPhoto: vi.fn()}));
vi.mock('./ProblemMap', () => ({default: ({onPoint, disabled}: {onPoint: (point: [number, number]) => void; disabled: boolean}) => <button disabled={disabled} type="button" data-map onClick={() => onPoint([72.6, 61.1])}>Отметить место на карте</button>}));
vi.mock('../version', () => ({watchVersion: vi.fn((_version: string, onChange: (available: boolean) => void) => {onChange(true); return () => {};})}));
const organizationId = '11111111-1111-4111-8111-111111111111', addressId = '22222222-2222-4222-8222-222222222222';
const catalog = {yandex_maps_api_key: '', organizations: [
  {id: organizationId, name: 'Уборка города', city: 'Сургут', color: '#2563eb',
    work_types: [{code: 'BIN_EMPTYING', name: 'УРНЫ'}, {code: 'DRAIN_CLEANING', name: 'КОЛОДЦЫ'}],
    addresses: [{id: addressId, label: 'Ленина, 10', district_id: 1}], territories: []},
]};
const emptyWall = {items: [], total: 0, page: 1, page_size: 20};
let root: Root, element: HTMLDivElement;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
function draft(pending = false): AppealDraft {
  return {form: {...EMPTY_FORM, city: 'Сургут', organization_id: organizationId, address_id: addressId, address: 'Ленина, 10', latitude: 61.1, longitude: 72.6,
    category: 'BIN_EMPTYING', description: 'Мусор возле урны', contact: 'private-contact'}, token: 'restored-token', pending, savedAt: Date.now(),
    photos: [{id: 'one', blob: new Blob(['photo'], {type: 'image/jpeg'}), preview: new Blob(['preview'], {type: 'image/jpeg'})}]};
}
const resumed = () => ({token: 'restored-token', expires_at: new Date(Date.now() + 1800_000).toISOString(), expired: false, submitted: null});
const submitButton = () => element.querySelector<HTMLButtonElement>('.citizen-submit button')!;
const byText = (text: string) => [...element.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.includes(text))!;
async function click(button: HTMLButtonElement) {await act(async () => {button.click(); await tick();});}
async function mount(value: AppealDraft | null) {
  vi.mocked(loadDraft).mockResolvedValue(value);
  await act(async () => {root.render(<StrictMode><CitizenAppeal/></StrictMode>); await tick();});
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(publicRequest).mockImplementation(async path => path === '/catalog' ? catalog : path.startsWith('/wall?') ? emptyWall : path.endsWith('/resume') ? resumed() : {number: 'ОБ-000042'});
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
  Object.defineProperty(URL, 'createObjectURL', {configurable: true, value: vi.fn(() => 'blob:photo')});
  Object.defineProperty(URL, 'revokeObjectURL', {configurable: true, value: vi.fn()});
});
afterEach(async () => {await act(async () => {root.unmount(); await tick();}); element.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs();});

it('opens the city wall and requires a map point before the questionnaire', async () => {
  await mount(null);
  expect(element.querySelector('h1')!.textContent).toBe('Обращения жителей');
  await click(byText('Сообщить о проблеме'));
  expect(element.querySelector('textarea')).toBeNull();
  expect(element.querySelector('[data-field="address_id"]')!.textContent).toContain('Ленина, 10');
  expect(element.querySelector('input[autocomplete="street-address"]')).toBeNull();
  expect(element.textContent).toContain('только адрес из списка обслуживаемых ею адресов');
  expect(byText('Далее').disabled).toBe(true);
  await click(element.querySelector<HTMLButtonElement>('[data-map]')!);
  await click(byText('Далее'));
  expect(element.querySelector('textarea')).not.toBeNull();
  const file = element.querySelector<HTMLInputElement>('input[type=file]')!;
  expect(file.hasAttribute('capture')).toBe(false);
  expect(element.textContent).not.toContain('КОЛОДЦЫ');
  expect(element.textContent).not.toContain('сток для дождевой воды');
  expect(element.querySelector('[data-field="category"]')!.textContent).toContain('Переполненная урна');
});

it('blocks submission for organizations without configured addresses', async () => {
  vi.mocked(publicRequest).mockImplementation(async path => path === '/catalog' ? {...catalog, organizations: [{...catalog.organizations[0], addresses: []}]} : emptyWall);
  await mount(null); await click(byText('Сообщить о проблеме'));
  expect(element.textContent).toContain('пока не добавила обслуживаемые адреса');
  expect(byText('Далее').disabled).toBe(true);
  expect(element.querySelector('[data-map]')).toBeNull();
});

it('restores gallery photos and submits map coordinates with stable organization and address identifiers', async () => {
  const short = draft(); short.form.description = 'Мусор';
  await mount(short);
  expect(element.querySelector('textarea')!.hasAttribute('minlength')).toBe(false);
  expect(element.querySelectorAll('.signal-upload-photo')).toHaveLength(1);
  expect(element.querySelector('input[type=checkbox]')).toBeNull();
  await click(submitButton());
  const upload = vi.mocked(publicRequest).mock.calls.find(call => call[0] === '/submissions')!;
  const data = upload[1].body as FormData, metadata = JSON.parse(data.get('metadata') as string);
  expect(metadata).toMatchObject({capture_source: 'gallery', organization_id: organizationId, address_id: addressId, latitude: 61.1, longitude: 72.6, category: 'BIN_EMPTYING', public_consent: true});
  expect(metadata).not.toHaveProperty('captures');
  expect(data.getAll('photos')).toHaveLength(1);
  expect(upload[1].headers).toEqual({'X-Capture-Token': 'restored-token'});
  expect(element.textContent).toContain('Обращение ОБ-000042 отправлено');
  expect(element.querySelector('h1')!.textContent).toBe('Обращения жителей');
  expect(vi.mocked(saveDraft).mock.calls.at(-1)![0].form.contact).toBe('');
});

it('returns to city choice when there are multiple cities and the old draft only contained automatic selections', async () => {
  const previous = draft(); previous.form.description = ''; previous.photos = [];
  vi.mocked(publicRequest).mockImplementation(async path => path === '/catalog' ? {...catalog, organizations: [catalog.organizations[0], {...catalog.organizations[0], id: 'second', city: 'Тюмень'}]} : emptyWall);
  await mount(previous);
  expect(element.querySelector<HTMLSelectElement>('select[name=city]')!.value).toBe('');
  expect(element.textContent).toContain('Выберите город');
});

it('keeps an uncertain send frozen and confirms receipt without uploading twice', async () => {
  let uploaded = false;
  vi.mocked(publicRequest).mockImplementation(async path => {
    if (path === '/catalog') return catalog;
    if (path.startsWith('/wall?')) return emptyWall;
    if (path.endsWith('/resume')) return uploaded ? {...resumed(), submitted: {number: 'ОБ-000043'}} : resumed();
    uploaded = true; throw new AppealRequestError('Соединение прервалось');
  });
  await mount(draft()); await click(submitButton());
  expect(submitButton().textContent).toContain('Проверить отправку');
  expect(element.querySelector('fieldset')!.disabled).toBe(true);
  await click(submitButton());
  expect(element.textContent).toContain('ОБ-000043');
  expect(vi.mocked(publicRequest).mock.calls.filter(call => call[0] === '/submissions')).toHaveLength(1);
});

it('restores a pending send with its original data even if the public catalog changed', async () => {
  const original = draft(true);
  vi.mocked(publicRequest).mockImplementation(async path => path === '/catalog' ? {...catalog, organizations: []} : path.startsWith('/wall?') ? emptyWall : path.endsWith('/resume') ? resumed() : {number: 'ОБ-000044'});
  await mount(original); await click(submitButton());
  const upload = vi.mocked(publicRequest).mock.calls.find(call => call[0] === '/submissions')!;
  expect(JSON.parse((upload[1].body as FormData).get('metadata') as string)).toMatchObject(original.form);
});

it('adds images selected from the phone without requesting camera or device coordinates', async () => {
  vi.mocked(galleryPhoto).mockResolvedValue({id: 'two', blob: new Blob(['second'], {type: 'image/jpeg'}), preview: new Blob(['preview'])});
  await mount(draft());
  const file = new File(['gallery'], 'phone.jpg', {type: 'image/jpeg'}), input = element.querySelector<HTMLInputElement>('input[type=file]')!;
  Object.defineProperty(input, 'files', {configurable: true, value: [file]});
  await act(async () => {input.dispatchEvent(new Event('change', {bubbles: true})); await tick();});
  expect(galleryPhoto).toHaveBeenCalledWith(file);
  expect(element.querySelectorAll('.signal-upload-photo')).toHaveLength(2);
});

function enableReleaseNotice() {
  vi.stubEnv('DEV', false);
  const browser = window, reload = vi.fn();
  vi.stubGlobal('window', new Proxy(browser, {get(target, key) {
    if (key === 'location') return {reload};
    const value = Reflect.get(target, key, target); return typeof value === 'function' ? value.bind(target) : value;
  }}));
  return reload;
}

it('waits for the complete draft including pending photos before loading an update', async () => {
  const reload = enableReleaseNotice(), original = draft(true); await mount(original);
  let finishSaving!: () => void;
  vi.mocked(saveDraft).mockImplementationOnce(() => new Promise<void>(resolve => {finishSaving = resolve;}));
  await click(element.querySelector<HTMLButtonElement>('.update-notice button')!);
  expect(reload).not.toHaveBeenCalled();
  const saved = vi.mocked(saveDraft).mock.calls.at(-1)![0];
  expect(saved.form).toEqual(original.form); expect(saved.photos).toEqual(original.photos); expect(saved.pending).toBe(true);
  await act(async () => {finishSaving(); await tick();});
  expect(reload).toHaveBeenCalledTimes(1);
});

it('keeps the form open when saving before an update fails and allows another attempt', async () => {
  const reload = enableReleaseNotice(); await mount(draft());
  vi.mocked(saveDraft).mockRejectedValueOnce(new Error('Storage full'));
  await click(element.querySelector<HTMLButtonElement>('.update-notice button')!);
  expect(reload).not.toHaveBeenCalled(); expect(element.querySelectorAll('.signal-upload-photo')).toHaveLength(1);
  expect(element.querySelector('.update-error')!.textContent).toContain('Не удалось сохранить черновик');
  await click(element.querySelector<HTMLButtonElement>('.update-notice button')!);
  expect(reload).toHaveBeenCalledTimes(1);
});
