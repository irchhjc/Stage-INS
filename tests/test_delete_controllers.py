from app.extensions import db
from app.models import AuditLog, DSF, User
from app.services.auth_service import create_user


CONFIRMATION = "DELETE_ALL_CONTROLLERS"


def _prepare_controllers():
    first = create_user("controleur.un", "motdepasse-premier")
    second = create_user("controleur.deux", "motdepasse-second")
    inactive = create_user("controleur.inactif", "motdepasse-inactif")
    inactive.is_active = False
    dsfs = DSF.query.order_by(DSF.id).all()
    dsfs[0].assigned_to_id = first.id
    dsfs[0].assigned_by_id = first.id
    dsfs[0].status = "in_progress"
    dsfs[1].assigned_to_id = second.id
    dsfs[1].assigned_by_id = first.id
    dsfs[1].status = "completed"
    db.session.commit()
    return first, second, inactive, dsfs


def test_delete_all_controllers_preserves_dsfs_and_audit_history(client, imported_session):
    first, second, inactive, dsfs = _prepare_controllers()
    controller_ids = {first.id, second.id, inactive.id}
    dsf_ids = [dsf.id for dsf in dsfs]

    response = client.post(
        "/admin/controllers/delete-all",
        data={"confirmation": CONFIRMATION},
        follow_redirects=True,
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "3 compte(s) contrôleur supprimé(s)" in html
    assert "2 affectation(s) retirée(s)" in html
    assert User.query.filter(User.id.in_(controller_ids)).count() == 0
    assert User.query.filter_by(role="admin").count() == 1
    preserved = DSF.query.order_by(DSF.id).all()
    assert [dsf.id for dsf in preserved] == dsf_ids
    assert [dsf.status for dsf in preserved] == ["in_progress", "completed"]
    assert all(dsf.assigned_to_id is None and dsf.assigned_by_id is None for dsf in preserved)
    logs = AuditLog.query.filter_by(action="suppression globale des contrôleurs").all()
    assert len(logs) == 2
    assert {log.old_value for log in logs} == {"controleur.un", "controleur.deux"}


def test_delete_all_controllers_requires_server_side_confirmation(client, imported_session):
    first, second, inactive, dsfs = _prepare_controllers()

    response = client.post(
        "/admin/controllers/delete-all",
        data={"confirmation": "WRONG"},
        follow_redirects=True,
    )

    assert "Confirmation invalide" in response.get_data(as_text=True)
    assert User.query.filter_by(role="controller").count() == 3
    assert DSF.query.filter(DSF.assigned_to_id.is_not(None)).count() == 2


def test_controller_cannot_delete_accounts(client, imported_session):
    controller = create_user("controleur", "motdepasse-controleur")
    client.post("/auth/logout")
    client.post(
        "/auth/login",
        data={"username": controller.username, "password": "motdepasse-controleur"},
    )

    response = client.post(
        "/admin/controllers/delete-all",
        data={"confirmation": CONFIRMATION},
    )

    assert response.status_code == 403
    assert User.query.filter_by(role="controller").count() == 1
