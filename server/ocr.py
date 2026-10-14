"""Local transcription only. OCR never supplies meanings or passage translations."""
from functools import lru_cache
from importlib.metadata import version as package_version
import gzip
import hashlib
import json
import marshal
import os
import re
import shutil
import subprocess
from bs4 import BeautifulSoup
import pymupdf
from .config import DATA, OCR_MODEL_PATH
from .model_files import model_fingerprint
from .db import digest, json_text

OCR_PIPELINE='tesseract-hocr-1'

@lru_cache(maxsize=1)
def engine():
    executable=os.environ.get('SHAS_TESSERACT') or shutil.which('tesseract')
    if not executable:raise RuntimeError('Tesseract is not installed')
    for language in ('heb','eng'):
        if not (OCR_MODEL_PATH/(language+'.traineddata')).is_file():
            raise RuntimeError('Local Hebrew/English OCR models are not downloaded')
    version=subprocess.run([executable,'--version'],capture_output=True,text=True,check=True).stdout.splitlines()[0]
    with open(executable,'rb') as source:binary_sha=hashlib.file_digest(source,'sha256').hexdigest()
    parser_sha=hashlib.sha256(marshal.dumps((recognize.__code__,title_fields.__code__))).hexdigest()
    return executable,{'engine':version,'binary_sha':binary_sha,'models':model_fingerprint(OCR_MODEL_PATH),'pipeline':OCR_PIPELINE,'parser_sha':parser_sha,'renderer':pymupdf.VersionBind,'html_parser':package_version('beautifulsoup4')}


def title_fields(node):
    result={}
    for field in node.get('title','').split(';'):
        parts=field.strip().split()
        if parts:result[parts[0]]=parts[1:]
    return result


def recognize(page,source_sha,clip=None,psm=3,dpi=400):
    executable,provenance=engine()
    clip=pymupdf.Rect(clip) if clip is not None else page.rect
    clip=clip & page.rect
    if clip.is_empty:raise ValueError('Empty OCR region')
    key=digest({'source':source_sha,'clip':list(clip),'psm':psm,'dpi':dpi,**provenance})
    cached=DATA/'ocr'/(key+'.json.gz')
    if cached.exists():
        with gzip.open(cached,'rt',encoding='utf-8') as source:return json.load(source)
    scale=dpi/72
    pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=clip,colorspace=pymupdf.csRGB,alpha=False)
    command=[executable,'stdin','stdout','--tessdata-dir',str(OCR_MODEL_PATH),'-l','heb+eng','--oem','1','--psm',str(psm),'--dpi',str(dpi),'-c','hocr_char_boxes=1','hocr']
    process=subprocess.run(command,input=pix.tobytes('png'),capture_output=True,timeout=180,env={**os.environ,'OMP_THREAD_LIMIT':'2'})
    if process.returncode:raise RuntimeError(process.stderr.decode('utf-8','replace').strip())
    hocr=process.stdout.decode('utf-8');soup=BeautifulSoup(hocr,'html.parser')
    words=[];lines=[];regions=[]
    def box(node):
        bounds=[float(v) for v in title_fields(node)['bbox']]
        return [(bounds[0]+pix.x)/scale,(bounds[1]+pix.y)/scale,(bounds[2]+pix.x)/scale,(bounds[3]+pix.y)/scale]
    for region in soup.select('.ocr_carea'):
        regions.append({'id':region.get('id'),'bounds':box(region)})
    for line in soup.select('.ocr_line, .ocr_header, .ocr_caption, .ocr_textfloat'):
        bounds=box(line);fields=title_fields(line);baseline=fields.get('baseline',['0','0'])
        lines.append({'id':line.get('id'),'bounds':bounds,'baseline':bounds[3]+float(baseline[-1])/scale})
    for node in soup.select('.ocrx_word'):
        fields=title_fields(node)
        text=node.get_text('',strip=True)
        if not text:continue
        line=node.find_parent(class_=lambda value:value and any(c in value.split() for c in ('ocr_line','ocr_header','ocr_caption','ocr_textfloat')))
        region=node.find_parent(class_='ocr_carea')
        chars=[]
        for char in node.select('.ocrx_cinfo'):
            info=title_fields(char);bounds=info.get('x_bboxes')
            if bounds:
                x0,y0,x1,y1=map(float,bounds)
                chars.append({'text':char.get_text(),'bounds':[(x0+pix.x)/scale,(y0+pix.y)/scale,(x1+pix.x)/scale,(y1+pix.y)/scale],'confidence':float(info.get('x_conf',['0'])[0])})
        words.append({'text':text,'bounds':box(node),'confidence':float(fields.get('x_wconf',['0'])[0]),'line':line.get('id') if line else None,'region':region.get('id') if region else None,'characters':chars})
    result={'key':key,'provenance':provenance,'clip':list(clip),'dpi':dpi,'psm':psm,'words':words,'lines':lines,'regions':regions,'hocr':hocr,'diagnostics':process.stderr.decode('utf-8','replace')}
    partial=cached.with_suffix(cached.suffix+'.part')
    with gzip.open(partial,'wt',encoding='utf-8') as destination:destination.write(json_text(result))
    partial.replace(cached)
    return result


def overlap(a,b):
    width=max(0,min(a[2],b[2])-max(a[0],b[0]))
    height=max(0,min(a[3],b[3])-max(a[1],b[1]))
    return width*height


def supplement(page,record,geometry,vector):
    from collections import defaultdict
    from .extract import identity
    from .text import normalize
    issues=geometry['issues']
    for word in geometry['words']:
        if word['state']!='unresolved':continue
        geometry['ocr_attempted']=True
        original=word['text']
        unknown=lambda c:c=='\ufffd' or 0xe000<=ord(c)<=0xf8ff
        pattern=''.join('([א-ת])' if unknown(c) else re.escape(normalize(c)) for c in original)
        try:
            clip=[word['x']-2,word['top']-2,word['r']+2,word['bottom']+2]
            result=recognize(page,record['source_sha'],clip,psm=8,dpi=500)
            candidates=[w for w in result['words'] if w['confidence']>=90]
            match=re.fullmatch(pattern,normalize(candidates[0]['text'])) if len(candidates)==1 else None
            if not match:
                issues.append({'kind':'ocr-unresolved','word':word['id'],'evidence':result['key']})
                continue
            replacements=iter(match.groups())
            text=''.join(next(replacements) if unknown(c) else c for c in original)
            word.update(text=text,normalized=normalize(text),state='ocr',ocr={'evidence':result['key'],'confidence':candidates[0]['confidence'],'original_text':original})
            issues.append({'kind':'ocr-transcription','word':word['id'],**word['ocr']})
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
            issues.append({'kind':'ocr-failed','word':word['id'],'error':str(exc)})
    # A full-page pass also finds outlined text outside embedded image objects.
    # Native words retain their original transcription and geometry below.
    clips=[list(page.rect)]
    native_boxes=[[w['x'],w['top'],w['r'],w['bottom']] for w in geometry['words']]
    added=[];seen=[];evidence=[w['ocr']['evidence'] for w in geometry['words'] if w.get('ocr')]
    for clip in clips:
        geometry['ocr_attempted']=True
        try:result=recognize(page,record['source_sha'],clip,psm=3,dpi=400)
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
            issues.append({'kind':'ocr-failed','bounds':list(clip),'error':str(exc)});continue
        evidence.append(result['key'])
        groups=defaultdict(list)
        for item in result['words']:
            bounds=item['bounds'];area=max(.01,(bounds[2]-bounds[0])*(bounds[3]-bounds[1]))
            # Embedded visible text already has exact glyph anchors.
            if any(overlap(bounds,box)/area>.2 for box in native_boxes):continue
            if any(overlap(bounds,box)/area>.6 for box in seen):continue
            seen.append(bounds)
            groups[item['line'],item['region']].append(item)
        if not groups:
            issues.append({'kind':'ocr-image-without-text','bounds':list(clip),'evidence':result['key']})
        for group in groups.values():
            chunks=[]
            for item in sorted(group,key=lambda w:w['bounds'][0]):
                box=item['bounds']
                if not chunks or box[0]-chunks[-1][-1]['bounds'][2]>max(8,box[3]-box[1]):chunks.append([])
                chunks[-1].append(item)
            for chunk in chunks:
                boxes=[item['bounds'] for item in chunk]
                bounds=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
                signature=[record['source_sha'],[round(v,3) for v in bounds]]
                lid=identity(record['id'],'ocr-line',signature);rid=identity(record['id'],'ocr-region',[lid])
                source_line=next((line for line in result['lines'] if line['id']==chunk[0]['line']),None)
                line={'id':lid,'region':rid,'x':bounds[0],'top':bounds[1],'r':bounds[2],'bottom':bounds[3],
                      'baseline':source_line['baseline'] if source_line else bounds[3],'size':bounds[3]-bounds[1],
                      'words':[],'reading_order':len(geometry['lines']),'source':'ocr'}
                for item in reversed(chunk):
                    box=item['bounds'];wid=identity(record['id'],'ocr-word',[record['source_sha'],[round(v,3) for v in box]])
                    word={'id':wid,'line':lid,'region':rid,'x':box[0],'top':box[1],'r':box[2],'bottom':box[3],
                          'text':item['text'],'normalized':normalize(item['text']),'state':'ocr','glyphs':[],
                          'reading_order':len(geometry['words']),'ocr':{'evidence':result['key'],'confidence':item['confidence'],'characters':item['characters']}}
                    geometry['words'].append(word);line['words'].append(wid);added.append(word)
                    issues.append({'kind':'ocr-transcription','word':wid,'confidence':item['confidence'],'evidence':result['key']})
                geometry['lines'].append(line)
                geometry['regions'].append({'id':rid,'kind':'unclassified','bounds':bounds,'reading_order':len(geometry['regions'])})
    if added:vector=attach_original_fragments(vector,geometry,added)
    if evidence:geometry['ocr_revision']=digest(evidence)
    return vector


def attach_original_fragments(vector,geometry,words):
    """Clip original source artwork per OCR word, retaining its original fonts/images."""
    from copy import deepcopy
    import xml.etree.ElementTree as ET
    from .extract import SVG
    xlink='{http://www.w3.org/1999/xlink}'
    root=ET.fromstring(vector)
    defs=ET.SubElement(root,SVG+'defs')
    source_id='ocr-original-'+digest(geometry['source_sha'])[:16]
    source=ET.SubElement(defs,SVG+'g',{'id':source_id})
    body=[node for node in list(root) if node.tag not in (SVG+'defs',SVG+'title',SVG+'desc')]
    for node in body:
        original=deepcopy(node)
        for child in original.iter():
            child.attrib.pop('data-line',None);child.attrib.pop('data-word',None)
        source.append(original)
    background_id=source_id+'-background'
    background=ET.SubElement(defs,SVG+'clipPath',{'id':background_id,'clipPathUnits':'userSpaceOnUse'})
    remaining=[[0,0,geometry['width'],geometry['height']]]
    for word in words:
        cut=[word['x'],word['top'],word['r'],word['bottom']];pieces=[]
        for left,top,right,bottom in remaining:
            x0,y0,x1,y1=max(left,cut[0]),max(top,cut[1]),min(right,cut[2]),min(bottom,cut[3])
            if x1<=x0 or y1<=y0:pieces.append([left,top,right,bottom]);continue
            if top<y0:pieces.append([left,top,right,y0])
            if y1<bottom:pieces.append([left,y1,right,bottom])
            if left<x0:pieces.append([left,y0,x0,y1])
            if x1<right:pieces.append([x1,y0,right,y1])
        remaining=pieces
    for left,top,right,bottom in remaining:
        ET.SubElement(background,SVG+'rect',{'x':str(left),'y':str(top),'width':str(right-left),'height':str(bottom-top)})
    base=ET.Element(SVG+'g',{'clip-path':f'url(#{background_id})','data-source-background':'true'})
    def native_only(node):
        if node.tag==SVG+'use':return deepcopy(node) if node.get('data-line') else None
        if node.tag!=SVG+'g':return None
        group=ET.Element(node.tag,dict(node.attrib))
        for child in node:
            kept=native_only(child)
            if kept is not None:group.append(kept)
        return group if len(group) else None
    for node in body:
        native=native_only(node)
        for parent in list(node.iter()):
            for child in list(parent):
                if child.tag==SVG+'use' and child.get('data-line'):parent.remove(child)
        root.remove(node);base.append(node)
        if native is not None:root.append(native)
    root.insert(0,base)
    for index,word in enumerate(words):
        attrs={'x':str(word['x']),'y':str(word['top']),'width':str(word['r']-word['x']),'height':str(word['bottom']-word['top'])}
        clip_id=source_id+'-word-'+str(index)
        clip=ET.SubElement(defs,SVG+'clipPath',{'id':clip_id,'clipPathUnits':'userSpaceOnUse'})
        ET.SubElement(clip,SVG+'rect',attrs)
        fragment=ET.SubElement(root,SVG+'g',{'data-line':word['line'],'data-word':word['id']})
        clipped=ET.SubElement(fragment,SVG+'g',{'clip-path':f'url(#{clip_id})'})
        ET.SubElement(clipped,SVG+'use',{xlink+'href':'#'+source_id})
    return ET.tostring(root,encoding='unicode')
