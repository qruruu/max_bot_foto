import { describe, expect, it } from 'vitest';
import { changePermission, hasPermission } from './permissions';
import type { PermissionDefinition, User } from './types';

const catalog: PermissionDefinition[] = [
  { code:'photos_view', name:'Фото', group:'Фото', requires:[], default_operator:true },
  { code:'photos_edit', name:'Изменение', group:'Фото', requires:['photos_view'], default_operator:true },
  { code:'originals_view', name:'Оригиналы', group:'Фото', requires:['photos_view'], default_operator:true },
  { code:'reports_view', name:'Отчёты', group:'Фото', requires:[], default_operator:true },
  { code:'reports_export', name:'Excel', group:'Фото', requires:['photos_view','reports_view'], default_operator:true },
  { code:'chats_manage', name:'Чаты', group:'Настройка', requires:[], default_operator:false },
];

describe('operator permissions', () => {
  it('enables every prerequisite when Excel export is selected', () => {
    expect(changePermission(['chats_manage'], 'reports_export', true, catalog))
      .toEqual(['photos_view','reports_view','reports_export','chats_manage']);
  });
  it('removes dependent functions without removing unrelated access', () => {
    const selected = catalog.map(item => item.code);
    expect(changePermission(selected, 'photos_view', false, catalog))
      .toEqual(['reports_view','chats_manage']);
  });
  it('grants only the stored operator functions while administrators retain all functions', () => {
    const operator: User = {id:1,login:'operator',name:'Test',active:true,role:'OPERATOR',permissions:['photos_view'],allowed_chat_ids:null,avatar_url:null};
    expect(hasPermission(operator,'photos_view')).toBe(true);
    expect(hasPermission(operator,'photos_edit')).toBe(false);
    expect(hasPermission({...operator,role:'ADMIN_OPERATOR',permissions:[]},'photos_edit')).toBe(true);
    expect(hasPermission({...operator,permissions:[]},'photos_view')).toBe(false);
  });
  it('keeps global exchange and training unavailable with a limited chat selection', () => {
    const operator = {role:'OPERATOR',allowed_chat_ids:[1],permissions:['photos_view','exchange_manage','learning_manage']} as User;
    expect(hasPermission(operator,'photos_view')).toBe(true);
    expect(hasPermission(operator,'exchange_manage')).toBe(false);
    expect(hasPermission(operator,'learning_manage')).toBe(false);
    expect(hasPermission({...operator,allowed_chat_ids:null},'exchange_manage')).toBe(true);
    expect(hasPermission({...operator,role:'ADMIN_OPERATOR'},'learning_manage')).toBe(true);
  });
});
