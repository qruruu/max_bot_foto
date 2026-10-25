import { useEffect, useRef } from 'react';
import { EditorContent, NodeViewWrapper, ReactNodeViewRenderer, useEditor, useEditorState } from '@tiptap/react';
import type { NodeViewProps } from '@tiptap/react';
import { Node, mergeAttributes } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { ArrowDown, ArrowUp, Bold, ImagePlus, Italic, Link2, List, ListOrdered, Redo2, Trash2, Undo2 } from 'lucide-react';
import type { NewsAsset, NewsNode } from './types';
import { editorAssetUrl } from './types';

function ImageBlock({node, updateAttributes, deleteNode, extension}: NodeViewProps) {
  const input = useRef<HTMLInputElement>(null);
  const attrs = node.attrs;
  return <NodeViewWrapper className="news-editor-image" contentEditable={false}>
    <img src={editorAssetUrl(attrs.asset_id)} alt={attrs.alt || ''}/>
    <div className="news-image-fields"><label>Подпись<input value={attrs.caption || ''} maxLength={500} placeholder="Куда смотреть и что получится" onChange={e => updateAttributes({caption:e.target.value})}/></label>
      <label>Описание для доступности (alt)<input value={attrs.alt || ''} maxLength={500} placeholder="Что изображено на скриншоте" onChange={e => updateAttributes({alt:e.target.value})}/></label>
      <div className="news-inline-actions"><button type="button" onClick={() => input.current?.click()}>Заменить изображение</button><button type="button" onClick={deleteNode}><Trash2 size={14}/>Убрать из статьи</button></div>
      <input type="file" hidden ref={input} accept="image/png,image/jpeg,image/webp" onChange={async e => {
        const file = e.target.files?.[0]; e.target.value = '';
        if (file) {const asset = await extension.options.upload(file); if (asset) updateAttributes({asset_id:asset.id});}
      }}/>
    </div>
  </NodeViewWrapper>;
}
const NewsImage = Node.create({
  name:'image', group:'block', atom:true, draggable:true,
  addOptions() {return {upload: async (_file:File):Promise<NewsAsset | null> => null};},
  addAttributes() {return {asset_id:{default:''}, alt:{default:''}, caption:{default:''}};},
  parseHTML() {return [{tag:'figure[data-news-image]'}];},
  renderHTML({HTMLAttributes}) {return ['figure', mergeAttributes(HTMLAttributes, {'data-news-image':''})];},
  addNodeView() {return ReactNodeViewRenderer(ImageBlock);},
});
const Important = Node.create({
  name:'important', group:'block', content:'(paragraph | bulletList | orderedList)+', defining:true,
  parseHTML() {return [{tag:'aside[data-news-important]'}];},
  renderHTML() {return ['aside', {'data-news-important':'', class:'news-important'}, 0];},
});
function ActionBlock({node, updateAttributes, deleteNode}:NodeViewProps) {
  return <NodeViewWrapper className="news-editor-action" contentEditable={false}><strong>Кнопка перехода</strong><div className="news-image-fields">
    <label>Название кнопки<input value={node.attrs.label} maxLength={100} onChange={e => updateAttributes({label:e.target.value})}/></label>
    <label>Ссылка<input value={node.attrs.href} placeholder="/photos" onChange={e => updateAttributes({href:e.target.value})}/></label></div>
    <p className="hint">Для раздела сервиса укажите /photos, /days или /review — откроется организация читателя.</p><button type="button" onClick={deleteNode}><Trash2 size={14}/>Убрать кнопку</button></NodeViewWrapper>;
}
const Action = Node.create({
  name:'action', group:'block', atom:true, draggable:true,
  addAttributes() {return {label:{default:'Открыть раздел'}, href:{default:'/photos'}};},
  parseHTML() {return [{tag:'div[data-news-action]'}];},
  renderHTML({HTMLAttributes}) {return ['div', mergeAttributes(HTMLAttributes, {'data-news-action':''})];},
  addNodeView() {return ReactNodeViewRenderer(ActionBlock);},
});

export default function RichEditor({initial, onChange, upload, onError, disabled=false}: {disabled?:boolean; initial:NewsNode; onChange:(doc:NewsNode)=>void; upload:(file:File)=>Promise<NewsAsset | null>; onError:(error:string)=>void}) {
  const latest = useRef({onChange, upload, onError}); latest.current = {onChange, upload, onError};
  const fileInput = useRef<HTMLInputElement>(null);
  const linkDialog = useRef<HTMLDialogElement>(null), linkInput = useRef<HTMLInputElement>(null);
  const editor = useEditor({
    extensions:[StarterKit.configure({heading:{levels:[2,3]}, blockquote:false, code:false, codeBlock:false, strike:false, underline:false, horizontalRule:false,
      link:{openOnClick:false, autolink:false, defaultProtocol:'https'}, trailingNode:false}),
      NewsImage.configure({upload:(file:File)=>latest.current.upload(file)}), Important, Action],
    content:initial,
    onUpdate:({editor}) => latest.current.onChange(editor.getJSON() as NewsNode),
    editorProps:{attributes:{class:'news-prose news-writing-area', 'aria-label':'Текст новости'},
      handlePaste:(_view, event) => {
        const files = [...(event.clipboardData?.files || [])].filter(f=>f.type.startsWith('image/'));
        if (!files.length) return false;
        event.preventDefault(); void insertImages(files); return true;
      },
      handleDrop:(_view, event, _slice, moved) => {
        if (moved || !event.dataTransfer?.files.length) return false;
        event.preventDefault(); void insertImages([...event.dataTransfer.files]); return true;
      },
    },
  });
  useEffect(()=>{editor?.setEditable(!disabled,false);},[editor,disabled]);
  useEditorState({editor, selector:({editor}) => editor ? {selection:editor.state.selection.from, doc:editor.state.doc, bold:editor.isActive('bold'), italic:editor.isActive('italic')} : null});
  async function insertImages(files:File[]) {
    for (const file of files) {
      const asset = await latest.current.upload(file);
      if (asset && editor && !editor.isDestroyed) insertBlock({type:'image', attrs:{asset_id:asset.id, alt:'', caption:''}});
    }
  }
  function insertBlock(block:NewsNode) {
    if (!editor) return;
    const {doc,selection}=editor.state;
    const index=Math.min(selection.$from.index(0),doc.childCount-1);
    let after=0;
    for(let i=0;i<=index;i++) after+=doc.child(i).nodeSize;
    // Adding a block must never replace the currently selected image or action.
    editor.chain().focus().insertContentAt(after,[block,{type:'paragraph'}]).run();
  }
  if (!editor) return null;
  const buttons = [
    {label:'Жирный', icon:Bold, active:editor.isActive('bold'), run:()=>editor.chain().focus().toggleBold().run()},
    {label:'Курсив', icon:Italic, active:editor.isActive('italic'), run:()=>editor.chain().focus().toggleItalic().run()},
    {label:'Маркированный список', icon:List, active:editor.isActive('bulletList'), run:()=>editor.chain().focus().toggleBulletList().run()},
    {label:'Нумерованный список', icon:ListOrdered, active:editor.isActive('orderedList'), run:()=>editor.chain().focus().toggleOrderedList().run()},
  ];
  function move(direction:number) {
    if (!editor) return;
    const {state} = editor, at = state.selection.$from;
    const index = Math.min(at.index(0), state.doc.childCount - 1);
    const target = index + direction;
    if (target < 0 || target >= state.doc.childCount) return;
    const nodes = Array.from({length:state.doc.childCount}, (_,i)=>state.doc.child(i));
    [nodes[index], nodes[target]] = [nodes[target], nodes[index]];
    const from = nodes.slice(0,target).reduce((n,node)=>n+node.nodeSize,0);
    editor.chain().setContent({type:'doc',content:nodes.map(n=>n.toJSON())}).setTextSelection(Math.min(from+1, state.doc.content.size-1)).focus().run();
  }
  return <div className="news-rich-editor">
    <div className="news-toolbar" role="toolbar" aria-label="Оформление текста">
      <select aria-label="Стиль абзаца" value={editor.isActive('heading',{level:2}) ? '2' : editor.isActive('heading',{level:3}) ? '3' : 'p'} onChange={e => e.target.value === 'p' ? editor.chain().focus().setParagraph().run() : editor.chain().focus().setHeading({level:Number(e.target.value) as 2|3}).run()}>
        <option value="p">Обычный текст</option><option value="2">Подзаголовок</option><option value="3">Малый подзаголовок</option></select>
      {buttons.map(({label,icon:Icon,active,run}) => <button key={label} type="button" title={label} aria-label={label} aria-pressed={active} onClick={run}><Icon size={17}/></button>)}
      <button type="button" title="Ссылка" aria-label="Добавить ссылку" onClick={()=>{linkDialog.current?.showModal(); if(linkInput.current) linkInput.current.value = editor.getAttributes('link').href || '';}}><Link2 size={17}/></button>
      <button type="button" onClick={()=>editor.isActive('important') ? editor.chain().focus().lift('important').run() : editor.chain().focus().wrapIn('important').run()} aria-pressed={editor.isActive('important')}>Важно</button>
      <button type="button" onClick={()=>fileInput.current?.click()}><ImagePlus size={17}/>Изображение</button>
      <button type="button" onClick={()=>insertBlock({type:'action',attrs:{label:'Открыть раздел',href:'/photos'}})}>Кнопка</button>
      <span className="news-toolbar-separator"/>
      <button type="button" title="Переместить блок выше" aria-label="Переместить блок выше" onClick={()=>move(-1)}><ArrowUp size={16}/></button>
      <button type="button" title="Переместить блок ниже" aria-label="Переместить блок ниже" onClick={()=>move(1)}><ArrowDown size={16}/></button>
      <button type="button" title="Отменить" aria-label="Отменить" disabled={!editor.can().undo()} onClick={()=>editor.chain().focus().undo().run()}><Undo2 size={16}/></button>
      <button type="button" title="Повторить" aria-label="Повторить" disabled={!editor.can().redo()} onClick={()=>editor.chain().focus().redo().run()}><Redo2 size={16}/></button>
    </div>
    <EditorContent editor={editor}/>
    <input type="file" ref={fileInput} hidden accept="image/png,image/jpeg,image/webp" multiple onChange={e=>{void insertImages([...e.target.files || []]); e.target.value='';}}/>
    <p className="news-upload-hint">PNG, JPG и WebP до 8 МБ. Можно перетащить файл или вставить скриншот из буфера. Стрелки перемещают выбранный блок.</p>
    <dialog ref={linkDialog} className="modal news-link-dialog"><form onSubmit={e=>{
      e.preventDefault(); const href = linkInput.current?.value.trim() || '';
      if (href && !/^(https?:\/\/[^\s]+|\/(?!\/|org\/)[^\s]*)$/.test(href)) {latest.current.onError('Укажите https://… или общий путь раздела, например /photos.'); return;}
      if (href) editor.chain().focus().extendMarkRange('link').setLink({href}).run(); else editor.chain().focus().unsetLink().run();
      linkDialog.current?.close();
    }}><h2>Ссылка в тексте</h2><label>Адрес<input ref={linkInput} autoFocus placeholder="https://… или /photos"/></label><p className="hint">Пустой адрес уберёт ссылку. Ссылка /photos откроет организацию читателя.</p><div className="news-inline-actions"><button type="button" onClick={()=>linkDialog.current?.close()}>Отмена</button><button className="primary">Применить</button></div></form></dialog>
  </div>;
}
