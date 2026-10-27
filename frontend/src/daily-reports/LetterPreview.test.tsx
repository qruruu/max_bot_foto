import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import LetterPreview from './LetterPreview';
import type { Report } from './types';

function example(cohort:'test'|'production'='production'):Report {
  return {id:1,version:2,approved:true,changed:false,approved_at:null,issues:[],new_photos:0,changed_photos:0,evidence:{total:0,confirmed:0,unconfirmed:0,unmatched:0,rows:{}},cohort,day:'2026-10-27',fact_day:'2026-10-26',letter_numbers:{'58':'МК-58-001'},
    config:{profile:{company_name:'Организация',short_name:'ИП Шашко',city:'',address:'',inn:'',ogrn:'',phone:'',email:'',recipient:['Адресат'],subject:'Содержание территорий',photo_url:'',letterhead_image:'data:image/png;base64,HEADER',signature_image:'data:image/png;base64,SIGNATURE'},contracts:[{id:'58',number:'58',prefix:'МК-58-',next_number:2}],works:[{id:'bins',name:'Очистка урн',unit:'шт.',season:'all',recurrence:'daily',schedule_note:'',windows:[],dates:[],interval_days:5,requires_event:false,photo_codes:[],assignments:[]}],areas:[{id:'a',contract_id:'58',name:'1, 2 микрорайоны',district_ids:[]}],summer_start:'',summer_end:'',source_notes:''},
    document:{fact:[{work_id:'bins',area_id:'a',decision:'info',quantity:null,resources:'3 человека',note:'Примечание',cycle_complete:false}],plan:[{work_id:'bins',area_id:'a',decision:'include',quantity:120,resources:'3 человека',note:'',cycle_complete:false}],fact_season:'',plan_season:'',fact_events:[],plan_events:[],note:''}};
}

it.each([[true,'production',false],[false,'production',true],[true,'test',false],[false,'test',false]] as const)(
  'shows the real signature only on final production letters (draft=%s, cohort=%s)',(draft,cohort,signed)=>{
    const html=renderToStaticMarkup(<LetterPreview report={example(cohort)} draft={draft}/>);
    expect(html.includes('base64,SIGNATURE')).toBe(signed);
    expect(html).toContain('base64,HEADER');
    expect(html.includes('ЧЕРНОВИК')).toBe(draft);
    expect(html).not.toContain('Без объёма');
    expect(html).toContain('120 шт.');
    expect(html).toContain('Примечание');
    expect(html).toContain('1, 2 микрорайоны');
  }
);
