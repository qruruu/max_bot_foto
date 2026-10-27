// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import InspectionForward from './Forward';
import type { Message } from './types';

vi.mock('../api',async importOriginal=>({...await importOriginal<typeof import('../api')>(),api:vi.fn()}));
const owner={key:'o:1',name:'Владелец',kind:'Владелец сервиса',organization_name:null};
let element:HTMLDivElement,root:Root;
async function input(selector:string,value:string){const field=element.querySelector<HTMLSelectElement|HTMLTextAreaElement>(selector)!;await act(async()=>{Object.getOwnPropertyDescriptor(field instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event(field instanceof HTMLSelectElement?'change':'input',{bubbles:true}));});}
async function send(){await act(async()=>element.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));}
beforeEach(()=>{(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;element=document.createElement('div');document.body.append(element);root=createRoot(element);vi.mocked(api).mockReset();});
afterEach(async()=>{await act(async()=>root.unmount());element.remove();});

it('offers the permitted recipients and retries photo forwarding with the same organization, comment and client id',async()=>{
  const attempts:unknown[]=[],onSent=vi.fn();
  vi.mocked(api).mockImplementation(async(path,method,body)=>{
    if(path.startsWith('/inspection/contacts?'))return [owner];
    attempts.push(body);if(attempts.length===1)throw new Error('offline');return {id:1};
  });
  await act(async()=>root.render(<InspectionForward photo={{id:85,organization_id:'company',preview_url:'/safe-photo'}} onClose={()=>{}} onSent={onSent}/>));
  expect(vi.mocked(api).mock.calls[0][0]).toBe('/inspection/contacts?photo_organization_id=company&photo_id=85');
  expect(element.querySelector('option[value="o:1"]')?.textContent).toContain('Владелец сервиса');
  await input('select','o:1');await input('textarea','Проверьте работу');await send();
  expect(element.querySelector('textarea')?.value).toBe('Проверьте работу');expect(onSent).not.toHaveBeenCalled();
  await send();expect(attempts[0]).toEqual(attempts[1]);
  expect(attempts[1]).toMatchObject({photo_id:85,photo_organization_id:'company',body:'Проверьте работу',client_id:expect.any(String)});
  expect(onSent).toHaveBeenCalledWith(owner);
});

it('forwards the source message by id without accepting changed text or author metadata',async()=>{
  vi.mocked(api).mockImplementation(async(path)=>path.includes('/contacts?')?[{...owner,key:'i:2'}]:{id:2});
  const source={id:10,body:'Исходное сообщение',outgoing:false,created_at:'2026-10-26T10:00:00Z',read_at:null} as Message;
  await act(async()=>root.render(<InspectionForward base="/platform/inspection/chat" message={source} onClose={()=>{}} onSent={()=>{}}/>));
  expect(element.querySelector('textarea')).toBeNull();
  expect(element.textContent).toContain(source.body);
  await input('select','i:2');await send();
  expect(api).toHaveBeenCalledWith('/platform/inspection/chat/messages?peer=i%3A2','POST',{client_id:expect.any(String),forward_message_id:10});
});
