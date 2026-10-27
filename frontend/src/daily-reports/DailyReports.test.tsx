// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import { useApp } from '../App';
import DailyReports from './DailyReports';
import type { Config, Report, Setup } from './types';

vi.mock('../api',async()=>({...await vi.importActual('../api'),api:vi.fn()}));
vi.mock('../App',()=>({useApp:vi.fn(),ErrorBox:({error}:{error:string})=>error?<div role="alert">{error}</div>:null}));
let root:Root,element:HTMLDivElement,setup:Setup,stored:Report|null;
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
const click=async(text:string)=>{const node=Array.from(element.querySelectorAll('button')).find(b=>b.textContent===text);expect(node,'button '+text).toBeTruthy();await act(async()=>{node!.click();await tick();});};
function config():Config {
  return {profile:{company_name:'Индивидуальный предприниматель Шашко Андрей Дмитриевич',short_name:'ИП Шашко А. Д.',city:'Нефтеюганск',address:'Адрес из образца',inn:'860400307580',ogrn:'304860413400240',phone:'',email:'',recipient:['Адресат'],photo_url:'https://disk.yandex.ru/d/example',subject:'По содержанию земель общего пользования'},contracts:[{id:'58',number:'ЭА.2026.00058',prefix:'МК-58-',next_number:1}],areas:[{id:'a',contract_id:'58',name:'1, 2 микрорайоны',district_ids:[]}],works:[{id:'bins',name:'Очистка урн',unit:'шт.',season:'all',recurrence:'daily',schedule_note:'Ежедневно',windows:[],dates:[],interval_days:5,requires_event:false,photo_codes:[],assignments:[{area_id:'a',quantity:null,resources:'',annual_limit:null}]}],summer_start:'',summer_end:'',source_notes:'558 урн и 3 человека — факт только за 17 октября, не постоянная норма.'};
}
function report():Report {
  const line={work_id:'bins',area_id:'a',decision:'pending' as const,quantity:null,resources:'',note:'',cycle_complete:false};
  return {id:1,day:'2026-10-27',fact_day:'2026-10-26',cohort:'test',version:1,approved:false,changed:false,approved_at:null,letter_numbers:{},config:config(),document:{fact:[{...line}],plan:[{...line}],fact_season:'',plan_season:'',fact_events:[],plan_events:[],note:''},issues:['Укажите объём'],evidence:{total:12,unmatched:0,rows:{'bins:a':{total:12,needs_review:1}}},new_photos:0,changed_photos:0};
}
async function mount(entry='/daily-reports') {
  await act(async()=>{root.render(<MemoryRouter initialEntries={[entry]}><DailyReports/></MemoryRouter>);await tick();});
}
async function select(label:string,value:string) {
  const node=element.querySelector<HTMLSelectElement>('select[aria-label="'+label+'"]')!;
  await act(async()=>{node.value=value;node.dispatchEvent(new Event('change',{bubbles:true}));await tick();});
}
beforeEach(()=>{
  vi.clearAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  element=document.createElement('div');document.body.append(element);root=createRoot(element);
  setup={version:1,config:config()};stored=null;
  vi.mocked(useApp).mockReturnValue({user:{id:1,role:'ADMIN_OPERATOR',allowed_chat_ids:null,permissions:[]} as never,meta:{today:'2026-10-27',intake_cohort:'test',districts:[],work_types:[]} as never,notify:vi.fn(),refresh:vi.fn(),updateUser:vi.fn()});
  vi.mocked(api).mockImplementation(async(path,method='GET',body)=>{
    const payload=body as Record<string,any>;
    if(path.endsWith('/settings')){if(method==='PUT')setup={version:setup.version+1,config:payload.config};return structuredClone(setup);}
    if(path==='/daily-reports'){if(method==='POST'){stored=report();return structuredClone(stored);}return stored?[stored]:[];}
    if(path.endsWith('/approve')){stored={...stored!,approved:true,approved_at:'2026-10-27T08:00:00Z',letter_numbers:{'58':'ТЕСТ-МК-58-20261027'},issues:[]};return structuredClone(stored);}
    if(path==='/daily-reports/1'){if(method==='PUT')stored={...stored!,document:payload.document,version:stored!.version+1};return structuredClone(stored);}
    throw new Error('Unexpected path '+path);
  });
});
afterEach(async()=>{await act(async()=>root.unmount());element.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('shows saved company settings without a demo or historical norms',async()=>{
  await mount('/daily-reports?tab=settings');
  expect(element.textContent).toContain('558 урн и 3 человека — факт только за 17 октября');
  expect(element.textContent).not.toContain('Территория в письме');
  expect(element.textContent).not.toContain('Заполнить для ИП Шашко');
  expect(element.querySelector<HTMLInputElement>('input[aria-label="Норма: 1, 2 микрорайоны"]')!.value).toBe('');
  await click('Рабочий день');
  expect(element.textContent).not.toContain('Открыть пример из Excel');
  expect(vi.mocked(api).mock.calls.every(c=>!['POST','PUT'].includes(c[1]||''))).toBe(true);
});

it('selects districts and adds work from the existing company catalog',async()=>{
  const context=vi.mocked(useApp).getMockImplementation()!();
  vi.mocked(useApp).mockReturnValue({...context,meta:{...context.meta,districts:[{id:12,name:'12 мкр',active:true}],work_types:[{code:'SNOW_MANUAL',name:'ПОДХОДЫ'}]} as never});
  await mount('/daily-reports?tab=settings');
  const box=element.querySelector<HTMLInputElement>('input[aria-label="ЭА.2026.00058: 12 мкр"]')!;
  await act(async()=>{box.click();await tick();});
  await select('Вид работы из справочника','SNOW_MANUAL');
  await click('Добавить работу');
  await click('Сохранить настройку');
  expect(setup.config.areas[0]).toMatchObject({name:'12 мкр',district_ids:[12]});
  expect(setup.config.works.at(-1)).toMatchObject({name:'ПОДХОДЫ',photo_codes:['SNOW_MANUAL']});
  expect(setup.config.works.at(-1)!.assignments[0].quantity).toBeNull();
});

it('shows photo evidence without filling work quantities or approving the day',async()=>{
  await mount();await click('Собрать черновик');
  expect(element.textContent).toContain('12 фото');
  expect(element.querySelector<HTMLInputElement>('input[aria-label="Факт: Очистка урн — ЭА.2026.00058"]')!.value).toBe('');
  expect(vi.mocked(api).mock.calls.some(c=>c[0].endsWith('/approve'))).toBe(false);
  await click('Подтвердить строки с объёмом');
  expect(element.querySelector<HTMLSelectElement>('select[aria-label="Решение: факт Очистка урн — ЭА.2026.00058"]')!.value).toBe('pending');
});

it('saves explicit decisions before approval and switches downloads to the approved version',async()=>{
  await mount();await click('Собрать черновик');
  await select('Решение: факт Очистка урн — ЭА.2026.00058','skip');
  await select('Решение: план Очистка урн — ЭА.2026.00058','info');
  await click('Утвердить отчёт');
  const writes=vi.mocked(api).mock.calls.filter(c=>['PUT','POST'].includes(c[1]||''));
  expect(writes.at(-2)?.[0]).toBe('/daily-reports/1');expect(writes.at(-2)?.[1]).toBe('PUT');
  expect(writes.at(-1)?.[0]).toBe('/daily-reports/1/approve');
  expect(element.querySelector<HTMLAnchorElement>('a[href*="/xlsx"]')!.getAttribute('href')).toBe('/api/daily-reports/1/xlsx');
});

it('keeps report settings read-only for an account without configuration permission',async()=>{
  const context=vi.mocked(useApp).getMockImplementation()!();
  vi.mocked(useApp).mockReturnValue({...context,user:{...context.user,role:'OPERATOR',permissions:['daily_reports_view'],allowed_chat_ids:null}});
  await mount();await click('Настройка организации');
  expect(element.querySelector('fieldset')!.disabled).toBe(true);
  expect(Array.from(element.querySelectorAll('button')).some(b=>b.textContent==='Заполнить для ИП Шашко')).toBe(false);
  expect(vi.mocked(api).mock.calls.some(c=>c[1]==='PUT')).toBe(false);
});

it('does not crash when the report date input is cleared',async()=>{
  await mount();
  const input=element.querySelector<HTMLInputElement>('.daily-day-picker input')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'');input.dispatchEvent(new Event('input',{bubbles:true}));await tick();});
  expect(element.textContent).toContain('Выберите дату');
});
