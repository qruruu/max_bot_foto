import { describe, expect, it } from 'vitest';
import { canRemoveMissingPreview } from './RemoveMissingPreview';

describe('orphan preview removal eligibility',()=>{
  it('allows only a confirmed missing original with failed storage',()=>{
    expect(canRemoveMissingPreview({processing_error:'ORIGINAL_MISSING',storage_status:'ERROR'})).toBe(true);
    for(const error of [null,'HTTP_404','HTTP_503','ReadTimeout'])
      expect(canRemoveMissingPreview({processing_error:error,storage_status:'ERROR'})).toBe(false);
    for(const status of ['SYNCED','PENDING','NOT_REQUIRED'])
      expect(canRemoveMissingPreview({processing_error:'ORIGINAL_MISSING',storage_status:status})).toBe(false);
  });
});
