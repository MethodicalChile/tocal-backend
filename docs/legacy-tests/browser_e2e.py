"""Recorrido de navegador; ejecutar con config.browser_settings."""

import io
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright


class BrowserJourney(StaticLiveServerTestCase):
    def test_week_report_pdf_and_sales(self):
        with (
            tempfile.TemporaryDirectory(prefix="tocal-browser-") as directory,
            override_settings(MEDIA_ROOT=Path(directory)),
        ):
            call_command("seed_demo", stdout=io.StringIO())
            qa = settings.BASE_DIR / ".qa"
            qa.mkdir(exist_ok=True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "response",
                    lambda response: (
                        errors.append(f"HTTP {response.status}: {response.url}")
                        if response.status >= 400
                        else None
                    ),
                )
                page.goto(self.live_server_url + "/login")
                page.locator("#email").fill("cmunoz@tocal.cl")
                page.locator("#password").fill("tocal2026")
                page.get_by_role("button", name="Ingresar").click()
                page.wait_for_url(self.live_server_url + "/")
                page.screenshot(path=str(qa / "django-dashboard.png"), full_page=True)
                page.get_by_role("link", name="EDS ARAMCO ANGOL", exact=True).first.click()
                base = page.url
                page.get_by_role("link", name="Prevención", exact=True).click()
                page.get_by_role("button", name="Nueva semana", exact=True).click()
                page.wait_for_url("**?semana=*")
                page.locator("#id_personal_operativo").fill("12")
                page.locator("#id_personal_adm").fill("4")
                page.locator("#id_hh_operativas").fill("504")
                page.locator("#id_hh_adm").fill("168")
                page.get_by_role("button", name="Guardar semana", exact=True).click()
                expect(
                    page.get_by_role("status").get_by_text("Guardado", exact=True)
                ).to_be_visible()
                page.get_by_role("link", name="Informes", exact=True).click()
                page.get_by_role("button", name="Nuevo informe", exact=True).click()
                report = page.url
                page.locator("#id_comentarios").fill(
                    "Se completa la migración a Django.\n! Se verifica el informe semanal.\n  - Revisión de fotografías."
                )
                page.get_by_role("button", name="Guardar borrador", exact=True).click()
                cutoff = page.locator("#id_fecha_corte").input_value()
                page.get_by_role("link", name="Subir fotos", exact=True).click()
                page.wait_for_load_state("networkidle")
                page.locator("summary").click()
                page.locator("#photos").set_input_files(
                    [
                        str(settings.BASE_DIR / "seed-assets/obra-01.jpg"),
                        str(settings.BASE_DIR / "seed-assets/obra-02.jpg"),
                    ]
                )
                page.locator("#id_fecha").fill(cutoff)
                page.get_by_role("button", name="Subir fotografías", exact=True).click()
                expect(page.get_by_text("2 fotos subidas", exact=True)).to_be_visible()
                page.goto(report)
                page.get_by_role("button", name="Emitir informe (PDF)", exact=True).click()
                expect(page.get_by_text("Informe emitido: PDF generado", exact=True)).to_be_visible(
                    timeout=30000
                )
                href = page.get_by_role("link", name="Descargar PDF", exact=True).get_attribute(
                    "href"
                )
                response = page.request.get(self.live_server_url + href)
                self.assertEqual(response.status, 200)
                self.assertTrue(response.body().startswith(b"%PDF"))
                (qa / "django-informe.pdf").write_bytes(response.body())
                page.goto(base + "/avance")
                page.screenshot(path=str(qa / "django-avance.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.goto(base)
                page.screenshot(path=str(qa / "django-mobile.png"), full_page=True)
                self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
                page.get_by_role("button", name="Cerrar sesión").click()
                page.locator("#email").fill("gerencia@tocal.cl")
                page.locator("#password").fill("tocal2026")
                page.get_by_role("button", name="Ingresar").click()
                page.wait_for_url(self.live_server_url + "/")
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.get_by_role("link", name="Ventas", exact=True).click()
                page.screenshot(path=str(qa / "django-ventas.png"), full_page=True)
                page.get_by_role("link", name="Libro de ventas", exact=True).click()
                page.get_by_role("link", name="Registrar documento", exact=True).click()
                page.locator("#id_numero").fill("987654")
                page.locator("#id_fecha").fill("2026-03-05")
                page.locator("#id_rut_cliente").fill("78027446-8")
                page.locator("#id_rut_cliente").blur()
                expect(page.locator("#id_razon_social")).to_have_value("EDS ANGOL SPA")
                page.locator("#id_afecto").fill("10000000")
                page.locator("#id_uf_dia").fill("39800")
                page.get_by_role("button", name="Guardar", exact=True).click()
                page.wait_for_url("**/ventas/documentos")
                expect(page.get_by_text("Documento guardado", exact=True)).to_be_visible()
                expect(page.get_by_text("N° 987654", exact=True)).to_be_visible()
                self.assertEqual(errors, [])
                browser.close()
