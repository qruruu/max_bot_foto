import { ApiError } from '../api';
import type { NewsArticle, NewsSnapshot } from './types';
export type SaveNews = (id:string, snapshot:NewsSnapshot, version:number)=>Promise<NewsArticle>;

/** Serialize autosaves and publish barriers; never let an old response replace new typing. */
export class DraftSession {
  article:NewsArticle;
  draft:NewsSnapshot;
  saved:string;
  pending:Promise<void> | null = null;
  error = '';
  conflict = false;
  private listeners = new Set<()=>void>();
  constructor(article:NewsArticle, private save:SaveNews) {this.article=article; this.draft=article.draft; this.saved=JSON.stringify(article.draft);}
  subscribe(listener:()=>void) {this.listeners.add(listener); return ()=>{this.listeners.delete(listener);};}
  emit() {for(const listener of this.listeners) listener();}
  get dirty() {return JSON.stringify(this.draft)!==this.saved;}
  edit(draft:NewsSnapshot) {this.draft=draft; if(!this.conflict) this.error=''; this.emit();}
  flush():Promise<void> {
    if(this.conflict) return Promise.reject(new Error(this.error));
    if(this.pending) return this.pending;
    this.pending=this.saveLoop().finally(()=>{this.pending=null; this.emit();});
    this.emit(); return this.pending;
  }
  private async saveLoop() {
    while(this.dirty) {
      const snapshot=structuredClone(this.draft), fingerprint=JSON.stringify(snapshot);
      try {
        const saved=await this.save(this.article.id,snapshot,this.article.version);
        this.article=saved; this.saved=fingerprint; this.error=''; this.emit();
      } catch(error) {
        this.error=(error as Error).message; this.conflict=error instanceof ApiError && error.status===409;
        this.emit(); throw error;
      }
    }
  }
  accept(article:NewsArticle) {this.article=article; this.draft=article.draft; this.saved=JSON.stringify(article.draft); this.error=''; this.conflict=false; this.emit();}
}
