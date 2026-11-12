import { Fragment } from 'react';

export default function LinkedText({children}: {children?: string | null}) {
  return (children ?? '').split(/(https?:\/\/[^\s<>"«»]+)/gi).map((part, index) => {
    if (!/^https?:\/\//i.test(part)) return part;
    let url = part.replace(/[.,!?;:'”]+$/, '');
    while (url.endsWith(')') && url.split(')').length > url.split('(').length) url = url.slice(0, -1);
    try {
      new URL(url);
    } catch {
      return part;
    }
    return <Fragment key={index}><a href={url} target="_blank" rel="noopener noreferrer">{url}</a>{part.slice(url.length)}</Fragment>;
  });
}
