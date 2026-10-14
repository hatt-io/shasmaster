import {useEffect,useRef} from 'react';
import type {Geometry} from '../types';
import type {Layout} from './layout';
import {SourceLetters} from './SourceText';

// Correction overlays use the same prepared text and fonts as the reader.
export function OriginalPagePreview({geometry,scale,onReady,onError}:{
 geometry:Geometry;layout:Layout;scale:number;onReady:()=>void;onError:(message:string)=>void;
}){
 const callbacks=useRef({onReady,onError});callbacks.current={onReady,onError};
 useEffect(()=>{
  let cancelled=false;
  void Promise.all((geometry.fonts||[]).map(font=>document.fonts.load(`12px "source-${font.id}"`)))
   .then(()=>{if(!cancelled)callbacks.current.onReady()})
   .catch(error=>{if(!cancelled)callbacks.current.onError(String(error))});
  return()=>{cancelled=true};
 },[geometry,scale]);
 return <div aria-hidden="true" style={{position:'absolute',inset:0,width:geometry.width*scale,height:geometry.height*scale,pointerEvents:'none'}}>
  <style>{(geometry.fonts||[]).map(font=>`@font-face{font-family:"source-${font.id}";src:url("${font.url}") format("opentype");ascent-override:100%;descent-override:0%;line-gap-override:0%}`).join('\n')}</style>
  {geometry.words.map(word=><span key={word.id} className="source-word" style={{position:'absolute',left:word.x*scale,top:word.top*scale,
   width:(word.r-word.x)*scale,height:(word.bottom-word.top)*scale,fontSize:(word.size||12)*scale,
   fontFamily:word.font?`"source-${word.font}"`:undefined}}><SourceLetters word={word} scale={scale}/></span>)}
 </div>;
}
