import type {Page,Tractate} from './types';

export interface DafReference {page_id:string;word_id:string|null}
export interface ReaderPosition {page_id:string;selected_word:string|null;anchor_word:string|null;anchor_line:string|null;source_x:number;source_y:number;viewport_x:number;viewport_y:number;zoom:number;updated_at:number}
export interface ReaderDestination {serial:number;position?:ReaderPosition;word_id?:string|null}
export interface Catalogue {tractates:Tractate[];pages:Page[]}

const aliases:Record<string,string>={berakhot:'berachos',berachot:'berachos',shabbat:'shabbos',shabbath:'shabbos',taanit:'taanis',taanith:'taanis',yevamot:'yevamos',yebamoth:'yevamos',ketubot:'kesubos',kethuboth:'kesubos',bavabatra:'bava-basra',bababathra:'bava-basra',babakamma:'bava-kamma',babametzia:'bava-metzia',makkot:'makkos',makkoth:'makkos',shevuot:'shevuos',shebuoth:'shevuos',horayot:'horayos',menachot:'menachos',bekhorot:'bechoros',bekhoroth:'bechoros',arakhin:'arachin',keritot:'kereisos',kerithoth:'kereisos',middot:'middos'};
const nameKey=(value:string)=>value.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f\u0591-\u05c7]/g,'').replace(/[^a-zא-ת]/g,'');
function hebrewNumber(value:string){const letters='אבגדהוזחטיכלמנסעפצקרשת',values=[1,2,3,4,5,6,7,8,9,10,20,30,40,50,60,70,80,90,100,200,300,400];let total=0;for(const letter of value.replace(/[׳״'"]/g,'')){const index=letters.indexOf(letter);if(index<0)return 0;total+=values[index]}return total}

export function parseReference(input:string,catalogue:Catalogue,current?:Page):DafReference|null {
 let raw=input.trim();
 if(/^https?:\/\//i.test(raw)){try{const url=new URL(raw);raw=url.hash||url.pathname}catch{return null}}
 const [encoded,query='']=raw.replace(/^#|^\//,'').split('?',2);let text:string;
 try{text=decodeURIComponent(encoded).replaceAll('_',' ').trim()}catch{return null}
 const word=new URLSearchParams(query).get('word');
 const exact=catalogue.pages.find(page=>page.id===text.toLowerCase());if(exact)return {page_id:exact.id,word_id:word};
 text=text.replace(/\s+ע[׳״'"\s]*([אב])\s*$/,(_,side)=>side==='א'?'a':'b');
 let tractate=current?.tractate,daf=0,amud=current?.amud||'a',explicitSide=false;
 const numeric=text.match(/^(.*?)(\d+)\s*([abאב])?(?:[.:]\d+(?:[-:]\d+)*)?([.:])?$/i);
 if(numeric){
  const name=nameKey(numeric[1]);if(name)tractate=aliases[name]||catalogue.tractates.find(t=>[t.id,t.label,t.hebrew].some(label=>nameKey(label)===name))?.id;
  daf=Number(numeric[2]);const side=numeric[3]?.toLowerCase();if(side)amud=side==='b'||side==='ב'?'b':'a';else if(numeric[4])amud=numeric[4]===':'?'b':'a';else if(name)amud='a';
  explicitSide=!!(side||numeric[4]);
 }else{
  const named=text.match(/^(.*?)\s+([א-ת׳״'"]+)([ab.:])?$/i),bare=text.match(/^([א-ת׳״'"]+)([ab.:])?$/i);
  const number=named?.[2]||bare?.[1],side=named?.[3]||bare?.[2];if(!number)return null;
  if(named){const name=nameKey(named[1]);tractate=catalogue.tractates.find(t=>nameKey(t.hebrew)===name||nameKey(t.label)===name)?.id}
  daf=hebrewNumber(number);if(side)amud=side===':'||side.toLowerCase()==='b'?'b':'a';else if(named)amud='a';
  explicitSide=!!side;
 }
 const matches=catalogue.pages.filter(p=>p.tractate===tractate&&p.daf===daf);
 const page=matches.find(p=>p.amud===amud)||(!explicitSide&&matches.length===1?matches[0]:undefined);
 return page?{page_id:page.id,word_id:word}:null;
}

export function referenceHash(reference:DafReference){return '#'+reference.page_id+(reference.word_id?'?word='+encodeURIComponent(reference.word_id):'')}
export function historyPosition(reference:DafReference):ReaderPosition|undefined {
 const position=history.state?.shas?.position as ReaderPosition|undefined;
 return position?.page_id===reference.page_id&&(position.selected_word||null)===reference.word_id?position:undefined;
}
export function writeReference(reference:DafReference,mode:'push'|'replace',position?:ReaderPosition){
 const state=typeof history.state==='object'&&history.state?history.state:{};
 history[mode==='push'?'pushState':'replaceState']({...state,shas:{...reference,position}},'',referenceHash(reference));
}
