// Activate on click; a drag or native text selection cancels that gesture.
export class SourceActivation {
 private start:{x:number;y:number}|null=null;
 private dragged=false;
 private cancelled=false;
 constructor(private activate:(id:string)=>void,private hasSelection:()=>boolean){}
 cancel(){this.cancelled=true}
 down(x:number,y:number){this.cancelled=false;this.start={x,y};this.dragged=false}
 move(x:number,y:number){if(this.start&&Math.hypot(x-this.start.x,y-this.start.y)>4){this.dragged=true;this.cancel()}}
 up(){this.start=null}
 click(id:string,detail:number){
  if(detail===0){this.activate(id);return}
  if(detail!==1||this.cancelled||this.dragged||this.hasSelection())return;
  this.activate(id);
 }
}

export function selectSourceWord(word:HTMLElement){
 const document=word.ownerDocument,selection=document.getSelection();
 if(!selection)return;
 const range=document.createRange();range.selectNodeContents(word);
 selection.removeAllRanges();selection.addRange(range);
}

export function copySourceSelection(root:HTMLElement,event:ClipboardEvent){
 const document=root.ownerDocument,active=document.activeElement;
 if(active?.matches('input,textarea,[contenteditable="true"]'))return;
 const selection=document.getSelection();
 if(!selection||selection.isCollapsed||selection.rangeCount!==1||!event.clipboardData)return;
 const range=selection.getRangeAt(0);
 if(!root.contains(range.startContainer)||!root.contains(range.endContainer))return;
 // DOM text contains explicit word spaces and line breaks in reading order.
 // Unlike Selection.toString(), this does not insert breaks for positioned words.
 const text=range.cloneContents().textContent;
 if(!text)return;
 event.clipboardData.setData('text/plain',text);
 event.preventDefault();
}
