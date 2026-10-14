"""Correct region membership without replacing word or artwork anchors."""
import json
from collections import defaultdict
from .db import digest,json_text


def apply_region(conn,geometry,item,correction_id,replay=False):
    from .corrections import number,CorrectionConflict
    regions={r['id']:dict(r) for r in geometry['regions']}
    lines={line['id']:line for line in geometry['lines']}
    target=item.get('id')
    if target and target not in regions:
        saved=conn.execute('SELECT * FROM region WHERE id=? AND page_revision=?',(target,geometry['revision'])).fetchone()
        if saved:
            regions[target]={'id':target,'kind':saved['kind'],'bounds':json.loads(saved['bounds_json']),'reading_order':saved['reading_order']}
        elif replay and item.get('lines') is not None:
            regions[target]={'id':target,'kind':item.get('kind','unclassified'),'bounds':item.get('bounds',[]),'reading_order':item.get('reading_order',0)}
        else:raise CorrectionConflict('Source region changed')
    selected=item.get('lines')
    legacy=selected is None
    if selected is None:
        if not target:raise ValueError('Select source fragments')
        selected=[line['id'] for line in lines.values() if line['region']==target]
    if not isinstance(selected,list) or not selected and not legacy or len(set(selected))!=len(selected) or any(lid not in lines for lid in selected):
        raise ValueError('Invalid source fragments')
    target=target or geometry['id']+':region:'+digest(['region',correction_id])[:24]
    old=regions.get(target)
    omitted=[lid for lid,line in lines.items() if line['region']==target and lid not in selected]
    expected=item.get('base_regions',{})
    if not replay:
        for lid in set(selected)|set(omitted):
            if lid in expected and expected[lid]!=lines[lid]['region']:
                raise CorrectionConflict('Source regions changed; reopen the correction')
    bounds=[number(v) for v in item['bounds']]
    if len(bounds)!=4 or bounds[2]<=bounds[0] or bounds[3]<=bounds[1]:raise ValueError('Invalid region bounds')
    if not legacy and any(line['x']<bounds[0]-.01 or line['top']<bounds[1]-.01 or line['r']>bounds[2]+.01 or line['bottom']>bounds[3]+.01 for line in (lines[lid] for lid in selected)):
        if not replay:raise ValueError('Region bounds must contain its source fragments')
        fragments=[lines[lid] for lid in selected]
        bounds=[min(bounds[0],*(l['x'] for l in fragments)),min(bounds[1],*(l['top'] for l in fragments)),max(bounds[2],*(l['r'] for l in fragments)),max(bounds[3],*(l['bottom'] for l in fragments))]
    kind=item.get('kind',old['kind'] if old else 'unclassified')
    if not isinstance(kind,str) or not kind or len(kind)>120:raise ValueError('Invalid region name')
    order=number(item.get('reading_order',old['reading_order'] if old else min(lines[lid]['reading_order'] for lid in selected)))
    regions[target]={'id':target,'kind':kind,'bounds':bounds,'reading_order':order}
    if not selected:
        conn.execute('UPDATE region SET kind=?,bounds_json=?,reading_order=? WHERE id=?',(kind,json_text(bounds),order,target))
        return {'region':target,'lines':[]}
    membership={lid:line['region'] for lid,line in lines.items()}
    affected={membership[lid] for lid in selected}|{target}
    for lid in selected:membership[lid]=target
    if omitted:
        remainder=geometry['id']+':region:'+digest(['region-remainder',correction_id])[:24]
        regions[remainder]={'id':remainder,'kind':old['kind'],'reading_order':old['reading_order']}
        for lid in omitted:membership[lid]=remainder
        affected.add(remainder)
    grouped=defaultdict(list)
    for lid,rid in membership.items():grouped[rid].append(lines[lid])
    for rid in affected:
        fragments=grouped.get(rid,[])
        if not fragments:continue
        region=regions[rid]
        if rid!=target:region['bounds']=[min(l['x'] for l in fragments),min(l['top'] for l in fragments),max(l['r'] for l in fragments),max(l['bottom'] for l in fragments)]
        conn.execute('INSERT INTO region VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET page_revision=excluded.page_revision,kind=excluded.kind,bounds_json=excluded.bounds_json,reading_order=excluded.reading_order',
                     (rid,geometry['revision'],region['kind'],json_text(region['bounds']),region['reading_order']))
    for word in geometry['words']:
        rid=membership[word['line']]
        if rid==word['region']:continue
        saved=conn.execute('SELECT geometry_json FROM occurrence WHERE id=?',(word['id'],)).fetchone()
        compact=json.loads(saved['geometry_json']);compact['region']=rid
        conn.execute('UPDATE occurrence SET region_id=?,geometry_json=? WHERE id=?',(rid,json_text(compact),word['id']))
    return {'region':target,'lines':selected}
