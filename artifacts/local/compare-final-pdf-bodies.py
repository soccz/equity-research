from pathlib import Path
import json, hashlib, fitz
root=Path(__file__).resolve().parents[2]
old=json.loads((root/'artifacts/local/pdf-body-before-driver-unit.json').read_text())
pointer=json.loads((root/'data/latest.json').read_text());version=pointer['contentHash']
results=[];changed=[]
for name,before in old.items():
    path=root/'artifacts/live'/name
    doc=fitz.open(path);pdf_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    for i,page in enumerate(doc):
        assert version[:12] in page.get_text(),(name,i)
        pixels=page.get_pixmap(matrix=fitz.Matrix(1,1),clip=fitz.Rect(0,0,page.rect.width,page.rect.height-38),alpha=False).samples
        h=hashlib.sha256(pixels).hexdigest()
        same=len(before)==len(doc) and before[i]==h
        result=dict(file=name,page=i+1,pdfHash=pdf_hash,bodyPixelHash=h,bodyMatchesPreviouslyViewedPage=same)
        if not same:
            preview=root/'artifacts/local'/f"{version[:12]}-{path.stem}-review-{i+1}.png"
            page.get_pixmap(matrix=fitz.Matrix(1.4,1.4),alpha=False).save(preview)
            result['preview']=str(preview.relative_to(root));changed.append(result)
        results.append(result)
record=dict(snapshotHash=version,baseline='artifacts/local/pdf-body-before-driver-unit.json',method='Actual PDF pixels excluding the bottom 38pt version footer compared with all 203 previously viewed pages; changed pages rendered for fresh visual review.',pages=results,changedPages=changed)
(root/'artifacts/local'/f'{version[:12]}-pdf-body-comparison.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(total=len(results),unchanged=sum(x['bodyMatchesPreviouslyViewedPage'] for x in results),changed=[x['preview'] for x in changed]),ensure_ascii=False,indent=2))
