import threading

import pytest
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from app import create_app
from app.extensions import db
from conftest import build_test_workbook


@pytest.fixture()
def e2e_server(tmp_path):
    class E2EConfig:
        TESTING = False
        SECRET_KEY = "playwright-test-key"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'e2e.db').as_posix()}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        MAX_CONTENT_LENGTH = 5 * 1024 * 1024
        UPLOAD_FOLDER = tmp_path / "uploads"
        EXPORT_FOLDER = tmp_path / "exports"
        ALLOWED_EXTENSIONS = {"xlsx"}
        INITIAL_ADMIN_USERNAME = "irch"
        INITIAL_ADMIN_PASSWORD = "15081960irchdefluviaire"

    application = create_app(E2EConfig)
    server = make_server("127.0.0.1", 0, application)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", tmp_path
    finally:
        server.shutdown()
        thread.join(timeout=5)
        with application.app_context():
            db.session.remove()


def _login(page, base_url, username, password):
    page.goto(f"{base_url}/auth/login")
    page.get_by_label("Nom d'utilisateur").fill(username)
    page.get_by_label("Mot de passe").fill(password)
    page.get_by_role("button", name="Se connecter").click()
    expect(page).to_have_url(f"{base_url}/")


def test_admin_assignment_lock_and_controller_scope(e2e_server):
    base_url, tmp_path = e2e_server
    workbook_path = tmp_path / "playwright_dsf.xlsx"
    workbook_path.write_bytes(build_test_workbook().getvalue())

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        _login(page, base_url, "IRCH", "15081960irchdefluviaire")

        page.goto(f"{base_url}/import/")
        page.locator("input[type=file]").set_input_files(workbook_path)
        page.get_by_role("button", name="Analyser et importer").click()
        expect(page.get_by_text("Import terminé : 2 DSF")).to_be_visible()

        page.goto(f"{base_url}/admin/")
        page.get_by_label("Nom d'utilisateur").fill("controleur")
        page.get_by_label("Mot de passe").fill("motdepasse10")
        page.get_by_role("button", name="Créer le compte").click()
        expect(page.get_by_text("Le compte controleur a été créé.")).to_be_visible()

        assigned_row = page.locator("#adminDsfRows tr", has_text="DSF-001")
        unassigned_row = page.locator("#adminDsfRows tr", has_text="DSF-002")
        forbidden_href = unassigned_row.get_by_role("link", name="Voir").get_attribute("href")
        assigned_row.locator("select[name=user_id]").select_option(label="controleur")
        assigned_row.get_by_role("button", name="Affecter").click()

        assigned_row = page.locator("#adminDsfRows tr", has_text="DSF-001")
        expect(assigned_row.get_by_text("Affectée", exact=True)).to_be_visible()
        expect(assigned_row.get_by_text("Affectation verrouillée")).to_be_visible()
        expect(assigned_row.locator("select[name=user_id]")).to_have_count(0)

        page.get_by_role("button", name="Déconnexion").click()
        _login(page, base_url, "controleur", "motdepasse10")
        expect(page.get_by_role("link", name="Mes DSF")).to_be_visible()
        expect(page.get_by_text("DSF-001", exact=True)).to_be_visible()
        expect(page.get_by_text("DSF-002", exact=True)).to_have_count(0)

        forbidden_response = page.goto(f"{base_url}{forbidden_href}")
        assert forbidden_response.status == 403
        assert page.goto(f"{base_url}/admin/").status == 403
        browser.close()

