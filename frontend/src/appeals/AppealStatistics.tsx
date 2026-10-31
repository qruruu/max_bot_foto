import { useEffect, useState } from 'react';
import { Download, RefreshCw } from 'lucide-react';
import { api } from '../api';
import { appealStatuses } from './statuses';
import './appeal-statistics.css';

export type AppealFilterOptions = {work_types: {code: string; name: string}[]; operators: {value: string; name: string}[]; organizations: {id: string; name: string}[]};
type Person = {key: string; name: string; organization_name: string; total: number; completed: number; active: number; overdue: number; other: number; average_days: number | null};
type Report = {start: string; end: string; timezone: string; total: number; completed: number; active: number; overdue: number; average_days: number | null; on_time_percent: number | null; timed_tasks: number;
  operators: Person[]; work_types: {code: string; name: string; count: number}[]; statuses: {code: string; count: number}[]; options: AppealFilterOptions};
const localDate = (value: Date) => `${value.getFullYear()}-${String(value.getMonth()+1).padStart(2,'0')}-${String(value.getDate()).padStart(2,'0')}`;
function range(days: number) {const end = new Date(), start = new Date(); start.setDate(end.getDate() - days + 1); return {start: localDate(start), end: localDate(end)};}
const number = (n: number | null, suffix = '') => n == null ? 'Нет данных' : n.toLocaleString('ru-RU') + suffix;
const colors = ['#35765b','#65a589','#ddaa4a','#ac7e9f','#7c9992','#bd795c','#8295ae','#947c60','#b87373','#90978b'];

export default function AppealStatistics({endpoint}: {endpoint: string}) {
  const [dates, setDates] = useState(() => range(30)), [period, setPeriod] = useState('30');
  const [organization, setOrganization] = useState(''), [operator, setOperator] = useState(''), [category, setCategory] = useState('');
  const [data, setData] = useState<Report | null>(null), [options, setOptions] = useState<AppealFilterOptions | null>(null);
  const [error, setError] = useState(''), [revision, setRevision] = useState(0), [sort, setSort] = useState<keyof Pick<Person, 'total'|'completed'|'overdue'|'average_days'>>('total');
  useEffect(() => {
    const abort = new AbortController(); setData(null); setError('');
    const params = new URLSearchParams({...dates});
    if (operator) params.set('operator', operator);
    if (category) params.set('category', category);
    if (organization) params.set('organization', organization);
    api<Report>(endpoint + '/statistics?' + params, 'GET', undefined, abort.signal)
      .then(value => {if (!abort.signal.aborted) {setData(value); setOptions(value.options);}})
      .catch(reason => {if (!abort.signal.aborted) setError(reason.message);});
    return () => abort.abort();
  }, [endpoint, dates, organization, operator, category, revision]);
  const reset = () => {setDates(range(30)); setPeriod('30'); setOrganization(''); setOperator(''); setCategory('');};
  function exportCsv() {
    if (!data) return;
    const rows: (string|number|null)[][] = [
      ['Статистика обращений', data.start, data.end], ['Часовой пояс', data.timezone],
      ['Показатель', 'Значение'], ['Всего обращений', data.total], ['Закрыто', data.completed], ['В работе и на рассмотрении', data.active],
      ['Просрочено текущих задач', data.overdue], ['Среднее время до закрытия, дни', data.average_days], ['Выполнено в срок, %', data.on_time_percent],
      [], ['Исполнитель', 'Организация', 'Всего назначений', 'Выполнено', 'В работе без просрочки', 'Просрочено', 'Другие результаты', 'Среднее время, дни'],
      ...data.operators.map(p => [p.name, p.organization_name, p.total, p.completed, p.active, p.overdue, p.other, p.average_days]),
      [], ['Вид работ', 'Обращений'], ...data.work_types.map(w => [w.name, w.count]),
      [], ['Состояние', 'Обращений'], ...data.statuses.map(s => [appealStatuses[s.code] || s.code, s.count]),
    ];
    const cell = (v: string|number|null) => '"' + String(v ?? '').replace(/^\s*[=+@-]/, "'$&").replaceAll('"','""') + '"';
    const url = URL.createObjectURL(new Blob(['\ufeff' + rows.map(row => row.map(cell).join(';')).join('\r\n')], {type: 'text/csv;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = `обращения-${data.start}-${data.end}.csv`; link.click(); window.setTimeout(() => URL.revokeObjectURL(url),1000);
  }
  const people = data ? [...data.operators].sort((a,b) => (b[sort] ?? -1) - (a[sort] ?? -1)) : [];
  const maxTasks = Math.max(1, ...(data?.operators.map(p => p.total) || []));
  const maxWork = Math.max(1, ...(data?.work_types.map(w => w.count) || []));
  let offset = 0;
  const segments = data?.statuses.map((s,i) => {const start = offset; offset += s.count / Math.max(data.total,1) * 100; return `${colors[i%colors.length]} ${start}% ${offset}%`;});
  return <section className="appeal-statistics" aria-label="Статистика обращений">
    <div className="panel appeal-report-filters">
      <label>Период<select value={period} onChange={e => {setPeriod(e.target.value); if (e.target.value !== 'custom') setDates(range(Number(e.target.value)));}}><option value="7">Последние 7 дней</option><option value="30">Последние 30 дней</option><option value="90">Последние 90 дней</option><option value="custom">Свой период</option></select></label>
      {period === 'custom' && <><label>С даты<input type="date" value={dates.start} max={dates.end} onChange={e => {if (e.target.value) setDates({...dates,start:e.target.value});}}/></label><label>По дату<input type="date" value={dates.end} min={dates.start} onChange={e => {if (e.target.value) setDates({...dates,end:e.target.value});}}/></label></>}
      {options && options.organizations.length > 1 && !endpoint.includes('/inspection/') && <label>Организация<select value={organization} onChange={e => {setOrganization(e.target.value); setOperator('');}}><option value="">Все организации</option>{options.organizations.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>}
      <label>Исполнитель<select value={operator} onChange={e => setOperator(e.target.value)}><option value="">Все исполнители</option>{options?.operators.filter(o => !organization || o.value.startsWith(organization+':')).map(o => <option key={o.value} value={o.value}>{o.name}</option>)}</select></label>
      <label>Вид работ<select value={category} onChange={e => setCategory(e.target.value)}><option value="">Все виды</option>{options?.work_types.map(w => <option key={w.code} value={w.code}>{w.name}</option>)}</select></label>
      <button onClick={reset}><RefreshCw size={16}/>Сбросить</button><button aria-label="Обновить статистику" onClick={() => setRevision(v=>v+1)}><RefreshCw size={16}/></button>
      <button className="primary" onClick={exportCsv} disabled={!data}><Download size={16}/>Экспорт CSV</button>
    </div>
    {error && <p role="alert" className="error">{error}</p>}
    {!data ? !error && <p className="loading">Считаем статистику…</p> : <>
      <div className="appeal-report-metrics">{[
        ['Всего обращений', number(data.total)], ['Закрыто', number(data.completed)], ['В работе и на рассмотрении', number(data.active)],
        ['Просрочено задач', number(data.overdue)], ['Среднее время до закрытия', number(data.average_days, ' дн.')], ['Выполнено в срок', number(data.on_time_percent, '%')],
      ].map(([label,value]) => <article className="panel" key={label}><span>{label}</span><strong className={value === 'Нет данных' ? 'appeal-report-unknown' : ''}>{value}</strong></article>)}</div>
      {!data.total && <p className="hint">За выбранный период обращений нет. Измените период или фильтры.</p>}
      <div className="appeal-report-grid">
        <section className="panel"><h3>Загрузка исполнителей</h3><div className="appeal-chart-legend"><span className="done">Выполнено</span><span className="active">В работе</span><span className="late">Просрочено</span><span className="other">Другие результаты</span></div>
          {data.operators.length ? data.operators.map(p => <div key={p.key} className="appeal-bar-row"><span title={p.organization_name}>{p.name}</span><div className="appeal-bar-track" role="img" aria-label={`${p.name}: выполнено ${p.completed}, в работе ${p.active}, просрочено ${p.overdue}, другие ${p.other}`}>
            <div className="appeal-bar-stack" style={{width:`${p.total/maxTasks*100}%`}}>{(['completed','active','overdue','other'] as const).map(key => p[key] > 0 && <span key={key} className={key} style={{width:`${p[key]/p.total*100}%`}} title={String(p[key])}>{p[key]}</span>)}</div></div><b>{p.total}</b></div>) : <p className="hint">Назначений пока нет.</p>}
        </section>
        <section className="panel"><h3>Итоги рассмотрения</h3><div className="appeal-donut-layout"><div className="appeal-donut" role="img" aria-label={`Всего ${data.total} обращений`} style={{background:data.total ? `conic-gradient(${segments?.join(',')})` : 'var(--border)'}}><span><small>Всего</small><strong>{data.total}</strong></span></div><ul className="appeal-status-legend">{data.statuses.map((s,i) => <li key={s.code}><i style={{background:colors[i%colors.length]}}/><span>{appealStatuses[s.code] || s.code}</span><b>{s.count}</b><small>{Math.round(s.count/Math.max(1,data.total)*100)}%</small></li>)}</ul></div></section>
        <section className="panel"><h3>Обращения по видам работ</h3>{data.work_types.map(w => <div key={w.code} className="appeal-bar-row"><span>{w.name}</span><div className="appeal-bar-track"><div className="appeal-work-bar" style={{width:`${w.count/maxWork*100}%`}}/></div><b>{w.count}</b></div>)}</section>
        <section className="panel appeal-report-table"><h3>Результаты исполнителей</h3><div className="table-scroll"><table><thead><tr><th>Исполнитель</th>{([['total','Всего задач'],['completed','Выполнено'],['overdue','Просрочено'],['average_days','Среднее время']] as const).map(([key,label]) => <th key={key}><button onClick={() => setSort(key)} aria-label={'Сортировать: '+label}>{label}{sort === key ? ' ↓' : ''}</button></th>)}</tr></thead><tbody>{people.map(p => <tr key={p.key}><td>{p.name}<small>{p.organization_name}</small></td><td>{p.total}</td><td>{p.completed}</td><td className={p.overdue ? 'appeal-overdue' : ''}>{p.overdue}</td><td>{number(p.average_days,' дн.')}</td></tr>)}</tbody></table></div></section>
      </div>
      <section className="panel appeal-report-statuses"><h3>Обращения по состояниям</h3><div className="appeal-status-track">{data.statuses.map((s,i) => <span key={s.code} style={{width:`${s.count/Math.max(1,data.total)*100}%`,background:colors[i%colors.length]}} title={`${appealStatuses[s.code]}: ${s.count}`}/>)}</div><div className="appeal-chart-legend">{data.statuses.map((s,i) => <span key={s.code}><i style={{background:colors[i%colors.length]}}/>{appealStatuses[s.code]}: <b>{s.count}</b></span>)}</div></section>
      <p className="hint appeal-report-method">Обращения отобраны по дате поступления, включая архив. «Закрыто» — только успешно закрытые обращения. Просрочка — у текущих незавершённых задач после конца назначенного дня ({data.timezone}). Среднее время обращения считается до закрытия, исполнителя — до передачи выполненного результата. В срок: выполненные задачи с датой завершения и назначенным сроком ({data.timed_tasks}). Старые задачи без даты завершения исключены из расчёта времени. При фильтре по исполнителю выбираются обращения с его текущим назначением.</p>
    </>}
  </section>;
}
