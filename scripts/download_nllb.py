"""Download the pinned, prequantized local NLLB model and verify its bytes."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'models/nllb-600m'
REPO = 'JustFrederik/nllb-200-distilled-600M-ct2-int8'
REVISION = '302d78f00e6fdb50a1064059df7c392b735e9d05'
FILES = {'config.json':159,'model.bin':622595991,'sentencepiece.bpe.model':4852054,
         'shared_vocabulary.txt':2568098,'special_tokens_map.json':3548,
         'tokenizer.json':17331176,'tokenizer_config.json':564,'README.md':3435}
MODEL_SHA = 'ed1beaf75134de7505315a5223162f56acff397eff6b50638a500d3936fe707b'


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8*1024*1024):
            digest.update(block)
    return digest.hexdigest()


def main():
    FOLDER.mkdir(parents=True,exist_ok=True)
    provenance = []
    for name,expected_size in FILES.items():
        target = FOLDER / name
        if not target.exists():
            url = f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}?download=true'
            partial = target.with_suffix(target.suffix+'.partial')
            print(f'Downloading {name}: {expected_size} bytes',flush=True)
            subprocess.run(['curl.exe','--fail','--location','--retry','2','--retry-all-errors',
                            '--max-time','1200','--silent','--show-error','--output',str(partial),url],check=True)
            if partial.stat().st_size != expected_size:
                raise ValueError(f'Size mismatch for {name}; partial retained')
            if name=='model.bin' and file_hash(partial)!=MODEL_SHA:
                raise ValueError('NLLB model SHA256 mismatch; partial retained')
            partial.replace(target)
        if target.stat().st_size != expected_size:
            raise ValueError(f'Existing file size mismatch: {name}')
        actual_hash = file_hash(target)
        if name=='model.bin' and actual_hash!=MODEL_SHA:
            raise ValueError('NLLB model SHA256 mismatch')
        provenance.append({'file':name,'size':expected_size,'sha256':actual_hash})
        print(f'Verified {name}',flush=True)
    (FOLDER/'provenance.json').write_text(json.dumps({'repository':REPO,'revision':REVISION,
        'license':'CC-BY-NC-4.0','quantization':'int8','files':provenance},indent=2),encoding='utf-8')
    print('NLLB local model installed and verified.',flush=True)


if __name__=='__main__':
    main()
