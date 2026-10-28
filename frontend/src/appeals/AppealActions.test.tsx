// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AppealActions from './AppealActions';
import type { WorkflowAppeal } from './AppealActions';
import { api } from '../api';

vi.mock('../api', () => ({api: vi.fn()}));
let root: Root, element: HTMLDivElement;
const tick = () => new Promise(resolve => setTimeout(resolve, 0)), changed = vi.fn();
const appeal: WorkflowAppeal = {id: 42, version: 3, status: 'COMPLETED', is_public: true, can_manage: true,
  task: {id: 1, operator_id: 7, operator_name: 'Исполнитель', status: 'COMPLETED', result_comment: 'Готово', created_at: '',
    photos: [{id: 'photo', url: '/result', preview_url: '/preview'}]}};
beforeEach(() => {
  vi.clearAllMocks(); vi.mocked(api).mockResolvedValue([]);
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
});
afterEach(async () => {await act(async () => root.unmount()); element.remove();});
async function mount(value = appeal) {await act(async () => {root.render(<AppealActions appeal={value} endpoint="/appeals" readOnly={false} changed={changed}/>); await tick();});}
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
