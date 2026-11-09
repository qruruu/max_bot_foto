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
  HTMLDialogElement.prototype.showModal = function () {this.setAttribute('open', '');};
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
  expect(element.querySelector('dialog')).toBeNull();
  await click(byText('Закрыть обращение'));
  await click(element.querySelector<HTMLButtonElement>('dialog [aria-label="Прикрепить фото"]')!);
  await click(byText('Фото исполнителя'));
  const answer = [...element.querySelectorAll('textarea')].at(-1)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(answer, 'Урна очищена');
    answer.dispatchEvent(new Event('input', {bubbles: true}));
    element.querySelector<HTMLInputElement>('input[type=checkbox]')!.click(); await tick();
  });
  expect(element.querySelector('dialog[open]')).not.toBeNull();
  expect(vi.mocked(api).mock.calls.filter(([, method]) => method === 'POST')).toHaveLength(0);
  await click(byText('Отмена'));
  expect(element.querySelector('dialog')).toBeNull();
  await click(byText('Закрыть обращение'));
  expect(element.querySelector('dialog textarea')?.textContent).toBe('Урна очищена');
  await click(byText('Подтвердить закрытие'));
  const call = vi.mocked(api).mock.calls.find(([, method]) => method === 'POST')!;
  expect(call[0]).toBe('/appeals/42/close');
  expect(JSON.parse((call[2] as FormData).get('metadata') as string)).toMatchObject({comment: 'Урна очищена', operator_photo_ids: ['photo'], expected_version: 3});
  expect(changed).toHaveBeenCalledTimes(1);
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
  if (role === 'admin') await click(byText('Закрыть обращение'));
  const photo = new File(['phone-original'], 'IMG_3557.jpeg', {type: 'image/jpeg'});
  await act(async () => {
    const textarea = [...element.querySelectorAll('textarea')].at(-1)!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, 'Почистили');
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
    const input = element.querySelector<HTMLInputElement>('input[type=file]')!;
    Object.defineProperty(input, 'files', {value: [photo]}); input.dispatchEvent(new Event('change', {bubbles: true}));
  });
  expect(element.textContent).toContain('по 25 МБ');
  if (role === 'admin') await click(byText('Подтвердить закрытие'));
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

it.each(['RESOLVED', 'DECLINED', 'CANCELLED', 'REJECTED'])('confirms the administrator decision %s with a required answer and optional photos', async status => {
  await mount({...appeal, task: status !== 'RESOLVED' ? {...appeal.task!, status: 'ASSIGNED'} : null});
  await click(byText('Закрыть обращение'));
  const decision = element.querySelector<HTMLSelectElement>('dialog select')!;
  await act(async () => {decision.value = status; decision.dispatchEvent(new Event('change', {bubbles: true}));});
  const confirm = {
    RESOLVED: 'Подтвердить закрытие', DECLINED: 'Подтвердить отказ',
    CANCELLED: 'Подтвердить отмену', REJECTED: 'Подтвердить отклонение',
  }[status]!;
  expect(byText(confirm).disabled).toBe(true);
  await act(async () => {
    const textarea = element.querySelector<HTMLTextAreaElement>('dialog textarea')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, 'Ответ организации');
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
  });
  expect(byText(confirm).disabled).toBe(false);
  await click(byText(confirm));
  const call = vi.mocked(api).mock.calls.find(([, method]) => method === 'POST')!;
  expect(call[0]).toBe('/appeals/42/close');
  expect(JSON.parse((call[2] as FormData).get('metadata') as string)).toMatchObject({status, comment: 'Ответ организации', operator_photo_ids: []});
  expect((call[2] as FormData).getAll('photos')).toHaveLength(0);
});

it.each(['CANCELLED', 'REJECTED'])('keeps final decision %s visible after closing', async status => {
  await mount({...appeal, status, is_final: true, resolved_at: new Date().toISOString(), public_response: 'Причина завершения', response_photos: []});
  expect(element.textContent).toContain('Причина завершения');
  expect(element.textContent).not.toContain('Решение по обращению');
  expect(element.textContent).not.toContain('Перенаправить задачу');
  expect(vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/operators'))).toBe(false);

});

it.each(['CANCELLED', 'REJECTED'])('allows the administrator to finalize task result %s without changing its name', async status => {
  await mount({...appeal, status, is_final: false, resolved_at: null, task: {...appeal.task!, status}});
  await click(byText('Закрыть обращение'));
  const decision = [...element.querySelectorAll('select')].find(select => [...select.options].some(option => option.value === 'DECLINED'))!;
  expect([...decision.options].map(option => option.text)).toEqual(['Закрыть обращение', 'Отказ', 'Задача отменена', 'Исполнитель отклонил']);
});

it('offers redirection in the executor tab only when both conversations exist', async () => {
  await act(async () => {
    root.render(<AppealActions appeal={appeal} endpoint="/appeals" readOnly={false} changed={changed}
      inspectorDiscussion={<div>Переписка проверяющего</div>} discussion={<div>Переписка исполнителя</div>}/>);
    await tick();
  });
  const visible = element.querySelector('.appeal-workflow > div:not([hidden])')!;
  const executor = element.querySelector('.appeal-workflow > div[hidden]')!;
  expect(visible.textContent).toContain('Закрыть обращение');
  expect(visible.textContent).not.toContain('Перенаправить задачу');
  expect(executor.textContent).toContain('Перенаправить задачу');
});

it('saves the deadline through reassignment and collapses the form after success', async () => {
  vi.mocked(api).mockResolvedValue([{id: 7, name: 'Исполнитель'}]);
  await mount({...appeal, status: 'ASSIGNED', task: {...appeal.task!, status: 'ASSIGNED', due_date: null}});
  expect(element.textContent).not.toContain('Изменить срок');
  const redirect = byText('Перенаправить задачу');
  expect(redirect.parentElement).toBe(byText('Закрыть обращение').parentElement);
  await click(redirect);
  const editor = element.querySelector<HTMLDialogElement>('dialog')!;
  const field = editor.querySelector<HTMLInputElement>('input[type=date]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(field, '2030-12-15');
    field.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await click(byText('Назначить'));
  expect(api).toHaveBeenCalledWith('/appeals/42/assign', 'POST', {operator_id: 7, instruction: '', due_date: '2030-12-15', expected_version: 3});
  expect(element.querySelector('dialog')).toBeNull();
});
it.each(['operator','inspector'])('shows deadlines to %s without granting deadline editing',async role=>{
  await mount({...appeal,status:'ASSIGNED',can_manage:false,can_execute:role==='operator',task:{...appeal.task!,status:'ASSIGNED',due_date:'2030-12-15'}},role==='inspector');
  expect(element.textContent).toContain('15.12.2030');expect(element.querySelector('input[type=date]')).toBeNull();
});

it('submits the chosen subtask deadline with its operator and retains the parent version', async () => {
  vi.mocked(api).mockResolvedValue([{id:7, name:'Исполнитель'}]);
  await mount({...appeal, status:'NEW', task:null, submitted_by_inspector_name:'Проверяющий', inspector_due_date:'2026-11-10'});
  const panel = element.querySelector('details')!;
  const inputs = panel.querySelectorAll<HTMLInputElement>('input');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(inputs[0], 'Уборка участка');
    inputs[0].dispatchEvent(new Event('input', {bubbles:true}));
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(panel.querySelector('textarea'), 'Убрать мусор у входа');
    panel.querySelector('textarea')!.dispatchEvent(new Event('input', {bubbles:true}));
    panel.querySelector('select')!.value = '7'; panel.querySelector('select')!.dispatchEvent(new Event('change', {bubbles:true}));
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(inputs[1], '2026-11-06');
    inputs[1].dispatchEvent(new Event('input', {bubbles:true}));
  });
  await click(byText('Создать подзадачу и назначить'));
  expect(vi.mocked(api).mock.calls.find(([path]) => path.endsWith('/subtasks'))?.[2]).toMatchObject({subject:'Уборка участка', description:'Убрать мусор у входа', operator_id:7, due_date:'2026-11-06', expected_version:3});
});

it('preserves the closing draft when opening the gallery and adds the returned selection to the response', async () => {
  vi.mocked(api).mockImplementation(async path => {
    if (path.includes('/close-chat-photos?')) return {items: [{id: 'chat-file', url: '/chat-image'}], has_more: false};
    return [];
  });
  const chooseGeneral = vi.fn();
  await act(async () => {
    root.render(<AppealActions appeal={appeal} endpoint="/appeals" readOnly={false} chooseGeneral={chooseGeneral} changed={changed}/>);
    await tick();
  });
  await click(byText('Закрыть обращение'));
  const openPicker = () => click(element.querySelector<HTMLButtonElement>('dialog [aria-label="Прикрепить фото"]')!);
  await openPicker();
  await click(byText('Фото из переписки'));
  await act(async () => element.querySelector<HTMLInputElement>('input[aria-label*="из переписки"]')!.click());
  await act(async () => {
    const answer = element.querySelector<HTMLTextAreaElement>('dialog textarea')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(answer, 'Выполнено');
    answer.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await openPicker();
  await click(byText('Общие фотографии'));
  const draft = chooseGeneral.mock.calls[0][0];
  expect(draft).toMatchObject({appealId: 42, version: 3, answer: 'Выполнено', sourcePhotos: [{id: 'chat-file', source: 'chat'}]});
  const consumeDraft = vi.fn();
  await act(async () => {
    root.render(<AppealActions key="return" appeal={appeal} endpoint="/appeals" readOnly={false} changed={changed}
      resumedDraft={{...draft, sourcePhotos: [...draft.sourcePhotos, {id: 10, source: 'general', url: '/preview/10'}]}}
      consumeDraft={consumeDraft}/>);
    await tick();
  });
  expect(element.querySelector<HTMLTextAreaElement>('dialog textarea')?.value).toBe('Выполнено');
  expect(consumeDraft).toHaveBeenCalledOnce();
  await click(byText('Подтвердить закрытие'));
  const [, , body] = vi.mocked(api).mock.calls.find(([path, method]) => path === '/appeals/42/close' && method === 'POST')!;
  expect(JSON.parse((body as FormData).get('metadata') as string)).toMatchObject({chat_photo_ids: ['chat-file'], photo_ids: [10], comment: 'Выполнено'});
});
