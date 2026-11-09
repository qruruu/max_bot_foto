import type { ReactNode } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { dateLabel, shiftDate } from './api';

export function PhotoPeriod({today, from = '', to = '', change, children}: {
  today: string; from?: string; to?: string;
  change: (dates: {date_from: string; date_to: string}) => void; children?: ReactNode;
}) {
  const current = to || from || today;
  const period = from && to ? (from === to ? dateLabel(to) : `${dateLabel(from)} – ${dateLabel(to)}`)
    : from ? 'С ' + dateLabel(from) : to ? 'До ' + dateLabel(to) : 'За всё время';
  const shortcuts = [
    ['Сегодня', today, today],
    ['Вчера', shiftDate(today, -1), shiftDate(today, -1)],
    ['7 дней', shiftDate(today, -6), today],
    ['Этот месяц', today.slice(0, 8) + '01', today],
    ['За всё время', '', ''],
  ];
  return <div className="period-row photo-period-row">
    <div className="date-switch">
      <button type="button" aria-label="Предыдущий день" onClick={() => {const day = shiftDate(current, -1); change({date_from: day, date_to: day});}}><ChevronLeft size={18}/></button>
      <strong>{period}</strong>
      <button type="button" aria-label="Следующий день" onClick={() => {const day = shiftDate(current, 1); change({date_from: day, date_to: day});}}><ChevronRight size={18}/></button>
    </div>
    <div className="quick-period">{shortcuts.map(([label, start, end]) =>
      <button type="button" key={label} aria-pressed={from === start && to === end}
        onClick={() => change({date_from: start, date_to: end})}>{label}</button>)}</div>
    {children}
  </div>;
}
