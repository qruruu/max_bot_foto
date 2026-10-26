import { describe, expect, it } from 'vitest';
import { defaultSidebarOrder, moveSidebarItem, normalizeSidebarOrder, sortSidebarLinks } from './sidebarOrder';

describe('personal sidebar order', () => {
  it('keeps the standard order for new accounts and unsupported stored values', () => {
    for (const value of [undefined, null, {}, 'broken', []]) expect(normalizeSidebarOrder(value)).toEqual(defaultSidebarOrder);
  });

  it('removes unknown and repeated entries and appends new sections once', () => {
    const order = normalizeSidebarOrder(['/review', '/photos', '/review', '/unknown', 5]);
    expect(order.slice(0, 2)).toEqual(['/review', '/photos']);
    expect(new Set(order)).toEqual(new Set(defaultSidebarOrder));
    expect(order).toHaveLength(defaultSidebarOrder.length);
    expect(order.at(-1)).toBe('/inspectors');
  });

  it('moves in both directions with stable identities without modifying the saved order', () => {
    const saved = ['/', '/photos', '/review'];
    const up = moveSidebarItem(saved, '/review', '/', 'before');
    expect(up.slice(0, 3)).toEqual(['/review', '/', '/photos']);
    expect(moveSidebarItem(up, '/review', '/photos', 'after').slice(0, 3)).toEqual(['/', '/photos', '/review']);
    expect(saved).toEqual(['/', '/photos', '/review']);
  });

  it('keeps unavailable sections in preferences without showing unauthorized links', () => {
    const saved = ['/users', '/review', '/photos', '/learning'];
    const allowed = [{to:'/photos',label:'Фото'}, {to:'/review',label:'Проверка'}];
    expect(sortSidebarLinks(allowed, saved).map(item=>item.to)).toEqual(['/review', '/photos']);
    const moved = moveSidebarItem(saved, '/photos', '/review', 'before');
    expect(sortSidebarLinks(allowed, moved).map(item=>item.to)).toEqual(['/photos', '/review']);
    expect(moved).toContain('/users');
    expect(moved).toContain('/learning');
    expect(allowed.map(item=>item.to)).toEqual(['/photos', '/review']);
  });

  it('ignores foreign and same-item drops and never drops another entry', () => {
    for (const [source,target] of [['/photos','/photos'],['/unknown','/photos'],['/photos','/unknown']]) {
      expect(moveSidebarItem(defaultSidebarOrder, source, target, 'before')).toEqual(defaultSidebarOrder);
    }
  });

  it('preserves every section across a sequence of moves and reset', () => {
    let order = normalizeSidebarOrder(['/learning']);
    for (const id of defaultSidebarOrder) order = moveSidebarItem(order, id, '/', 'before');
    expect(new Set(order)).toEqual(new Set(defaultSidebarOrder));
    expect(order).toHaveLength(defaultSidebarOrder.length);
    expect(sortSidebarLinks(defaultSidebarOrder.map(to=>({to})), [])).toEqual(defaultSidebarOrder.map(to=>({to})));
  });
});
