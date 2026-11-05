export type AppealSource = 'all' | 'inspector' | 'signal' | 'admin';
export const sourceLabels = {all: 'Все источники', inspector: 'Задачи проверяющих', signal: 'Обращения из Сигнала', admin: 'Задачи администраторов'};
export default function AppealSourceFilter({value, onChange, includeAdmin = true}: {value: AppealSource; onChange: (value: AppealSource) => void; includeAdmin?: boolean}) {
  return <label>Источник<select name="source" value={value} onChange={event => onChange(event.target.value as AppealSource)}>{Object.entries(sourceLabels).filter(([id]) => includeAdmin || id !== 'admin').map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>;
}
