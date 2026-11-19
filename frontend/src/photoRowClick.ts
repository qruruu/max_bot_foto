import type { MouseEvent } from 'react';

export function isPhotoRowClick(event: MouseEvent<HTMLElement>) {
  return !(event.target instanceof Element && event.target.closest('button, a, input, label, select, textarea'));
}
