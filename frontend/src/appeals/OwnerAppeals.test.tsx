// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import OwnerAppeals from './OwnerAppeals';
import { AppContextProvider, PhotoList } from '../App';
import { ResponsePhotoDraftProvider } from './ResponsePhotoDraft';
import type { Meta, User } from '../types';
import { api, ApiError } from '../api';

vi.mock('../api', async () => ({...await vi.importActual('../api'), api: vi.fn()}));
let root: Root, element: HTMLDivElement, messages: number;
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const row = {id: 42, number: 'ОБ-000042', status: 'NEW', version: 1, photo_count: 1, organization_name: 'Организация', organization_id: 'organization-one', work_type_name: '',
  city: 'Сургут', address: 'Сквер', place: 'У входа', description: 'Мусор', category: 'WASTE', created_at: '2026-10-28T10:00:00Z', owner_note: '',
  preview_url: '/preview', photos: [{id: 'one', url: '/photo', preview_url: '/preview', original_url: '/original'}], task: null, can_manage: true, can_execute: false};
let current: typeof row & {archived_at?: string};
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () {this.setAttribute('open', '');};
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
    if (path.includes('?page=')) return {items: [{...current, unanswered_comments: messages}], total: 1, page: 1, page_size: 20, can_manage: current.can_manage, can_execute: current.can_execute};
    return {...current, unanswered_comments: messages};
  });
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
});
afterEach(async () => {await act(async () => root.unmount()); element.remove();});

async function clickButton(text: string) {
  const button = [...element.querySelectorAll('button')].find(item => item.textContent === text)!;
  await act(async () => {button.click(); await tick();});
}

it('keeps message notifications after opening and clears them after a reply without losing the drafted administrator answer', async () => {
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint="/appeals"/></MemoryRouter>); await tick();});
  expect(element.textContent).toContain('Новые сообщения: 2'); expect(element.querySelector('img')?.getAttribute('src')).toBe('/preview');
  expect(element.textContent).not.toContain('Показать фото');
  expect(element.querySelector('button button')).toBeNull();
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  expect(element.textContent).toContain('Новые сообщения: 2');
  expect(element.querySelector('.owner-appeal-photos img')?.getAttribute('src')).toBe('/photo');
  expect(element.querySelector<HTMLAnchorElement>('.owner-appeal-photos .button')?.getAttribute('href')).toBe('/original');
  expect(element.textContent).not.toContain('Показать фото');
  await clickButton('Закрыть обращение');
  const answer = element.querySelector<HTMLTextAreaElement>('dialog textarea')!;
  const chat = element.querySelector<HTMLTextAreaElement>('[aria-label="Сообщение по обращению"]')!;
  await act(async () => {
    for (const [field, text] of [[answer, 'Черновик ответа'], [chat, 'Проверяем']] as const) {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, text); field.dispatchEvent(new Event('input', {bubbles: true}));
    }
  });
  await clickButton('Отмена');
  await act(async () => {element.querySelector<HTMLButtonElement>('.chat-composer button[type=submit]')!.click(); await tick();});
  expect(element.textContent).not.toContain('Новые сообщения'); expect(answer.value).toBe('Черновик ответа');
  expect(chat.value).toBe('');
  messages = 1;
  await act(async () => {window.dispatchEvent(new Event('focus')); await tick();});
  expect(element.textContent).toContain('Новые сообщения: 1');
  await clickButton('Закрыть обращение');
  expect(element.querySelector<HTMLTextAreaElement>('dialog textarea')?.value).toBe('Черновик ответа');
});

it.each(['/appeals', '/platform/appeals'])('assigns original organization work types and can clear them through %s', async endpoint => {
  current.category = '';
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint={endpoint}/></MemoryRouter>); await tick();});
  expect(element.querySelector('.appeal-list-title')!.textContent).toBe('Мусор');
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  expect(element.textContent).toContain('Обработка обращения');
  expect(element.querySelector('select[name=work_type]')).toBeNull();
  await clickButton('Редактировать');
  let select = element.querySelector<HTMLSelectElement>('select[name=work_type]')!;
  expect([...select.options].map(option => option.text)).toEqual(['Не назначен', 'УРНЫ', 'Особая работа организации']);
  expect(element.textContent).not.toContain('Переполненная урна');
  await act(async () => {select.value = 'BIN_EMPTYING'; select.dispatchEvent(new Event('change', {bubbles: true}));});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-edit button')!.click(); await tick();});
  expect(api).toHaveBeenCalledWith(endpoint + '/42', 'PATCH', {category: 'BIN_EMPTYING', status: 'NEW', owner_note: '', expected_version: 1});
  expect(element.querySelector('dialog')).toBeNull();
  expect(element.querySelector('.appeal-processing-summary')?.textContent).toContain('УРНЫ');
  await clickButton('Редактировать');
  expect(element.querySelector<HTMLSelectElement>('select[name=work_type]')!.value).toBe('BIN_EMPTYING');
  expect(element.querySelector('.appeal-detail-header h1')!.textContent).toContain('Мусор');
  select = element.querySelector<HTMLSelectElement>('select[name=work_type]')!;
  await act(async () => {select.value = ''; select.dispatchEvent(new Event('change', {bubbles: true}));});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-edit button')!.click(); await tick();});
  expect(api).toHaveBeenCalledWith(endpoint + '/42', 'PATCH', {category: '', status: 'NEW', owner_note: '', expected_version: 2});
  expect(element.querySelector('.appeal-processing-summary')?.textContent).toContain('Не назначен');
});

it('saves the executor deadline and task edits together from the settings dialog', async () => {
  Object.assign(current, {status: 'ASSIGNED', source: 'admin', subject: 'Уборка двора', inspector_due_date: '2030-12-31',
    task: {id: 1, operator_id: 7, operator_name: 'Исполнитель', status: 'ASSIGNED', photos: [], due_date: null}});
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint="/appeals"/></MemoryRouter>); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  await clickButton('Редактировать');
  const deadline = element.querySelector<HTMLInputElement>('dialog input[type=date]')!;
  expect(deadline.max).toBe('2030-12-31');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(deadline, '2030-12-15');
    deadline.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await clickButton('Сохранить');
  expect(api).toHaveBeenCalledWith('/appeals/42', 'PATCH', {due_date: '2030-12-15', status: 'ASSIGNED', owner_note: '', expected_version: 1});
});

it.each(['operator', 'inspector', 'archived'])('does not offer work type editing for %s', async role => {
  if (role === 'operator') current = {...current, can_manage: false, can_execute: true};
  if (role === 'archived') current = {...current, archived_at: '2026-10-29T12:00:00Z'};
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint="/appeals" readOnly={role === 'inspector'}/></MemoryRouter>); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  expect(element.querySelector('select[name=work_type]')).toBeNull();
  expect(vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/work-types'))).toBe(false);
});

it('shows operators only the execution deadline in their list and task', async () => {
  Object.assign(current, {can_execute: true, can_manage: false, operator_name: 'Иван Исполнитель', inspector_due_date: '2030-12-31',
    submitted_by_inspector_name: 'Проверяющий', status: 'ASSIGNED', due_date: '2030-12-15',
    task: {id: 1, status: 'ASSIGNED', operator_id: 7, operator_name: 'Иван Исполнитель', photos: [], due_date: '2030-12-15'}});
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint="/appeals"/></MemoryRouter>); await tick();});
  expect(element.textContent).toContain('15.12.2030');
  expect(element.textContent).not.toContain('Иван Исполнитель');
  expect(element.textContent).not.toContain('31.12.2030');
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('#appeal-tab-executor')!.click();});
  expect(element.textContent).toContain('15.12.2030');
  expect(element.textContent).not.toContain('Иван Исполнитель');
  expect(element.textContent).not.toContain('31.12.2030');
});

it('keeps the selected work type and note after a version conflict', async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, method, ...args) => {
    if (method === 'PATCH') throw new ApiError(409, 'Обращение изменилось. Обновите карточку.');
    return original(path, method, ...args);
  });
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint="/appeals"/></MemoryRouter>); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  await clickButton('Редактировать');
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
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint={endpoint} readOnly={readOnly}/></MemoryRouter>); await tick();});
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
    const status = element.querySelector<HTMLSelectElement>('.appeal-list-filters select[name=status]')!;
    status.value = 'SPAM'; status.dispatchEvent(new Event('change', {bubbles: true})); await tick();
  });
  expect(Object.fromEntries(new URLSearchParams(lastSearch().split('?')[1]))).toMatchObject({q: 'ОБ-000042', archived: 'true', status: 'SPAM', page: '1'});
  await act(async () => {element.querySelector<HTMLButtonElement>('[aria-label="Очистить поиск"]')!.click(); await tick();});
  const params = new URLSearchParams(lastSearch().split('?')[1]);
  expect(params.has('q')).toBe(false); expect(params.get('status')).toBe('SPAM'); expect(params.get('archived')).toBe('true');
});

it('keeps editing behind a dialog and retains the chat draft when switching tabs', async () => {
  Object.assign(current, {source: 'admin', subject: 'Проверить уборку'});
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint="/appeals"/></MemoryRouter>); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  const request = element.querySelector<HTMLElement>('#appeal-panel-request')!;
  const work = element.querySelector<HTMLElement>('#appeal-panel-work')!;
  expect(request.hidden).toBe(false); expect(work.hidden).toBe(true);
  expect(request.textContent).toContain('Проверить уборку');
  expect(request.querySelector('.appeal-processing-summary')).not.toBeNull();
  expect(element.querySelector('dialog')).toBeNull();
  await act(async () => {element.querySelector<HTMLButtonElement>('#appeal-tab-executor')!.click();});
  expect(request.hidden).toBe(true); expect(work.hidden).toBe(false);
  expect(work.textContent).toContain('Проверить уборку');
  expect(work.textContent).toContain('Сургут, Сквер');
  await clickButton('Редактировать');
  expect(element.querySelector('dialog[open] .owner-appeal-edit')).not.toBeNull();
  await act(async () => {element.querySelector<HTMLButtonElement>('dialog header button')!.click();});
  const field = element.querySelector<HTMLTextAreaElement>('[aria-label="Сообщение по обращению"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, 'Неотправленное сообщение');
    field.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => {element.querySelector<HTMLButtonElement>('#appeal-tab-request')!.click();});
  expect(request.hidden).toBe(false); expect(work.hidden).toBe(true);
  await act(async () => {element.querySelector<HTMLButtonElement>('#appeal-tab-executor')!.click();});
  expect(field.value).toBe('Неотправленное сообщение');
  expect(vi.mocked(api).mock.calls.filter(([, method]) => method === 'POST')).toHaveLength(0);
});

it('shows citizen requests and the final answer to inspectors without processing controls or chat', async () => {
  Object.assign(current, {status: 'RESOLVED', public_response: 'Площадку убрали, работу приняли.', is_final: true});
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint="/inspection/organizations/one/appeals" readOnly/></MemoryRouter>); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  expect(element.textContent).toContain('Итоговый ответ администратора');
  expect(element.textContent).toContain('Площадку убрали, работу приняли.');
  expect(element.querySelector('#appeal-tab-executor')).toBeNull();
  expect(element.querySelector('#appeal-tab-inspector')).toBeNull();
  expect(element.querySelector('.appeal-discussion')).toBeNull();
  expect(vi.mocked(api).mock.calls.some(([path]) => path.includes('/events'))).toBe(false);
});

it('keeps separate inspector and executor chats and preserves both drafts when switching workspaces', async () => {
  Object.assign(current, {submitted_by_inspector_name: 'Проверяющий', is_public: false, status: 'ASSIGNED', task: {id:1, operator_id:2, operator_name:'Оператор', status:'ASSIGNED', result_comment:'', photos:[], created_at:current.created_at}});
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint="/appeals"/></MemoryRouter>); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('#appeal-tab-executor')!.click();});
  const checking = element.querySelector<HTMLTextAreaElement>('[aria-label="Чат с проверяющим"] textarea')!;
  const executor = element.querySelector<HTMLTextAreaElement>('[aria-label="Чат с исполнителем"] textarea')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(checking, 'Уточнение проверяющему');
    checking.dispatchEvent(new Event('input', {bubbles:true}));
  });
  await act(async () => {[...element.querySelectorAll<HTMLButtonElement>('[role=tab]')].find(button => button.textContent === 'Работа с исполнителем')!.click();});
  expect(checking.isConnected).toBe(true);
  expect(checking.value).toBe('Уточнение проверяющему');
  expect(executor.disabled).toBe(false);
  expect(vi.mocked(api).mock.calls.some(([path]) => path === '/appeals/42/events?channel=inspector')).toBe(true);
  expect(vi.mocked(api).mock.calls.some(([path]) => path === '/appeals/42/events?channel=executor')).toBe(true);
});

it('puts separate chat badges on the top tabs and clears only the answered channel', async () => {
  Object.assign(current, {submitted_by_inspector_name:'Проверяющий', is_public:false, task:{id:1,operator_id:2,operator_name:'Оператор',status:'ASSIGNED',result_comment:'',photos:[]}});
  const original = vi.mocked(api).getMockImplementation()!;
  const counts = {inspector:2,executor:3};
  vi.mocked(api).mockImplementation(async (path, method, body, ...args) => {
    if (path.includes('/events?')) return {items:[], has_more:false, can_comment:true, unanswered_comments:counts[path.includes('channel=inspector') ? 'inspector' : 'executor']};
    if (path.endsWith('/comments') && method === 'POST') counts[(body as {channel:'inspector'|'executor'}).channel] = 0;
    return original(path,method,body,...args);
  });
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint="/appeals"/></MemoryRouter>); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('.owner-appeal-card-open')!.click(); await tick();});
  expect(element.querySelector('#appeal-tab-inspector .appeal-tab-count')?.textContent).toBe('2');
  expect(element.querySelector('#appeal-tab-executor .appeal-tab-count')?.textContent).toBe('3');
  expect(element.textContent).not.toContain('Работа с обращением');
  await act(async () => {element.querySelector<HTMLButtonElement>('#appeal-tab-inspector')!.click();});
  const text = element.querySelector<HTMLTextAreaElement>('[aria-label="Чат с проверяющим"] textarea')!;
  await act(async () => {Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(text,'Приняли'); text.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async () => {element.querySelector<HTMLButtonElement>('[aria-label="Чат с проверяющим"] form button[type=submit], [aria-label="Чат с проверяющим"] form button.primary')!.click(); await tick();});
  expect(element.querySelector('#appeal-tab-inspector .appeal-tab-count')).toBeNull();
  expect(element.querySelector('#appeal-tab-executor .appeal-tab-count')?.textContent).toBe('3');
});

it.each(['operator','inspector','administrator'])('shares the citizen page and preserves the source filter in the archive for %s', async role => {
  Object.assign(current, {can_manage:role === 'administrator',can_execute:role === 'operator'});
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (...args) => {const result = await original(...args); return args[0].includes('?page=') ? {...result as object,public_url:'https://signal.example/'} : result;});
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint="/appeals" readOnly={role === 'inspector'}/></MemoryRouter>); await tick();});
  expect(element.querySelector('a[href="https://signal.example/"]')).not.toBeNull();
  await act(async () => {const select = element.querySelector<HTMLSelectElement>('select[name=source]')!; select.value='inspector'; select.dispatchEvent(new Event('change',{bubbles:true})); await tick();});
  await act(async () => {[...element.querySelectorAll<HTMLButtonElement>('[role=tab]')].find(button => button.textContent === 'Архив')!.click(); await tick();});
  const query = vi.mocked(api).mock.calls.filter(([path]) => path.includes('?page=')).at(-1)![0];
  expect(Object.fromEntries(new URLSearchParams(query.split('?')[1]))).toMatchObject({source:'inspector',archived:'true'});
});

it('opens a shared task URL and returns to its list without retaining the task parameter', async () => {
  await act(async () => {
    root.render(<MemoryRouter initialEntries={['/appeals?appeal=42']}><OwnerAppeals organization endpoint="/appeals"/></MemoryRouter>);
    await tick();
  });
  expect(vi.mocked(api).mock.calls.some(([path]) => path === '/appeals/42')).toBe(true);
  expect(element.querySelector('h1')?.textContent).toContain('ОБ-000042');
  expect(document.activeElement).toBe(element.querySelector('h1'));
  await act(async () => element.querySelector<HTMLButtonElement>('.owner-appeal-back')!.click());
  expect(element.querySelector('#appeal-row-42')).not.toBeNull();
});

it('returns keyboard focus to the task that was opened from the list', async () => {
  await act(async () => {root.render(<MemoryRouter><OwnerAppeals organization endpoint="/appeals"/></MemoryRouter>); await tick();});
  await act(async () => {element.querySelector<HTMLButtonElement>('#appeal-row-42')!.click(); await tick();});
  await act(async () => element.querySelector<HTMLButtonElement>('.owner-appeal-back')!.click());
  expect(document.activeElement?.id).toBe('appeal-row-42');
});

it('keeps the chat draft when the open task is refreshed at a newer version', async () => {
  await act(async () => {root.render(<MemoryRouter initialEntries={['/appeals?appeal=42']}><OwnerAppeals organization endpoint="/appeals"/></MemoryRouter>); await tick();});
  await act(async () => element.querySelector<HTMLButtonElement>('#appeal-tab-executor')!.click());
  const draft = element.querySelector<HTMLTextAreaElement>('[aria-label="Сообщение по обращению"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(draft, 'Черновик');
    draft.dispatchEvent(new Event('input', {bubbles: true}));
  });
  current = {...current, version: current.version + 1};
  await act(async () => {window.dispatchEvent(new Event('refresh-appeals')); await tick();});
  expect(element.querySelector('[aria-label="Сообщение по обращению"]')).toBe(draft);
  expect(draft.value).toBe('Черновик');
});

it('returns from the shared photos page with the answer and checked photo still in the closing form', async () => {
  const fallback = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, ...args) => {
    if (path.startsWith('/photos/filter-counts')) return null;
    if (path.startsWith('/photos?')) return {items: [{id: 10, preview_url: '/preview/10',
      received_at: '2026-11-09T09:00:00Z', status: 'ACCEPTED'}], page: 1, page_size: 20, total: 1};
    return fallback(path, ...args);
  });
  const user = {id: 1, role: 'ADMIN_OPERATOR', permissions: ['photos_view']} as User;
  const meta = {organization: {id: 'one'}, today: '2026-11-09', work_types: [], districts: [],
    chats: [], statuses: [], operators: []} as unknown as Meta;
  await act(async () => {
    root.render(<MemoryRouter initialEntries={['/appeals?appeal=42&tab=executor']}>
      <AppContextProvider value={{user, meta, refresh: async () => {}, notify: () => {}, updateUser: () => {}}}>
        <ResponsePhotoDraftProvider><Routes>
          <Route path="/appeals" element={<OwnerAppeals organization canAttachPhotos/>}/>
          <Route path="/photos" element={<PhotoList/>}/>
        </Routes></ResponsePhotoDraftProvider>
      </AppContextProvider>
    </MemoryRouter>);
    await tick();
  });
  await clickButton('Закрыть обращение');
  await act(async () => {
    const answer = element.querySelector<HTMLTextAreaElement>('dialog textarea')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(answer, 'Проверено');
    answer.dispatchEvent(new Event('input', {bubbles: true}));
    element.querySelector<HTMLButtonElement>('dialog [aria-label="Прикрепить фото"]')!.click();
  });
  await clickButton('Общие фотографии');
  expect(element.querySelector('dialog')).toBeNull();
  await act(async () => element.querySelector<HTMLInputElement>('[aria-label="Выбрать фото №10"]')!.click());
  await clickButton('Добавить в ответ');
  expect(element.querySelector<HTMLTextAreaElement>('dialog textarea')?.value).toBe('Проверено');
  expect(element.querySelector('dialog img[src="/preview/10"]')).not.toBeNull();
  expect(vi.mocked(api).mock.calls.some(([path, method]) => method === 'POST' && /close$|photo-comments$/.test(path))).toBe(false);
});
