"""Cancelable historical text translation; Qt and stored ASR stay separate."""
import asyncio
import threading
from PyQt6.QtCore import QObject,pyqtSignal
from app.session_postprocess import translate_row


class RecordRewriteJob(QObject):
    completed=pyqtSignal(list)
    failed=pyqtSignal(str)
    progress=pyqtSignal(int,int)
    cancelled=pyqtSignal(int,int)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.running=False
        self.cancel=threading.Event()
        self.completed_count=0
        self.total_count=0
    def start(self,rows,settings):
        if self.running: return
        self.running=True
        self.cancel.clear()
        rows=[dict(row) for row in rows]
        settings=dict(settings)
        self.completed_count=0
        self.total_count=len(rows)
        async def work():
            results=[]
            for row in rows:
                if self.cancel.is_set(): break
                if row.get('target_language'):
                    try: result=await translate_row(row,settings,self.cancel)
                    except Exception as exc:
                        if self.cancel.is_set(): break
                        result={'translation_stale':True,'translation_error':str(exc),'translation_pending':False}
                    results.append({**row,**result})
                else: results.append(row)
                self.completed_count+=1
                self.progress.emit(self.completed_count,len(rows))
            return results
        def run():
            try: results=asyncio.run(work())
            except Exception as exc:
                self.running=False
                self.failed.emit(str(exc))
            else:
                self.running=False
                if self.cancel.is_set():
                    self.cancelled.emit(self.completed_count,self.total_count)
                else:
                    self.completed.emit(results)
        threading.Thread(target=run,daemon=True,name='SavedMeetingTranslation').start()
