// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';
import { downloadPhotos } from './photoDownload';

vi.mock('./api', async () => ({...await vi.importActual('./api'), api: vi.fn()}));
afterEach(() => {document.body.replaceChildren(); vi.clearAllMocks(); vi.useRealTimers();});
const ticket = {url: '/api/photos/downloads/ticket', status_url: '/photos/downloads/ticket/status'};

it('starts a native transfer and reports queued, streaming and finished states without fetching bytes', async () => {
  vi.useFakeTimers();
  vi.mocked(api).mockResolvedValueOnce(ticket).mockResolvedValueOnce({state: 'queued'})
    .mockResolvedValueOnce({state: 'streaming'}).mockResolvedValueOnce({state: 'finished'});
  const selection = {filters: {chat_id: '123', snapshot_id: 900000}, excluded_ids: [2]};
  const onState = vi.fn();
  await downloadPhotos(selection, vi.fn(), onState);
  expect(api).toHaveBeenCalledWith('/photos/downloads', 'POST', selection);
  const frame = document.querySelector('iframe')!;
  expect(frame.getAttribute('src')).toBe(ticket.url);
  expect(frame.hidden).toBe(true);
  await vi.advanceTimersByTimeAsync(9000);
  expect(onState.mock.calls.map(([state]) => state)).toEqual(['queued', 'streaming', 'finished']);
  expect(document.querySelector('iframe')).toBeNull();
  expect(vi.mocked(api).mock.calls.every(([path]) => ['/photos/downloads', ticket.status_url].includes(path))).toBe(true);
});

it('propagates request failures before starting a download', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('Выбрано больше 50 фотографий'));
  await expect(downloadPhotos({ids: [1, 2]})).rejects.toThrow('50');
  expect(document.querySelector('iframe')).toBeNull();
});

it('reports native download errors from the same-origin response', async () => {
  vi.useFakeTimers();
  vi.mocked(api).mockResolvedValue(ticket);
  const onError = vi.fn();
  await downloadPhotos({ids: [1]}, onError);
  const frame = document.querySelector('iframe')!;
  Object.defineProperty(frame, 'contentDocument', {value: {querySelector: () => null, body: {textContent: JSON.stringify({detail: 'Ссылка истекла'})}}});
  frame.dispatchEvent(new Event('load'));
  expect(onError).toHaveBeenCalledWith('Ссылка истекла');
  expect(document.querySelector('iframe')).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});

it('starting another download does not cancel the first', async () => {
  vi.useFakeTimers();
  vi.mocked(api).mockResolvedValue(ticket);
  await downloadPhotos({ids: [1]});
  const first = document.querySelector('iframe');
  await downloadPhotos({ids: [2]});
  expect(document.querySelectorAll('iframe')).toHaveLength(2);
  expect(first?.isConnected).toBe(true);
});

it('a transient status failure does not interrupt the download or require another click', async () => {
  vi.useFakeTimers();
  vi.mocked(api).mockResolvedValueOnce(ticket).mockRejectedValueOnce(new ApiError(503, 'Занято'))
    .mockResolvedValueOnce({state: 'finished'});
  const onError = vi.fn();
  await downloadPhotos({ids: [1]}, onError);
  await vi.advanceTimersByTimeAsync(3000);
  expect(document.querySelector('iframe')).not.toBeNull();
  await vi.advanceTimersByTimeAsync(3000);
  expect(document.querySelector('iframe')).toBeNull();
  expect(onError).not.toHaveBeenCalled();
});
