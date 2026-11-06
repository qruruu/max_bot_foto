// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import useSidebar from './useSidebar';

afterEach(() => vi.unstubAllGlobals());

function Workspace() {
  const menu = useSidebar();
  return <>
    <button ref={menu.menuButton} aria-expanded={!menu.collapsed} onClick={menu.toggle}>Меню</button>
    {!menu.collapsed && <aside ref={menu.sidebar}>
      <a href="#photos" onClick={menu.closeMenu}>Фотографии</a>
      <button className="sidebar-toggle" aria-expanded="true" onClick={menu.toggle}>Закрыть меню</button>
    </aside>}
  </>;
}

it('opens the mobile drawer temporarily and restores focus on Escape or navigation', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn()})));
  const storage = {getItem: vi.fn(() => 'false'), setItem: vi.fn()};
  vi.stubGlobal('localStorage', storage);
  const node = document.createElement('div');
  document.body.append(node);
  const root = createRoot(node);
  const drawer = () => node.querySelector('aside');
  try {
    await act(async () => root.render(<Workspace/>));
    const trigger = node.querySelector('button')!;
    expect(drawer()).toBeNull();

    await act(async () => trigger.click());
    expect(document.activeElement).toBe(drawer()?.querySelector('button'));
    expect(document.body.style.overflow).toBe('hidden');

    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab', bubbles: true, cancelable: true}));
    expect(document.activeElement).toBe(drawer()?.querySelector('a'));

    await act(async () => {document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));});
    expect(drawer()).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(document.body.style.overflow).toBe('');

    await act(async () => trigger.click());
    await act(async () => drawer()?.querySelector('a')?.click());
    expect(drawer()).toBeNull();
    expect(storage.setItem).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
    node.remove();
  }
});
