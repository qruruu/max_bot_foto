import { expect, it } from 'vitest';
import { companyFolders } from './diskFolders';

it('keeps all company destinations distinct and under the chosen company name', () => {
  expect(companyFolders('  MAX_ФОТО_СТРОЙДВОР  ')).toEqual({
    photo_root:'MAX_ФОТО_СТРОЙДВОР',training_root:'MAX_ФОТО_СТРОЙДВОР_TRAINING',
    spam_root:'MAX_ФОТО_СТРОЙДВОР_SPAM',exchange_root:'MAX_ФОТО_СТРОЙДВОР_ARM_EXCHANGE',
  });
  const first=Object.values(companyFolders('Компания А')), second=Object.values(companyFolders('Компания Б'));
  expect(new Set([...first,...second]).size).toBe(8);
});
