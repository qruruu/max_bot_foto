import { expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { OperatorDayTable } from './OperatorDayStatus';
import WorkDistrictMatrix from './WorkDistrictMatrix';
import type { Report } from './types';

it('distinguishes personal closure, another person closure and missing closure', () => {
  const common = {chats:[{id:1, name:'Бригада 1'}], total:12, confirmed:12, pending:0};
  const markup = renderToStaticMarkup(<OperatorDayTable timezone="Asia/Yekaterinburg" items={[
    {...common, id:1, name:'Анна', status:'CLOSED', last_closed_at:'2026-10-16T10:00:00Z', confirmed_by:['Анна']},
    {...common, id:2, name:'Иван', status:'CLOSED_BY_OTHER', last_closed_at:null, confirmed_by:['Анна']},
    {...common, id:3, name:'Мария', status:'NOT_CLOSED', confirmed:4, pending:8, last_closed_at:null, confirmed_by:[]},
  ]}/>);
  expect(markup).toContain('Закрыл день');
  expect(markup).toContain('Закрыт другим оператором');
  expect(markup).toContain('Сам не закрывал');
  expect(markup).toContain('15:00:00');
  expect(markup).toContain('Осталось проверить: 8');
});

const report = {work_types:[{id:'BINS', name:'Урны', count:3}], districts:[{id:1,name:'1 мкр',count:3}],
  work_district_matrix:[{work_type:'BINS',district_id:1,count:3}]} as Report;
const meta = {work_types:[{code:'BINS',name:'Урны'},{code:'LAWN',name:'Газоны'}],
  districts:[{id:1,name:'1 мкр',active:true},{id:2,name:'2 мкр',active:true}]};

it('includes empty districts and work types with zero counts so missing coverage is visible', () => {
  const markup = renderToStaticMarkup(<WorkDistrictMatrix report={report} meta={meta} filters={{}} canBrowse open={() => {}}/>);
  expect(markup).toContain('2 мкр'); expect(markup).toContain('Газоны');
  expect(markup).toContain('>3</button>'); expect(markup).toContain('>0</span>');
  expect(markup).toContain('Вид работы × микрорайон');
});

it('limits matrix axes to selected filters and disables browsing without photo access', () => {
  const markup = renderToStaticMarkup(<WorkDistrictMatrix report={report} meta={meta}
    filters={{work_type:'BINS',district_id:'1'}} canBrowse={false} open={() => {}}/>);
  expect(markup).not.toContain('2 мкр'); expect(markup).not.toContain('Газоны');
  expect(markup).toContain('disabled=""');
});
