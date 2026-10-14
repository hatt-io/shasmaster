"""Lossless page encoding: shared measurements and reconstructed identities."""
import hashlib
import json
import lzma
import struct
from collections import defaultdict
from statistics import median
from fractions import Fraction
from .text import normalize


def identity(page, kind, glyphs):
    values=[(round(g['origin_x'],3),round(g['baseline'],3),g.get('source_font',g['font']),g.get('source_glyph',g['glyph'])) for g in glyphs]
    return page+':'+kind+':'+hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]


def region_identity(page, line):
    return page+':region:'+hashlib.sha256(json.dumps([line],separators=(',',':')).encode()).hexdigest()[:24]


def derived_word(page, word, glyphs):
    if not glyphs:return {}
    raw=''.join(g['text'] for g in glyphs)
    text=''.join(g['text'] for g in reversed(glyphs)) if any('א'<=c<='ת' for c in raw) else raw
    return {'id':identity(page,'word',glyphs),'text':text,'normalized':normalize(text),
        'x':min(g['ink_x'] for g in glyphs),'r':max(g['ink_r'] for g in glyphs),
        'top':min(g['top'] for g in glyphs),'bottom':max(g['bottom'] for g in glyphs),
        'state':'unresolved' if any(g['unresolved'] for g in glyphs) else 'native'}


def derived_line(page,glyphs):
    if not glyphs:return {}
    return {'id':identity(page,'line',glyphs),'x':min(g['ink_x'] for g in glyphs),
            'r':max(g['ink_r'] for g in glyphs),'top':min(g['top'] for g in glyphs),
            'bottom':max(g['bottom'] for g in glyphs),'baseline':median(g['baseline'] for g in glyphs),
            'size':median(g['size'] for g in glyphs)}


def _bits(value):return struct.unpack('<Q',struct.pack('<d',value))[0]
def _float(value):return struct.unpack('<d',struct.pack('<Q',value))[0]
def _single(value):return struct.unpack('<f',struct.pack('<f',value))[0]


class Columns:
    def __init__(self,binary=None,strings=None):
        self.binary=bytearray() if binary is None else binary
        self.strings=[] if strings is None else strings
        self.indices={} if strings is None else {value:i for i,value in enumerate(strings)}

    def intern(self,value):
        if isinstance(value,str):
            if value not in self.indices:
                self.indices[value]=len(self.strings);self.strings.append(value)
            return ['s',self.indices[value]]
        if isinstance(value,list):return ['a',[self.intern(v) for v in value]]
        if isinstance(value,dict):return ['o',[[k,self.intern(v)] for k,v in value.items()]]
        return value

    def expand(self,value):
        if not isinstance(value,list):return value
        kind,body=value
        if kind=='s':return self.strings[body]
        if kind=='a':return [self.expand(v) for v in body]
        if kind=='o':return {k:self.expand(v) for k,v in body}
        raise ValueError('Invalid page value')

    def write(self,records,predictors=None):
        columns=[]
        for field in sorted({k for row in records for k in row}):
            positions=[i for i,row in enumerate(records) if field in row]
            values=[records[i][field] for i in positions]
            present=None if len(positions)==len(records) else positions
            if values and all(type(v) is float for v in values):
                numbers=[_bits(v)^(_bits(predictors[i].get(field,0.0)) if predictors else 0) for i,v in zip(positions,values)]
                raw=struct.pack('<'+'Q'*len(numbers),*numbers)
                offset=len(self.binary)
                # Separate significant bytes from low-order residuals.
                self.binary.extend(b''.join(raw[n::8] for n in range(8)))
                columns.append([field,present,'f',offset,len(numbers)])
            else:columns.append([field,present,'j',self.intern(values)])
        return [len(records),columns]

    def read(self,table,predictors=None):
        count,columns=table;records=[{} for _ in range(count)]
        for column in columns:
            field,positions,kind=column[:3]
            positions=range(count) if positions is None else positions
            if kind=='f':
                offset,n=column[3:];raw=bytearray(n*8)
                for byte in range(8):raw[byte::8]=self.binary[offset+byte*n:offset+(byte+1)*n]
                values=struct.unpack('<'+'Q'*n,raw)
                values=[_float(v^(_bits(predictors[i].get(field,0.0)) if predictors else 0)) for i,v in zip(positions,values)]
            else:values=self.expand(column[3])
            for i,value in zip(positions,values,strict=True):records[i][field]=value
        return records


BASE_FIELDS=('x','r','baseline','size','font','glyph')
RESIDUAL_FIELDS={'ink_x':('x','width'),'ink_r':('x','width'),'top':('baseline','size'),'bottom':('baseline','size')}


def predictions(bases,metrics):
    result=[]
    for g in bases:
        values={'origin_x':g.get('x',0.0)}
        key=(g.get('font'),g.get('glyph'))
        for field,(origin,scale) in RESIDUAL_FIELDS.items():
            coefficient=metrics.get(key,{}).get(field)
            if coefficient is not None:
                factor=g['r']-g['x'] if scale=='width' else g['size']
                numerator,denominator=coefficient
                values[field]=g[origin]+numerator*(factor/denominator)
        result.append(values)
    return result


def encode(page,compress=True):
    glyphs=[];words=[];counts=[]
    line_indices={row['id']:i for i,row in enumerate(page['lines'])}
    region_indices={row['id']:i for i,row in enumerate(page['regions'])}
    word_indices={row['id']:i for i,row in enumerate(page['words'])}
    by_line=defaultdict(list)
    for index,original in enumerate(page['words']):
        word=dict(original);items=word.pop('glyphs',None);counts.append(None if items is None else len(items))
        derived=derived_word(page['id'],word,items or [])
        for key,value in derived.items():
            if key in word and word[key]==value:del word[key]
        if word.get('reading_order')==index:del word['reading_order']
        if original['line'] in line_indices:word['line']=line_indices[original['line']]
        line=page['lines'][line_indices[original['line']]]
        for key in ('baseline','size'):
            if key in word and word[key]==line.get(key):del word[key]
        if original['region'] in region_indices:word['region']=region_indices[original['region']]
        glyphs.extend(items or []);by_line[original['line']].extend(items or []);words.append(word)
    lines=[]
    for index,original in enumerate(page['lines']):
        line=dict(original)
        for key,value in derived_line(page['id'],by_line[line['id']]).items():
            if key in line and line[key]==value:del line[key]
        if line.get('reading_order')==index:del line['reading_order']
        line['words']=[word_indices.get(w,w) for w in line['words']]
        if line['region'] in region_indices:line['region']=region_indices[line['region']]
        lines.append(line)
    regions=[];region_lines={l['region']:l['id'] for l in page['lines']}
    for index,original in enumerate(page['regions']):
        region=dict(original);line=region_lines.get(region['id'])
        if line is not None and region['id']==region_identity(page['id'],line):
            del region['id'];region['_line']=line_indices[line]
        if line is not None:
            source=page['lines'][line_indices[line]]
            if region.get('bounds')==[source['x'],source['top'],source['r'],source['bottom']]:
                del region['bounds'];region['_bounds']=line_indices[line]
        if region.get('reading_order')==index:del region['reading_order']
        regions.append(region)
    bases=[{k:g[k] for k in BASE_FIELDS if k in g} for g in glyphs]
    residuals=[{k:v for k,v in g.items() if k not in BASE_FIELDS} for g in glyphs]
    metrics={};defaults={}
    for g in glyphs:
        key=(g.get('font'),g.get('glyph'));values=metrics.setdefault(key,{})
        defaults.setdefault(key,{k:g[k] for k in ('text','original','mapping','unresolved') if k in g})
        if 'width' not in values and g['size']:values['width']=round((g['r']-g['x'])/g['size'],6)
        for field,(origin,scale) in RESIDUAL_FIELDS.items():
            factor=g['r']-g['x'] if scale=='width' else g['size']
            if field in g and field not in values and factor:
                coefficient=Fraction((g[field]-g[origin])/factor).limit_denominator(1000000)
                values[field]=[coefficient.numerator,coefficient.denominator]
    for g,record in zip(glyphs,residuals):
        for key,value in defaults[(g.get('font'),g.get('glyph'))].items():
            if key in record and record[key]==value:del record[key]
    previous=0.0;coordinates=[]
    for g in glyphs:
        width=metrics[(g.get('font'),g.get('glyph'))].get('width',0.0)
        coordinates.extend([_bits(g['x'])^_bits(previous),_bits(g['r'])^_bits(_single(g['x']+g['size']*width))])
        previous=g['r']
    codec=Columns()
    metric_indices={key:i for i,key in enumerate(metrics)}
    raw=struct.pack('<'+'Q'*len(coordinates),*coordinates)
    codec.binary.extend(b''.join(raw[n::8] for n in range(8)))
    header=[codec.intern({k:v for k,v in page.items() if k not in ('words','lines','regions')}),counts,
            codec.write(words),codec.write(lines),codec.write(regions),codec.write([{k:v for k,v in b.items() if k not in ('x','r','font','glyph')}|{'type':metric_indices[(b['font'],b['glyph'])]} for b in bases]),
            codec.write(residuals,predictions(bases,metrics)),codec.intern([[*k,v,defaults[k]] for k,v in metrics.items()])]
    encoded=json.dumps([header,codec.strings],ensure_ascii=False,separators=(',',':')).encode()
    raw=struct.pack('<I',len(encoded))+encoded+codec.binary
    return b'SHAS2'+(lzma.compress(raw,preset=6) if compress else raw)


def share(content,values,indices,defer=False):
    raw=content[5:] if defer else lzma.decompress(content[5:]);length=struct.unpack_from('<I',raw)[0]
    header,strings=json.loads(raw[4:4+length]);codec=Columns(bytearray(raw[4+length:]),strings)
    shared=[]
    for font,glyph,metrics,defaults in codec.expand(header[7]):
        key=json.dumps([metrics,defaults],ensure_ascii=False,sort_keys=True,separators=(',',':'))
        if key not in indices:indices[key]=len(values);values.append([metrics,defaults])
        shared.append([font,glyph,indices[key]])
    header[7]=codec.intern(shared)
    words=codec.read(header[2]);lines=codec.read(header[3]);members=defaultdict(list)
    for i,word in enumerate(words):members[word['line']].append(i)
    for i,line in enumerate(lines):
        if line.get('words')==members[i]:del line['words']
    header[3]=codec.write(lines)
    encoded=json.dumps([header,codec.strings],ensure_ascii=False,separators=(',',':')).encode()
    raw=struct.pack('<I',len(encoded))+encoded+codec.binary
    if defer:return raw,{i:values[i] for _,_,i in shared}
    return b'SHAS3'+lzma.compress(raw,preset=6)


def decode(content,shared_metrics=None):
    raw=lzma.decompress(content[5:]);length=struct.unpack_from('<I',raw)[0]
    header,strings=json.loads(raw[4:4+length]);codec=Columns(raw[4+length:],strings)
    metadata,counts,wt,lt,rt,bt,gt,mt=header
    page=codec.expand(metadata);words=codec.read(wt);lines=codec.read(lt);regions=codec.read(rt)
    bases=codec.read(bt);entries=codec.expand(mt)
    if content.startswith(b'SHAS3'):
        if shared_metrics is None:raise ValueError('Shared page measurements are required')
        entries=[[f,g,*shared_metrics[i]] for f,g,i in entries]
    metrics={(f,g):v for f,g,v,d in entries};defaults={(f,g):d for f,g,v,d in entries}
    for base in bases:
        font,glyph,_,_=entries[base.pop('type')];base.update(font=font,glyph=glyph)
    n=len(bases)*2;raw=bytearray(n*8)
    for byte in range(8):raw[byte::8]=codec.binary[byte*n:(byte+1)*n]
    coordinates=struct.unpack('<'+'Q'*n,raw);previous=0.0
    for i,g in enumerate(bases):
        g['x']=_float(coordinates[i*2]^_bits(previous))
        width=metrics[(g.get('font'),g.get('glyph'))].get('width',0.0)
        g['r']=_float(coordinates[i*2+1]^_bits(_single(g['x']+g['size']*width)));previous=g['r']
    glyphs=[b|defaults[(b.get('font'),b.get('glyph'))]|g for b,g in zip(bases,codec.read(gt,predictions(bases,metrics)),strict=True)]
    cursor=0;by_line=defaultdict(list);line_words=defaultdict(list)
    for index,(word,count) in enumerate(zip(words,counts,strict=True)):
        items=[] if count is None else glyphs[cursor:cursor+count];cursor+=count or 0
        if count is not None:word['glyphs']=items
        derived=derived_word(page['id'],word,items)
        for k,v in derived.items():word.setdefault(k,v)
        word.setdefault('reading_order',index);by_line[word['line']].extend(items);line_words[word['line']].append(index)
    for index,line in enumerate(lines):
        for k,v in derived_line(page['id'],by_line[index]).items():line.setdefault(k,v)
        line.setdefault('reading_order',index)
        line['words']=[words[w]['id'] if type(w) is int else w for w in line.get('words',line_words[index])]
    for index,region in enumerate(regions):
        if '_line' in region:region['id']=region_identity(page['id'],lines[region.pop('_line')]['id'])
        if '_bounds' in region:
            line=lines[region.pop('_bounds')];region['bounds']=[line['x'],line['top'],line['r'],line['bottom']]
        region.setdefault('reading_order',index)
    for word in words:
        if type(word['line']) is int:
            line=lines[word['line']]
            for key in ('baseline','size'):word.setdefault(key,line[key])
            word['line']=line['id']
        if type(word['region']) is int:word['region']=regions[word['region']]['id']
    for line in lines:
        if type(line['region']) is int:line['region']=regions[line['region']]['id']
    page.update(words=words,lines=lines,regions=regions)
    return page
