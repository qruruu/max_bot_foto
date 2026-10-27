import { Camera, CheckCheck, ChevronRight, Layers, Wrench } from 'lucide-react';
import WorkDistrictMatrix from '../WorkDistrictMatrix';
import type { InspectionMeta, InspectionReport } from './types';

export default function InspectionOverview({report,meta,filters,open}: {report:InspectionReport;meta:InspectionMeta;filters:Record<string,string>;open:(filters:Record<string,string>)=>void}) {
  const view={...report,accepted:report.total,counts:{ACCEPTED:report.total},chats:[],matrix:[]};
  return <><div className="stat-grid">{[
    {label:'Всего в отчёте',value:report.total,Icon:Camera,filter:{}},
    {label:'Подтверждены при закрытии',value:report.total,Icon:CheckCheck,filter:{}},
    {label:'С неисправностями',value:report.defects,Icon:Wrench,filter:{is_defect:'true'}},
    {label:'Видов работ',value:report.work_types.length,Icon:Layers,filter:{}},
  ].map(({label,value,Icon,filter},i)=><button key={label} className={'stat-card stat-'+i} onClick={()=>open(filter as Record<string,string>)}><div><span>{label}</span><Icon size={19}/></div><strong>{value.toLocaleString('ru-RU')}</strong><small>За выбранный период</small></button>)}</div>
    <WorkDistrictMatrix report={view} meta={meta} filters={filters} canBrowse={false} open={open}/>
    <div className="two-columns">{([['districts','По микрорайонам'],['work_types','Виды выполненных работ']] as const).map(([key,label])=><section key={key} className="panel"><div className="section-title"><h2>{label}</h2><span>Фотографий</span></div>
      <div className="bar-list">{report[key].map(row=>{
        const content=<><div><span>{row.name}</span><strong>{row.count}</strong></div><div className="bar"><i style={{width:row.count/Math.max(...report[key].map(r=>r.count))*100+'%'}}/></div></>;
        return key==='districts'?<button key={row.id} onClick={()=>open({district_id:String(row.id)})}>{content}</button>:<div className="inspection-work-summary" key={row.id}>{content}</div>;
      })}</div>
      {!report[key].length&&<p className="muted">За выбранный период фотографий нет.</p>}</section>)}</div>
    <button className="text-button" onClick={()=>open({})}>Открыть все фотографии отчёта<ChevronRight size={16}/></button>
  </>;
}
