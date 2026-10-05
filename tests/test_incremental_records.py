import json
from app.records import Journal, read_record, CaptionStore


def test_incremental_journal_keeps_all_rows_in_database(tmp_path):
    journal=Journal(tmp_path,{'long_meeting_mode':True,'save_records':True})
    for i in range(250):
        journal.save_changes([{'id':str(i),'start':i,'source':str(i)}])
    journal.save_changes([],extra={'status':'interrupted'})
    journal.close()
    doc=read_record(journal.path)
    assert len(doc['rows'])==250 and doc['storage']['type']=='sqlite'
    assert len(json.loads(journal.path.read_text(encoding='utf-8'))['rows'])<=200


def test_history_rename_is_written_without_changing_native_speaker(tmp_path):
    from app.records import update_record
    journal=Journal(tmp_path,{'save_records':True})
    rows=[{'id':'1','start':0,'source':'hello','speaker':1,'speaker_name':'旧名','native':{'speaker':1}}]
    journal.save(rows)
    rows[0]['speaker_name']='新名'
    update_record(journal.path,rows=rows,participant_state={'meeting_id':'m'})
    doc=read_record(journal.path)
    assert doc['rows'][0]['speaker_name']=='新名' and doc['rows'][0]['native']['speaker']==1


def test_retention_prunes_same_start_silence_without_changing_speech_identity():
    store=CaptionStore()
    store.ingest_snapshot({'type':'snapshot','lines':[{'text':'','speaker':-2,'start':0,'end':.1},
        {'text':'word','speaker':1,'start':0,'end':1}]})
    original=store.rows()[0]['id']
    store.ingest_snapshot({'type':'diff','lines_pruned':1,'n_lines':1,'new_lines':[]})
    assert [r['id'] for r in store.rows()]==[original]


def test_updated_word_evidence_is_detected_even_with_equal_display_text():
    store=CaptionStore()
    line={'text':'hello','start':0,'end':1,'speaker':1}
    store.ingest_snapshot({'lines':[line]})
    changed=store.ingest_snapshot({'lines':[{**line,'tokens':[{'text':'hello','start':.1,'end':.9}]}]})
    assert len(changed)==1 and changed[0]['native']['tokens'][0]['start']==.1


def test_repair_before_deliberate_edit_keeps_broken_manifest_bytes(tmp_path):
    from app.records import update_record
    journal=Journal(tmp_path,{'long_meeting_mode':True})
    journal.save_changes([{'id':'1','start':0,'source':'confirmed'}])
    journal.close()
    journal.path.write_bytes(b'{broken')
    update_record(journal.path,participant_state={'meeting_id':'m'})
    backups=list(tmp_path.glob('*.corrupt-*.bak'))
    assert len(backups)==1 and backups[0].read_bytes()==b'{broken'
    assert read_record(journal.path)['rows'][0]['source']=='confirmed'
