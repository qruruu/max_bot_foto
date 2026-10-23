import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Search } from 'lucide-react';
import { api } from './api';

export function photoNumber(value: string): number | null {
  const match = value.trim().match(/^[#№]?\s*(\d+)$/u);
  if (!match) return null;
  const number = Number(match[1]);
  return Number.isInteger(number) && number > 0 && number <= 2147483647 ? number : null;
}

export async function findPhotoByNumber(value: string, signal?: AbortSignal): Promise<number> {
  const id = photoNumber(value);
  if (id === null) throw new Error('Введите номер фотографии, например 195 или #195.');
  const photo = await api<{id: number}>('/photos/' + id, 'GET', undefined, signal);
  return photo.id;
}

export default function PhotoNumberSearch({owner, open}: {owner: boolean; open: (id: number) => void}) {
  const [value, setValue] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  async function search(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError('');
    try { open(await findPhotoByNumber(value, controller.signal)); }
    catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className="panel photo-number-search" aria-label="Поиск фотографии по номеру">
    <form onSubmit={search}>
      <label htmlFor="photo-number">Номер фотографии</label>
      <div className="photo-number-controls"><input id="photo-number" inputMode="numeric" autoComplete="off"
        placeholder="Например, 195" value={value} onChange={e => setValue(e.target.value)} disabled={busy}/>
        <button type="submit" disabled={busy || !value.trim()}><Search size={17}/>{busy ? 'Ищем…' : 'Найти фото'}</button></div>
    </form>
    <p className="hint">{owner ? 'Ищет в этой организации среди рабочих и тестовых фото, независимо от даты и фильтров.'
      : 'Ищет среди доступных вам фото текущего режима, независимо от даты и фильтров.'}</p>
    {error && <div className="error" role="alert">{error}</div>}
  </section>;
}
