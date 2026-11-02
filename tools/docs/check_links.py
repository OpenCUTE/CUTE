#!/usr/bin/env python3
"""Check local HTML links and fragments across all three generated doc sites."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote,urlsplit

class Page(HTMLParser):
    def __init__(self,text):
        super().__init__();self.ids=set();self.links=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.add(a['id'])
        if tag=='a' and 'href' in a:self.links.append(a['href'])

def check(root):
    pages={p.resolve():Page(p.read_text()) for p in root.rglob('*.html')};errors=[];count=0
    for source,page in pages.items():
        for href in page.links:
            u=urlsplit(href)
            if u.scheme or u.netloc:continue
            name=unquote(u.path)
            target=(root/name.lstrip('/') if name.startswith('/') else source.parent/name).resolve() if name else source
            if target.is_dir():target/='index.html'
            count+=1
            if not target.is_file():errors.append({'page':str(source.relative_to(root)),'link':href,'error':'missing file'});continue
            fragment=unquote(u.fragment)
            if fragment and target in pages and fragment not in pages[target].ids:errors.append({'page':str(source.relative_to(root)),'link':href,'error':'missing anchor'})
    return {'pages':len(pages),'local_links':count,'errors':errors}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('site',type=lambda x:Path(x).resolve());p.add_argument('--report',type=Path);a=p.parse_args();r=check(a.site)
    data=json.dumps(r,ensure_ascii=False,indent=2)+'\n'
    if a.report:a.report.write_text(data)
    print(data);return bool(r['errors'])
if __name__=='__main__':raise SystemExit(main())
