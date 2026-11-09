// @vitest-environment jsdom
import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import InspectorApp from './InspectorApp';
import { api } from '../api';
import type { Inspector } from './types';
import { ThemeProvider } from '../theme';
import * as yandexMaps from '../yandexMaps';

vi.mock('../api',async importOriginal=>({...await importOriginal<typeof import('../api')>(),api:vi.fn(),dateLabel:(date:string|null)=>date||'—'}));
const account={id:1,name:'Проверяющий',role:'INSPECTOR',agency_name:'Администрация',can_create_accounts:true} as Inspector;
const photo={id:85,photo_date:'2026-10-18',photo_time:'12:30',received_at:'2026-10-18T13:00:00Z',latitude:null,longitude:null,
  district_name:'Центр',work_type_name:'Уборка',is_defect:false,preview_url:'/safe-photo'};
let element:HTMLDivElement,root:Root,navigate:ReturnType<typeof useNavigate>;
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
const button=(text:string)=>[...element.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')===text || b.textContent?.includes(text))!;
function TestApp(){navigate=useNavigate();return <InspectorApp/>;}
async function mount(url='/inspection?org=company&page=3') {await act(async()=>{root.render(<StrictMode><ThemeProvider><MemoryRouter initialEntries={[url]}><TestApp/></MemoryRouter></ThemeProvider></StrictMode>);await tick();await tick();});}
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
    if(path.includes('/photos?'))return {items:[photo],total:120,page:3,page_size:40,focus_id:path.includes('anchor_id=85')?85:null};
    if(path.endsWith('/photos/85'))return photo;
    if(path.includes('/navigation?'))return {previous:null,next:null};
    if(path.endsWith('/photos/arrivals'))return {photo_ids:[]};
    if(path==='/inspection/redeem')return {id:'company',name:'Организация'};
    if(path==='/inspection/contacts')return [];
    if(path==='/inspection/unread')return {unread:2};
    if(path==='/inspection/sessions')return {session_hours:12,items:[{id:'current',current:true,device:'Mac',device_type:'desktop',browser:'Safari',os:'macOS',ip_address:null,created_at:null,last_seen_at:null,expires_at:'2026-10-27T12:00:00Z'}]};
    if(path==='/inspection/sidebar-order')return {sidebar_order:['/photos','/districts']};
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
  expect(element.querySelector('.inspection-photo-detail h1')?.textContent).toBe('Фотография #85');
  expect(element.querySelector('[role=dialog]')).toBeNull();
  expect(document.body.style.position).toBe('');
  expect(element.querySelector('.inspection-photo-detail .review-layout')).not.toBeNull();
  expect(element.querySelector('.inspection-photo-detail input:not([readonly]):not([disabled])')).toBeNull();
  expect(element.querySelector('#inspection-photo-85')).toBe(row);
  await act(async()=>{button('К списку').click();await tick();});
  expect(element.querySelector('.inspection-photo-detail')).toBeNull();
  expect(element.textContent).toContain('Страница 3 из 3');
  expect(window.scrollTo).toHaveBeenLastCalledWith({top:1200,behavior:'instant'});
  expect(document.activeElement).toBe(element.querySelector('#inspection-photo-85'));
  expect(element.querySelector('#photo-row-85')?.classList.contains('photo-return-row')).toBe(true);
  expect(element.querySelector('table.inspection-photo-table')).not.toBeNull();
  expect(element.querySelector('nav.inspection-modules')).toBeNull();
  const navigation=element.querySelector('.sidebar nav')!;
  const content=element.querySelector('main.inspection-workspace')!;
  expect(navigation.compareDocumentPosition(content)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(vi.mocked(api).mock.calls.filter(([path])=>path.includes('/photos?'))).toHaveLength(calls+1);
  for(const hidden of ['Чаты MAX','Операторы','Отправитель','Нейросеть'])expect(element.textContent).not.toContain(hidden);
});

it.each(['list button','browser back'])('returns to the last viewed photo on a different page via %s',async(exit)=>{
  const original=vi.mocked(api).getMockImplementation()!;
  const nextPhoto={...photo,id:84};
  vi.mocked(api).mockImplementation(async(path,...args)=>{
    if(path.includes('anchor_id=84'))return {items:[nextPhoto],total:120,page:2,page_size:40,focus_id:84};
    if(path.includes('/85/navigation?'))return {previous:null,next:84};
    if(path.endsWith('/photos/84'))return nextPhoto;
    return original(path,...args);
  });
  await mount('/inspection?org=company&work_type=CLEAN&page=3');
  await act(async()=>{element.querySelector<HTMLButtonElement>('#inspection-photo-85')!.click();await tick();});
  await act(async()=>{button('Следующая').click();await tick();});
  expect(element.querySelector('.inspection-photo-detail h1')?.textContent).toBe('Фотография #84');
  await act(async()=>{if(exit==='browser back')navigate(-1);else button('К списку').click();await tick();await tick();});
  expect(element.textContent).toContain('Страница 2 из 3');
  expect(element.querySelector('#photo-row-84')?.classList.contains('photo-return-row')).toBe(true);
  expect(document.activeElement).toBe(element.querySelector('#inspection-photo-84'));
  expect(vi.mocked(api).mock.calls.some(([path])=>path.includes('/photos?work_type=CLEAN&page=3&anchor_id=84'))).toBe(true);
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

it('links visible cards and map points, and keeps the map when closing a photo',async()=>{
  const fallback=vi.mocked(api).getMockImplementation()!;
  const endpoint='/inspection/organizations/company/photos/map?district_id=2&';
  const sample={...photo,latitude:61.1,longitude:72.6,preview_url:'/api/inspection/organizations/company/photos/85/preview'};
  vi.mocked(api).mockImplementation(async(path,method,body,signal)=>{
    if(path.startsWith(endpoint))return {items:[sample,{...sample,id:86}],next_after_id:86};
    if(path==='/inspection/organizations/company/meta')return {...await fallback(path,method,body,signal) as object,yandex_maps_api_key:'map-test'};
    return fallback(path,method,body,signal);
  });
  const add=vi.fn<(collection: {features: yandexMaps.MapFeature[]})=>void>();
  const placemark = vi.fn();
  const addToMap = vi.fn(), removeFromMap = vi.fn();
  const setObjectOptions = vi.fn();
  const mapState = vi.fn();
  const fitToViewport=vi.fn();
  let pointClick: (event: yandexMaps.YMapEvent) => void;
  const getBounds=()=>[[72.5,61],[72.7,61.2]];
  vi.spyOn(yandexMaps,'loadYandexMaps').mockResolvedValue({
    Map: function(_container: HTMLElement, state: object){
      mapState(state);
      return {getBounds,geoObjects:{add:addToMap,remove:removeFromMap},container:{fitToViewport},destroy:vi.fn()};
    },
    ObjectManager: function(){
      return {add,removeAll:vi.fn(),getObjectState:(id:number)=>({isClustered:id===86}),
        objects:{setObjectOptions,events:{add:(_name:string,click:typeof pointClick)=>{pointClick=click;}}}};
    },
    Placemark: function(coordinates: number[], properties: object, options: object){
      return placemark(coordinates, properties, options) || {properties};
    },
  } as unknown as yandexMaps.YMaps);

  await mount('/inspection?org=company&tab=photo-map&district_id=2');
  expect(element.textContent).toContain('На карте: 2');
  expect(mapState).toHaveBeenCalledWith(expect.objectContaining({behaviors:['default','scrollZoom']}));
  const calls=vi.mocked(api).mock.calls.filter(([path])=>path.startsWith(endpoint));
  expect(calls).toHaveLength(1);
  expect(new URLSearchParams(calls[0][0].split('?')[1]).get('bounds')).toBe('72.50000,61.00000,72.70000,61.20000');
  const canvas=element.querySelector<HTMLDivElement>('.photo-map-canvas')!;
  const point=add.mock.lastCall![0].features[0];
  expect(point.geometry.coordinates).toEqual([72.6,61.1]);
  expect(canvas.querySelector('img')).toBeNull();
  expect(element.querySelector('[data-map-photo="85"] img')?.getAttribute('src')).toBe(sample.preview_url);
  await act(async()=>{pointClick({get:()=>86});await tick();});
  expect(element.querySelector('article.is-selected')?.getAttribute('data-map-photo')).toBe('86');
  expect(element.querySelector('article.is-selected .photo-map-selected-label')?.textContent).toContain('Выбрано');
  const oldMarker = addToMap.mock.lastCall![0];
  expect(placemark).toHaveBeenCalledWith([72.6,61.1],{},expect.objectContaining({preset:'islands#circleDotIcon',iconColor:'#000',zIndex:10000}));
  await act(async()=>{element.querySelector<HTMLButtonElement>('[data-map-photo="85"] button')!.click();await tick();});
  expect(removeFromMap).toHaveBeenCalledWith(oldMarker);
  expect(setObjectOptions).toHaveBeenLastCalledWith(85,{iconColor:'#000'});
  expect(element.querySelectorAll('article.is-selected')).toHaveLength(1);
  await act(async()=>{pointClick({get:()=>86});await tick();});
  expect(setObjectOptions).toHaveBeenLastCalledWith(85,{iconColor:'#1e98ff'});
  await act(async()=>{element.querySelector<HTMLButtonElement>('[data-map-photo="85"] button')!.click();await tick();});
  await act(async()=>{element.querySelector<HTMLAnchorElement>('article.is-selected a')!.click();await tick();});
  expect(element.querySelector('.inspection-photo-detail h1')?.textContent).toBe('Фотография #85');
  await act(async()=>{button('К карте').click();await tick();});
  expect(element.querySelector('.inspection-photo-detail')).toBeNull();
  expect(element.querySelector('.photo-map-canvas')).toBe(canvas);
  expect(fitToViewport).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api).mock.calls.filter(([path])=>path.startsWith(endpoint))).toHaveLength(calls.length);
  await act(async()=>{element.querySelector<HTMLAnchorElement>('.photo-map-actions a')!.click();await tick();});
  expect(vi.mocked(api).mock.calls.some(([path])=>path.includes('/photos?') && new URLSearchParams(path.split('?')[1]).get('district_id') === '2')).toBe(true);
});

it('does not show an all-organizations selector on the overview or with a single organization',async()=>{
  await mount('/inspection');
  expect(element.querySelector('.inspection-organization-select')).toBeNull();
  expect(element.textContent).not.toContain('Все организации');
  expect(element.querySelector('a[aria-label="Чаты"] [aria-label="Непрочитанных сообщений: 2"]')).not.toBeNull();
  await act(async()=>{button('Открыть').click();await tick();});
  expect(element.querySelector('.inspection-organization-select')).toBeNull();
});

it('keeps the conversation, draft and scroll when viewing a photo from another organization',async()=>{
  const fallback=vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async(path,method,body,signal)=>{
    if(path==='/inspection/organizations')return [{id:'first',name:'Первая'},{id:'company',name:'Вторая'}];
    if(path==='/inspection/contacts')return [{key:'i:2',name:'Коллега',kind:'Проверяющий',unread:0,avatar_url:null,last_message:null}];
    if(path.includes('/inspection/messages/read?'))return {ok:true};
    if(path.includes('/inspection/messages?'))return {items:[{id:1,body:'Посмотрите фото',outgoing:false,created_at:'2026-10-26T10:00:00Z',read_at:null,photo:{id:85,available:true,organization_id:'company',organization_name:'Вторая',preview_url:'/safe-photo',detail_url:'/inspection/photos/85?org=company&tab=messages&with=i%3A2&inspection_chat=i%3A2'}}],next_before_id:null,has_newer:false,peer_read_through_id:0};
    return fallback(path,method,body,signal);
  });
  await mount('/inspection?tab=messages&with=i%3A2');
  const log=element.querySelector<HTMLDivElement>('.operator-message-list')!,field=element.querySelector('textarea')!;
  log.scrollTop=160;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,'Мой черновик');field.dispatchEvent(new Event('input',{bubbles:true}));});
  await act(async()=>{element.querySelector<HTMLAnchorElement>('.operator-message-photo')!.click();await tick();});
  expect(element.querySelector('.inspection-photo-detail')).not.toBeNull();
  expect(element.querySelector('.operator-message-list')).toBe(log);
  await act(async()=>{button('К переписке').click();await tick();});
  expect(element.querySelector('.inspection-photo-detail')).toBeNull();
  expect(element.querySelector('.operator-message-list')).toBe(log);
  expect(log.scrollTop).toBe(160);
  expect(element.querySelector('textarea')?.value).toBe('Мой черновик');
});

it('opens photo forwarding from the read-only card',async()=>{
  const fallback=vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async(path,method,body,signal)=>path.startsWith('/inspection/contacts?')?[{key:'o:1',name:'Владелец',kind:'Владелец сервиса'}]:fallback(path,method,body,signal));
  await mount();
  await act(async()=>{element.querySelector<HTMLButtonElement>('#inspection-photo-85')!.click();await tick();});
  expect(button('Переслать фото').matches('.review-form .photo-forward-button')).toBe(true);
  await act(async()=>{button('Переслать фото').click();await tick();});
  expect(element.querySelector('[role=dialog] h2')?.textContent).toBe('Переслать фото');
  expect(element.querySelector('.forward-destinations button')?.textContent).toContain('Владелец сервиса');
  expect(vi.mocked(api).mock.calls.some(([path])=>path==='/inspection/contacts?photo_organization_id=company&photo_id=85')).toBe(true);
});

it('applies the work-type filter in the inspector archive',async()=>{
  await mount('/inspection?org=company&tab=photos&work_type=CLEAN');
  expect(element.querySelector('[aria-label="Вид работы"]')).not.toBeNull();
  expect(element.textContent).toContain('Все виды работ');
  const requests=vi.mocked(api).mock.calls.filter(([path])=>path.includes('/photos?'));
  expect(requests.length).toBeGreaterThan(0);
  expect(requests.every(([path])=>path.includes('work_type=CLEAN'))).toBe(true);
  expect(element.querySelector('.export')).toBeNull();
});

it('opens photos for a legacy reports URL and never exposes inspector reports or Excel',async()=>{
  await mount('/inspection?org=company&tab=reports&date_from=2026-10-18&date_to=2026-10-18');
  expect(element.querySelector('a[aria-label="Отчёты"]')).toBeNull();
  expect(element.querySelector('.export')).toBeNull();
  expect(element.querySelector('.inspection-photo-table')).not.toBeNull();
  expect(element.querySelector('input[type="date"]')?.getAttribute('value')).toBe('2026-10-18');
  expect(element.textContent).not.toContain('Скачать Excel');
  expect(vi.mocked(api).mock.calls.some(([path])=>path.includes('/reports')||path.includes('export.xlsx'))).toBe(false);
  expect(vi.mocked(api).mock.calls.some(([path])=>path.includes('/photos?date_from=2026-10-18&date_to=2026-10-18'))).toBe(true);
  await act(async()=>{element.querySelector<HTMLButtonElement>('button[aria-label="Изменить порядок меню"]')!.click();await tick();});
  expect(element.querySelector('button[aria-label*=«Отчёты»]')).toBeNull();
});
