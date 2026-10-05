"""Meeting-scoped human labels; native diarization numbers remain evidence."""
from copy import deepcopy
import uuid


class ParticipantRegistry:
    def __init__(self, meeting_id=None, state=None):
        state=deepcopy(state or {})
        self.meeting_id=state.get('meeting_id') or meeting_id or uuid.uuid4().hex
        self.participants=state.get('participants',{})
        self.bindings=state.get('bindings',{})

    @staticmethod
    def key(row):
        namespace=str(row.get('speaker_namespace') or row.get('audio_source') or 'legacy')
        return namespace+'|'+str(row.get('speaker'))

    def _create(self, source, name='', confirmed=False):
        pid='p-'+uuid.uuid4().hex[:12]
        self.participants[pid]={'name':str(name),'source':source,'confirmed':bool(confirmed)}
        return pid

    def decorate(self, row):
        result=dict(row)
        key=self.key(row)
        result['speaker_key']=key
        speaker=row.get('speaker')
        if speaker in (None,0,-1,-2,'0','-1','-2'):
            result.update(participant_id=None,participant_pending=False)
            return result
        source=row.get('audio_source','main')
        pid=self.bindings.get(key)
        if pid is None:
            name=f'麦克风发言人 {speaker}' if source=='mic' else f'发言人 {speaker}'
            pid=self._create(source,name,confirmed=False)
            self.bindings[key]=pid
        participant=self.participants[pid]
        name=participant['name'] or f'发言人 {speaker}'
        result.update(participant_id=pid,participant_name=name,speaker_name=name,
                      participant_pending=not participant.get('confirmed',False))
        return result

    def rename(self, pid, name):
        if pid not in self.participants: raise ValueError('请选择有效参会者')
        name=str(name).strip()
        if not name: raise ValueError('参会者名称不能为空')
        self.participants[pid]['name']=name
        self.participants[pid]['confirmed']=True

    def associate(self, key, pid):
        if key not in self.bindings or pid not in self.participants:
            raise ValueError('该声音尚未分配有效编号，或参会者不存在')
        self.bindings[key]=pid
        self.participants[pid]['confirmed']=True

    def merge(self, source_pid, target_pid):
        if source_pid not in self.participants or target_pid not in self.participants:
            raise ValueError('请选择有效参会者')
        for key,value in tuple(self.bindings.items()):
            if value==source_pid: self.bindings[key]=target_pid
        self.participants[target_pid]['confirmed']=True
        if source_pid!=target_pid: self.participants.pop(source_pid)

    def split(self, keys, name):
        keys=list(keys)
        if not str(name).strip(): raise ValueError('参会者名称不能为空')
        if not keys or any(key not in self.bindings for key in keys):
            raise ValueError('请选择声音分段')
        source=self.participants[self.bindings[keys[0]]].get('source','main')
        pid=self._create(source,str(name).strip(),confirmed=True)
        for key in keys: self.bindings[key]=pid
        return pid

    def to_dict(self):
        return deepcopy({'meeting_id':self.meeting_id,'participants':self.participants,'bindings':self.bindings})
