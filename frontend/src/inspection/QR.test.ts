// @vitest-environment jsdom
import { expect, it } from 'vitest';
import { invitationToken } from './QR';
import { signInDestination } from '../Login';
import type { User } from '../types';

it('reads a local organization QR while rejecting foreign URLs and malformed invitations',()=>{
  const token='a'.repeat(43);
  expect(invitationToken(token)).toBe(token);
  expect(invitationToken(window.location.origin+'/inspection#invite='+token)).toBe(token);
  for(const invalid of ['https://foreign.example/inspection#invite='+token,window.location.origin+'/other#invite='+token,
    window.location.origin+'/inspection#invite=short','javascript:alert(1)'])expect(()=>invitationToken(invalid)).toThrow();
});

it('routes inspectors to their independent workspace after common sign-in',()=>{
  expect(signInDestination({role:'INSPECTOR'} as User)).toBe('/inspection');
});
