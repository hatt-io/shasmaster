import {useEffect,useMemo,useState} from 'react';
import {api} from '../api';
import type {PageData,Word} from '../types';
import {WordBoundaries,type BoundaryEdit} from './WordBoundaries';
import {RegionEditor,type RegionEdit} from './RegionEditor';
import {orderedWords} from './sourceOrder';
import {BoundsEditor} from './BoundsEditor';

type Kind='word'|'line'|'region'|'font'|'reading_order'|'boundaries';
export type SourceRecovery={id:string;kind:Kind;payload:Record<string,unknown>;source_words?:Record<string,string>};
type Glyph={font:string;glyph:number;text:string;mapping:string};
type SourceWord=Word&{glyphs:Glyph[];ocr?:{confidence:number}};
const labels:Record<string,string>={text:'Text',x:'Left',r:'Right',top:'Top',bottom:'Bottom',baseline:'Baseline',reading_order:'Reading order',unicode:'Unicode',kind:'Type'};
export function SourceEditor({data,word,onSave,recovery}:{data:PageData;word:Word;onSave:(kind:Kind,payload:Record<string,unknown>)=>Promise<void>;recovery?:SourceRecovery|null}){
 const [kind,setKind]=useState<Kind>(recovery?.kind||'word'),[source,setSource]=useState<SourceWord|null>(null),[fields,setFields]=useState<Record<string,string>>({}),[glyph,setGlyph]=useState(0),[unicode,setUnicode]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [boundary,setBoundary]=useState<BoundaryEdit|null>(null);
 const [regionEdit,setRegionEdit]=useState<RegionEdit|null>(null);
 const line=data.geometry.lines.find(l=>l.id===word.line)!;
 const wordMap=useMemo(()=>new Map(data.geometry.words.map(w=>[w.id,w])),[data]);
 const [order,setOrder]=useState(()=>orderedWords(data).map(w=>w.id));
 const [orderWord,setOrderWord]=useState(word.id);
 const endpoint='/pages/'+data.page.id+'/source/'+encodeURIComponent(word.id);
 const revisionQuery='?revision='+encodeURIComponent(data.geometry.revision);
 useEffect(()=>{const controller=new AbortController();api<SourceWord>(endpoint+revisionQuery,{signal:controller.signal}).then(setSource).catch(e=>{if(!controller.signal.aborted)setError(String(e))});return()=>controller.abort()},[endpoint,revisionQuery]);
 useEffect(()=>{
  if(kind==='word')setFields({text:typeof recovery?.payload.text==='string'?recovery.payload.text:word.text,x:String(word.x),r:String(word.r),top:String(word.top),bottom:String(word.bottom)});
  if(kind==='line')setFields(Object.fromEntries(['x','r','top','bottom','baseline','reading_order'].map(k=>[k,String((line as any)[k])])));
 },[kind,word,line,recovery]);
 useEffect(()=>{setUnicode(typeof recovery?.payload.unicode==='string'?recovery.payload.unicode:source?.glyphs[glyph]?.text||'')},[source,glyph,recovery]);
 async function save(){
  setBusy(true);setError('');
  try{
   let payload:Record<string,unknown>;
   if(kind==='boundaries'){
    if(!boundary)return;payload=boundary;
   }else if(kind==='font'){
    const selected=source?.glyphs[glyph];if(!selected)return;
    payload={font_fingerprint:selected.font,glyph:selected.glyph,unicode};
   }else if(kind==='reading_order')payload={words:order};
   else if(kind==='region'){if(!regionEdit)return;payload=regionEdit}
   else{
    if(kind==='word'&&(!fields.text||/\s/u.test(fields.text)))throw new Error('Enter one source word');
    payload={id:kind==='word'?word.id:line.id,...Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,k==='text'?v:Number(v)]))};
   }
   await onSave(kind,payload);
  }catch(e){setError(String(e))}finally{setBusy(false)}
 }
 function move(delta:number){const index=order.indexOf(orderWord),target=index+delta;if(target<0||target>=order.length)return;setOrder(ids=>{const next=[...ids];[next[index],next[target]]=[next[target],next[index]];return next})}
 return <form onSubmit={e=>{e.preventDefault();void save()}}>
  <nav className="source-tabs" aria-label="Source corrections">{(recovery?[recovery.kind]:['word','boundaries','line','region','font','reading_order'] as Kind[]).map(k=><button key={k} type="button" aria-pressed={kind===k} onClick={()=>setKind(k)}>{{word:'Text',boundaries:'Word breaks',line:'Line',region:'Region',font:'Characters',reading_order:'Reading order'}[k]}</button>)}</nav>
  {recovery&&<OriginalCorrection recovery={recovery}/>}
  {!['word','line','boundaries','region'].includes(kind)&&<img className="source-preview" src={'/api'+endpoint+'/image'+revisionQuery} alt={word.text}/>}
  {kind==='boundaries'&&<WordBoundaries data={data} word={word} onChange={setBoundary}/>}
  {kind==='region'&&<RegionEditor data={data} word={word} onChange={setRegionEdit} initialKind={typeof recovery?.payload.kind==='string'?recovery.payload.kind:undefined}/>}
  {kind==='word'&&<label className="field"><span>Text</span><input dir="rtl" value={fields.text||''} onChange={e=>setFields(f=>({...f,text:e.target.value}))}/></label>}
  {['word','line'].includes(kind)&&fields.x!==undefined&&<BoundsEditor key={kind} geometry={data.geometry} focusBounds={kind==='word'?word:line} bounds={{x:Number(fields.x),r:Number(fields.r),top:Number(fields.top),bottom:Number(fields.bottom)}} baseline={kind==='line'?Number(fields.baseline):undefined} onChange={(bounds,baseline)=>setFields(previous=>({...previous,...Object.fromEntries(Object.entries(bounds).map(([key,value])=>[key,String(value)])),...(baseline===undefined?{}:{baseline:String(baseline)})}))}/>}
  {kind==='font'&&<><div className="source-glyphs" dir="rtl">{source?.glyphs.map((g,index)=><button key={index} type="button" aria-label={'Character '+(index+1)} aria-pressed={glyph===index} onClick={()=>setGlyph(index)}><img src={'/api'+endpoint+'/image'+revisionQuery+'&glyph='+index} alt={g.text}/></button>)}</div><label className="field"><span>Character</span><input required dir="rtl" maxLength={16} value={unicode} onChange={e=>setUnicode(e.target.value)}/></label></>}
  {kind==='reading_order'&&<><div className="settings-row"><button type="button" aria-label="Earlier" onClick={()=>move(-1)} disabled={order[0]===orderWord}>Move earlier</button><button type="button" aria-label="Later" onClick={()=>move(1)} disabled={order.at(-1)===orderWord}>Move later</button></div><select className="source-order" size={10} aria-label="Word reading order" value={orderWord} onChange={e=>setOrderWord(e.target.value)}>{order.map((id,index)=><option key={id} value={id}>{index+1}. {wordMap.get(id)?.text}</option>)}</select></>}
  {error&&<p className="error-message" role="alert">{error}</p>}
  <button disabled={busy||(kind==='font'&&!source?.glyphs.length)||(kind==='boundaries'&&!boundary)||(kind==='region'&&!regionEdit)} type="submit">{busy?<span className="busy" aria-label="Saving"/>:'Save'}</button>
 </form>;
}

function OriginalCorrection({recovery}:{recovery:SourceRecovery}){
 const payload=recovery.payload;
 const values=Object.entries(payload).filter(([key,value])=>(key in labels||key==='unicode'||key==='kind')&&(typeof value==='string'||typeof value==='number'));
 const bounds=payload.bounds;
 if(Array.isArray(bounds))['x','top','r','bottom'].forEach((key,index)=>values.push([key,bounds[index]]));
 return <details className="original-correction"><summary>Original</summary>
  {values.map(([key,value])=><div className="settings-row" key={key}><span>{labels[key]}</span><span dir="auto">{String(value)}</span></div>)}
  {Array.isArray(payload.texts)&&<p dir="rtl">{payload.texts.join(' · ')}</p>}
  {Array.isArray(payload.cuts)&&payload.cuts.length>0&&<div className="settings-row"><span>Boundaries</span><span>{payload.cuts.join(' · ')}</span></div>}
  {Array.isArray(payload.words)&&<ol dir="rtl">{payload.words.map(id=><li key={String(id)}>{recovery.source_words?.[String(id)]||'—'}</li>)}</ol>}
 </details>;
}
