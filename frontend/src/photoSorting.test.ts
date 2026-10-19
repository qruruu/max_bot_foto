import { describe, expect, it } from 'vitest';
import { photoSortForUser } from './photoSorting';
import { changePermission } from './permissions';
import type { Filters, PermissionDefinition, User } from './types';

const operator = {role:'OPERATOR',permissions:['photos_view'],allowed_chat_ids:null} as User;

describe('administrator-controlled photo sorting', () => {
  it('overrides old links with photo time descending when permission is absent', () => {
    const links: Filters[] = [{}, {date_basis:'received',sort_order:'asc'}, {sort_order:'received_desc'}, {date_basis:'photo',sort_order:'asc'}];
    for (const filters of links) {
      expect(photoSortForUser(filters, operator)).toEqual({date_basis:'photo',sort_order:'desc'});
    }
  });

  it('preserves all four choices for enabled operators and administrators', () => {
    for (const user of [{...operator,permissions:['photos_view','photos_sort']}, {...operator,role:'ADMIN_OPERATOR',permissions:[]}]) {
      for (const date_basis of ['photo','received']) for (const sort_order of ['asc','desc']) {
        expect(photoSortForUser({date_basis,sort_order}, user)).toEqual({date_basis,sort_order});
      }
      expect(photoSortForUser({},user)).toEqual({date_basis:'received',sort_order:'desc'});
    }
  });

  it('restores the fixed order immediately after revocation without changing other filters', () => {
    const filters = {date_basis:'received',sort_order:'asc',sender_id:'455424204',chat_id:'-79357181921806'};
    expect({...filters,...photoSortForUser(filters,operator)}).toEqual({...filters,date_basis:'photo',sort_order:'desc'});
  });

  it('enables photo viewing together with sorting and removes sorting with viewing', () => {
    const catalog: PermissionDefinition[] = [
      {code:'photos_view',name:'Фото',group:'Фото',requires:[],default_operator:true},
      {code:'photos_sort',name:'Сортировка',group:'Фото',requires:['photos_view'],default_operator:false},
    ];
    expect(changePermission([],'photos_sort',true,catalog)).toEqual(['photos_view','photos_sort']);
    expect(changePermission(['photos_view','photos_sort'],'photos_view',false,catalog)).toEqual([]);
  });
});
