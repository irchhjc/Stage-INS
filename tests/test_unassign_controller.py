from datetime import datetime, timezone
import pytest
from app.extensions import db
from app.models import AuditLog, DSF, DSFValue, User, ImportSession


def setup_assignments():
    admin = User.query.filter_by(role="admin").first()
    controller = User(username="controleurtest", role="controller")
    controller.set_password("motdepasse-test")
    other = User(username="autrecontroleur", role="controller")
    other.set_password("motdepasse-test")
    db.session.add_all([controller, other])
    db.session.flush()
    rows = DSF.query.order_by(DSF.id).all()
    for row in rows:
        row.assignee = controller
        row.assigned_by = admin
        row.assigned_at = datetime.now(timezone.utc)
    rows[1].status = "in_progress"
    extra = ImportSession(filename="second.xlsx", filepath="test", sheet_name="DONNEES")
    db.session.add(extra)
    db.session.flush()
    pending = DSF(import_session_id=extra.id,row_index=2,assignee=controller,assigned_by=admin,assigned_at=datetime.now(timezone.utc),status="not_started")
    done = DSF(import_session_id=extra.id,row_index=3,assignee=controller,status="completed")
    untouched = DSF(import_session_id=extra.id,row_index=4,assignee=other,status="not_started")
    db.session.add_all([pending, done, untouched]); db.session.commit()
    return controller, other, rows[0], rows[1], pending, done, untouched


def test_bulk_unassign_preserves_data_and_other_work(client, imported_session):
    ctrl, other, first, started, pending, done, untouched = setup_assignments()
    ids = [first.id,pending.id]
    original_values = [(v.id,v.current_value) for v in DSFValue.query.order_by(DSFValue.id)]
    url=f"/admin/controllers/{ctrl.id}/unassign-not-started"
    page=client.get('/admin/').get_data(as_text=True)
    assert url in page
    assert 'Retirer les non commencées (2)' in page
    assert client.post(url).status_code == 302
    db.session.expire_all()
    for id in ids:
        row=db.session.get(DSF,id)
        assert row.assigned_to_id is None
        assert row.assigned_by_id is None
        assert row.assigned_at is None
        assert row.status == 'not_started'
    assert started.assigned_to_id == ctrl.id
    assert done.assigned_to_id == ctrl.id
    assert untouched.assigned_to_id == other.id
    assert DSF.query.count() == 5
    assert [(v.id,v.current_value) for v in DSFValue.query.order_by(DSFValue.id)] == original_values
    logs=AuditLog.query.filter_by(action='retrait affectation DSF non commencée').all()
    assert {log.dsf_id for log in logs} == set(ids)
    assert all(log.old_value == ctrl.username and log.operator == 'irch' for log in logs)
    assert client.post(url).status_code == 302
    assert AuditLog.query.filter_by(action='retrait affectation DSF non commencée').count() == 2
    assert client.post(f'/admin/dsfs/{first.id}/assign',data={'user_id':other.id}).status_code == 302
    db.session.expire_all()
    assert first.assigned_to_id == other.id


def test_rejects_controller_and_get(client, imported_session):
    ctrl, *_ = setup_assignments()
    url=f'/admin/controllers/{ctrl.id}/unassign-not-started'
    assert client.get(url).status_code == 405
    with client.session_transaction() as session: session['user_id']=ctrl.id
    assert client.post(url).status_code == 403
    assert DSF.query.filter_by(assigned_to_id=ctrl.id).count() == 4


def test_rechecks_status_and_requires_csrf(app, client, imported_session):
    ctrl, _, first, *_ = setup_assignments()
    url=f'/admin/controllers/{ctrl.id}/unassign-not-started'
    app.config['TESTING']=False
    assert client.post(url).status_code == 400
    first.status='in_progress';db.session.commit()
    with client.session_transaction() as session: token=session['csrf_token']
    assert client.post(url,data={'csrf_token':token}).status_code == 302
    db.session.expire_all()
    assert first.assigned_to_id == ctrl.id


def test_rolls_back_when_audit_commit_fails(client, imported_session, monkeypatch):
    ctrl, *_=setup_assignments()
    def fail(): raise RuntimeError('commit failed')
    monkeypatch.setattr(db.session,'commit',fail)
    with pytest.raises(RuntimeError):
        client.post(f'/admin/controllers/{ctrl.id}/unassign-not-started')
    assert DSF.query.filter_by(assigned_to_id=ctrl.id).count() == 4
    assert AuditLog.query.filter_by(action='retrait affectation DSF non commencée').count() == 0
