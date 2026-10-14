import {api} from '../api';
import type {Annotation,AnnotationComponent,Direction,Draft} from '../types';
type Stored={head:number;next:Draft|null;flight:Draft|null;completed?:Draft[];conflict?:{head_revision:number;revision:number};error?:string;mappedTo?:string;sourceConflict?:boolean};
const PREFIX='shasmaster:annotation:';
const records=new Map<string,Stored>(),running=new Set<string>(),timers=new Map<string,ReturnType<typeof setTimeout>>();
const listeners=new Set<()=>void>();
let lastStorageError='';
function notify(){for(const fn of listeners)fn()}
function persist(id:string){try{localStorage.setItem(PREFIX+id,JSON.stringify(records.get(id)));lastStorageError=''}catch{lastStorageError='Draft storage full'}notify()}
function record(id:string,head=0){if(!records.has(id)){try{const saved=localStorage.getItem(PREFIX+id);records.set(id,saved?JSON.parse(saved):{head,next:null,flight:null})}catch{records.set(id,{head,next:null,flight:null})}}return records.get(id)!}
function loadSavedDrafts(){
 try{for(let index=0;index<localStorage.length;index++){const key=localStorage.key(index);if(key?.startsWith(PREFIX))record(key.slice(PREFIX.length))}}
 catch{lastStorageError='Draft storage unavailable'}
}
export function subscribeDrafts(fn:()=>void){listeners.add(fn);return()=>{listeners.delete(fn)}}
export function draftStatus(){if(lastStorageError)return lastStorageError;const all=[...records.values()];if(all.some(r=>r.conflict||r.sourceConflict))return 'Conflict';if(all.some(r=>r.error))return 'Save failed';if(all.some(r=>r.next||r.flight||r.completed?.length))return 'Saving';return 'Saved'}
export function pendingDraft(id:string){const r=records.get(id)||record(id);return r.next||r.completed?.at(-1)||r.flight}
export function conflictFor(id:string){return records.get(id)?.conflict}
export function acknowledgeSource(id:string,target:string){const r=record(id);r.mappedTo=target;delete r.sourceConflict;persist(id);if(r.next||r.flight||r.completed?.length)void flush(id)}
export function initializeDraft(annotation:Annotation){const r=record(annotation.occurrence_id,annotation.head_revision);if(!r.next&&!r.flight&&!r.completed?.length&&!r.conflict)r.head=annotation.head_revision;if(r.next||r.flight||r.completed?.length)void flush(annotation.occurrence_id);return pendingDraft(annotation.occurrence_id)}
export function changeDraft(id:string,text:string,direction:Direction,deleted=false,components?:AnnotationComponent[],remember_meaning=false){const r=record(id);r.next={occurrence_id:id,text,direction,deleted,components,remember_meaning,base_revision:r.head,operation_id:crypto.randomUUID()};delete r.error;if(remember_meaning){(r.completed??=[]).push(r.next);r.next=null}persist(id);clearTimeout(timers.get(id));if(remember_meaning)void flush(id);else timers.set(id,setTimeout(()=>void flush(id),350))}
export function resolveDraft(id:string,head:number,text:string,direction:Direction,deleted=false,components?:AnnotationComponent[]){const r=record(id);r.head=head;r.flight=null;r.next=null;r.completed=[];delete r.conflict;delete r.sourceConflict;for(const [old,other] of records){if(other.mappedTo===id){delete other.sourceConflict;persist(old)}}changeDraft(id,text,direction,deleted,components);void flush(id)}

export function saveDrafts(ids:string[]):Promise<void>{
 return new Promise((resolve,reject)=>{
  let unsubscribe=()=>{},finished=false;
  const changed=()=>{if(finished)return;const items=ids.map(id=>record(id));const error=items.find(r=>r.conflict||r.sourceConflict||r.error);if(error){finished=true;unsubscribe();reject(new Error(error.error||'Resolve the translation conflict first'));return}if(items.every(r=>!r.next&&!r.flight&&!r.completed?.length)){finished=true;unsubscribe();resolve()}};
  for(const id of ids){clearTimeout(timers.get(id));delete record(id).error}
  unsubscribe=subscribeDrafts(changed);
  for(const id of ids)void flush(id);
  changed();
 });
}
export async function saveAllDrafts(){
 loadSavedDrafts();
 if(lastStorageError)throw new Error(lastStorageError);
 await saveDrafts([...records.keys()].filter(id=>{const r=records.get(id)!;return r.next||r.flight||r.completed?.length||r.conflict||r.sourceConflict||r.error}));
}
export async function flush(id:string){
 const r=record(id);if(running.has(id)||r.conflict)return;running.add(id);
 try{
  while(r.flight||r.completed?.length||r.next){
   if(!r.flight){if(r.completed?.length)r.flight=r.completed.shift()!;else{r.flight=r.next;r.next=null}r.flight!.base_revision=r.head;persist(id)}
   const sent=r.flight!,{occurrence_id,...body}=sent;
   try{
    const result=await api<{head_revision:number;revision:number;conflict:boolean;mapped_to?:string;mapped_conflict?:boolean;recovery?:boolean;resolved_sources?:string[]}>('/annotations/'+encodeURIComponent(id),{method:'PUT',body:JSON.stringify(body)});
    // A history restore can supersede this request while it is in flight.
    if(r.flight?.operation_id!==sent.operation_id)continue;
    if(result.mapped_to)r.mappedTo=result.mapped_to;
    r.sourceConflict=!!(result.mapped_conflict||result.recovery);
    for(const old of result.resolved_sources||[]){const original=record(old);original.mappedTo=id;delete original.sourceConflict;persist(old)}
    if(result.conflict){r.conflict=result;r.head=result.head_revision;r.next=r.next||sent;r.flight=null;persist(id);break}
    r.head=result.head_revision;r.flight=null;delete r.error;if(r.next)r.next.base_revision=r.head;persist(id);
   }catch(error){
    if(r.flight?.operation_id!==sent.operation_id)continue;
    r.error=String(error);persist(id);break;
   }
  }
 }finally{running.delete(id);notify()}
}
export function retryDrafts(){loadSavedDrafts();for(const [id,r] of records)if(r.next||r.flight||r.completed?.length)void flush(id);notify()}
window.addEventListener('online',retryDrafts);
