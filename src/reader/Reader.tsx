import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import type {AnnotationComponent,Direction,PageData,Word,SavedMeaning,SavedMeanings} from '../types';
import {api,ApiError} from '../api';
import {SourceText} from './SourceText';
import {useReaderPosition} from './useReaderPosition';
import {useWordPopover} from './useWordPopover';
import type {ReaderDestination,ReaderPosition} from '../navigation';
import {layoutPage} from './layout';
import {changeDraft,initializeDraft,saveAllDrafts,draftStatus} from './drafts';
import {orderedWords} from './sourceOrder';
import {componentsFor,componentText,emptyBase} from './components';

export function Reader({data,zoom,initialWord,destination,onPosition,onHistory,onCorrect,onSelected}:{data:PageData;zoom:number;initialWord?:string|null;destination:ReaderDestination;onPosition:(position:ReaderPosition)=>void;onHistory:(id:string)=>void;onCorrect:(word:Word)=>void;onSelected:(id:string|null)=>void}){
 const geometry=data.geometry;
 const initial=useMemo(()=>{const server=new Map(data.annotations.map(a=>[a.occurrence_id,a]));const pieces:Record<string,AnnotationComponent[]>={};for(const w of geometry.words){const a=server.get(w.id)||{occurrence_id:w.id,head_revision:0,text:'',direction:'auto' as Direction,deleted:false};const draft=initializeDraft(a);pieces[w.id]=componentsFor(draft||a)}return pieces},[data]);
 const [components,setComponents]=useState(initial),[activePiece,setActivePiece]=useState('base'),[selected,setSelected]=useState<string|null>(()=>geometry.words.some(w=>w.id===initialWord)?initialWord||null:null),[menuOpen,setMenuOpen]=useState(!!initialWord),[error,setError]=useState('');
 const [preview,setPreview]=useState<{word:string;range:[number,number]|null}|null>(null);
 const [deleting,setDeleting]=useState<string|null>(null),[deleteError,setDeleteError]=useState('');
 const focusEditor=useRef(false);
 const pan=useRef<{id:number;x:number;y:number;left:number;top:number;alt:boolean}|null>(null);
 const suppressPanClick=useRef(false);
 const visibleComponents=useMemo(()=>{if(!selected||components[selected]?.length)return components;return {...components,[selected]:[emptyBase()]}},[components,selected]);
 const values=useMemo(()=>Object.fromEntries(Object.entries(components).map(([id,parts])=>[id,componentText(parts)])),[components]);
 const directions=useMemo(()=>Object.fromEntries(Object.entries(components).map(([id,parts])=>[id,parts.find(p=>p.role==='base')?.direction||'auto'])),[components]);
 const [width,setWidth]=useState(Math.min(window.innerWidth-32,1100));
 const host=useRef<HTMLDivElement>(null),scroller=useRef<HTMLDivElement>(null),inputs=useRef(new Map<string,HTMLTextAreaElement>()),groups=useRef(new Map<string,HTMLDivElement>()),buttons=useRef(new Map<string,HTMLElement>());
 function stopPan(){
  const viewport=scroller.current,start=pan.current;pan.current=null;
  viewport?.classList.remove('panning');
  if(start&&viewport?.hasPointerCapture(start.id))viewport.releasePointerCapture(start.id);
 }
 useEffect(()=>{
  const down=(event:KeyboardEvent)=>{
   if(event.key!=='Alt'||(event.target as HTMLElement)?.closest('input,textarea,select,[contenteditable=true],[role=dialog]'))return;
   event.preventDefault();scroller.current?.classList.add('pan-ready');
  };
  const up=(event:KeyboardEvent)=>{if(event.key==='Alt'){scroller.current?.classList.remove('pan-ready');if(pan.current?.alt)stopPan()}};
  const blur=()=>{scroller.current?.classList.remove('pan-ready');stopPan()};
  window.addEventListener('keydown',down);window.addEventListener('keyup',up);window.addEventListener('blur',blur);
  return()=>{window.removeEventListener('keydown',down);window.removeEventListener('keyup',up);window.removeEventListener('blur',blur);blur()};
 },[]);
 const scale=width*zoom/geometry.width;
 const layout=useMemo(()=>layoutPage(geometry,values,selected,scale,directions,visibleComponents),[geometry,values,selected,scale,directions,visibleComponents]);
 const wordMap=useMemo(()=>new Map(geometry.words.map(w=>[w.id,w])),[geometry]);
 const selectedWord=selected?wordMap.get(selected):undefined;
 const [suggestions,setSuggestions]=useState<SavedMeanings|null>(null),[suggestionBusy,setSuggestionBusy]=useState(false),[suggestionError,setSuggestionError]=useState(''),[suggestionPage,setSuggestionPage]=useState(0),[suggestionRetry,setSuggestionRetry]=useState(0);
 useEffect(()=>{
  if(!suggestionError)return;
  const retry=()=>setSuggestionRetry(value=>value+1);
  window.addEventListener('online',retry);window.addEventListener('focus',retry);
  return()=>{window.removeEventListener('online',retry);window.removeEventListener('focus',retry)};
 },[suggestionError]);
 useEffect(()=>{
  if(!selected||!menuOpen){setSuggestions(null);return}
  const controller=new AbortController();setSuggestionBusy(true);setSuggestionError('');
  if(suggestionPage===0)setSuggestions(null);
   const endpoint='/suggestions/'+encodeURIComponent(selected)+'?offset='+suggestionPage;
  let retryTimer:ReturnType<typeof setTimeout>|undefined;
  async function load(path:string){
   for(let attempt=0;;attempt++){
    try{return await api<SavedMeanings>(path,{signal:controller.signal})}
    catch(error){
     if(controller.signal.aborted||attempt>=3||!(error instanceof TypeError||error instanceof ApiError&&error.status>=500))throw error;
     await new Promise<void>((resolve,reject)=>{
      const abort=()=>{clearTimeout(retryTimer);reject(new DOMException('Cancelled','AbortError'))};
      controller.signal.addEventListener('abort',abort,{once:true});
      retryTimer=setTimeout(()=>{controller.signal.removeEventListener('abort',abort);resolve()},500*2**attempt);
     });
    }
   }
  }
   const saving=draftStatus()!=='Saved'?saveAllDrafts().then(()=>true,()=>false):null;
   const show=(result:SavedMeanings)=>{if(!controller.signal.aborted)setSuggestions(previous=>({...result,items:suggestionPage&&previous?[...previous.items,...result.items]:result.items}))};
   void load(endpoint)
   .then(async result=>{
    show(result);if(!controller.signal.aborted)setSuggestionBusy(false);
    // Existing choices are usable while earlier edits finish saving.
    if(saving&&await saving&&!controller.signal.aborted&&suggestionPage===0)show(await load(endpoint));
   })
   .catch(error=>{if(!controller.signal.aborted)setSuggestionError(String(error))})
   .finally(()=>{if(!controller.signal.aborted)setSuggestionBusy(false)});
  return()=>{controller.abort();clearTimeout(retryTimer)};
 },[selected,menuOpen,suggestionPage,suggestionRetry,geometry.revision]);
 const unfinished=useRef(new Map<string,AnnotationComponent[]>());
 function finish(id:string|null){
  if(!id)return;
  const parts=unfinished.current.get(id);if(!parts)return;
  unfinished.current.delete(id);
  changeDraft(id,componentText(parts),parts.find(p=>p.role==='base')?.direction||'auto',!parts.length,parts,true);
 }
 useEffect(()=>{
  const finishAll=()=>{for(const id of [...unfinished.current.keys()])finish(id)};
  window.addEventListener('pagehide',finishAll);
  return()=>{window.removeEventListener('pagehide',finishAll);finishAll()};
 },[]);
 function accept(option:SavedMeaning){
  if(!selected)return;
  finish(selected);
  const parts:AnnotationComponent[]=[{id:'base',role:'base',text:option.text,direction:option.direction,char_range:null}];
  store(selected,parts);finish(selected);setActivePiece('base');
  requestAnimationFrame(()=>inputs.current.get(selected)?.focus({preventScroll:true}));
 }
 async function forget(option:SavedMeaning){
  if(!selected||deleting)return;
  const id=selected;setDeleting(option.id);setDeleteError('');
  try{
   finish(id);await saveAllDrafts();
   await api('/suggestions/'+encodeURIComponent(id),{method:'DELETE',body:JSON.stringify({text:option.text})});
   setSuggestions(previous=>previous?{...previous,items:previous.items.filter(item=>item.id!==option.id),total:Math.max(0,previous.total-(previous.items.some(item=>item.id===option.id)?1:0))}:previous);
   setSuggestionPage(0);setSuggestionRetry(value=>value+1);
  }catch(error){setDeleteError('Could not delete suggestion. '+String(error))}
  finally{setDeleting(null)}
 }
 useReaderPosition({geometry,layout,ready:true,scale,zoom,selected,destination,host,scroller,onPosition});
 const {menu,position:menuPosition}=useWordPopover(menuOpen,selected,buttons,groups,layout,scale);
 useEffect(()=>{const update=()=>setWidth(Math.min(window.innerWidth-32,1100));window.addEventListener('resize',update);return()=>window.removeEventListener('resize',update)},[]);
 useEffect(()=>{onSelected(selected)},[selected,onSelected]);
 useLayoutEffect(()=>{
  if(!selected||!focusEditor.current)return;
  const parts=visibleComponents[selected]||[];
  if(!parts.some(p=>p.id===activePiece)){setActivePiece(parts.find(p=>p.role==='base')?.id||parts[0]?.id||'base');return}
  inputs.current.get(selected)?.focus({preventScroll:true});
 },[selected,activePiece,menuOpen]);
 useEffect(()=>{const valid=initialWord&&wordMap.has(initialWord)?initialWord:null;setSelected(valid);setMenuOpen(!!valid);if(initialWord&&!valid)setError('Source word unavailable')},[initialWord,destination.serial,wordMap]);
 function select(id:string,piece?:string,edit=true){
  focusEditor.current=edit;
  if(edit&&selected===id&&menuOpen)inputs.current.get(id)?.focus({preventScroll:true});
  if(selected!==id){finish(selected);setSuggestions(null);setSuggestionError('');setSuggestionPage(0);setSuggestionBusy(true)}
  setSelected(id);setActivePiece(piece||components[id]?.find(p=>p.role==='base')?.id||components[id]?.[0]?.id||'base');setMenuOpen(true);setError('');
 }
 function dismiss(){finish(selected);setSelected(null);setMenuOpen(false)}
 function store(id:string,parts:AnnotationComponent[]){
  unfinished.current.set(id,parts);
  setComponents(v=>({...v,[id]:parts}));changeDraft(id,componentText(parts),parts.find(p=>p.role==='base')?.direction||'auto',parts.length===0,parts);
 }
 function remove(id:string){
  store(id,[]);finish(id);dismiss();buttons.current.get(id)?.focus({preventScroll:true});
 }
 function update(id:string,pieceId:string,text:string,dir?:Direction){
  const parts=visibleComponents[id]?.length?visibleComponents[id]:[emptyBase()];
  store(id,parts.map(p=>p.id===pieceId?{id:p.id,role:p.role,text,direction:dir||p.direction,char_range:null}:p));
 }
 function retry(){setError('')}
 function key(event:React.KeyboardEvent,id:string){
  if(event.nativeEvent.isComposing||event.keyCode===229)return;
  const editing=event.currentTarget instanceof HTMLTextAreaElement;
  if(event.altKey&&event.key==='ArrowDown'){event.preventDefault();setMenuOpen(true);menu.current?.querySelector<HTMLButtonElement>('.suggestion-accept')?.focus();return}
  if(!editing&&(event.key==='Enter'||event.key===' ')){event.preventDefault();select(id);inputs.current.get(id)?.focus({preventScroll:true});return}
  if(event.key==='Escape'){event.preventDefault();dismiss();buttons.current.get(id)?.focus({preventScroll:true});return}
  if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();dismiss();buttons.current.get(id)?.focus({preventScroll:true});return}
  if(event.key==='Tab'){
   if(editing){const pieces=visibleComponents[id]||[],index=pieces.findIndex(p=>p.id===(event.currentTarget as HTMLTextAreaElement).dataset.piece),next=pieces[index+(event.shiftKey?-1:1)];if(next){event.preventDefault();setActivePiece(next.id);return}}
   const ordered=orderedWords(data).filter(w=>w.normalized);const index=ordered.findIndex(w=>w.id===id),next=ordered[index+(event.shiftKey?-1:1)];if(next){event.preventDefault();select(next.id);buttons.current.get(next.id)?.scrollIntoView({block:'nearest'})}
  }
 }
 const editingPiece=selected?visibleComponents[selected]?.find(p=>p.id===activePiece)||visibleComponents[selected]?.[0]:undefined;
 const sourceRange=preview?.word===selected?preview.range:editingPiece?.source?.source_occurrence_id===selected||!editingPiece?.source?.source_occurrence_id?editingPiece?.char_range:null;
 const characterBounds=selectedWord?.character_bounds;
 const highlight=sourceRange&&characterBounds&&sourceRange[1]<=characterBounds.length?characterBounds.slice(sourceRange[0],sourceRange[1]):null;
 const highlightLeft=highlight?.length?Math.min(...highlight.map(b=>b[0])):null;
 const highlightRight=highlight?.length?Math.max(...highlight.map(b=>b[1])):null;
 return <div ref={scroller} className="reader-scroll" tabIndex={0} aria-label="Reading page"
  onPointerDownCapture={e=>{
   suppressPanClick.current=false;
   if(e.pointerType==='touch'||!(e.button===0&&e.altKey||e.button===1))return;
   e.preventDefault();e.stopPropagation();dismiss();
   suppressPanClick.current=true;
   pan.current={id:e.pointerId,x:e.clientX,y:e.clientY,left:e.currentTarget.scrollLeft,top:e.currentTarget.scrollTop,alt:e.button===0};
   e.currentTarget.setPointerCapture(e.pointerId);e.currentTarget.classList.add('panning');
  }}
  onPointerMove={e=>{const start=pan.current;if(!start||start.id!==e.pointerId)return;e.preventDefault();e.currentTarget.scrollLeft=start.left+start.x-e.clientX;e.currentTarget.scrollTop=start.top+start.y-e.clientY}}
  onPointerUp={e=>{if(pan.current?.id===e.pointerId)stopPan()}}
  onPointerCancel={()=>stopPan()}
  onLostPointerCapture={e=>{pan.current=null;e.currentTarget.classList.remove('panning')}}
  onClickCapture={e=>{if(suppressPanClick.current){suppressPanClick.current=false;e.preventDefault();e.stopPropagation()}}}
  onAuxClick={e=>{if(e.button===1)e.preventDefault()}}
  onKeyDown={e=>{if(e.key==='Escape')stopPan()}}
  onPointerDown={e=>{if(e.target===e.currentTarget||e.target===host.current)dismiss()}}>
  <div ref={host} className="daf" style={{width:(layout.width||geometry.width)*scale,height:layout.height*scale}}>
  <SourceText data={data} layout={layout} scale={scale} selected={selected} targets={buttons} onActivate={id=>select(id)} onSelecting={()=>{focusEditor.current=false;finish(selected);setMenuOpen(false)}} onKeyDown={key}/>
  {selectedWord&&highlightLeft!==null&&highlightRight!==null&&<div className="component-source-range" aria-hidden="true" style={{left:highlightLeft*scale,top:(selectedWord.top+(layout.offsets[selectedWord.line]||0))*scale,width:(highlightRight-highlightLeft)*scale,height:(selectedWord.bottom-selectedWord.top)*scale}}/>}
  {Object.entries(layout.annotations).map(([id,p])=><div key={id} id={'translation-'+id} ref={el=>{if(el)groups.current.set(id,el);else groups.current.delete(id)}} className={'word-annotation'+(selected===id?' selected':'')} role="group" aria-label={'Translation: '+wordMap.get(id)?.text} style={{left:p.x*scale,top:p.y*scale,width:p.width*scale,height:p.height*scale}}>
   {p.pieces.map(position=>{const piece=visibleComponents[id]?.find(c=>c.id===position.id)||emptyBase();return <button type="button" key={piece.id} className={'word-translation component-'+piece.role+(selected===id?' selected':'')} aria-label={'Edit meaning: '+wordMap.get(id)?.text} dir={piece.direction||'auto'} style={{left:0,top:position.y*scale,width:'100%',height:position.height*scale,fontSize:position.fontSize*scale,lineHeight:1.25}} onClick={()=>select(id,piece.id)} onKeyDown={e=>key(e,id)}>{piece.text}</button>})}
  </div>)}
  {menuOpen&&selected&&createPortal(<div ref={menu} className="suggestions" style={{position:'fixed',...menuPosition}} onKeyDown={e=>{if(e.key==='Escape'&&!e.defaultPrevented&&!e.nativeEvent.isComposing&&e.keyCode!==229){e.preventDefault();dismiss();buttons.current.get(selected)?.focus({preventScroll:true})}}}>
   <textarea key={selected} data-piece={editingPiece?.id||'base'} className="new-meaning" aria-label="Write meaning" placeholder="Write meaning" rows={2} spellCheck={false}
    ref={element=>{if(element)inputs.current.set(selected,element);else inputs.current.delete(selected)}}
    value={editingPiece?.text||''} dir={editingPiece?.direction||'auto'} maxLength={20000}
    onChange={event=>update(selected,editingPiece?.id||'base',event.target.value)}
    onBlur={()=>finish(selected)} onKeyDown={event=>key(event,selected)}/>
   <div className="suggestion-list" aria-label="Meanings">
    {suggestions?.items.map(option=><div className="suggestion-option" key={option.id}>
     <button className="suggestion-accept" aria-label={'Meaning: '+option.text} onClick={()=>accept(option)}><span dir={option.direction}>{option.text}</span></button>
     <button className="suggestion-delete" disabled={!!deleting} aria-label={'Delete saved suggestion: '+option.text} title="Delete saved suggestion" onClick={()=>void forget(option)}>{deleting===option.id?'…':'×'}</button>
    </div>)}
    {suggestionBusy&&<span className="busy" role="status" aria-label="Loading meanings"/>}
    {deleteError&&<span className="error-message" role="alert">{deleteError}</span>}
    {suggestionError&&<button title={suggestionError} onClick={()=>setSuggestionRetry(value=>value+1)}>Retry meanings</button>}
    {!suggestionBusy&&!suggestionError&&suggestions?.total===0&&<span className="empty-result">No saved meanings yet.</span>}
    {suggestions&&suggestions.items.length<suggestions.total&&<button disabled={suggestionBusy} onClick={()=>setSuggestionPage(suggestions.offset+24)}>More meanings</button>}
   </div>
   {!!editingPiece?.text.trim()&&<div className="word-tools"><button aria-label="Remove selected meaning" onClick={()=>remove(selected)}>Remove annotation</button></div>}
  </div>,document.body)}
 </div>{error&&<button className="reader-error" onClick={retry} title={error} aria-label={error}>!</button>}</div>
}
