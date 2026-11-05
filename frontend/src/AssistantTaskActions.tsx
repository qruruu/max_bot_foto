import TaskImageInput from './appeals/TaskImageInput';
import type useAssistantTask from './useAssistantTask';

export default function AssistantTaskActions({task, resetDraft}: {
  task: ReturnType<typeof useAssistantTask>; resetDraft: () => void;
}) {
  if (!task.step) return null;
  return <div className="operator-assistant-actions">
    {task.step === 'operator' && task.operators.length > 0 && <select aria-label="Исполнитель" value="" onChange={event => {
      const operator = task.operators.find(item => item.id === Number(event.target.value));
      if (operator) task.chooseOperator(operator);
    }}>
      <option value="">Выберите оператора</option>
      {task.operators.map(operator => <option value={operator.id} key={operator.id}>{operator.name}</option>)}
    </select>}
    {task.step === 'photos' && <TaskImageInput disabled={false} allowPaste={false} files={task.files} onChange={task.changeFiles}/>}
    <div className="operator-assistant-action-buttons">
      {task.step === 'deadline' && <button type="button" onClick={() => {task.skipDeadline(); resetDraft();}}>Пропустить срок</button>}
      {task.step === 'photos' && <>
        <button type="button" onClick={() => task.finishPhotos(false)}>Пропустить фото</button>
        {!!task.files.length && <button type="button" className="primary" onClick={() => task.finishPhotos(true)}>Добавить фото</button>}
      </>}
      {task.step === 'review' && <button type="button" className="primary" disabled={task.saving} onClick={() => void task.confirm()}>
        {task.saving ? 'Создаём…' : 'Создать задачу'}
      </button>}
      <button type="button" disabled={task.saving} onClick={() => {task.cancel(); resetDraft();}}>Отменить задачу</button>
    </div>
  </div>;
}
