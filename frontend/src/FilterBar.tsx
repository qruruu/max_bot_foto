import { useEffect, useState } from 'react';
import { ArrowDownToLine, ChevronLeft, ChevronRight } from 'lucide-react';
import { useApp } from './App';
import { api, dateLabel, query, shiftDate, statusNames } from './api';
import { filterOptionLabel } from './filterCounts';
import { hasPermission } from './permissions';
import type { FilterCounts, Filters } from './types';

export default function FilterBar({filters, change, fixedStatus = false, hideWork = false, refreshKey = 0}: {
  filters: Filters;
  change: (values: Filters) => void;
  fixedStatus?: boolean;
  hideWork?: boolean;
  refreshKey?: number;
}) {
  const {meta, user} = useApp();
  const current = filters.date_to || meta.today;
  const key = query(filters);
  const [loaded, setLoaded] = useState<{key: string; counts: FilterCounts} | null>(null);
  const [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const counts = loaded?.key === key ? loaded.counts : undefined;
  useEffect(() => {
    const controller = new AbortController();
    setLoaded(null); setError('');
    api<FilterCounts>('/photos/filter-counts?' + key, 'GET', undefined, controller.signal)
      .then(value => {if (!controller.signal.aborted) setLoaded({key, counts: value});})
      .catch(e => {if (!controller.signal.aborted) setError(e.message);});
    return () => controller.abort();
  }, [key, refreshKey, retry]);
  const label = (name: string, facet: keyof FilterCounts, value?: string) => filterOptionLabel(name, counts?.[facet], value);

  return <div className="filter-panel">
    <div className="period-row">
      <div className="date-switch">
        <button aria-label="Предыдущий день" onClick={() => change({date_from: shiftDate(current, -1), date_to: shiftDate(current, -1)})}><ChevronLeft size={18}/></button>
        <strong>{filters.date_from === filters.date_to && filters.date_to ? dateLabel(filters.date_to) : 'Выбранный период'}</strong>
        <button aria-label="Следующий день" onClick={() => change({date_from: shiftDate(current, 1), date_to: shiftDate(current, 1)})}><ChevronRight size={18}/></button>
      </div>
      <div className="quick-period">
        {[
          ['Сегодня', meta.today], ['Вчера', shiftDate(meta.today, -1)],
          ['7 дней', shiftDate(meta.today, -6)], ['Этот месяц', meta.today.slice(0, 8) + '01'],
        ].map(([title, from]) => <button key={title} onClick={() => change({date_from: from, date_to: title === 'Вчера' ? from : meta.today})}>{title}</button>)}
        <button onClick={() => change({date_from: '', date_to: ''})}>За всё время</button>
      </div>
      {hasPermission(user, 'reports_export') && <a className="button export" href={'/api/export.xlsx?' + key}><ArrowDownToLine size={16}/>Скачать Excel</a>}
    </div>
    <div className="filters" aria-busy={!counts && !error}>
      <label>Дата от<input type="date" value={filters.date_from || ''} onChange={e => change({date_from: e.target.value})}/></label>
      <label>Дата до<input type="date" value={filters.date_to || ''} onChange={e => change({date_to: e.target.value})}/></label>
      <label>Микрорайон<select aria-label="Микрорайон" value={filters.district_id || ''} onChange={e => change({district_id: e.target.value})}>
        <option value="">{label('Все микрорайоны', 'district_id')}</option>
        <option value="0">{label('Не определён', 'district_id', '0')}</option>
        {meta.districts.map(d => <option key={d.id} value={d.id}>{label(d.name, 'district_id', String(d.id))}</option>)}
      </select></label>
      <label>Чат<select aria-label="Чат" value={filters.chat_id || ''} onChange={e => change({chat_id: e.target.value})}>
        <option value="">{label('Все чаты', 'chat_id')}</option>
        {meta.chats.map(c => <option key={c.id} value={c.max_chat_id}>{label(c.name, 'chat_id', c.max_chat_id)}</option>)}
      </select></label>
      {!hideWork && <label>Вид работы<select aria-label="Вид работы" value={filters.work_type || ''} onChange={e => change({work_type: e.target.value})}>
        <option value="">{label('Все виды работ', 'work_type')}</option>
        <option value="NONE">{label('Не определён', 'work_type', 'NONE')}</option>
        {meta.work_types.map(w => <option key={w.code} value={w.code}>{label(w.name, 'work_type', w.code)}</option>)}
      </select></label>}
      <label>Статус<select aria-label="Статус" disabled={fixedStatus} value={filters.accepted_only === 'true' ? 'ACCEPTED_ALL' : filters.status || ''}
        onChange={e => change({status: e.target.value === 'ACCEPTED_ALL' ? '' : e.target.value, accepted_only: e.target.value === 'ACCEPTED_ALL' ? 'true' : ''})}>
        <option value="">{label('Все статусы', 'status')}</option>
        <option value="ACCEPTED_ALL">{label('Принято системой', 'status', 'ACCEPTED_ALL')}</option>
        {meta.statuses.filter(s => s !== 'SPAM' || hasPermission(user, 'spam_view')).map(s => <option key={s} value={s}>{label(statusNames[s], 'status', s)}</option>)}
      </select></label>
      <label>Оператор<select aria-label="Оператор" value={filters.operator_id || ''} onChange={e => change({operator_id: e.target.value})}>
        <option value="">{label('Все операторы', 'operator_id')}</option>
        <option value="0">{label('Не проверено', 'operator_id', '0')}</option>
        {meta.operators.map(o => <option key={o.id} value={o.id}>{label(o.name, 'operator_id', String(o.id))}</option>)}
      </select></label>
      <label>Дата отчёта<select aria-label="Дата отчёта" value={filters.date_basis || 'photo'} onChange={e => change({date_basis: e.target.value})}>
        <option value="photo">Дата фотографии</option><option value="received">Дата получения</option>
      </select></label>
    </div>
    {error && <p className="hint filter-counts-error" role="status">Не удалось обновить количество фото. <button type="button" className="text-button" onClick={() => setRetry(value => value + 1)}>Повторить</button></p>}
  </div>;
}
