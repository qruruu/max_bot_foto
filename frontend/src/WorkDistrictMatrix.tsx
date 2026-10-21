import type { Filters, Meta, Report } from './types';

export default function WorkDistrictMatrix({report, meta, filters, canBrowse, open}: {
  report: Report; meta: Pick<Meta, 'districts' | 'work_types'>; filters: Filters; canBrowse: boolean; open: (filters: Filters) => void;
}) {
  const cells = report.work_district_matrix || [];
  const works = new Map(meta.work_types.map(work => [work.code, {id: work.code, name: work.name}]));
  for (const work of report.work_types) if (!works.has(String(work.id))) works.set(String(work.id), {id: String(work.id), name: work.name});
  const districts = new Map(meta.districts.filter(district => district.active).map(district => [Number(district.id), {id: Number(district.id), name: district.name}]));
  for (const district of report.districts) if (!districts.has(Number(district.id))) districts.set(Number(district.id), {id: Number(district.id), name: district.name});
  const rows = [...works.values()].filter(work => !filters.work_type || work.id === filters.work_type);
  const columns = [...districts.values()].filter(district => filters.district_id === undefined || filters.district_id === '' || district.id === Number(filters.district_id));
  const counts = new Map(cells.map(cell => [cell.work_type + ':' + cell.district_id, cell.count]));
  const count = (work: string, district: number) => counts.get(work + ':' + district) || 0;
  return <section className="panel work-district-panel">
    <div className="section-title"><h2>Вид работы × микрорайон</h2><span>Количество фотографий</span></div>
    <p className="hint">За выбранный период с учётом фильтров. Ноль означает, что фотографий нет.{canBrowse && ' Нажмите на число, чтобы открыть фотографии.'}</p>
    {!rows.length || !columns.length ? <p className="muted">Добавьте виды работ и микрорайоны, чтобы видеть таблицу покрытия.</p> : <div className="table-scroll"><table>
      <thead><tr><th>Вид работы</th>{columns.map(district => <th key={district.id}>{district.name}</th>)}<th>Всего</th></tr></thead>
      <tbody>{rows.map(work => <tr key={work.id}><th scope="row">{work.name}</th>{columns.map(district => {
        const value = count(work.id, district.id);
        return <td key={district.id}>{value ? <button className="number-link" disabled={!canBrowse} onClick={() => open({work_type: work.id, district_id: String(district.id)})}>{value}</button> : <span className="muted">0</span>}</td>;
      })}<td><strong>{columns.reduce((total, district) => total + count(work.id, district.id), 0)}</strong></td></tr>)}</tbody>
      <tfoot><tr><th>Всего</th>{columns.map(district => <td key={district.id}><strong>{rows.reduce((total, work) => total + count(work.id, district.id), 0)}</strong></td>)}
        <td><strong>{rows.reduce((total, work) => total + columns.reduce((sum, district) => sum + count(work.id, district.id), 0), 0)}</strong></td></tr></tfoot>
    </table></div>}
  </section>;
}
