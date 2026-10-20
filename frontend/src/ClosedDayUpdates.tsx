import { Link } from 'react-router-dom';
import { CalendarCheck, ChevronRight } from 'lucide-react';
import { dateLabel } from './api';
import type { Report } from './types';

export default function ClosedDayUpdates({updates}: {updates: Report['day_updates']}) {
  if (!updates?.length) return null;
  return <section className="panel day-state day-pending" aria-label="Дополнения к закрытым дням">
    <div className="section-title"><h2>Дополнения к закрытым дням</h2><CalendarCheck size={20}/></div>
    <p>Эти фотографии ещё не включены в проверенные итоги. Проверьте дополнения и добавьте их в день.</p>
    {updates.map(item => <Link key={item.day} className="list-row day-update-row" to={'/days?day=' + item.day}>
      <span className="day-update-copy"><strong>{dateLabel(item.day)}</strong><small>Не включено в день: {item.pending}. После закрытия поступило: {item.late}.{item.needs_review ? ` Требуют решения оператора: ${item.needs_review}.` : ''}</small></span>
      <span className="day-update-action">Проверить<ChevronRight size={16}/></span>
    </Link>)}
  </section>;
}
