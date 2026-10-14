"""Remember the user's own wording for exactly the same printed spelling."""
from .db import read, transaction, digest


def forget(occurrence_id, text):
    with transaction() as conn:
        word=conn.execute('SELECT text FROM occurrence WHERE id=?',(occurrence_id,)).fetchone()
        if word is None:raise KeyError(occurrence_id)
        conn.execute('DELETE FROM saved_meaning WHERE spelling=? AND text=?',(word['text'],text))


def remember(conn, spelling, text, direction='auto', created_at=None):
    if not isinstance(spelling, str) or not spelling or len(spelling)>20000:
        raise ValueError('Invalid saved spelling')
    if not isinstance(text, str) or len(text)>20000 or direction not in ('auto','ltr','rtl'):
        raise ValueError('Invalid saved meaning')
    if not text.strip():
        return
    conn.execute('INSERT OR IGNORE INTO saved_meaning(spelling,text,direction,created_at) '
                 'VALUES(?,?,?,coalesce(?,CURRENT_TIMESTAMP))',
                 (spelling,text,direction,created_at))


def suggestions_for_word(occurrence_id, offset=0, limit=24):
    with read() as conn:
        conn.execute('BEGIN')
        word=conn.execute('SELECT text FROM occurrence WHERE id=?',(occurrence_id,)).fetchone()
        if word is None:
            raise KeyError(occurrence_id)
        spelling=word['text']
        total=conn.execute('SELECT count(*) FROM saved_meaning WHERE spelling=?',(spelling,)).fetchone()[0]
        rows=conn.execute('SELECT text,direction FROM saved_meaning WHERE spelling=? '
                          'ORDER BY created_at DESC,text LIMIT ? OFFSET ?',
                          (spelling,limit,offset)).fetchall()
        return {'items':[{'id':digest([spelling,r['text']]),'text':r['text'],
                          'direction':r['direction']} for r in rows],
                'offset':offset,'total':total}
