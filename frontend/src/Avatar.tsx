import { useState } from 'react';

export default function Avatar({name, src, className = ''}: {name: string; src: string | null; className?: string}) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  return <span className={`avatar ${className}`} aria-hidden="true">
    {src && failedSrc !== src
      ? <img src={src} alt="" onError={() => setFailedSrc(src)}/>
      : name.charAt(0).toLocaleUpperCase('ru-RU')}
  </span>;
}
