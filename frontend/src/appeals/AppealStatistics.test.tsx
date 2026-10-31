// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AppealStatistics from './AppealStatistics';
import { api } from '../api';
vi.mock('../api', () => ({api: vi.fn()}));
const tick = () => new Promise(resolve => setTimeout(resolve,0));
let root: Root, element: HTMLDivElement;
const report = {start:'2026-10-01',end:'2026-10-31',timezone:'Asia/Yekaterinburg',total:3,completed:1,active:2,overdue:1,average_days:2.5,on_time_percent:50,timed_tasks:2,
  operators:[{key:'one:2',name:'Первый оператор',organization_name:'Организация',total:2,completed:1,active:0,overdue:1,other:0,average_days:1}],
  statuses:[{code:'RESOLVED',count:1},{code:'IN_PROGRESS',count:2}],work_types:[{code:'BIN_EMPTYING',name:'УРНЫ',count:3}],
  options:{organizations:[{id:'one',name:'Организация'}],operators:[{value:'one:2',name:'Первый оператор'}],work_types:[{code:'BIN_EMPTYING',name:'УРНЫ'}]}};
beforeEach(() => {
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  vi.clearAllMocks(); vi.mocked(api).mockResolvedValue(report);
  element=document.createElement('div');document.body.append(element);root=createRoot(element);
});
afterEach(async()=>{await act(async()=>root.unmount());element.remove();});
it('loads scoped reporting and filters by the chosen operator and work type',async()=>{
  await act(async()=>{root.render(<AppealStatistics endpoint="/inspection/organizations/one/appeals"/>);await tick();});
  expect(vi.mocked(api).mock.calls[0][0]).toContain('/inspection/organizations/one/appeals/statistics?');
  expect(element.textContent).toContain('Первый оператор');expect(element.textContent).toContain('2,5 дн.');
  expect(element.querySelectorAll('.appeal-report-metrics article')).toHaveLength(6);
  const select = [...element.querySelectorAll('label')].find(l=>l.textContent?.startsWith('Исполнитель'))!.querySelector('select')!;
  await act(async()=>{select.value='one:2';select.dispatchEvent(new Event('change',{bubbles:true}));await tick();});
  expect(new URLSearchParams(vi.mocked(api).mock.calls.at(-1)![0].split('?')[1]).get('operator')).toBe('one:2');
});
it('shows zero results and unknown timing instead of inventing performance data',async()=>{
  vi.mocked(api).mockResolvedValue({...report,total:0,completed:0,active:0,overdue:0,average_days:null,on_time_percent:null,timed_tasks:0,operators:[],statuses:[],work_types:[]});
  await act(async()=>{root.render(<AppealStatistics endpoint="/appeals"/>);await tick();});
  expect(element.textContent).toContain('За выбранный период обращений нет');
  expect(element.textContent).toContain('Назначений пока нет');
  expect([...element.querySelectorAll('.appeal-report-metrics strong')].map(e=>e.textContent)).toEqual(['0','0','0','0','Нет данных','Нет данных']);
});
