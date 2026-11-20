"""Explicit manual runner; never imported or executed by tests/web startup."""
from pathlib import Path
import json
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import PROJECT_ROOT, read_local_env
from app.adapters.thingo_probe import probe, ENDPOINT, MODEL


def main():
    config=read_local_env(PROJECT_ROOT/'.env')
    if config.get('THINGO_API_ENDPOINT')!=ENDPOINT or config.get('THINGO_MODEL')!=MODEL:
        raise RuntimeError('Local endpoint/model differs from authorized request')
    key=config.get('THINGO_API_KEY','').strip()
    if not key:raise RuntimeError('Local key missing')
    doc='859cc211586147da8d4a64d881271c88'
    # Fixed existing project database: no alternate credentials or external files.
    dbpath=PROJECT_ROOT/'backend/data/crosslink.sqlite3'
    with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
        row=db.execute('SELECT text FROM document_pages WHERE document_id=? AND page_number=1',(doc,)).fetchone()
    if not row or not row[0].strip():raise RuntimeError('Existing public page missing')
    excerpt=row[0][:300]
    result=probe(key=key,excerpt=excerpt,ledger=PROJECT_ROOT/'backend/data/thingo-single-probe.sqlite3')
    result.update({'document_id':doc,'physical_page':1})
    out=PROJECT_ROOT/'acceptance/thingo-single-probe.json'
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':
    try:main()
    except Exception:
        print('Probe stopped. No automatic retry. Inspect local permit ledger without exposing credentials.')
        sys.exit(1)
