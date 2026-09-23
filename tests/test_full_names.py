import pytest
from sqlalchemy import create_engine, text, inspect
from app.extensions import db
from app.models import User, DSF
from app.services.auth_service import create_user


def test_existing_user_name_keeps_login_and_assignments(client, imported_session):
    user=create_user('ancien','motdepasse-test')
    dsf=DSF.query.first();dsf.assignee=user;db.session.commit()
    original_hash=user.password_hash
    response=client.post(f'/admin/users/{user.id}/full-name',data={'full_name':"  Élodie   N'Diaye  "})
    assert response.status_code==302
    db.session.expire_all()
    assert user.full_name=="Élodie N'Diaye"
    assert user.username=='ancien' and user.password_hash==original_hash
    assert dsf.assigned_to_id==user.id
    assert 'ancien' in client.get('/admin/').get_data(as_text=True)
    assert f'data-dsf-id="{dsf.id}"' in client.get('/admin/search?q=N%27Diaye').get_data(as_text=True)
    client.post('/auth/logout')
    assert client.post('/auth/login',data={'username':'ancien','password':'motdepasse-test'}).status_code==302
    html=client.get('/').get_data(as_text=True)
    assert 'Élodie' in html and 'ancien' in html
    assert original_hash not in html and 'motdepasse-test' not in html


def test_create_name_optional_clear_and_max_length(client):
    assert client.post('/admin/users',data={'username':'nouveau','password':'motdepasse-test','full_name':'Alice Martin'}).status_code==302
    user=User.query.filter_by(username='nouveau').one()
    assert user.display_name=='Alice Martin'
    client.post(f'/admin/users/{user.id}/full-name',data={'full_name':'x'*151})
    db.session.expire_all();assert user.full_name=='Alice Martin'
    client.post(f'/admin/users/{user.id}/full-name',data={'full_name':' '})
    db.session.expire_all();assert user.full_name is None and user.display_name=='nouveau'


def test_only_admin_with_csrf_can_change_name(app,client):
    user=create_user('controleurtest','motdepasse-test')
    url=f'/admin/users/{user.id}/full-name'
    assert client.get(url).status_code==405
    app.config['TESTING']=False
    assert client.post(url,data={'full_name':'Interdit'}).status_code==400
    with client.session_transaction() as session:session['user_id']=user.id;token=session['csrf_token']
    assert client.post(url,data={'full_name':'Interdit','csrf_token':token}).status_code==403
    db.session.expire_all();assert user.full_name is None


def test_legacy_upgrade_is_additive_and_idempotent():
    from types import SimpleNamespace
    from unittest.mock import patch
    from app.services.database_service import upgrade_legacy_schema
    engine=create_engine('sqlite:///:memory:')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT)'))
        c.execute(text("INSERT INTO users VALUES (1,'ancien','hash-existing')"))
    with patch('app.services.database_service.db',SimpleNamespace(engine=engine)):
        upgrade_legacy_schema();upgrade_legacy_schema()
    assert 'full_name' in {c['name'] for c in inspect(engine).get_columns('users')}
    with engine.connect() as c:
        assert c.execute(text('SELECT * FROM users')).one()==(1,'ancien','hash-existing',None)
    engine.dispose()
