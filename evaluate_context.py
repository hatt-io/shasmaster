"""Evaluate exact-spelling saved meanings, using isolated temporary learner work.

The user replaced dictionary translation with remembering their own entries.
This is the existing sole evaluator; no dictionary words or live annotations
are used, and no case reports or persistent search caches are created.
"""
import argparse
import asyncio
import json
from pathlib import Path
import tempfile
import subprocess
import uuid
import httpx
from server.db import database_scope, migrate, transaction, read, backup, load_backup
from server.annotations import write_annotation, restore_into
from server.saved_meanings import suggestions_for_word


def evaluate_drafts():
    """Exercise the real browser save queue with delayed and failed requests."""
    subprocess.run(['node','--input-type=commonjs'],input=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ts=require('typescript');
const compiled=ts.transpileModule(fs.readFileSync('src/reader/drafts.ts','utf8'),{
 compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}
}).outputText;
const storage=new Map(), learned=new Set(), operations=new Map();
let pending=[],head=0,fail=false,automatic=false;
const api=async(path,options)=>{
 const body=JSON.parse(options.body);
 if(fail){fail=false;throw Error('Offline')}
 if(!automatic)await new Promise(resolve=>pending.push(resolve));
 if(!operations.has(body.operation_id)){
  assert.equal(body.base_revision,head);
  if(body.remember_meaning)learned.add(body.text);
  operations.set(body.operation_id,{head_revision:++head,revision:head,conflict:false});
 }
 return operations.get(body.operation_id);
};
function load(){
 const exports={};
 const context={exports,require:name=>{assert.equal(name,'../api');return {api}},
  localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),
   get length(){return storage.size},key:i=>[...storage.keys()][i]},
  window:{addEventListener(){}},crypto:require('node:crypto').webcrypto,setTimeout,clearTimeout};
 vm.runInNewContext(compiled,context);return exports;
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const drafts=load();
 drafts.changeDraft('synthetic','incomplete','ltr');void drafts.flush('synthetic');
 drafts.changeDraft('synthetic','First completed meaning','ltr',false,undefined,true);
 drafts.changeDraft('synthetic','Second completed meaning','ltr',false,undefined,true);
 drafts.changeDraft('synthetic','next incomplete','ltr');
 for(let i=0;i<4;i++){assert.equal(pending.length,1);pending.shift()();await tick()}
 await drafts.saveAllDrafts();assert.equal(learned.size,2);assert.equal(head,4);
 automatic=true;fail=true;
 drafts.changeDraft('synthetic','Offline completed meaning','ltr',false,undefined,true);
 await tick();assert.equal(drafts.draftStatus(),'Save failed');
 const reopened=load();await reopened.saveAllDrafts();
 assert.equal(learned.size,3);assert.equal(reopened.draftStatus(),'Saved');
 console.log('Browser save queue: rapid completed edits retained; offline edit recovered after reload');
})().catch(error=>{console.error(error);process.exitCode=1});
''',text=True,check=True,cwd=Path(__file__).resolve().parent)


def evaluate_reader_ux():
    """Exercise reader event handling and layout without controlling the UI."""
    subprocess.run(['node','--input-type=commonjs'],input=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),ts=require('typescript');
function load(path,globals={}){
 const exports={};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(path,'utf8'),{
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}
 }).outputText,{exports,...globals});return exports;
}
let selected=false,activations=0;
const {SourceActivation,copySourceSelection,selectSourceWord}=load('src/reader/sourceSelection.ts',{
 setTimeout:()=>{throw new Error('Word activation must not wait for a timer')}
});
const activation=new SourceActivation(()=>activations++,()=>selected);
activation.down(10,10);activation.up();activation.click('synthetic',1);
assert.equal(activations,1);
activation.down(10,10);activation.move(30,10);activation.up();activation.click('synthetic',1);assert.equal(activations,1);
activation.down(10,10);activation.up();activation.click('synthetic',1);
activation.down(10,10);activation.up();activation.click('synthetic',2);assert.equal(activations,2);
activation.down(10,10);selected=true;activation.up();activation.click('synthetic',1);assert.equal(activations,2);
selected=false;activation.click('synthetic',0);assert.equal(activations,3);
activation.down(10,10);activation.cancel();activation.up();activation.click('synthetic',1);assert.equal(activations,3);
activation.down(10,10);activation.up();activation.click('synthetic',1);assert.equal(activations,4);
let selectedWord=null,removedRanges=0,addedRange=null;
const wordRange={selectNodeContents:word=>selectedWord=word};
const selectableWord={ownerDocument:{createRange:()=>wordRange,getSelection:()=>({removeAllRanges:()=>removedRanges++,addRange:range=>addedRange=range})}};
selectSourceWord(selectableWord);
assert.ok(selectedWord===selectableWord&&removedRanges===1&&addedRange===wordRange,'double click selects the entire source word across letter spans');
let editing=false,inside=true,collapsed=false,copies=0,prevented=0,cloned=0;
const range={startContainer:{},endContainer:{},cloneContents:()=>{cloned++;return {textContent:'synthetic text\nsecond line'}}};
const root={contains:()=>inside,ownerDocument:{activeElement:{matches:()=>editing},getSelection:()=>({isCollapsed:collapsed,rangeCount:1,getRangeAt:()=>range})}};
const event={clipboardData:{setData:()=>copies++},preventDefault:()=>prevented++};
copySourceSelection(root,event);assert.equal(copies,1);assert.equal(prevented,1);assert.equal(cloned,1);
editing=true;copySourceSelection(root,event);editing=false;inside=false;copySourceSelection(root,event);
inside=true;collapsed=true;copySourceSelection(root,event);assert.equal(copies,1);
// Model text measurement only; this is not a browser-rendering assertion.
const canvas={font:'',measureText(text){return {width:text.length*parseFloat(this.font)*.6}}};
const document={body:{append(){}},createElement:kind=>kind==='canvas'?{getContext:()=>canvas}:{
 style:{},value:'',setAttribute(){},get scrollHeight(){
  const size=parseFloat(this.style.fontSize),width=parseFloat(this.style.width);
  let rows=0;for(const line of this.value.split('\n')){
   let used=0;rows++;
   for(const word of line.split(' ')){const next=word.length*size*.6+(used?size*.6:0);if(used&&used+next>width){rows++;used=0}used+=next}
  }return Math.ceil(rows*size*1.25);
 }
}};
const {layoutPage}=load('src/reader/layout.ts',{document});
const words=[0,1,2].map(i=>({id:'w'+i,line:'line',region:'region',x:30+i*20,r:40+i*20,top:10,bottom:30,text:'',normalized:'',reading_order:i,state:'original'}));
const geometry={width:200,height:100,words,lines:[{id:'line',x:30,r:80,top:10,bottom:30,baseline:28,size:20,words:words.map(w=>w.id),reading_order:0,region:'region'}],regions:[]};
const values={w0:'translation',w1:'neighboring',w2:'a phrase with several words'};
for(const scale of [.5,1,2]){
 const placed=layoutPage(geometry,values,null,scale).annotations;
 console.log('Annotation center displacement at zoom '+scale+': '+Math.max(...words.map(word=>Math.abs(placed[word.id].x+placed[word.id].width/2-(word.x+word.r)/2)))+' source units');
 for(const [id,note] of Object.entries(placed)){
  const longest=Math.max(...values[id].split(' ').map(word=>word.length))*note.fontSize*.6;
  assert.ok(note.width>longest,'every whole word fits');
  if(!values[id].includes(' '))assert.ok(note.pieces[0].height<=Math.ceil(note.fontSize*1.25*scale)/scale+.01,'single word stays on one line');
 }
 const notes=Object.values(placed);
 for(let i=0;i<notes.length;i++)for(let j=i+1;j<notes.length;j++){
  const a=notes[i],b=notes[j];
  assert.ok(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y,'neighboring meanings do not overlap');
 }
}
console.log('Reader UX: click/drag/double-click separation, clipboard guards, whole-word widths and collision handling at three zoom levels passed. Native browser rendering was not automated.');
''',text=True,check=True,cwd=Path(__file__).resolve().parent)


def seed():
    with transaction() as conn:
        conn.execute("INSERT INTO tractate VALUES('evaluation','Evaluation','',0,2,'a',2,'b','evaluation')")
        for side in ('a','b'):
            page='evaluation-'+side
            conn.execute('INSERT INTO page(id,tractate,daf,amud,sequence,edition,source_url) VALUES(?,?,?,?,?,?,?)',
                         (page,'evaluation',2,side,int(side=='b'),'evaluation','local'))
            conn.execute('INSERT INTO page_revision(id,page_id,source_sha,geometry_path,extractor_revision) VALUES(?,?,?,?,?)',
                         (page,page,'evaluation','unused','evaluation'))
            conn.execute('INSERT INTO region VALUES(?,?,?,?,?)',(page,page,'body','[]',0))
            # Synthetic letter sequences test identity, not dictionary meanings.
            for number in range(32):
                spelling='אא'+chr(0x05d0+number//22)+chr(0x05d0+number%22)+'אא'
                conn.execute('INSERT INTO occurrence VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                             (f'{side}-{number}',page,page,page,'line',spelling,spelling,'{}',number,'original',1))
        # Same normalized key, different printed final letter and punctuation.
        for ident,spelling in (('final','אאאאך'),('ordinary','אאאאכ'),('punctuation','אאאאאא.')):
            conn.execute('INSERT INTO occurrence VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                         (ident,'evaluation-b','evaluation-b','evaluation-b','line',spelling,'אאאאאא','{}',99,'original',1))


def evaluate():
    outcomes=[]
    evaluate_drafts()
    outcomes.append('browser save queue retains rapid edits and retries completed meanings after reload')
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent,prefix='codex-tmp-saved-meanings-') as folder:
        folder=Path(folder)
        with database_scope(folder/'before.sqlite3'):
            migrate(initialize=True)
            seed()
            heads={}
            def save(word,text,*,remember=True,deleted=False,base=None):
                parent=heads.get(word,0) if base is None else base
                result=write_annotation(word,text,'ltr',parent,str(uuid.uuid4()),deleted,
                    [{'id':'base','role':'base','text':text,'direction':'ltr','char_range':None}],remember)
                if not result['conflict']:heads[word]=result['head_revision']
                return result
            # An ordinary autosave must not teach unfinished text.
            save('a-0','unfinished',remember=False)
            assert suggestions_for_word('b-0')['total']==0
            for number in range(32):
                for option in range(3):save(f'a-{number}',f'Meaning {option}')
                assert suggestions_for_word(f'b-{number}')['total']==3
            outcomes.append('32 spellings: three completed meanings recalled on another page')
            save('a-0','Meaning 0')
            assert suggestions_for_word('b-0')['total']==3
            outcomes.append('repeated meanings appear once; unfinished typing is excluded')
            conflict=save('a-0','Conflicting text',base=0)
            assert conflict['conflict'] and suggestions_for_word('b-0')['total']==3
            save('a-0','',deleted=True)
            assert suggestions_for_word('b-0')['total']==3
            outcomes.append('conflicting edits do not teach; removing an annotation preserves remembered choices')
            assert suggestions_for_word('punctuation')['total']==0
            save('final','Final-letter meaning')
            assert suggestions_for_word('ordinary')['total']==0
            outcomes.append('punctuation and final-letter differences remain distinct')
            for option in range(30):save('a-0',f'Additional meaning {option}')
            first=suggestions_for_word('b-0')
            last=suggestions_for_word('b-0',24)
            assert first['total']==33 and len(first['items'])==24 and len(last['items'])==9
            outcomes.append('all 33 choices remain available across list pages')
            for _ in range(100):suggestions_for_word('b-0')
            with read() as conn:
                assert conn.execute('SELECT count(*) FROM saved_meaning').fetchone()[0]==127
            outcomes.append('100 repeat lookups create no additional saved meanings')

            async def routes():
                from server.api import app,TOKEN
                transport=httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport,base_url='http://127.0.0.1:9473') as client:
                    response=await client.get('/api/suggestions/b-1')
                    response.raise_for_status()
                    choice=response.json()['items'][0]
                    body={'text':choice['text'],'direction':choice['direction'],'base_revision':0,
                          'operation_id':str(uuid.uuid4()),'remember_meaning':True,
                          'components':[{'id':'base','role':'base','text':choice['text'],'direction':choice['direction']}]}
                    response=await client.put('/api/annotations/b-1',json=body,headers={'x-shas-token':TOKEN})
                    response.raise_for_status()
                    assert response.json()['head_revision']==1 and not response.json()['conflict']
                    retry=await client.put('/api/annotations/b-1',json=body,headers={'x-shas-token':TOKEN})
                    retry.raise_for_status()
                    assert retry.json()['head_revision']==1
                    missing=await client.get('/api/dictionary')
                    assert missing.status_code==404
                    denied=await client.request('DELETE','/api/suggestions/b-1',json={'text':choice['text']})
                    assert denied.status_code==403
                    for _ in range(2):
                        deleted=await client.request('DELETE','/api/suggestions/b-1',json={'text':choice['text']},headers={'x-shas-token':TOKEN})
                        deleted.raise_for_status()
                    assert suggestions_for_word('a-1')['total']==2
                    assert suggestions_for_word('b-2')['total']==3
                    with read() as conn:
                        assert conn.execute('SELECT head_revision FROM annotation WHERE occurrence_id=?',('b-1',)).fetchone()[0]==1
            asyncio.run(routes())
            outcomes.append('actual API: select/persist; delete suggestion across same-spelling occurrences; repeat deletion; preserve annotation and other spellings; reject unauthorized deletion')
            snapshot=backup(directory=folder/'backups')
            payload=load_backup(snapshot)
            assert len(payload['saved_meanings'])==126
        with database_scope(folder/'after.sqlite3'):
            migrate(initialize=True)
            seed()
            with transaction() as conn:
                result=restore_into(conn,payload,select_heads=True)
                # The earlier deliberately conflicting edit remains in history.
                assert result['conflicts']==1 and result['unresolved']==0
            assert suggestions_for_word('b-0')['total']==33
            # A fresh connection establishes persisted memory after reopening.
            with read() as conn:
                assert conn.execute('SELECT count(*) FROM saved_meaning').fetchone()[0]==126
            assert suggestions_for_word('b-1')['total']==2
            outcomes.append('backup and restoration preserve all 126 remaining remembered pairs, deletion and annotation history')
    print(json.dumps({'passed':len(outcomes),'results':outcomes,'temporary_files':'removed'},indent=2))


def evaluate_reader_editing():
    """Exercise real Reader event handlers and render transitions, without UI control."""
    subprocess.run(['node','--input-type=commonjs'],input=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),ts=require('typescript');
const slots=[];let cursor=0,saves=[],effects=[],passiveEffects=[],focused=null,focusCalls=0;
const events=new Map();
const window={innerWidth:1000,addEventListener(name,fn){if(!events.has(name))events.set(name,new Set());events.get(name).add(fn)},removeEventListener(name,fn){events.get(name)?.delete(fn)}};
const dispatch=(name,event)=>{for(const fn of events.get(name)||[])fn(event)};
class TextArea {constructor(){this.dataset={piece:'base'}} focus(){focused=this;focusCalls++}}
const editors=new Map();
const react={useState(initial){const i=cursor++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return [slots[i],value=>slots[i]=typeof value==='function'?value(slots[i]):value]},useRef(value){const i=cursor++;return slots[i]??(slots[i]={current:value})},useMemo:fn=>fn(),useEffect(fn){passiveEffects.push(fn)},useLayoutEffect(fn,deps){const i=cursor++,previous=slots[i];if(!previous||deps.some((v,n)=>v!==previous[n]))effects.push(fn);slots[i]=deps}};
const jsx=(type,props,key)=>({type,props:props||{},key});
function load(path){const exports={};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,{exports,require:name=>{
 if(name==='react')return react;if(name==='react/jsx-runtime')return {jsx,jsxs:jsx};
 if(name==='react-dom')return {createPortal:node=>jsx('portal',{children:node})};
 if(name==='./components')return load('src/reader/components.ts');
 if(name==='./drafts')return {initializeDraft:()=>null,changeDraft:(...args)=>saves.push(args),draftStatus:()=> 'Saved',saveAllDrafts:async()=>{}};
 if(name==='./layout')return {layoutPage:(g,values)=>({height:100,offsets:{},annotations:Object.fromEntries(Object.entries(values).filter(([,v])=>v.trim()).map(([id,text])=>[id,{x:0,y:30,width:100,height:20,pieces:[{id:'base',y:0,height:20,fontSize:12}]}]))})};
 if(name==='./useReaderPosition')return {useReaderPosition(){}};
 if(name==='./useWordPopover')return {useWordPopover:()=>({menu:{current:null},position:{}})};
 if(name==='./sourceOrder')return {orderedWords:d=>d.geometry.words};
 if(name==='./SourceText')return {SourceText:()=>null};
 if(name==='../api')return {};throw Error(name);
},window,document:{body:{}},HTMLTextAreaElement:TextArea,requestAnimationFrame:()=>0});return exports;}
const {Reader}=load('src/reader/Reader.tsx');
const props={data:{geometry:{width:200,height:100,words:[{id:'synthetic',line:'line',text:'אא',normalized:'אא',x:0,r:20,top:0,bottom:20}],lines:[],regions:[]},annotations:[]},zoom:1,initialWord:'synthetic',destination:{serial:1},onPosition(){},onHistory(){},onCorrect(){},onSelected(){}};
function fields(node,path='root',found=[]){if(Array.isArray(node)){node.forEach((n,i)=>fields(n,path+'/'+i,found));return found}if(!node||typeof node!=='object')return found;if(node.type==='textarea')found.push({node,path});fields(node.props?.children,path+'/'+String(node.type),found);return found}
props.data.geometry.words.push({...props.data.geometry.words[0],id:'synthetic-next',x:30,r:50});
let tree;
function nodes(node,predicate,result=[]){if(Array.isArray(node)){node.forEach(n=>nodes(n,predicate,result));return result}if(!node||typeof node!=='object')return result;if(predicate(node))result.push(node);nodes(node.props?.children,predicate,result);return result}
function render(open=true){cursor=0;effects=[];passiveEffects=[];tree=Reader(props);const found=fields(tree);assert.equal(found.length,open?1:0,'one editor only while open');for(const {node} of found){if(!editors.has(node.key))editors.set(node.key,new TextArea());node.props.ref(editors.get(node.key))}for(const effect of effects)effect();return found[0]}
function press(key,options={}){const event={key,nativeEvent:{isComposing:false},currentTarget:new TextArea(),preventDefault(){this.defaultPrevented=true},...options};field.node.props.onKeyDown(event);return event}
let field=render();const path=field.path,key=field.node.key;
for(const value of ['a','ab','abc','','ש','של','שלום','svenska åäö','mixed שלום text']){
 field.node.props.onChange({target:{value}});field=render();
 assert.equal(field.path,path,'editor remains in the same tree location');assert.equal(field.node.key,key,'editor identity remains stable');
 assert.equal(field.node.props.value,value,'typing is retained without reordering');
}
field.node.props.onBlur();assert.ok(saves.at(-1)[5],'leaving the field remembers completed text');
press('Enter',{nativeEvent:{isComposing:true}});field=render();
press('Escape',{nativeEvent:{isComposing:true}});field=render();
const popup=nodes(tree,n=>n.props.className==='suggestions')[0];
popup.props.onKeyDown({key:'Escape',nativeEvent:{isComposing:true}});field=render();
const newline=press('Enter',{shiftKey:true});assert.ok(!newline.defaultPrevented,'Shift+Enter remains native');
field.node.props.onChange({target:{value:'first\nsecond'}});field=render();
press('Tab');field=render();assert.equal(field.node.key,'synthetic-next');
field.node.props.onChange({target:{value:'next word'}});field=render();
press('Tab',{shiftKey:true});field=render();assert.equal(field.node.props.value,'first\nsecond');assert.equal(field.node.props.dir,'auto');
const remove=nodes(tree,n=>n.props['aria-label']==='Remove selected meaning')[0];remove.props.onClick();render(false);
assert.ok(saves.at(-1)[3]&&saves.at(-1)[5],'Remove persists deletion');
const source=nodes(tree,n=>n.props.onActivate)[0];source.props.onActivate('synthetic');field=render();assert.equal(field.node.props.value,'');
assert.equal(focused,editors.get('synthetic'),'clicking a source word focuses its writing field immediately');
const focusedAtOpen=focusCalls;
field.node.props.onChange({target:{value:'ready to type'}});field=render();
assert.equal(focusCalls,focusedAtOpen,'typing does not refocus the field or reset its caret');
nodes(tree,n=>n.props.onActivate)[0].props.onSelecting();render(false);
nodes(tree,n=>n.props.onActivate)[0].props.onActivate('synthetic-next');field=render();
assert.equal(focused,editors.get('synthetic-next'),'switching words focuses the new writing field');
nodes(tree,n=>n.props.onActivate)[0].props.onActivate('synthetic');field=render();
field.node.props.onChange({target:{value:'retained on Enter'}});field=render();press('Enter');render(false);assert.ok(saves.at(-1)[5]);
nodes(tree,n=>n.props.onActivate)[0].props.onActivate('synthetic');field=render();assert.equal(field.node.props.value,'retained on Enter');
field.node.props.onChange({target:{value:'retained on Escape'}});field=render();press('Escape');render(false);assert.ok(saves.at(-1)[5]);
const classes=new Set();
const viewport={scrollLeft:200,scrollTop:300,classList:{add:name=>classes.add(name),remove:name=>classes.delete(name)},setPointerCapture(id){this.captured=id},hasPointerCapture(id){return this.captured===id},releasePointerCapture(){this.captured=null}};
tree.props.ref.current=viewport;
const cleanup=passiveEffects.map(effect=>effect()).filter(Boolean);
const pointer={button:0,altKey:true,pointerType:'mouse',pointerId:1,clientX:100,clientY:100,target:{closest:()=>null},currentTarget:viewport,preventDefault(){},stopPropagation(){}};
dispatch('keydown',{key:'Alt',target:{closest:()=>null},preventDefault(){}});assert.ok(classes.has('pan-ready'));
tree.props.onPointerDownCapture(pointer);assert.equal(viewport.captured,1);
tree.props.onPointerMove({...pointer,clientX:70,clientY:50});assert.equal(viewport.scrollLeft,230);assert.equal(viewport.scrollTop,350);
let suppressed=false;tree.props.onClickCapture({...pointer,preventDefault(){suppressed=true}});assert.ok(suppressed,'moving cannot open a word editor');
tree.props.onPointerUp(pointer);assert.equal(viewport.captured,null);
tree.props.onPointerMove({...pointer,clientX:0,clientY:0});assert.equal(viewport.scrollTop,350,'release stops movement');
tree.props.onPointerDownCapture(pointer);tree.props.onPointerCancel(pointer);viewport.captured=null;
tree.props.onPointerMove({...pointer,clientY:0});assert.equal(viewport.scrollTop,350,'cancel stops movement');
tree.props.onPointerDownCapture(pointer);dispatch('keyup',{key:'Alt'});assert.equal(viewport.captured,null);assert.ok(!classes.has('pan-ready'),'releasing Alt immediately returns to normal selection');
tree.props.onPointerMove({...pointer,clientY:0});assert.equal(viewport.scrollTop,350);
tree.props.onPointerDownCapture({...pointer,altKey:false});assert.equal(viewport.captured,null,'ordinary dragging remains text selection');
tree.props.onPointerDownCapture({...pointer,pointerType:'touch'});assert.equal(viewport.captured,null,'touch movement uses native scrolling');
tree.props.onPointerDownCapture({...pointer,altKey:false,button:1});assert.equal(viewport.captured,1,'middle button can pan without a key');
dispatch('blur',{});assert.equal(viewport.captured,null,'losing window focus cancels panning');
dispatch('keydown',{key:'Alt',target:{closest:()=>({})},preventDefault(){throw Error('Typing must retain Option/Alt combinations')}});assert.ok(!classes.has('pan-ready'));
dispatch('keydown',{key:' ',target:{closest:()=>null},preventDefault(){throw Error('Space must not be intercepted')}});
for(const dispose of cleanup)dispose();
render(false);
nodes(tree,n=>n.props.onActivate)[0].props.onActivate('synthetic');field=render();assert.equal(field.node.props.value,'retained on Escape');
console.log('Reader editing: typing, saved edits, Alt/middle-button dragging, key release, cancellation, blur, native touch scrolling and preserved typing/Space behavior passed. Native graphical interaction was not automated.');
''',text=True,check=True,cwd=Path(__file__).resolve().parent)


def evaluate_reader_fonts():
    """Exercise original-font delivery across source pages without word inspection."""
    from io import BytesIO
    from fontTools.ttLib import TTFont
    from server.api import page_data, source_font
    from server.extract import load_geometry,cff_glyphs,ttf_glyphs
    from server.prepare_fonts import embedded_fonts
    with read() as conn:
        pages=[r[0] for r in conn.execute('''SELECT id FROM page
            WHERE active_revision IS NOT NULL ORDER BY sequence LIMIT 6''')]
    count=0
    total=0
    for page_id in pages:
        with read() as conn:
            original=load_geometry(page_id,conn,include_artwork=False)
            asset=conn.execute('SELECT asset_path FROM page WHERE id=?',(page_id,)).fetchone()[0]
        assets=embedded_fonts(asset)
        metrics={key:(cff_glyphs(data) if ext=='cff' else ttf_glyphs(data)) for key,(ext,data) in assets.items()}
        ratios=[]
        for word in original['words']:
            for glyph in word.get('glyphs',[]):
                metric=metrics.get(glyph['font'],{}).get(glyph['glyph'],{})
                if metric.get('advance') and glyph.get('size'):
                    ratios.append((glyph['r']-glyph['x'])*metric['units']/metric['advance']/glyph['size'])
        print(f'Source horizontal scale: {min(ratios):.4f}–{max(ratios):.4f}; {sum(abs(r-1)>.01 for r in ratios)} letters differ from unscaled type',flush=True)
        data=page_data(page_id)
        fonts=data['geometry'].get('fonts',[])
        if not fonts:raise RuntimeError('No original fonts delivered')
        glyphs=[g for word in data['geometry']['words'] for g in word.get('source_glyphs',[])]
        print(f'Source text: {len(glyphs)} positioned letters; {sum(len(g["text"])!=1 for g in glyphs)} multi-character glyphs; {sum(not w.get("source_glyphs") for w in data["geometry"]["words"])} words without original glyph placement',flush=True)
        for font in fonts:
            response=source_font(page_id,font['id'])
            loaded=TTFont(BytesIO(response.body))
            if not loaded.getBestCmap():raise RuntimeError('Empty source font character map')
            loaded.close()
            count+=1;total+=len(response.body)
        print(f'Original-font delivery: {page_id}, {len(fonts)} fonts',flush=True)
    print(f'Loaded {count} browser fonts across {len(pages)} pages; {total} bytes; no font files written.')


def storage_inventory():
    from server.config import DATA
    with read() as conn:
        revisions=[dict(row) for row in conn.execute('SELECT id,geometry_path,vector_path FROM page_revision')]
        active=conn.execute('SELECT count(*) FROM page WHERE active_revision IS NOT NULL').fetchone()[0]
    referenced={str((DATA/row[key]).resolve()) for row in revisions for key in ('geometry_path','vector_path') if row[key]}
    report={'active_pages':active,'retained_revisions':len(revisions),'folders':{}}
    for name in ('geometry','vectors'):
        files=[p for p in (DATA/name).iterdir() if p.is_file()]
        kept=[p for p in files if str(p.resolve()) in referenced]
        unused=[p for p in files if str(p.resolve()) not in referenced]
        report['folders'][name]={'files':len(files),'referenced':len(kept),'unreferenced':len(unused),
            'kept_bytes':sum(p.stat().st_size for p in kept),'unreferenced_bytes':sum(p.stat().st_size for p in unused)}
    report['missing_referenced_files']=sum(not Path(path).is_file() for path in referenced)
    print(json.dumps(report,indent=2))


def distribution_inventory():
    """Measure retained structures without inspecting individual dictionary words."""
    import lzma
    import hashlib
    import sqlite3
    from collections import Counter
    from server.config import DATA
    from server.content_codec import decode_page
    from server.compact_page import encode as compact_encode,decode as compact_decode,share
    import time
    corpus=DATA/'prepared';paths=sorted((corpus/'pages').glob('*.shas'));sample=paths[::450]
    totals=Counter();word_fields=Counter();glyph_fields=Counter();counts=Counter()
    started=time.monotonic();compact_bytes=0;before=[];after=[];compact_parts=Counter();shared_values=[];shared_indices={};shared_bytes=0
    def size(value):return len(lzma.compress(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode(),preset=0))
    for path in sample:
        page=decode_page(path.read_bytes())
        compact=compact_encode(page);compact_bytes+=len(compact)
        import struct
        raw=lzma.decompress(compact[5:]);header_size=struct.unpack_from('<I',raw)[0]
        header,strings=json.loads(raw[4:4+header_size]);binary=raw[4+header_size:]
        for name,value in zip(('metadata','counts','words','lines','regions','bases','glyphs','metrics'),header):
            compact_parts[name]+=size(value)
            if name in ('words','lines','regions','bases','glyphs'):
                for column in value[1]:
                    if column[2]=='f':
                        offset,count=column[3:]
                        compact_parts[name+'.'+column[0]]+=len(lzma.compress(binary[offset:offset+count*8]))
        compact_parts['strings']+=size(strings)
        restored=compact_decode(compact)
        shared=share(compact,shared_values,shared_indices);shared_bytes+=len(shared)
        restored=compact_decode(shared,shared_values)
        for output,value in ((before,page),(after,restored)):
            output.append(path.name+' '+hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest())
        for key,value in page.items():totals[key]+=size(value)
        words=page['words'];glyphs=[g for w in words for g in w.get('glyphs',[])]
        counts.update(words=len(words),glyphs=len(glyphs))
        for word in words:
            values=[(round(g['origin_x'],3),round(g['baseline'],3),g.get('source_font',g['font']),g.get('source_glyph',g['glyph'])) for g in word.get('glyphs',[])]
            candidate=page['id']+':word:'+hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]
            counts['reconstructible_word_ids']+=candidate==word['id']
        for key in {k for w in words for k in w}:word_fields[key]+=size([w.get(key) for w in words])
        for key in {k for g in glyphs for k in g}:glyph_fields[key]+=size([g.get(key) for g in glyphs])
    with sqlite3.connect(corpus/'fonts.sqlite3') as fonts:
        from server.font_chunks import chunks
        import zlib
        font_info={table:fonts.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('font_blob','font','template')}
        font_info['compressed_blob_bytes']=fonts.execute('SELECT sum(length(content)) FROM font_blob').fetchone()[0]
        shared={};references=0;original=0;raw_bytes=0
        for index,(content,) in enumerate(fonts.execute('SELECT content FROM font_blob')):
            if index%100:continue
            original+=len(content);data=zlib.decompress(content);raw_bytes+=len(data)
            for part in chunks(data):
                key=hashlib.sha256(part).digest();shared.setdefault(key,len(zlib.compress(part,9)));references+=1
        font_info.update(sample_original=original,sample_raw=raw_bytes,sample_shared=sum(shared.values()),sample_references=references*4,sample_chunks=len(shared))
    first=Path('codex-tmp-page-before.txt');second=Path('codex-tmp-page-after.txt')
    try:
        first.write_text('\n'.join(before)+'\n');second.write_text('\n'.join(after)+'\n')
        subprocess.run(['diff','-u',str(first),str(second)],check=True)
    finally:first.unlink(missing_ok=True);second.unlink(missing_ok=True)
    print(json.dumps({'sample_pages':len(sample),'all_page_bytes':sum(p.stat().st_size for p in paths),
        'compact_sample_bytes':compact_bytes,
        'shared_sample_bytes':shared_bytes,'shared_measurements_bytes':size(shared_values),'shared_measurements_count':len(shared_values),
        'compact_parts':compact_parts,
        'sample_page_bytes':sum(p.stat().st_size for p in sample),'seconds':time.monotonic()-started,
        'counts':counts,'page_fields_compressed':totals,'word_fields_compressed':word_fields,
        'glyph_fields_compressed':glyph_fields,'fonts':font_info},indent=2))


def compact_font_outputs():
    """Produce complete original/restored font digests for direct diff."""
    import hashlib
    import sqlite3
    from contextlib import closing
    from server.font_chunks import restore
    before=Path('codex-tmp-fonts-before.txt');after=Path('codex-tmp-fonts-after.txt')
    with closing(sqlite3.connect('file:data/prepared-compact/fonts.sqlite3?mode=ro',uri=True)) as conn,before.open('w') as left,after.open('w') as right:
        for i,(sha,content) in enumerate(conn.execute('SELECT sha,content FROM font_blob ORDER BY sha'),1):
            left.write(sha.hex()+'\n');right.write(hashlib.sha256(restore(conn,content)).hexdigest()+'\n')
            if i%10000==0:print(f'Reconstructed {i} complete fonts',flush=True)
    subprocess.run(['diff','-u',str(before),str(after)],check=True)
    with closing(sqlite3.connect('file:data/prepared/fonts.sqlite3?mode=ro',uri=True)) as original,closing(sqlite3.connect('file:data/prepared-compact/fonts.sqlite3?mode=ro',uri=True)) as compact:
        for table,columns in (('font','id,sha'),('template','fingerprint,font_id')):
            before.write_text('\n'.join('|'.join(row) for row in original.execute('SELECT '+columns+' FROM '+table+' ORDER BY 1'))+'\n')
            after.write_text('\n'.join('|'.join(value.hex() for value in row) for row in compact.execute('SELECT '+columns+' FROM '+table+' ORDER BY 1'))+'\n')
            subprocess.run(['diff','-u',str(before),str(after)],check=True)
    before.unlink();after.unlink()
    print('All 97,782 font files and all font/template references match the original output.',flush=True)


def compact_search_outputs():
    """Compare complete indexed page membership and search result outputs."""
    import hashlib
    import sqlite3
    from contextlib import closing
    from server.retained_pages import page_search_query
    before=Path('codex-tmp-search-before.txt');after=Path('codex-tmp-search-after.txt')
    for directory,output in (('prepared',before),('prepared-compact',after)):
        with closing(sqlite3.connect(f'file:data/{directory}/catalogue.sqlite3?mode=ro&immutable=1',uri=True)) as conn:
            conn.execute('PRAGMA temp_store=MEMORY')
            conn.execute("CREATE VIRTUAL TABLE temp.terms USING fts5vocab(main,retained_page_text,'instance')")
            digest=hashlib.sha256();count=0
            for term,doc in conn.execute('SELECT DISTINCT term,doc FROM temp.terms ORDER BY term,doc'):
                digest.update(json.dumps([term,doc],ensure_ascii=False,separators=(',',':')).encode()+b'\n');count+=1
            output.write_text(f'{count} {digest.hexdigest()}\n')
    subprocess.run(['diff','-u',str(before),str(after)],check=True)
    print(f'All {count:,} search-term/page memberships match.',flush=True)
    queries=['alpha beta','beta alpha','alpha-beta','alpha','beta','a"b','Café','Cafe\u0301','123.45','"',chr(0x5d0)+chr(0x5b7)+chr(0x5d1)]
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.execute("CREATE VIRTUAL TABLE exact USING fts5(text,normalized,tokenize='unicode61 remove_diacritics 2')")
        conn.execute("CREATE VIRTUAL TABLE coarse USING fts5(text,normalized,detail=none,tokenize='unicode61 remove_diacritics 2')")
        for text in queries:
            conn.execute('INSERT INTO exact VALUES(?,?)',(text,''));conn.execute('INSERT INTO coarse VALUES(?,?)',(text,''))
        with before.open('w') as left,after.open('w') as right:
            for i,q in enumerate(queries):
                exact='text : "'+q.replace('"','""')+'"';candidate=page_search_query(q)
                original=[row[0] for row in conn.execute('SELECT rowid FROM exact WHERE exact MATCH ? ORDER BY rowid',(exact,))]
                restored=[row[0] for row in conn.execute('SELECT rowid FROM exact WHERE exact MATCH ? AND rowid IN (SELECT rowid FROM coarse WHERE coarse MATCH ?) ORDER BY rowid',(exact,candidate))] if candidate else []
                left.write(json.dumps([i,original])+'\n');right.write(json.dumps([i,restored])+'\n')
    subprocess.run(['diff','-u',str(before),str(after)],check=True)
    before.unlink();after.unlink()
    print('Exact search outputs match for phrases, reordered terms, punctuation, quotes, accents, numbers and combining marks.',flush=True)


def evaluate_installation():
    """Exercise first install, replacement, backup and process-lock release."""
    import os
    import shutil
    import sys
    root=Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='codex-tmp-installation-',dir=root) as directory:
        base=Path(directory);corpus=base/'application'/'prepared';corpus.mkdir(parents=True)
        user=base/'personal-work'
        with database_scope(corpus/'catalogue.sqlite3'):
            migrate(initialize=True)
        (corpus/'manifest.json').write_text(json.dumps({'format':'shas-corpus-1','complete':True,'page_count':0,'pages':{}}))
        env={**os.environ,'NODE_ENV':'production','SHAS_CORPUS':str(corpus),'SHAS_USER_DATA':str(user)}
        initialize='from server.user_install import initialize_user_data; initialize_user_data()'
        def child(code,**kwargs):
            return subprocess.run([sys.executable,'-c',code],env=env,cwd=root,text=True,check=True,**kwargs)
        child(initialize)
        child("from server.db import transaction; from server.saved_meanings import remember\nwith transaction() as conn: remember(conn,'synthetic-installation','Persistent meaning','ltr')")
        # Replace the application directory, exactly as an installer/update does.
        replacement=base/'replacement'/'prepared';replacement.parent.mkdir()
        shutil.copytree(corpus,replacement);shutil.rmtree(corpus.parent)
        env['SHAS_CORPUS']=str(replacement)
        child(initialize)
        child("from server.db import read,backup,load_backup\nwith read() as conn:\n assert conn.execute('SELECT count(*) FROM saved_meaning').fetchone()[0]==1\npath=backup('installation-evaluation')\nassert path.parent.name=='backups'\nassert load_backup(path)['saved_meanings'][0]['text']=='Persistent meaning'")
        print('User-data lifecycle: first install, application replacement, saved meaning and default-location backup passed',flush=True)
        holder=subprocess.Popen([sys.executable,'-c',
            "from server.source_jobs import source_lock\nwith source_lock('installation-evaluation'):\n print('locked',flush=True)\n input()"],
            env=env,cwd=root,text=True,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        try:
            if holder.stdout.readline().strip()!='locked':raise RuntimeError('Lock holder did not start')
            child("from server.source_jobs import source_lock,SourceJobBusy\ntry:\n with source_lock('installation-evaluation',blocking=False): raise AssertionError('Concurrent writer acquired lock')\nexcept SourceJobBusy: pass")
            holder.kill();holder.wait(timeout=10)
            child("from server.source_jobs import source_lock\nwith source_lock('installation-evaluation',blocking=False): pass")
        finally:
            if holder.poll() is None:holder.kill();holder.wait(timeout=10)
            holder.stdin.close();holder.stdout.close()
        print(f'Process locks: concurrent writer refused; killed writer released lock on {sys.platform}',flush=True)
        (user/'shasmaster.sqlite3').unlink()
        result=subprocess.run([sys.executable,'-c',initialize],env=env,cwd=root,text=True,capture_output=True)
        if result.returncode==0:raise RuntimeError('Missing personal database was silently replaced')
        print('Missing saved-work database: replacement refused; backup remains available',flush=True)


def content_outputs():
    """Produce canonical source/decoded digests and use diff for the comparison."""
    import gzip
    import hashlib
    from server.config import DATA
    from server.content_codec import encode_page,decode_page
    from server.db import json_text
    root=Path(__file__).resolve().parent
    with read() as conn:
        rows=conn.execute('SELECT p.id,r.geometry_path FROM page p JOIN page_revision r ON r.id=p.active_revision WHERE p.sequence%450=0 ORDER BY p.sequence').fetchall()
    with tempfile.TemporaryDirectory(prefix='codex-tmp-content-',dir=root) as directory:
        original=Path(directory)/'original.txt';decoded=Path(directory)/'decoded.txt'
        with original.open('w') as first,decoded.open('w') as second:
            for row in rows:
                with gzip.open(DATA/row['geometry_path'],'rt',encoding='utf-8') as source:page=json.load(source)
                first.write(row['id']+' '+hashlib.sha256(json_text(page).encode()).hexdigest()+'\n')
                second.write(row['id']+' '+hashlib.sha256(json_text(decode_page(encode_page(page))).encode()).hexdigest()+'\n')
        subprocess.run(['diff','-u',str(original),str(decoded)],check=True)
    print(f'Canonical content outputs: diff found no changes in {len(rows)} pages distributed across the corpus; temporary outputs removed',flush=True)


def font_source_structure():
    """Inspect font resource structure only; do not inspect word meanings."""
    import pymupdf
    import xml.etree.ElementTree as ET
    from server.config import DATA
    with read() as conn:
        asset=conn.execute('SELECT asset_path FROM page WHERE id=?',('meilah-22a',)).fetchone()[0]
    with pymupdf.open(DATA/asset) as document:
        svg=ET.fromstring(document[0].get_svg_image(text_as_path=True))
        uses=[node for node in svg.iter() if node.tag.endswith('}use')]
        paths=[node for node in svg.iter() if node.tag.endswith('}path') and node.get('id')]
        print(json.dumps({'uses':[dict(node.attrib) for node in uses[:4]],
            'paths':[dict(node.attrib)|{'d':node.get('d','')[:100]} for node in paths[:4]],
            'fonts':[list(font[:5]) for font in document[0].get_fonts(full=True)]},indent=2))


def evaluate_frozen_backend(web=False,native=False,browser=False):
    """Exercise the actual Release executable without source assets or Python on PATH."""
    import os
    import socket
    import time
    import sqlite3
    import shutil
    from contextlib import closing
    root=Path(__file__).resolve().parent
    executable=Path(os.environ.get('SHAS_EVALUATE_BINARY',str(root/'.desktop-build/runtime/shas-backend'/('shas-backend.exe' if os.name=='nt' else 'shas-backend'))))
    command=[str(executable),'--configuration','Release']
    if browser:command.append('--open-browser')
    if web:
        node=shutil.which('node')
        if not node:raise RuntimeError('Node is required for the web launcher')
        command=[node,str(root/'web/start.cjs')]
    if native:
        native_app=Path(os.environ.get('SHAS_WINDOWS_APP',str(root/'.desktop-build/windows-launcher/ShasMaster.exe'))) if os.name=='nt' else root/'out/native-mac/Shas Master.app/Contents/MacOS/ShasMaster'
        command=[str(native_app),'--verify-service']
    corpus=Path(os.environ.get('SHAS_EVALUATE_CORPUS',str(root/'data/prepared')))
    if native:corpus=native_app.parent/'prepared' if os.name=='nt' else root/'out/native-mac/Shas Master.app/Contents/Resources/prepared'
    manifest=json.loads((corpus/'manifest.json').read_text())
    if not manifest.get('complete'):raise RuntimeError('Content preparation is incomplete')
    with closing(sqlite3.connect((corpus/'catalogue.sqlite3').as_uri()+'?mode=ro',uri=True)) as conn:
        private={name:conn.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                 for name in ('annotation','annotation_revision','saved_meaning','bookmark','preference','correction','operation')}
    if any(private.values()):raise RuntimeError('Personal records found in distributable catalogue')
    print('Distributable catalogue contains no personal work',flush=True)
    with tempfile.TemporaryDirectory(prefix='codex-tmp-frozen-',dir=root) as directory:
        base=Path(directory);userdata=base/'user';logfile=base/'backend.log'
        with socket.socket() as available:
            available.bind(('127.0.0.1',0));port=available.getsockname()[1]
        env={**os.environ,'NODE_ENV':'production','SHAS_CORPUS':str(corpus),
             'SHAS_USER_DATA':str(userdata),'SHAS_DATA':str(base/'no-source-assets'),
             'SHAS_FRONTEND':os.environ.get('SHAS_EVALUATE_FRONTEND',str(root/'dist')),'SHAS_PORT':str(port),'PYTHONPATH':'',
             'PATH':os.environ.get('SystemRoot',r'C:\Windows')+'\\System32' if os.name=='nt' else '/usr/bin:/bin'}
        if browser:
            opener=base/'browser-opener'
            opener.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$SHAS_BROWSER_CAPTURE"\n')
            opener.chmod(0o700)
            env['BROWSER']=str(opener)
            env['SHAS_BROWSER_CAPTURE']=str(base/'browser-opened')
        process=None
        def start():
            nonlocal process
            with logfile.open('a') as output:
                process=subprocess.Popen(command,env=env,cwd=base,
                                         stdout=output,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError(logfile.read_text()[-4000:])
                try:
                    response=httpx.get(f'http://127.0.0.1:{port}/api/session',timeout=1)
                    if response.status_code==200:return response.json()['token']
                except httpx.HTTPError:pass
                time.sleep(.1)
            raise RuntimeError('Release executable did not start: '+logfile.read_text()[-4000:])
        def stop():
            nonlocal process
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
                if native:
                    if os.name=='nt':
                        powershell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
                        result=subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-Command',
                            "$ErrorActionPreference='Stop'; "
                            f"$listeners=@(Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq {port}); "
                            "if ($listeners.Count -ne 0) { exit 1 }"],capture_output=True,text=True,timeout=30)
                        if result.returncode!=0:
                            raise RuntimeError('Reader service remained listening or Windows could not inspect it: '+result.stderr)
                    else:
                        try:
                            httpx.get(f'http://127.0.0.1:{port}/api/session',timeout=1)
                        except httpx.ConnectError:pass
                        else:raise RuntimeError('Reader service stayed running after the app closed')
            process=None
        try:
            token=start()
            if browser:
                limit=time.monotonic()+5
                while not (base/'browser-opened').exists() and time.monotonic()<limit:time.sleep(.05)
                if not (base/'browser-opened').exists():raise RuntimeError('Application did not open the reader automatically')
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=60,headers={'x-shas-token':token}) as client:
                interface=client.get('/');interface.raise_for_status()
                if 'text/html' not in interface.headers.get('content-type',''):raise RuntimeError('Packaged interface unavailable')
                if web:
                    client.get('/manifest.webmanifest').raise_for_status()
                    client.get('/icon.svg').raise_for_status()
                catalogue=client.get('/api/catalogue');catalogue.raise_for_status()
                pages=catalogue.json()['pages'];selected=pages[::450]
                # Exercise runtime cmap construction for duplicate-Unicode
                # source outlines, not only fonts already stored in the package.
                selected.extend(page for page in pages if page['id'] in ('bechoros-8b','arachin-5b','yoma-24b') and page not in selected)
                first=None;fonts=0
                for page in selected:
                    response=client.get('/api/pages/'+page['id']);response.raise_for_status();data=response.json()
                    if first is None:first=data
                    for font in data['geometry']['fonts']:
                        response=client.get(font['url']);response.raise_for_status()
                        if not response.content:raise RuntimeError('Empty packaged font')
                        fonts+=1
                occurrence=first['geometry']['words'][0]['id'];page_id=first['page']['id']
                response=client.put('/api/annotations/'+occurrence,json={'base_revision':0,'operation_id':str(uuid.uuid4()),
                    'text':'Installed persistence check','direction':'ltr','remember_meaning':True});response.raise_for_status()
                client.put('/api/bookmarks/'+page_id,json={'occurrence_id':occurrence,'label':'Release evaluation'}).raise_for_status()
                client.put('/api/preferences/release-evaluation',json={'value':'retained'}).raise_for_status()
                client.post('/api/backups').raise_for_status()
                response=client.get('/api/pages/'+page_id+'/source/'+occurrence+'/image');response.raise_for_status()
                if 'image/svg+xml' not in response.headers.get('content-type',''):raise RuntimeError('Correction preview did not use prepared outlines')
            stop();token=start()
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=60,headers={'x-shas-token':token}) as client:
                remembered=client.get('/api/suggestions/'+occurrence);remembered.raise_for_status()
                if not any(item['text']=='Installed persistence check' for item in remembered.json()['items']):raise RuntimeError('Saved meaning lost after restart')
                response=client.get('/api/pages/'+page_id);response.raise_for_status()
                if not any(item['text']=='Installed persistence check' for item in response.json()['annotations']):raise RuntimeError('Annotation lost after restart')
                if not client.get('/api/bookmarks').json():raise RuntimeError('Bookmark lost after restart')
                if client.get('/api/preferences').json().get('release-evaluation')!='retained':raise RuntimeError('Preference lost after restart')
                snapshots=client.get('/api/backups').json()
                if not snapshots:raise RuntimeError('Backup missing after restart')
                client.post('/api/backups/'+snapshots[0]['name']+'/restore').raise_for_status()
                response=client.request('DELETE','/api/suggestions/'+occurrence,json={'text':'Installed persistence check'});response.raise_for_status()
                if client.get('/api/suggestions/'+occurrence).json()['total']!=0:raise RuntimeError('Remembered meaning was not removed')
            print(f'{"Native app" if native else "Web launcher" if web else "Frozen Release"}: {len(pages)} catalogue pages; {len(selected)} pages and {fonts} fonts loaded without source assets; outline preview, save/restart, bookmark, preference, backup/restore and suggestion deletion passed',flush=True)
        finally:
            stop()


def work_outputs():
    """Print preservation evidence using a direct diff of saved work exports."""
    import os
    from server.annotations import export_from_connection
    root=Path(__file__).resolve().parent
    paths=[Path(os.environ['SHAS_COMPARE_SOURCE']),Path(os.environ['SHAS_COMPARE_DESTINATION'])]
    outputs=[root/'codex-tmp-work-before.json',root/'codex-tmp-work-after.json']
    try:
        for path,output in zip(paths,outputs):
            with read(path) as conn:
                payload=export_from_connection(conn)
            work={key:sorted(payload.get(key,[]),key=lambda item:json.dumps(item,sort_keys=True))
                  for key in ('annotations','heads','saved_meanings','bookmarks','preferences','corrections','recovery')}
            output.write_text(json.dumps(work,ensure_ascii=False,sort_keys=True,indent=2))
            print(path, {key:len(value) for key,value in work.items()},flush=True)
        subprocess.run(['diff','-u',str(outputs[0]),str(outputs[1])],check=True)
    finally:
        for output in outputs:output.unlink(missing_ok=True)


def verify_linux_signature():
    root=Path(__file__).resolve().parent
    import os
    package=Path(os.environ.get('SHAS_LINUX_PACKAGE',str(root/'release/Shas-Master-x86_64.AppImage')))
    subprocess.run(['gpg','--verify',str(package)+'.asc',str(package)],check=True)
    print('Linux installer bytes:',package.stat().st_size,flush=True)


def evaluate_notarization_flow():
    """Exercise saved submission recovery without uploading an installer."""
    subprocess.run(['node','--input-type=commonjs'],input=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync('native/notarize-mac.cjs','utf8');
const files=new Map();let uploads=0,staples=0,status='In Progress',interrupt=false,modified=1;
const fakeFS={existsSync:p=>files.has(p),statSync:()=>({size:100,mtimeMs:modified}),
 readFileSync:p=>files.get(p),writeFileSync(p,value,options){if(options?.flag==='wx'&&files.has(p))throw Error('exists');files.set(p,value)}};
function invoke(){
 const process={platform:'darwin',argv:['node','script','Release'],env:{SHAS_NOTARY_PROFILE:'fixture'},exitCode:0};
 vm.runInNewContext(source,{__dirname:path.resolve('native'),process,console:{log(){},error(){}},require:name=>{
  if(name==='node:fs')return fakeFS;if(name==='node:path')return path;
  if(name==='node:child_process')return {spawnSync(command,args){
   if(args[0]==='notarytool'&&args[1]==='submit'){uploads++;if(interrupt)return {status:1,stderr:'interrupted'};return {status:0,stdout:JSON.stringify({id:'submission-fixture'})}}
   if(args[0]==='notarytool'&&args[1]==='info')return {status:0,stdout:JSON.stringify({status})};
   if(args[0]==='stapler'&&args[1]==='staple'){staples++;modified++}
   return {status:0};
  }};throw Error(name);
 }});return process.exitCode;
}
assert.equal(invoke(),2);assert.equal(uploads,1);assert.equal(staples,0);
assert.equal(invoke(),2);assert.equal(uploads,1,'pending submission must not be uploaded again');
status='Accepted';assert.equal(invoke(),0);assert.equal(staples,1);
assert.equal(invoke(),0);assert.equal(uploads,1,'accepted submission must be reused');
modified++;assert.equal(invoke(),1,'changed installer must not reuse old approval');
files.clear();interrupt=true;assert.equal(invoke(),1);const uploaded=uploads;
interrupt=false;assert.equal(invoke(),1);assert.equal(uploads,uploaded,'interrupted upload must not be silently repeated');
files.clear();status='Invalid';assert.equal(invoke(),1);assert.equal(staples,2,'rejected installer must not be stapled');
console.log('Approval workflow: pending/accepted submission reuse, changed-installer refusal, interrupted-upload recovery guard and rejection handling passed. No Apple submission performed.');
''',text=True,check=True,cwd=Path(__file__).resolve().parent)


def verify_mac_release():
    import plistlib
    import platform
    root=Path(__file__).resolve().parent
    architecture='arm64' if platform.machine()=='arm64' else 'x64'
    import os
    application=Path(os.environ.get('SHAS_MAC_APP',str(root/'out/native-mac/Shas Master.app')))
    image=Path(os.environ.get('SHAS_MAC_INSTALLER',str(root/f'release/Shas-Master-Native-macOS-{architecture}.dmg')))
    subprocess.run(['codesign','--verify','--deep','--strict','--verbose=2',str(application)],check=True)
    subprocess.run(['codesign','--verify','--strict','--verbose=2',str(image)],check=True)
    subprocess.run(['codesign','--display','--verbose=2',str(application)],check=True)
    subprocess.run(['hdiutil','verify',str(image)],check=True)
    with (application/'Contents/_CodeSignature/CodeResources').open('rb') as source:
        seals=plistlib.load(source).get('files2',{})
    resources=application/'Contents/Resources'
    print(json.dumps({'installer_bytes':image.stat().st_size,
        'prepared_pages':len(list((resources/'prepared/pages').glob('*.shas'))),
        'sealed_prepared_pages':sum(name.startswith('Resources/prepared/pages/') for name in seals),
        'packaged_pdfs':len(list(resources.rglob('*.pdf')))},indent=2),flush=True)
    assessment=subprocess.run(['spctl','--assess','--type','execute','--verbose=2',str(application)],capture_output=True,text=True)
    print('Gatekeeper assessment:',assessment.returncode,(assessment.stdout+assessment.stderr).strip(),flush=True)
    if assessment.returncode:
        raise RuntimeError('Mac release is not ready: Gatekeeper rejected the application')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['saved-meanings','reader-ux','reader-fonts','reader-editing','storage-inventory','distribution-inventory','compact-font-outputs','compact-search-outputs','installation','content-outputs','font-source-structure','frozen-backend','mac-release','work-outputs','web-runtime','native-runtime','browser-runtime','linux-signature','notarization-flow'])
    args=parser.parse_args()
    if args.command=='notarization-flow':evaluate_notarization_flow()
    elif args.command=='linux-signature':verify_linux_signature()
    elif args.command=='browser-runtime':evaluate_frozen_backend(browser=True)
    elif args.command=='native-runtime':evaluate_frozen_backend(native=True)
    elif args.command=='web-runtime':evaluate_frozen_backend(web=True)
    elif args.command=='work-outputs':work_outputs()
    elif args.command=='mac-release':verify_mac_release()
    elif args.command=='frozen-backend':evaluate_frozen_backend()
    elif args.command=='font-source-structure':font_source_structure()
    elif args.command=='content-outputs':content_outputs()
    elif args.command=='installation':evaluate_installation()
    elif args.command=='distribution-inventory':distribution_inventory()
    elif args.command=='compact-font-outputs':compact_font_outputs()
    elif args.command=='compact-search-outputs':compact_search_outputs()
    elif args.command=='storage-inventory':storage_inventory()
    elif args.command=='reader-editing':evaluate_reader_editing()
    elif args.command=='reader-fonts':evaluate_reader_fonts()
    elif args.command=='reader-ux':evaluate_reader_ux()
    else:evaluate()
