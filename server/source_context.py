"""Assemble source passages from printed geometry, without translating them."""
from collections import Counter
from statistics import median
import gzip
import json
import logging
import re
from .config import DATA
from .db import digest

REVISION='printed-sentence-5'
TERMINAL=re.compile(r'[.!?:\u05c3][\s\"\u05f4\u201d\u2019\)\]]*$')
logger=logging.getLogger(__name__)

def printed_blocks(geometry):
    if 'prepared_reading_blocks' in geometry:
        return geometry['prepared_reading_blocks']
    from .config import CORPUS
    if CORPUS:
        from .prepared_content import reading_blocks
        return reading_blocks(geometry['id'])
    keys={word.get('ocr',{}).get('evidence') for word in geometry['words']}
    keys.update(issue.get('evidence') for issue in geometry.get('issues',[]))
    for key in sorted(value for value in keys if isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value)):
        path=DATA/'ocr'/(key+'.json.gz')
        if not path.is_file():continue
        try:
            with gzip.open(path,'rt',encoding='utf-8') as source:record=json.load(source)
        except (OSError,EOFError,ValueError):
            logger.warning('Printed layout evidence unavailable: %s',key,exc_info=True)
            continue
        clip=record['clip']
        if record.get('psm')==3 and clip[2]-clip[0]>=geometry['width']*.99 and clip[3]-clip[1]>=geometry['height']*.99:
            return record.get('regions',[])
    return []

def reading_flows(geometry):
    words={word['id']:word for word in geometry['words']}
    regions={region['id']:region for region in geometry['regions']}
    region_lines=Counter(line['region'] for line in geometry['lines'])
    blocks=printed_blocks(geometry)
    def block_for(line):
        overlaps=[]
        for block in blocks:
            left,top,right,bottom=block['bounds']
            area=max(0,min(right,line['r'])-max(left,line['x']))*max(0,min(bottom,line['bottom'])-max(top,line['top']))
            if area>=(line['r']-line['x'])*(line['bottom']-line['top'])*.6:overlaps.append((area,block['id']))
        return max(overlaps)[1] if overlaps else None
    def explicit_regions(ids):
        return {rid for rid in ids if region_lines[rid]>1 or regions.get(rid,{}).get('kind','unclassified')!='unclassified'}
    fragments=[]
    for line in geometry['lines']:
        members=[words[wid] for wid in line['words'] if wid in words]
        if not members:continue
        fonts=Counter(glyph['font'] for word in members for glyph in word.get('glyphs',[]) if glyph.get('font'))
        fragments.append({**line,'members':members,'block':block_for(line),'fonts':{font for font,count in fonts.items() if count>=max(fonts.values(),default=1)*.3}})
    # The native extractor can split a justified printed line at a wide space.
    # Join those fragments only when their baseline and typography agree.
    rows=[]
    for fragment in sorted(fragments,key=lambda line:(line['baseline'],line['x'])):
        match=None
        for row in reversed(rows):
            if row['block'] and fragment['block'] and row['block']!=fragment['block']:continue
            if (explicit_regions(row['regions']) or explicit_regions({fragment['region']})) and fragment['region'] not in row['regions']:continue
            size=min(row['size'],fragment['size'])
            if fragment['baseline']-row['baseline']>max(.8,size*.12):continue
            gap=max(row['x'],fragment['x'])-min(row['r'],fragment['r'])
            ratio=max(row['size'],fragment['size'])/max(.1,size)
            same_font=bool(row['fonts']&fragment['fonts'])
            if ratio<=1.3 and 0<=gap<=size*(2 if same_font else .55):
                match=row;break
        if match is None:
            rows.append({**fragment,'regions':{fragment['region']},'line_ids':[fragment['id']]})
        else:
            match['x']=min(match['x'],fragment['x']);match['r']=max(match['r'],fragment['r'])
            match['top']=min(match['top'],fragment['top']);match['bottom']=max(match['bottom'],fragment['bottom'])
            match['members']+=fragment['members'];match['fonts']|=fragment['fonts']
            match['regions'].add(fragment['region']);match['line_ids'].append(fragment['id'])
            match['block']=match['block'] or fragment['block']
    region_rows=Counter(rid for row in rows for rid in row['regions'])
    for row in rows:
        row['members'].sort(key=lambda word:(-word['x'],word['id']))

    def continuation(first,second):
        if second['baseline']<=first['baseline']+max(.8,min(first['size'],second['size'])*.12):return None
        shared=first['regions']&second['regions']
        explicit_first={rid for rid in first['regions'] if region_rows[rid]>1 or regions.get(rid,{}).get('kind','unclassified')!='unclassified'}
        explicit_second={rid for rid in second['regions'] if region_rows[rid]>1 or regions.get(rid,{}).get('kind','unclassified')!='unclassified'}
        if (explicit_first or explicit_second) and not shared:return None
        width=min(first['r']-first['x'],second['r']-second['x'])
        overlap=min(first['r'],second['r'])-max(first['x'],second['x'])
        if overlap<max(.5,width*.3) and abs(first['r']-second['r'])>min(first['size'],second['size']):return None
        gap=second['top']-first['bottom']
        ratio=max(first['size'],second['size'])/max(.1,min(first['size'],second['size']))
        # A large opening word may precede smaller body text. A whole body
        # line cannot use this exception to absorb a full-width footnote.
        opening=(len(first['members'])==1 and first['size']>=second['size']*1.45
                 and second['x']<=first['x'] and second['r']>=first['r'])
        if not shared and not opening and first['block'] and second['block'] and first['block']!=second['block']:return None
        same_font=bool(first['fonts']&second['fonts']) or not first['fonts'] or not second['fonts']
        # A different embedded font may occupy the same column. Require both
        # column edges to agree; one shared edge also fits unrelated footnotes.
        aligned=(max(abs(first['r']-second['r']),abs(first['x']-second['x']))
                 <=min(first['size'],second['size']))
        if not shared and not opening and (ratio>1.3 or not (same_font or aligned)):return None
        if gap>max(first['size'],second['size'])*(8 if opening else 3):return None
        # Prefer the nearest line in the same column; reserve one predecessor
        # per line so two neighbouring columns cannot merge into one passage.
        return max(0,gap)/max(.1,second['size'])+abs(first['r']-second['r'])/max(1,width)

    edges=[]
    for index,row in enumerate(rows):
        for other,next_row in enumerate(rows):
            if other==index:continue
            cost=continuation(row,next_row)
            if cost is not None:edges.append((cost,index,other))
    successor={};predecessor={}
    for _,first,second in sorted(edges):
        if first not in successor and second not in predecessor:
            successor[first]=second;predecessor[second]=first
    flows=[]
    for start in range(len(rows)):
        if start in predecessor:continue
        chain=[];index=start
        while True:
            chain.append(rows[index])
            if index not in successor:break
            index=successor[index]
        members=[word for row in chain for word in row['members']]
        flows.append({'words':members,'lines':[lid for row in chain for lid in row['line_ids']],
                      'x':min(row['x'] for row in chain),'r':max(row['r'] for row in chain),
                      'top':chain[0]['top'],'bottom':chain[-1]['bottom'],
                      'size':median(row['size'] for row in chain),
                      'fonts':set().union(*(row['fonts'] for row in chain))})
    if geometry.get('explicit_word_order'):
        for flow in flows:flow['words'].sort(key=lambda word:word['reading_order'])
        return sorted(flows,key=lambda flow:min(word['reading_order'] for word in flow['words']))
    return sorted(flows,key=lambda flow:(flow['top'],-flow['r']))

def sentence_context(geometry,occurrence_id,flows=None):
    flows=reading_flows(geometry) if flows is None else flows
    flow=next((flow for flow in flows if any(word['id']==occurrence_id for word in flow['words'])),None)
    if flow is None:raise KeyError('Source word unavailable')
    words=flow['words']
    selected=next(index for index,word in enumerate(words) if word['id']==occurrence_id)
    start=selected
    while start>0 and not TERMINAL.search(words[start-1]['text']):start-=1
    end=selected+1
    while end<len(words) and not TERMINAL.search(words[end-1]['text']):end+=1
    members=words[start:end]
    return {'words':[word['text'] for word in members],'selected':selected-start,
            'occurrences':[word['id'] for word in members],
            'revision':digest([REVISION,geometry['revision'],[(word['id'],word['text']) for word in members]]),
            'complete_start':start>0,'complete_end':bool(TERMINAL.search(members[-1]['text']))}

def context_geometry(conn,page_id):
    from .page_geometry import load_geometry
    from .corrections import inactive_corrections
    geometry=load_geometry(page_id,conn)
    inactive=inactive_corrections(conn)
    geometry['explicit_word_order']=any(row['id'] not in inactive for row in conn.execute("SELECT id FROM correction WHERE page_id=? AND kind='reading_order'",(page_id,)))
    return geometry

def context_for_word(conn,word):
    geometry=context_geometry(conn,word['page_id']);flows=reading_flows(geometry)
    flow=next(flow for flow in flows if any(item['id']==word['id'] for item in flow['words']))
    context=sentence_context(geometry,word['id'],flows)
    page=conn.execute('SELECT sequence,tractate FROM page WHERE id=?',(word['page_id'],)).fetchone()
    revisions=[geometry['revision']]
    for delta,needed in ((-1,not context['complete_start']),(1,not context['complete_end'])):
        if not needed:continue
        boundary=0 if delta<0 else -1
        if context['occurrences'][boundary]!=flow['words'][boundary]['id']:continue
        adjacent=conn.execute('SELECT id FROM page WHERE tractate=? AND sequence=? AND active_revision IS NOT NULL',(page['tractate'],page['sequence']+delta)).fetchone()
        if not adjacent:continue
        other=context_geometry(conn,adjacent['id'])
        matches=[]
        for candidate in reading_flows(other):
            # Cross-page continuation needs matching typography and column
            # position. Do not guess across a changed or ambiguous layout.
            if not flow['fonts']&candidate['fonts']:continue
            ratio=candidate['size']/max(.1,flow['size'])
            if not .85<=ratio<=1.18:continue
            left=max(flow['x']/geometry['width'],candidate['x']/other['width'])
            right=min(flow['r']/geometry['width'],candidate['r']/other['width'])
            width=min((flow['r']-flow['x'])/geometry['width'],(candidate['r']-candidate['x'])/other['width'])
            if right-left<width*.6:continue
            matches.append(candidate)
        if len(matches)!=1:continue
        # The unique passage on the previous daf, or first on the next daf,
        # continues this column. A terminal mark ends it before this word.
        continuation=matches[0]
        members=continuation['words']
        if delta<0:
            if TERMINAL.search(members[-1]['text']):continue
            start=len(members)-1
            while start>0 and not TERMINAL.search(members[start-1]['text']):start-=1
            members=members[start:]
            context['words']=[item['text'] for item in members]+context['words']
            context['occurrences']=[item['id'] for item in members]+context['occurrences']
            context['selected']+=len(members);context['complete_start']=start>0
        else:
            end=1
            while end<len(members) and not TERMINAL.search(members[end-1]['text']):end+=1
            members=members[:end]
            context['words']+=[item['text'] for item in members]
            context['occurrences']+=[item['id'] for item in members]
            context['complete_end']=bool(TERMINAL.search(members[-1]['text']))
        revisions.append(other['revision'])
    context['revision']=digest([REVISION,revisions,context['occurrences'],context['words'],context['selected']])
    return context

def attach_reading_order(geometry,explicit=False):
    geometry['explicit_word_order']=explicit
    flows=reading_flows(geometry)
    geometry['word_order']=[word['id'] for word in sorted(geometry['words'],key=lambda word:word['reading_order'])] if explicit else [word['id'] for flow in flows for word in flow['words']]
    return flows
