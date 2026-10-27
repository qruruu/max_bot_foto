import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';

it('keeps the A4 preview and printed document styles identical across separate build contexts',()=>{
  const preview=readFileSync(new URL('./report-letter.css',import.meta.url),'utf8');
  const printed=readFileSync(new URL('../../../backend/app/report_letter.css',import.meta.url),'utf8');
  expect(preview).toBe(printed);
});
