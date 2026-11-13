// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import PhotoContextMenu from './PhotoContextMenu';
import type { Photo } from './types';

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const download = vi.fn(), forward = vi.fn();

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  host = document.createElement('div'); document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove(); vi.clearAllMocks(); vi.unstubAllGlobals();
});

async function render(count: number, canSendToTask = true) {
  await act(async () => root.render(<PhotoContextMenu
    target={{photo: {id: 99, preview_url: null} as Photo, row: document.createElement('tr'), x: 0, y: 0}}
    count={count} canSelect selecting canSendToTask={canSendToTask} downloading={false} download={download}
    close={() => {}} select={() => {}} cancel={() => {}} forward={forward}/>));
}

it('hides both forwarding actions above ten and restores them when selection returns to ten', async () => {
  await render(10);
  expect(document.body.textContent).toContain('Переслать в чат');
  expect(document.body.textContent).toContain('Переслать в задачу');
  await render(11);
  expect(document.body.textContent).not.toContain('Переслать');
  await render(10);
  expect(document.body.textContent).toContain('Переслать в чат');
  expect(document.body.textContent).toContain('Переслать в задачу');
});

it('allows downloading the selection even when the context-menu photo is unavailable', async () => {
  await render(12);
  const button = [...document.querySelectorAll('button')].find(button => button.textContent?.includes('Скачать'))!;
  expect(button.disabled).toBe(false);
  await act(async () => button.click());
  expect(download).toHaveBeenCalledOnce();
  expect(forward).not.toHaveBeenCalled();
});

it('respects task forwarding permissions within the forwarding limit', async () => {
  await render(2, false);
  expect(document.body.textContent).toContain('Переслать в чат');
  expect(document.body.textContent).not.toContain('Переслать в задачу');
});

it.each([50, 51])('enforces the same 50-photo download limit in the context menu (%s)', async count => {
  await render(count);
  const button = [...document.querySelectorAll('button')].find(button => button.textContent?.includes('Скачать'))!;
  expect(button.disabled).toBe(count > 50);
});
