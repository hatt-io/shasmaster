import type {AnnotationComponent,Direction} from '../types';
export function componentsFor(value:{text:string;direction:Direction;components?:AnnotationComponent[];deleted?:boolean}):AnnotationComponent[]{
 if(value.deleted)return [];
 // The reader has one meaning field per word. Older annotations can contain
 // several former dictionary parts, including empty ones; retain their text
 // in one editable field without retaining those extra controls.
 const text=value.components?.length?value.components.map(c=>c.text).filter(text=>text.trim()).join('\n'):value.text;
 return [{id:'base',role:'base',text,direction:value.direction,char_range:null}];
}
export function componentText(components:AnnotationComponent[]){return components.map(c=>c.text).join('\n')}
export function emptyBase():AnnotationComponent{return {id:'base',role:'base',text:'',direction:'auto',char_range:null}}
