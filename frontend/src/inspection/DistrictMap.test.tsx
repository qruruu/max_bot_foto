// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import DistrictMap from '../DistrictMap';
import { ThemeProvider } from '../theme';
import { api } from '../api';

const mocks=vi.hoisted(()=>({startEditing:vi.fn(),startDrawing:vi.fn()}));
vi.mock('../App',()=>({ErrorBox:({error}:{error:string})=>error?<p>{error}</p>:null,useApp:()=>({
  user:{role:'ADMIN_OPERATOR'},meta:{yandex_maps_api_key:'test-map-key'},refresh:vi.fn(),notify:vi.fn(),
})}));
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{}}));
vi.mock('../yandexMaps',async importOriginal=>({...await importOriginal<typeof import('../yandexMaps')>(),loadYandexMaps:async()=>({
  Map:class {geoObjects={add:vi.fn(),remove:vi.fn(),getBounds:()=>[[72,61],[73,62]]};setBounds=vi.fn();destroy=vi.fn();},
  Polygon:class {events={add:vi.fn()};geometry={getBounds:()=>[[72,61],[73,62]],getCoordinates:()=>[]};editor={startEditing:mocks.startEditing,startDrawing:mocks.startDrawing,stopEditing:vi.fn(),stopDrawing:vi.fn()};},
})}));
afterEach(()=>{vi.clearAllMocks();});

it('shows territory boundaries without enabling any editing even if its surrounding context has an administrator role',async()=>{
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  vi.mocked(api).mockResolvedValue({type:'FeatureCollection',features:[{type:'Feature',id:1,properties:{id:1,name:'Центральный',active:true},geometry:{type:'Polygon',coordinates:[[[72,61],[73,61],[73,62],[72,61]]]}}]});
  const element=document.createElement('div');document.body.append(element);const root=createRoot(element);
  try{
    await act(async()=>{root.render(<ThemeProvider><DistrictMap readOnly endpoint="/inspection/organizations/org/districts"/></ThemeProvider>);await new Promise(resolve=>setTimeout(resolve,0));});
    const territory=[...element.querySelectorAll('button')].find(b=>b.textContent?.includes('Центральный'))!;
    expect(territory).toBeTruthy();await act(async()=>territory.click());
    expect(element.textContent).not.toContain('Сохранить границы');
    expect(element.textContent).not.toContain('Нарисовать часть');
    expect(mocks.startEditing).not.toHaveBeenCalled();expect(mocks.startDrawing).not.toHaveBeenCalled();
    expect(vi.mocked(api).mock.calls.every(([path,method])=>path==='/inspection/organizations/org/districts'&&(!method||method==='GET'))).toBe(true);
  }finally{await act(async()=>root.unmount());element.remove();}
});
