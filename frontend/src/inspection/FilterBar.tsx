import { ChevronLeft, ChevronRight, Download } from 'lucide-react';
import { dateLabel, shiftDate } from '../api';
import type { InspectionMeta } from './types';

export const inspectionFilterKeys=['date_from','date_to','district_id','is_defect','date_basis','sort_order','photo_id'];

export default function InspectionFilters({meta,filters,change,base}: {
  meta: InspectionMeta; filters: Record<string,string>; change: (values: Record<string,string>)=>void; base: string;
}) {
  const current=filters.date_to||meta.today, sort=(filters.date_basis||'photo')+'_'+(filters.sort_order||'desc');
  const key=new URLSearchParams(filters).toString();
  return <div className="filter-panel"><div className="period-row"><div className="date-switch">
    <button aria-label="Предыдущий день" onClick={()=>change({date_from:shiftDate(current,-1),date_to:shiftDate(current,-1)})}><ChevronLeft size={18}/></button>
    <strong>{filters.date_from&&filters.date_from===filters.date_to?dateLabel(filters.date_to):'Выбранный период'}</strong>
    <button aria-label="Следующий день" onClick={()=>change({date_from:shiftDate(current,1),date_to:shiftDate(current,1)})}><ChevronRight size={18}/></button></div>
    <div className="quick-period">{[['Сегодня',meta.today],['Вчера',shiftDate(meta.today,-1)],['7 дней',shiftDate(meta.today,-6)],['Этот месяц',meta.today.slice(0,8)+'01']].map(([title,from])=>
      <button key={title} onClick={()=>change({date_from:from,date_to:title==='Вчера'?from:meta.today})}>{title}</button>)}
      <button onClick={()=>change({date_from:'',date_to:''})}>За всё время</button></div>
    <a className="button export" href={'/api'+base+'/export.xlsx?'+key}><Download size={16}/>Скачать Excel</a></div>
    <div className="filters inspection-archive-filters"><label>Дата от<input type="date" value={filters.date_from||''} onChange={e=>change({date_from:e.target.value})}/></label>
      <label>Дата до<input type="date" value={filters.date_to||''} onChange={e=>change({date_to:e.target.value})}/></label>
      <label>Микрорайон<select aria-label="Микрорайон" value={filters.district_id||''} onChange={e=>change({district_id:e.target.value})}><option value="">Все микрорайоны</option><option value="0">Не определён</option>{meta.districts.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
      <label>Неисправность<select value={filters.is_defect||''} onChange={e=>change({is_defect:e.target.value})}><option value="">Все фотографии</option><option value="true">С неисправностями</option><option value="false">Без неисправностей</option></select></label>
      <label>Сортировка<select aria-label="Сортировка" value={sort} onChange={e=>{const [date_basis,sort_order]=e.target.value.split('_');change({date_basis,sort_order});}}>
        <option value="photo_desc">Сначала поздние фотографии</option><option value="photo_asc">Сначала ранние фотографии</option><option value="received_desc">Сначала поздние получения</option><option value="received_asc">Сначала ранние получения</option></select></label>
    </div><p className="hint filter-sort-hint">В выборке только фотографии, подтверждённые при закрытии дня. Часовой пояс: {meta.timezone}.</p>
  </div>;
}
