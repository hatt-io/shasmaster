import type {AnnotationComponent,Direction,Geometry,Line} from '../types';
export interface PlacedAnnotation {x:number;y:number;width:number;height:number;fontSize:number;text:string;pieces:{id:string;y:number;height:number;fontSize:number}[]}
export interface FrameExpansion {cut:number;extra:number;innerLeft:number;innerRight:number;bodyTop:number}
export interface Layout {height:number;width?:number;xOffsets?:Record<string,number>;offsets:Record<string,number>;annotations:Record<string,PlacedAnnotation>;frames?:Record<string,FrameExpansion>}
type Measurement={text:string;width:number;fontSize:number;scale:number;direction:Direction;height:number};
const measurementCache=new WeakMap<Geometry,Map<string,Measurement>>();
let measurement:HTMLTextAreaElement|null=null;
let textWidth:CanvasRenderingContext2D|null=null;
function annotationWidth(parts:AnnotationComponent[],fontSize:number,sourceWidth:number,scale:number){
 if(!textWidth)textWidth=document.createElement('canvas').getContext('2d');
 let longestWord=0,longestLine=0;
 for(const part of parts){
  const size=fontSize*(part.role==='base'?1:.82);
  if(textWidth)textWidth.font=`${size*scale}px Arial,sans-serif`;
  const measure=(text:string)=>(textWidth?.measureText(text).width??text.length*size*scale)/scale;
  for(const word of part.text.split(/\s+/u))longestWord=Math.max(longestWord,measure(word));
  for(const line of part.text.split('\n'))longestLine=Math.max(longestLine,measure(line));
 }
 const padding=4/scale;
 // The longest word is a hard minimum, even beyond the usual phrase width.
 return Math.max(sourceWidth,longestWord+padding,longestLine+padding);
}
function wrapHeight(text:string,width:number,fontSize:number,scale:number,direction:Direction){
 if(!measurement){measurement=document.createElement('textarea');measurement.tabIndex=-1;measurement.setAttribute('aria-hidden','true');measurement.style.cssText='position:absolute;visibility:hidden;left:-99999px;top:0;padding:0;border:0;min-width:0;box-sizing:border-box;font-family:Arial,sans-serif;font-weight:400;font-style:normal;line-height:1.25;overflow-wrap:normal;word-break:normal;white-space:pre-wrap;resize:none;overflow:hidden';document.body.append(measurement)}
 measurement.style.width=width*scale+'px';measurement.style.fontSize=fontSize*scale+'px';measurement.style.height='0px';measurement.value=text||' ';measurement.dir=direction;
 return Math.max(fontSize*1.25,measurement.scrollHeight/scale);
}
export function layoutPage(geometry:Geometry,values:Record<string,string>,selected:string|null,scale=1,directions:Record<string,Direction>={},components:Record<string,AnnotationComponent[]>={}):Layout{
 const offsets:Record<string,number>={},annotations:Record<string,PlacedAnnotation>={},extra:Record<string,number>={};
 const flow:Record<string,{left:number;right:number}>={};
 const wordMap=new Map(geometry.words.map(w=>[w.id,w]));
 const lines=[...geometry.lines].sort((a,b)=>a.baseline-b.baseline||b.x-a.x);
 let measurements=measurementCache.get(geometry);if(!measurements){measurements=new Map();measurementCache.set(geometry,measurements)}
 for(const line of lines){
  flow[line.id]={left:line.x,right:line.r};extra[line.id]=0;
  for(const id of [...line.words].sort((a,b)=>(wordMap.get(b)?.x||0)-(wordMap.get(a)?.x||0))){
   const text=values[id]||'';if(!text.trim()){measurements.delete(id);continue}
   const w=wordMap.get(id);if(!w)continue;
   const fontSize=Math.max(.5,(w.size||line.size)*.55);
   const parts:AnnotationComponent[]=components[id]?.length?components[id]:[{id:'base',role:'base',text,direction:directions[id]||'auto'}];
   const width=annotationWidth(parts,fontSize,w.r-w.x,scale);
   let height=1;
   const pieces=parts.map(part=>{
    const size=fontSize*(part.role==='base'?1:.82),direction=part.direction||directions[id]||'auto',key=id+':'+part.id,saved=measurements.get(key);
    const partHeight=saved&&saved.text===part.text&&saved.width===width&&saved.fontSize===size&&saved.scale===scale&&saved.direction===direction?saved.height:wrapHeight(part.text,width,size,scale,direction);
    measurements.set(key,{text:part.text,width,fontSize:size,scale,direction,height:partHeight});
    const piece={id:part.id,y:height,height:partHeight,fontSize:size};height+=partHeight+1;return piece;
   });
   const placed={x:Math.max(0,Math.min(geometry.width-width,(w.x+w.r-width)/2)),y:0,width,height,fontSize,text,pieces};annotations[id]=placed;
   flow[line.id].left=Math.min(flow[line.id].left,placed.x);
   flow[line.id].right=Math.max(flow[line.id].right,placed.x+width);
  }
  for(const id of line.words)if(annotations[id]){
   annotations[id].y=line.bottom+.5;
   extra[line.id]=Math.max(extra[line.id],annotations[id].height+1.5);
  }
 }
 // Preserve the center of each source word. Crowding changes only annotation
 // size, never the word-to-meaning alignment or the printed page geometry.
 for(const line of lines){
  const noted=line.words.map(id=>wordMap.get(id)!).filter(w=>w&&annotations[w.id]).sort((a,b)=>a.x-b.x);
  if(!noted.length)continue;
  let fit=1;
  for(let i=0;i<noted.length;i++){
   const word=noted[i],center=(word.x+word.r)/2,note=annotations[word.id];
   fit=Math.min(fit,2*Math.min(center,geometry.width-center)/note.width);
   if(i){
    const previous=noted[i-1],distance=center-(previous.x+previous.r)/2;
    const gap=Math.min(2,distance*.1);
    fit=Math.min(fit,2*Math.max(0,distance-gap)/(annotations[previous.id].width+note.width));
   }
  }
  fit=Math.max(.01,fit);
  for(const word of noted){
   const note=annotations[word.id];
   note.width*=fit;note.fontSize*=fit;note.height*=fit;
   for(const piece of note.pieces){piece.fontSize*=fit;piece.height*=fit;piece.y*=fit}
   note.x=(word.x+word.r-note.width)/2;
  }
  flow[line.id]={left:Math.min(line.x,...noted.map(w=>annotations[w.id].x)),right:Math.max(line.r,...noted.map(w=>annotations[w.id].x+annotations[w.id].width))};
  extra[line.id]=Math.max(...noted.map(w=>annotations[w.id].height))+1.5;
 }
 const frames:Record<string,FrameExpansion>={};
 const contains=(outer:Line,inner:Line)=>outer.x<inner.x&&outer.r>inner.r&&outer.top<inner.top&&outer.bottom>inner.bottom;
 const enclosing=lines.filter(line=>line.source==='artwork'&&lines.some(inner=>inner.words.length>0&&contains(line,inner)));
 const parent=new Map<string,string>();
 for(const line of lines){
  const owners=enclosing.filter(frame=>frame.id!==line.id&&contains(frame,line));
  owners.sort((a,b)=>(a.r-a.x)*(a.bottom-a.top)-(b.r-b.x)*(b.bottom-b.top));
  if(owners[0])parent.set(line.id,owners[0].id);
 }
 const frameIds=new Set(enclosing.map(frame=>frame.id));
 type Block={id:string;x:number;r:number;top:number;bottom:number;baseline:number;extra:number;shift:number;members:Line[];notes:PlacedAnnotation[]};
 const overlaps=(left:number,right:number,otherLeft:number,otherRight:number)=>Math.min(right,otherRight)>Math.max(left,otherLeft);
 function move(block:Block,shift:number){
  block.shift=shift;
  for(const line of block.members)offsets[line.id]=(offsets[line.id]||0)+shift;
  for(const note of block.notes)note.y+=shift;
 }
 function arrange(owner?:string):Block[]{
  const blocks:Block[]=lines.filter(line=>parent.get(line.id)===owner).map(line=>{
   offsets[line.id]=0;
   if(!frameIds.has(line.id))return {id:line.id,x:flow[line.id].left,r:flow[line.id].right,top:line.top,bottom:line.bottom,baseline:line.baseline,extra:extra[line.id],shift:0,members:[line],notes:line.words.map(id=>annotations[id]).filter((note):note is PlacedAnnotation=>!!note)};
   const children=arrange(line.id),contentBottom=Math.max(...children.map(child=>child.bottom));
   const innerBottom=line.frame_inner_bottom??contentBottom;
   const growth=Math.max(0,...children.map(child=>child.bottom+child.shift+child.extra+1-innerBottom));
   frames[line.id]={cut:innerBottom,bodyTop:line.frame_inner_top??Math.min(...children.map(child=>child.top)),extra:growth,innerLeft:Math.min(...children.map(child=>child.x)),innerRight:Math.max(...children.map(child=>child.r))};
   return {id:line.id,x:Math.min(line.x,...children.map(child=>child.x)),r:Math.max(line.r,...children.map(child=>child.r)),top:line.top,bottom:line.bottom,baseline:line.top,extra:growth,shift:0,members:[line,...children.flatMap(child=>child.members)],notes:children.flatMap(child=>child.notes)};
  }).sort((a,b)=>a.baseline-b.baseline||b.x-a.x);
  for(let i=0;i<blocks.length;i++){
   const current=blocks[i];let shift=0;
   for(let j=0;j<i;j++){
    const previous=blocks[j];
    if(!overlaps(current.x,current.r,previous.x,previous.r))continue;
    shift=Math.max(shift,previous.shift+previous.extra);
    for(const note of previous.notes){
     if(overlaps(note.x,note.x+note.width,current.x,current.r))shift=Math.max(shift,note.y+note.height+1-current.top);
     for(const after of current.notes)if(overlaps(note.x,note.x+note.width,after.x,after.x+after.width))shift=Math.max(shift,note.y+note.height+1-after.y);
    }
    for(const note of current.notes)if(overlaps(note.x,note.x+note.width,previous.x,previous.r))shift=Math.max(shift,previous.bottom+previous.shift+1-note.y);
   }
   move(current,shift);
  }
  return blocks;
 }
 const blocks=arrange();
 const height=Math.max(geometry.height,...blocks.map(block=>block.bottom+block.shift+block.extra))+2;
 return {height,width:geometry.width,offsets,annotations,frames};
}
