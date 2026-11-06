// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ChatMessageMenu from './ChatMessageMenu';

const reply = vi.fn(), forward = vi.fn();
const menu = () => document.querySelector('[role="menu"]');
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<ChatMessageMenu as="article" id={1} className="" reply={reply} forward={forward}>
    <a href="#attachment">Скриншот</a>
  </ChatMessageMenu>));
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

function key(element: EventTarget, name: string, shiftKey = false) {
  element.dispatchEvent(new KeyboardEvent('keydown', {key: name, shiftKey, bubbles: true, cancelable: true}));
}

it('opens by right-click on the attachment and forwards from the menu', async () => {
  expect(host.querySelector('button')).toBeNull();
  const event = new MouseEvent('contextmenu', {bubbles: true, cancelable: true, clientX: 20, clientY: 20});
  await act(async () => {host.querySelector('a')!.dispatchEvent(event);});
  expect(event.defaultPrevented).toBe(true);
  expect(document.activeElement?.textContent).toBe('Ответить');
  await act(async () => menu()!.querySelectorAll('button')[1].click());
  expect(forward).toHaveBeenCalledOnce();
  expect(reply).not.toHaveBeenCalled();
  expect(menu()).toBeNull();
});

it('supports the context menu keyboard shortcut, navigation and Escape', async () => {
  const message = host.querySelector('article')!;
  message.focus();
  await act(async () => key(message, 'F10', true));
  expect(document.activeElement?.textContent).toBe('Ответить');
  await act(async () => key(document.activeElement!, 'ArrowDown'));
  expect(document.activeElement?.textContent).toBe('Переслать');
  await act(async () => key(document.activeElement!, 'Escape'));
  expect(menu()).toBeNull();
  expect(document.activeElement).toBe(message);
});

it('opens by long touch but ignores a swipe and the tap after a long touch', async () => {
  vi.useFakeTimers();
  const link = host.querySelector('a')!;
  function pointer(type: string, x: number) {
    const event = new MouseEvent(type, {clientX: x, clientY: 20, bubbles: true});
    Object.defineProperty(event, 'pointerType', {value: 'touch'});
    link.dispatchEvent(event);
  }
  await act(async () => {pointer('pointerdown', 20); pointer('pointermove', 40); vi.advanceTimersByTime(550);});
  expect(menu()).toBeNull();
  await act(async () => {pointer('pointerdown', 20); vi.advanceTimersByTime(550); pointer('pointerup', 20);});
  expect(menu()).not.toBeNull();
  const tap = new MouseEvent('click', {bubbles: true, cancelable: true});
  await act(async () => {link.dispatchEvent(tap);});
  expect(tap.defaultPrevented).toBe(true);
  await act(async () => menu()!.querySelector('button')!.click());
  expect(reply).toHaveBeenCalledOnce();
});
