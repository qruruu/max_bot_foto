// @vitest-environment jsdom
import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, api } from '../api';
import InspectionChats from './Chats';
import type { Contact, Message } from './types';

vi.mock('../api', async importOriginal => ({...await importOriginal<typeof import('../api')>(), api: vi.fn()}));
const contacts: Contact[] = [
  {key:'i:2',name:'Анна',kind:'Проверяющий',organization_name:null,avatar_url:'/safe-avatar',unread:2,last_message:'Здравствуйте',last_message_at:'2026-10-25T10:00:00Z',last_message_outgoing:false},
  {key:'a:org:3',name:'Иван',kind:'Администратор организации',organization_name:'Городская уборка',avatar_url:null,unread:1,last_message:null,last_message_at:null,last_message_outgoing:false},
];
const message = (id:number, body='Сообщение '+id):Message => ({id,body,outgoing:id%2===0,created_at:'2026-10-25T10:00:00Z',read_at:null});
const page = (items:Message[], before:number|null=null, read=0) => ({items,next_before_id:before,has_newer:false,peer_read_through_id:read});
let element:HTMLDivElement, root:Root;
function Location() {return <output id="location">{useLocation().search}</output>;}
async function mount(url='/inspection?org=org&tab=messages',base='/inspection', revision=0) {
  await act(async()=>root.render(<StrictMode><MemoryRouter initialEntries={[url]}><InspectionChats base={base} revision={revision}/><Location/></MemoryRouter></StrictMode>));
}
const click = async (selector:string) => {await act(async()=>element.querySelector<HTMLButtonElement>(selector)!.click());};
async function input(selector:string,value:string) {
  const field=element.querySelector<HTMLInputElement|HTMLTextAreaElement>(selector)!;
  await act(async()=>{Object.getOwnPropertyDescriptor(field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});
}
async function enter(shiftKey=false) {await act(async()=>element.querySelector('textarea')!.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',shiftKey,bubbles:true})));}
beforeEach(()=>{
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  vi.useFakeTimers();
  element=document.createElement('div');document.body.append(element);root=createRoot(element);
  vi.spyOn(document,'hidden','get').mockReturnValue(false);
  vi.mocked(api).mockReset().mockImplementation(async(path,method)=>{
    if(path.endsWith('/contacts'))return contacts;
    if(path.includes('/messages/read?'))return {ok:true};
    if(path.includes('/messages?')&&(!method||method==='GET'))return page([message(1),message(2)]);
    throw new Error('Unexpected '+path);
  });
});
afterEach(async()=>{await act(async()=>root.unmount());element.remove();vi.restoreAllMocks();vi.useRealTimers();});

it('uses the operator conversation layout, searches organizations and preserves the inspector URL',async()=>{
  await mount();
  expect(element.querySelector('.panel.operator-chats')).not.toBeNull();
  expect(element.querySelector('.operator-chat-contact img')?.getAttribute('src')).toBe('/safe-avatar');
  await input('input','уборка');
  expect(element.querySelectorAll('.operator-chat-contact')).toHaveLength(1);
  await click('.operator-chat-contact');
  expect(element.querySelector('#location')?.textContent).toBe('?org=org&tab=messages&with=a%3Aorg%3A3');
  expect(element.querySelector('.operator-conversation-header')?.textContent).toContain('Администратор организации · Городская уборка');
  expect(element.querySelector('.operator-message-day')?.textContent).toBe('25 октября 2026 г.');
  expect(element.querySelector('.operator-message.own [aria-label="Отправлено"]')).not.toBeNull();
  expect(element.querySelector('textarea')?.maxLength).toBe(4000);
  await click('.operator-chat-back');
  expect(element.querySelector('#location')?.textContent).toBe('?org=org&tab=messages');
});

it('keeps drafts per recipient and retries uncertain sends with the same client id',async()=>{
  const fallback=vi.mocked(api).getMockImplementation()!, attempts:unknown[]=[];
  vi.mocked(api).mockImplementation(async(path,method,body,signal)=>{
    if(path.includes('/messages?')&&method==='POST') {attempts.push(body);if(attempts.length===1)throw new Error('offline');return message(3,'Текст Анне');}
    return fallback(path,method,body,signal);
  });
  await mount();await click('.operator-chat-contact');await input('textarea','Текст Анне');
  await click('.operator-chat-contact:nth-child(2)');expect(element.querySelector('textarea')?.value).toBe('');
  await input('textarea','Текст Ивану');await click('.operator-chat-contact');
  expect(element.querySelector('textarea')?.value).toBe('Текст Анне');
  await enter(true);expect(attempts).toHaveLength(0);
  await enter();expect(attempts).toHaveLength(1);
  expect(element.querySelector('textarea')?.value).toBe('Текст Анне');
  expect(element.textContent).toContain('Повторите попытку');
  await enter();expect(attempts).toHaveLength(2);expect(attempts[0]).toEqual(attempts[1]);
  expect(element.querySelector('textarea')?.value).toBe('');
  await click('.operator-chat-contact:nth-child(2)');expect(element.querySelector('textarea')?.value).toBe('Текст Ивану');
});

it('anchors older history and incoming polls without jumping, and updates read receipts',async()=>{
  const fallback=vi.mocked(api).getMockImplementation()!;
  let newer=false;
  vi.mocked(api).mockImplementation(async(path,method,body,signal)=>{
    if(path.includes('/messages?')&&method==='GET') {
      if(path.includes('before_id='))return page([message(1),message(2)]);
      if(path.includes('after_id='))return page(newer?[message(5)]:[],null,4);
      return page([message(3),message(4)],3);
    }
    return fallback(path,method,body,signal);
  });
  await mount('/inspection?org=org&tab=messages&with=i%3A2');
  const list=element.querySelector<HTMLDivElement>('.operator-message-list')!;
  Object.defineProperty(list,'clientHeight',{get:()=>200});
  Object.defineProperty(list,'scrollHeight',{get:()=>400+element.querySelectorAll('.operator-message').length*100});
  list.scrollTop=80;
  await click('.operator-chat-older');
  expect(list.scrollTop).toBe(280);
  expect(element.querySelectorAll('.operator-message')).toHaveLength(4);
  newer=true;list.scrollTop=100;
  await act(async()=>{await vi.advanceTimersByTimeAsync(3000);});
  expect(list.scrollTop).toBe(100);
  expect(element.querySelectorAll('.operator-message')).toHaveLength(5);
  expect(element.querySelector('.operator-message.own [aria-label="Прочитано"]')).not.toBeNull();
  expect(vi.mocked(api).mock.calls.some(([path])=>path.includes('after_id=4'))).toBe(true);
});

it('discards delayed history after a switch and closes conversations removed from contacts',async()=>{
  const fallback=vi.mocked(api).getMockImplementation()!;
  let resolve!: (result:unknown)=>void, revoked=false;
  vi.mocked(api).mockImplementation(async(path,method,body,signal)=>{
    if(path.endsWith('/contacts'))return revoked?[contacts[1]]:contacts;
    if(path.includes('/messages?peer=i%3A2'))return new Promise(done=>{resolve=done;});
    return fallback(path,method,body,signal);
  });
  await mount();await click('.operator-chat-contact');await click('.operator-chat-contact:nth-child(2)');
  await act(async()=>resolve(page([message(50,'Чужая история')])));
  expect(element.textContent).not.toContain('Чужая история');
  await click('.operator-chat-contact');revoked=true;
  await act(async()=>{await vi.advanceTimersByTimeAsync(5000);});
  expect(element.querySelector('#location')?.textContent).toBe('?org=org&tab=messages');
  expect(element.querySelector('textarea')).toBeNull();
});

it('uses the organization administrator endpoints with the same view and handles denied access',async()=>{
  const fallback=vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async(path,method,body,signal)=>{
    if(path.includes('/inspection-admin/messages?'))throw new ApiError(404,'Собеседник недоступен');
    return fallback(path,method,body,signal);
  });
  await mount('/org/company/inspectors?with=i%3A2','/inspection-admin');
  expect(element.querySelector('.panel.operator-chats')).not.toBeNull();
  expect(element.querySelector('button[aria-label="Обновить чаты"]')).not.toBeNull();
  expect(element.querySelector('textarea')).toBeNull();
  expect(vi.mocked(api).mock.calls.some(([path])=>path.startsWith('/inspection/messages'))).toBe(false);
});
