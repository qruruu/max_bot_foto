import { PhotoFilterOptions, PhotoPeriod } from '../PhotoFiltersLayout';
import type { InspectionMeta } from './types';

export const inspectionFilterKeys=['date_from','date_to','district_id','is_defect','photo_id'];

export default function InspectionFilters({meta,filters,change}: {
  meta: InspectionMeta; filters: Record<string,string>; change: (values: Record<string,string>)=>void;
}) {
  return <div className="filter-panel photo-filters">
    <PhotoPeriod today={meta.today} from={filters.date_from} to={filters.date_to} change={change}/>
    <PhotoFilterOptions count={[filters.district_id, filters.is_defect, filters.photo_id].filter(Boolean).length}>
    <div className="filters inspection-archive-filters"><label>Дата съёмки с<input type="date" value={filters.date_from||''} onChange={e=>change({date_from:e.target.value})}/></label>
      <label>Дата съёмки по<input type="date" value={filters.date_to||''} onChange={e=>change({date_to:e.target.value})}/></label>
      <label>Микрорайон<select aria-label="Микрорайон" value={filters.district_id||''} onChange={e=>change({district_id:e.target.value})}><option value="">Все микрорайоны</option><option value="0">Не определён</option>{meta.districts.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
      <label>Неисправность<select value={filters.is_defect||''} onChange={e=>change({is_defect:e.target.value})}><option value="">Все фотографии</option><option value="true">С неисправностями</option><option value="false">Без неисправностей</option></select></label>
    </div>
    </PhotoFilterOptions>
  </div>;
}
