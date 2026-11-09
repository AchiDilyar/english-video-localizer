"""Download official sherpa ONNX assets into ignored local storage; no audio upload."""
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request


def main():
    root=Path(__file__).resolve().parents[3];folder=root/'models/diarization';folder.mkdir(parents=True,exist_ok=True)
    base='https://github.com/k2-fsa/sherpa-onnx/releases/download/'
    assets=[('segmentation.tar.bz2','speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2'),
            ('embedding.onnx','speaker-recongition-models/wespeaker_en_voxceleb_resnet34.onnx'),
            ('two-speakers-en.wav','speaker-segmentation-models/1-two-speakers-en.wav')]
    receipt=[]
    for name,suffix in assets:
        target=folder/name;url=base+suffix
        if not target.exists():
            with urllib.request.urlopen(url,timeout=60) as response,target.open('xb') as out:
                size=0
                while data:=response.read(1024*1024):
                    size+=len(data)
                    if size>100*1024**2:raise ValueError('Asset unexpectedly large')
                    out.write(data)
        receipt.append({'file':name,'url':url,'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        print(name,target.stat().st_size,flush=True)
    with tarfile.open(folder/'segmentation.tar.bz2','r:bz2') as archive:
        for member in archive.getmembers():
            if member.isfile() and Path(member.name).name in ['model.onnx','LICENSE','README.md']:
                target=folder/('segmentation.onnx' if Path(member.name).name=='model.onnx' else 'segmentation-'+Path(member.name).name)
                with archive.extractfile(member) as stream:target.write_bytes(stream.read())
    if not (folder/'segmentation.onnx').exists():raise ValueError('Segmentation model missing')
    receipt.append({'file':'segmentation.onnx','sha256':hashlib.sha256((folder/'segmentation.onnx').read_bytes()).hexdigest()})
    (folder/'provenance.json').write_text(json.dumps({'assets':receipt,'upstream_published_checksums':False,
        'fixture_scope':'official public engineering sample; not redistributed with source'},indent=2),encoding='utf-8')


if __name__=='__main__':main()
