import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, Eye, History, ImagePlus, Monitor, Moon, Newspaper, Plus, RefreshCw, Save, Send, Smartphone, Sun, Trash2, Undo2, X } from 'lucide-react';
import { api, ApiError } from './api';
import ArticleView from './news/ArticleView';
import RichEditor from './news/RichEditor';
import { DraftSession } from './news/DraftSession';
import { editorAssetUrl, newsAssetIds, newsDate } from './news/types';
import type { NewsArticle, NewsAsset, NewsListItem, NewsNode, NewsPost, NewsRevision } from './news/types';
import './news.css';
import './news-editor.css';

const base='/platform/news';
const actionNames:Record<string,string>={CREATE:'Создан черновик',IMPORT:'Перенос публикации',SAVE:'Сохранён черновик',PUBLISH:'Опубликовано',UNPUBLISH:'Снято с публикации',TRASH:'В корзине',RESTORE:'Восстановлено из корзины',RESTORE_REVISION:'Восстановлена редакция'};
function stamp(value:string) {return new Date(value).toLocaleString('ru-RU', {day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});}
function plainText(node:NewsNode):string {return (node.text || '')+(node.content?.map(plainText).join(node.type==='doc'?'\n\n':' ') || '');}

export default function NewsAdmin({onEditingChange}:{onEditingChange?:(editing:boolean)=>void}) {
  const [items,setItems]=useState<NewsListItem[]>([]),[trash,setTrash]=useState(false),[selected,setSelected]=useState<NewsArticle | null>(null);
  const [error,setError]=useState(''),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[picker,setPicker]=useState(false);
  const [reload,setReload]=useState(0);
  useEffect(()=>{onEditingChange?.(!!selected);return()=>onEditingChange?.(false);},[!!selected,onEditingChange]);
  async function load() {setLoading(true); setError(''); try{setItems(await api<NewsListItem[]>(base+'?state='+(trash?'trash':'active')));} catch(e){setError((e as Error).message);} finally{setLoading(false);}}
  useEffect(()=>{void load();},[trash,reload]);
  async function open(id:string) {setError(''); setBusy(true); try{setSelected(await api<NewsArticle>(base+'/'+id));} catch(e){setError((e as Error).message);} finally{setBusy(false);}}
  async function create(template:string) {setBusy(true); setError(''); try{setSelected(await api<NewsArticle>(base,'POST',{template})); setPicker(false);} catch(e){setError((e as Error).message);} finally{setBusy(false);}}
  if(selected) return <NewsEditor key={selected.id} initial={selected} onBack={()=>{setSelected(null); setReload(n=>n+1);}}/>;
  return <div className="news-admin">
    <header className="page-header"><div><span className="eyebrow">ОБЩИЕ ОБНОВЛЕНИЯ СЕРВИСА</span><h1>Редактор новостей</h1><p>Расскажите операторам, что изменилось и как это поможет в работе.</p></div><button className="primary" disabled={busy} onClick={()=>setPicker(true)}><Plus size={18}/>Написать новость</button></header>
    <div className="news-admin-scope"><Newspaper size={18}/><span>Публикации общие для всех организаций. Их читают пользователи с доступом к новостям.</span></div>
    <nav className="news-admin-tabs" aria-label="Статьи"><button className={!trash?'selected':''} onClick={()=>setTrash(false)}>Все статьи</button><button className={trash?'selected':''} onClick={()=>setTrash(true)}><Trash2 size={15}/>Корзина</button><button aria-label="Обновить статьи" onClick={()=>setReload(n=>n+1)}><RefreshCw size={16}/></button></nav>
    {error && <div className="error" role="alert">{error}</div>}
    {loading?<p className="loading">Загружаем статьи…</p>:<div className="news-admin-list">{items.map(item=><button className="panel news-admin-card" key={item.id} disabled={busy} onClick={()=>void open(item.id)}>
      <div className="news-admin-card-copy"><div className="news-meta"><span className="news-category">{item.draft.category || 'Без категории'}</span><span className={'news-status '+(item.published?'published':'')}>{trash?'В корзине':item.published?'Опубликовано':'Черновик'}</span>{item.published && item.has_changes && <span>Есть неопубликованные правки</span>}</div>
        <h2>{item.draft.title || 'Новая статья'}</h2><p>{item.draft.summary || 'Добавьте анонс, чтобы читатель сразу понял пользу.'}</p><small>{item.author_name} · {stamp(item.updated_at)}</small></div><ArrowRight size={20}/></button>)}
      {!items.length && <div className="panel news-not-found"><Newspaper size={32}/><h2>{trash?'Корзина пуста':'Начните с полезной новости'}</h2><p>{trash?'Удалённые статьи можно восстановить здесь.':'Выберите шаблон и расскажите о новой возможности.'}</p></div>}</div>}
    {picker && <div className="modal-backdrop"><div className="modal news-template-picker"><div className="section-title"><h2>С чего начнём?</h2><button aria-label="Закрыть" disabled={busy} onClick={()=>setPicker(false)}><X size={18}/></button></div><p className="hint">Структуру и заголовки можно свободно менять.</p>
      {[['update','Обновление','Польза → как пользоваться → скриншоты → условия'],['tip','Полезный совет','Рабочая ситуация, короткий приём и результат'],['empty','Чистый лист','Свободный рассказ в вашем порядке']].map(([key,title,description])=><button key={key} disabled={busy} className="news-template" onClick={()=>void create(key)}><span><strong>{title}</strong><small>{description}</small></span><ArrowRight size={17}/></button>)}</div></div>}
  </div>;
}

function NewsEditor({initial,onBack}:{initial:NewsArticle;onBack:()=>void}) {
  const session=useMemo(()=>new DraftSession(initial,(id,snapshot,version)=>api<NewsArticle>(base+'/'+id,'PUT',{...snapshot,expected_version:version})),[initial.id]);
  const [,redraw]=useState(0),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[uploads,setUploads]=useState(0);
  const [preview,setPreview]=useState<NewsPost | null>(null),[phone,setPhone]=useState(false),[previewTheme,setPreviewTheme]=useState<'light'|'dark'>('light');
  const [history,setHistory]=useState<NewsRevision[] | null>(null),[historyPreview,setHistoryPreview]=useState<NewsRevision | null>(null),[editorKey,setEditorKey]=useState(0);
  const [confirm,setConfirm]=useState<'publish'|'unpublish'|'trash'|'restore'|null>(null);
  const previewDialog=useRef<HTMLDialogElement>(null),historyDialog=useRef<HTMLDialogElement>(null),confirmDialog=useRef<HTMLDialogElement>(null),coverInput=useRef<HTMLInputElement>(null);
  useEffect(()=>session.subscribe(()=>redraw(n=>n+1)),[session]);
  const draft=session.draft, article=session.article, dirty=session.dirty;
  useEffect(()=>{if(!dirty || session.conflict || busy || uploads || article.deleted_at) return; const timer=setTimeout(()=>{void session.flush().catch(()=>{});},1200);return()=>clearTimeout(timer);},[draft,dirty,session,busy,uploads,article.deleted_at]);
  useEffect(()=>{const guard=(e:BeforeUnloadEvent)=>{if(session.dirty || session.pending || uploads){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',guard);return()=>window.removeEventListener('beforeunload',guard);},[session,uploads]);
  useEffect(()=>{if(preview)previewDialog.current?.showModal(); else previewDialog.current?.close();},[preview]);
  useEffect(()=>{if(history)historyDialog.current?.showModal();else historyDialog.current?.close();},[history]);
  useEffect(()=>{if(confirm)confirmDialog.current?.showModal();else confirmDialog.current?.close();},[confirm]);
  function change(patch:Partial<typeof draft>){session.edit({...session.draft,...patch});setNotice('');}
  async function perform(task:()=>Promise<void>){setBusy(true);setError('');setNotice('');try{await task();}catch(e){setError((e as Error).message);setConfirm(null);if(history)setHistory(null);if(e instanceof ApiError && e.status===409 && (e.detail as {code?:string})?.code==='NEWS_CONFLICT'){session.conflict=true;session.error=e.message;session.emit();}}finally{setBusy(false);}}
  async function upload(file:File):Promise<NewsAsset | null>{
    if(!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size>8*1024*1024){setError('Выберите PNG, JPG или WebP не больше 8 МБ.');return null;}
    setUploads(n=>n+1);setError('');try{return await api<NewsAsset>(base+'/assets','POST',file);}catch(e){setError((e as Error).message);return null;}finally{setUploads(n=>n-1);}
  }
  function previewSnapshot(snapshot:typeof draft):NewsPost {
    const document=structuredClone(snapshot.document);
    function walk(node:NewsNode){if(node.type==='image')node.attrs={...node.attrs,src:editorAssetUrl(String(node.attrs?.asset_id))};node.content?.forEach(walk);}walk(document);
    return {...snapshot,document,slug:article.slug,publishedAt:(article.published_at || new Date().toISOString()).slice(0,10)};
  }
  async function execute(action:string){await session.flush();const result=await api<NewsArticle>(base+'/'+article.id+'/'+action,'POST',{expected_version:session.article.version});session.accept(result);setEditorKey(n=>n+1);setConfirm(null);setNotice(action==='publish'?'Новость опубликована. Операторы уже могут её открыть.':action==='trash'?'Новость в корзине. Читателям она недоступна.':action==='restore'?'Статья восстановлена как черновик. Её можно опубликовать.':'Новость снята с публикации. Черновик сохранён.');}
  const images=newsAssetIds(draft.document);
  const status=session.conflict?'Конфликт изменений':session.error?'Не удалось сохранить':uploads?'Загружаем изображение…':session.pending?'Сохраняем…':dirty?'Есть несохранённые изменения':'Черновик сохранён';
  const disabled=busy || uploads>0;
  return <div className="news-admin news-editing">
    <div className="news-editor-top"><button disabled={disabled || session.conflict} onClick={()=>void perform(async()=>{if(!session.conflict)await session.flush();onBack();})}><ArrowLeft size={16}/>Все статьи</button><span className={'news-save-status '+(session.error?'warning-text':'')} role="status">{!dirty && !session.error && <Check size={15}/>} {status}</span>
      <div className="news-editor-actions"><button disabled={disabled || !!article.deleted_at} onClick={()=>void perform(async()=>{await session.flush();setNotice('Черновик сохранён. Публикация — отдельное действие.');})}><Save size={16}/>Сохранить</button>
        <button disabled={disabled || !!article.deleted_at} onClick={()=>void perform(async()=>{await session.flush();setPreview(await api<NewsPost>(base+'/'+article.id+'/preview','POST',{expected_version:session.article.version}));})}><Eye size={16}/>Предпросмотр</button>
        {!article.deleted_at && <button className="primary" disabled={disabled || session.conflict} onClick={()=>setConfirm('publish')}><Send size={16}/>{article.published?'Опубликовать правки':'Опубликовать'}</button>}</div></div>
    {(error || session.error) && <div className="error" role="alert">{error || session.error}{session.conflict && <div className="news-inline-actions"><button onClick={()=>void navigator.clipboard.writeText([draft.title,draft.summary,plainText(draft.document)].join('\n\n')).then(()=>setNotice('Ваш текст скопирован.'))}>Скопировать мой текст</button><button onClick={()=>void perform(async()=>{session.accept(await api<NewsArticle>(base+'/'+article.id));setEditorKey(n=>n+1);})}>Загрузить свежую версию</button></div>}{!session.conflict && <button onClick={()=>void perform(()=>session.flush())}>Повторить сохранение</button>}</div>}
    {notice && <p className="organization-notice" role="status">{notice}</p>}
    <div className="news-editor-grid"><section className="panel news-compose">
      <div className="news-meta"><span className={'news-status '+(article.published?'published':'')}>{article.deleted_at?'В корзине':article.published?'Опубликовано':'Черновик'}</span><span>Общая новость для всех организаций</span></div>
      <fieldset disabled={disabled || !!article.deleted_at || session.conflict} className="news-compose-fields">
        <label className="news-title-field">Заголовок<input value={draft.title} maxLength={200} placeholder="Что теперь проще делать в работе?" onChange={e=>change({title:e.target.value})}/></label>
        <label>Короткий анонс<textarea rows={3} value={draft.summary} maxLength={600} placeholder="Одна-две фразы о пользе — появятся в списке новостей" onChange={e=>change({summary:e.target.value})}/></label>
        <label>Категория<input list="news-categories" value={draft.category} maxLength={60} onChange={e=>change({category:e.target.value})}/><datalist id="news-categories"><option>Обновление</option><option>Полезный совет</option><option>Инструкция</option></datalist></label>
        <label className="news-body-label">Текст статьи</label><RichEditor disabled={disabled || !!article.deleted_at || session.conflict} key={editorKey} initial={draft.document} upload={upload} onError={setError} onChange={document=>change({document})}/>
      </fieldset>
    </section><aside className="news-editor-side">
      <section className="panel"><span className="eyebrow">ПУБЛИКАЦИЯ</span><h2>{article.published?'Статья доступна читателям':'Пока видите только вы'}</h2><p className="hint">{article.published?'Правки сохраняются в черновик. Читатели увидят их после повторной публикации.':'Сохранение не публикует статью. Сначала проверьте текст и скриншоты в предпросмотре.'}</p><p className="news-revision-meta">{article.author_name}<br/>{stamp(article.updated_at)}</p>
        <button disabled={disabled} onClick={()=>void perform(async()=>{if(!article.deleted_at)await session.flush();setHistory(await api<NewsRevision[]>(base+'/'+article.id+'/revisions'));})}><History size={16}/>История изменений</button>
        {article.published && !article.deleted_at && <button disabled={disabled} onClick={()=>setConfirm('unpublish')}>Снять с публикации</button>}
        <button className={article.deleted_at?'':'danger'} disabled={disabled} onClick={()=>setConfirm(article.deleted_at?'restore':'trash')}>{article.deleted_at?<Undo2 size={15}/>:<Trash2 size={15}/>} {article.deleted_at?'Восстановить статью':'В корзину'}</button>
      </section>
      <section className="panel news-cover-picker"><h2>Обложка в списке</h2><p className="hint">Необязательно. Выберите скриншот из статьи или загрузите отдельный.</p>{draft.cover_id && <img src={editorAssetUrl(draft.cover_id)} alt="Выбранная обложка"/>}
        <div className="news-cover-options">{images.map(id=><button disabled={disabled || !!article.deleted_at || session.conflict} aria-label="Выбрать обложку" aria-pressed={draft.cover_id===id} key={id} onClick={()=>change({cover_id:id})}><img src={editorAssetUrl(id)} alt="Вариант обложки"/></button>)}</div>
        <button disabled={disabled || !!article.deleted_at || session.conflict} onClick={()=>coverInput.current?.click()}><ImagePlus size={15}/>Загрузить обложку</button>{draft.cover_id && <button disabled={disabled || !!article.deleted_at || session.conflict} onClick={()=>change({cover_id:null})}>Без обложки</button>}
        <input ref={coverInput} type="file" hidden accept="image/png,image/jpeg,image/webp" onChange={async e=>{const file=e.target.files?.[0];e.target.value='';if(file){const asset=await upload(file);if(asset)change({cover_id:asset.id});}}}/>
      </section><section className="panel news-editor-tip"><h2>Помогите оператору начать</h2><p>Покажите пользу в первых строках. Затем — несколько шагов с названиями кнопок и скриншот рядом с действием.</p><p>Для примеров используйте тестовые данные без личных сведений.</p></section>
    </aside></div>
    <dialog ref={previewDialog} className="news-preview-dialog" aria-label="Предпросмотр новости" onClose={()=>setPreview(null)}>
      <div className="news-preview-toolbar"><strong>Так увидит читатель</strong><div className="news-inline-actions"><button aria-label="Компьютер" aria-pressed={!phone} onClick={()=>setPhone(false)}><Monitor size={17}/></button><button aria-label="Телефон" aria-pressed={phone} onClick={()=>setPhone(true)}><Smartphone size={17}/></button><button aria-label="Светлая тема" aria-pressed={previewTheme==='light'} onClick={()=>setPreviewTheme('light')}><Sun size={17}/></button><button aria-label="Тёмная тема" aria-pressed={previewTheme==='dark'} onClick={()=>setPreviewTheme('dark')}><Moon size={17}/></button><button aria-label="Закрыть предпросмотр" onClick={()=>setPreview(null)}><X size={19}/></button></div></div>
      <div className={'news-preview-surface news-theme-'+previewTheme}><div className={'news-preview-page '+(phone?'phone':'')}>{preview && <ArticleView post={preview}/>}</div></div>
    </dialog>
    <dialog ref={historyDialog} className="news-history-dialog" aria-label="История изменений" onClose={()=>{setHistory(null);setHistoryPreview(null);}}>
      <div className="section-title"><div><h2>История изменений</h2><p className="hint">Восстановление меняет черновик. Опубликованная статья останется прежней.</p></div><button aria-label="Закрыть историю" onClick={()=>setHistory(null)}><X size={19}/></button></div>
      <div className="news-history-layout"><div>{history?.map(row=><button className={'news-history-row '+(historyPreview?.id===row.id?'selected':'')} key={row.id} onClick={()=>setHistoryPreview(row)}><strong>{actionNames[row.action] || row.action} · v{row.version}</strong><span>{row.author_name}</span><small>{stamp(row.created_at)}</small></button>)}</div>
        <div>{historyPreview?<><button disabled={disabled || !!article.deleted_at} onClick={()=>void perform(async()=>{await session.flush();session.accept(await api<NewsArticle>(base+'/'+article.id+'/revisions/'+historyPreview.id+'/restore','POST',{expected_version:session.article.version}));setEditorKey(n=>n+1);setHistory(null);setNotice('Редакция восстановлена в черновик.');})}><Undo2 size={15}/>Восстановить в черновик</button><ArticleView post={previewSnapshot(historyPreview.snapshot)}/></>:<p className="empty">Выберите редакцию слева.</p>}</div></div>
    </dialog>
    <dialog ref={confirmDialog} className="modal news-confirm-dialog" aria-label="Подтверждение действия" onClose={()=>setConfirm(null)}><h2>{confirm==='publish'?'Опубликовать новость?':confirm==='trash'?'Переместить в корзину?':confirm==='restore'?'Восстановить статью?':'Снять с публикации?'}</h2><p>{confirm==='publish'?'Текущий черновик станет доступен во всех организациях пользователям с правом просмотра новостей.':confirm==='trash'?'Статья и её изображения перестанут открываться у читателей. Черновик и история сохранятся, статью можно восстановить.':confirm==='restore'?'Статья вернётся в черновики. Чтобы снова показать её читателям, нажмите «Опубликовать».':'Статья и её изображения станут недоступны читателям. Черновик и история сохранятся.'}</p><div className="news-inline-actions"><button disabled={disabled} onClick={()=>setConfirm(null)}>Отмена</button><button className="primary" disabled={disabled} onClick={()=>confirm && void perform(()=>execute(confirm))}>{busy?'Сохраняем…':'Подтвердить'}</button></div></dialog>
  </div>;
}
