import { describe, expect, it } from 'vitest';
import { query, shiftDate } from './api';
describe('report filters and calendar',()=>{
  it('preserves the unassigned district sentinel and removes empty filters',()=>{expect(query({district_id:'0',chat_id:'',status:'NEEDS_REVIEW'})).toBe('district_id=0&status=NEEDS_REVIEW');});
  it('crosses month and year boundaries consistently',()=>{expect(shiftDate('2026-01-01',-1)).toBe('2025-12-31');expect(shiftDate('2024-03-01',-1)).toBe('2024-02-29');});
});
