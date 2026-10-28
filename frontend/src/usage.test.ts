// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { expect, it, vi } from 'vitest';
const source=readFileSync('public/usage.js','utf8');
function tracker(blocked=false,dnt=false) {
  const fetch=vi.fn().mockResolvedValue({}),timer=vi.fn();
  const storage={getItem:()=>{if(blocked)throw Error('Blocked');return null;},setItem:()=>{if(blocked)throw Error('Blocked');}};
  const win={} as Window;
  new Function('window','document','navigator','location','crypto','localStorage','sessionStorage','fetch','setInterval',source)(
    win,{hidden:false,referrer:'https://example.org/private-page?token=secret',addEventListener:vi.fn()},
    {doNotTrack:dnt?'1':'0',userAgent:'iPhone'}, {search:'?from=telegram&contact=private',hostname:'signal.example'},
    {randomUUID},storage,storage,fetch,timer);
  return {win,fetch,timer};
}
it('keeps a visit together with blocked browser storage and sends only allowlisted metadata',()=>{
  const {win,fetch}=tracker(true);
  win.MetkaUsage!.page('signal','appeal_form');win.MetkaUsage!.event('signal','appeal_sent');
  const bodies=fetch.mock.calls.map(call=>JSON.parse(call[1].body));
  expect(bodies).toHaveLength(2);
  expect(bodies[0].session_id).toBe(bodies[1].session_id);
  expect(bodies[0].visitor_id).toBe(bodies[1].visitor_id);
  expect(bodies[0].source).toBe('telegram');expect(bodies[0].device).toBe('phone');
  expect(JSON.stringify(bodies)).not.toMatch(/secret|private-page|contact|token/);
});
it('respects Do Not Track and deduplicates immediate React remounts',()=>{
  const disabled=tracker(false,true);expect(disabled.win.MetkaUsage).toBeUndefined();expect(disabled.fetch).not.toHaveBeenCalled();
  const {win,fetch}=tracker();win.MetkaUsage!.page('metka','photos','same-key');win.MetkaUsage!.page('metka','photos','same-key');
  expect(fetch).toHaveBeenCalledTimes(1);
});
