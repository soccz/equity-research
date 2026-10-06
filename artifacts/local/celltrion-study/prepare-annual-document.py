from pathlib import Path
import importlib.util,sys,os
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('archive_dart_doc', ROOT/'scripts/archive-dart-document.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.ROOT=Path(__file__).resolve().parent;(m.ROOT/'data/sources').mkdir(parents=True,exist_ok=True)
original=m.request
def checked(endpoint,params):
    body=original(endpoint,params);key=os.environ.get('DART_API_KEY','')
    if key and key.encode() in body:raise ValueError('Credential in response; content withheld')
    return body
m.request=checked
sys.argv=['archive-dart-document.py','--receipt','20260316001415','--dart-env','/mnt/20t/report/.env'];m.main()
