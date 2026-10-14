import {useLayoutEffect,useRef,useState,type RefObject} from 'react';
import type {Layout} from './layout';

type Position={left:number;top:number;width:number;maxHeight:number;visibility:'visible'|'hidden'};
type Targets<T> = RefObject<Map<string,T>>;
const gap=5,margin=8;

export function useWordPopover(open:boolean,selected:string|null,buttons:Targets<HTMLElement>,inputs:Targets<HTMLDivElement>,layout:Layout,scale:number){
 const menu=useRef<HTMLDivElement>(null),reposition=useRef<(()=>void)|null>(null);
 const [position,setPosition]=useState<Position>({left:0,top:0,width:200,maxHeight:280,visibility:'hidden'});
 useLayoutEffect(()=>{
  if(!open||!selected||!menu.current)return;
  const popup=menu.current,word=buttons.current.get(selected);
  if(!word)return;
  const editor=inputs.current.get(selected)||word;
  let frame=0;
  const place=()=>{
   const viewport=window.visualViewport;
   const left=(viewport?.offsetLeft||0)+margin,right=left+(viewport?.width||innerWidth)-2*margin;
   const header=document.querySelector('header[data-reader-header]')?.getBoundingClientRect().bottom||0;
   const top=Math.max((viewport?.offsetTop||0)+margin,header+margin),bottom=(viewport?.offsetTop||0)+(viewport?.height||innerHeight)-margin;
   const width=Math.max(1,Math.min(200,right-left)),source=word.getBoundingClientRect(),text=editor.getBoundingClientRect();
   const visible=(rect:DOMRect)=>rect.right>left&&rect.left<right&&rect.bottom>top&&rect.top<bottom;
   const editing=popup.contains(document.activeElement);
   if(bottom<=top||!editing&&!visible(source)&&!visible(text)){
    setPosition(previous=>previous.visibility==='hidden'?previous:{...previous,visibility:'hidden'});return;
   }
   const list=popup.querySelector<HTMLElement>('.suggestion-list');
   const wanted=Math.min(bottom-top,(list?Math.min(235,list.scrollHeight)+popup.offsetHeight-list.clientHeight:popup.scrollHeight));
   const below=Math.max(0,bottom-Math.max(source.bottom,text.bottom)-gap),above=Math.max(0,source.top-gap-top);
   let x=(source.left+source.right-width)/2,y=0,available=0;
   if(below>=wanted||below>=above){available=below;y=Math.max(source.bottom,text.bottom)+gap}
   else{available=above;y=source.top-gap-Math.min(wanted,available)}
   if(available<wanted){
    const besideLeft=Math.min(source.left,text.left)-gap-width,besideRight=Math.max(source.right,text.right)+gap;
    if(besideLeft>=left||besideRight+width<=right){
     x=besideLeft>=left?besideLeft:besideRight;available=Math.max(0,bottom-top);y=Math.max(top,Math.min(source.top,bottom-wanted));
    }
   }
   // A narrow viewport may have no free side; retain a scrollable choice list.
   if(available<60){available=Math.max(1,bottom-top);y=Math.max(top,Math.min(source.bottom+gap,bottom-wanted))}
   const next:Position={left:Math.max(left,Math.min(right-width,x)),top:Math.max(top,Math.min(bottom-Math.min(wanted,available),y)),width,maxHeight:Math.max(1,available),visibility:'visible'};
   setPosition(previous=>Object.keys(next).every(key=>previous[key as keyof Position]===next[key as keyof Position])?previous:next);
  };
  const schedule=()=>{if(!frame)frame=requestAnimationFrame(()=>{frame=0;place()})};
  const resized=new ResizeObserver(schedule);resized.observe(popup);resized.observe(editor);resized.observe(word);
  reposition.current=place;place();
  window.addEventListener('scroll',schedule,true);window.addEventListener('resize',schedule);
  window.visualViewport?.addEventListener('resize',schedule);window.visualViewport?.addEventListener('scroll',schedule);
  return()=>{reposition.current=null;cancelAnimationFrame(frame);resized.disconnect();window.removeEventListener('scroll',schedule,true);window.removeEventListener('resize',schedule);window.visualViewport?.removeEventListener('resize',schedule);window.visualViewport?.removeEventListener('scroll',schedule)};
 },[open,selected,buttons,inputs,!!(selected&&layout.annotations[selected])]);
 useLayoutEffect(()=>{reposition.current?.()},[layout,scale]);
 return {menu,position};
}
