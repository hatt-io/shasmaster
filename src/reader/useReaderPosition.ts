import {useEffect,useLayoutEffect,useRef,type RefObject} from 'react';
import type {Geometry,Word} from '../types';
import type {ReaderDestination,ReaderPosition} from '../navigation';
import type {Layout} from './layout';

type Props={geometry:Geometry;layout:Layout;ready:boolean;scale:number;zoom:number;selected:string|null;destination:ReaderDestination;host:RefObject<HTMLDivElement|null>;scroller:RefObject<HTMLDivElement|null>;onPosition:(position:ReaderPosition)=>void};
export function useReaderPosition(props:Props){
 const current=useRef(props);current.current=props;
 const restored=useRef<number|null>(null),focus=useRef<{id:string;x:number;y:number;sourceY:number;scale:number;visible:boolean}|null>(null);
 const pendingSelection=useRef<string|null|undefined>(undefined);
 function point(word:Word){const p=current.current;return {x:(word.x+word.r)/2+(p.layout.xOffsets?.[word.id]||0),y:word.top+(p.layout.offsets[word.line]||0)}}
 function rememberFocus(){
  const p=current.current,rect=p.host.current?.getBoundingClientRect();
  if(!rect){focus.current=null;return}
  let word=p.geometry.words.find(w=>w.id===p.selected);
  if(!word){
   const viewport=p.scroller.current?.getBoundingClientRect();
   const cx=(viewport?.left||0)+(viewport?.width||innerWidth)/2,cy=(viewport?.top||0)+(viewport?.height||innerHeight)/2;
   let best=Infinity;
   for(const candidate of p.geometry.words){const source=point(candidate),distance=Math.hypot(rect.left+source.x*p.scale-cx,rect.top+source.y*p.scale-cy);if(distance<best){best=distance;word=candidate}}
  }
  if(!word){focus.current=null;return}
  const source=point(word),x=rect.left+source.x*p.scale,y=rect.top+source.y*p.scale;
  const viewport=window.visualViewport,left=viewport?.offsetLeft||0,top=viewport?.offsetTop||0;
  focus.current={id:word.id,x,y,sourceY:source.y,scale:p.scale,visible:y>=top&&y<top+(viewport?.height||innerHeight)&&x>=left&&x<left+(viewport?.width||innerWidth)};
 }
 function keepEditorVisible(){
  const p=current.current,word=p.geometry.words.find(w=>w.id===p.selected),rect=p.host.current?.getBoundingClientRect();
  if(!word||!rect||!(document.activeElement instanceof HTMLTextAreaElement)||!p.host.current?.contains(document.activeElement))return;
  const viewport=window.visualViewport,header=document.querySelector('header[data-reader-header]')?.getBoundingClientRect().bottom||0;
  const top=Math.max(viewport?.offsetTop||0,header)+12,bottom=(viewport?.offsetTop||0)+(viewport?.height||innerHeight)-12;
  if(bottom<=top)return;
  const source=point(word),annotation=p.layout.annotations[word.id],y=rect.top+source.y*p.scale;
  const edge=annotation?annotation.y+Math.min(annotation.height,annotation.fontSize*1.25):word.bottom+(p.layout.offsets[word.line]||0);
  const height=(edge-source.y)*p.scale;
  const shift=y<top?y-top:y+height>bottom?y-Math.max(top,bottom-height):0;
  if(shift)p.scroller.current?.scrollBy({top:shift,behavior:'instant'});
 }
 function capture(){
  const p=current.current,rect=p.host.current?.getBoundingClientRect();if(!p.ready||restored.current!==p.destination.serial||!rect)return;
  if(pendingSelection.current!==undefined&&pendingSelection.current!==p.selected)return;
  pendingSelection.current=undefined;
  const header=document.querySelector('header[data-reader-header]')?.getBoundingClientRect().bottom||50;
  let nearest:Word|undefined,best=Infinity;
  for(const word of p.geometry.words){const source=point(word),x=rect.left+source.x*p.scale,y=rect.top+source.y*p.scale;if(x<0||x>innerWidth)continue;const score=Math.abs(y-header-20)+Math.abs(x-innerWidth/2)*.025;if(score<best){best=score;nearest=word}}
  if(!nearest)return;
  const source=point(nearest);
  p.onPosition({page_id:p.geometry.id,selected_word:p.selected,anchor_word:nearest.id,anchor_line:nearest.line,source_x:source.x,source_y:nearest.top,viewport_x:(rect.left+source.x*p.scale)/innerWidth,viewport_y:(rect.top+source.y*p.scale)/innerHeight,zoom:p.zoom,updated_at:0});
 }
 useLayoutEffect(()=>{
  const p=current.current;if(!p.ready||!p.host.current||!p.scroller.current||restored.current===p.destination.serial)return;
  const saved=p.destination.position,requested=p.destination.word_id;let x=0,y=0,viewportX=.5,viewportY=.35,hasTarget=false;
  const word=p.geometry.words.find(w=>w.id===(saved?.anchor_word||requested));
  if(word){const source=point(word);x=source.x;y=source.y;hasTarget=true}
  else if(saved){
   const line=p.geometry.lines.find(l=>l.id===saved.anchor_line);
   if(line){x=saved.source_x;y=line.top+(p.layout.offsets[line.id]||0);hasTarget=true}
   else if(p.geometry.words.length){const nearest=p.geometry.words.reduce((best,w)=>Math.hypot(w.x-saved.source_x,w.top-saved.source_y)<Math.hypot(best.x-saved.source_x,best.top-saved.source_y)?w:best);const source=point(nearest);x=source.x;y=source.y;hasTarget=true}
  }
  if(saved){viewportX=Math.max(.03,Math.min(.97,saved.viewport_x));viewportY=Math.max(.08,Math.min(.9,saved.viewport_y))}
  restored.current=p.destination.serial;focus.current=null;
  const selection=saved?.selected_word||requested||null;
  pendingSelection.current=p.geometry.words.some(word=>word.id===selection)?selection:null;
  if(hasTarget){const rect=p.host.current.getBoundingClientRect();p.scroller.current.scrollLeft+=rect.left+x*p.scale-innerWidth*viewportX;p.scroller.current.scrollTop+=rect.top+y*p.scale-innerHeight*viewportY}
  else if(!saved&&!requested){p.scroller.current.scrollLeft=0;p.scroller.current.scrollTop=0}
  rememberFocus();capture();
 },[props.ready,props.destination.serial,props.layout,props.scale]);
 useLayoutEffect(()=>{
  const p=current.current,previous=focus.current,word=p.geometry.words.find(w=>w.id===(p.selected||previous?.id)),rect=p.host.current?.getBoundingClientRect();
  if(previous&&word&&rect&&p.scroller.current&&previous.id===word.id&&previous.visible){
   const source=point(word);
   if(previous.scale!==p.scale||previous.sourceY!==source.y){p.scroller.current.scrollLeft+=rect.left+source.x*p.scale-previous.x;p.scroller.current.scrollTop+=rect.top+source.y*p.scale-previous.y}
  }
  rememberFocus();capture();
 },[props.layout,props.scale,props.selected,props.ready]);
 useEffect(()=>{
  let timer:ReturnType<typeof setTimeout>|undefined;
  const schedule=()=>{rememberFocus();if(!timer)timer=setTimeout(()=>{timer=undefined;capture()},100)};
  const viewportResize=()=>{keepEditorVisible();schedule()};
  const scroll=(event:Event)=>{if(event.target===document||event.target===window||event.target===current.current.scroller.current)schedule()};
  const interrupt=()=>{if(!current.current.ready)restored.current=current.current.destination.serial};
  const hide=()=>capture();
  window.addEventListener('scroll',scroll,true);window.addEventListener('resize',schedule);window.addEventListener('wheel',interrupt,{passive:true});window.addEventListener('pagehide',hide);
  window.visualViewport?.addEventListener('resize',viewportResize);
  return()=>{clearTimeout(timer);window.removeEventListener('scroll',scroll,true);window.removeEventListener('resize',schedule);window.removeEventListener('wheel',interrupt);window.removeEventListener('pagehide',hide);window.visualViewport?.removeEventListener('resize',viewportResize)};
 },[]);
}
