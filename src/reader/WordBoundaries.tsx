import {useEffect,useMemo,useState} from 'react';
import {api} from '../api';
import type {PageData,Word} from '../types';

type Glyph={x:number;r:number;ink_x?:number;ink_r?:number;text:string};
type Source=Word&{glyphs?:Glyph[]};
export type BoundaryEdit={id:string;words:string[];cuts:number[];texts:string[];anchors:Record<string,number|null>};
export function WordBoundaries({data,word,onChange}:{data:PageData;word:Word;onChange:(edit:BoundaryEdit|null)=>void}){
 const [source,setSource]=useState<Source[]>([]),[range,setRange]=useState<[number,number]>([0,0]),[cuts,setCuts]=useState<number[]>([]),[texts,setTexts]=useState<string[]>([word.text]),[anchors,setAnchors]=useState<Record<string,number|null>>({[word.id]:0}),[error,setError]=useState('');
 useEffect(()=>{const controller=new AbortController();api<Source[]>('/pages/'+data.page.id+'/source?line_id='+encodeURIComponent(word.line)+'&revision='+encodeURIComponent(data.geometry.revision),{signal:controller.signal}).then(items=>{items.sort((a,b)=>b.x-a.x);const index=items.findIndex(item=>item.id===word.id);setSource(items);setRange([index,index])}).catch(e=>{if(!controller.signal.aborted)setError(String(e))});return()=>controller.abort()},[data.page.id,data.geometry.revision,word.id,word.line]);
 const selected=useMemo(()=>source.slice(range[0],range[1]+1),[source,range]);
 const left=selected.length?Math.min(...selected.map(w=>w.x)):word.x,right=selected.length?Math.max(...selected.map(w=>w.r)):word.r;
 const imageLeft=Math.max(0,left-.6),imageRight=Math.min(data.geometry.width,right+.6);
 const parts=useMemo(()=>{const edges=[left,...cuts,right];return edges.slice(0,-1).map((x,i)=>({x,r:edges[i+1]})).reverse()},[left,right,cuts]);
 useEffect(()=>{onChange(selected.length?{id:word.id,words:selected.map(w=>w.id),cuts,texts,anchors}:null)},[word.id,selected,cuts,texts,anchors,onChange]);
 function infer(x:number,r:number):string {
  const pieces:string[]=[];
  for(const w of selected){
   if(w.r<=x||w.x>=r)continue;
   if(w.x>=x&&w.r<=r){pieces.push(w.text);continue}
   const glyphs=[...(w.glyphs||[])].sort((a,b)=>a.x-b.x);
   if(!glyphs.length)return '';
   const logical=/[א-ת]/.test(w.text)?[...glyphs].reverse():glyphs;
   if(logical.map(g=>g.text).join('')!==w.text)return '';
   pieces.push(logical.filter(g=>{const center=((g.ink_x??g.x)+(g.ink_r??g.r))/2;return center>=x&&(center<r||r===right&&center<=r)}).map(g=>g.text).join(''));
  }
  return pieces.join('');
 }
 function partition(next:number[]){
  next.sort((a,b)=>a-b);const edges=[left,...next,right],nextParts=edges.slice(0,-1).map((x,i)=>({x,r:edges[i+1]})).reverse();
  setTexts(nextParts.map(part=>{const identical=parts.findIndex(p=>p.x===part.x&&p.r===part.r);if(identical>=0)return texts[identical];const contained=parts.map((p,index)=>({...p,index})).filter(p=>p.x>=part.x&&p.r<=part.r);if(contained.length&&contained.at(-1)!.x===part.x&&contained[0].r===part.r)return contained.map(p=>texts[p.index]).join('');return infer(part.x,part.r)}));
  setAnchors(Object.fromEntries(selected.map(w=>{const index=nextParts.findIndex(p=>w.x>=p.x&&w.r<=p.r);return [w.id,index<0?null:index]})));
  setCuts(next);
 }
 function addBoundary(event:React.PointerEvent<HTMLDivElement>){
  if(!source.length||event.target instanceof HTMLButtonElement)return;
  const bounds=event.currentTarget.getBoundingClientRect();const x=imageLeft+(event.clientX-bounds.left)/bounds.width*(imageRight-imageLeft);
  if(x<=left||x>=right||cuts.some(cut=>Math.abs(cut-x)<.15))return;
  partition([...cuts,Math.round(x*1000)/1000]);
 }
 function extend(side:'left'|'right'){
  const next: [number,number]=side==='right'?[range[0]-1,range[1]]:[range[0],range[1]+1];
  if(next[0]<0||next[1]>=source.length)return;
  const neighbor=source[side==='right'?next[0]:next[1]];
  if(neighbor.region!==word.region)return;
  const combined=texts.join('');setRange(next);setCuts([]);setTexts([side==='right'?neighbor.text+combined:combined+neighbor.text]);
  setAnchors(Object.fromEntries(source.slice(next[0],next[1]+1).map(w=>[w.id,0])));
 }
 const image='/api/pages/'+data.page.id+'/source/'+encodeURIComponent(word.id)+'/image?include='+encodeURIComponent(selected.map(w=>w.id).join(','))+'&revision='+encodeURIComponent(data.geometry.revision);
 return <div className="boundary-editor">
  <div className="settings-row"><button type="button" aria-label="Include left fragment" disabled={range[1]>=source.length-1||source[range[1]+1]?.region!==word.region} onClick={()=>extend('left')}>←</button><button type="button" aria-label="Include right fragment" disabled={range[0]<=0||source[range[0]-1]?.region!==word.region} onClick={()=>extend('right')}>→</button><button type="button" disabled={!cuts.length} onClick={()=>partition([])}>Join</button></div>
  <div className="boundary-preview" onPointerDown={addBoundary}>
   <img src={image} alt={selected.map(w=>w.text).join(' ')} draggable={false}/>
   {cuts.map((cut,index)=><button key={cut} type="button" className="boundary-cut" style={{left:(cut-imageLeft)/(imageRight-imageLeft)*100+'%'}} aria-label={'Remove boundary '+(index+1)} onPointerDown={e=>e.stopPropagation()} onClick={()=>partition(cuts.filter(value=>value!==cut))}/>)}
  </div>
  <div className="boundary-texts" dir="rtl">{parts.map((part,index)=><label key={index} style={{flex:part.r-part.x}}><input required dir="rtl" value={texts[index]||''} aria-label={'Source word '+(index+1)} onChange={e=>setTexts(values=>values.map((text,i)=>i===index?e.target.value:text))}/></label>)}</div>
  {selected.map(w=><label className="field" key={w.id}><span dir="rtl">{w.text}</span><select aria-label={'Translation attachment: '+w.text} value={anchors[w.id]??''} onChange={e=>setAnchors(values=>({...values,[w.id]:e.target.value===''?null:Number(e.target.value)}))}><option value="">—</option>{texts.map((text,index)=><option key={index} value={index}>{text||index+1}</option>)}</select></label>)}
  {error&&<p className="error-message" role="alert">{error}</p>}
 </div>;
}
