// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AppealActions from './AppealActions';
import type { WorkflowAppeal } from './AppealActions';
import { api } from '../api';
import { galleryPhoto } from './gallery';

vi.mock('../api', () => ({api: vi.fn()}));
vi.mock('./gallery', () => ({galleryPhoto: vi.fn()}));
let root: Root, element: HTMLDivElement;
const tick = () => new Promise(resolve => setTimeout(resolve, 0)), changed = vi.fn();
const appeal: WorkflowAppeal = {id: 42, version: 3, status: 'COMPLETED', is_public: true, can_manage: true,
  task: {id: 1, operator_id: 7, operator_name: 'Исполнитель', status: 'COMPLETED', result_comment: 'Готово', created_at: '',
    photos: [{id: 'photo', url: '/result', preview_url: '/preview'}]}};
beforeEach(() => {
  vi.clearAllMocks(); vi.mocked(api).mockResolvedValue([]);
  vi.mocked(galleryPhoto).mockResolvedValue({id: 'prepared', blob: new Blob(['prepared'], {type: 'image/jpeg'}), preview: new Blob()});
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
});
afterEach(async () => {await act(async () => root.unmount()); element.remove();});
async function mount(value = appeal, readOnly = false) {await act(async () => {root.render(<AppealActions appeal={value} endpoint="/appeals" readOnly={readOnly} changed={changed}/>); await tick();});}
const byText = (text: string) => [...element.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.includes(text))!;
const click = async (button: HTMLButtonElement) => {await act(async () => {button.click(); await tick();});};

it('requires a separate confirmation, allows editing again, and sends selected evidence only after confirming', async () => {
  await mount();
  const answer = [...element.querySelectorAll('textarea')].at(-1)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(answer, 'Урна очищена');
    answer.dispatchEvent(new Event('input', {bubbles: true}));
    element.querySelector<HTMLInputElement>('input[type=checkbox]')!.click(); await tick();
  });
  await click(byText('Закрыть и опубликовать'));
  expect(element.querySelector('[role=alertdialog]')).not.toBeNull();
  expect(vi.mocked(api).mock.calls.filter(([, method]) => method === 'POST')).toHaveLength(0);
  await click(byText('Продолжить редактирование'));
  expect(element.querySelector('[role=alertdialog]')).toBeNull(); expect(answer.value).toBe('Урна очищена');
  await click(byText('Закрыть и опубликовать')); await click(byText('Подтвердить закрытие'));
  const call = vi.mocked(api).mock.calls.find(([, method]) => method === 'POST')!;
  expect(call[0]).toBe('/appeals/42/close');
  expect(JSON.parse((call[2] as FormData).get('metadata') as string)).toMatchObject({comment: 'Урна очищена', operator_photo_ids: ['photo'], expected_version: 3});
  expect(changed).toHaveBeenCalledTimes(1);
});

it('archives a closed complaint and restores one already archived', async () => {
  await mount({...appeal, status: 'RESOLVED'}); await click(byText('Перенести в архив'));
  expect(api).toHaveBeenCalledWith('/appeals/42/archive', 'POST', {archived: true, expected_version: 3});
  await mount({...appeal, status: 'RESOLVED', archived_at: new Date().toISOString()}); await click(byText('Вернуть из архива'));
  expect(api).toHaveBeenCalledWith('/appeals/42/archive', 'POST', {archived: false, expected_version: 3});
});

it('offers archive and restore for spam without publishing it', async () => {
  await mount({...appeal, status: 'SPAM'}); await click(byText('Перенести в архив'));
  expect(api).toHaveBeenCalledWith('/appeals/42/archive', 'POST', {archived: true, expected_version: 3});
  expect(element.textContent).toContain('На стене «Сигнала» он не появится');
  await mount({...appeal, status: 'SPAM', archived_at: new Date().toISOString()}); await click(byText('Вернуть из архива'));
  expect(api).toHaveBeenCalledWith('/appeals/42/archive', 'POST', {archived: false, expected_version: 3});
});

it('lets the operator return an active task to assigned and offers cancellation or completion with evidence', async () => {
  await mount({...appeal, status: 'IN_PROGRESS', can_manage: false, can_execute: true});
  const select = element.querySelector<HTMLSelectElement>('select')!;
  expect([...select.options].map(option => option.value)).toEqual(['ASSIGNED', 'IN_PROGRESS', 'CANCELLED', 'COMPLETED']);
  await act(async () => {select.value = 'ASSIGNED'; select.dispatchEvent(new Event('change', {bubbles: true}));});
  await click(byText('Сохранить статус задачи'));
  expect(api).toHaveBeenCalledWith('/appeals/42/task-status', 'POST', {status: 'ASSIGNED', expected_version: 3});
});

it.each(['operator', 'admin'])('prepares selected phone photos before submitting the %s result', async role => {
  await mount(role === 'operator' ? {...appeal, status: 'ASSIGNED', can_manage: false, can_execute: true} : appeal);
  if (role === 'operator') await act(async () => {
    const select = element.querySelector('select')!; select.value = 'COMPLETED'; select.dispatchEvent(new Event('change', {bubbles: true}));
  });
  const photo = new File(['phone-original'], 'IMG_3557.jpeg', {type: 'image/jpeg'});
  await act(async () => {
    const textarea = [...element.querySelectorAll('textarea')].at(-1)!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, 'Почистили');
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
    const input = element.querySelector<HTMLInputElement>('input[type=file]')!;
    Object.defineProperty(input, 'files', {value: [photo]}); input.dispatchEvent(new Event('change', {bubbles: true}));
  });
  expect(element.textContent).toContain('по 25 МБ');
  if (role === 'admin') {await click(byText('Закрыть и опубликовать')); await click(byText('Подтвердить закрытие'));}
  else await click(byText('Передать результат'));
  expect(galleryPhoto).toHaveBeenCalledWith(photo);
  const call = vi.mocked(api).mock.calls.find(([, method]) => method === 'POST')!;
  expect(call[0]).toBe(`/appeals/42/${role === 'operator' ? 'result' : 'close'}`);
  const body = call[2] as FormData, uploaded = body.get('photos') as File;
  expect(uploaded.type).toBe('image/jpeg'); expect(uploaded.name).toBe('result-1.jpg'); expect(uploaded.size).toBe(8);
  expect(JSON.parse(body.get('metadata') as string)).toMatchObject({comment: 'Почистили', expected_version: 3});
  expect(changed).toHaveBeenCalledTimes(1);
});

it('keeps the comment and selected photo after a preparation error so the operator can retry', async () => {
  vi.mocked(galleryPhoto).mockRejectedValueOnce(new Error('Одна фотография должна занимать не больше 25 МБ'));
  await mount({...appeal, status: 'ASSIGNED', can_manage: false, can_execute: true});
  await act(async () => {
    const select = element.querySelector('select')!; select.value = 'COMPLETED'; select.dispatchEvent(new Event('change', {bubbles: true}));
  });
  await act(async () => {
    const textarea = element.querySelector('textarea')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, 'Почистили'); textarea.dispatchEvent(new Event('input', {bubbles: true}));
    const input = element.querySelector('input[type=file]')!;
    Object.defineProperty(input, 'files', {value: [new File(['original'], 'phone.jpeg')]}); input.dispatchEvent(new Event('change', {bubbles: true}));
  });
  await click(byText('Передать результат'));
  expect(element.querySelector('[role=alert]')?.textContent).toContain('25 МБ');
  expect(element.querySelector('textarea')?.value).toBe('Почистили'); expect(element.textContent).toContain('Выбрано: 1');
  expect(vi.mocked(api).mock.calls.filter(([, method]) => method === 'POST')).toHaveLength(0);
  await click(byText('Передать результат')); expect(changed).toHaveBeenCalledTimes(1);
});

it('allows a checking inspector to mark completed or cancelled without exposing administrator actions', async () => {
  await mount({...appeal, status: 'NEW', task: null, can_manage: false, can_execute: false, can_set_task_status: true}, true);
  const select = element.querySelector('select')!;
  expect([...select.options].filter(option => !option.disabled).map(option => option.text)).toEqual(['Выполнена', 'Отменена']);
  await act(async () => {select.value = 'COMPLETED'; select.dispatchEvent(new Event('change', {bubbles: true}));});
  await click(byText('Сохранить статус задачи'));
  expect(api).toHaveBeenCalledWith('/appeals/42/task-status', 'POST', {status: 'COMPLETED', expected_version: 3});
  expect(element.textContent).not.toContain('Назначить исполнителя'); expect(element.textContent).not.toContain('Решение по обращению');
});

it.each(['RESOLVED', 'DECLINED'])('confirms the administrator decision %s with a required answer and optional photos', async status => {
  await mount({...appeal, task: status === 'DECLINED' ? {...appeal.task!, status: 'ASSIGNED'} : null});
  const decision = [...element.querySelectorAll('select')].find(select => [...select.options].some(option => option.value === 'DECLINED'))!;
  await act(async () => {decision.value = status; decision.dispatchEvent(new Event('change', {bubbles: true}));});
  const action = () => byText(status === 'DECLINED' ? 'Отказать и опубликовать' : 'Закрыть и опубликовать');
  expect(action().disabled).toBe(true);
  await act(async () => {
    const textarea = [...element.querySelectorAll('textarea')].at(-1)!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, 'Ответ организации'); textarea.dispatchEvent(new Event('input', {bubbles: true}));
  });
  expect(action().disabled).toBe(false); await click(action());
  expect(element.querySelector('[role=alertdialog]')?.textContent).toContain('Фотографий результата: 0');
  expect(vi.mocked(api).mock.calls.filter(([, method]) => method === 'POST')).toHaveLength(0);
  await click(byText(status === 'DECLINED' ? 'Подтвердить отказ' : 'Подтвердить закрытие'));
  const call = vi.mocked(api).mock.calls.find(([, method]) => method === 'POST')!;
  expect(call[0]).toBe('/appeals/42/close');
  expect(JSON.parse((call[2] as FormData).get('metadata') as string)).toMatchObject({status, comment: 'Ответ организации', operator_photo_ids: []});
  expect((call[2] as FormData).getAll('photos')).toHaveLength(0);
});
