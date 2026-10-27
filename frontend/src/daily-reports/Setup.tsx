import { Plus, Trash2 } from 'lucide-react';
import type { Meta } from '../types';
import { assignment, frequencies, newWork } from './types';
import type { Config, Work, Profile } from './types';

type Props={config:Config;meta:Meta;disabled:boolean;change:(config:Config)=>void};
export default function ReportingSetup({config,meta,disabled,change}:Props) {
  const [workCode,setWorkCode]=useState('');
  const districts=meta.districts.filter(d=>d.active||config.areas.some(a=>a.district_ids.includes(d.id)));
  function districtSelection(areaId:string,ids:number[]) {
    const name=ids.map(id=>meta.districts.find(d=>d.id===id)?.name).filter(Boolean).join(', ')||'Микрорайоны не выбраны';
    change({...config,areas:config.areas.map(a=>a.id===areaId?{...a,district_ids:ids,name}:a)});
  }
  function addWork() {
    const type=meta.work_types.find(t=>t.code===workCode);
    if(type)change({...config,works:[...config.works,{...newWork(),name:type.name,photo_codes:[type.code],assignments:config.areas.map(a=>assignment(a.id))}]});
    setWorkCode('');
  }
  function profile<K extends keyof Profile>(key:K,value:Profile[K]) {change({...config,profile:{...config.profile,[key]:value}});}
  function work(index:number, update:Partial<Work>) {change({...config,works:config.works.map((w,i)=>i===index?{...w,...update}:w)});}
  const profileFields:[keyof Omit<Profile,'recipient'>,string][]=[['company_name','Полное название организации'],['short_name','Короткое название для письма'],['city','Город'],['address','Адрес'],['inn','ИНН'],['ogrn','ОГРНИП / ОГРН'],['phone','Телефон'],['email','Электронная почта'],['photo_url','Ссылка на фотоотчёт'],['subject','Предмет отчёта']];
  const removeArea=(id:string)=>change({...config,areas:config.areas.filter(a=>a.id!==id),works:config.works.map(w=>({...w,assignments:w.assignments.filter(a=>a.area_id!==id)}))});
  return <fieldset className="daily-setup" disabled={disabled}>
    <section className="panel"><div className="section-title"><h2>1. Реквизиты и письмо</h2><span>Заполняются один раз</span></div>
      <div className="daily-form-grid">{profileFields.map(([key,label])=><label key={key}>{label}<input value={config.profile[key]} onChange={e=>profile(key,e.target.value)}/></label>)}
        <label className="daily-full-width">Адресат — по одной строке<input aria-label="Адресат, строка 1" value={config.profile.recipient[0]||''} onChange={e=>profile('recipient',[e.target.value,...config.profile.recipient.slice(1)])}/>
          <input aria-label="Адресат, строка 2" value={config.profile.recipient[1]||''} onChange={e=>profile('recipient',[config.profile.recipient[0]||'',e.target.value,...config.profile.recipient.slice(2)])}/>
          <input aria-label="Адресат, строка 3" value={config.profile.recipient[2]||''} onChange={e=>profile('recipient',[config.profile.recipient[0]||'',config.profile.recipient[1]||'',e.target.value])}/></label>
      </div><p className="hint">Подпись и печать в файлы автоматически не проставляются.</p></section>
    <section className="panel"><div className="section-title"><h2>2. Контракты и микрорайоны</h2><button type="button" onClick={()=>change({...config,contracts:[...config.contracts,{id:crypto.randomUUID(),number:'Новый контракт',prefix:'',next_number:1}]})}><Plus size={16}/>Добавить контракт</button></div>
      {config.contracts.map(contract=><div className="daily-contract-setup" key={contract.id}>
        <div className="daily-form-grid"><label>Номер контракта<input value={contract.number} onChange={e=>change({...config,contracts:config.contracts.map(c=>c.id===contract.id?{...c,number:e.target.value}:c)})}/></label>
          <label>Начало номера письма<input value={contract.prefix} placeholder="МК-58-" onChange={e=>change({...config,contracts:config.contracts.map(c=>c.id===contract.id?{...c,prefix:e.target.value}:c)})}/></label>
          <label>Следующий порядковый номер<input type="number" min="1" value={contract.next_number} onChange={e=>change({...config,contracts:config.contracts.map(c=>c.id===contract.id?{...c,next_number:Number(e.target.value)}:c)})}/></label>
        </div>
        {config.areas.filter(a=>a.contract_id===contract.id).map(area=><div className="daily-area" key={area.id}><strong>Микрорайоны контракта · выбрано {area.district_ids.length}</strong><p className="hint">Из раздела «Микрорайоны» этой организации. Этот выбор используется в письме и для подбора фотографий.</p>
          <div className="daily-checkbox-grid">{districts.map(d=><label className="checkbox" key={d.id}><input aria-label={contract.number+': '+d.name} type="checkbox" checked={area.district_ids.includes(d.id)} onChange={e=>districtSelection(area.id,e.target.checked?[...area.district_ids,d.id]:area.district_ids.filter(id=>id!==d.id))}/>{d.name}{!d.active?' (неактивен)':''}</label>)}</div>
          {!districts.length&&<p className="daily-warning">В организации пока нет микрорайонов. Добавьте их в разделе «Микрорайоны».</p>}
          <p className="hint">В письме: {area.district_ids.length?area.name:'выберите микрорайоны выше'}</p>
          <button className="text-button" type="button" onClick={()=>removeArea(area.id)}><Trash2 size={14}/>Удалить группу микрорайонов</button></div>)}
        <div className="daily-inline"><button type="button" onClick={()=>change({...config,areas:[...config.areas,{id:crypto.randomUUID(),contract_id:contract.id,name:'Микрорайоны не выбраны',district_ids:[]}]})}><Plus size={14}/>Выбрать микрорайоны</button>
          <button className="text-button" type="button" onClick={()=>{if(config.areas.some(a=>a.contract_id===contract.id)){window.alert('Сначала удалите группы микрорайонов этого контракта.');return;}change({...config,contracts:config.contracts.filter(c=>c.id!==contract.id)});}}><Trash2 size={14}/>Удалить контракт</button></div>
      </div>)}<p className="hint">Несколько микрорайонов можно объединить одной строкой отчёта или разделить на группы с собственными объёмами. Названия берутся из справочника. Письма нумеруются при утверждении.</p></section>
    <section className="panel"><div className="section-title"><h2>3. Работы и календарь</h2><div className="daily-inline"><select aria-label="Вид работы из справочника" value={workCode} onChange={e=>setWorkCode(e.target.value)}><option value="">Выберите вид работы</option>{meta.work_types.map(t=><option key={t.code} value={t.code}>{t.name}</option>)}</select><button disabled={!workCode} type="button" onClick={addWork}><Plus size={16}/>Добавить работу</button></div></div>
      <p className="hint">Виды работ уже есть в сервисе. Здесь для них задаются только условия контракта и формулировка в письме.</p>
      <div className="daily-form-grid"><label>Летний сезон: начало, ежегодно<input type="date" value={config.summer_start?meta.today.slice(0,4)+'-'+config.summer_start:''} onChange={e=>change({...config,summer_start:e.target.value.slice(5)})}/></label>
        <label>Летний сезон: окончание, ежегодно<input type="date" value={config.summer_end?meta.today.slice(0,4)+'-'+config.summer_end:''} onChange={e=>change({...config,summer_end:e.target.value.slice(5)})}/></label></div>
      <p className="hint">Остальные даты относятся к зиме. Если границы пока неизвестны, сезон выбирается при подготовке каждого отчёта.</p>
      {config.works.map((w,index)=><details className="daily-work-setup" key={w.id} open={config.works.length===1}><summary><strong>{w.name}</strong><span>{frequencies[w.recurrence]} · {w.unit}</span></summary>
        <div className="daily-form-grid"><label className="daily-full-width">Наименование в отчёте<input value={w.name} onChange={e=>work(index,{name:e.target.value})}/></label>
          <label>Единица измерения<input value={w.unit} placeholder="шт., м², м³" onChange={e=>work(index,{unit:e.target.value})}/></label>
          <label>Сезон<select value={w.season} onChange={e=>work(index,{season:e.target.value as Work['season']})}><option value="all">Круглый год</option><option value="summer">Лето</option><option value="winter">Зима</option></select></label>
          <label>Периодичность<select value={w.recurrence} onChange={e=>work(index,{recurrence:e.target.value as Work['recurrence']})}>{Object.entries(frequencies).map(([key,value])=><option value={key} key={key}>{value}</option>)}</select></label>
          {['deadlines','dates'].includes(w.recurrence)&&<label>Даты, день.месяц, через запятую<input key={w.recurrence} defaultValue={w.dates.map(d=>d.split('-').reverse().join('.')).join(', ')} placeholder="12.06, 31.07, 30.08" onBlur={e=>work(index,{dates:e.target.value.split(',').filter(v=>v.trim()).map(v=>v.trim().split('.').reverse().map(p=>p.padStart(2,'0')).join('-'))})}/></label>}
          {w.recurrence==='windows'&&<label>Окна, день.месяц — день.месяц<input defaultValue={w.windows.map(v=>v.start.split('-').reverse().join('.')+' — '+v.end.split('-').reverse().join('.')).join(', ')} placeholder="01.06 — 15.06, 01.08 — 15.08" onBlur={e=>work(index,{windows:e.target.value.split(',').filter(v=>v.trim()).map(v=>{const [a='',b='']=v.trim().split(/\s*[—–/]\s*/);return {start:a.split('.').reverse().map(p=>p.padStart(2,'0')).join('-'),end:b.split('.').reverse().map(p=>p.padStart(2,'0')).join('-')};})})}/></label>}
          {w.recurrence==='interval'&&<label>Интервал, дней<input type="number" min="1" max="366" value={w.interval_days} onChange={e=>work(index,{interval_days:Number(e.target.value)})}/></label>}
          <label className="daily-full-width">Условия контракта<textarea rows={2} value={w.schedule_note} onChange={e=>work(index,{schedule_note:e.target.value})}/></label></div>
        <label className="checkbox"><input type="checkbox" checked={w.requires_event} onChange={e=>work(index,{requires_event:e.target.checked})}/>Включать только после отметки события, заявки или активного снежного периода</label>
        <details><summary>Какие фотографии относятся к работе: {w.photo_codes.length}</summary><div className="daily-checkbox-grid">{meta.work_types.map(t=><label className="checkbox" key={t.code}><input type="checkbox" checked={w.photo_codes.includes(t.code)} onChange={e=>work(index,{photo_codes:e.target.checked?[...w.photo_codes,t.code]:w.photo_codes.filter(code=>code!==t.code)})}/>{t.name}</label>)}</div><p className="hint">Один вид фото может подтверждать разные договорные работы. Количество фото не переводится в объём.</p></details>
        <div className="table-scroll"><table><thead><tr><th>Применять</th><th>Микрорайоны</th><th>Норма на цикл, {w.unit}</th><th>Персонал / техника по умолчанию</th><th>Лимит за год, {w.unit}</th></tr></thead><tbody>{config.areas.map(area=>{
          const a=w.assignments.find(a=>a.area_id===area.id);const update=(data:Partial<NonNullable<typeof a>>)=>work(index,{assignments:w.assignments.map(item=>item.area_id===area.id?{...item,...data}:item)});
          return <tr key={area.id}><td><input aria-label={'Применять: '+area.name} type="checkbox" checked={!!a} onChange={e=>work(index,{assignments:e.target.checked?[...w.assignments,assignment(area.id)]:w.assignments.filter(item=>item.area_id!==area.id)})}/></td><td>{config.contracts.find(c=>c.id===area.contract_id)?.number}<small>{area.name}</small></td>
            <td><input aria-label={'Норма: '+area.name} type="number" min="0" step="any" disabled={!a} value={a?.quantity??''} placeholder="Не задана" onChange={e=>update({quantity:e.target.value===''?null:Number(e.target.value)})}/></td>
            <td><input aria-label={'Ресурсы: '+area.name} disabled={!a} value={a?.resources||''} placeholder="Не заданы" onChange={e=>update({resources:e.target.value})}/></td>
            <td><input aria-label={'Годовой лимит: '+area.name} type="number" min="0" step="any" disabled={!a} value={a?.annual_limit??''} placeholder="Не задан" onChange={e=>update({annual_limit:e.target.value===''?null:Number(e.target.value)})}/></td></tr>;
        })}</tbody></table></div>
        <p className="hint">Норма используется только для предложения плана. Факт подтверждает оператор. Пустое значение означает «неизвестно». Годовой лимит учитывает утверждённый факт; тестовый режим и рабочий считаются отдельно.</p>
        <button className="text-button" type="button" onClick={()=>change({...config,works:config.works.filter(item=>item.id!==w.id)})}><Trash2 size={14}/>Удалить работу</button>
      </details>)}
    </section>
    <section className="panel"><h2>Основания и недостающие данные</h2><textarea rows={6} value={config.source_notes} onChange={e=>change({...config,source_notes:e.target.value})}/></section>
  </fieldset>;
}
import { useState } from 'react';
