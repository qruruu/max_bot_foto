import type { Report, Line } from './types';

export type Kind = 'fact'|'plan';
export type Check = {id:string;kind?:Kind;index?:number;label:string;message:string;settings?:boolean};
export const rowId=(kind:Kind,index:number)=>`daily-${kind}-${index}`;
export function rowProblem(row:Line, unit:string) {
  if(row.decision==='skip'||row.decision==='info')return '';
  if(unit==='уточнить')return 'Уточните единицу измерения в настройке';
  if(row.quantity===null||!Number.isFinite(row.quantity)||row.quantity<=0)return 'Укажите объём или выберите «Без объёма»';
  if(row.quantity>1e12)return 'Объём не должен превышать 1 000 000 000 000';
  if(Math.abs(row.quantity*1000-Math.round(row.quantity*1000))>0.00001)return 'Укажите не более трёх знаков после запятой';
  if(row.decision==='pending')return 'Подтвердите работу';
  return '';
}
// One actionable entry per work row, both before and after saving.
export function reportChecks(report:Report):Check[] {
  const checks:Check[]=[];
  const {config,document}=report;
  if(!config.profile.company_name.trim()||!config.profile.recipient.some(s=>s.trim())||!config.contracts.length)
    checks.push({id:'daily-company',label:'Реквизиты письма',message:'Заполните организацию, адресата и контракт',settings:true});
  for(const kind of ['fact','plan'] as const) {
    const label=kind==='fact'?'Выполненные работы':'Запланированные работы';
    if(!document[`${kind}_season`]&&config.works.some(w=>w.season!=='all'))
      checks.push({id:`daily-${kind}-season`,kind,label,message:'Выберите летний или зимний сезон'});
    document[kind].forEach((row,index)=>{
      const work=config.works.find(w=>w.id===row.work_id), area=config.areas.find(a=>a.id===row.area_id);
      const message=rowProblem(row,work?.unit||'');
      if(message)checks.push({id:rowId(kind,index),kind,index,label:`${work?.name} · ${area?.name}`,message});
    });
  }
  return checks;
}
