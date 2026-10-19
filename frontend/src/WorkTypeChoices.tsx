import { Check } from 'lucide-react';
import WorkTypeHint from './WorkTypeHint';
import { workTypeLabel } from './photoWork';

type WorkType = {code: string; name: string; description?: string};

export default function WorkTypeChoices({items, value, isDefect, disabled, onChange}: {
  items: WorkType[];
  value: string;
  isDefect: boolean;
  disabled: boolean;
  onChange: (code: string) => void;
}) {
  return <div className="work-options" role="group" aria-label="Виды работ">
    {items.map((work, index) => <div key={work.code} className={'work-option-row'+(value===work.code?' selected':'')}>
      <button type="button" className={'work-option-select'+(value===work.code?' selected':'')} disabled={disabled}
        aria-pressed={value===work.code} onClick={() => onChange(work.code)}>
        <span>{String(index+1).padStart(2,'0')}</span><span className="work-option-label">{workTypeLabel(work.name,isDefect&&value===work.code)}</span>
        {value===work.code && <Check size={16} aria-hidden="true"/>}
      </button>
      <WorkTypeHint name={work.name} description={work.description}/>
    </div>)}
  </div>;
}
