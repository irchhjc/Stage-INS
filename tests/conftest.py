import io

import pytest
from openpyxl import Workbook

from app import create_app
from app.config.fiche_mapping import FICHE_DEFINITIONS
from app.extensions import db


def build_test_workbook():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "DONNEES"
    headers = [
        "NUMERO DE LA DSF",
        "NUMERO DSF_T",
        "NIU",
        "Cle",
        "Raison sociale",
        "Sigle usuel",
        "Ville",
        "Ville",
        "Année",
        "IMMOBILISATIONS INCORPORELLES (BRUT)",
        "IMMOBILISATIONS INCORPORELLES (AMORT/DEPREC)",
        "IMMOBILISATIONS INCORPORELLES (NET_N)",
        "IMMOBILISATIONS INCORPORELLES (NET_N-1)",
        "TOTAL GENERAL (NET_N)",
        "Capital NET (N)",
        "TOTAL GENERAL PASSIF(N)",
        "TA Ventes de marchandises(N)",
        "XI RESULTAT NET(N)",
    ]
    for definition in FICHE_DEFINITIONS[4:-1]:
        headers.append(definition["start"])
        headers.append(f"Variable test {definition['code']}(N)")
    headers.append(FICHE_DEFINITIONS[-1]["start"])
    headers.extend(["Date de sasie", "Heure de fin de la saisie"])
    worksheet.append(headers)

    def row(numero, niu, name, gross, depreciation, net):
        values = [numero, "T-1", niu, "A", name, name[:3], "Douala", "Littoral", 2025]
        values += [gross, depreciation, net, net - 10, net]
        values += [100, net, 200, 10]
        values += [None] * (len(headers) - len(values))
        return values

    worksheet.append(row("DSF-001", "M001", "ALPHA SARL", 100, 20, 80))
    worksheet.append(row("DSF-002", "M001", "ALPHA SARL", 150, 50, 100))
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


@pytest.fixture()
def app(tmp_path):
    class LocalTestConfig:
        TESTING = True
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        MAX_CONTENT_LENGTH = 5 * 1024 * 1024
        UPLOAD_FOLDER = tmp_path / "uploads"
        EXPORT_FOLDER = tmp_path / "exports"
        ALLOWED_EXTENSIONS = {"xlsx"}
        INITIAL_ADMIN_USERNAME = "irch"
        INITIAL_ADMIN_PASSWORD = "15081960irchdefluviaire"

    application = create_app(LocalTestConfig)
    with application.app_context():
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    test_client = app.test_client()
    response = test_client.post(
        "/auth/login",
        data={"username": "irch", "password": "15081960irchdefluviaire"},
    )
    assert response.status_code == 302
    return test_client


@pytest.fixture()
def imported_session(client):
    response = client.post(
        "/import/",
        data={"file": (build_test_workbook(), "test_dsf.xlsx")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302
    from app.models import ImportSession

    return ImportSession.query.one()
