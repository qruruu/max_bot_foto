// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AppealPhotos from './AppealPhotos';
import { api } from '../api';

vi.mock('../api', () => ({api: vi.fn()}));
let root: Root, element: HTMLDivElement;
const photos = [{id: 'one', url: '/photo', preview_url: '/preview', original_url: '/original'}];
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
beforeEach(() => {
  vi.clearAllMocks(); vi.mocked(api).mockResolvedValue({photos});
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
});
afterEach(async () => {await act(async () => root.unmount()); element.remove();});

it('loads private card photos only after expanding, shows previews, and links to the full image', async () => {
  await act(async () => root.render(<AppealPhotos endpoint="/appeals/42" count={1}/>));
  expect(api).not.toHaveBeenCalled(); expect(element.querySelector('img')).toBeNull();
  const toggle = element.querySelector('button')!;
  await act(async () => {toggle.click(); await tick();});
  expect(api).toHaveBeenCalledWith('/appeals/42', 'GET', undefined, expect.any(AbortSignal));
  expect(element.querySelector('img')?.getAttribute('src')).toBe('/preview');
  expect(element.querySelector('a')?.getAttribute('href')).toBe('/original');
  expect(element.querySelector('a')?.getAttribute('target')).toBe('_blank');
  await act(async () => toggle.click()); expect(element.querySelector('img')).toBeNull();
  await act(async () => toggle.click()); expect(api).toHaveBeenCalledTimes(1);
});

it('keeps public photos collapsed and reflects a refreshed response without making private requests', async () => {
  await act(async () => root.render(<AppealPhotos photos={photos}/>));
  expect(element.querySelector('img')).toBeNull();
  await act(async () => element.querySelector('button')!.click());
  await act(async () => root.render(<AppealPhotos photos={[{id: 'two', url: '/new', preview_url: '/new-preview'}]}/>));
  expect(element.querySelector('img')?.getAttribute('src')).toBe('/new-preview'); expect(api).not.toHaveBeenCalled();
});
