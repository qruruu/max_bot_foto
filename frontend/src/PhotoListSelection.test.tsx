// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AppContextProvider, PhotoList } from './App';
import { api } from './api';
import { downloadPhotos } from './photoDownload';
import { selectFilteredPhotos } from './photoSelection';
import type { Filters, Meta, User } from './types';

vi.mock('./api', async () => ({...await vi.importActual('./api'), api: vi.fn()}));
vi.mock('./photoDownload', () => ({downloadPhotos: vi.fn().mockResolvedValue(undefined)}));
vi.mock('./photoSelection', async () => ({...await vi.importActual('./photoSelection'), selectFilteredPhotos: vi.fn()}));
vi.mock('./FilterBar', () => ({default: ({change}: {change: (filters: Filters) => void}) =>
  <button onClick={() => change({chat_id: '456'})}>Другой чат</button>}));

const photos = Array.from({length: 12}, (_, index) => ({id: index + 1, preview_url: `/preview/${index + 1}`}));
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.mocked(selectFilteredPhotos).mockResolvedValue({filters: {chat_id: '123', date_from: '2026-11-12', date_to: '2026-11-12', work_only: 'true'}, snapshot_id: 12, count: 12, ids: photos.map(photo => photo.id)});
  vi.mocked(api).mockResolvedValue({items: [{...photos[0], received_at: '2026-11-12T09:00:00Z', ai_confidence: null}], total: 12, page: 1, page_size: 1});
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  const user = {id: 1, role: 'ADMIN_OPERATOR', permissions: ['photos_view']} as User;
  const meta = {today: '2026-11-13', organization: {id: 'one'}, work_types: [], districts: [], chats: [], statuses: [], operators: []} as unknown as Meta;
  await act(async () => root.render(<MemoryRouter initialEntries={['/photos?chat_id=123&date_from=2026-11-12&date_to=2026-11-12']}>
    <AppContextProvider value={{user, meta, refresh: async () => {}, notify: () => {}, updateUser: () => {}}}>
      <PhotoList/>
    </AppContextProvider>
  </MemoryRouter>));
});

afterEach(async () => {await act(async () => root.unmount()); host.remove(); vi.clearAllMocks(); vi.unstubAllGlobals();});
async function click(text: string) {
  const button = [...host.querySelectorAll('button')].find(button => button.textContent === text)!;
  expect(button).toBeDefined();
  await act(async () => button.click());
}

it('selects across pages using the active filters, then downloads the full selection', async () => {
  await click('Выбрать все');
  expect(selectFilteredPhotos).toHaveBeenCalledWith(expect.objectContaining({chat_id: '123', date_from: '2026-11-12', date_to: '2026-11-12', work_only: 'true'}), expect.any(AbortSignal));
  expect(host.textContent).toContain('Выбрано фотографий: 12');
  expect(host.querySelector<HTMLInputElement>('[aria-label="Выбрать фото №1"]')?.checked).toBe(true);
  await click('Скачать');
  expect(downloadPhotos).toHaveBeenCalledWith({ids: photos.map(photo => photo.id)}, expect.any(Function), expect.any(Function));
});

it('allows excluding an individual photo from select-all before downloading', async () => {
  await click('Выбрать все');
  await act(async () => host.querySelector<HTMLInputElement>('[aria-label="Выбрать фото №1"]')!.click());
  expect(host.textContent).toContain('Выбрано фотографий: 11');
  await click('Скачать');
  expect(downloadPhotos).toHaveBeenCalledWith({ids: photos.slice(1).map(photo => photo.id)}, expect.any(Function), expect.any(Function));
});

it('clears the previous selection when the user changes filters', async () => {
  await click('Выбрать все');
  await click('Другой чат');
  expect(host.textContent).not.toContain('Выбрано фотографий:');
  expect([...host.querySelectorAll('button')].some(button => button.textContent === 'Скачать')).toBe(false);
});

it('keeps select-all when moving to another page without loading the whole selection', async () => {
  await click('Выбрать все');
  vi.mocked(api).mockResolvedValueOnce({items: [{...photos[1], received_at: '2026-11-12T09:00:00Z', ai_confidence: null}], total: 12, page: 2, page_size: 1});
  await click('Далее');
  expect(host.querySelector<HTMLInputElement>('[aria-label="Выбрать фото №2"]')?.checked).toBe(true);
  expect(host.textContent).toContain('Выбрано фотографий: 12');
  expect(selectFilteredPhotos).toHaveBeenCalledOnce();
});

it('caps select-all at fifty, disables unchecked rows and re-enables them after deselection', async () => {
  vi.mocked(selectFilteredPhotos).mockResolvedValueOnce({filters: {chat_id: '123'}, snapshot_id: 51, count: 51,
    ids: Array.from({length: 51}, (_, index) => index + 1)});
  await click('Выбрать все');
  expect(host.textContent).toContain('Выбрано фотографий: 50');
  expect(host.textContent).not.toContain('За один раз можно скачать');
  const download = [...host.querySelectorAll('button')].find(button => button.textContent === 'Скачать')!;
  expect(download.disabled).toBe(false);
  vi.mocked(api).mockResolvedValueOnce({items: [
    {...photos[0], received_at: '2026-11-12T09:00:00Z', ai_confidence: null},
    {id: 51, preview_url: '/preview/51', received_at: '2026-11-12T09:00:00Z', ai_confidence: null},
  ], total: 51, page: 2, page_size: 2});
  await click('Далее');
  const extra = host.querySelector<HTMLInputElement>('[aria-label="Выбрать фото №51"]')!;
  expect(extra.checked).toBe(false);
  expect(extra.disabled).toBe(true);
  const first = host.querySelector<HTMLInputElement>('[aria-label="Выбрать фото №1"]')!;
  expect(first.disabled).toBe(false);
  await act(async () => first.click());
  expect(extra.disabled).toBe(false);
  await act(async () => extra.click());
  expect(host.textContent).toContain('Выбрано фотографий: 50');
  expect(first.disabled).toBe(true);
  await click('Скачать');
  expect(downloadPhotos).toHaveBeenCalledWith({ids: [...Array.from({length: 49}, (_, index) => index + 2), 51]},
    expect.any(Function), expect.any(Function));
});
