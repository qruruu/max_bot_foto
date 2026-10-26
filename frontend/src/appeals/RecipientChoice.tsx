type Choice = {value: string; label: string};

export default function RecipientChoice({label, name, options, value, disabled, onChange, autoComplete}: {
  label: string; name: string; options: Choice[]; value: string; disabled: boolean;
  onChange: (value: string) => void; autoComplete?: string;
}) {
  if (!options.length) return null;
  // A pending upload must retain its old payload even if the catalog has changed.
  if (disabled && value && !options.some(option => option.value === value)) return null;
  if (options.length === 1) return <dl className="citizen-fixed-field citizen-wide" data-field={name}>
    <dt>{label}</dt><dd>{options[0].label}</dd>
  </dl>;
  return <label className="citizen-wide">{label}<select name={name} required autoComplete={autoComplete}
    disabled={disabled} value={value} onChange={event => onChange(event.target.value)}>
    <option value="">{label === 'Город' ? 'Выберите город' : label === 'Организация' ? 'Выберите организацию' : 'Выберите вид работ'}</option>
    {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
  </select></label>;
}
