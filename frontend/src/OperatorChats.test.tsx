// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import OperatorChats from './OperatorChats';
import { api } from './api';

const {refreshUnread, session} = vi.hoisted(()=>({refreshUnread:vi.fn(async()=>{}), session:{role:'OPERATOR', assistant:false}}));
vi.mock('./OperatorChatsProvider',()=>({useOperatorChats:()=>({refreshUnread})}));
vi.mock('./App',()=>({useApp:()=>({user:{id:1, role:session.role},meta:{timezone:'Asia/Yekaterinburg', local_assistant_enabled:session.assistant}}),ErrorBox:({error}:{error:string})=>error?<p role="alert">{error}</p>:null}));
vi.mock('./api', async importOriginal=>({...await importOriginal<typeof import('./api')>(),api:vi.fn()}));
let unmount:()=>Promise<void> = async()=>{};
afterEach(async()=>{await unmount();vi.clearAllMocks();session.role='OPERATOR';session.assistant=false;});

it('preserves operator photo attachments, read acknowledgement and compose controls in the shared view',async()=>{
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  const element=document.createElement('div');document.body.append(element);const root=createRoot(element);
  unmount=async()=>{await act(async()=>root.unmount());element.remove();};
  vi.mocked(api).mockImplementation(async(path)=>{
    if(path==='/operator-chats')return {items:[{id:2,name:'Администратор',role:'ADMIN_OPERATOR',active:true,avatar_url:null,unread:1,last_message:null}],unread:1};
    if(path==='/operator-chats/2/messages')return {items:[{id:10,sender_id:2,recipient_id:1,body:'Посмотрите фото',created_at:'2026-10-25T10:00:00Z',read_at:null,photo:{id:48,available:true,preview_url:'/api/photos/48/preview'}}],has_older:false,peer_read_through_id:0};
    if(path==='/operator-chats/2/read')return {ok:true};
    throw new Error(path);
  });
  await act(async()=>root.render(<MemoryRouter initialEntries={['/messages?with=2']}><OperatorChats/></MemoryRouter>));
  expect(element.querySelector('.operator-message-photo')?.getAttribute('href')).toBe('/photos/48?operator_chat=2');
  expect(element.querySelector('.operator-message-photo img')?.getAttribute('src')).toBe('/api/photos/48/preview');
  expect(element.querySelector('textarea[aria-label="Сообщение оператору"]')).not.toBeNull();
  expect(element.querySelector('.operator-conversation-header')?.textContent).toContain('Администратор');
  expect(api).toHaveBeenCalledWith('/operator-chats/2/read','POST',{through_id:10},expect.any(AbortSignal));
  expect(refreshUnread).toHaveBeenCalled();
});

it('opens the admin assistant from the contact list and keeps replies when returning to the chat', async () => {
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  session.role = 'ADMIN_OPERATOR';
  session.assistant = true;
  const element = document.createElement('div');
  document.body.append(element);
  const root = createRoot(element);
  unmount = async () => { await act(async () => root.unmount()); element.remove(); };
  vi.mocked(api).mockImplementation(async path => {
    if (path === '/operator-chats') return {items: [], unread: 0};
    if (path === '/local-assistant/question') return {answer: 'Поступило фото: 7'};
    throw new Error(path);
  });

  await act(async () => root.render(<MemoryRouter initialEntries={['/messages']}><OperatorChats/></MemoryRouter>));
  const contact = element.querySelector<HTMLButtonElement>('.operator-chat-contact')!;
  expect(contact.textContent).toContain('Даня ИИ');
  expect(element.querySelector('.page-header')?.textContent).not.toContain('Даня ИИ');
  await act(async () => contact.click());
  expect(element.querySelector('.operator-conversation-header')?.textContent).toContain('Локальный помощник');

  const input = element.querySelector<HTMLTextAreaElement>('textarea')!;
  expect(input.maxLength).toBe(500);
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, 'Сколько фото сегодня?');
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})));
  expect(api).toHaveBeenCalledWith('/local-assistant/question', 'POST', {question: 'Сколько фото сегодня?'});
  expect(element.querySelector('[role="log"]')?.textContent).toContain('Поступило фото: 7');
  await act(async () => element.querySelector<HTMLButtonElement>('.operator-chat-back')!.click());
  await act(async () => contact.click());
  expect(element.querySelector('[role="log"]')?.textContent).toContain('Поступило фото: 7');
});
