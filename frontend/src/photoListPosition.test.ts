import { afterEach, describe, expect, it, vi } from 'vitest';
import { capturePhotoListPosition, photoListAnchor, restorePhotoListPosition } from './photoNavigation';

afterEach(() => vi.unstubAllGlobals());

function viewport(rowTop: number | null, scrollY = 0) {
  const focus = vi.fn(), scrollTo = vi.fn();
  const table = {scrollLeft: 0};
  const row = rowTop === null ? null : {
    getBoundingClientRect: () => ({top: rowTop, height: 140}),
    querySelector: () => ({focus}),
  };
  vi.stubGlobal('document', {getElementById: () => row, querySelector: () => table});
  vi.stubGlobal('window', {scrollY, innerHeight: 800, scrollTo});
  return {table, focus, scrollTo};
}

describe('shared archive and day-review return position', () => {
  it('restores the same row offset, horizontal scroll and keyboard focus after loading the table', () => {
    const original = viewport(190, 1400);
    original.table.scrollLeft = 480;
    const position = capturePhotoListPosition(70);
    const returned = viewport(1590);
    restorePhotoListPosition(70, position);
    expect(returned.scrollTo).toHaveBeenCalledWith({top: 1400, behavior: 'instant'});
    expect(returned.table.scrollLeft).toBe(480);
    expect(returned.focus).toHaveBeenCalledWith({preventScroll: true});
  });
  it('uses the server-resolved neighbour when the saved photo has left the AI queue', () => {
    const position = {photoId: 70, rowOffset: 190, scrollY: 1400, scrollLeft: 480};
    expect(photoListAnchor('42', position)).toBe(42);
    expect(photoListAnchor(null, position)).toBe(70);
    const returned = viewport(1450);
    restorePhotoListPosition(42, position);
    expect(returned.scrollTo).toHaveBeenCalledWith({top: 1260, behavior: 'instant'});
  });
  it('falls back to the saved viewport when the filtered queue is empty', () => {
    const returned = viewport(null);
    restorePhotoListPosition(70, {photoId: 70, rowOffset: 190, scrollY: 1400, scrollLeft: 200});
    expect(returned.scrollTo).toHaveBeenCalledWith({top: 1400, behavior: 'instant'});
    expect(returned.table.scrollLeft).toBe(200);
    expect(returned.focus).not.toHaveBeenCalled();
  });
  it('centres a return anchor when opening the list without a stored viewport', () => {
    const returned = viewport(1400);
    restorePhotoListPosition(70);
    expect(returned.scrollTo).toHaveBeenCalledWith({top: 1070, behavior: 'instant'});
  });
});
