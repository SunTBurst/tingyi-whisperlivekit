"""Cancellable model operations in a process owned by the desktop tools panel."""
import argparse
import json
import sys
from app.model_manager import download_model, remove_model, installed_models, backend_availability


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['download','remove','list'])
    parser.add_argument('value',nargs='?')
    args=parser.parse_args()
    def emit(value): print(json.dumps(value,ensure_ascii=False),flush=True)
    try:
        if args.action=='download':
            path=download_model(args.value,progress=emit)
            emit({'stage':'ready','path':str(path)})
        elif args.action=='remove':
            emit({'stage':'removed','path':str(remove_model(args.value))})
        else: emit({'models':installed_models(),'backends':backend_availability()})
    except Exception as exc:
        emit({'stage':'failed','message':str(exc)})
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
