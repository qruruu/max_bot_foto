// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { api } from '../api';
import InviteInspector from './InviteInspector';

vi.mock('../api', () => ({api: vi.fn()}));
vi.mock('qrcode', () => ({default: {toDataURL: async () => 'data:image/png;base64,cXI='}}));

it('creates the QR only on request and keeps it available when reopening the invitation', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const showModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal');
  const close = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close');
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: {configurable: true, value(this: HTMLDialogElement) {this.open = true;}},
    close: {configurable: true, value(this: HTMLDialogElement) {this.open = false;}},
  });
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const onClose = vi.fn();
  vi.mocked(api).mockResolvedValue({url: 'https://metka.example/inspection#invite=demo', expires_at: '2026-11-06T08:00:00Z'});
  const render = async (open: boolean) => act(async () => root.render(<InviteInspector open={open} onClose={onClose}/>));
  try {
    await render(true);
    expect(host.querySelector('dialog')?.open).toBe(true);
    expect(api).not.toHaveBeenCalled();
    await act(async () => host.querySelectorAll('button')[1].click());
    expect(api).toHaveBeenCalledOnce();
    expect(api).toHaveBeenCalledWith('/inspection-admin/qr', 'POST');
    expect(host.querySelector('.inspection-qr-image')).not.toBeNull();
    await act(async () => host.querySelector('button')?.click());
    expect(onClose).toHaveBeenCalledOnce();
    await render(false);
    expect(host.querySelector('dialog')?.open).toBe(false);
    await render(true);
    expect(host.querySelector('.inspection-qr-image')).not.toBeNull();
    expect(api).toHaveBeenCalledOnce();
  } finally {
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
    for (const [name, descriptor] of Object.entries({showModal, close})) {
      if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
      else Reflect.deleteProperty(HTMLDialogElement.prototype, name);
    }
  }
});
