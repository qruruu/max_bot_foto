import { useRef, useState } from 'react';
import { api, dateLabel, shiftDate } from './api';
import { createAdminTask, findTaskOperator } from './appeals/adminTaskData';
import type { AdminTaskDraft, TaskOperator } from './appeals/adminTaskData';

const endpoint = '/appeals/internal-tasks';
type Task = {
  id: string; operators: TaskOperator[]; operator?: TaskOperator; subject?: string | null;
  description?: string | null; dueDate?: string | null; files?: File[];
};
type Step = 'operator' | 'description' | 'deadline' | 'photos' | 'review';

function taskStep(task: Task): Step {
  if (!task.operator) return 'operator';
  if (!task.description) return 'description';
  if (task.dueDate === undefined) return 'deadline';
  return task.files === undefined ? 'photos' : 'review';
}

function taskTitle(task: Task): string {
  return task.subject?.trim() || task.description?.split('\n')[0].slice(0, 80).trim() || '';
}

function prompt(task: Task): string {
  switch (taskStep(task)) {
    case 'operator': return task.operators.length ? 'Кому назначить задачу? Выберите оператора из списка.' : 'В этой организации нет активных операторов для назначения.';
    case 'description': return 'Что нужно сделать? Напишите поручение одним сообщением.';
    case 'deadline': return 'К какому сроку выполнить задачу? Можно написать «завтра», указать дату или пропустить этот шаг.';
    case 'photos': return 'Есть фото или скриншоты для исполнителя? Можно прикрепить до трёх файлов. Это необязательно.';
    case 'review': return [
      'Проверьте задачу перед созданием.',
      `Исполнитель — ${task.operator?.name}`,
      `Название — ${taskTitle(task)}`,
      `Что сделать — ${task.description}`,
      `Срок — ${task.dueDate ? dateLabel(task.dueDate) : 'без срока'}`,
      `Фото — ${task.files?.length || 0}`,
    ].join('\n');
  }
}

function deadline(text: string, today: string) {
  const value = text.toLocaleLowerCase('ru-RU').trim().replace(/^до +/, '');
  if (value === 'сегодня') return today;
  if (value === 'завтра') return shiftDate(today, 1);
  if (value === 'послезавтра') return shiftDate(today, 2);
  const parts = /^(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?$/.exec(value);
  const date = parts
    ? `${parts[3] || today.slice(0, 4)}-${parts[2].padStart(2, '0')}-${parts[1].padStart(2, '0')}`
    : value;
  const instant = new Date(date + 'T12:00:00Z');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(+instant) || instant.toISOString().slice(0, 10) !== date) return null;
  return date >= today ? date : null;
}

export default function useAssistantTask(today: string, append: (reply: string, question?: string) => void) {
  const [task, setTask] = useState<Task>();
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const step = task && taskStep(task);

  function advance(next: Task, question?: string) {
    setTask(next);
    setError('');
    append(prompt(next), question);
  }

  async function begin(initial: AdminTaskDraft, question: string) {
    const operators = await api<TaskOperator[]>(endpoint + '/options');
    const operator = initial.executor ? findTaskOperator(operators, initial.executor) : undefined;
    setFiles([]);
    advance({
      id: crypto.randomUUID(), operators, operator,
      subject: initial.subject, description: initial.description?.trim(),
      dueDate: initial.dueDate ?? undefined,
    }, question);
  }

  function chooseOperator(operator: TaskOperator) {
    if (task && step === 'operator') advance({...task, operator}, operator.name);
  }

  function skipDeadline() {
    if (task && step === 'deadline') advance({...task, dueDate: null}, 'Без срока');
  }

  function reply(text: string) {
    if (!task) return false;
    if (step === 'description') {
      advance({...task, description: text}, text);
      return true;
    }
    if (step === 'deadline') {
      if (/^(?:без срока|пропустить)$/i.test(text)) {
        skipDeadline();
        return true;
      }
      const dueDate = deadline(text, today);
      if (dueDate) {
        advance({...task, dueDate}, text);
        return true;
      }
      setError('Укажите дату, например 15.11, или нажмите «Пропустить срок».');
    }
    return false;
  }

  function changeFiles(next: File[]) {
    if (next.length > 3) {
      setError('Можно приложить до трёх фото или скриншотов.');
      return;
    }
    setError('');
    setFiles(next);
  }

  function finishPhotos(include: boolean) {
    if (!task || step !== 'photos') return;
    advance({...task, files: include ? files : []}, include && files.length ? `Фото приложено: ${files.length}` : 'Без фото');
  }

  function cancel() {
    if (savingRef.current) return;
    setTask(undefined);
    setError('');
    append('Черновик задачи отменён.');
  }

  async function confirm() {
    if (step !== 'review' || !task?.operator || !task.description || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setError('');
    try {
      const {id} = await createAdminTask(endpoint, {
        client_id: task.id,
        subject: taskTitle(task),
        description: task.description,
        operator_id: task.operator.id,
        due_date: task.dueDate ?? null,
      }, task.files ?? []);
      setTask(undefined);
      append(`Задача №${id} создана и назначена исполнителю.`, 'Создать задачу');
      window.dispatchEvent(new Event('appeals-changed'));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось создать задачу.');
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  return {
    step, operators: task?.operators ?? [], files, error, saving, begin, chooseOperator, reply,
    skipDeadline, changeFiles, finishPhotos, cancel, confirm,
  };
}
