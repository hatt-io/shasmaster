"""Recover missing Unicode from identical, already identified source outlines."""
from functools import lru_cache
from io import BytesIO
from fractions import Fraction
import hashlib
import json
import unicodedata
import pymupdf
from fontTools.ttLib import TTFont
from fontTools.agl import toUnicode
from fontTools.cffLib import CFFFontSet
from fontTools.pens.recordingPen import RecordingPen
from .config import DATA
from .db import digest, read, transaction, job_progress,migrate

PRINTED_GLYPHS=[{
    'font':'f480a605899f2ec8afbb7d8056b1a36f45a6d4f4b74d4dfe502107f1eae271c6',
    'glyph':145,'unicode':'נ','page':'yevamos-111b','asset':'pdf/yevamos-111b.pdf',
    'source_sha':'cc5ea48037d5dfc4658b36ac92d9625b78c8560ba2bf9e548df87e543ca3f0c8',
    'word':'yevamos-111b:word:e0b557609ccbbf11a66399f8','method':'source-print',
},{
    'font':'7bbbbb0c9fe5395024e650dbf24e4153d95ed03d043b3e8687cca6d75db7fca9',
    'glyph':145,'unicode':'נ','page':'bava-basra-100a','asset':'pdf/bava-basra-100a.pdf',
    'source_sha':'1890c65e1f4602c9db35076046cd2adcbf06637e0711a032ef1c4453c5615afb',
    'word':'bava-basra-100a:word:0f3aab9b080f84978717ffd5','method':'source-print',
},{
    'font':'d7c1a6fe008aa6de356d34ed410906663b7e6f7f543bb6d94fa88e472e7332a4',
    'glyph':145,'unicode':'נ','page':'shabbos-100a','asset':'pdf/shabbos-100a.pdf',
    'source_sha':'6fb6234371accc29f4b439668b996d1ab5a70cb79dc8a9a6c2f782095418e552',
    'word':'shabbos-100a:word:6046dedc65ed0688369adf40','method':'source-print',
},{
    'font':'47345963b37c387864fac6d36a01dd26e25896f075ec595e69fcdf82e54120d2',
    'glyph':145,'unicode':'נ','page':'gittin-10a','asset':'pdf/gittin-10a.pdf',
    'source_sha':'f8c0e3eaaefe56a30e591f79ac7e8ee37798e9e2a8dddba5ac181d8cd1b9bf40',
    'word':'gittin-10a:word:38ff1c8ce87f1775f73f3860','method':'source-print',
},{
    'font':'f6be818bcb4cb4f9dfe50b2f086c597f30bec70ed3d8b95eca324482a1a997de',
    'glyph':145,'unicode':'נ','page':'gittin-27a','asset':'pdf/gittin-27a.pdf',
    'source_sha':'6a40d54c11069e00b3b2cd29b19e15d92d85a718047d25ece601a7a4fe91938c',
    'word':'gittin-27a:word:af9e86e73c1300ea3b46a931','method':'source-print',
},{
    'font':'ff2ad70635e0a0da36bc5a847fdb28d6e0eecac1dfe3a31954183074e4d9b088',
    'glyph':145,'unicode':'נ','page':'kiddushin-8a','asset':'pdf/kiddushin-8a.pdf',
    'source_sha':'cbc1bbeb2350ff0ff3d7b2f2b331511f2e3d0759abdd6ee62119efa31dd2dc6e',
    'word':'kiddushin-8a:word:03d93c1b743878bbc346aa86','method':'source-print',
},{
    'font':'03d2805e9ef012841bc80f12d71c59393aa8906986544129a266f69b3fc3d81c',
    'glyph':17,'unicode':'נ','page':'yoma-20b','asset':'pdf/yoma-20b.pdf',
    'source_sha':'e60aa4f139309d6a78f3f2d58ea1c93cdd7c605a67a3b619b3f6ec2849a72c4f',
    'word':'yoma-20b:word:3564f330819e047c998f0a82','method':'source-print',
},{
    'font':'f6e3c971456135adb5aeadabd79e594832f861b20baeb9bd79516681172d2de3',
    'glyph':22,'unicode':'נ','page':'menachos-17a','asset':'pdf/menachos-17a.pdf',
    'source_sha':'46c8d3ddf937cdb65762c758c28ee753cde49b12e1ccadf6425443ec05bc5ba8',
    'word':'menachos-17a:word:45da2fb842c03aef5e258e3e','method':'source-print',
},{
    'font':'827a6ec9896de94b76735ade38fc6446a6bc4d487411153c5f372b0084d47990',
    'glyph':27,'unicode':'נ','page':'berachos-24b','asset':'pdf/berachos-24b.pdf',
    'source_sha':'dc27c3bbae907e5008d8054b0194f9acf3548ecd0f41bb4f76f36ea6ffae08b8',
    'word':'berachos-24b:word:b1540ef44a708c2be90cfb99','method':'source-print',
    'evidence':'source/unresolved-fonts/827a6ec9896de94b76735ade38fc6446a6bc4d487411153c5f372b0084d47990-27.json',
},{
    'font':'144b4433abf937ef35259897f2d37f4058ad41ecd76c2db45fa4062934a36dad',
    'glyph':14,'unicode':'נ','page':'megillah-23a','asset':'pdf/megillah-23a.pdf',
    'source_sha':'c31f733220e1043264821aaea202bdff16d6d303f7a6a402f17d503ab179c1b0',
    'word':'megillah-23a:word:c7bc0e50cf6ea658c02da2a7','method':'source-print',
    'evidence':'source/unresolved-fonts/144b4433abf937ef35259897f2d37f4058ad41ecd76c2db45fa4062934a36dad-14.json',
},{
    'font':'9a20adb561ef1575f85ead60678abf72a15099a329fde08c9effe75d92de60e0',
    'glyph':1,'unicode':'נ','page':'chagigah-19b','asset':'pdf/chagigah-19b.pdf',
    'source_sha':'76154da89cfdaaf7338df8fc4bc1d2d97a56b07a78e3791d0cecfb37d2fb1bd8',
    'word':'chagigah-19b:word:e76dbe91585016c370fca9cf','method':'source-print',
    'evidence':'source/unresolved-fonts/9a20adb561ef1575f85ead60678abf72a15099a329fde08c9effe75d92de60e0-1.json',
},{
    'font':'42a3544109c9c8fddefaa1e8b896d7b8b9ce80103d8569b61927bf686c63214a',
    'glyph':27,'unicode':'נ','page':'nazir-46a','asset':'pdf/nazir-46a.pdf',
    'source_sha':'5551211df32a815790ae71c9e185941fafeaacc03ae2bd8f67535b231b7ad447',
    'word':'nazir-46a:word:cb53a2fef28c16fa36cc8e2f','method':'source-print',
    'evidence':'source/unresolved-fonts/42a3544109c9c8fddefaa1e8b896d7b8b9ce80103d8569b61927bf686c63214a-27.json',
},{
    'font':'ea07819cb6a8da40f7e5b912463a2358b11915166836fc07bfda2273fe0c47db',
    'glyph':25,'unicode':'נ','page':'nazir-47a','asset':'pdf/nazir-47a.pdf',
    'source_sha':'96e1d260c0d37addb9334d69add2ab72f5b1ef484bdcb008132b998835f667d6',
    'word':'nazir-47a:word:28037c1bdb3e91fcf7906395','method':'source-print',
    'evidence':'source/unresolved-fonts/ea07819cb6a8da40f7e5b912463a2358b11915166836fc07bfda2273fe0c47db-25.json',
},
{
    "font": "81d75091c00fdb84e9730522ad3802015d1943da83b57cd12420c0f3f792ca15",
    "glyph": 13,
    "page": "menachos-15b",
    "source_sha": "022d239e7fc42fcffd80caeb9aa70833d86de22f9bfa4d5c4dae4da51028e263",
    "word": "menachos-15b:word:5fed55283d8bac974724f62e",
    "unicode": "נ",
    "asset": "pdf/menachos-15b.pdf",
    "method": "source-print",
    "evidence": "source/unresolved-fonts/81d75091c00fdb84e9730522ad3802015d1943da83b57cd12420c0f3f792ca15-13.json"
},
{
    "font": "3aeb4c85588096cd0f0c7430782b336fe474effdb7e59b8d521bc052351052c4",
    "glyph": 14,
    "page": "menachos-20b",
    "source_sha": "ec099bb1481f25d03c2f31a104a2c195284585c7511fc3f7fa6b5cc02b96d027",
    "word": "menachos-20b:word:d727659dac254f7e3019b3d4",
    "unicode": "נ",
    "asset": "pdf/menachos-20b.pdf",
    "method": "source-print",
    "evidence": "source/unresolved-fonts/3aeb4c85588096cd0f0c7430782b336fe474effdb7e59b8d521bc052351052c4-14.json"
},
{
    "font": "76644eb9aaf141a753f580c58b8cdf3c4cd633f521338e4068328e12d1614c81",
    "glyph": 28,
    "page": "menachos-48a",
    "source_sha": "bffbd1de4d614552594d8731aedb0a99dbbeb3024d592ff912342a0b1cfd09a3",
    "word": "menachos-48a:word:e04432a0d08ac1de6bc67a60",
    "unicode": "נ",
    "asset": "pdf/menachos-48a.pdf",
    "method": "source-print",
    "evidence": "source/unresolved-fonts/76644eb9aaf141a753f580c58b8cdf3c4cd633f521338e4068328e12d1614c81-28.json"
},
{
    "font": "26e9b02b934b35f728ad283075a3570156492eb0ff29d06f7ce65983bcd17dc7",
    "glyph": 20,
    "page": "menachos-65a",
    "source_sha": "6f4278ad25ffb2863e3cbcb76c83d4bf2f6314ef7500b1c1e12eff1fc7445c4c",
    "word": "menachos-65a:word:5f7b47f67113236545c31306",
    "unicode": "נ",
    "asset": "pdf/menachos-65a.pdf",
    "method": "source-print",
    "evidence": "source/unresolved-fonts/26e9b02b934b35f728ad283075a3570156492eb0ff29d06f7ce65983bcd17dc7-20.json"
},
{
    "font": "05922133695f8c43f9b658ed54d00de86b6a4eb75d1bfc6cff56f1e004800e28",
    "glyph": 20,
    "page": "menachos-94b",
    "source_sha": "566f51b972f97bcc37cac755504cc63d6e3f01eda2a8b6286ae66116e60cf9f3",
    "word": "menachos-94b:word:8207fbd721c64237d66ee397",
    "unicode": "נ",
    "asset": "pdf/menachos-94b.pdf",
    "method": "source-print",
    "evidence": "source/unresolved-fonts/05922133695f8c43f9b658ed54d00de86b6a4eb75d1bfc6cff56f1e004800e28-20.json"
},
{
    "font": "cf9159a03f719413116f3e68de34eb410f3f702fd79d16aeb0fe043da13e808a",
    "glyph": 19,
    "page": "menachos-107a",
    "source_sha": "0cbbe26ad432d808b52cbba49ed552be048a772da528321b3bfd929e5dd01193",
    "word": "menachos-107a:word:1bfc68985cfa7e5b672d34c2",
    "unicode": "נ",
    "asset": "pdf/menachos-107a.pdf",
    "method": "source-print",
    "evidence": "source/unresolved-fonts/cf9159a03f719413116f3e68de34eb410f3f702fd79d16aeb0fe043da13e808a-19.json"
},
{
    "font": "font-choice:0ec49fc350c98f2c8362adf65ec4f87f9cde920230284856683b8bec53f2e0cf",
    "glyph": 145,
    "page": "meilah-22a",
    "source_sha": "9a9f7b9d4bb4b5f637c60dfd7312732a7968e37eb929a992e58fb3f9b71d1def",
    "word": "meilah-22a:word:22eacbb76f1c2267a7168344",
    "unicode": "נ",
    "asset": "pdf/meilah-22a.pdf",
    "method": "source-print",
    "evidence": "source/unresolved-fonts/font-choice_0ec49fc350c98f2c8362adf65ec4f87f9cde920230284856683b8bec53f2e0cf-145.json"
},
{
    "font": "font-choice:90f2e769eae27abc45f1d0107c90696ab45d8a25ba0eb3d9fdfe2b4c9de7adea",
    "glyph": 145,
    "page": "meilah-22a",
    "source_sha": "9a9f7b9d4bb4b5f637c60dfd7312732a7968e37eb929a992e58fb3f9b71d1def",
    "word": "meilah-22a:word:f757b914f32f4aad4c2fdcf9",
    "unicode": "נ",
    "asset": "pdf/meilah-22a.pdf",
    "method": "source-print",
    "evidence": "source/unresolved-fonts/font-choice_90f2e769eae27abc45f1d0107c90696ab45d8a25ba0eb3d9fdfe2b4c9de7adea-145.json"
},
{
    "font": "font-choice:1680d59282cf912c01eb7da9445eb2c77ff5c84adb971b72b1596f2e52090551",
    "glyph": 145,
    "page": "meilah-22a",
    "source_sha": "9a9f7b9d4bb4b5f637c60dfd7312732a7968e37eb929a992e58fb3f9b71d1def",
    "word": "meilah-22a:word:07739ac675aa3f0e2328b2b6",
    "unicode": "נ",
    "asset": "pdf/meilah-22a.pdf",
    "method": "source-print",
    "evidence": "source/unresolved-fonts/font-choice_1680d59282cf912c01eb7da9445eb2c77ff5c84adb971b72b1596f2e52090551-145.json"
},
{
    "font": "font-choice:1ecbac4b1cbd39908b1f6fb804d5d3436dbd01e7b140680edbdbaf84deee3390",
    "glyph": 145,
    "page": "meilah-22a",
    "source_sha": "9a9f7b9d4bb4b5f637c60dfd7312732a7968e37eb929a992e58fb3f9b71d1def",
    "word": "meilah-22a:word:53195c11ea9ed67f2c32b8c4",
    "unicode": "נ",
    "asset": "pdf/meilah-22a.pdf",
    "method": "source-print",
    "evidence": "source/unresolved-fonts/font-choice_1ecbac4b1cbd39908b1f6fb804d5d3436dbd01e7b140680edbdbaf84deee3390-145.json"
},
{
    "font": "font-choice:869ea0689d3c19e2b9657823f930850b0e08760d4e587db3a8e60597c8c0ce15",
    "glyph": 145,
    "page": "meilah-22a",
    "source_sha": "9a9f7b9d4bb4b5f637c60dfd7312732a7968e37eb929a992e58fb3f9b71d1def",
    "word": "meilah-22a:word:f6f3218ec51c033ac4dc4a96",
    "unicode": "נ",
    "asset": "pdf/meilah-22a.pdf",
    "method": "source-print",
    "evidence": "source/unresolved-fonts/font-choice_869ea0689d3c19e2b9657823f930850b0e08760d4e587db3a8e60597c8c0ce15-145.json"
}
]


@lru_cache(maxsize=1)
def printed_glyphs():
    return {(seed['font'],seed['glyph']):seed for seed in PRINTED_GLYPHS}


def cff_outlines(top):
    result={};a,b,c,d,e,f=map(Fraction,top.FontMatrix)
    def point(value):
        if value is None:return None
        x,y=map(Fraction,value)
        return [str(a*x+c*y+e),str(b*x+d*y+f)]
    for index,name in enumerate(top.charset):
        pen=RecordingPen();top.CharStrings[name].draw(pen)
        if any(points for _,points in pen.value):
            result[index]=digest({'format':'cff','path':[(operator,[point(p) for p in points]) for operator,points in pen.value]})
    return result


@lru_cache(maxsize=80)
def outlines(buffer,extension='ttf'):
    if extension=='cff':
        font=CFFFontSet();font.decompile(BytesIO(buffer),None)
        return cff_outlines(font[font.fontNames[0]])
    result={}
    with TTFont(BytesIO(buffer)) as font:
        if 'glyf' not in font:
            return cff_outlines(font['CFF '].cff.topDictIndex[0]) if 'CFF ' in font else result
        units=font['head'].unitsPerEm
        glyf=font['glyf']
        for index,name in enumerate(font.getGlyphOrder()):
            try:
                coordinates,ends,flags=glyf[name].getCoordinates(glyf)
                if not coordinates:continue
                # Keep coordinates, contour order and curve flags exact. Similar
                # shapes, empty glyphs and different outlines do not match.
                shape={
                    'coordinates':[(str(Fraction(x)/units),str(Fraction(y)/units)) for x,y in coordinates],
                    'ends':list(ends),'on_curve':[int(flag)&1 for flag in flags],
                }
                result[index]=digest(shape)
            except (KeyError,ValueError,IndexError):
                continue
    return result


@lru_cache(maxsize=80)
def font_asset(asset_path,fingerprint):
    with pymupdf.open(DATA/asset_path) as doc:
        for font in doc[0].get_fonts(full=True):
            _,ext,_,buffer=doc.extract_font(font[0])
            if hashlib.sha256(buffer).hexdigest()==fingerprint:
                return ext,buffer
    return '',b''


@lru_cache(maxsize=80)
def source_font(asset_path,fingerprint):
    ext,buffer=font_asset(asset_path,fingerprint)
    return outlines(buffer,ext) if ext in ('ttf','otf','cff') else {}


def glyph_unicode(name):
    text=toUnicode(name)
    if not text and name.endswith('final'):text=toUnicode('final'+name[:-5])
    if any(c=='\ufffd' or unicodedata.category(c)=='Co' for c in text):return ''
    return text


@lru_cache(maxsize=80)
def source_glyphs(asset_path,fingerprint):
    from .extract import cff_glyphs,ttf_glyphs
    ext,buffer=font_asset(asset_path,fingerprint)
    return cff_glyphs(buffer) if ext=='cff' else ttf_glyphs(buffer) if ext in ('ttf','otf') else {}


def source_glyph_names(asset_path,fingerprint):
    return {gid:glyph.get('name','') for gid,glyph in source_glyphs(asset_path,fingerprint).items() if isinstance(gid,int)}


def nonprinting_glyph(asset_path,fingerprint,glyph):
    info=source_glyphs(asset_path,fingerprint).get(glyph,{})
    return info.get('empty') is True and info.get('advance')==0


def printed_shapes():
    known={};errors=[]
    for seed in PRINTED_GLYPHS:
        try:shape=source_font(seed['asset'],seed['font']).get(seed['glyph'])
        except Exception as exc:
            errors.append({'font':seed['font'],'error':str(exc)});continue
        if shape:known.setdefault(shape,{}).setdefault(seed['unicode'],[]).append(seed)
    return known,errors


def recover_glyphs(buffer,extension='ttf'):
    known,errors=printed_shapes();recovered={}
    for glyph,shape in outlines(buffer,extension).items():
        interpretations=known.get(shape,{})
        if len(interpretations)==1:
            text,evidence=next(iter(interpretations.items()))
            recovered[glyph]={'unicode':text,'outline':shape,'sources':evidence}
    return recovered,errors


def recover_fonts():
    migrate()
    from .corrections import apply_correction
    with read() as conn:
        seeds=[dict(r) for r in conn.execute('''
            SELECT m.*,p.asset_path FROM font_mapping m
            JOIN page_font f ON f.font_fingerprint=m.font_fingerprint
            JOIN page p ON p.id=f.page_id
            GROUP BY m.font_fingerprint,m.glyph
        ''')]
        targets=[dict(r) for r in conn.execute('''
            SELECT json_extract(i.evidence_json,'$.font') AS font,
                   json_extract(i.evidence_json,'$.glyph') AS glyph,
                   p.id AS page_id,p.asset_path
            FROM source_issue i JOIN page p ON p.id=i.page_id
            WHERE i.kind='unmapped-glyph' AND i.resolved=0
              AND p.active_revision IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM font_mapping m
                  WHERE m.font_fingerprint=json_extract(i.evidence_json,'$.font')
                    AND m.glyph=json_extract(i.evidence_json,'$.glyph'))
            GROUP BY font,glyph
        ''')]
    known,errors=printed_shapes()
    for seed in seeds:
        try:shape=source_font(seed['asset_path'],seed['font_fingerprint']).get(seed['glyph'])
        except Exception as exc:
            errors.append({'font':seed['font_fingerprint'],'error':str(exc)});continue
        if shape:
            known.setdefault(shape,{}).setdefault(seed['unicode'],[]).append({
                'font':seed['font_fingerprint'],'glyph':seed['glyph'],
                'provenance':json.loads(seed['provenance_json']),
            })
    recovered=0;unresolved=[]
    job_progress('font-recovery','fonts','running',0,len(targets))
    for index,target in enumerate(targets,1):
        try:
            printed=printed_glyphs().get((target['font'],target['glyph']))
            name=source_glyph_names(target['asset_path'],target['font']).get(target['glyph'],'')
            named=glyph_unicode(name)
            nonprinting=nonprinting_glyph(target['asset_path'],target['font'],target['glyph'])
            shape=source_font(target['asset_path'],target['font']).get(target['glyph'])
            interpretations=known.get(shape,{})
            if printed or nonprinting or named or len(interpretations)==1:
                if printed:
                    text=printed['unicode'];evidence=printed
                elif nonprinting:
                    text='';evidence={'method':'nonprinting-glyph','page':target['page_id'],'font':target['font'],'glyph':target['glyph'],'outline':'empty','advance':0}
                elif named:
                    text=named;evidence={'method':'font-glyph-name','name':name,'page':target['page_id'],'font':target['font'],'glyph':target['glyph']}
                else:
                    text,sources=next(iter(interpretations.items()))
                    evidence={'method':'identical-glyph-outline','outline':shape,'sources':sources}
                payload={'font_fingerprint':target['font'],'glyph':target['glyph'],'unicode':text,'evidence':evidence}
                correction_id='font-recovery-'+digest(payload)
                with transaction() as conn:
                    existing=conn.execute('SELECT 1 FROM font_mapping WHERE font_fingerprint=? AND glyph=?',(target['font'],target['glyph'])).fetchone()
                    page=conn.execute('SELECT active_revision FROM page WHERE id=?',(target['page_id'],)).fetchone()
                    if not existing and page and page['active_revision']:
                        apply_correction(conn,target['page_id'],page['active_revision'],'font',payload,correction_id)
                        recovered+=1
                        print(f'Recovered font {target["font"][:12]}, glyph {target["glyph"]}: {text or "nonprinting"}',flush=True)
            else:
                reason='Conflicting outline mappings' if interpretations else 'No identified matching outline' if shape else 'Outline unavailable'
                unresolved.append({'font':target['font'],'glyph':target['glyph'],'reason':reason})
        except Exception as exc:
            errors.append({'font':target['font'],'glyph':target['glyph'],'error':str(exc)})
        job_progress('font-recovery','fonts','running',index,len(targets),recovered=recovered,unresolved=unresolved,errors=errors)
    job_progress('font-recovery','fonts','incomplete' if errors or unresolved else 'complete',len(targets),len(targets),recovered=recovered,unresolved=unresolved,errors=errors)
    print(f'Recovered {recovered} font mappings; {len(unresolved)} unresolved; {len(errors)} recovery failures.',flush=True)


def repair_legacy_mappings(page, geometry, legacy):
    """Repair the superseded decoder through retained font/code evidence."""
    from .extract import LEGACY_HEBREW
    from .corrections import apply_correction
    targets=set();decoded={};codes={}
    for word in geometry['words']:
        for glyph in word.get('glyphs',[]):
            font=glyph['font'];encoding=legacy.get(font)
            if not encoding or font.startswith('font-choice:'):continue
            key=(font,glyph['glyph'])
            value=LEGACY_HEBREW[encoding].get(chr(glyph['original']))
            decoded.setdefault(key,set()).add(value)
            codes.setdefault(key,set()).add(glyph['original'])
            if glyph.get('mapping')=='hebrew-macroman-nun':targets.add(key)
    repaired=0
    for font,glyph in sorted(targets):
        values=decoded[font,glyph]
        if len(values)!=1:continue
        text=next(iter(values))
        if not text or len(text)!=1 or not 'א'<=text<='ת':continue
        payload={'font_fingerprint':font,'glyph':glyph,'unicode':text,'evidence':{
            'method':'legacy-character-code','encoding':legacy[font],
            'original_codes':sorted(codes[font,glyph]),
            'superseded_method':'hebrew-macroman-nun',
            'page':page['id'],'source_sha':geometry['source_sha'],
            'source_revision':geometry['revision'],'asset':page['asset_path'],
        }}
        with transaction() as conn:
            if conn.execute('SELECT 1 FROM font_mapping WHERE font_fingerprint=? AND glyph=?',(font,glyph)).fetchone():continue
            print(f'Recovering legacy font {font[:12]}, glyph {glyph} from original character codes',flush=True)
            apply_correction(conn,page['id'],geometry['revision'],'font',payload,'font-encoding-'+digest(payload))
        repaired+=1
        print(f'Recovered legacy font {font[:12]}, glyph {glyph}: {text}',flush=True)
    return repaired


def repair_font_text(tractate=None):
    """Re-import source fragments affected by encoding and subset repairs."""
    migrate()
    from .extract import extract_page,load_geometry,legacy_font_encodings,LEGACY_HEBREW
    profiles={};errors=[];repaired=0;repaired_fonts=0
    job_id='font-text-recovery'+(':'+tractate if tractate else '')
    with read() as conn:
        pages=[dict(row) for row in conn.execute("SELECT * FROM page WHERE acquisition_state='complete' AND active_revision IS NOT NULL AND (? IS NULL OR tractate=?) ORDER BY sequence",(tractate,tractate))]
    job_progress(job_id,'fonts','running',0,len(pages))
    for index,page in enumerate(pages,1):
        needed=False
        try:
            geometry=load_geometry(page['id'],include_artwork=False)
            if geometry.get('font_resolution_revision')!='font-subsets-1':
                with pymupdf.open(DATA/page['asset_path']) as doc:
                    names={}
                    for font in doc[0].get_fonts(full=True):names.setdefault(font[3].split('+')[-1],set()).add(font[0])
                    needed=any(len(values)>1 for values in names.values())
            if not needed:
                font_chars={}
                for word in geometry['words']:
                    for glyph in word.get('glyphs',[]):font_chars.setdefault(glyph['font'],[]).append(chr(glyph['original']))
                legacy=legacy_font_encodings(font_chars)
                mappings=repair_legacy_mappings(page,geometry,legacy)
                if mappings:
                    repaired_fonts+=mappings
                    geometry=load_geometry(page['id'],include_artwork=False)
                for word in geometry['words']:
                    if word['state']=='corrected' or not word.get('glyphs'):continue
                    pieces=[];changed=False
                    for glyph in word['glyphs']:
                        fingerprint=glyph['font']
                        if fingerprint not in profiles:
                            profiles[fingerprint]={gid:glyph_unicode(name) for gid,name in source_glyph_names(page['asset_path'],fingerprint).items()}
                        named=profiles[fingerprint].get(glyph['glyph'],'')
                        text=glyph['text']
                        if glyph.get('mapping')!='correction':
                            if any('א'<=c<='ת' for c in named):text=named
                            elif legacy.get(fingerprint):text=LEGACY_HEBREW[legacy[fingerprint]].get(chr(glyph['original']),text)
                        changed|=text!=glyph['text'];pieces.append(text)
                    if any('א'<=c<='ת' for piece in pieces for c in piece):pieces.reverse()
                    expected=''.join(pieces)
                    known=not any(c=='\ufffd' or unicodedata.category(c)=='Co' for c in expected)
                    if changed or known and not word.get('ocr') and expected!=word['text']:
                        needed=True;break
            if needed:
                with transaction() as conn:
                    queued=conn.execute("UPDATE page SET extraction_state='pending' WHERE id=? AND active_revision=?",(page['id'],geometry['revision'])).rowcount
                if queued:
                    extract_page(page);repaired+=1
                    print(f'Recovered source text: {page["id"]}',flush=True)
        except Exception as exc:
            errors.append({'page':page['id'],'error':str(exc)})
            with transaction() as conn:
                from .db import json_text
                conn.execute('INSERT INTO source_issue(page_id,kind,evidence_json) VALUES(?,?,?)',(page['id'],'font-text-recovery',json_text({'error':str(exc)})))
        if index%20==0 or needed:
            job_progress(job_id,'fonts','running',index,len(pages),repaired=repaired,repaired_fonts=repaired_fonts,errors=errors)
    job_progress(job_id,'fonts','incomplete' if errors else 'complete',len(pages),len(pages),repaired=repaired,repaired_fonts=repaired_fonts,errors=errors)
    print(f'Recovered {repaired_fonts} font mappings and rebuilt {repaired} pages; {len(errors)} recovery failures.',flush=True)


if __name__=='__main__':
    recover_fonts();repair_font_text()
