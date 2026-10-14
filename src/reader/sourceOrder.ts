import type {PageData,Word} from '../types';

export function orderedWords(data:PageData):Word[]{
 const explicit=data.corrections.some(c=>{
  if(!c||typeof c!=='object')return false;
  return (c as {kind?:string}).kind==='reading_order';
 });
 if(!explicit&&data.geometry.word_order){
  const order=new Map(data.geometry.word_order.map((id,index)=>[id,index]));
  return [...data.geometry.words].sort((a,b)=>(order.get(a.id)??Infinity)-(order.get(b.id)??Infinity));
 }
 const lines=new Map(data.geometry.lines.map(line=>[line.id,line]));
 const firstLine=new Map<string,number>();
 for(const line of lines.values())firstLine.set(line.region,Math.min(firstLine.get(line.region)??Infinity,line.reading_order));
 const regions=new Map([...data.geometry.regions].sort((a,b)=>a.reading_order-b.reading_order||(firstLine.get(a.id)??0)-(firstLine.get(b.id)??0)||a.id.localeCompare(b.id)).map((region,index)=>[region.id,index]));
 return [...data.geometry.words].sort((a,b)=>explicit?a.reading_order-b.reading_order:(regions.get(a.region)??0)-(regions.get(b.region)??0)||lines.get(a.line)!.reading_order-lines.get(b.line)!.reading_order||b.x-a.x);
}
