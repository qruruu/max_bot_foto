import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { CalendarDays, Camera, CheckCheck, Download, FileText, History, Plus, Printer, RefreshCw, Save, Settings2, X } from 'lucide-react';
import { api, dateLabel, query, shiftDate } from '../api';
import { ErrorBox, useApp } from '../App';
import { hasPermission } from '../permissions';
import { workspacePrefix } from '../workspace';
import ReportingSetup from './Setup';
import { newLine } from './types';
import type { Config, Document, Line, Report, ReportSummary, Setup } from './types';
import './daily-reports.css';

const base='/daily-reports';
type Tab='day'|'history'|'settings';
type PhotoPage={total:number;page:number;items:{id:number;status:string;preview_url:string|null}[]};
type PhotoSelection={work_id:string;area_id:string;page:number;title:string};
export default function DailyReports() {
  const {meta,user,notify}=useApp();
  const [params,setParams]=useSearchParams();
  const edit=hasPermission(user,'daily_reports_edit'), configure=hasPermission(user,'daily_reports_configure');
  const [tab,setTab]=useState<Tab>(params.get('tab')==='settings'?'settings':params.get('tab')==='history'?'history':'day'), [day,setDay]=useState(meta.today);
  const [setup,setSetup]=useState<Setup|null>(null),[archive,setArchive]=useState<ReportSummary[]>([]),[report,setReport]=useState<Report|null>(null);
  const [dirty,setDirty]=useState(false),[setupDirty,setSetupDirty]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [preview,setPreview]=useState(false),[photos,setPhotos]=useState<PhotoSelection|null>(null),[photoPage,setPhotoPage]=useState<PhotoPage|null>(null);
  const [history,setHistory]=useState<{version:number;action:string;at:string;author:string}[]|null>(null);
  const [add,setAdd]=useState<{kind:'fact'|'plan';work_id:string;area_id:string}>({kind:'fact',work_id:'',area_id:''});
  async function load() {
    const [s,a]=await Promise.all([api<Setup>(base+'/settings'),api<ReportSummary[]>(base)]);
    setSetup(s);setSetupDirty(false);setArchive(a);return s;
  }
  useEffect(()=>{let active=true;setBusy(true);setReport(null);setDirty(false);setSetupDirty(false);void Promise.all([api<Setup>(base+'/settings'),api<ReportSummary[]>(base)]).then(async([s,a])=>{if(active){setSetup(s);setArchive(a);if(!s.version&&configure)setTab('settings');const id=Number(params.get('report'));if(Number.isSafeInteger(id)&&id>0){const r=await api<Report>(base+'/'+id);if(active){setReport(r);setDay(r.day);}}}}).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setBusy(false);});return()=>{active=false;};},[meta.intake_cohort,configure]);
  useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{if(dirty||setupDirty)event.preventDefault();};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[dirty,setupDirty]);
  useEffect(()=>{if(!photos||!report)return;const c=new AbortController();setPhotoPage(null);void api<PhotoPage>(base+'/'+report.id+'/photos?'+query({work_id:photos.work_id,area_id:photos.area_id,page:String(photos.page)}),'GET',undefined,c.signal).then(setPhotoPage).catch(e=>{if(!c.signal.aborted)setError(e.message);});return()=>c.abort();},[photos,report?.id]);
  async function perform(action:()=>Promise<void>) {setBusy(true);setError('');try{await action();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  const leave=()=>!(dirty||setupDirty)||window.confirm('Есть несохранённые изменения. Перейти без сохранения?');
  function changeTab(next:Tab) {if(next!==tab&&leave()){setTab(next);setParams({tab:next,...(report?{report:String(report.id)}:{})});setPreview(false);}}
  function document(update:Partial<Document>) {if(report){setReport({...report,document:{...report.document,...update}});setDirty(true);}}
  async function save(current=report) {if(!current)throw new Error('Отчёт не открыт');const saved=await api<Report>(base+'/'+current.id,'PUT',{version:current.version,document:current.document});setReport(saved);setDirty(false);return saved;}
  async function open(id:number) {if(!leave())return;await perform(async()=>{const r=await api<Report>(base+'/'+id);setReport(r);setDirty(false);setDay(r.day);setTab('day');setParams({report:String(id)});setPreview(false);});}
  function create() {if(!leave())return;void perform(async()=>{const r=await api<Report>(base,'POST',{day});setReport(r);setDirty(false);setDay(r.day);setTab('day');setParams({report:String(r.id)});setPreview(false);await load();});}
  function changeConfig(config:Config) {if(setup){setSetup({...setup,config});setSetupDirty(true);}}
  const config=report?.config;
  const updateLine=(kind:'fact'|'plan', index:number, update:Partial<Line>)=>document({[kind]:report!.document[kind].map((row,i)=>i===index?{...row,...update}:row)});
  const bulk=(kind:'fact'|'plan')=>document({[kind]:report!.document[kind].map(row=>row.decision==='pending'&&row.quantity!==null&&row.quantity>0?{...row,decision:'include'}:row)});
  const url=(action:'xlsx'|'print',draft=false)=>workspacePrefix()+'/api'+base+'/'+report!.id+'/'+action+(draft?'?draft=true':'');
  const pending=report?(!dirty?report.issues.length:report.document.fact.concat(report.document.plan).filter(r=>r.decision==='pending').length):0;
  return <div className="daily-reports">
    <header className="page-header"><div><span className="eyebrow">КОНТРАКТЫ И ЕЖЕДНЕВНЫЕ ПИСЬМА</span><h1>Ежедневные отчёты</h1><p>Факт за прошедший день, план на следующий и отдельное письмо по каждому контракту.</p></div><FileText className="daily-header-icon" size={30}/></header>
    <div className="daily-tabs" role="tablist" aria-label="Отчётность">{([['day','Рабочий день',CalendarDays],['history','Архив отчётов',History],['settings','Настройка организации',Settings2]] as const).map(([key,label,Icon])=><button role="tab" aria-selected={tab===key} key={key} onClick={()=>changeTab(key)}><Icon size={17}/>{label}</button>)}</div>
    <ErrorBox error={error}/>
    {tab==='settings'&&setup&&<>
      <div className="daily-setup-intro panel"><div><h2>{setup.config.profile.short_name||'Настройка отчётности'}</h2><p>Микрорайоны и виды работ берутся из справочников этой организации. Здесь задаются реквизиты писем, контракты и правила отчётности.</p></div>
      </div>
      {setup.config.source_notes&&<details className="daily-source-note"><summary>Источники и данные, которые нужно уточнить</summary><p>{setup.config.source_notes}</p></details>}
      <ReportingSetup config={setup.config} meta={meta} disabled={!configure||busy} change={changeConfig}/>
      {configure&&(setupDirty||!setup.version)&&<div className="daily-bottom-bar"><span>{setupDirty?'Есть несохранённые изменения':'Настройка пока не сохранена'}<small>Уже созданные отчёты сохраняют свои реквизиты и правила.</small></span><button className="primary" disabled={busy||!setupDirty} onClick={()=>void perform(async()=>{setSetup(await api<Setup>(base+'/settings','PUT',setup));setSetupDirty(false);notify('Настройка отчётности сохранена');})}><Save size={17}/>Сохранить настройку</button></div>}
    </>}
    {tab==='history'&&<section className="panel"><div className="section-title"><h2>Сохранённые отчёты</h2><span>{meta.intake_cohort==='test'?'Тестовый режим':'Рабочий режим'}</span></div>
      {!archive.length?<p className="muted">Пока нет сохранённых отчётов.</p>:<div className="table-scroll"><table><thead><tr><th>Дата письма</th><th>Факт за</th><th>Состояние</th><th>Номера писем</th><th/></tr></thead><tbody>{archive.map(r=><tr key={r.id}><td>{dateLabel(r.day)}</td><td>{dateLabel(shiftDate(r.day,-1))}</td><td>{r.changed?'Исправление в черновике':r.approved?'Утверждён':'Черновик'}</td><td>{Object.values(r.letter_numbers).join(', ')||'Будут присвоены при утверждении'}</td><td><button disabled={busy} onClick={()=>void open(r.id)}>Открыть</button></td></tr>)}</tbody></table></div>}
    </section>}
    {tab==='day'&&<>
      <section className="panel daily-day-picker"><label>Дата письма<input type="date" value={day} onChange={e=>{if(leave()){setDay(e.target.value);setReport(null);setDirty(false);}}}/></label>
        <div><span>Факт: <strong>{dateLabel(day?shiftDate(day,-1):'')}</strong></span><span>План: <strong>{dateLabel(day)}</strong></span></div>
        <button className="primary" disabled={busy||!day||!setup?.version||(!edit&&!archive.some(r=>r.day===day))} onClick={()=>{const existing=archive.find(r=>r.day===day);if(existing)void open(existing.id);else if(edit)create();}}><CalendarDays size={17}/>{archive.some(r=>r.day===day)?'Открыть отчёт':'Собрать черновик'}</button>
      </section>
      {!setup?.version&&<div className="daily-empty panel"><Settings2 size={28}/><h2>Начните с настройки организации</h2><p>Добавьте контракт, выберите его микрорайоны и виды работ из справочников организации, укажите правила отчётности.</p><button onClick={()=>changeTab('settings')}>Открыть настройку</button></div>}
      {!report&&!!setup?.version&&<div className="daily-empty panel"><FileText size={32}/><h2>Выберите дату и соберите отчёт</h2><p>Система предложит работы по календарю, подставит заданные нормы и покажет фотографии. Факт остаётся на подтверждение.</p></div>}
      {report&&config&&<>
        <div className="daily-stats"><div><span>Факт за {dateLabel(report.fact_day)}</span><strong>{report.document.fact.length}</strong><small>строк работ</small></div><div><span>Нужно проверить</span><strong>{pending}</strong><small>факт и план</small></div><div><span>Фотографии за день</span><strong>{report.evidence.total}</strong><small>{report.evidence.unmatched?'Без сопоставления: '+report.evidence.unmatched:'Дубли и спам исключены'}</small></div><div><span>Состояние отчёта</span><strong className="daily-state">{dirty?'Не сохранён':report.changed?'Исправляется':report.approved?'Утверждён':'Черновик'}</strong><small>Версия {report.version}{report.cohort==='test'?' · Тестовый':''}</small></div></div>
        {(report.new_photos>0||report.changed_photos>0)&&<div className="daily-source-note"><strong>После утверждения изменились фотографии</strong><p>Новых: {report.new_photos}, изменённых или удалённых: {report.changed_photos}. Объёмы утверждённого письма сохраняются. При необходимости внесите исправление и утвердите его.</p></div>}
        <div className="daily-inline daily-document-toolbar"><button disabled={busy||!edit} onClick={()=>void perform(async()=>{const current=dirty?await save():report;setReport(await api<Report>(base+'/'+current.id+'/rebuild','POST',{version:current.version}));setDirty(false);notify('Настройки обновлены в черновике. Проверьте строки и обновите календарь.');})}><RefreshCw size={15}/>Взять актуальные настройки</button>
          <button disabled={busy} onClick={()=>void perform(async()=>setHistory(await api(base+'/'+report.id+'/history')))}><History size={15}/>История</button>
          <label className="daily-preview-switch"><input type="checkbox" checked={preview} onChange={e=>setPreview(e.target.checked)}/>Предпросмотр писем</label>
        </div>
        {preview?<LetterPreview report={report}/>:<>
          <div className="daily-note"><Camera size={18}/><span>Фото помогают проверить работу. Их количество не является объёмом в штуках или квадратных метрах. Незапланированную работу можно добавить вручную.</span></div>
          {(['fact','plan'] as const).map(kind=>{
            const date=kind==='fact'?report.fact_day:report.day;
            const seasonKey=`${kind}_season` as const, eventsKey=`${kind}_events` as const;
            return <section className="panel daily-fact-plan" key={kind}><div className="section-title"><div><span className="eyebrow">{kind==='fact'?'ПРОВЕРИТЬ ВЫПОЛНЕНИЕ':'ПОДГОТОВИТЬ СЛЕДУЮЩИЙ ДЕНЬ'}</span><h2>{kind==='fact'?'Факт за ':'План на '}{dateLabel(date)}</h2></div>{edit&&<button disabled={busy} onClick={()=>bulk(kind)}>Подтвердить строки с объёмом</button>}</div>
              <div className="daily-calendar-controls"><label>Сезон<select disabled={!edit||busy} value={report.document[seasonKey]} onChange={e=>document({[seasonKey]:e.target.value})}><option value="">Нужно уточнить</option><option value="summer">Лето</option><option value="winter">Зима</option></select></label>
                <details><summary>События и заявки</summary>{config.works.filter(w=>w.requires_event||w.recurrence==='event').map(w=><label className="checkbox" key={w.id}><input type="checkbox" disabled={!edit||busy} checked={report.document[eventsKey].includes(w.id)} onChange={e=>document({[eventsKey]:e.target.checked?[...report.document[eventsKey],w.id]:report.document[eventsKey].filter(id=>id!==w.id)})}/>{w.name}<small>{w.schedule_note}</small></label>)}</details>
                {edit&&<button disabled={busy} onClick={()=>void perform(async()=>{setReport(await api<Report>(base+'/'+report.id+'/calendar','POST',{version:report.version,document:report.document}));setDirty(false);})}><RefreshCw size={15}/>Добавить по календарю</button>}
              </div>
              {config.contracts.map(contract=>{
                const rows=report.document[kind].map((row,index)=>({row,index})).filter(({row})=>config.areas.find(a=>a.id===row.area_id)?.contract_id===contract.id);
                return <details className="daily-contract" key={contract.id} open><summary><span>{contract.number}</span><small>{rows.length} строк · {rows.filter(x=>x.row.decision==='pending').length} без решения</small></summary>
                  {!rows.length?<p className="muted">Нет работ по календарю. При необходимости добавьте строку ниже.</p>:<div className="table-scroll"><table><thead><tr><th>Вид работы и микрорайоны</th><th>Объём</th><th>Персонал / техника</th><th>{kind==='fact'?'Фото / завершение цикла':'Примечание'}</th><th>Решение</th></tr></thead><tbody>{rows.map(({row,index})=>{
                    const w=config.works.find(w=>w.id===row.work_id)!,area=config.areas.find(a=>a.id===row.area_id)!;
                    const evidence=report.evidence.rows[row.work_id+':'+row.area_id];
                    return <tr key={row.work_id+':'+row.area_id} className={'daily-row-'+row.decision}><td><strong>{w.name}</strong><small>{area.name}</small><details><summary>Условия и примечание</summary><p>{w.schedule_note}</p><textarea aria-label={'Примечание: '+w.name} disabled={!edit||busy} value={row.note} onChange={e=>updateLine(kind,index,{note:e.target.value})}/></details></td>
                      <td data-label="Объём"><div className="daily-quantity"><input aria-label={(kind==='fact'?'Факт: ':'План: ')+w.name+' — '+contract.number} type="number" min="0" step="any" disabled={!edit||busy||row.decision==='info'||row.decision==='skip'} value={row.quantity??''} placeholder="Указать" onChange={e=>updateLine(kind,index,{quantity:e.target.value===''?null:Number(e.target.value),decision:'pending'})}/><span>{w.unit}</span></div></td>
                      <td data-label="Персонал / техника"><input aria-label={'Персонал: '+w.name+' — '+contract.number} disabled={!edit||busy} value={row.resources} placeholder="Указать" onChange={e=>updateLine(kind,index,{resources:e.target.value})}/></td>
                      <td data-label="Подтверждение">{kind==='fact'?<><button disabled={!hasPermission(user,'photos_view')||!evidence?.total} className="text-button" onClick={()=>setPhotos({work_id:row.work_id,area_id:row.area_id,page:1,title:w.name+' · '+area.name})}><Camera size={15}/>{evidence?.total||0} фото</button>{!!evidence?.needs_review&&<small className="daily-warning">С вопросами: {evidence.needs_review}</small>}{!['daily','event','dates'].includes(w.recurrence)&&<label className="daily-cycle"><input type="checkbox" disabled={!edit||busy||row.decision!=='include'} checked={row.cycle_complete} onChange={e=>updateLine(kind,index,{cycle_complete:e.target.checked})}/>Цикл выполнен целиком</label>}</>:<span className="muted">{row.note||'—'}</span>}</td>
                      <td data-label="Решение"><select aria-label={'Решение: '+(kind==='fact'?'факт ':'план ')+w.name+' — '+contract.number} disabled={!edit||busy} value={row.decision} onChange={e=>updateLine(kind,index,{decision:e.target.value as Line['decision'],cycle_complete:false})}><option value="pending">Нужно подтвердить</option><option value="include">{kind==='fact'?'Выполнено':'Включить в план'}</option><option value="info">Указать без объёма</option><option value="skip">{kind==='fact'?'Не выполнялось':'Не планировать'}</option></select></td></tr>;
                  })}</tbody></table></div>}
                </details>;
              })}
            </section>;
          })}
          {edit&&<section className="panel"><div className="section-title"><h2>Добавить работу</h2><span>В том числе без фотографии</span></div><div className="daily-inline daily-add-line"><select aria-label="Добавить в" value={add.kind} onChange={e=>setAdd({...add,kind:e.target.value as 'fact'|'plan'})}><option value="fact">В факт</option><option value="plan">В план</option></select><select aria-label="Добавляемый вид работы" value={add.work_id} onChange={e=>setAdd({...add,work_id:e.target.value,area_id:''})}><option value="">Вид работы</option>{config.works.map(w=><option value={w.id} key={w.id}>{w.name}</option>)}</select><select aria-label="Добавляемые микрорайоны" value={add.area_id} onChange={e=>setAdd({...add,area_id:e.target.value})}><option value="">Микрорайоны</option>{config.works.find(w=>w.id===add.work_id)?.assignments.map(a=><option value={a.area_id} key={a.area_id}>{config.areas.find(x=>x.id===a.area_id)?.name}</option>)}</select><button disabled={busy||!add.work_id||!add.area_id} onClick={()=>{const w=config.works.find(w=>w.id===add.work_id)!;if(report.document[add.kind].some(r=>r.work_id===w.id&&r.area_id===add.area_id)){setError('Такая работа в этих микрорайонах уже есть в отчёте');return;}document({[add.kind]:[...report.document[add.kind],newLine(w,w.assignments.find(a=>a.area_id===add.area_id)!)]});}}><Plus size={16}/>Добавить</button></div></section>}
          <section className="panel"><label>Общее примечание к дню<textarea rows={2} disabled={!edit||busy} value={report.document.note} onChange={e=>document({note:e.target.value})}/></label></section>
        </>}
        {!dirty&&report.issues.length>0&&<details className="daily-validation"><summary>Перед утверждением нужно проверить: {report.issues.length}</summary><ul>{report.issues.map((item,i)=><li key={i}>{item}</li>)}</ul></details>}
        <div className="daily-bottom-bar"><span>{report.changed?'Прежние утверждённые письма сохраняются до нового утверждения':dirty?'Есть изменения в черновике':'Факт и план разнесены по контрактам'}<small>Скачивание не означает отправку заказчику.</small></span><div className="daily-inline">
          {edit&&<><button disabled={busy||!dirty} onClick={()=>void perform(async()=>{await save();notify('Черновик сохранён');})}><Save size={16}/>Сохранить</button><button className="primary" disabled={busy||(!dirty&&report.approved&&!report.changed)} onClick={()=>void perform(async()=>{const r=dirty?await save():report;setReport(await api<Report>(base+'/'+r.id+'/approve','POST',{version:r.version}));await load();notify('Отчёт утверждён. Можно скачать письма.');})}><CheckCheck size={17}/>Утвердить отчёт</button></>}
          <a className={'button'+(dirty&&!report.approved?' daily-disabled-link':'')} href={url('xlsx',!report.approved)} onClick={e=>{if(dirty&&!report.approved)e.preventDefault();}}><Download size={16}/>{report.approved?'Excel утверждённого':'Excel черновика'}</a>
          <a className={'button'+(dirty&&!report.approved?' daily-disabled-link':'')} target="_blank" rel="noreferrer" href={url('print',!report.approved)} onClick={e=>{if(dirty&&!report.approved)e.preventDefault();}}><Printer size={16}/>Печать / PDF</a>
        </div></div>
      </>}
    </>}
    {(photos||history)&&<div className="modal-backdrop" onClick={()=>{setPhotos(null);setHistory(null);}}><section className="modal daily-modal" role="dialog" aria-modal="true" aria-label={photos?'Фотографии работы':'История отчёта'} onClick={e=>e.stopPropagation()}><button className="modal-close" aria-label="Закрыть" onClick={()=>{setPhotos(null);setHistory(null);}}><X size={22}/></button>
      {photos&&<><h2>{photos.title}</h2>{photoPage?<><p className="muted">{photoPage.total} фото за {dateLabel(report!.fact_day)}. Отбор по виду работы, микрорайонам и текущему режиму.</p><div className="daily-photo-grid">{photoPage.items.map(p=><Link key={p.id} to={'/photos/'+p.id+'?'+query({date_from:report!.fact_day,date_to:report!.fact_day,date_basis:'photo',work_only:'true'})} target="_blank">{p.preview_url?<img src={p.preview_url} alt={'Фото №'+p.id}/>:<Camera size={30}/>}<strong>#{p.id}</strong><small>{p.status==='ACCEPTED'?'Принято':'Нужна проверка'}</small></Link>)}</div><div className="daily-inline"><button disabled={photos.page===1} onClick={()=>setPhotos({...photos,page:photos.page-1})}>Назад</button><span>Страница {photos.page}</span><button disabled={photos.page*60>=photoPage.total} onClick={()=>setPhotos({...photos,page:photos.page+1})}>Далее</button></div></>:<p>Загружаем фотографии…</p>}</>}
      {history&&<><h2>История отчёта</h2>{history.map((h,i)=><div className="daily-history-row" key={i}><strong>Версия {h.version} · {({CREATED:'Создан',SAVED:'Сохранён',APPROVED:'Утверждён',CALENDAR:'Обновлён календарь',REBUILT:'Взяты новые настройки'} as Record<string,string>)[h.action]||h.action}</strong><small>{h.author} · {new Date(h.at).toLocaleString('ru-RU')}</small></div>)}</>}
    </section></div>}
  </div>;
}

function LetterPreview({report}:{report:Report}) {
  const {config,document}=report;
  return <div className="daily-letters">{config.contracts.map(contract=><section className="daily-letter" key={contract.id}><span className="daily-letter-draft">Предпросмотр текущего черновика</span><header><h2>{config.profile.company_name}</h2><p>{config.profile.address}</p><small>ИНН {config.profile.inn} · ОГРНИП/ОГРН {config.profile.ogrn} · {config.profile.phone} · {config.profile.email}</small></header>
    <div className="daily-letter-recipient"><span>№ {report.letter_numbers[contract.id]||'без номера'} от {dateLabel(report.day)}</span><div>{config.profile.recipient.map((s,i)=><div key={i}>{s}</div>)}</div></div><p>В рамках исполнения контракта {contract.number} сообщаю следующую информацию:</p>
    {(['fact','plan'] as const).map(kind=><div key={kind}><h3>{kind==='fact'?'Фактическая дислокация оказания услуг (производства работ)':'Плановая дислокация оказания услуг'}</h3><p className="daily-letter-center">{config.profile.subject}<br/>{config.profile.short_name}<br/>{kind==='fact'?'За ':'На '}{dateLabel(kind==='fact'?report.fact_day:report.day)}</p><div className="table-scroll"><table><thead><tr><th>Наименование работ, услуг</th><th>Место оказания услуг</th><th>Персонал / техника</th><th>Объём</th><th>Примечания</th></tr></thead><tbody>{document[kind].filter(r=>config.areas.find(a=>a.id===r.area_id)?.contract_id===contract.id&&['include','info'].includes(r.decision)).map(r=><tr key={r.work_id+':'+r.area_id}><td>{config.works.find(w=>w.id===r.work_id)?.name}</td><td>{config.areas.find(a=>a.id===r.area_id)?.name}</td><td>{r.resources||'—'}</td><td>{r.decision==='include'&&r.quantity!==null?r.quantity.toLocaleString('ru-RU')+' '+config.works.find(w=>w.id===r.work_id)?.unit:'Без объёма'}</td><td>{r.note}</td></tr>)}</tbody></table></div></div>)}
    <p>Фотоотчёт: {config.profile.photo_url||'Ссылка не задана'}</p><p>{config.profile.short_name}</p></section>)}</div>;
}
