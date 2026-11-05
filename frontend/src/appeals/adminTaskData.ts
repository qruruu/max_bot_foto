import { api } from '../api';
import { galleryPhoto } from './gallery';

export type TaskOperator = {id: number; name: string};
export type AdminTaskDraft = {executor?: string | null; subject?: string | null; description?: string | null; dueDate?: string | null};
type TaskInput = {client_id: string; subject: string; description: string; operator_id: number; due_date: string | null};

const nameKey = (value: string) => value.toLocaleLowerCase('ru-RU').replaceAll('ё', 'е').trim().split(/\s+/).sort().join(' ');

export function findTaskOperator(operators: TaskOperator[], name: string) {
  const expected = nameKey(name);
  const matches = operators.filter(operator => nameKey(operator.name) === expected);
  return matches.length === 1 ? matches[0] : undefined;
}

export async function createAdminTask(endpoint: string, task: TaskInput, files: File[]) {
  const body = new FormData();
  body.append('metadata', JSON.stringify(task));
  for (const file of files) {
    const {blob} = await galleryPhoto(file);
    body.append('photos', blob, file.name);
  }
  return api<{id: number}>(endpoint, 'POST', body);
}
