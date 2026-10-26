// @vitest-environment jsdom
import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import InspectorApp from './InspectorApp';
import { api } from '../api';
import type { Inspector } from './types';
import { ThemeProvider } from '../theme';

vi.mock('../api',async importOriginal=>({...await importOriginal<typeof import('../api')>(),api:vi.fn(),dateLabel:(date:string|null)=>date||'—'}));
const account={id:1,name:'Проверяющий',role:'INSPECTOR',agency_name:'Администрация',can_create_accounts:true} as Inspector;
const photo={id:85,photo_date:'2026-10-18',photo_time:'12:30',received_at:'2026-10-18T13:00:00Z',latitude:null,longitude:null,
  district_name:'Центр',work_type_name:'Уборка',is_defect:false,preview_url:'/safe-photo'};
let element:HTMLDivElement,root:Root;
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
const button=(text:string)=>[...element.querySelectorAll('button')].find(b=>b.textContent?.includes(text))!;
async function mount(url='/inspection?org=company&page=3') {await act(async()=>{root.render(<StrictMode><ThemeProvider><MemoryRouter initialEntries={[url]}><InspectorApp/></MemoryRouter></ThemeProvider></StrictMode>);await tick();await tick();});}
beforeEach(()=>{
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  element=document.createElement('div');document.body.append(element);root=createRoot(element);
  vi.spyOn(window,'scrollTo').mockImplementation(()=>{});vi.spyOn(window,'scrollY','get').mockReturnValue(1200);
  vi.stubGlobal('matchMedia',vi.fn(()=>({matches:false,addEventListener:vi.fn(),removeEventListener:vi.fn()})));
  sessionStorage.clear();window.history.replaceState({},'', '/inspection');
  vi.mocked(api).mockReset().mockImplementation(async(path:string)=>{
    if(path==='/inspection/me')return account;
    if(path==='/inspection/organizations')return [{id:'company',name:'Организация'}];
    if(path.endsWith('/meta'))return {districts:[],work_types:[]};
    if(path.includes('/photos?'))return {items:[photo],total:120,page:3,page_size:40};
    if(path.endsWith('/photos/85'))return photo;
    if(path.includes('/navigation?'))return {previous:null,next:null};
    if(path.endsWith('/photos/arrivals'))return {photo_ids:[]};
    if(path==='/inspection/redeem')return {id:'company',name:'Организация'};
    if(path==='/inspection/contacts')return [];
    if(path==='/inspection/unread')return {unread:2};
    if(path==='/inspection/sessions')return {session_hours:12,items:[{id:'current',current:true,device:'Mac',device_type:'desktop',browser:'Safari',os:'macOS',ip_address:null,created_at:null,last_seen_at:null,expires_at:'2026-10-27T12:00:00Z'}]};
    if(path==='/inspection/sidebar-order')return {sidebar_order:['/photos','/districts','/']};
    throw new Error('Unexpected '+path);
  });
});
afterEach(async()=>{await act(async()=>root.unmount());element.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('keeps the same page, photo list, scroll and focus after closing a photo',async()=>{
  await mount();
  const row=element.querySelector<HTMLButtonElement>('#inspection-photo-85')!;
  const calls=vi.mocked(api).mock.calls.filter(([path])=>path.includes('/photos?')).length;
  row.focus();
  await act(async()=>{row.click();await tick();});
  expect(element.querySelector('[role=dialog]')).not.toBeNull();
  expect(document.body.style.position).toBe('fixed');
  expect(element.querySelector('#inspection-photo-85')).toBe(row);
  await act(async()=>{button('К списку').click();await tick();});
  expect(element.querySelector('[role=dialog]')).toBeNull();
  expect(element.textContent).toContain('Страница 3 из 3');
  expect(window.scrollTo).toHaveBeenLastCalledWith(0,1200);
  expect(document.activeElement).toBe(row);
  expect(row.closest('tr')?.id).toBe('inspection-photo-row-85');
  expect(element.querySelector('table.inspection-photo-table')).not.toBeNull();
  expect(element.querySelector('nav.inspection-modules')).toBeNull();
  const navigation=element.querySelector('.sidebar nav')!;
  const content=element.querySelector('main.inspection-workspace')!;
  expect(navigation.compareDocumentPosition(content)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(vi.mocked(api).mock.calls.filter(([path])=>path.includes('/photos?'))).toHaveLength(calls);
  for(const hidden of ['Чаты MAX','Операторы','Отправитель','Нейросеть'])expect(element.textContent).not.toContain(hidden);
});

it('redeems a QR link only once under StrictMode and removes its secret from the URL',async()=>{
  const token='a'.repeat(43);window.history.replaceState({},'', '/inspection#invite='+token);
  await mount();
  expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/inspection/redeem')).toHaveLength(1);
  expect(vi.mocked(api)).toHaveBeenCalledWith('/inspection/redeem','POST',{token});
  expect(window.location.hash).toBe('');
  expect(sessionStorage.getItem('inspection-pending-invite')).toBeNull();
});

it('refreshes photos explicitly and hides account creation for subordinate accounts',async()=>{
  vi.mocked(api).mockResolvedValueOnce({...account,can_create_accounts:false}).mockResolvedValueOnce({...account,can_create_accounts:false});
  await mount();
  expect(element.textContent).not.toContain('Аккаунты');
  const calls=vi.mocked(api).mock.calls.filter(([path])=>path.includes('/photos?')).length;
  await act(async()=>{button('Обновить').click();await tick();});
  expect(vi.mocked(api).mock.calls.filter(([path])=>path.includes('/photos?')).length).toBeGreaterThan(calls);
});

it('keeps refresh available when leaving a photo request that is still loading',async()=>{
  const original=vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async(path:string)=>{if(path.includes('/photos?'))await new Promise(()=>{});return original(path);});
  await mount();
  expect(button('Обновить').disabled).toBe(true);
  await act(async()=>{element.querySelector<HTMLAnchorElement>('a[aria-label="Чаты"]')!.click();await tick();});
  expect(button('Обновить').disabled).toBe(false);
});

it('opens the same personal settings sections as the operator and uses independent inspector session endpoints',async()=>{
  await mount();
  await act(async()=>{element.querySelector<HTMLAnchorElement>('a[aria-label="Настройки"]')!.click();await tick();});
  expect(element.querySelector('input[aria-label="Выберите аватарку"]')).not.toBeNull();
  for(const section of ['Профиль','Оформление','Уведомления','Безопасность','Активные сеансы'])expect(element.querySelector(`a[aria-label="${section}"]`)).not.toBeNull();
  await act(async()=>{element.querySelector<HTMLAnchorElement>('a[aria-label="Активные сеансы"]')!.click();await tick();});
  expect(api).toHaveBeenCalledWith('/inspection/sessions','GET',undefined,expect.any(AbortSignal));
  expect(element.textContent).toContain('Текущий сеанс');
  expect(vi.mocked(api).mock.calls.some(([path])=>path.startsWith('/auth/sessions'))).toBe(false);
});

it('offers both maps and saves the personal sidebar order through the inspector endpoint',async()=>{
  await mount();
  expect(element.querySelector('a[aria-label="Карта фотографий"]')).not.toBeNull();
  expect(element.querySelector('a[aria-label="Микрорайоны"]')).not.toBeNull();
  await act(async()=>{element.querySelector<HTMLButtonElement>('button[aria-label="Изменить порядок меню"]')!.click();await tick();});
  await act(async()=>{element.querySelector<HTMLButtonElement>('button[aria-label="Поднять «Фотографии»"]')!.click();await tick();});
  await act(async()=>{button('Сохранить').click();await tick();});
  expect(vi.mocked(api).mock.calls.some(([path,method])=>path==='/inspection/sidebar-order'&&method==='PUT')).toBe(true);
});

it('does not show an all-organizations selector on the overview or with a single organization',async()=>{
  await mount('/inspection');
  expect(element.querySelector('.inspection-organization-select')).toBeNull();
  expect(element.textContent).not.toContain('Все организации');
  expect(element.querySelector('a[aria-label="Чаты"] [aria-label="Непрочитанных сообщений: 2"]')).not.toBeNull();
  await act(async()=>{button('Открыть').click();await tick();});
  expect(element.querySelector('.inspection-organization-select')).toBeNull();
});
