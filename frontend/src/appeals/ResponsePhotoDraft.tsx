import { createContext, useContext, useRef } from 'react';
import type { ReactNode, RefObject } from 'react';

export type ClosePhoto = {id: string | number; url: string; source: 'chat' | 'general'};
export type ResponsePhotoDraft = {
  appealId: number;
  version: number;
  decision: string;
  answer: string;
  files: File[];
  operatorPhotos: string[];
  sourcePhotos: ClosePhoto[];
};

const Context = createContext<RefObject<ResponsePhotoDraft | null> | null>(null);

export function ResponsePhotoDraftProvider({children}: {children: ReactNode}) {
  const draft = useRef<ResponsePhotoDraft | null>(null);
  return <Context.Provider value={draft}>{children}</Context.Provider>;
}

export const useResponsePhotoDraft = () => useContext(Context);
