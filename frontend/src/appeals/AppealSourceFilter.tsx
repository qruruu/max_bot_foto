export type AppealSource = 'all' | 'inspector' | 'signal';
export const sourceLabels = {all: 'Все источники', inspector: 'Задачи проверяющих', signal: 'Обращения из Сигнала'};
export default function AppealSourceFilter({value, onChange}: {value: AppealSource; onChange: (value: AppealSource) => void}) {
  return <label>Источник<select name="source" value={value} onChange={event => onChange(event.target.value as AppealSource)}>{Object.entries(sourceLabels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>;
}
