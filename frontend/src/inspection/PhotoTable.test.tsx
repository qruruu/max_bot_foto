import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import InspectionPhotoTable from './PhotoTable';
import type { InspectionPhoto } from './types';

it('renders the operator table structure with only inspector-visible fields and read-only defects', () => {
  const photo = {id:4669,photo_date:'2026-10-25',photo_time:'14:44:00',received_at:'2026-10-25T13:45:17Z',
    latitude:61.0876,longitude:72.6129,district_name:'2 мкр',work_type_name:'Газон',is_defect:true,
    preview_url:'/safe-preview',chat_name:'hidden-chat',operator_name:'hidden-operator',sender_id:'hidden-sender',
    ai_confidence:0.74,work_type_source:'AI'} as unknown as InspectionPhoto;
  const html = renderToStaticMarkup(<InspectionPhotoTable photos={[photo]} openPhoto={() => {}}/>);
  expect(html).toContain('photos-table inspection-photo-table');
  expect(html).toContain('photo-thumb');
  for (const value of ['#4669','14:44:00','Получено','2 мкр','61.08760','72.61290','Газон','Принято','Открыть']) expect(html).toContain(value);
  expect(html).toMatch(/type="checkbox"[^>]*disabled=""/);
  for (const value of ['hidden-chat','hidden-operator','hidden-sender','74%','Нейросеть','Источник классификации']) expect(html).not.toContain(value);
});
