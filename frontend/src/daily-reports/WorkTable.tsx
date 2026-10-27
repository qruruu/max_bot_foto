import { useState } from 'react';
import { Camera, Check } from 'lucide-react';
import type { Line, Report } from './types';
import { rowId, rowProblem } from './review';
import type { Kind } from './review';

type Props={report:Report;kind:Kind;disabled:boolean;photosAllowed:boolean;onlyProblems:boolean;
  update:(index:number,update:Partial<Line>)=>void;showPhotos:(work_id:string,area_id:string,title:string)=>void;
  crew:(contract_id:string,value:string)=>void};
export default function WorkTable({report,kind,disabled,photosAllowed,onlyProblems,update,showPhotos,crew}:Props) {
  const [crewValues,setCrewValues]=useState<Record<string,string>>({});
  const {config,document}=report;
  return <>{config.contracts.map(contract=>{
    const all=document[kind].map((row,index)=>({row,index})).filter(({row})=>config.areas.find(a=>a.id===row.area_id)?.contract_id===contract.id);
    const rows=all.filter(({row})=>!onlyProblems||rowProblem(row,config.works.find(w=>w.id===row.work_id)!.unit));
    if(onlyProblems&&!rows.length)return null;
    return <section className="daily-work-contract" key={contract.id}><div className="section-title"><h3>Контракт {contract.number}</h3><span>{all.length} работ</span></div>
      {!disabled&&all.length>1&&<details className="daily-crew"><summary>Указать людей и технику сразу для нескольких работ</summary><div className="daily-inline"><label>Персонал / техника<input aria-label={'Общий персонал: '+contract.number} placeholder="Например, 3 человека" value={crewValues[contract.id]||''} onChange={e=>setCrewValues({...crewValues,[contract.id]:e.target.value})}/></label><button disabled={!crewValues[contract.id]?.trim()} onClick={()=>crew(contract.id,crewValues[contract.id].trim())}>Заполнить пустые поля</button></div><p className="hint">Только для {kind==='fact'?'выполненных':'запланированных'} работ этого контракта. Уже указанные сведения сохранятся.</p></details>}
      {!rows.length?<p className="muted">Работ пока нет. Дополнительную работу можно добавить ниже.</p>:<div className="table-scroll"><table className="daily-simple-table"><thead><tr><th>Работа</th><th>Объём</th><th>{kind==='fact'?'Проверенные фото':'Сведения'}</th><th>{kind==='fact'?'Выполнено?':'Планируем?'}</th></tr></thead><tbody>{rows.map(({row,index})=>{
        const work=config.works.find(w=>w.id===row.work_id)!,area=config.areas.find(a=>a.id===row.area_id)!;
        const evidence=report.evidence.rows[row.work_id+':'+row.area_id];
        const problem=rowProblem(row,work.unit);
        return <tr id={rowId(kind,index)} tabIndex={-1} key={row.work_id+':'+row.area_id} className={problem?'daily-row-pending':row.decision==='skip'?'daily-row-skip':'daily-row-done'}>
          <td><strong>{work.name}</strong><small>{area.name}</small><details><summary>{row.resources||'Люди, техника и примечание'}</summary><label>Персонал / техника<input aria-label={`${kind==='fact'?'Люди: ':'Люди в плане: '}${work.name} — ${contract.number}`} disabled={disabled} placeholder="Если нужно указать в письме" value={row.resources} onChange={e=>update(index,{resources:e.target.value})}/></label><label>Примечание<textarea disabled={disabled} value={row.note} onChange={e=>update(index,{note:e.target.value})}/></label><p>{work.schedule_note}</p>
            {!['daily','event','dates'].includes(work.recurrence)&&kind==='fact'&&<label className="checkbox"><input type="checkbox" disabled={disabled||row.decision!=='include'} checked={row.cycle_complete} onChange={e=>update(index,{cycle_complete:e.target.checked})}/>Вся работа за этот период выполнена</label>}
          </details></td>
          <td data-label="Объём">{row.decision==='skip'?<span className="muted">—</span>:row.decision==='info'?<><span>Без объёма</span><button className="text-button" disabled={disabled} onClick={()=>update(index,{decision:'pending'})}>Указать объём</button></>:<><div className="daily-quantity"><input aria-label={`${kind==='fact'?'Выполнено: ':'Запланировано: '}${work.name} — ${contract.number}`} aria-invalid={!!problem&&(row.quantity===null||row.quantity<=0)} disabled={disabled} type="number" min="0" step="0.001" value={row.quantity??''} placeholder="Указать" onChange={e=>{const quantity=e.target.value===''?null:Number(e.target.value);update(index,{quantity,decision:quantity!==null&&quantity>0?'include':'pending',cycle_complete:false});}}/><span>{work.unit}</span></div><button disabled={disabled} className="text-button" onClick={()=>update(index,{decision:'info',cycle_complete:false})}>Без объёма</button></>}
            {problem&&<small className="daily-warning">{problem}</small>}</td>
          <td data-label={kind==='fact'?'Проверенные фото':'Сведения'}>{kind==='fact'?<><button className="text-button" disabled={!photosAllowed||!evidence?.confirmed} onClick={()=>showPhotos(row.work_id,row.area_id,work.name+' · '+area.name)}><Camera size={15}/>{evidence?.confirmed||0} фото</button>{!!evidence&&evidence.confirmed<evidence.total&&<small>{evidence.total-evidence.confirmed} ещё не включено в проверенный день</small>}</>:<small>{row.resources||'При необходимости укажите людей и технику в сведениях о работе'}</small>}</td>
          <td data-label={kind==='fact'?'Выполнено?':'Планируем?'}><div className="daily-decisions"><button aria-pressed={row.decision==='include'||row.decision==='info'} disabled={disabled} onClick={()=>update(index,{decision:row.decision==='info'?'info':'include'})}><Check size={14}/>{kind==='fact'?'Выполнено':'Запланировано'}</button><button aria-pressed={row.decision==='skip'} disabled={disabled} onClick={()=>update(index,{decision:'skip',cycle_complete:false})}>{kind==='fact'?'Не выполнялось':'Не планировать'}</button></div></td>
        </tr>;
      })}</tbody></table></div>}
    </section>;
  })}</>;
}
