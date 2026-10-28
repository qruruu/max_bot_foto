// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { galleryPhoto } from './gallery';

let canDecode: boolean;
beforeEach(() => {
  canDecode = true;
  vi.stubGlobal('URL', {createObjectURL: vi.fn(() => 'blob:phone-photo'), revokeObjectURL: vi.fn()});
  vi.stubGlobal('Image', class {
    naturalWidth = 4032; naturalHeight = 3024;
    onload?: () => void; onerror?: () => void;
    set src(_value: string) {queueMicrotask(() => canDecode ? this.onload?.() : this.onerror?.());}
  });
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({fillRect: vi.fn(), drawImage: vi.fn()} as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (callback, type) {callback(new Blob(['normalized'], {type}));});
});
afterEach(() => {vi.restoreAllMocks(); vi.unstubAllGlobals();});

it('prepares a phone JPEG as a smaller JPEG and releases its temporary URL', async () => {
  const photo = await galleryPhoto(new File(['original'], 'IMG_3557.jpeg', {type: 'image/jpeg'}));
  expect(photo.blob.type).toBe('image/jpeg'); expect(photo.blob.size).toBe(10);
  const canvas = vi.mocked(HTMLCanvasElement.prototype.getContext).mock.instances[0] as HTMLCanvasElement;
  expect([canvas.width, canvas.height]).toEqual([2560, 1920]);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:phone-photo');
});

it.each([['IMG_3557.jpeg', ''], ['IMG_3557.heic', 'image/heic']])('passes an undecodable phone photo to the server even above 6 MB: %s', async (name, type) => {
  canDecode = false;
  const file = new File([new Uint8Array(7 * 1024 * 1024)], name, {type});
  expect((await galleryPhoto(file)).blob).toBe(file);
  expect(URL.revokeObjectURL).toHaveBeenCalled();
});

it('accepts the 25 MB boundary and rejects larger files before decoding', async () => {
  canDecode = false;
  const limit = 25 * 1024 * 1024;
  const file = new File([new Uint8Array(limit)], 'photo.heic');
  expect((await galleryPhoto(file)).blob).toBe(file);
  vi.mocked(URL.createObjectURL).mockClear();
  await expect(galleryPhoto(new File([new Uint8Array(limit + 1)], 'photo.jpeg'))).rejects.toThrow('25 МБ');
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it('does not pass unsupported file types through the image decoder fallback', async () => {
  await expect(galleryPhoto(new File(['gif'], 'photo.gif', {type: 'image/gif'}))).rejects.toThrow('JPG, PNG, WebP или HEIC');
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});
