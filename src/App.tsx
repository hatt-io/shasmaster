import {useCallback,useEffect,useRef,useState} from 'react';
import {api} from './api';
import type {Page,PageData,Tractate,Word,Direction} from './types';
import {Reader} from './reader/Reader';
import {SourceEditor,type SourceRecovery} from './reader/SourceEditor';
import {Settings} from './Settings';
import {parseReference,referenceHash,historyPosition,writeReference,type Catalogue,type DafReference,type ReaderPosition,type ReaderDestination} from './navigation';
import {localPosition,readPosition,savePosition} from './reader/positionStore';
import {draftStatus,retryDrafts,resolveDraft,subscribeDrafts,saveDrafts,saveAllDrafts,acknowledgeSource} from './reader/drafts';

type Modal='search'|'history'|'bookmarks'|'settings'|'correct'|'recovery'|null;
export function App(){
 const [catalogue,setCatalogue]=useState<{tractates:Tractate[];pages:Page[]}>({tractates:[],pages:[]}),[pageId,setPageId]=useState(''),[data,setData]=useState<PageData|null>(null),[zoom,setZoom]=useState(1),[targetWord,setTargetWord]=useState<string|null>(null),[selected,setSelected]=useState<string|null>(null),[modal,setModal]=useState<Modal>(null),[error,setError]=useState(''),[saveState,setSaveState]=useState('Saved'),[query,setQuery]=useState(''),[results,setResults]=useState<any[]>([]),[revisions,setRevisions]=useState<any[]>([]),[bookmarks,setBookmarks]=useState<any[]>([]),[backups,setBackups]=useState<{name:string;size:number}[]>([]),[correcting,setCorrecting]=useState<Word|null>(null);
 const [searchBusy,setSearchBusy]=useState(false);
 const [recovery,setRecovery]=useState<any[]>([]);
 const [settingsLoading,setSettingsLoading]=useState(false);
 const [recoveringCorrection,setRecoveringCorrection]=useState<SourceRecovery|null>(null);
 const anchorRequest=useRef<AbortController|null>(null);
 const correctionOperation=useRef('');
 const modalElement=useRef<HTMLElement|null>(null);
 const catalogueRef=useRef<Catalogue>({tractates:[],pages:[]}),pageRef=useRef(''),selectedRef=useRef<string|null>(null),positionRef=useRef<ReaderPosition|undefined>(undefined),navigationSerial=useRef(0);
 const [destination,setDestination]=useState<ReaderDestination>({serial:0}),[referenceError,setReferenceError]=useState('');
 const [readerRevision,setReaderRevision]=useState(0),[dafInput,setDafInput]=useState('2');
 const page=catalogue.pages.find(p=>p.id===pageId);
 useEffect(()=>{if(page)setDafInput(String(page.daf))},[pageId,catalogue]);
 useEffect(()=>{
  const controller=new AbortController(),previousRestoration=history.scrollRestoration;history.scrollRestoration='manual';
  Promise.all([api<Catalogue>('/catalogue',{signal:controller.signal}),api<Record<string,any>>('/preferences',{signal:controller.signal})]).then(([c,p])=>{
   if(controller.signal.aborted)return;catalogueRef.current=c;setCatalogue(c);
   const local=localPosition(),server=readPosition(p.location?{...p.location,zoom:p.location.zoom??p.zoom}:undefined),saved=local&&(!server||local.updated_at>=server.updated_at)?local:server;
   const requested=location.hash?parseReference(location.hash,c):null;
   const resumed=requested?readPosition(historyPosition(requested)):saved;
   const fallback=saved&&c.pages.some(page=>page.id===saved.page_id)?{page_id:saved.page_id,word_id:saved.selected_word}:{page_id:c.pages[0]?.id||'berachos-2a',word_id:null};
   const invalid=location.hash&&!requested?location.hash:'';
   if(typeof p.zoom==='number')setZoom(Math.max(.5,Math.min(3,p.zoom)));
   installDestination(requested||fallback,resumed,'replace');if(invalid)setReferenceError(invalid);
  }).catch(e=>{if(!controller.signal.aborted)setError(String(e))});
  void loadBookmarks();const unsubscribe=subscribeDrafts(()=>setSaveState(draftStatus()));retryDrafts();
  return()=>{controller.abort();unsubscribe();history.scrollRestoration=previousRestoration};
 },[]);
 useEffect(()=>{if(!pageId)return;const controller=new AbortController();setData(null);setError('');api<PageData>('/pages/'+pageId,{signal:controller.signal}).then(d=>{if(!controller.signal.aborted)setData(d)}).catch(e=>{if(!controller.signal.aborted)setError(String(e))});return()=>controller.abort()},[pageId]);
 useEffect(()=>{
  let frame=0;
  const changed=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{if(!catalogueRef.current.pages.length)return;const reference=parseReference(location.hash,catalogueRef.current);if(reference)installDestination(reference,readPosition(historyPosition(reference)),'replace');else setReferenceError(location.hash)})};
  window.addEventListener('popstate',changed);window.addEventListener('hashchange',changed);
  return()=>{cancelAnimationFrame(frame);window.removeEventListener('popstate',changed);window.removeEventListener('hashchange',changed)};
 },[]);
 useEffect(()=>{
  if(!modal)return;
  const previous=document.activeElement as HTMLElement|null,container=modalElement.current;
  const overflow=document.body.style.overflow;document.body.style.overflow='hidden';
  const background=Array.from(document.getElementById('root')?.children||[]).filter((node):node is HTMLElement=>node instanceof HTMLElement&&!node.contains(container));
  const inert=background.map(node=>node.hasAttribute('inert'));for(const node of background)node.setAttribute('inert','');
  const focusable=()=>Array.from(container?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],summary,[tabindex="0"]')||[]).filter(node=>node.getClientRects().length);
  const key=(event:KeyboardEvent)=>{
   if(event.key==='Escape'){event.preventDefault();setModal(null);return}
   if(event.key!=='Tab')return;const items=focusable(),first=items[0],last=items.at(-1);
   if(!first){event.preventDefault();container?.focus();return}
   if(event.shiftKey&&(document.activeElement===first||!container?.contains(document.activeElement))){event.preventDefault();last?.focus()}
   else if(!event.shiftKey&&(document.activeElement===last||!container?.contains(document.activeElement))){event.preventDefault();first.focus()}
  };
  if(!container?.contains(document.activeElement))focusable()[0]?.focus({preventScroll:true});
  window.addEventListener('keydown',key);
  return()=>{window.removeEventListener('keydown',key);document.body.style.overflow=overflow;background.forEach((node,index)=>{if(!inert[index])node.removeAttribute('inert')});if(previous?.isConnected)previous.focus({preventScroll:true})};
 },[!!modal]);
 useEffect(()=>{const container=modalElement.current;if(modal&&!container?.contains(document.activeElement))container?.querySelector<HTMLElement>('input,button')?.focus({preventScroll:true})},[modal]);
 useEffect(()=>{
  const shortcut=(event:KeyboardEvent)=>{if(modal||!event.altKey||(event.key!=='PageDown'&&event.key!=='PageUp'))return;event.preventDefault();adjacent(event.key==='PageDown'?1:-1)};
  window.addEventListener('keydown',shortcut);return()=>window.removeEventListener('keydown',shortcut);
 },[modal,pageId,catalogue]);
 useEffect(()=>{const controller=new AbortController();if(modal!=='search')return;setSearchBusy(true);setResults([]);const timer=setTimeout(()=>{api<any[]>('/search?q='+encodeURIComponent(query),{signal:controller.signal}).then(value=>{if(!controller.signal.aborted)setResults(value)}).catch(e=>{if(!controller.signal.aborted)setError(String(e))}).finally(()=>{if(!controller.signal.aborted)setSearchBusy(false)})},150);return()=>{clearTimeout(timer);controller.abort()}},[query,modal]);
 async function loadBookmarks(){try{setBookmarks(await api<any[]>('/bookmarks'))}catch(e){setError(String(e))}}
 function installDestination(reference:DafReference,position?:ReaderPosition,mode:'push'|'replace'='push'){
  const requested=catalogueRef.current.pages.find(page=>page.id===reference.page_id);
  if(!requested){setReferenceError(reference.page_id);return}
  if(position?.page_id!==reference.page_id)position=undefined;
  if(pageRef.current!==reference.page_id)setData(null);
  pageRef.current=reference.page_id;selectedRef.current=reference.word_id;positionRef.current=position;
  setPageId(reference.page_id);setDafInput(String(requested.daf));setTargetWord(reference.word_id);setSelected(reference.word_id);setReferenceError('');setModal(null);
  if(position)setZoom(position.zoom);
  const serial=++navigationSerial.current;
  setDestination({serial,word_id:reference.word_id,position});
  writeReference(reference,mode==='push'&&location.hash===referenceHash(reference)?'replace':mode,position);
  anchorRequest.current?.abort();
  if(reference.word_id){
   const controller=new AbortController();anchorRequest.current=controller;
   api<{occurrence_id:string;page_id:string;state:string}>('/anchors/'+encodeURIComponent(reference.word_id),{signal:controller.signal}).then(anchor=>{
    if(controller.signal.aborted||navigationSerial.current!==serial||anchor.state!=='mapped')return;
    if(selectedRef.current&&selectedRef.current!==reference.word_id&&selectedRef.current!==anchor.occurrence_id)return;
    const saved=position?{...position,page_id:anchor.page_id,selected_word:anchor.occurrence_id,anchor_word:position.anchor_word===reference.word_id?anchor.occurrence_id:position.anchor_word}:undefined;
    installDestination({page_id:anchor.page_id,word_id:anchor.occurrence_id},saved,'replace');
   }).catch(()=>{});
  }
 }
 function navigate(id:string,word:string|null=null){installDestination({page_id:id,word_id:word})}
 function remountReader(target=selectedRef.current,mappings:Record<string,string|null>={}){
  const saved=positionRef.current;
  const position=saved?.page_id===pageRef.current?{...saved,selected_word:target,anchor_word:saved.anchor_word&&Object.hasOwn(mappings,saved.anchor_word)?mappings[saved.anchor_word]:saved.anchor_word}:undefined;
  positionRef.current=position;selectedRef.current=target;setTargetWord(target);setSelected(target);
  setDestination({serial:++navigationSerial.current,word_id:target,position});setReaderRevision(v=>v+1);
  writeReference({page_id:pageRef.current,word_id:target},'replace',position);
 }
 async function refreshPage(target=selectedRef.current,mappings:Record<string,string|null>={}){
  const id=pageRef.current,next=await api<PageData>('/pages/'+id);if(id!==pageRef.current)return;
  setData(next);remountReader(target,mappings);
 }
 function adjacent(delta:number){if(!page)return;const next=catalogue.pages.find(p=>p.sequence===page.sequence+delta);if(next)navigate(next.id)}
 function chooseDaf(daf:number,amud=page?.amud||'a'){if(!page)return;const next=catalogue.pages.find(p=>p.tractate===page.tractate&&p.daf===daf&&p.amud===amud);if(next)navigate(next.id)}
 function submitReference(){if(!page||dafInput.trim()===String(page.daf))return;const reference=parseReference(dafInput,catalogue,page);if(reference)installDestination(reference);else setReferenceError(dafInput||'—')}
 function changeZoom(value:number){const next=Math.max(.5,Math.min(3,value));setZoom(next);void api('/preferences/zoom',{method:'PUT',body:JSON.stringify({value:next})})}
 async function openHistory(id:string){setSelected(id);setModal('history');try{setRevisions(await api<any[]>('/annotations/'+encodeURIComponent(id)+'/history'))}catch(e){setError(String(e))}}
 function openCorrection(word:Word){correctionOperation.current=crypto.randomUUID();setRecoveringCorrection(null);setCorrecting(word);setModal('correct')}
 async function recoverItem(item:any,target:Word){
  try{
   if(item.kind==='correction'){
    const kind=item.payload.kind;
    if(!['word','line','region','font','reading_order','boundaries'].includes(kind))throw new Error('Unsupported source correction');
    setRecoveringCorrection({id:item.id,kind,payload:JSON.parse(item.payload.payload_json),source_words:item.source_words});setCorrecting(target);setModal('correct');return;
   }
   await api('/recovery/'+item.id+'/resolve',{method:'POST',body:JSON.stringify({occurrence_id:target.id})});
   const source=item.payload.anchors?.[0];if(item.kind==='annotation'&&source?.id)acknowledgeSource(source.id,target.id);
   setRecovery(await api('/recovery'));await refreshPage(target.id);await loadBookmarks();
  }catch(e){setError(String(e))}
 }
 async function saveCorrection(kind:string,payload:Record<string,unknown>){
  if(!data)return;
  if(kind==='boundaries')await saveDrafts(payload.words as string[]);
  const correction={base_revision:data.geometry.revision,kind,payload};
  const endpoint=recoveringCorrection?'/recovery/'+recoveringCorrection.id+'/resolve':'/pages/'+pageId+'/corrections';
  const body=recoveringCorrection?{occurrence_id:correcting?.id,correction}:{id:correctionOperation.current,...correction};
  const result=await api<{anchors?:Record<string,string|null>;unresolved?:number;conflicts?:string[]}>(endpoint,{method:'POST',body:JSON.stringify(body)});
  const target=correcting&&result.anchors&&Object.hasOwn(result.anchors,correcting.id)?result.anchors[correcting.id]:selectedRef.current;
  await refreshPage(target||null,result.anchors);
  if(recoveringCorrection){setRecoveringCorrection(null);setRecovery(await api('/recovery'));setModal('recovery')}
  else if(result.unresolved){setRecovery(await api('/recovery'));setModal('recovery')}
  else if(result.conflicts?.length)await openHistory(result.conflicts[0]);
  else setModal(null);
 }
 async function toggleBookmark(){try{const exists=bookmarks.some(b=>b.page_id===pageId);await api('/bookmarks/'+pageId,{method:exists?'DELETE':'PUT',body:exists?undefined:JSON.stringify({occurrence_id:selected})});await loadBookmarks()}catch(e){setError(String(e))}}
 async function exportWork(){
  try{
   await saveAllDrafts();
   const payload=await api('/export'),url=URL.createObjectURL(new Blob([JSON.stringify(payload)],{type:'application/json'}));
   const link=document.createElement('a');link.href=url;link.download='shas-master-work.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){setError(String(e))}
 }
 async function makeBackup(){try{await saveAllDrafts();await api('/backups',{method:'POST'});setBackups(await api('/backups'))}catch(e){setError(String(e))}}
 async function restoreBackup(name:string){try{await saveAllDrafts();const result=await api<{unresolved:number}>('/backups/'+encodeURIComponent(name)+'/restore',{method:'POST'});await refreshPage();await loadBookmarks();if(result.unresolved){setRecovery(await api('/recovery'));setModal('recovery')}else setModal(null)}catch(e){setError(String(e))}}
 async function restore(file:File){try{const payload=JSON.parse(await file.text());await saveAllDrafts();const result=await api<{unresolved:number}>('/restore',{method:'POST',body:JSON.stringify(payload)});if(result.unresolved){setRecovery(await api('/recovery'));setModal('recovery')}await refreshPage();await loadBookmarks()}catch(e){setError(String(e))}}
 async function openSettings(){
  setError('');setSettingsLoading(true);setModal('settings');
  try{
   const [savedBackups,pending]=await Promise.all([api<{name:string;size:number}[]>('/backups'),api<any[]>('/recovery')]);
   setBackups(savedBackups);setRecovery(pending);
  }catch(e){setError(String(e))}finally{setSettingsLoading(false)}
 }
 const onSelected=useCallback((id:string|null)=>{
  setSelected(id);selectedRef.current=id;if(!pageRef.current)return;
  const saved=positionRef.current,position=saved?.page_id===pageRef.current?{...saved,selected_word:id}:undefined;
  positionRef.current=position;writeReference({page_id:pageRef.current,word_id:id},'replace',position);
 },[]);
 const onPosition=useCallback((value:ReaderPosition)=>{
  if(value.page_id!==pageRef.current)return;const saved=savePosition(value);positionRef.current=saved;
  writeReference({page_id:value.page_id,word_id:value.selected_word},'replace',saved);
 },[]);
 return <><div className="reader-shell"><header className="reader-toolbar" data-reader-header>
  <span className="brand">Shas Master</span>
  <nav className="navigation" aria-label="Daf navigation" dir="rtl">
   <button dir="ltr" aria-label="Previous amud" onClick={()=>adjacent(-1)} disabled={!page||page.sequence===0}>Previous <span aria-hidden="true">›</span></button>
   <label className="navigation-field"><span>Mesechta</span><select value={page?.tractate||''} onChange={e=>{const next=catalogue.pages.find(p=>p.tractate===e.target.value);if(next)navigate(next.id)}}>{catalogue.tractates.map(t=><option key={t.id} value={t.id}>{t.label}</option>)}</select></label>
   <label className="navigation-field"><span>Daf</span><input aria-label="Daf or reference" aria-invalid={!!referenceError} title={referenceError?'Unknown reference: '+referenceError:undefined} value={dafInput} onChange={e=>{setDafInput(e.target.value);setReferenceError('')}} onBlur={submitReference} onKeyDown={e=>{if(e.key==='Enter')submitReference();if(e.key==='Escape'){setDafInput(String(page?.daf||''));setReferenceError('')}}}/></label>
   <label className="navigation-field"><span>Amud</span><select value={page?.amud||'a'} onChange={e=>chooseDaf(page?.daf||2,e.target.value as 'a'|'b')}><option value="a" disabled={!catalogue.pages.some(p=>p.tractate===page?.tractate&&p.daf===page?.daf&&p.amud==='a')}>a</option><option value="b" disabled={!catalogue.pages.some(p=>p.tractate===page?.tractate&&p.daf===page?.daf&&p.amud==='b')}>b</option></select></label>
   <button dir="ltr" aria-label="Next amud" onClick={()=>adjacent(1)} disabled={!page||page.sequence===catalogue.pages.length-1}><span aria-hidden="true">‹</span> Next</button>
  </nav>
  <div className="actions">
   <div className="zoom-controls" role="group" aria-label="Zoom" title="Hold Option (Alt) and drag to move around the page">
    <button onClick={()=>changeZoom(zoom-.1)} disabled={zoom<=.5}>− Zoom out</button>
    <button className="zoom" onClick={()=>changeZoom(1)} aria-label={'Zoom '+Math.round(zoom*100)+' percent; reset to 100 percent'}>{Math.round(zoom*100)}% · Reset</button>
    <button onClick={()=>changeZoom(zoom+.1)} disabled={zoom>=3}>+ Zoom in</button>
   </div>
   <button onClick={()=>{setQuery('');setResults([]);setModal('search')}}><span aria-hidden="true">⌕</span> Search</button>
   <button onClick={toggleBookmark}>{bookmarks.some(b=>b.page_id===pageId)?'★ Remove bookmark':'☆ Bookmark page'}</button>
   <button onClick={()=>setModal('bookmarks')}>Bookmarks</button>
   <button onClick={()=>void openSettings()}>Settings</button>
   <div className="save-indicator"><span role="status"><span aria-hidden="true" className={'save-state '+(saveState==='Saving'?'pending':saveState==='Saved'?'':'error')}/>{saveState}</span>{saveState!=='Saved'&&saveState!=='Saving'&&<button onClick={retryDrafts}>Retry save</button>}</div>
  </div>
 </header>
 {data?<Reader key={data.geometry.id+data.geometry.revision+readerRevision} data={data} zoom={zoom} initialWord={targetWord} destination={destination} onPosition={onPosition} onHistory={id=>void openHistory(id)} onCorrect={openCorrection} onSelected={onSelected}/>:<div className="page-status">{error?'Page unavailable':<span className="busy" aria-label="Loading page"/>}</div>}
 </div>
 {modal&&<div className="modal-backdrop" onPointerDown={e=>{if(e.target===e.currentTarget)setModal(null)}}><section ref={modalElement} tabIndex={-1} className={'modal'+(modal==='settings'?' settings-modal':modal==='correct'?' source-modal':'')} role="dialog" aria-modal="true" aria-labelledby="modal-title"><header><h2 id="modal-title">{{search:'Search',history:'History',bookmarks:'Bookmarks',settings:'Settings',correct:'Correct source',recovery:'Recovery'}[modal]}</h2><button aria-label="Close" onClick={()=>setModal(null)}>×</button></header>
 {modal==='search'&&<><input autoFocus type="search" aria-label="Search printed text" value={query} dir="auto" onChange={e=>{setError('');setQuery(e.target.value)}}/>{searchBusy?<span className="busy" role="status" aria-label="Searching"/>:<div className="result-list">{results.map((r,i)=><button key={r.occurrence_id||r.id||i} onClick={()=>navigate(r.page_id,r.occurrence_id)}><span dir="auto">{r.text}</span>{r.page_id&&<span>{catalogue.tractates.find(t=>t.id===r.tractate)?.label} {r.daf}{r.amud}</span>}</button>)}</div>}</>}
 {modal==='bookmarks'&&<div className="result-list">{bookmarks.map(b=><button key={b.page_id} onClick={()=>navigate(b.page_id,b.occurrence_id)}>{catalogue.tractates.find(t=>t.id===b.tractate)?.label} {b.daf}{b.amud}</button>)}</div>}
 {modal==='history'&&revisions.map(r=><div className="history-item" key={r.revision}><div className="history-components">{r.deleted?'∅':r.components?.map((c:any)=><p key={c.id} dir={c.direction||r.direction} className={'component-'+c.role}>{c.text}</p>)||<p dir={r.direction}>{r.text}</p>}</div><time>{r.created_at}</time><button onClick={()=>{if(!selected)return;const head=r.head_revision;resolveDraft(selected,head,r.text,r.direction as Direction,!!r.deleted,r.components);setData(data?{...data}:null);remountReader(selected);setModal(null)}}>Restore</button></div>)}
 {modal==='settings'&&<Settings backups={backups} loading={settingsLoading} recoveryCount={recovery.length} onExport={exportWork} onImport={restore} onBackup={makeBackup} onRestore={restoreBackup} onRecovery={()=>setModal('recovery')}/>}
 {modal==='recovery'&&recovery.map(item=>{const source=item.payload.anchors?.[0];const versions=item.payload.annotations||[];const head=item.payload.heads?.[0]?.head_revision;const wording=versions.find((r:any)=>r.revision===head)?.text||versions.at(-1)?.text;const target=data?.geometry.words.find(w=>w.id===selected);return <div className="history-item" key={item.id}><p dir="auto">{source?.text||item.payload.label||item.kind}{wording&&<> · {wording}</>}</p><small>{item.reason}</small><div className="settings-row"><span dir="rtl">{target?.text||'—'}</span><button disabled={!target} onClick={()=>target&&void recoverItem(item,target)}>{item.kind==='annotation'?'Attach':item.kind==='correction'?'Edit':'Apply'}</button></div></div>})}
 {modal==='correct'&&data&&correcting&&<SourceEditor key={correcting.id+':'+(recoveringCorrection?.id||correctionOperation.current)} data={data} word={correcting} recovery={recoveringCorrection} onSave={saveCorrection}/>}
 {error&&<p className="error-message" role="alert">{error}</p>}
 </section></div>}
 </>;
}
