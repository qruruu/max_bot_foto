import { dateLabel } from '../api';
import type { Report } from './types';

export default function LetterPreview({report,draft}:{report:Report;draft:boolean}) {
  const {config,document}=report;
  const profile=config.profile;
  const signed=!draft&&report.cohort==='production'&&!!profile.signature_image;
  return <div className="daily-letters">{config.contracts.map(contract=><article className="daily-letter" key={contract.id} aria-label={'Письмо по контракту '+contract.number}>
    {(draft||report.cohort==='test')&&<div className="daily-letter-draft">{draft?'ЧЕРНОВИК':'ТЕСТОВЫЙ ОТЧЁТ'}</div>}
    {profile.letterhead_image?<header className="daily-letter-image-header"><img src={profile.letterhead_image} alt="Фирменный бланк"/></header>:<header><h2>{profile.company_name}</h2><p>{profile.address}</p><small>ИНН {profile.inn} · ОГРНИП/ОГРН {profile.ogrn} · {profile.phone} · {profile.email}</small></header>}
    <div className="daily-letter-recipient"><span>№ {report.letter_numbers[contract.id]||'б/н'} от {dateLabel(report.day)}</span><div>{profile.recipient.map((line,i)=><div key={i}>{line}</div>)}</div></div>
    <p>В рамках исполнения контракта {contract.number} сообщаю следующую информацию:</p>
    {(['fact','plan'] as const).map(kind=>{
      const rows=document[kind].filter(row=>config.areas.find(area=>area.id===row.area_id)?.contract_id===contract.id&&['include','info'].includes(row.decision));
      return <section className="daily-letter-block" key={kind}>
        <h3>{kind==='fact'?'Фактическая дислокация оказания услуг (производства работ)':'Плановая дислокация оказания услуг'}</h3>
        <p className="daily-letter-center">{profile.subject}<br/>{profile.short_name||profile.company_name}<br/><b>{kind==='fact'?'За ':'На '}{dateLabel(kind==='fact'?report.fact_day:report.day)} года</b></p>
        <div className="table-scroll"><table><colgroup>{[5,27,30,14,11,13].map((width,i)=><col key={i} style={{width:width+'%'}}/>)}</colgroup><thead><tr><th>№</th><th>Наименование работ, услуг</th><th>Место оказания услуг (производства работ)</th><th>Спецтехника, персонал</th><th>{kind==='fact'?'Объём':'План, объём'}</th><th>Примечания</th></tr></thead><tbody>{rows.map((row,i)=><tr key={row.work_id+':'+row.area_id}><td>{i+1}</td><td>{config.works.find(work=>work.id===row.work_id)?.name}</td><td>{config.areas.find(area=>area.id===row.area_id)?.name}</td><td>{row.resources}</td><td>{row.decision==='include'&&row.quantity!==null?row.quantity.toLocaleString('ru-RU')+' '+config.works.find(work=>work.id===row.work_id)?.unit:'—'}</td><td>{row.note}</td></tr>)}{!rows.length&&<tr><td colSpan={6}>Работы не заявлены. {document.note}</td></tr>}</tbody></table></div>
      </section>;
    })}
    {profile.photo_url&&<p>Фотоотчёт доступен по ссылке <a href={profile.photo_url} target="_blank" rel="noreferrer">{profile.photo_url}</a></p>}
    {document.note&&<p>Примечание: {document.note}</p>}
    <div className="daily-letter-signature">{signed?<img src={profile.signature_image} alt="Подпись и печать организации"/>:<p>{profile.short_name||profile.company_name}</p>}</div>
  </article>)}</div>;
}
