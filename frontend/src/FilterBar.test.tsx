import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import FilterBar from './FilterBar';

const context = vi.hoisted(() => ({
  user: {role:'OPERATOR',permissions:['photos_view'],allowed_chat_ids:null},
  meta: {today:'2026-10-19',work_types:[],districts:[],chats:[],statuses:[],operators:[]},
}));
vi.mock('./App', () => ({useApp: () => context}));
afterEach(() => {context.user.role='OPERATOR'; context.user.permissions=['photos_view'];});

describe('sorting control visibility', () => {
  const render = () => renderToStaticMarkup(<FilterBar filters={{date_basis:'received',sort_order:'asc'}} change={() => {}}/>);

  it('hides the control when permission is absent', () => {
    const html = render();
    expect(html).not.toContain('aria-label="Сортировка"');
    expect(html).not.toContain('Сначала ранние поступления');
  });

  it('shows capture and receipt ordering choices when the administrator enables the permission', () => {
    context.user.permissions=['photos_view','photos_sort'];
    const html = render();
    expect(html).toContain('aria-label="Сортировка"');
    for (const text of ['Сначала ранние фотографии','Сначала поздние фотографии','Сначала ранние поступления','Сначала поздние поступления']) {
      expect(html).toContain(text);
    }
    expect(html).toContain('value="photo_asc" selected=""');
  });

  it('always keeps the sorting control available to the administrator', () => {
    context.user.role='ADMIN_OPERATOR'; context.user.permissions=[];
    expect(render()).toContain('aria-label="Сортировка"');
  });
});

it('shows the selected period and keeps active filters reachable open by default', () => {
  const html = renderToStaticMarkup(<FilterBar filters={{date_from:'2026-10-13',date_to:'2026-10-19',district_id:'3'}} change={() => {}}/>);
  expect(html).toContain('13.10.2026 – 19.10.2026');
  expect(html).toContain('aria-pressed="true">7 дней');
  expect(html).not.toContain('<summary');
  expect(html).not.toContain('Фильтры');
  expect(html).toContain('aria-label="Микрорайон"');
});

it('only shows the combined status when the user opens that selection from a report', () => {
  const normal = renderToStaticMarkup(<FilterBar filters={{work_only:'true'}} change={() => {}}/>);
  expect(normal).toContain('Основная лента');
  expect(normal).not.toContain('ACCEPTED_ALL');
  const fromReport = renderToStaticMarkup(<FilterBar filters={{work_only:'true',accepted_only:'true'}} change={() => {}}/>);
  expect(fromReport).toContain('value="ACCEPTED_ALL" selected="">Принято и требует проверки');
});

it('keeps map filters visible without a separate disclosure row', () => {
  const html = renderToStaticMarkup(<FilterBar filters={{}} change={() => {}}/>);
  expect(html).not.toContain('<summary');
  expect(html).toContain('aria-label="Микрорайон"');
  expect(html).toContain('aria-label="Чат"');
});
