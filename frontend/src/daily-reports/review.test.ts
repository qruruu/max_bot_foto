import { expect,it } from 'vitest';
import { reportChecks,rowProblem } from './review';
import type { Line,Report } from './types';
const line=(values:Partial<Line>={}):Line=>({work_id:'w',area_id:'a',quantity:null,decision:'pending',resources:'',note:'',cycle_complete:false,...values});
it('gives one actionable item per row even when both confirmation and volume are missing',()=>{
  const report={config:{profile:{company_name:'Компания',recipient:['Адресат']},contracts:[{id:'c'}],works:[{id:'w',name:'Урны',unit:'шт.',season:'summer'}],areas:[{id:'a',name:'1 мкр'}]},document:{fact:[line()],plan:[line()],fact_season:'',plan_season:''}} as Report;
  const checks=reportChecks(report);
  expect(checks).toHaveLength(4);
  expect(checks.map(c=>c.id)).toEqual(['daily-fact-season','daily-fact-0','daily-plan-season','daily-plan-0']);
  report.document.fact[0]=line({decision:'info'});
  expect(reportChecks(report)).toHaveLength(3);
});
it('does not require a quantity for explicitly skipped or informational rows',()=>{
  expect(rowProblem(line({decision:'skip'}),'уточнить')).toBe('');
  expect(rowProblem(line({decision:'info'}),'уточнить')).toBe('');
  expect(rowProblem(line({decision:'include',quantity:null}),'шт.')).toContain('Укажите объём');
});
it('checks precision, bounds, and confirmation before preparing letters',()=>{
  expect(rowProblem(line({quantity:10}),'шт.')).toBe('Подтвердите работу');
  expect(rowProblem(line({quantity:1.1234,decision:'include'}),'м²')).toContain('трёх знаков');
  expect(rowProblem(line({quantity:1e13,decision:'include'}),'м²')).toContain('не должен превышать');
  expect(rowProblem(line({quantity:1.123,decision:'include'}),'м²')).toBe('');
});
