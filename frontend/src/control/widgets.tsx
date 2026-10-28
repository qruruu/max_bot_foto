import type { ReactNode } from 'react';
import { Activity, AlertTriangle, Clock3 } from 'lucide-react';
export const number = (value:number|null|undefined) => value == null ? '—' : value.toLocaleString('ru-RU',{maximumFractionDigits:1});
export const bytes = (value:number|null|undefined) => value == null ? '—' : value >= 1024**3 ? number(value/1024**3)+' ГиБ' : value >= 1024**2 ? number(value/1024**2)+' МиБ' : value >= 1024 ? number(value/1024)+' КиБ' : number(value)+' Б';
export const timestamp = (value:string|null|undefined) => value ? new Date(value).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : 'Нет данных';
export const duration = (value:number|null|undefined) => value == null ? '—' : value >= 86400 ? number(value/86400)+' дн.' : value >= 3600 ? number(value/3600)+' ч' : value >= 60 ? number(value/60)+' мин' : number(value)+' с';
export function Metric({label,value,hint,change,tone}:{label:string;value:ReactNode;hint?:ReactNode;change?:number|null;tone?:string}) {
  return <article className={'control-metric '+(tone||'')}><span>{label}</span><strong>{value}</strong><small>{hint || '\u00a0'}</small>{change != null && <span className={'control-change '+(change>=0?'positive':'negative')}>{change>0?'+':''}{number(change)}% к прошлому периоду</span>}</article>;
}
export function EmptyData({children}:{children:ReactNode}) {return <div className="control-empty"><Activity size={27}/><p>{children}</p></div>;}
export function Notice({children,tone='warning'}:{children:ReactNode;tone?:string}) {return <div className={'control-notice '+tone}><AlertTriangle size={17}/><div>{children}</div></div>;}
export function Freshness({at}:{at:string|null|undefined}) {return <span className="control-freshness"><Clock3 size={13}/>{timestamp(at)}</span>;}
export function Panel({title,aside,children}:{title:string;aside?:ReactNode;children:ReactNode}) {return <section className="control-panel"><header><h2>{title}</h2>{aside}</header>{children}</section>;}
export function Bars({items,empty='Данные появятся после первых посещений.'}:{items:{label:string;value:number;hint?:string}[];empty?:string}) {
  const max = Math.max(1,...items.map(i=>i.value));
  return !items.length ? <EmptyData>{empty}</EmptyData> : <div className="control-bars">{items.map((item,index)=><div key={item.label+index}><div><span title={item.label}>{item.label}{item.hint&&<small>{item.hint}</small>}</span><strong>{number(item.value)}</strong></div><div className="control-bar"><i style={{width:100*item.value/max+'%'}}/></div></div>)}</div>;
}
export function Trend({series,label,color='var(--primary)',percent=false}:{series:{label:string;value:number|null}[];label:string;color?:string;percent?:boolean}) {
  const known=series.filter(s=>s.value!=null);
  if(!known.length)return <EmptyData>Пока недостаточно данных для графика.</EmptyData>;
  const width=680,height=190,pad=28,max=percent?100:Math.max(1,...known.map(s=>s.value!));
  const x=(i:number)=>pad+(width-2*pad)*i/Math.max(1,series.length-1),y=(v:number)=>height-pad-(height-2*pad)*v/max;
  let path=''; let connected=false;
  series.forEach((s,i)=>{if(s.value==null){connected=false;return;}path+=(connected?' L':' M')+x(i)+','+y(s.value);connected=true;});
  return <div className="control-trend"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
    {[0,.5,1].map(n=><g key={n}><line x1={pad} x2={width-pad} y1={y(max*n)} y2={y(max*n)} stroke="var(--border)" strokeDasharray="3 5"/><text x={4} y={y(max*n)-5}>{number(max*n)}{percent?'%':''}</text></g>)}
    <path d={path} fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round"/>
    {series.map((s,i)=>s.value!=null&&<circle key={i} cx={x(i)} cy={y(s.value)} r={series.length>100?2:4} fill={color}><title>{s.label}: {number(s.value)}{percent?'%':''}</title></circle>)}
  </svg><div className="control-trend-labels"><span>{series[0]?.label}</span><span>{series.at(-1)?.label}</span></div></div>;
}
