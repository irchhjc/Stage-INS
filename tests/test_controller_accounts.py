from app.extensions import db
from app.models import DSF, User
from app.services.auth_service import create_user


def test_admin_updates_controller_credentials_without_losing_assignments(client, imported_session):
    controller = create_user(
        "ancien.compte",
        "ancien-mot-de-passe",
        full_name="Ancien Nom",
    )
    dsf = DSF.query.first()
    dsf.assigned_to_id = controller.id
    db.session.commit()
    controller_id = controller.id
    original_hash = controller.password_hash

    response = client.post(
        f"/admin/controllers/{controller.id}/account",
        data={
            "full_name": "  Nouveau   Nom  ",
            "username": "nouveau.compte",
            "new_password": "nouveau-mot-de-passe",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Le compte nouveau.compte a été mis à jour" in response.get_data(as_text=True)
    updated = db.session.get(User, controller_id)
    assert updated.full_name == "Nouveau Nom"
    assert updated.username == "nouveau.compte"
    assert updated.password_hash != original_hash
    assert updated.check_password("nouveau-mot-de-passe")
    assert DSF.query.first().assigned_to_id == controller_id

    client.post("/auth/logout")
    assert client.post(
        "/auth/login",
        data={"username": "ancien.compte", "password": "ancien-mot-de-passe"},
    ).status_code == 200
    assert client.post(
        "/auth/login",
        data={"username": "nouveau.compte", "password": "nouveau-mot-de-passe"},
    ).status_code == 302


def test_blank_password_keeps_existing_password(client):
    controller = create_user("controleur", "motdepasse-original", full_name="Nom Initial")
    original_hash = controller.password_hash

    client.post(
        f"/admin/controllers/{controller.id}/account",
        data={
            "full_name": "Nom Corrigé",
            "username": "controleur",
            "new_password": "",
        },
    )

    db.session.refresh(controller)
    assert controller.full_name == "Nom Corrigé"
    assert controller.password_hash == original_hash
    assert controller.check_password("motdepasse-original")


def test_invalid_controller_update_is_atomic(client):
    first = create_user("premier", "motdepasse-premier", full_name="Premier Nom")
    second = create_user("second", "motdepasse-second", full_name="Second Nom")
    original_hash = second.password_hash

    duplicate = client.post(
        f"/admin/controllers/{second.id}/account",
        data={
            "full_name": "Nom à ne pas enregistrer",
            "username": first.username,
            "new_password": "nouveau-mot-de-passe",
        },
        follow_redirects=True,
    )
    assert "existe déjà" in duplicate.get_data(as_text=True)
    db.session.refresh(second)
    assert second.username == "second"
    assert second.full_name == "Second Nom"
    assert second.password_hash == original_hash

    short = client.post(
        f"/admin/controllers/{second.id}/account",
        data={
            "full_name": "Toujours inchangé",
            "username": "second-modifie",
            "new_password": "court",
        },
        follow_redirects=True,
    )
    assert "au moins 10 caractères" in short.get_data(as_text=True)
    db.session.refresh(second)
    assert second.username == "second" and second.full_name == "Second Nom"


def test_controller_cannot_update_accounts(client, imported_session):
    controller = create_user("controleur", "motdepasse-controleur")
    client.post("/auth/logout")
    client.post(
        "/auth/login",
        data={"username": "controleur", "password": "motdepasse-controleur"},
    )

    response = client.post(
        f"/admin/controllers/{controller.id}/account",
        data={"username": "pirate", "full_name": "Interdit", "new_password": "motdepasse-pirate"},
    )

    assert response.status_code == 403
    db.session.refresh(controller)
    assert controller.username == "controleur"
