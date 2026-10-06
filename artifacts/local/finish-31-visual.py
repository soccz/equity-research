from pathlib import Path
import json,hashlib,fitz
from PIL import Image,ImageOps,ImageDraw
ROOT=Path(__file__).resolve().parents[2]
pointer=json.loads((ROOT/'artifacts/local/last-verified-run.json').read_text())
run=json.loads((ROOT/pointer['file']).read_text());expected='862c4ed8540f788d3aad1e219c84cab6ef72a771c3e05a28c8c0206572617c42'
if run['status']!='artifacts_verified' or run['snapshotHash']!=expected:raise ValueError('31-model verification not finished')
out=ROOT/'artifacts/local/retail-study/visual';out.mkdir(exist_ok=True)
record=dict(snapshotHash=expected,status='awaiting_visual_inspection',financialApproval=False,pdfs={})
for name in ['costco','orion']:
 path=ROOT/f'artifacts/live/{name}.pdf';doc=fitz.open(path);thumbs=[];detail=[]
 for i,page in enumerate(doc):
  pix=page.get_pixmap(matrix=fitz.Matrix(.48,.48));im=Image.frombytes('RGB',[pix.width,pix.height],pix.samples);im=ImageOps.expand(im,border=(4,22,4,4),fill='white');ImageDraw.Draw(im).text((8,4),f'{name} {i+1}',fill='black');thumbs.append(im)
  if any(s in ''.join(page.get_text().split()) for s in ['회원비는이미사업손익','리스전액','종속기업취득산술','제과영업과바이오']):
   page.get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(out/f'{name}-{i+1}.png');detail.append(i+1)
 w=max(x.width for x in thumbs);h=max(x.height for x in thumbs);sheet=Image.new('RGB',(w*4,h*((len(thumbs)+3)//4)), '#cccccc')
 for i,im in enumerate(thumbs):sheet.paste(im,(i%4*w,i//4*h))
 sheet.save(out/f'{name}-contact.png')
 record['pdfs'][name]=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),pages=len(doc),details=detail)
(out/'inspection-manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2));print(json.dumps(record,ensure_ascii=False))
