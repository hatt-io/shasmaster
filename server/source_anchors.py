"""Retain anchors when font decoding changes within the same PDF asset."""
from collections import Counter,defaultdict
import gzip
import json
from .config import DATA
from .db import read


def glyph_key(glyphs):
    return tuple(sorted((round(g['origin_x'],3),round(g['baseline'],3),g['glyph'],g['original']) for g in glyphs))


def retain_glyph_ids(record,words,lines,regions,issues,rules):
    with read() as conn:
        prior=conn.execute('SELECT r.* FROM page p JOIN page_revision r ON r.id=p.active_revision WHERE p.id=? AND r.source_sha=?',(record['id'],record['source_sha'])).fetchone()
    if not prior:return None
    try:
        with gzip.open(DATA/prior['geometry_path'],'rt',encoding='utf-8') as source:old=json.load(source)
    except (OSError,ValueError) as exc:
        issues.append({'kind':'previous-source-unavailable','revision':prior['id'],'error':str(exc)})
        return None
    old_words={w['id']:w for w in old['words']}
    known_words=defaultdict(list);known_lines=defaultdict(list)
    for word in old['words']:
        if word.get('glyphs'):known_words[glyph_key(word['glyphs'])].append(word)
    for line in old['lines']:
        glyphs=[g for wid in line['words'] for g in old_words.get(wid,{}).get('glyphs',[])]
        if glyphs:known_lines[glyph_key(glyphs)].append(line)
    current={word['id']:word for word in words}
    line_keys={line['id']:glyph_key([g for wid in line['words'] for g in current[wid]['glyphs']]) for line in lines}
    word_counts=Counter(glyph_key(w['glyphs']) for w in words)
    line_counts=Counter(line_keys.values())
    word_ids={};line_ids={};region_ids={}
    for word in words:
        key=glyph_key(word['glyphs']);matches=known_words.get(key,[])
        if len(matches)==1 and word_counts[key]==1:word_ids[word['id']]=matches[0]['id']
        elif matches:issues.append({'kind':'ambiguous-source-anchor','word':word['id'],'previous':[w['id'] for w in matches]})
    for line in lines:
        key=line_keys[line['id']];matches=known_lines.get(key,[])
        if len(matches)==1 and line_counts[key]==1:
            line_ids[line['id']]=matches[0]['id'];region_ids[line['region']]=matches[0]['region']
        elif matches:issues.append({'kind':'ambiguous-source-anchor','line':line['id'],'previous':[l['id'] for l in matches]})
    for word in words:
        word['id']=word_ids.get(word['id'],word['id']);word['line']=line_ids.get(word['line'],word['line']);word['region']=region_ids.get(word['region'],word['region'])
    for line in lines:
        line['id']=line_ids.get(line['id'],line['id']);line['region']=region_ids.get(line['region'],line['region']);line['words']=[word_ids.get(wid,wid) for wid in line['words']]
    for region in regions:region['id']=region_ids.get(region['id'],region['id'])
    if old.get('extraction_rules')==rules:return old.get('anchor_provenance')
    return {'previous_revision':prior['id'],'rule':'identical-source-glyph-positions','words':len(word_ids),'lines':len(line_ids)}
