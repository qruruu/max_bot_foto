import { describe, expect, it } from 'vitest';
import { filterOptionLabel, senderFilterOptions } from './filterCounts';

describe('counts in filter options', () => {
  const facet = {total: 1240, values: {BIN_EMPTYING: 1200, NONE: 40, '0': 40}};
  it('shows the whole matching count for all options', () => {
    expect(filterOptionLabel('Все виды работ', facet)).toBe('Все виды работ (1\u00a0240)');
  });
  it('shows the count for a category and unassigned values', () => {
    expect(filterOptionLabel('УРНЫ', facet, 'BIN_EMPTYING')).toBe('УРНЫ (1\u00a0200)');
    expect(filterOptionLabel('Не определён', facet, 'NONE')).toBe('Не определён (40)');
    expect(filterOptionLabel('Не проверено', facet, '0')).toBe('Не проверено (40)');
  });
  it('keeps zero alternatives visible and leaves labels intact while loading or on error', () => {
    expect(filterOptionLabel('ГАЗОН', facet, 'GREEN_CLEANING')).toBe('ГАЗОН (0)');
    expect(filterOptionLabel('ГАЗОН', undefined, 'GREEN_CLEANING')).toBe('ГАЗОН');
  });
});

describe('sender filter choices', () => {
  it('preserves full IDs and distinguishes identical labels', () => {
    const result = senderFilterOptions({total: 3, values: {}, options: [
      {value: '9007199254740992', name: 'Иван'},
      {value: '9007199254740993', name: 'Иван'},
      {value: '321', name: null},
    ]});
    expect(result).toEqual([
      {value: '9007199254740992', name: 'Иван · ID 9007199254740992'},
      {value: '9007199254740993', name: 'Иван · ID 9007199254740993'},
      {value: '321', name: 'ID 321'},
    ]);
  });
  it('keeps the selected sender visible during loading or an empty selection', () => {
    expect(senderFilterOptions(undefined, '9007199254740993'))
      .toEqual([{value: '9007199254740993', name: 'ID 9007199254740993'}]);
    expect(senderFilterOptions({total: 0, values: {}, options: []}, '123'))
      .toEqual([{value: '123', name: 'ID 123'}]);
    expect(senderFilterOptions(undefined, '0')).toEqual([]);
  });
});
