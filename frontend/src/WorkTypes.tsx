import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Pencil, Plus, X } from 'lucide-react';
import { api } from './api';
import { ErrorBox, useApp } from './App';

type WorkType = { id: number; code: string; name: string; sort_order: number; version: number };

export default function WorkTypes() {
  const {refresh, notify} = useApp();
  const [rows, setRows] = useState<WorkType[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [formError, setFormError] = useState('');
  const [editing, setEditing] = useState<WorkType | null | undefined>();
  const [name, setName] = useState('');
  const [position, setPosition] = useState(1);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const dialog = useRef<HTMLFormElement>(null);

  async function load() { setRows(await api<WorkType[]>('/work-types')); setLoaded(true); }
  useEffect(() => { load().catch(e => setError(e.message)); }, []);
  useEffect(() => {
    if (editing === undefined) return;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    input.current?.focus();
    function key(event: KeyboardEvent) {
      if (event.key === 'Escape' && !busy) setEditing(undefined);
      if (event.key !== 'Tab') return;
      const elements = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)') || []);
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener('keydown', key);
    return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', key); opener.current?.focus(); };
  }, [editing, busy]);

  function open(row: WorkType | null) {
    opener.current = document.activeElement as HTMLElement;
    setName(row?.name || '');
    setPosition(row?.sort_order ?? Math.max(0, ...rows.map(w => w.sort_order)) + 1);
    setFormError(''); setEditing(row);
  }
  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setFormError('');
    let saved = false;
    try {
      await api('/work-types' + (editing ? '/' + editing.id : ''), editing ? 'PUT' : 'POST', {
        name: name.trim(), sort_order: position, ...(editing ? {version: editing.version} : {}),
      });
      // A subsequent refresh failure must not leave a submitted create form open for resubmission.
      saved = true; setEditing(undefined);
      await Promise.all([load(), refresh()]);
      setError(''); notify('Справочник сохранён');
    } catch (error) { (saved ? setError : setFormError)((error as Error).message); }
    finally { setBusy(false); }
  }
  return <>
    <header className="page-header"><div><span className="eyebrow">СПРАВОЧНИК</span><h1>Виды работ</h1>
      <p>Добавляйте виды работ, меняйте названия и порядок в списке.</p></div>
      <button className="primary" disabled={!loaded} onClick={() => open(null)}><Plus size={16}/>Добавить вид работы</button>
    </header>
    <ErrorBox error={error}/>
    <section className="panel">
      {!loaded && !error ? <p className="loading">Загружаем справочник…</p> : rows.length ? <div className="table-scroll"><table>
        <thead><tr><th>Порядок</th><th>Вид работы</th><th/></tr></thead>
        <tbody>{rows.map(row => <tr key={row.code}><td>{row.sort_order}</td><td><strong>{row.name}</strong></td>
          <td><button onClick={() => open(row)} aria-label={'Изменить ' + row.name}><Pencil size={15}/>Изменить</button></td></tr>)}</tbody>
      </table></div> : loaded && <p className="empty">Виды работ ещё не добавлены. Создайте первый вид работы.</p>}
    </section>
    <p className="footnote">Изменение названия и порядка сохраняет привязки фотографий и обученной нейросети. Новые виды работ доступны для ручного выбора сразу; для распознавания нужны размеченные примеры и обучение.</p>
    {editing !== undefined && <div className="modal-backdrop"><form ref={dialog} className="modal" role="dialog" aria-modal="true" aria-labelledby="work-type-title" onSubmit={save}>
      <div className="section-title"><h2 id="work-type-title">{editing ? 'Изменить вид работы' : 'Добавить вид работы'}</h2>
        <button type="button" disabled={busy} aria-label="Закрыть" onClick={() => setEditing(undefined)}><X size={18}/></button></div>
      <ErrorBox error={formError}/>
      <label>Название<input ref={input} required maxLength={100} disabled={busy} value={name} onChange={e => setName(e.target.value)}/></label>
      <label>Порядок в списке<input required type="number" min={1} max={1000000} step={1} disabled={busy} value={position} onChange={e => setPosition(Number(e.target.value))}/></label>
      <button className="primary" disabled={busy || !name.trim()}>{busy ? 'Сохранение…' : 'Сохранить'}</button>
    </form></div>}
  </>;
}
