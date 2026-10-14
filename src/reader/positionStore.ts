import {api} from '../api';
import type {ReaderPosition} from '../navigation';

const KEY='shasmaster:location';
let pending:ReaderPosition|undefined,running=false,timer:ReturnType<typeof setTimeout>|undefined;
export function readPosition(value:unknown):ReaderPosition|undefined {
 if(!value||typeof value!=='object'||!('page_id' in value)||typeof value.page_id!=='string')return;
 const saved=value as Record<string,unknown>,number=(key:string,fallback:number)=>typeof saved[key]==='number'&&Number.isFinite(saved[key])?saved[key] as number:fallback,string=(key:string)=>typeof saved[key]==='string'?saved[key] as string:null;
 return {page_id:value.page_id,selected_word:string('selected_word'),anchor_word:string('anchor_word'),anchor_line:string('anchor_line'),source_x:number('source_x',0),source_y:number('source_y',0),viewport_x:number('viewport_x',.5),viewport_y:number('viewport_y',.1),zoom:Math.max(.5,Math.min(3,number('zoom',1))),updated_at:number('updated_at',0)};
}
export function localPosition():ReaderPosition|undefined {try{return readPosition(JSON.parse(localStorage.getItem(KEY)||'null'))}catch{return undefined}}
export function savePosition(position:ReaderPosition){
 const saved=localPosition();position={...position,updated_at:Math.max(Date.now(),(saved?.updated_at||0)+1)};
 try{localStorage.setItem(KEY,JSON.stringify(position))}catch{}
 pending=position;clearTimeout(timer);timer=setTimeout(()=>void flushPosition(),300);
 return position;
}
export async function flushPosition(){
 if(running)return;running=true;
 try{while(pending){const value=pending;pending=undefined;try{await api('/preferences/location',{method:'PUT',body:JSON.stringify({value}),keepalive:true})}catch{const newer=pending as ReaderPosition|undefined;if(!newer||newer.updated_at<value.updated_at)pending=value;timer=setTimeout(()=>void flushPosition(),2000);break}}}finally{running=false}
}
window.addEventListener('online',()=>void flushPosition());
window.addEventListener('pagehide',()=>void flushPosition());
