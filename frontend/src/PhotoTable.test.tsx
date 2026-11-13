import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import PhotoTable from './PhotoTable';
import type { Photo } from './types';

vi.mock('./App', () => ({
  useApp: () => ({meta: {work_types: []}, user: {role: 'OPERATOR', permissions: []}}),
  StatusBadge: () => null,
}));
vi.mock('./DefectCheckbox', () => ({default: () => null}));

const photo = {id: 11, preview_url: '/11', received_at: '2026-11-13T00:00:00Z', ai_confidence: null} as Photo;

function checkbox(limit?: number) {
  const html = renderToStaticMarkup(<PhotoTable photos={[photo]} openPhoto={() => {}} onDefect={async () => {}}
    selection={{ids: new Set(Array.from({length: 10}, (_, index) => index + 1)), toggle: () => {}, limit}}/>);
  return html.match(/<input[^>]+>/)![0];
}

it('allows selecting an eleventh photo without an explicit limit', () => {
  expect(checkbox()).not.toContain('disabled');
});

it('preserves the explicit limit when attaching photos to a task', () => {
  expect(checkbox(10)).toContain('disabled');
});
