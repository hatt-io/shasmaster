export type Direction='auto'|'ltr'|'rtl';
export interface SourceGlyph {text:string;x:number;baseline:number;size:number;font?:string}
export interface Word {id:string;line:string;region:string;x:number;r:number;top:number;bottom:number;text:string;normalized:string;reading_order:number;state:string;size?:number;baseline?:number;font?:string;source_glyphs?:SourceGlyph[];character_bounds?:[number,number][]}
export interface Line {id:string;x:number;r:number;top:number;bottom:number;baseline:number;size:number;words:string[];reading_order:number;region:string;source?:string;frame_inner_top?:number;frame_inner_bottom?:number}
export interface Geometry {id:string;width:number;height:number;revision:string;source_sha:string;pdf:string;fonts?:{id:string;url:string}[];words:Word[];word_order?:string[];lines:Line[];regions:{id:string;kind:string;bounds:number[];reading_order:number}[]}
export interface Page {id:string;tractate:string;daf:number;amud:'a'|'b';sequence:number;acquisition_state:string;extraction_state:string;label?:string;hebrew?:string}
export interface AnnotationComponent {id:string;role:'base'|'prefix'|'suffix'|'custom';text:string;direction:Direction;char_range?:[number,number]|null;form?:string;headword?:string;entry_id?:string;sense_id?:string;source?:Record<string,unknown>;relationship?:Record<string,unknown>;interpretation_id?:string}
export interface SuggestionComponent extends Omit<AnnotationComponent,'direction'> {direction?:Direction;entry_id:string;sense_id:string;form:string;headword:string;source:Record<string,unknown>;relationship:Record<string,unknown>;normalized_range?:[number,number];alternate_evidence?:Record<string,unknown>[]}
export interface Annotation {occurrence_id:string;head_revision:number;text:string;direction:Direction;components?:AnnotationComponent[];deleted:boolean;conflict?:boolean}
export interface PageData {page:Page;geometry:Geometry;annotations:Annotation[];corrections:unknown[]}
export interface Tractate {id:string;label:string;hebrew:string;sequence:number;first_daf:number;first_amud:string;last_daf:number;last_amud:string}
export interface Draft {occurrence_id:string;text:string;direction:Direction;base_revision:number;operation_id:string;deleted:boolean;components?:AnnotationComponent[];remember_meaning?:boolean}
export interface SavedMeaning {id:string;text:string;direction:Direction}
export interface SavedMeanings {items:SavedMeaning[];offset:number;total:number}
export interface Suggestion {components:SuggestionComponent[];approximate:boolean;id:string;entry_id:string;sense_id:string;text:string;headword:string;grammar_json:string;score?:number|null;word_interpretation?:Record<string,unknown>|null;word_parts_connected?:boolean;interpretation_complete?:boolean}
export interface Suggestions {items:Suggestion[];offset:number;total:number;ranking:'word_only'|'pending'|'available'|'partial'|'unavailable'}
