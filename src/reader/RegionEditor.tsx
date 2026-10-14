import {useEffect,useMemo,useRef,useState} from 'react';
import type {Line,PageData,Word} from '../types';
import {OriginalPagePreview} from './OriginalPagePreview';
import {BoundsEditor} from './BoundsEditor';

export type RegionEdit={id?:string;lines:string[];kind:string;bounds:number[];reading_order:number;base_regions:Record<string,string>};
type Point={x:number;y:number};
const names=['unclassified','gemara','mishnah','rashi','tosafos','heading','margin','reference'];
function boundsOf(lines:Line[]){return [Math.min(...lines.map(l=>l.x)),Math.min(...lines.map(l=>l.top)),Math.max(...lines.map(l=>l.r)),Math.max(...lines.map(l=>l.bottom))]}
function boundFields(bounds:number[]){return {x:String(bounds[0]),top:String(bounds[1]),r:String(bounds[2]),bottom:String(bounds[3])}}

export function RegionEditor({data,word,onChange,initialKind}:{data:PageData;word:Word;onChange:(value:RegionEdit|null)=>void;initialKind?:string}){
 const geometry=data.geometry,original=geometry.regions.find(r=>r.id===word.region)!;
 const [target,setTarget]=useState(original.id),[selected,setSelected]=useState(()=>new Set(geometry.lines.filter(l=>l.region===original.id).map(l=>l.id)));
 const [kind,setKind]=useState(initialKind??original.kind),[order,setOrder]=useState(String(original.reading_order)),[bounds,setBounds]=useState(()=>boundFields(original.bounds));
 const [zoom,setZoom]=useState(1),[width,setWidth]=useState(520),[remove,setRemove]=useState(false),[drag,setDrag]=useState<[Point,Point]|null>(null),[error,setError]=useState(''),[adjustBounds,setAdjustBounds]=useState(false);
 const viewport=useRef<HTMLDivElement>(null),sheet=useRef<HTMLDivElement>(null),positioned=useRef(false),start=useRef<{point:Point;line?:string;remove:boolean}|null>(null);
 const scale=width/geometry.width*zoom;
 const layout=useMemo(()=>({height:geometry.height,offsets:{},annotations:{}}),[geometry]);
 function ready(){const element=viewport.current;if(!element||positioned.current)return;positioned.current=true;element.scrollTo({left:Math.max(0,(word.x+word.r)/2*scale-element.clientWidth/2),top:Math.max(0,(word.top+word.bottom)/2*scale-element.clientHeight/2)})}
 const words=useMemo(()=>new Map(geometry.words.map(w=>[w.id,w])),[geometry]);
 const lineText=useMemo(()=>new Map(geometry.lines.map(line=>[line.id,[...line.words].sort((a,b)=>(words.get(b)?.x||0)-(words.get(a)?.x||0)).map(id=>words.get(id)?.text||'').join(' ')])),[geometry,words]);
 const regionText=useMemo(()=>new Map(geometry.regions.map(region=>[region.id,geometry.lines.filter(l=>l.region===region.id).sort((a,b)=>a.reading_order-b.reading_order).map(l=>lineText.get(l.id)).join(' ').slice(0,60)])),[geometry,lineText]);
 useEffect(()=>{const element=viewport.current;if(!element)return;const resize=new ResizeObserver(()=>setWidth(element.clientWidth));resize.observe(element);setWidth(element.clientWidth);return()=>resize.disconnect()},[]);
 useEffect(()=>{
  const numbers=[bounds.x,bounds.top,bounds.r,bounds.bottom,order];
  if(!selected.size||!kind.trim()||numbers.some(n=>!n.trim()||!Number.isFinite(Number(n)))){onChange(null);return}
  onChange({...(target?{id:target}:{}),lines:[...selected],kind:kind.trim(),bounds:[bounds.x,bounds.top,bounds.r,bounds.bottom].map(Number),reading_order:Number(order),base_regions:Object.fromEntries(geometry.lines.filter(l=>selected.has(l.id)||l.region===target).map(l=>[l.id,l.region]))});
 },[target,selected,kind,bounds,order,geometry,onChange]);
 function select(ids:Set<string>){setSelected(ids);if(ids.size)setBounds(boundFields(boundsOf(geometry.lines.filter(l=>ids.has(l.id)))))}
 function toggle(id:string){const ids=new Set(selected);if(ids.has(id))ids.delete(id);else ids.add(id);select(ids)}
 function choose(id:string){
  setTarget(id);setDrag(null);start.current=null;
  const region=geometry.regions.find(r=>r.id===id);
  if(region){setSelected(new Set(geometry.lines.filter(l=>l.region===id).map(l=>l.id)));setKind(region.kind);setOrder(String(region.reading_order));setBounds(boundFields(region.bounds))}
  else{const line=geometry.lines.find(l=>l.id===word.line)!;setSelected(new Set([line.id]));setKind(initialKind??original.kind);setOrder(String(original.reading_order));setBounds(boundFields(boundsOf([line])))}
 }
 function point(event:React.PointerEvent):Point{const box=sheet.current!.getBoundingClientRect();return {x:Math.max(0,Math.min(geometry.width,(event.clientX-box.left)/scale)),y:Math.max(0,Math.min(geometry.height,(event.clientY-box.top)/scale))}}
 function down(event:React.PointerEvent<HTMLDivElement>){
  if(event.button!==0)return;event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);
  const position=point(event),line=(event.target as HTMLElement).closest<HTMLElement>('[data-source-line]')?.dataset.sourceLine;
  start.current={point:position,line,remove:remove||event.shiftKey};setDrag([position,position]);
 }
 function up(event:React.PointerEvent<HTMLDivElement>){
  const origin=start.current;if(!origin)return;
  const end=point(event);start.current=null;setDrag(null);event.currentTarget.releasePointerCapture(event.pointerId);
  if(Math.hypot(end.x-origin.point.x,end.y-origin.point.y)*scale<4){if(origin.line)toggle(origin.line);return}
  const left=Math.min(origin.point.x,end.x),right=Math.max(origin.point.x,end.x),top=Math.min(origin.point.y,end.y),bottom=Math.max(origin.point.y,end.y);
  const ids=new Set(selected);
  for(const line of geometry.lines){const x=(line.x+line.r)/2,y=(line.top+line.bottom)/2;if(x>=left&&x<=right&&y>=top&&y<=bottom){if(origin.remove)ids.delete(line.id);else ids.add(line.id)}}
  select(ids);
 }
 return <div className="source-regions">
  <div className="region-controls"><select aria-label="Source region" value={target} onChange={e=>choose(e.target.value)}><option value="">New region</option>{[...geometry.regions].sort((a,b)=>a.reading_order-b.reading_order).map(r=><option key={r.id} value={r.id}>{r.kind} · {regionText.get(r.id)}</option>)}</select><button type="button" aria-label="New region" title="New region" onClick={()=>choose('')}>New region</button></div>
  <div className="region-controls"><button type="button" aria-label="Add fragments" title="Add fragments" aria-pressed={!remove} onClick={()=>setRemove(false)}>Add lines</button><button type="button" aria-label="Remove fragments" title="Remove fragments" aria-pressed={remove} onClick={()=>setRemove(true)}>Remove lines</button><button type="button" aria-label="Zoom out" onClick={()=>setZoom(z=>Math.max(.75,z-.25))} disabled={zoom<=.75}>− Zoom out</button><button type="button" aria-label="Zoom in" onClick={()=>setZoom(z=>Math.min(4,z+.25))} disabled={zoom>=4}>+ Zoom in</button></div>
  <div className="region-viewport" ref={viewport}><div className="region-sheet" ref={sheet} style={{width:geometry.width*scale,height:geometry.height*scale}} onPointerDown={down} onPointerMove={e=>{if(start.current)setDrag([start.current.point,point(e)])}} onPointerUp={up} onPointerCancel={()=>{start.current=null;setDrag(null)}}>
   <OriginalPagePreview geometry={geometry} layout={layout} scale={scale} onReady={ready} onError={setError}/>
   {geometry.lines.map(line=><button key={line.id} type="button" data-source-line={line.id} className={'region-fragment'+(selected.has(line.id)?' chosen':'')} style={{left:line.x*scale,top:line.top*scale,width:Math.max(1,line.r-line.x)*scale,height:Math.max(1,line.bottom-line.top)*scale}} aria-label={lineText.get(line.id)} aria-pressed={selected.has(line.id)} onClick={e=>{if(e.detail===0)toggle(line.id)}}/>)}
   {Number(bounds.r)>Number(bounds.x)&&Number(bounds.bottom)>Number(bounds.top)&&<div className="region-bounds" style={{left:Number(bounds.x)*scale,top:Number(bounds.top)*scale,width:(Number(bounds.r)-Number(bounds.x))*scale,height:(Number(bounds.bottom)-Number(bounds.top))*scale}}/>}
   {drag&&<div className="region-drag" style={{left:Math.min(drag[0].x,drag[1].x)*scale,top:Math.min(drag[0].y,drag[1].y)*scale,width:Math.abs(drag[1].x-drag[0].x)*scale,height:Math.abs(drag[1].y-drag[0].y)*scale}}/>}
  </div></div>
  <label className="field"><span>Type</span><input list="source-region-types" value={kind} maxLength={120} onChange={e=>setKind(e.target.value)}/><datalist id="source-region-types">{names.map(name=><option key={name} value={name}/>)}</datalist></label>
  <button type="button" aria-expanded={adjustBounds} onClick={()=>setAdjustBounds(value=>!value)}>Adjust outline</button>
  {adjustBounds&&<BoundsEditor key={target} geometry={geometry} bounds={{x:Number(bounds.x),r:Number(bounds.r),top:Number(bounds.top),bottom:Number(bounds.bottom)}} onChange={value=>setBounds(boundFields([value.x,value.top,value.r,value.bottom]))}/>}
  {error&&<p className="error-message" role="alert">{error}</p>}
 </div>;
}
