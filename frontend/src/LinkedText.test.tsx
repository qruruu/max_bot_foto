import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import LinkedText from './LinkedText';

it('links URLs from appeal descriptions and preserves surrounding text', () => {
  const url = 'https://vk.ru/wall-52642163_1758832';
  const html = renderToStaticMarkup(<LinkedText>{`Смотрите ${url}.\nИ https://example.com/a_(b)?x=1#photo`}</LinkedText>);
  expect(html).toContain(`<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>.\nИ `);
  expect(html).toContain('href="https://example.com/a_(b)?x=1#photo"');
});

it('keeps unbalanced closing parentheses outside links and renders HTML as text', () => {
  const html = renderToStaticMarkup(<LinkedText>{'(https://example.com/photo) <img src=x> javascript:alert(1)'}</LinkedText>);
  expect(html).toContain('href="https://example.com/photo"');
  expect(html).toContain('</a>) &lt;img src=x&gt; javascript:alert(1)');
  expect(html.match(/<a /g)).toHaveLength(1);
});
