def row(namespace='system:g0:e0',speaker=1,source='system'):
    return {'id':namespace+':line','speaker':speaker,'speaker_namespace':namespace,
            'audio_source':source,'native':{'speaker':speaker,'text':'hello'}}


def test_equal_native_ids_across_sources_or_epochs_never_inherit_name():
    from app.participants import ParticipantRegistry
    registry=ParticipantRegistry('meeting')
    first=registry.decorate(row())
    registry.rename(first['participant_id'],'张工')
    same=registry.decorate(row())
    mic=registry.decorate(row('mic:g0:e0',source='mic'))
    reset=registry.decorate(row('system:g1:e0'))
    assert same['speaker_name']=='张工'
    assert first['participant_id']!=mic['participant_id']!=reset['participant_id']
    assert reset['speaker_name']!='张工' and reset['participant_pending']
    assert first['native']==row()['native']


def test_explicit_association_and_reopened_name_persist_without_changing_native_id():
    from app.participants import ParticipantRegistry
    registry=ParticipantRegistry('meeting')
    first=registry.decorate(row())
    second=registry.decorate(row('system:g1:e0'))
    registry.rename(first['participant_id'],'王工')
    registry.associate(second['speaker_key'],first['participant_id'])
    reopened=ParticipantRegistry(state=registry.to_dict())
    after=reopened.decorate(row('system:g1:e0'))
    assert after['participant_id']==first['participant_id']
    assert after['speaker_name']=='王工' and not after['participant_pending']
    assert after['native']['speaker']==1


def test_different_meeting_does_not_reuse_global_speaker_names():
    from app.participants import ParticipantRegistry
    one,two=ParticipantRegistry('one'),ParticipantRegistry('two')
    first=one.decorate(row())
    one.rename(first['participant_id'],'旧名字')
    assert two.decorate(row())['speaker_name']!='旧名字'


def test_unknown_speaker_cannot_be_bound_to_real_participant():
    from app.participants import ParticipantRegistry
    import pytest
    registry=ParticipantRegistry('meeting')
    unknown=registry.decorate(row(speaker=-1))
    assert unknown['participant_id'] is None
    with pytest.raises(ValueError): registry.associate(unknown['speaker_key'],'missing')
