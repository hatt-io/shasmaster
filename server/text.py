import re
import unicodedata

HEBREW = re.compile('[\u05d0-\u05ea]+')

def normalize(text):
    text=unicodedata.normalize('NFKD',text)
    text=''.join(c for c in text if not unicodedata.combining(c))
    return re.sub('[^\u05d0-\u05ea\u05f3\u05f4\'\"]','',text).replace("'",'׳').replace('"','״')
