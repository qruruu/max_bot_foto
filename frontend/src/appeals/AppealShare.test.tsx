// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AppealShare, { appealShareLinks, SignalShare } from './AppealShare';

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
  expect(element.querySelectorAll('a[target="_blank"]')).toHaveLength(0);
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

it('shares the Signal form from Metka and attributes only the link source', async () => {
  await act(async () => root.render(<SignalShare url="https://signal.example/"/>));
  const links = [...element.querySelectorAll<HTMLAnchorElement>('a[target="_blank"]')];
  expect(links).toHaveLength(3);
  for (const [i, source] of ['max','telegram','vk'].entries()) {
    const share = new URL(links[i].href);
    const value = share.searchParams.get(i === 0 ? 'text' : 'url')!;
    expect(value).toBe('https://signal.example/?from=' + source);
    expect([...share.searchParams.keys()]).toEqual([i === 0 ? 'text' : 'url']);
  }
});
