from app.extensions import db
from app.models import AuditLog, DSF, User


def _controller(username, full_name):
    user = User(username=username, full_name=full_name, role="controller")
    user.set_password("motdepasse-test")
    db.session.add(user)
    return user


def _login(client, username):
    client.post("/auth/logout")
    response = client.post(
        "/auth/login",
        data={"username": username, "password": "motdepasse-test"},
    )
    assert response.status_code == 302


def test_all_dsfs_are_shared_but_only_owner_can_work_on_claimed_dsf(client, imported_session):
    first_controller = _controller("controleur.un", "Contrôleur Un")
    second_controller = _controller("controleur.deux", "Contrôleur Deux")
    db.session.commit()
    first, second = DSF.query.order_by(DSF.id).all()

    _login(client, first_controller.username)
    dashboard = client.get("/").get_data(as_text=True)
    assert first.numero_dsf in dashboard and second.numero_dsf in dashboard
    all_dsfs = client.get("/dsfs").get_data(as_text=True)
    assert first.numero_dsf in all_dsfs
    assert second.numero_dsf in all_dsfs
    assert all_dsfs.count("Prendre en charge") == 2
    assert client.get(f"/dsf/{first.id}").status_code == 403
    assert first.numero_dsf not in client.get("/my-dsfs").get_data(as_text=True)

    claimed = client.post(f"/dsfs/{first.id}/claim", follow_redirects=False)
    assert claimed.status_code == 302
    assert claimed.headers["Location"].endswith(f"/dsf/{first.id}")
    db.session.refresh(first)
    assert first.assigned_to_id == first_controller.id
    assert first.assigned_by_id == first_controller.id
    assert AuditLog.query.filter_by(dsf_id=first.id, action="prise en charge DSF").count() == 1
    assert client.get(f"/dsf/{first.id}").status_code == 200

    # Une DSF simplement réservée n'entre dans « Mes DSF » qu'après le début du travail.
    assert first.numero_dsf not in client.get("/my-dsfs").get_data(as_text=True)
    first.status = "in_progress"
    db.session.commit()
    mine = client.get("/my-dsfs").get_data(as_text=True)
    assert first.numero_dsf in mine
    assert second.numero_dsf not in mine

    first.status = "completed"
    db.session.commit()
    assert first.numero_dsf in client.get("/my-dsfs?status=completed").get_data(as_text=True)

    _login(client, second_controller.username)
    shared = client.get("/dsfs").get_data(as_text=True)
    assert first.numero_dsf in shared and second.numero_dsf in shared
    assert "Utilisée par Contrôleur Un" in shared
    denied_claim = client.post(f"/dsfs/{first.id}/claim", follow_redirects=True)
    assert "prise en charge par un autre contrôleur" in denied_claim.get_data(as_text=True)
    db.session.refresh(first)
    assert first.assigned_to_id == first_controller.id
    assert client.get(f"/dsf/{first.id}").status_code == 403


def test_admin_cannot_claim_and_is_redirected_to_dsf(client, imported_session):
    dsf = DSF.query.first()

    response = client.post(f"/dsfs/{dsf.id}/claim", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/dsf/{dsf.id}")
    db.session.refresh(dsf)
    assert dsf.assigned_to_id is None
