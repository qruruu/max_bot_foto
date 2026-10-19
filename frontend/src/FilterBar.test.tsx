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

  it('hides the control and explains the fixed photo order when permission is absent', () => {
    const html = render();
    expect(html).not.toContain('aria-label="Сортировка"');
    expect(html).toContain('Сначала поздние фотографии.');
    expect(html).not.toContain('Сначала ранние получения');
  });

  it('shows all four choices when the administrator enables the permission', () => {
    context.user.permissions=['photos_view','photos_sort'];
    const html = render();
    expect(html).toContain('aria-label="Сортировка"');
    for (const text of ['Сначала ранние фотографии','Сначала поздние фотографии','Сначала ранние получения','Сначала поздние получения']) {
      expect(html).toContain(text);
    }
    expect(html).toContain('value="received_asc" selected=""');
  });

  it('always keeps the sorting control available to the administrator', () => {
    context.user.role='ADMIN_OPERATOR'; context.user.permissions=[];
    expect(render()).toContain('aria-label="Сортировка"');
  });
});
