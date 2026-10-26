// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';
import News from './News';
import { NewsNotificationsProvider, NewsUnreadBadge } from './NewsNotificationsProvider';
import { watchNewsUnread } from './newsNotifications';
import type { NewsPost } from './news/types';

vi.mock('./api', async () => ({...await vi.importActual('./api'), api: vi.fn()}));

let stop = () => {};
let root: Root | undefined, element: HTMLDivElement;
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  Object.defineProperty(document, 'hidden', {configurable: true, value: false});
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {configurable: true,
    value: function (this: HTMLDialogElement) {this.removeAttribute('open');}});
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {configurable: true,
    value: function (this: HTMLDialogElement) {this.setAttribute('open', '');}});
});
afterEach(async () => {
  stop(); stop = () => {};
  if (root) await act(async () => root!.unmount());
  root = undefined; element?.remove();
  vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

describe('unread news polling', () => {
  it('finds new publications, keeps the count offline, and stops when access is revoked', async () => {
    const load = vi.fn().mockResolvedValueOnce({unread: 1}).mockResolvedValueOnce({unread: 2})
      .mockRejectedValueOnce(new Error('offline')).mockRejectedValueOnce(new ApiError(403, 'Нет доступа'));
    const update = vi.fn();
    stop = watchNewsUnread(load, update).stop;
    await vi.advanceTimersByTimeAsync(0);
    expect(update).toHaveBeenLastCalledWith(1);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(update).toHaveBeenLastCalledWith(2);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(update).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(40_000);
    window.dispatchEvent(new Event('focus'));
    expect(load).toHaveBeenCalledTimes(4);
  });

  it('ignores old responses after refreshing or signing out and cancels the request', async () => {
    let finish!: (value: {unread: number}) => void;
    const load = vi.fn().mockImplementationOnce(() => new Promise(resolve => {finish = resolve;}))
      .mockResolvedValue({unread: 0});
    const update = vi.fn(), watcher = watchNewsUnread(load, update);
    stop = watcher.stop;
    await watcher.refresh();
    expect(load.mock.calls[0][0].aborted).toBe(true);
    finish({unread: 9});
    await vi.advanceTimersByTimeAsync(0);
    expect(update.mock.calls).toEqual([[0]]);
    stop(); window.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(30_000);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('pauses in a hidden tab and refreshes on return, while rejecting malformed counts', async () => {
    Object.defineProperty(document, 'hidden', {configurable: true, value: true});
    const load = vi.fn().mockResolvedValueOnce({unread: -1}).mockResolvedValueOnce({unread: 1.5})
      .mockResolvedValue({unread: 3});
    const update = vi.fn(); stop = watchNewsUnread(load, update).stop;
    await vi.advanceTimersByTimeAsync(30_000);
    expect(load).not.toHaveBeenCalled();
    Object.defineProperty(document, 'hidden', {configurable: true, value: false});
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0);
    window.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(0);
    expect(update).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(update).toHaveBeenLastCalledWith(3);
  });
});

describe('news notifications in the reader', () => {
  let posts: NewsPost[], read: Set<string>;
  const flush = () => act(async () => {await vi.advanceTimersByTimeAsync(0);});
  function article(slug: string): NewsPost {
    return {slug, title: 'Новость ' + slug, summary: 'Описание обновления', category: 'Обновление',
      publishedAt: '2026-10-26', cover_id: null, document: {type: 'doc', content: [{type: 'paragraph',
        content: [{type: 'text', text: 'Понятная инструкция.'}]}]}};
  }
  async function mount(path = '/news', enabled = true) {
    element = document.createElement('div'); document.body.append(element); root = createRoot(element);
    await act(async () => {root!.render(<MemoryRouter initialEntries={[path]}>
      <NewsNotificationsProvider enabled={enabled}><NewsUnreadBadge/>
        {enabled && <Routes><Route path="/news" element={<News/>}/><Route path="/news/:slug" element={<News/>}/></Routes>}
      </NewsNotificationsProvider></MemoryRouter>);});
    await flush();
  }
  beforeEach(() => {
    posts = [article('one'), article('two')]; read = new Set();
    vi.mocked(api).mockImplementation(async (path, method = 'GET') => {
      if (path === '/news/unread') return {unread: posts.filter(post => !read.has(post.slug)).length};
      if (path === '/news') return posts.map(post => ({...post, unread: !read.has(post.slug)}));
      const slug = path.split('/')[2];
      if (method === 'POST' && path.endsWith('/read')) {read.add(slug); return {ok: true};}
      return {...posts.find(post => post.slug === slug), unread: !read.has(slug)};
    });
  });

  it('keeps the badge while listing news and clears only the article actually opened', async () => {
    await mount();
    expect(element.querySelector('.news-unread-badge')?.textContent).toBe('2');
    expect(element.querySelectorAll('.news-unread-label')).toHaveLength(2);
    expect(vi.mocked(api).mock.calls.some(call => call[1] === 'POST')).toBe(false);
    await act(async () => element.querySelector<HTMLAnchorElement>('.news-card')!.click());
    await flush();
    expect(read).toEqual(new Set(['one']));
    expect(element.querySelector('.news-unread-badge')?.textContent).toBe('1');
    expect(element.textContent).toContain('Понятная инструкция.');
    await act(async () => window.dispatchEvent(new Event('focus')));
    await flush();
    expect(vi.mocked(api).mock.calls.filter(call => call[1] === 'POST')).toHaveLength(1);
  });

  it('shows a new publication without reloading the page and reloads read state from the account', async () => {
    read.add('one'); await mount();
    expect(element.querySelector('.news-unread-badge')?.textContent).toBe('1');
    const scrolls = vi.mocked(window.scrollTo).mock.calls.length;
    posts.push(article('three'));
    await act(async () => {await vi.advanceTimersByTimeAsync(10_000);});
    await flush();
    expect(element.querySelectorAll('.news-card')).toHaveLength(3);
    expect(element.querySelector('.news-unread-badge')?.textContent).toBe('2');
    expect(window.scrollTo).toHaveBeenCalledTimes(scrolls);
    await act(async () => root!.unmount()); element.remove();
    await mount();
    expect(element.querySelector('.news-unread-badge')?.textContent).toBe('2');
    expect(element.querySelectorAll('.news-unread-label')).toHaveLength(2);
  });

  it('does not request news or show notifications without permission', async () => {
    await mount('/news', false);
    await act(async () => {await vi.advanceTimersByTimeAsync(30_000);});
    expect(api).not.toHaveBeenCalled();
    expect(element.querySelector('.news-unread-badge')).toBeNull();
  });

  it('marks an already opened article only after the tab becomes visible', async () => {
    Object.defineProperty(document, 'hidden', {configurable: true, value: true});
    await mount('/news/one');
    expect(read.size).toBe(0);
    Object.defineProperty(document, 'hidden', {configurable: true, value: false});
    await act(async () => document.dispatchEvent(new Event('visibilitychange')));
    await flush();
    expect(read.has('one')).toBe(true);
    expect(element.querySelector('.news-unread-badge')?.textContent).toBe('1');
  });

  it('retries a failed read receipt when the network returns', async () => {
    const respond = vi.mocked(api).getMockImplementation()!;
    let offline = true;
    vi.mocked(api).mockImplementation(async (...args) => {
      if (args[1] === 'POST' && offline) throw new Error('offline');
      return respond(...args);
    });
    await mount('/news/one');
    expect(read.size).toBe(0);
    expect(element.querySelector('.news-unread-badge')?.textContent).toBe('2');
    offline = false;
    await act(async () => window.dispatchEvent(new Event('online')));
    await flush();
    expect(read.has('one')).toBe(true);
    expect(element.querySelector('.news-unread-badge')?.textContent).toBe('1');
  });

  it('caps the visual badge while retaining the full accessible count', async () => {
    vi.mocked(api).mockResolvedValue({unread: 120});
    await mount('/not-news');
    expect(element.querySelector('.news-unread-badge')?.textContent).toBe('99+');
    expect(element.querySelector('.news-unread-badge')?.getAttribute('aria-label')).toBe('Непрочитанных новостей: 120');
  });
});
