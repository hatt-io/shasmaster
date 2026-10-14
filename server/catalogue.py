from urllib.parse import urlencode
from .config import EDITION
from .db import transaction, json_text

# Bounds published by Shas.org. The combined volume is catalogued without duplication.
TRACTATES = [
 ('berachos','Berachos','ברכות',2,'a',64,'a'),('shabbos','Shabbos','שבת',2,'a',157,'b'),
 ('eruvin','Eruvin','עירובין',2,'a',105,'a'),('pesachim','Pesachim','פסחים',2,'a',121,'b'),
 ('shekalim','Shekalim','שקלים',2,'a',22,'b'),('yoma','Yoma','יומא',2,'a',88,'a'),
 ('sukkah','Sukkah','סוכה',2,'a',56,'b'),('beitzah','Beitzah','ביצה',2,'a',40,'b'),
 ('rosh-hashanah','Rosh Hashanah','ראש השנה',2,'a',35,'a'),('taanis','Taanis','תענית',2,'a',31,'a'),
 ('megillah','Megillah','מגילה',2,'a',32,'a'),('moed-katan','Moed Katan','מועד קטן',2,'a',29,'a'),
 ('chagigah','Chagigah','חגיגה',2,'a',27,'a'),('yevamos','Yevamos','יבמות',2,'a',122,'a'),
 ('kesubos','Kesubos','כתובות',2,'a',112,'b'),('nedarim','Nedarim','נדרים',2,'a',91,'b'),
 ('nazir','Nazir','נזיר',2,'a',66,'b'),('sotah','Sotah','סוטה',2,'a',49,'b'),
 ('gittin','Gittin','גיטין',2,'a',90,'b'),('kiddushin','Kiddushin','קידושין',2,'a',82,'b'),
 ('bava-kamma','Bava Kamma','בבא קמא',2,'a',119,'b'),('bava-metzia','Bava Metzia','בבא מציעא',2,'a',119,'a'),
 ('bava-basra','Bava Basra','בבא בתרא',2,'a',176,'b'),('sanhedrin','Sanhedrin','סנהדרין',2,'a',113,'b'),
 ('makkos','Makkos','מכות',2,'a',24,'b'),('shevuos','Shevuos','שבועות',2,'a',49,'b'),
 ('avodah-zarah','Avodah Zarah','עבודה זרה',2,'a',76,'b'),('horayos','Horayos','הוריות',2,'a',14,'a'),
 ('zevachim','Zevachim','זבחים',2,'a',120,'b'),('menachos','Menachos','מנחות',2,'a',110,'a'),
 ('chullin','Chullin','חולין',2,'a',142,'a'),('bechoros','Bechoros','בכורות',2,'a',61,'a'),
 ('arachin','Arachin','ערכין',2,'a',34,'a'),('temurah','Temurah','תמורה',2,'a',34,'a'),
 ('kereisos','Kereisos','כריתות',2,'a',28,'b'),('meilah','Meilah','מעילה',2,'a',22,'a'),
 ('kinnim','Kinnim','קינים',22,'b',25,'a'),('tamid','Tamid','תמיד',25,'b',33,'b'),
 ('middos','Middos','מידות',34,'a',37,'b'),('niddah','Niddah','נדה',2,'a',73,'a'),
]

def initialize_catalogue():
    sequence = 0
    with transaction() as conn:
        for order, (name,label,hebrew,start,start_amud,end,end_amud) in enumerate(TRACTATES):
            source = 'meilah' if name in ('kinnim','tamid','middos') else name
            conn.execute('INSERT OR IGNORE INTO tractate VALUES(?,?,?,?,?,?,?,?,?)', (name,label,hebrew,order,start,start_amud,end,end_amud,source))
            for index in range(start*2+(start_amud=='b'), end*2+(end_amud=='b')+1):
                daf, side = divmod(index,2)
                amud = 'b' if side else 'a'
                page_id = f'{name}-{daf}{amud}'
                url = 'https://www.shas.org/daf-pdf/api/?'+urlencode({'masechta':source,'daf':daf,'amud':amud})
                conn.execute('INSERT OR IGNORE INTO page(id,tractate,daf,amud,sequence,edition,source_url) VALUES(?,?,?,?,?,?,?)', (page_id,name,daf,amud,sequence,EDITION,url))
                sequence += 1
    return sequence
