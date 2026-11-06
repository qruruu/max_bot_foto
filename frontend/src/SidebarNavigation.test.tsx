// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { Camera, Users } from 'lucide-react';
import { expect, it, vi } from 'vitest';
import SidebarNavigation from './SidebarNavigation';

it('keeps daily links visible and expands management for an active destination', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<MemoryRouter initialEntries={['/photos']}>
      <SidebarNavigation links={[{to: '/photos', label: 'Фотографии', Icon: Camera},
        {to: '/users', label: 'Сотрудники', Icon: Users, group: 'management'}]}
        order={['/users', '/photos']} collapsed={false} toggle={() => {}} onSaved={() => {}}/>
    </MemoryRouter>));
    const photos = host.querySelector('[aria-label="Фотографии"]');
    const employees = host.querySelector('[aria-label="Сотрудники"]') as HTMLAnchorElement;
    const management = host.querySelector('[aria-label="Управление"]') as HTMLButtonElement;
    expect(photos?.closest('[hidden]')).toBeNull();
    expect(employees.closest('[hidden]')).not.toBeNull();
    await act(async () => management.click());
    expect(employees.closest('[hidden]')).toBeNull();
    await act(async () => employees.click());
    expect(employees.getAttribute('aria-current')).toBe('page');
    expect(management.getAttribute('aria-expanded')).toBe('true');
  } finally {
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
  }
});
