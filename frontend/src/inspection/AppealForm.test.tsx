// @vitest-environment jsdom
import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import InspectionAppealForm from './AppealForm';
import { api, ApiError } from '../api';
import { EMPTY_FORM, clearDraft, loadDraft, saveDraft } from '../appeals/drafts';
import type { AppealDraft } from '../appeals/drafts';

vi.mock('../api', async () => ({...await vi.importActual('../api'), api: vi.fn()}));
vi.mock('../appeals/drafts', async () => ({...await vi.importActual('../appeals/drafts'), loadDraft: vi.fn(), saveDraft: vi.fn(async () => {}), clearDraft: vi.fn(async () => {})}));
vi.mock('../appeals/ProblemMap', () => ({default: ({onPoint, disabled}: {onPoint: (point: [number, number]) => void; disabled: boolean}) => <button type="button" disabled={disabled} data-map onClick={() => onPoint([72.6, 61.1])}>Отметить место</button>}));
const organizationId = '11111111-1111-4111-8111-111111111111', addressId = '22222222-2222-4222-8222-222222222222';
const clientId = '33333333-3333-4333-8333-333333333333', endpoint = '/inspection/organizations/' + organizationId + '/appeals';
const catalog = {organization: {id: organizationId, name: 'Демо-организация', city: 'Сургут', color: '#2563eb',
  work_types: [{code: 'BIN_EMPTYING', name: 'УРНЫ'}], addresses: [{id: addressId, label: '11А мкр', district_id: 1}], territories: []}, yandex_maps_api_key: ''};
const receipt = {id: 42, number: 'ОБ-000042', is_public: false};
const storageKey = 'inspector:7:' + organizationId;
let root: Root, element: HTMLDivElement;
const tick = () => new Promise(resolve => setTimeout(resolve, 0)), created = vi.fn();
function draft(pending = false): AppealDraft {
  return {form: {...EMPTY_FORM, organization_id: organizationId, city: 'Сургут', address_id: addressId, address: '11А мкр', latitude: 61.1, longitude: 72.6,
    category: 'BIN_EMPTYING', description: 'Переполненная урна на участке'}, clientId, token: null, pending, savedAt: Date.now(),
    photos: [{id: 'photo', blob: new Blob(['photo'], {type: 'image/jpeg'}), preview: new Blob(['preview'])}]};
}
async function mount(value: AppealDraft | null = null) {
  vi.mocked(loadDraft).mockResolvedValue(value);
  await act(async () => {root.render(<StrictMode><InspectionAppealForm organizationId={organizationId} inspectorId={7} created={created}/></StrictMode>); await tick();});
}
const send = () => element.querySelector<HTMLButtonElement>('form>button')!;
const click = async (button: HTMLButtonElement) => {await act(async () => {button.click(); await tick();});};
beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
  Object.defineProperty(URL, 'createObjectURL', {configurable: true, value: vi.fn(() => 'blob:private-photo')});
  Object.defineProperty(URL, 'revokeObjectURL', {configurable: true, value: vi.fn()});
  vi.mocked(api).mockImplementation(async (path, method) => path.endsWith('/catalog') ? catalog : method === 'POST' ? receipt : Promise.reject(new ApiError(404, 'Не найдено')));
});
afterEach(async () => {await act(async () => root.unmount()); element.remove(); vi.restoreAllMocks();});

it('requires an allowed address and map point and keeps inspector drafts separate from public drafts', async () => {
  await mount();
  expect(loadDraft).toHaveBeenCalledWith(storageKey);
  expect(element.textContent).toContain('Только в «Метке»');
  expect(element.textContent).toContain('На стене «Сигнала» они не появятся');
  expect(element.textContent).not.toContain('Контакт для уточнений');
  expect(element.querySelectorAll('fieldset')[1].disabled).toBe(true); expect(send().disabled).toBe(true);
  expect(element.querySelector('[data-field="address_id"]')!.textContent).toContain('11А мкр');
  await click(element.querySelector<HTMLButtonElement>('[data-map]')!);
  expect(element.querySelectorAll('fieldset')[1].disabled).toBe(false);
  expect(vi.mocked(saveDraft).mock.calls.at(-1)![1]).toBe(storageKey);
});

it('submits the same workflow fields through the authenticated private endpoint and leaves the receipt open', async () => {
  await mount(draft()); await click(send());
  const call = vi.mocked(api).mock.calls.find(([, method]) => method === 'POST')!;
  expect(call[0]).toBe(endpoint);
  const data = call[2] as FormData, metadata = JSON.parse(data.get('metadata') as string);
  expect(metadata).toMatchObject({client_id: clientId, organization_id: organizationId, address_id: addressId, latitude: 61.1, longitude: 72.6});
  expect(metadata).not.toHaveProperty('is_public'); expect(metadata).not.toHaveProperty('public_consent');
  expect(metadata).not.toHaveProperty('contact');
  expect(data.getAll('photos')).toHaveLength(1); expect(clearDraft).toHaveBeenCalledWith(storageKey);
  expect(element.querySelector('.inspector-appeal-form')).not.toBeNull();
  expect(element.querySelector('[role=status]')!.textContent).toContain('ОБ-000042');
  expect(created).toHaveBeenCalledTimes(1);
});

it('freezes an uncertain send and checks its original client UUID without uploading a duplicate', async () => {
  let sent = false;
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (path.endsWith('/catalog')) return catalog;
    if (path.endsWith('/submissions/' + clientId)) return receipt;
    if (method === 'POST') {sent = true; throw new TypeError('Connection lost');}
    throw new Error('Unexpected ' + path);
  });
  await mount(draft()); await click(send());
  expect(sent).toBe(true); expect(send().textContent).toContain('Проверить отправку');
  expect(element.querySelector('fieldset')!.disabled).toBe(true);
  expect(vi.mocked(saveDraft).mock.calls.some(([saved, key]) => key === storageKey && saved.pending && saved.clientId === clientId)).toBe(true);
  await click(send());
  expect(element.textContent).toContain('ОБ-000042');
  expect(vi.mocked(api).mock.calls.filter(([, method]) => method === 'POST')).toHaveLength(1);
});

it('recovers a pending receipt even when the organization address catalog has changed', async () => {
  vi.mocked(api).mockImplementation(async path => path.endsWith('/catalog') ? {...catalog, organization: {...catalog.organization, addresses: []}} : receipt);
  await mount(draft(true)); await click(send());
  expect(vi.mocked(api)).toHaveBeenCalledWith(endpoint + '/submissions/' + clientId);
  expect(vi.mocked(api).mock.calls.filter(([, method]) => method === 'POST')).toHaveLength(0);
  expect(element.textContent).toContain('ОБ-000042');
});
