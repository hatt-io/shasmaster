"""Move original PDF glyph outlines, then render the resulting vector PDF with PDF.js."""
from functools import lru_cache
import gzip
import json
import re
import xml.etree.ElementTree as ET
import pymupdf
from .config import DATA
from .db import read
from .extract import load_geometry, SVG
from .artwork import source_fragments

@lru_cache(maxsize=12)
def vector_source(page_id,revision):
    with read() as conn:
        row=conn.execute('SELECT geometry_path,vector_path FROM page_revision WHERE id=? AND page_id=?',(revision,page_id)).fetchone()
    if not row:raise KeyError(page_id)
    return source_fragments(row['geometry_path'],row['vector_path'])[1]

def expanded_pdf(page_id,revision,offsets,height):
    geometry=load_geometry(page_id)
    if geometry['revision']!=revision:raise ValueError('Source revision changed')
    lines={line['id']:line for line in geometry['lines']}
    if any(key not in lines for key in offsets):raise ValueError('Unknown source line')
    if any(not isinstance(value,(int,float)) or value<0 or value>100000 for value in offsets.values()):raise ValueError('Invalid line offset')
    minimum=max([geometry['height']]+[line['bottom']+offsets.get(line['id'],0) for line in lines.values()])
    if not minimum<=height<=200000:raise ValueError('Invalid page height')
    root=ET.fromstring(vector_source(page_id,revision))
    root.set('height',str(height));root.set('viewBox',f'0 0 {geometry["width"]} {height}')
    # MuPDF's outer page clip uses this root-coordinate rectangle.
    outer_clips={node.get('clip-path','')[5:-1] for node in root if node.tag==SVG+'g' and not node.get('data-source-background') and node.get('clip-path','').startswith('url(#')}
    for clip in root.iter(SVG+'clipPath'):
        name=clip.get('id')
        if name in outer_clips:
            clip.clear();clip.set('id',name)
            ET.SubElement(clip,SVG+'rect',{'x':'0','y':'0','width':str(geometry['width']),'height':str(height)})
    for node in root.iter():
        shift=offsets.get(node.get('data-line',''),0)
        if shift:node.set('transform',f'translate(0,{shift}) '+node.get('transform',''))
    svg=ET.tostring(root,encoding='utf-8')
    with pymupdf.open(stream=svg,filetype='svg') as document:
        return document.convert_to_pdf()


@lru_cache(maxsize=6)
def fragment_atlas(page_id,revision):
    """Pack original source fragments once; the reader moves their canvases locally."""
    with read() as conn:
        row=conn.execute('SELECT geometry_path,vector_path FROM page_revision WHERE id=? AND page_id=?',(revision,page_id)).fetchone()
    if not row:raise KeyError(page_id)
    geometry,vector=source_fragments(row['geometry_path'],row['vector_path'])
    root=ET.fromstring(vector)
    width=geometry['width'];cursor=geometry['height']+4
    fragments=[];shifts={}
    for line in sorted(geometry['lines'],key=lambda line:line.get('source')!='artwork'):
        pad=max(1,line['size']*.25)
        left=max(0,line['x']-pad);right=min(width,line['r']+pad)
        top=max(0,line['top']-pad);bottom=min(geometry['height'],line['bottom']+pad)
        if right<=left or bottom<=top:continue
        fragments.append({'id':line['id'],'x':left,'y':top,'width':right-left,'height':bottom-top,'atlas_y':cursor})
        shifts[line['id']]=cursor-top
        cursor+=bottom-top+4
    root.set('height',str(cursor));root.set('viewBox',f'0 0 {width} {cursor}')
    outer_clips={node.get('clip-path','')[5:-1] for node in root if node.tag==SVG+'g' and not node.get('data-source-background') and node.get('clip-path','').startswith('url(#')}
    for clip in root.iter(SVG+'clipPath'):
        name=clip.get('id')
        if name in outer_clips:
            clip.clear();clip.set('id',name)
            ET.SubElement(clip,SVG+'rect',{'x':'0','y':'0','width':str(width),'height':str(cursor)})
    for node in root.iter():
        shift=shifts.get(node.get('data-line',''))
        if shift is not None:node.set('transform',f'translate(0,{shift}) '+node.get('transform',''))
    with pymupdf.open(stream=ET.tostring(root,encoding='utf-8'),filetype='svg') as document:
        pdf=document.convert_to_pdf()
    return {'revision':revision,'width':width,'height':geometry['height'],'fragments':fragments},pdf
