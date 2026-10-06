from pathlib import Path
import importlib.util, sys, os
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('archive_dart_doc',ROOT/'scripts/archive-dart-document.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.ROOT=Path(__file__).parent
original=m.request
def checked(endpoint, params):
    body=original(endpoint,params)
    if os.environ.get('DART_API_KEY','').encode() in body:
        raise ValueError('Credential in response; withheld')
    return body
m.request=checked
for receipt in ['20260715000004','20260821000495','20260819000254','20260922000361']:
    if (m.ROOT/'data/sources'/f'dart-document-{receipt}.manifest.json').exists():
        continue
    sys.argv=['archive-dart-document.py','--receipt',receipt,'--dart-env','/mnt/20t/report/.env']
    m.main()
