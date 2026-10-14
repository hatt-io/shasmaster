"""Extract original glyphs and geometry. Vector outlines remain source material."""
from collections import defaultdict
from contextlib import nullcontext
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import gzip
import hashlib
import json
import math
import re
import statistics
import struct
import time
import xml.etree.ElementTree as ET
import pymupdf
from fontTools.cffLib import CFFFontSet
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen
from .font_recovery import glyph_unicode,printed_glyphs
from .config import DATA
from .db import migrate, read, transaction, json_text, job_progress, digest
from .text import normalize
from .extraction_state import runtime_revision,ocr_runtime_revision,queue_stale_pages
from .source_jobs import source_lock,source_running
from .source_assets import retain_pdf,retain_catalogue_sources

REVISION='glyph-source-3'
RULE_REVISION=digest({name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                      for name in ('extract.py','ocr.py','font_recovery.py','source_anchors.py','artwork.py')})
SVG='{http://www.w3.org/2000/svg}'
MAC_HEBREW=dict(zip(bytes(range(224,251)).decode('mac_roman'),'אבגדהוזחטיךכלםמןנסעףפץצקרשת'))
WINDOWS_HEBREW=dict(zip(map(chr,range(224,251)),'אבגדהוזחטיךכלםמןנסעףפץצקרשת'))
LEGACY_HEBREW={'macroman':MAC_HEBREW,'windows1255':WINDOWS_HEBREW}
ET.register_namespace('',SVG[1:-1]);ET.register_namespace('xlink','http://www.w3.org/1999/xlink')

def legacy_font_encodings(font_chars):
    legacy={}
    for fingerprint,characters in font_chars.items():
        letters=[c for c in characters if c.isalpha() or c in MAC_HEBREW or c=='\ufffd']
        mac=sum(c in MAC_HEBREW for c in letters);windows=sum(c in WINDOWS_HEBREW for c in letters)
        legacy[fingerprint]='windows1255' if windows>max(mac,len(letters)*.6) else 'macroman' if mac>len(letters)*.3 else None
    return legacy

@lru_cache(maxsize=300)
def cff_glyphs(data):
    result={}
    try:
        cff=CFFFontSet();cff.decompile(BytesIO(data),None);top=cff[cff.fontNames[0]]
        units=1/top.FontMatrix[0]
        for index,name in enumerate(top.charset):
            charstring=top.CharStrings[name]
            pen=BoundsPen(top.CharStrings);charstring.draw(pen)
            result[index]={'name':name,'bounds':pen.bounds,'advance':getattr(charstring,'width',None),'units':units,'empty':pen.bounds is None}
    except Exception as exc:
        result['_errors']=[str(exc)]
    return result

@lru_cache(maxsize=100)
def ttf_glyphs(data):
    result={}
    try:
        font=TTFont(BytesIO(data));units=font['head'].unitsPerEm
        # Some embedded subsets omit trailing hmtx bearings. Glyph names and
        # outlines remain usable without decompiling that truncated table.
        metrics=font.reader['hmtx'];count=font['hhea'].numberOfHMetrics
        glyf=font['glyf'];cmap=font.getBestCmap() or {}
        unicode_by_name=defaultdict(list)
        for cp,name in cmap.items():
            if cp!=0xfffd and not 0xe000<=cp<=0xf8ff:unicode_by_name[name].append(chr(cp))
        for index,name in enumerate(font.getGlyphOrder()):
            metric=min(index,count-1)*4
            advance=struct.unpack_from('>H',metrics,metric)[0] if 0<=metric<=len(metrics)-2 else None
            item={'name':name,'bounds':None,'advance':advance,'units':units,'unicode':unicode_by_name.get(name,[])}
            result[index]=item
            try:
                glyph=glyf[name]
                item['empty']=glyph.numberOfContours==0
                if glyph.numberOfContours:
                    glyph.recalcBounds(glyf)
                    item['bounds']=(glyph.xMin,glyph.yMin,glyph.xMax,glyph.yMax)
            except Exception as exc:result.setdefault('_errors',[]).append(f'{index}: {exc}')
        font.close()
    except Exception as exc:
        result.setdefault('_errors',[]).append(str(exc))
    return result

def identity(page_id,kind,values):
    return f'{page_id}:{kind}:'+hashlib.sha256(json_text(values).encode()).hexdigest()[:24]

def native_geometry(doc,page_record):
    page=doc[0];pid=page_record['id'];issues=[]
    fonts=defaultdict(list);font_records={};recovered_mappings={}
    with read() as conn:
        custom={(r['font_fingerprint'],r['glyph']):r['unicode'] for r in conn.execute('SELECT * FROM font_mapping')}
    for font in page.get_fonts(full=True):
        name,ext,kind,buffer=doc.extract_font(font[0]);fingerprint=hashlib.sha256(buffer).hexdigest()
        info={'fingerprint':fingerprint,'buffer':buffer,'extension':ext,'glyphs':cff_glyphs(buffer) if ext=='cff' else ttf_glyphs(buffer) if ext in ('ttf','otf') else {}}
        font_records[fingerprint]=info
        for alias in {font[3],font[3].split('+')[-1]}:
            if not any(candidate['fingerprint']==fingerprint for candidate in fonts[alias]):fonts[alias].append(info)
        for error in info['glyphs'].get('_errors',[]):issues.append({'kind':'font-recovery','font':fingerprint,'error':error})
    spans=[span for span in page.get_texttrace() if span['type']!=3]
    span_fonts=[]
    for span in spans:
        candidates=fonts.get(span['font'],[]) or fonts.get(span['font'].split('+')[-1],[])
        glyph_ids={c[1] for c in span['chars'] if not chr(c[0]).isspace()}
        if len(candidates)>1:candidates=[info for info in candidates if glyph_ids<=info['glyphs'].keys()]
        if len(candidates)==1:info=candidates[0]
        else:
            choices=fonts.get(span['font'],[]) or fonts.get(span['font'].split('+')[-1],[])
            fingerprints=sorted(candidate['fingerprint'] for candidate in choices)
            info={'fingerprint':'font-choice:'+digest([span['font'],fingerprints]),'glyphs':{}}
            issues.append({'kind':'ambiguous-font-subset','font':span['font'],'candidates':fingerprints,'glyphs':sorted(glyph_ids),'position':list(span['chars'][0][2]) if span['chars'] else None})
        span_fonts.append(info)
    font_chars=defaultdict(list)
    for span,info in zip(spans,span_fonts):font_chars[info['fingerprint']].extend(chr(c[0]) for c in span['chars'] if not chr(c[0]).isspace())
    legacy=legacy_font_encodings(font_chars)
    rows={}
    for span,info in zip(spans,span_fonts):
        for cp,gid,origin,box in span['chars']:
            original=chr(cp)
            if original.isspace():continue
            glyph_info=info['glyphs'].get(gid,{})
            named=glyph_unicode(glyph_info.get('name',''))
            key=(info['fingerprint'],gid)
            printed=printed_glyphs().get(key)
            if key in custom:text=custom[key];method='correction'
            elif printed:text=printed['unicode'];method='source-print'
            elif any('א'<=c<='ת' for c in named):text=named;method='glyph-name'
            elif legacy.get(info['fingerprint']):
                encoding=legacy[info['fingerprint']];text=LEGACY_HEBREW[encoding].get(original,original);method='hebrew-'+encoding
            else:text=original;method='embedded-unicode'
            if text=='\ufffd' or any(0xe000<=ord(c)<=0xf8ff for c in text):
                alternatives=glyph_info.get('unicode',[])
                if named and all(ord(c)!=0xfffd and not 0xe000<=ord(c)<=0xf8ff for c in named):
                    text=named;method='glyph-name'
                elif len(alternatives)==1:text=alternatives[0];method='font-cmap'
            unresolved=text=='\ufffd' or any(0xe000<=ord(c)<=0xf8ff for c in text)
            if unresolved and info.get('extension') in ('ttf','otf','cff'):
                if 'recovered' not in info:
                    from .font_recovery import recover_glyphs
                    try:
                        info['recovered'],errors=recover_glyphs(info['buffer'],info['extension'])
                        for error in errors:issues.append({'kind':'font-recovery',**error})
                    except Exception as exc:
                        info['recovered']={}
                        issues.append({'kind':'font-recovery','font':info['fingerprint'],'error':str(exc)})
                recovered=info['recovered'].get(gid)
                if recovered:
                    text=recovered['unicode'];method='source-outline';unresolved=False
                    recovered_mappings[key]=recovered
            x,y=origin;top,bottom=box[1],box[3]
            ink_x,ink_r=box[0],box[2]
            bounds=glyph_info.get('bounds');advance=glyph_info.get('advance')
            if bounds and advance:
                sx=(box[2]-box[0])/advance;sy=span['size']/glyph_info['units']
                ink_x=x+bounds[0]*sx;ink_r=x+bounds[2]*sx
                top=y-bounds[3]*sy;bottom=y-bounds[1]*sy
            g={'x':box[0],'r':box[2],'ink_x':ink_x,'ink_r':ink_r,'origin_x':x,'baseline':y,'top':top,'bottom':bottom,'size':span['size'],'text':text,'font':info['fingerprint'],'glyph':gid,'original':cp,'mapping':method,'unresolved':unresolved}
            if method=='source-outline':g['mapping_evidence']=recovered_mappings[key]
            elif method=='source-print':g['mapping_evidence']=printed
            if unresolved:issues.append({'kind':'unmapped-glyph','font':info['fingerprint'],'glyph':gid,'position':[x,y]})
            bucket=round(y*2)
            near=next((k for k in (bucket,bucket-1,bucket+1) if k in rows and abs(rows[k][0]['baseline']-y)<.45),bucket)
            rows.setdefault(near,[]).append(g)
    lines=[];words=[];regions=[]
    for glyphs in sorted(rows.values(),key=lambda gs:gs[0]['baseline']):
        chunks=[]
        for g in sorted(glyphs,key=lambda c:c['x']):
            gap=g['x']-chunks[-1][-1]['r'] if chunks else math.inf
            previous=chunks[-1][-1] if chunks else g
            separate=gap>max(7,.85*min(g['size'],previous['size'])) or (gap>3 and max(g['size'],previous['size'])/max(.1,min(g['size'],previous['size']))>1.3)
            if not chunks or separate:chunks.append([])
            chunks[-1].append(g)
        for chunk in chunks:
            baseline=statistics.median(g['baseline'] for g in chunk)
            lid=identity(pid,'line',[(round(g['origin_x'],3),round(g['baseline'],3),g['font'],g['glyph']) for g in chunk])
            line={'id':lid,'x':min(g['ink_x'] for g in chunk),'r':max(g['ink_r'] for g in chunk),'top':min(g['top'] for g in chunk),'bottom':max(g['bottom'] for g in chunk),'baseline':baseline,'size':statistics.median(g['size'] for g in chunk),'words':[],'reading_order':len(lines)}
            groups=[]
            for g in chunk:
                if not groups or g['x']-groups[-1][-1]['r']>max(.5,.14*min(g['size'],groups[-1][-1]['size'])):groups.append([])
                groups[-1].append(g)
            for group in groups:
                raw=''.join(g['text'] for g in group)
                text=''.join(g['text'] for g in reversed(group)) if any('\u05d0'<=c<='\u05ea' for c in raw) else raw
                wid=identity(pid,'word',[(round(g['origin_x'],3),round(g['baseline'],3),g['font'],g['glyph']) for g in group])
                word={'id':wid,'line':lid,'x':min(g['ink_x'] for g in group),'r':max(g['ink_r'] for g in group),'top':min(g['top'] for g in group),'bottom':max(g['bottom'] for g in group),'text':text,'normalized':normalize(text),'reading_order':len(words),'state':'unresolved' if any(g['unresolved'] for g in group) else 'native','glyphs':group}
                words.append(word);line['words'].append(wid)
            # Geometric regions retain every source fragment; corrections can merge/classify them.
            region_id=identity(pid,'region',[lid]);line['region']=region_id
            regions.append({'id':region_id,'kind':'unclassified','bounds':[line['x'],line['top'],line['r'],line['bottom']],'reading_order':len(regions)})
            for w in words[-len(groups):]:w['region']=region_id
            lines.append(line)
    from .source_anchors import retain_glyph_ids
    anchors=retain_glyph_ids(page_record,words,lines,regions,issues,RULE_REVISION)
    vector=ET.fromstring(page.get_svg_image(text_as_path=True))
    glyph_positions=defaultdict(list)
    for word in words:
        for g in word['glyphs']:glyph_positions[round(g['baseline'])].append((g,word))
    for node in vector.iter(SVG+'use'):
        if 'data-text' not in node.attrib:continue
        numbers=re.findall(r'[-+]?(?:\d*\.)?\d+(?:[eE][-+]?\d+)?',node.get('transform',''))
        if len(numbers)!=6:
            issues.append({'kind':'unsupported-vector-transform','transform':node.get('transform')});continue
        x,y=float(numbers[4]),float(numbers[5])
        candidates=[(g,w) for k in (round(y)-1,round(y),round(y)+1) for g,w in glyph_positions.get(k,[]) if abs(g['baseline']-y)<.5 and abs(g['origin_x']-x)<.5]
        if candidates:
            g,w=min(candidates,key=lambda gw:abs(gw[0]['origin_x']-x)+abs(gw[0]['baseline']-y))
            node.set('data-line',w['line']);node.set('data-word',w['id'])
        else:issues.append({'kind':'unattached-source-glyph','position':[x,y]})
    fingerprints=sorted(set(font_records)|{glyph['font'] for word in words for glyph in word['glyphs']})
    mapping_revision=digest([(fingerprint,glyph,text) for (fingerprint,glyph),text in sorted(custom.items()) if fingerprint in fingerprints])
    result={'id':pid,'width':page.rect.width,'height':page.rect.height,'lines':lines,'words':words,'regions':regions,'source_sha':page_record['source_sha'],'extractor_revision':REVISION,'issues':issues,'fonts':fingerprints,'font_mapping_revision':mapping_revision,'pdf':f'/api/pages/{pid}/pdf'}
    result['extraction_rules']=RULE_REVISION
    result['font_resolution_revision']='font-subsets-1'
    if anchors:result['anchor_provenance']=anchors
    if recovered_mappings:result['font_recovery_revision']=digest([(font,glyph,evidence) for (font,glyph),evidence in sorted(recovered_mappings.items())])
    return result,ET.tostring(vector,encoding='unicode')

class FontMappingsChanged(RuntimeError):
    pass

class SourceRevisionChanged(RuntimeError):
    pass


def extract_page(record):
    with source_lock('page:'+record['id']):
        while True:
            with read() as conn:
                current=conn.execute('SELECT * FROM page WHERE id=?',(record['id'],)).fetchone()
            if not current or current['acquisition_state']!='complete':raise RuntimeError('Source acquisition is not complete')
            try:return _extract_page(dict(current))
            except (FontMappingsChanged,SourceRevisionChanged):continue


def _extract_page(record):
    path=DATA/record['asset_path']
    source=path.read_bytes()
    retain_pdf(record,source)
    with pymupdf.open(stream=source,filetype='pdf') as doc:
        geometry,vector=native_geometry(doc,record)
        from .ocr import supplement
        vector=supplement(doc[0],record,geometry,vector)
        from .artwork import attach_artwork
        vector=attach_artwork(geometry,vector)
        if not geometry['words']:
            raise ValueError('No recoverable words after native extraction and OCR')
    geometry['runtime_revision']=runtime_revision()
    if geometry.get('ocr_attempted'):geometry['ocr_runtime_revision']=ocr_runtime_revision()
    version_parts=[record['source_sha'],REVISION,RULE_REVISION,geometry['runtime_revision'],geometry['font_mapping_revision']]
    if geometry.get('ocr_runtime_revision'):version_parts.append(geometry['ocr_runtime_revision'])
    if geometry.get('font_recovery_revision'):version_parts.append(geometry['font_recovery_revision'])
    if geometry.get('ocr_revision'):version_parts.append(geometry['ocr_revision'])
    revision=identity(record['id'],'revision',version_parts)
    geometry['revision']=revision
    geometry_path=DATA/'geometry'/f'{revision.replace(":","_")}.json.gz'
    vector_path=DATA/'vectors'/f'{revision.replace(":","_")}.svg.gz'
    for destination,content in ((geometry_path,json_text(geometry)),(vector_path,vector)):
        partial=destination.with_suffix(destination.suffix+'.part')
        with gzip.open(partial,'wt',encoding='utf-8') as handle:handle.write(content)
        partial.replace(destination)
    with transaction() as conn:
        current=conn.execute('SELECT source_sha,acquisition_state FROM page WHERE id=?',(record['id'],)).fetchone()
        if not current or current['source_sha']!=record['source_sha'] or current['acquisition_state']!='complete':
            raise SourceRevisionChanged('Source changed during extraction')
        mappings=[(r['font_fingerprint'],r['glyph'],r['unicode']) for r in conn.execute('SELECT * FROM font_mapping ORDER BY font_fingerprint,glyph') if r['font_fingerprint'] in geometry['fonts']]
        if digest(mappings)!=geometry['font_mapping_revision']:
            raise FontMappingsChanged('Font mapping changed during extraction')
        conn.execute('INSERT OR IGNORE INTO page_revision(id,page_id,source_sha,geometry_path,vector_path,extractor_revision,rules_revision,runtime_revision,ocr_runtime_revision) VALUES(?,?,?,?,?,?,?,?,?)',(revision,record['id'],record['source_sha'],str(geometry_path.relative_to(DATA)),str(vector_path.relative_to(DATA)),REVISION,RULE_REVISION,geometry['runtime_revision'],geometry.get('ocr_runtime_revision')))
        conn.execute('UPDATE occurrence SET active=0 WHERE page_id=? AND active=1',(record['id'],))
        corrected={r['id']:dict(r) for r in conn.execute("SELECT id,text,normalized,geometry_json,reading_order,transcription_state FROM occurrence WHERE page_id=? AND transcription_state='corrected'",(record['id'],))}
        for r in geometry['regions']:
            conn.execute('INSERT INTO region VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET page_revision=excluded.page_revision,kind=excluded.kind,bounds_json=excluded.bounds_json,reading_order=excluded.reading_order',(r['id'],revision,r['kind'],json_text(r['bounds']),r['reading_order']))
        for w in geometry['words']:
            compact={k:v for k,v in w.items() if k!='glyphs'}
            if w['id'] in corrected:
                saved=corrected[w['id']];bounds=json.loads(saved['geometry_json'])
                if saved['transcription_state']=='corrected':
                    compact.update({key:bounds[key] for key in ('x','r','top','bottom')})
                    compact['reading_order']=saved['reading_order']
                compact.update(text=saved['text'],normalized=saved['normalized'],state=saved['transcription_state'])
            conn.execute('INSERT INTO occurrence(id,page_id,page_revision,region_id,line_id,text,normalized,geometry_json,reading_order,transcription_state) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET page_revision=excluded.page_revision,region_id=excluded.region_id,line_id=excluded.line_id,text=excluded.text,normalized=excluded.normalized,geometry_json=excluded.geometry_json,reading_order=excluded.reading_order,transcription_state=excluded.transcription_state,active=1',(w['id'],record['id'],revision,w['region'],w['line'],compact['text'],compact['normalized'],json_text(compact),compact['reading_order'],compact['state']))
        conn.execute('DELETE FROM page_font WHERE page_id=?',(record['id'],))
        for fingerprint in geometry['fonts']:conn.execute('INSERT INTO page_font VALUES(?,?)',(record['id'],fingerprint))
        conn.execute('DELETE FROM source_issue WHERE page_id=? AND resolved=0',(record['id'],))
        for issue in geometry['issues']:conn.execute('INSERT INTO source_issue(page_id,kind,evidence_json) VALUES(?,?,?)',(record['id'],issue['kind'],json_text(issue)))
        state='issues' if geometry['issues'] else 'complete'
        conn.execute('UPDATE page SET width=?,height=?,extraction_state=?,active_revision=?,error=NULL WHERE id=?',(geometry['width'],geometry['height'],state,revision,record['id']))
        from .corrections import replay_source_corrections
        failed_corrections=replay_source_corrections(conn,record['id'],revision)
        if failed_corrections:conn.execute("UPDATE page SET extraction_state='issues' WHERE id=?",(record['id'],))
        retain_unmapped_work(conn,record['id'])
        word_count=conn.execute('SELECT count(*) FROM occurrence WHERE page_id=? AND active=1',(record['id'],)).fetchone()[0]
    return word_count,len(geometry['issues'])+failed_corrections

def retain_unmapped_work(conn,page_id):
    from .annotations import retain_recovery,annotation_bundle,mapped_anchor
    missing=conn.execute('SELECT o.*,r.source_sha FROM occurrence o JOIN annotation a ON a.occurrence_id=o.id JOIN page_revision r ON r.id=o.page_revision WHERE o.page_id=? AND o.active=0',(page_id,)).fetchall()
    for word in missing:
        if mapped_anchor(conn,word['id']):continue
        bundle=annotation_bundle(conn,word['id'])
        if bundle:retain_recovery(conn,'annotation',bundle,'Source word changed during extraction')
    bookmarks=conn.execute('SELECT b.* FROM bookmark b JOIN occurrence o ON o.id=b.occurrence_id WHERE b.page_id=? AND o.active=0',(page_id,)).fetchall()
    for row in bookmarks:
        target=mapped_anchor(conn,row['occurrence_id'])
        if target:conn.execute('UPDATE bookmark SET occurrence_id=? WHERE page_id=?',(target,page_id))
        else:retain_recovery(conn,'bookmark',dict(row),'Bookmark source changed during extraction')

from .page_geometry import load_geometry

def import_available(follow=False):
    with source_lock('printed-extraction',blocking=False):
        _import_available(follow)


def _import_available(follow=False):
    migrate()
    retain_catalogue_sources()
    with transaction() as conn:
        queue_stale_pages(conn,RULE_REVISION,retry_failures=True)
    while True:
        with transaction() as conn:queue_stale_pages(conn,RULE_REVISION)
        with read() as conn:
            pages=[dict(r) for r in conn.execute("SELECT * FROM page WHERE acquisition_state='complete' AND extraction_state='pending' ORDER BY sequence")]
            total=conn.execute('SELECT count(*) FROM page').fetchone()[0]
            done=conn.execute("SELECT count(*) FROM page WHERE extraction_state IN ('complete','issues')").fetchone()[0]
        acquiring=source_running('printed-corpus')
        for page in pages:
            try:
                words,issues=extract_page(page);done+=1
                job_progress('printed-extraction','extract','running',done,total,last_page=page['id'],words=words,issues=issues)
                if done%20==0:print(f'Extracted {done}/{total}: {page["id"]}; {words} words; {issues} source issues',flush=True)
            except Exception as exc:
                with transaction() as conn:
                    conn.execute("UPDATE page SET extraction_state='failed',error=? WHERE id=?",(str(exc),page['id']))
                    conn.execute('INSERT INTO source_issue(page_id,kind,evidence_json) VALUES(?,?,?)',(page['id'],'extraction-failed',json_text({'error':str(exc)})))
                print(f'Extraction failed: {page["id"]}: {exc}',flush=True)
        if not follow or not acquiring:
            with read() as conn:
                done=conn.execute("SELECT count(*) FROM page p JOIN page_revision r ON r.id=p.active_revision WHERE p.acquisition_state='complete' AND p.extraction_state IN ('complete','issues') AND r.source_sha=p.source_sha AND r.rules_revision=? AND r.runtime_revision=? AND (r.ocr_runtime_revision IS NULL OR r.ocr_runtime_revision=?)",(RULE_REVISION,runtime_revision(),ocr_runtime_revision())).fetchone()[0]
            job_progress('printed-extraction','extract','complete' if done==total else 'incomplete',done,total,rules=RULE_REVISION,runtime=runtime_revision())
            if done!=total:raise RuntimeError(f'Page extraction incomplete: {done}/{total}; rerun extraction to resume')
            break
        if not pages:time.sleep(3)

if __name__=='__main__':
    import sys
    import_available('--follow' in sys.argv)
