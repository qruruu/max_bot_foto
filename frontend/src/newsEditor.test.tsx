import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { ApiError } from './api';
import { DraftSession } from './news/DraftSession';
import ArticleView from './news/ArticleView';
import type { NewsArticle, NewsSnapshot } from './news/types';

const draft:NewsSnapshot={title:'Начало',summary:'Коротко',category:'Обновление',cover_id:null,document:{type:'doc',content:[{type:'paragraph',content:[{type:'text',text:'Текст'}]}]}};
function article(snapshot=draft,version=1):NewsArticle {return {id:'id',slug:'post-id',version,draft:structuredClone(snapshot),published:null,published_at:null,deleted_at:null,updated_at:'2026-10-25T10:00:00Z',author_name:'Владелец',has_changes:true};}
function deferred<T>(){let resolve!:(value:T)=>void;let reject!:(reason:unknown)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}

describe('news autosave and publish barrier',()=>{
  it('serializes saves, keeps typing during requests, and waits for the newest version before publishing',async()=>{
    const first=deferred<NewsArticle>(),second=deferred<NewsArticle>();
    const save=vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const session=new DraftSession(article(),save);
    session.edit({...draft,title:'Первая правка'});
    const flushing=session.flush();
    session.edit({...draft,title:'Продолжаю писать'});
    expect(session.flush()).toBe(flushing);
    expect(save).toHaveBeenCalledTimes(1);
    first.resolve(article({...draft,title:'Первая правка'},2));
    await new Promise(resolve=>setTimeout(resolve,0));
    expect(session.draft.title).toBe('Продолжаю писать');
    expect(save.mock.calls[1][2]).toBe(2);
    let published=false;const publish=flushing.then(()=>{published=true;});
    expect(published).toBe(false);
    second.resolve(article({...draft,title:'Продолжаю писать'},3));
    await publish;
    expect(session.article.version).toBe(3);
    expect(session.dirty).toBe(false);
    expect(session.pending).toBeNull();
  });
  it('keeps local text on a stale-version conflict and never retries it silently',async()=>{
    const save=vi.fn().mockRejectedValue(new ApiError(409,{message:'Другая вкладка изменила новость'}));
    const session=new DraftSession(article(),save);
    session.edit({...draft,title:'Мой текст'});
    await expect(session.flush()).rejects.toThrow('Другая вкладка');
    expect(session.draft.title).toBe('Мой текст');
    expect(session.dirty && session.conflict).toBe(true);
    await expect(session.flush()).rejects.toThrow();
    expect(save).toHaveBeenCalledTimes(1);
    session.accept(article({...draft,title:'Свежая версия'},5));
    expect(session.dirty || session.conflict).toBe(false);
  });
  it('retries a temporary failure using the same server version',async()=>{
    const save=vi.fn().mockRejectedValueOnce(new Error('Нет соединения')).mockResolvedValueOnce(article({...draft,title:'Сохранить'},2));
    const session=new DraftSession(article(),save);
    session.edit({...draft,title:'Сохранить'});
    await expect(session.flush()).rejects.toThrow('Нет соединения');
    expect(session.conflict).toBe(false);
    await session.flush();
    expect(save.mock.calls.map(call=>call[2])).toEqual([1,1]);
    expect(session.dirty).toBe(false);
  });
});

describe('shared reader and preview rendering',()=>{
  it('resolves action buttons and inline links in the reader’s organization and renders formatting as safe React text',()=>{
    const base='/org/11111111-1111-4111-8111-111111111111';
    const markup=renderToStaticMarkup(<MemoryRouter basename={base} initialEntries={[base+'/news/test']}><ArticleView post={{...draft,slug:'test',publishedAt:'2026-10-25',document:{type:'doc',content:[
      {type:'heading',attrs:{level:2},content:[{type:'text',text:'Как пользоваться'}]},
      {type:'paragraph',content:[{type:'text',text:'<script>alert(1)</script>',marks:[{type:'bold'},{type:'italic'},{type:'link',attrs:{href:'/review'}}]}]},
      {type:'important',content:[{type:'paragraph',content:[{type:'text',text:'Нужен доступ к фотографиям.'}]}]},
      {type:'action',attrs:{href:'/photos?all_dates=1',label:'Открыть фотографии'}},
      {type:'image',attrs:{src:base+'/api/news/assets/image',alt:'Тестовый пример',caption:'Подпись'}},
    ]}}}/></MemoryRouter>);
    expect(markup).toContain('href="'+base+'/photos?all_dates=1"');
    expect(markup).toContain('href="'+base+'/review"');
    expect(markup).toContain('&lt;script&gt;');
    expect(markup).not.toContain('<script>');
    expect(markup).toContain('<strong>');
    expect(markup).toContain('<em>');
    expect(markup).toContain('news-important');
    expect(markup).toContain('Увеличить скриншот: Тестовый пример');
    expect(markup).toContain('<figcaption>Подпись</figcaption>');
  });
});
