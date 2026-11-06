// @vitest-environment jsdom
import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect, it, vi} from 'vitest';
import IntegrationKeys from './IntegrationKeys';
import {api} from './api';

vi.mock('./api',()=>({api:vi.fn()}));
vi.mock('./App',()=>({ErrorBox:()=>null,useApp:()=>({meta:{organization:{name:'Компания'},intake_cohort:'production'}})}));

it('shows a newly issued key once, avoids browser storage and permits revocation', async()=>{
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  const issued={id:'public-id',name:'Отчёты',scopes:['photos:read','geozones:read','changes:read'],cohort:'production',
    expires_at:'2027-01-01T00:00:00Z',revoked_at:null,last_used_at:null};
  let created=false;
  vi.mocked(api).mockImplementation(async(_path,method)=>{
    if(method==='POST'){created=true;return {...issued,key:'PRIVATE_API_KEY'};}
    if(method==='DELETE')return {ok:true};
    return {items:created?[issued]:[]};
  });
  const local=vi.spyOn(Storage.prototype,'setItem');
  const element=document.createElement('div');document.body.append(element);const root=createRoot(element);
  const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
  const button=(text:string)=>[...element.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent?.includes(text))!;
  try {
    await act(async()=>{root.render(<IntegrationKeys/>);await tick();});
    await act(async()=>{element.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await tick();});
    expect(api).toHaveBeenCalledWith('/integration-keys','POST',expect.objectContaining({scopes:issued.scopes}));
    expect(element.querySelector('textarea')?.value).toBe('PRIVATE_API_KEY');
    expect(button('Создать ключ').disabled).toBe(true);
    expect(local).not.toHaveBeenCalled();
    await act(async()=>{button('Ключ сохранён').click();});
    expect(element.querySelector('textarea')).toBeNull();
    await act(async()=>{button('Отозвать').click();await tick();});
    expect(api).toHaveBeenCalledWith('/integration-keys/public-id','DELETE');
  } finally {await act(async()=>root.unmount());element.remove();local.mockRestore();}
});
