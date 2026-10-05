import json
from pathlib import Path


def test_transactional_rows_reopen_and_header_contains_only_preview(tmp_path):
    from app.meeting_store import MeetingStore, load_meeting
    path=tmp_path/'meeting.json'
    store=MeetingStore(path,{'meeting_id':'test','settings':{'save_records':True}})
    rows=[{'id':str(i),'start':i,'end':i+1,'source':str(i),'native':{'text':str(i)}} for i in range(450)]
    store.upsert(rows)
    store.checkpoint({'status':'active','participants':{'p1':{'name':'甲'}}})
    store.close()
    manifest=json.loads(path.read_text(encoding='utf-8'))
    assert manifest['row_count']==450 and len(manifest['rows'])<=200
    loaded=load_meeting(path)
    assert loaded['rows']==rows and loaded['participants']['p1']['name']=='甲'


def test_corrupt_manifest_does_not_destroy_committed_sqlite_rows(tmp_path):
    from app.meeting_store import MeetingStore, load_meeting
    path=tmp_path/'meeting.json'
    store=MeetingStore(path,{'meeting_id':'test'})
    store.upsert([{'id':'1','start':0,'source':'已确认','native':{'text':'已确认'}}])
    store.checkpoint({'status':'active'})
    store.close()
    path.write_text('{broken',encoding='utf-8')
    loaded=load_meeting(path)
    assert loaded['rows'][0]['source']=='已确认'
    assert loaded['recovered'] is True and path.read_text(encoding='utf-8')=='{broken'


def test_recovery_rejects_external_database_reference(tmp_path):
    import pytest
    from app.meeting_store import load_meeting
    path=tmp_path/'bad.json'
    path.write_text(json.dumps({'storage':{'type':'sqlite','file':'../outside.sqlite3'}}))
    with pytest.raises(ValueError): load_meeting(path)


def test_rows_revisions_and_removals_are_not_duplicated(tmp_path):
    from app.meeting_store import MeetingStore, load_meeting
    path=tmp_path/'meeting.json'
    store=MeetingStore(path,{})
    store.upsert([{'id':'1','start':0,'source':'first'},{'id':'2','start':1,'source':'second'}])
    store.upsert([{'id':'1','start':0,'source':'corrected'}],removed=['2'])
    store.checkpoint({'status':'interrupted'})
    store.close()
    assert load_meeting(path)['rows']==[{'id':'1','start':0,'source':'corrected'}]


def test_corrupt_row_is_isolated_and_original_database_is_preserved(tmp_path):
    from app.meeting_store import MeetingStore,load_meeting
    path=tmp_path/'meeting.json'
    store=MeetingStore(path,{})
    store.upsert([{'id':'1','start':0,'source':'valid'},{'id':'2','start':1,'source':'will break'}])
    store.checkpoint({'status':'interrupted'})
    with store.connection: store.connection.execute("UPDATE rows SET payload='{broken' WHERE id='2'")
    loaded=load_meeting(path)
    assert [row['id'] for row in loaded['rows']]==['1']
    assert loaded['recovery_warnings']['corrupted_row_ids']==['2']
    assert store.connection.execute("SELECT payload FROM rows WHERE id='2'").fetchone()[0]=='{broken'
    store.upsert([{'id':'3','start':2,'source':'after recovery'}])
    store.checkpoint({'status':'active'})
    assert [row['id'] for row in load_meeting(path)['rows']]==['1','3']
    assert store.connection.execute("SELECT payload FROM rows WHERE id='2'").fetchone()[0]=='{broken'
    store.close()
