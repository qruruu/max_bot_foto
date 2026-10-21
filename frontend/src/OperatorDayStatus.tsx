import { useEffect, useState } from 'react';
import { RefreshCw, Users } from 'lucide-react';
import { api, dateLabel } from './api';
import { useApp } from './App';
import { hasPermission } from './permissions';
import './day-reviews.css';

export const progressLabels = {
  CLOSED: 'Закрыл день', NOT_CLOSED: 'Не закрыл', ADDITIONS: 'Есть дополнения',
  CLOSED_BY_OTHER: 'Закрыт другим оператором', NO_PHOTOS: 'Нет фотографий', NO_PERMISSION: 'Нет права закрывать день',
};
export type OperatorDay = {
  id: number; name: string; status: keyof typeof progressLabels;
  chats: {id: number; name: string}[]; total: number; confirmed: number; pending: number;
  last_closed_at: string | null; confirmed_by: string[];
};

export function OperatorDayTable({items, timezone}: {items: OperatorDay[]; timezone: string}) {
  const format = (value: string) => new Date(value).toLocaleString('ru-RU', {timeZone: timezone});
  return <div className="table-scroll"><table className="operator-day-table"><thead><tr>
    <th>Оператор</th><th>Доступные чаты</th><th>Состояние дня</th><th>Фотографии</th><th>Закрытие</th>
  </tr></thead><tbody>{items.map(item => <tr key={item.id}>
    <td><strong>{item.name}</strong></td>
    <td><div className="operator-day-chats">{item.chats.map(chat => <span key={chat.id}>{chat.name}</span>)}</div></td>
    <td><span className={'badge ' + (item.status === 'CLOSED' ? 'status-ACCEPTED' : ['NOT_CLOSED', 'ADDITIONS'].includes(item.status) ? 'status-NEEDS_REVIEW' : '')}>{progressLabels[item.status]}</span></td>
    <td><strong>{item.confirmed} из {item.total}</strong><small>{item.pending ? `Осталось проверить: ${item.pending}` : item.total ? 'Все фото подтверждены' : 'За выбранную дату'}</small></td>
    <td><span>{item.last_closed_at ? 'Сам: ' + format(item.last_closed_at) : 'Сам не закрывал'}</span>
      {!!item.confirmed_by.length && <small>Подтверждали: {item.confirmed_by.join(', ')}</small>}</td>
  </tr>)}</tbody></table>{!items.length && <p className="muted">Нет операторов с доступом к этим чатам.</p>}</div>;
}

export default function OperatorDayStatus({day, refreshKey = 0, dateEditable = false}: {day: string; refreshKey?: number | string; dateEditable?: boolean}) {
  const {meta, user} = useApp();
  const enabled = meta.chats.length > 1 && hasPermission(user, 'reports_view');
  const accessKey = meta.chats.map(chat => chat.id).sort((a, b) => a - b).join(',');
  const [selectedDay, setSelectedDay] = useState(day), [revision, setRevision] = useState(0);
  const [items, setItems] = useState<OperatorDay[] | null>(null), [error, setError] = useState('');
  useEffect(() => {setSelectedDay(day);}, [day]);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController(); setItems(null); setError('');
    api<{items: OperatorDay[]}>('/day-reviews/' + selectedDay + '/operators', 'GET', undefined, controller.signal)
      .then(result => {if (!controller.signal.aborted) setItems(result.items);})
      .catch(error => {if (!controller.signal.aborted) setError(error.message);});
    return () => controller.abort();
  }, [enabled, accessKey, selectedDay, refreshKey, revision]);
  if (!enabled) return null;
  return <section className="panel operator-day-panel">
    <div className="section-title"><div><h2><Users size={18}/>Контроль операторов</h2><span>За {dateLabel(selectedDay)} · по дате на фотографии</span></div>
      <div className="operator-day-actions">{dateEditable && <label>Дата проверки<input type="date" value={selectedDay} onChange={e => {if (e.target.value) setSelectedDay(e.target.value);}}/></label>}
        <button aria-label="Обновить контроль операторов" onClick={() => setRevision(value => value + 1)}><RefreshCw size={17}/></button></div>
    </div>
    <p className="hint">Показаны только доступные вам чаты. Закрытие другим сотрудником отмечается отдельно; поздние фото и изменения возвращают день на проверку.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {items ? <OperatorDayTable items={items} timezone={meta.timezone}/> : !error && <p className="muted">Загружаем состояние дней…</p>}
  </section>;
}
