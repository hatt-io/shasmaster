"""Retain unassigned printed ink as movable source fragments."""
from copy import deepcopy
from functools import lru_cache
import gzip
import json
import re
import xml.etree.ElementTree as ET
import pymupdf
from .config import DATA
from .db import digest

SVG='{http://www.w3.org/2000/svg}'
XLINK='{http://www.w3.org/1999/xlink}'
REVISION='remaining-ink-1'


def ink_boxes(pix):
    # Find connected ink runs. Rasterization supplies bounds only; rendering
    # continues to use the untouched vector/image source inside those bounds.
    samples=pix.samples
    parents={};bounds={};previous=[];serial=0
    def root(index):
        while parents[index]!=index:
            parents[index]=parents[parents[index]];index=parents[index]
        return index
    for y in range(pix.height):
        current=[];cursor=0
        for match in re.finditer(b'[\x00-\xfe]+',samples[y*pix.stride:y*pix.stride+pix.width]):
            left,right=match.span()
            while cursor<len(previous) and previous[cursor][1]<left:cursor+=1
            touching=set();index=cursor
            while index<len(previous) and previous[index][0]<=right:
                touching.add(root(previous[index][2]));index+=1
            if touching:
                component=min(touching)
                for other in touching-{component}:
                    parents[other]=component
                    a,b=bounds[component],bounds.pop(other)
                    bounds[component]=[min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])]
                box=bounds[component];box[0]=min(box[0],left);box[2]=max(box[2],right);box[3]=y+1
            else:
                component=serial;serial+=1;parents[component]=component;bounds[component]=[left,y,right,y+1]
            current.append((left,right,component))
        previous=current
    # Disjoint rectangles prevent double-painting where connected shapes enclose
    # other marks or their antialiased edges meet.
    boxes=[]
    for box in bounds.values():
        box=[max(0,box[0]-1),max(0,box[1]-1),min(pix.width,box[2]+1),min(pix.height,box[3]+1)]
        index=0
        while index<len(boxes):
            other=boxes[index]
            if box[0]<=other[2] and other[0]<=box[2] and box[1]<=other[3] and other[1]<=box[3]:
                box=[min(box[0],other[0]),min(box[1],other[1]),max(box[2],other[2]),max(box[3],other[3])]
                boxes.pop(index);index=0
            else:index+=1
        boxes.append(box)
    return sorted(boxes,key=lambda box:(box[1],-box[2]))


def separate(node,tagged):
    if node.get('data-line'):return deepcopy(node) if tagged else None
    if node.tag in (SVG+'g',SVG+'svg'):
        result=ET.Element(node.tag,dict(node.attrib))
        for child in node:
            kept=separate(child,tagged)
            if kept is not None:result.append(kept)
        return result if len(result) else None
    return None if tagged else deepcopy(node)


def attach_artwork(geometry,vector):
    if geometry.get('artwork_revision')==REVISION:return vector
    root=ET.fromstring(vector)
    definitions=[deepcopy(node) for node in root if node.tag in (SVG+'defs',SVG+'title',SVG+'desc')]
    body=[node for node in root if node.tag not in (SVG+'defs',SVG+'title',SVG+'desc')]
    remaining=[kept for node in body if (kept:=separate(node,False)) is not None]
    tagged=[kept for node in body if (kept:=separate(node,True)) is not None]
    background=ET.Element(root.tag,dict(root.attrib));background.extend(deepcopy(definitions));background.extend(deepcopy(remaining))
    scale=4
    with pymupdf.open(stream=ET.tostring(background,encoding='utf-8'),filetype='svg') as document:
        pix=document[0].get_pixmap(matrix=pymupdf.Matrix(scale,scale),colorspace=pymupdf.csGRAY,alpha=False)
        boxes=ink_boxes(pix)
        origin=(pix.x,pix.y)
    source_id='remaining-ink-'+digest([geometry['source_sha'],REVISION])[:20]
    output=ET.Element(root.tag,dict(root.attrib));output.extend(definitions)
    defs=ET.SubElement(output,SVG+'defs')
    source=ET.SubElement(defs,SVG+'g',{'id':source_id});source.extend(remaining)
    source_lines=list(geometry['lines'])
    for index,box in enumerate(boxes):
        left,top,right,bottom=[(value+origin[i%2])/scale for i,value in enumerate(box)]
        nearby=[]
        for line in source_lines:
            overlap=max(0,min(bottom,line['bottom'])-max(top,line['top']))
            gap=max(0,left-line['r'],line['x']-right)
            if overlap>=(bottom-top)*.5 and bottom-top<=line['size']*1.5 and gap<=max(1,line['size']*.5):
                nearby.append((gap,-overlap,line['id'],line))
        if nearby:
            # Unattached glyphs and adjacent marks on an existing printed line
            # must share its movement, including descenders below the baseline.
            line=min(nearby,key=lambda item:item[:3])[3];identity=line['id']
            line['x']=min(line['x'],left);line['r']=max(line['r'],right)
            line['top']=min(line['top'],top);line['bottom']=max(line['bottom'],bottom)
        else:
            identity=geometry['id']+':artwork:'+digest([geometry['source_sha'],REVISION,box])[:24]
            region_id=identity+':region'
            line={'id':identity,'region':region_id,'x':left,'r':right,'top':top,'bottom':bottom,'baseline':bottom,'size':bottom-top,'words':[],'reading_order':len(geometry['lines']),'source':'artwork'}
            enclosed=[item for item in source_lines if item['words'] and left<item['x'] and right>item['r'] and top<item['top'] and bottom>item['bottom']]
            if enclosed:
                # Existing white space inside an ornamental frame is available
                # for wording before any border needs to move.
                x1=max(box[0],int(min(item['x'] for item in enclosed)*scale-origin[0]))
                x2=min(box[2],int(max(item['r'] for item in enclosed)*scale-origin[0]))
                content_top=int(min(item['top'] for item in enclosed)*scale-origin[1])
                content_bottom=int(max(item['bottom'] for item in enclosed)*scale-origin[1])
                samples=pix.samples
                def has_ink(y):return any(value<230 for value in samples[y*pix.stride+x1:y*pix.stride+x2])
                inner_bottom=next((y for y in range(content_bottom,box[3]) if has_ink(y)),box[3])
                inner_top=next((y+1 for y in range(content_top,box[1]-1,-1) if has_ink(y)),box[1])
                line['frame_inner_bottom']=(inner_bottom+origin[1])/scale
                line['frame_inner_top']=(inner_top+origin[1])/scale
            geometry['lines'].append(line)
            geometry['regions'].append({'id':region_id,'kind':'unassigned-print','bounds':[left,top,right,bottom],'reading_order':len(geometry['regions'])})
        clip_id=source_id+'-'+str(index)
        clip=ET.SubElement(defs,SVG+'clipPath',{'id':clip_id,'clipPathUnits':'userSpaceOnUse'})
        ET.SubElement(clip,SVG+'rect',{'x':str(left),'y':str(top),'width':str(right-left),'height':str(bottom-top)})
        fragment=ET.SubElement(output,SVG+'g',{'data-line':identity})
        clipped=ET.SubElement(fragment,SVG+'g',{'clip-path':f'url(#{clip_id})'})
        ET.SubElement(clipped,SVG+'use',{XLINK+'href':'#'+source_id})
    output.extend(tagged)
    if boxes:geometry['issues'].append({'kind':'unassigned-printed-ink','fragments':len(boxes),'revision':REVISION})
    geometry['artwork_revision']=REVISION
    return ET.tostring(output,encoding='unicode')


@lru_cache(maxsize=6)
def _source_fragments(geometry_path,vector_path):
    with gzip.open(DATA/geometry_path,'rt',encoding='utf-8') as handle:geometry=json.load(handle)
    with gzip.open(DATA/vector_path,'rt',encoding='utf-8') as handle:vector=handle.read()
    return geometry,attach_artwork(geometry,vector)


def source_fragments(geometry_path,vector_path):
    geometry,vector=_source_fragments(geometry_path,vector_path)
    return deepcopy(geometry),vector
