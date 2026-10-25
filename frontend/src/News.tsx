import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Newspaper, PenLine } from 'lucide-react';
import { api, ApiError } from './api';
import { newsDate } from './news/types';
import type { NewsPost, NewsSummary } from './news/types';
import ArticleView from './news/ArticleView';
import './news.css';

export default function News({owner = false}: {owner?: boolean}) {
  const {slug} = useParams();
  const [posts, setPosts] = useState<NewsSummary[]>([]), [post, setPost] = useState<NewsPost | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState(''), [notFound, setNotFound] = useState(false), [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    window.scrollTo(0, 0); setPost(null); setPosts([]); setLoading(true); setError(''); setNotFound(false);
    const request = slug ? api<NewsPost>('/news/'+encodeURIComponent(slug),'GET',undefined,controller.signal).then(value => {if (!controller.signal.aborted) setPost(value);})
      : api<NewsSummary[]>('/news','GET',undefined,controller.signal).then(value => {if (!controller.signal.aborted) setPosts(value);});
    request.catch(e => {
      if (controller.signal.aborted) return;
      if (e instanceof ApiError && e.status===404) setNotFound(true); else setError(e.message);
    }).finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [slug, retry]);
  if (loading) return <p className="loading">Открываем новости…</p>;
  if (error) return <div className="news-page"><div className="error" role="alert">{error}</div><button type="button" onClick={() => setRetry(value => value+1)}>Повторить</button></div>;
  return <div className="news-page">
    {slug && <Link className="back-link" to="/news"><ArrowLeft size={16}/>Все новости</Link>}
    {notFound ? <section className="panel news-not-found"><Newspaper size={32}/><h1>Новость не найдена</h1><p>Откройте список публикаций и выберите нужную статью.</p></section> : post ? <ArticleView post={post}/> : <>
      <header className="page-header"><div><span className="eyebrow">ОБНОВЛЕНИЯ MAX ФОТО</span><h1>Новости</h1><p>Новые возможности и понятные инструкции — со скриншотами и примерами.</p></div>{owner ? <a className="button" href="/?section=news"><PenLine size={17}/>Редактор новостей</a> : <span className="news-page-icon"><Newspaper size={25}/></span>}</header>
      <div className="news-layout"><section className="news-feed" aria-label="Публикации об обновлениях">
        {posts.map(item => <Link className="panel news-card" to={'/news/'+item.slug} key={item.slug}>
          {item.cover_src && <img className="news-card-cover" src={item.cover_src} alt="" loading="lazy"/>}
          <div className="news-meta"><span className="news-category">{item.category}</span><time dateTime={item.publishedAt}>{newsDate(item.publishedAt)}</time></div>
          <h2>{item.title}</h2><p>{item.summary}</p><span className="news-read">Читать новость<ArrowRight size={16}/></span></Link>)}
        {!posts.length && <section className="panel news-not-found"><Newspaper size={32}/><h2>Публикации скоро появятся</h2><p>Здесь будут новости об обновлениях сервиса.</p></section>}
      </section><aside className="panel news-guide"><span className="eyebrow">В КАЖДОЙ ПУБЛИКАЦИИ</span><h2>От обновления к действию</h2><ul>
        <li><strong>Что нового</strong><span>Какие возможности появились и что изменилось.</span></li><li><strong>Как пользоваться</strong><span>Порядок действий и примеры на экране.</span></li><li><strong>Что учесть</strong><span>Нужные права и особенности работы.</span></li></ul><p>Свежие публикации всегда сверху. Инструкции можно открыть в любой момент.</p></aside></div></>}
  </div>;
}
