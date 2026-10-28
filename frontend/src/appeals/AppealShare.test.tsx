// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AppealShare, { appealShareLinks } from './AppealShare';

let root: Root, element: HTMLDivElement;
beforeEach(() => {
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  Object.defineProperty(navigator, 'clipboard', {configurable: true, get: () => undefined});
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
});
afterEach(async () => {await act(async () => root.unmount()); element.remove(); vi.restoreAllMocks();});

it('opens each platform with only the public appeal link and no message', () => {
  const url = 'https://signal.example/a/12';
  const links = appealShareLinks(url).map(item => new URL(item.href));
  expect(links.map(link => link.hostname)).toEqual(['max.ru', 't.me', 'vk.com']);
  expect([...links[0].searchParams.entries()]).toEqual([['text', url]]);
  expect([...links[1].searchParams.entries()]).toEqual([['url', url]]);
  expect([...links[2].searchParams.entries()]).toEqual([['url', url]]);
});

it('copies the short link without opening or sending any message', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.spyOn(navigator, 'clipboard', 'get').mockReturnValue({writeText} as unknown as Clipboard);
  await act(async () => root.render(<AppealShare id={12} url="https://signal.example/a/12"/>));
  expect(element.querySelectorAll('a[target="_blank"]')).toHaveLength(3);
  await act(async () => element.querySelector<HTMLButtonElement>('button')!.click());
  expect(writeText).toHaveBeenCalledWith('https://signal.example/a/12');
  expect(element.textContent).toContain('Ссылка скопирована');
});

it('shows a selectable link when the clipboard is unavailable', async () => {
  await act(async () => root.render(<AppealShare id={12} url="https://signal.example/a/12"/>));
  await act(async () => element.querySelector<HTMLButtonElement>('button')!.click());
  const input = element.querySelector<HTMLInputElement>('input')!;
  expect(input.value).toBe('https://signal.example/a/12'); expect(input.readOnly).toBe(true);
});
