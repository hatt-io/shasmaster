import {Fragment,memo,useEffect,useMemo,useRef,type RefObject} from 'react';
import type {PageData,Word} from '../types';
import type {Layout} from './layout';
import {orderedWords} from './sourceOrder';
import {SourceActivation,copySourceSelection,selectSourceWord} from './sourceSelection';

export const SourceLetters=memo(function SourceLetters({word,scale}:{word:Word;scale:number}){
 return word.source_glyphs?.length?<>{word.source_glyphs.map((glyph,i)=><span key={i} className="source-word-text source-glyph"
  style={{left:(glyph.x-word.x)*scale,top:(glyph.baseline-glyph.size-word.top)*scale,
   fontSize:glyph.size*scale,fontFamily:glyph.font?`"source-${glyph.font}"`:undefined}}>{glyph.text}</span>)}</>:
  <span className="source-word-text" style={{position:'absolute',right:0,top:((word.baseline||word.bottom)-(word.size||12)-word.top)*scale}}>{word.text}</span>;
});

export function SourceText({data,layout,scale,selected,targets,onActivate,onSelecting,onKeyDown}:{
 data:PageData;layout:Layout;scale:number;selected:string|null;
 targets:RefObject<Map<string,HTMLElement>>;onActivate:(id:string)=>void;
 onSelecting:()=>void;onKeyDown:(event:React.KeyboardEvent,id:string)=>void;
}){
 const root=useRef<HTMLDivElement>(null);
 const callbacks=useRef({onActivate,onSelecting});callbacks.current={onActivate,onSelecting};
 const activation=useMemo(()=>new SourceActivation(id=>callbacks.current.onActivate(id),()=>{
  const selection=document.getSelection();return !!selection&&!selection.isCollapsed;
 }),[]);
 const words=useMemo(()=>orderedWords(data),[data]);
 const fontStyles=useMemo(()=>(data.geometry.fonts||[]).map(font=>
  `@font-face{font-family:"source-${font.id}";src:url("${font.url}") format("opentype");font-display:block;ascent-override:100%;descent-override:0%;line-gap-override:0%}`).join('\n'),[data.geometry.fonts]);
 useEffect(()=>{
  const changed=()=>{
   const selection=document.getSelection();
   if(selection&&!selection.isCollapsed&&(root.current?.contains(selection.anchorNode)||root.current?.contains(selection.focusNode))){
    activation.cancel();callbacks.current.onSelecting();
   }
  };
  const copy=(event:ClipboardEvent)=>{if(root.current)copySourceSelection(root.current,event)};
  const up=()=>activation.up();
  document.addEventListener('selectionchange',changed);
  document.addEventListener('copy',copy);
  window.addEventListener('pointerup',up);
  window.addEventListener('pointercancel',up);
  return()=>{activation.cancel();document.removeEventListener('selectionchange',changed);document.removeEventListener('copy',copy);window.removeEventListener('pointerup',up);window.removeEventListener('pointercancel',up)};
 },[activation]);
 return <div ref={root} className="source-text-layer" lang="he" dir="rtl"
  onPointerDown={event=>{if(event.button===0){activation.down(event.clientX,event.clientY);callbacks.current.onSelecting()}}}
  onPointerMove={event=>activation.move(event.clientX,event.clientY)}>
  <style>{fontStyles}</style>
  {words.map((word,index)=><Fragment key={word.id}><span
   ref={element=>{if(element)targets.current.set(word.id,element);else targets.current.delete(word.id)}}
   className={'source-word'+(selected===word.id?' selected':'')} role="button" tabIndex={0}
   aria-label={word.text} aria-pressed={selected===word.id} aria-controls={layout.annotations[word.id]?'translation-'+word.id:undefined}
   style={{left:(word.x+(layout.xOffsets?.[word.id]||0))*scale,top:(word.top+(layout.offsets[word.line]||0))*scale,
    width:Math.max(word.r-word.x,1)*scale,height:Math.max(word.bottom-word.top,1)*scale,
    fontSize:(word.size||12)*scale,fontFamily:word.font?`"source-${word.font}"`:undefined}}
   onClick={event=>{if(!event.shiftKey)activation.click(word.id,event.detail)}}
   onDoubleClick={event=>{event.preventDefault();activation.cancel();selectSourceWord(event.currentTarget);callbacks.current.onSelecting()}}
   onKeyDown={event=>{activation.cancel();onKeyDown(event,word.id)}}>
   <SourceLetters word={word} scale={scale}/>
  </span>{index<words.length-1?(words[index+1].line===word.line?' ':'\n'):''}</Fragment>)}
 </div>;
}
