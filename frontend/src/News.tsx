import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, CalendarDays, Expand, Newspaper, X } from 'lucide-react';
import { api, ApiError } from './api';
import { newsDate } from './news/types';
import type { NewsPost, NewsScreenshot, NewsSummary } from './news/types';
import './news.css';

export default function News() {
  const {slug} = useParams();
  const [image, setImage] = useState<NewsScreenshot | null>(null);
  const viewer = useRef<HTMLDialogElement>(null);
  const [posts, setPosts] = useState<NewsSummary[]>([]), [post, setPost] = useState<NewsPost | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState(''), [notFound, setNotFound] = useState(false), [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    window.scrollTo(0, 0); setImage(null); setPost(null); setPosts([]); setLoading(true); setError(''); setNotFound(false);
    const request = slug ? api<NewsPost>('/news/'+encodeURIComponent(slug),'GET',undefined,controller.signal).then(value => {if (!controller.signal.aborted) setPost(value);})
      : api<NewsSummary[]>('/news','GET',undefined,controller.signal).then(value => {if (!controller.signal.aborted) setPosts(value);});
    request.catch(e => {
      if (controller.signal.aborted) return;
      if (e instanceof ApiError && e.status===404) setNotFound(true);
      else setError(e.message);
    }).finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [slug, retry]);
  useEffect(() => {
    if (image) viewer.current?.showModal();
    else viewer.current?.close();
  }, [image]);

  if (loading) return <p className="loading">Открываем новости…</p>;
  if (error) return <div className="news-page"><div className="error" role="alert">{error}</div><button type="button" onClick={() => setRetry(value => value+1)}>Повторить</button></div>;
  if (notFound) return <div className="news-page">
    <Link className="back-link" to="/news"><ArrowLeft size={16}/>Все новости</Link>
    <section className="panel news-not-found"><Newspaper size={32}/><h1>Новость не найдена</h1><p>Откройте список публикаций и выберите нужную статью.</p></section>
  </div>;

  return <div className="news-page">
    {post ? <>
      <Link className="back-link" to="/news"><ArrowLeft size={16}/>Все новости</Link>
      <article className="panel news-article">
        <header className="news-article-header">
          <div className="news-meta"><span className="news-category">{post.category}</span><time dateTime={post.publishedAt}><CalendarDays size={14} aria-hidden="true"/>{newsDate(post.publishedAt)}</time></div>
          <h1>{post.title}</h1><p className="news-lead">{post.summary}</p>
        </header>
        {post.sections.map((section, index) => <section className="news-section" key={index} aria-labelledby={'news-section-'+index}>
          <h2 id={'news-section-'+index}>{section.title}</h2>
          {section.paragraphs?.map((paragraph, i) => <p key={i}>{paragraph}</p>)}
          {section.steps.length > 0 && <ol className="news-steps">{section.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>}
          {section.screenshots?.map(screenshot => <figure className="news-figure" key={screenshot.src}>
            <button type="button" className="news-screenshot" onClick={() => setImage(screenshot)} aria-label={'Увеличить скриншот: '+screenshot.alt}>
              <img src={screenshot.src} alt={screenshot.alt} loading="lazy" width={screenshot.width} height={screenshot.height}/>
              <span className="news-zoom"><Expand size={14} aria-hidden="true"/>Увеличить</span>
            </button>
            <figcaption>{screenshot.caption}</figcaption>
          </figure>)}
        </section>)}
        <footer className="news-article-footer"><Link className="text-button" to="/news"><ArrowLeft size={15}/>К списку новостей</Link></footer>
      </article>
    </> : <>
      <header className="page-header"><div><span className="eyebrow">ОБНОВЛЕНИЯ MAX ФОТО</span><h1>Новости</h1><p>Новые возможности и понятные инструкции — со скриншотами и примерами.</p></div><span className="news-page-icon" aria-hidden="true"><Newspaper size={25}/></span></header>
      <div className="news-layout">
        <section className="news-feed" aria-label="Публикации об обновлениях">
          {posts.map(item => <Link className="panel news-card" to={'/news/'+item.slug} key={item.slug} aria-labelledby={'news-title-'+item.slug}>
            <div className="news-meta"><span className="news-category">{item.category}</span><time dateTime={item.publishedAt}>{newsDate(item.publishedAt)}</time></div>
            <h2 id={'news-title-'+item.slug}>{item.title}</h2><p>{item.summary}</p>
            <span className="news-read">Читать новость<ArrowRight size={16} aria-hidden="true"/></span>
          </Link>)}
          {!posts.length && <section className="panel news-not-found"><Newspaper size={32}/><h2>Публикации скоро появятся</h2><p>Здесь будут новости об обновлениях сервиса.</p></section>}
        </section>
        <aside className="panel news-guide"><span className="eyebrow">В КАЖДОЙ ПУБЛИКАЦИИ</span><h2>От обновления к действию</h2><ul>
          <li><strong>Что нового</strong><span>Какие возможности появились и что изменилось.</span></li>
          <li><strong>Как пользоваться</strong><span>Порядок действий и примеры на экране.</span></li>
          <li><strong>Что учесть</strong><span>Нужные права и особенности работы.</span></li>
        </ul><p>Свежие публикации всегда сверху. Инструкции можно открыть в любой момент.</p></aside>
      </div>
    </>}
    <dialog ref={viewer} className="news-image-viewer" aria-label="Просмотр скриншота" onClose={() => setImage(null)}
      onClick={event => {if(event.target===event.currentTarget) viewer.current?.close();}}>
      <div className="news-image-content"><div className="news-image-toolbar"><span>Скриншот</span><button type="button" autoFocus aria-label="Закрыть скриншот" onClick={() => viewer.current?.close()}><X size={20}/></button></div>
        {image && <figure><img src={image.src} alt={image.alt}/><figcaption>{image.caption}</figcaption></figure>}
      </div>
    </dialog>
  </div>;
}
