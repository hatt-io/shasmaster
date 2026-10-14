import {useEffect,useMemo,useRef,useState} from 'react';
import type {Geometry} from '../types';
import {OriginalPagePreview} from './OriginalPagePreview';

export type Bounds={x:number;r:number;top:number;bottom:number};
type Handle='move'|'left'|'right'|'top'|'bottom'|'top-left'|'top-right'|'bottom-left'|'bottom-right'|'baseline';
const handles:Handle[]=['left','right','top','bottom','top-left','top-right','bottom-left','bottom-right'];
const ready=()=>{};

export function BoundsEditor({geometry,bounds,focusBounds,baseline,onChange}:{geometry:Geometry;bounds:Bounds;focusBounds?:Bounds;baseline?:number;onChange:(bounds:Bounds,baseline?:number)=>void}){
 const viewport=useRef<HTMLDivElement>(null),initial=useRef(focusBounds||bounds);
 const drag=useRef<{x:number;y:number;bounds:Bounds;baseline?:number;handle:Handle}|null>(null);
 const [width,setWidth]=useState(500),[zoom,setZoom]=useState(1),[error,setError]=useState('');
 useEffect(()=>{const element=viewport.current;if(!element)return;const observer=new ResizeObserver(()=>setWidth(element.clientWidth));observer.observe(element);setWidth(element.clientWidth);return()=>observer.disconnect()},[]);
 const layout=useMemo(()=>({height:geometry.height,offsets:{},annotations:{}}),[geometry]);
 const original=initial.current,centerX=(original.x+original.r)/2,centerY=(original.top+original.bottom)/2;
 const scale=Math.min(width/Math.max(80,(original.r-original.x)*1.8),180/Math.max(25,(original.bottom-original.top)*2.8))*zoom;
 const viewHeight=220,left=Math.max(0,Math.min(geometry.width-width/scale,centerX-width/scale/2)),top=Math.max(0,Math.min(geometry.height-viewHeight/scale,centerY-viewHeight/scale/2));
 function changed(handle:Handle,dx:number,dy:number,base=bounds,line=baseline){
  const next={...base};
  if(handle==='baseline'){onChange(next,Math.max(next.top,Math.min(next.bottom,(line??next.bottom)+dy)));return}
  if(handle==='move'){
   dx=Math.max(-base.x,Math.min(geometry.width-base.r,dx));dy=Math.max(-base.top,Math.min(geometry.height-base.bottom,dy));
   next.x+=dx;next.r+=dx;next.top+=dy;next.bottom+=dy;
   onChange(next,line===undefined?undefined:line+dy);return;
  }
  if(handle.includes('left'))next.x=Math.max(0,Math.min(base.r-.5,base.x+dx));
  if(handle.includes('right'))next.r=Math.min(geometry.width,Math.max(base.x+.5,base.r+dx));
  if(handle.includes('top'))next.top=Math.max(0,Math.min(base.bottom-.5,base.top+dy));
  if(handle.includes('bottom'))next.bottom=Math.min(geometry.height,Math.max(base.top+.5,base.bottom+dy));
  onChange(next,line===undefined?undefined:Math.max(next.top,Math.min(next.bottom,line)));
 }
 function down(event:React.PointerEvent<HTMLButtonElement>,handle:Handle){
  if(event.button!==0)return;event.preventDefault();event.stopPropagation();event.currentTarget.focus();event.currentTarget.setPointerCapture(event.pointerId);
  drag.current={x:event.clientX,y:event.clientY,bounds,baseline,handle};
 }
 function move(event:React.PointerEvent<HTMLButtonElement>){const origin=drag.current;if(origin)changed(origin.handle,(event.clientX-origin.x)/scale,(event.clientY-origin.y)/scale,origin.bounds,origin.baseline)}
 function up(event:React.PointerEvent<HTMLButtonElement>){drag.current=null;if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId)}
 function key(event:React.KeyboardEvent,handle:Handle){
  const delta=({ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]} as Record<string,number[]>)[event.key];if(!delta)return;
  event.preventDefault();const step=(event.shiftKey?10:1)/scale;changed(handle,delta[0]*step,delta[1]*step);
 }
 function control(handle:Handle,label:string){return <button key={handle} type="button" className={'bounds-handle handle-'+handle} aria-label={label} title={label} onPointerDown={event=>down(event,handle)} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onKeyDown={event=>key(event,handle)}/>}
 return <div className="bounds-editor">
  <div className="bounds-toolbar"><button type="button" onClick={()=>setZoom(value=>Math.max(.5,value-.25))} disabled={zoom<=.5}>− Zoom out</button><button type="button" onClick={()=>setZoom(value=>Math.min(4,value+.25))} disabled={zoom>=4}>+ Zoom in</button></div>
  <div ref={viewport} className="bounds-viewport" style={{height:viewHeight}}>
   <div className="bounds-sheet" style={{left:-left*scale,top:-top*scale,width:geometry.width*scale,height:geometry.height*scale}}>
    <OriginalPagePreview geometry={geometry} layout={layout} scale={scale} onReady={ready} onError={setError}/>
    <div className="bounds-selection" style={{left:bounds.x*scale,top:bounds.top*scale,width:(bounds.r-bounds.x)*scale,height:(bounds.bottom-bounds.top)*scale}}>
     {control('move','Move selection')}{handles.map(handle=>control(handle,'Resize '+handle.replace('-',' ')+' edge'))}
     {baseline!==undefined&&<div className="bounds-baseline" style={{top:(baseline-bounds.top)*scale}}>{control('baseline','Move baseline')}</div>}
    </div>
   </div>
  </div>
  {error&&<p className="error-message" role="alert">{error}</p>}
 </div>;
}
