from app.settings import DEFAULTS


def test_desktop_translation_honors_environment_auth_and_validates_json(monkeypatch):
    from app.server import build_app
    from fastapi.testclient import TestClient
    monkeypatch.setenv('WLK_API_TOKEN','synthetic-auth-token')
    app,_=build_app({**DEFAULTS,'asr_model':'small','wlk':{'api_token':None}},management=False)
    # Do not enter lifespan: this tests HTTP auth/validation without loading a model.
    client=TestClient(app)
    try:
        assert client.post('/desktop/translate',json={}).status_code==401
        headers={'Authorization':'Bearer synthetic-auth-token'}
        assert client.post('/desktop/translate',json={},headers=headers).status_code==400
        assert client.post('/desktop/translate',json=[],headers=headers).status_code==400
        assert client.post('/desktop/translate',content='broken',headers=headers).status_code==400
    finally: client.close()
