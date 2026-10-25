import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { CalendarDays, Expand, X } from 'lucide-react';
import { newsDate } from './types';
import type { NewsNode, NewsPost, NewsScreenshot } from './types';

export function ArticleLink({href, children, className}: {href: string; children: ReactNode; className?: string}) {
  // Internal product paths are relative to the reader's router basename (/org/<reader>).
  return href.startsWith('/') && !href.startsWith('//') ? <Link to={href} className={className}>{children}</Link> :
    <a href={/^https?:\/\//.test(href) ? href : '#'} className={className} target="_blank" rel="noopener noreferrer">{children}</a>;
}

export default function ArticleView({post}: {post: NewsPost}) {
  const [image, setImage] = useState<NewsScreenshot | null>(null);
  const viewer = useRef<HTMLDialogElement>(null);
  useEffect(() => {if (image) viewer.current?.showModal(); else viewer.current?.close();}, [image]);
  function render(node: NewsNode, index: number): ReactNode {
    const children = node.content?.map(render);
    const attrs = node.attrs || {};
    switch (node.type) {
      case 'text': {
        let text: ReactNode = node.text;
        for (const mark of node.marks || []) {
          if (mark.type === 'bold') text = <strong>{text}</strong>;
          if (mark.type === 'italic') text = <em>{text}</em>;
          if (mark.type === 'link') text = <ArticleLink href={mark.attrs?.href || '#'}>{text}</ArticleLink>;
        }
        return <span key={index}>{text}</span>;
      }
      case 'paragraph': return <p key={index}>{children?.length ? children : <br/>}</p>;
      case 'heading': return attrs.level === 3 ? <h3 key={index}>{children}</h3> : <h2 key={index}>{children}</h2>;
      case 'bulletList': return <ul key={index}>{children}</ul>;
      case 'orderedList': return <ol key={index} start={Number(attrs.start || 1)}>{children}</ol>;
      case 'listItem': return <li key={index}>{children}</li>;
      case 'hardBreak': return <br key={index}/>;
      case 'important': return <aside className="news-important" key={index}><strong>Важно</strong>{children}</aside>;
      case 'action': return <p className="news-action" key={index}><ArticleLink href={String(attrs.href)} className="button primary">{String(attrs.label)}</ArticleLink></p>;
      case 'image': {
        const screenshot = {src: String(attrs.src), alt: String(attrs.alt || ''), caption: String(attrs.caption || '')};
        return <figure className="news-figure" key={index}><button type="button" className="news-screenshot" onClick={() => setImage(screenshot)} aria-label={'Увеличить скриншот: ' + screenshot.alt}>
          <img src={screenshot.src} alt={screenshot.alt} loading="lazy"/><span className="news-zoom"><Expand size={14}/>Увеличить</span></button>
          {screenshot.caption && <figcaption>{screenshot.caption}</figcaption>}</figure>;
      }
      default: return null;
    }
  }
  return <><article className="panel news-article">
    <header className="news-article-header"><div className="news-meta"><span className="news-category">{post.category || 'Категория'}</span><time dateTime={post.publishedAt}><CalendarDays size={14}/>{newsDate(post.publishedAt)}</time></div>
      <h1>{post.title || 'Заголовок статьи'}</h1><p className="news-lead">{post.summary || 'Коротко расскажите, чем полезна новость.'}</p></header>
    <div className="news-prose">{post.document.content?.map(render)}</div>
  </article><dialog ref={viewer} className="news-image-viewer" aria-label="Просмотр скриншота" onClose={() => setImage(null)} onClick={e => {if(e.target === e.currentTarget) viewer.current?.close();}}>
    <div className="news-image-content"><div className="news-image-toolbar"><span>Скриншот</span><button type="button" autoFocus aria-label="Закрыть скриншот" onClick={() => viewer.current?.close()}><X size={20}/></button></div>
      {image && <figure><img src={image.src} alt={image.alt}/><figcaption>{image.caption}</figcaption></figure>}</div>
  </dialog></>;
}
