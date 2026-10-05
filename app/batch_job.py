"""Process boundary makes long REST uploads cancellable without Qt threads."""
import argparse
import json
from pathlib import Path
from app.file_tools import transcribe_files


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',required=True)
    args=parser.parse_args()
    path=Path(args.request)
    data=json.loads(path.read_text(encoding='utf-8'))
    path.unlink(missing_ok=True)
    def emit(info): print(json.dumps(info,ensure_ascii=False),flush=True)
    try:
        files=transcribe_files(**data,progress=emit)
        emit({'stage':'complete','files':files})
        return 0
    except Exception as exc:
        emit({'stage':'failed','message':str(exc)})
        return 1


if __name__=='__main__':
    raise SystemExit(main())
