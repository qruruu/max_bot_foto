import type { PermissionDefinition } from './types';
import { changePermission } from './permissions';

export default function PermissionEditor({catalog, value, onChange, administrator}: {
  catalog: PermissionDefinition[];
  value: string[];
  onChange: (value: string[]) => void;
  administrator: boolean;
}) {
  return <section className="permissions-editor" aria-labelledby="permissions-title">
    <h3 id="permissions-title">Доступные функции</h3>
    {administrator ? <p className="hint">Администратор имеет полный доступ, включая управление операторами и выдачу прав.</p> : <>
      <p className="hint">Отметьте разрешённые функции. Необходимые права на просмотр включаются вместе с изменением. Без галочек останется только личный аккаунт.</p>
      <div className="permission-actions">
        <button type="button" onClick={() => onChange(catalog.filter(item => item.default_operator).map(item => item.code))}>Обычный оператор</button>
        <button type="button" onClick={() => onChange(catalog.filter(item => ['reports_view','photos_view','spam_view','districts_view'].includes(item.code)).map(item => item.code))}>Только просмотр</button>
        <button type="button" onClick={() => onChange([])}>Снять все</button>
      </div>
      <div className="permission-groups">{[...new Set(catalog.map(item => item.group))].map(group => <fieldset key={group}>
        <legend>{group}</legend>
        {catalog.filter(item => item.group === group).map(item => <label className="checkbox" key={item.code}>
          <input type="checkbox" checked={value.includes(item.code)} onChange={event => onChange(changePermission(value, item.code, event.target.checked, catalog))}/>
          {item.name}
        </label>)}
      </fieldset>)}</div>
      <p className="hint">Для переноса в спам также нужно право на изменение фото. Управление операторами и выдача прав доступны только администратору. После изменения прав оператору нужно войти снова.</p>
    </>}
  </section>;
}
