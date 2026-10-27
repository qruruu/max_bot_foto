// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { expect,it,vi } from 'vitest';
import { api } from '../api';
import InspectionOwner from './Owner';

vi.mock('../api',async importOriginal=>({...await importOriginal<typeof import('../api')>(),api:vi.fn()}));
it('lets the owner read and reply in a separate inspector conversation',async()=>{
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  const element=document.createElement('div');document.body.append(element);const root=createRoot(element);
  vi.mocked(api).mockImplementation(async(path,method)=>{
    if(path==='/platform/inspection/agencies')return [];
    if(path.endsWith('/chat/unread'))return {unread:1};
    if(path.endsWith('/chat/contacts'))return [{key:'i:2',name:'Проверяющий',kind:'Проверяющий',organization_name:'Группа',unread:1,last_message:null}];
    if(path.includes('/chat/messages/read?'))return {ok:true};
    if(path.includes('/chat/messages?')){const item={id:1,body:method==='POST'?'Ответ владельца':'Вопрос',created_at:'2026-10-26T10:00:00Z',outgoing:method==='POST',read_at:null};return method==='POST'?item:{items:[item],next_before_id:null,has_newer:false,peer_read_through_id:0};}
    throw new Error(path);
  });
  try{
    await act(async()=>root.render(<MemoryRouter initialEntries={['/?section=inspectors&inspection_tab=messages&with=i%3A2']}><InspectionOwner organizations={[]}/></MemoryRouter>));
    expect(element.querySelector('.operator-message-list')?.textContent).toContain('Вопрос');
    const field=element.querySelector('textarea')!;
    await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,'Ответ владельца');field.dispatchEvent(new Event('input',{bubbles:true}));});
    await act(async()=>field.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true})));
    expect(api).toHaveBeenCalledWith('/platform/inspection/chat/messages?peer=i%3A2','POST',{body:'Ответ владельца',client_id:expect.any(String)});
    expect(element.querySelector('button[aria-label="Переслать сообщение №1"]')).not.toBeNull();
  }finally{await act(async()=>root.unmount());element.remove();vi.mocked(api).mockReset();}
});
