import type { StoredPhoto } from './drafts';

export async function galleryPhoto(file: File): Promise<StoredPhoto> {
  if (!/\.(jpe?g|png|webp|hei[cf])$/i.test(file.name) && !/^image\/(jpeg|png|webp|hei[cf])$/.test(file.type)) {
    throw new Error('Выберите фотографию JPG, PNG, WebP или HEIC');
  }
  if (file.size > 25 * 1024 * 1024) throw new Error('Одна фотография должна занимать не больше 25 МБ');
  const url = URL.createObjectURL(file);
  try {
    const image = new Image(); image.src = url;
    await new Promise<void>((resolve, reject) => {image.onload = () => resolve(); image.onerror = () => reject(new Error('Не удалось открыть фотографию'));});
    const ratio = Math.min(1, 2560 / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(image.naturalWidth * ratio); canvas.height = Math.round(image.naturalHeight * ratio);
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Не удалось подготовить фотографию');
    context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height); context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(new Error('Не удалось подготовить фотографию')), 'image/jpeg', .86));
    return {id: crypto.randomUUID(), blob, preview: blob};
  } catch (error) {
    // HEIC preview support differs between browsers; the server can decode the original.
    if (/\.hei[cf]$/i.test(file.name) && file.size <= 6 * 1024 * 1024) return {id: crypto.randomUUID(), blob: file, preview: file};
    throw error;
  } finally {URL.revokeObjectURL(url);}
}
