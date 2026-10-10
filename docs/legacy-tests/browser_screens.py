import io
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import override_settings
from playwright.sync_api import sync_playwright

from intranet import models as m

VIEWPORTS = {"desktop": (1440, 1000), "mobile": (390, 844)}
SCROLL_THROUGH = """async () => {
  for (let y = 0; y < document.documentElement.scrollHeight; y += innerHeight / 2) {
    window.scrollTo(0, y);
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  window.scrollTo(0, 0);
}"""
PENDING_CHARTS = """[...document.querySelectorAll('[data-chart]')]
  .filter(el => !el.closest('[hidden]') && !el.querySelector('canvas, .chart-empty'))
  .map(el => el.id)"""


class Screens(StaticLiveServerTestCase):
    def test_capture_all_screens(self):
        out = Path(os.environ.get("QA_DIR", settings.BASE_DIR / ".qa" / "rediseno" / "actual"))
        out.mkdir(parents=True, exist_ok=True)
        with (
            tempfile.TemporaryDirectory(prefix="tocal-screens-") as directory,
            override_settings(MEDIA_ROOT=Path(directory), DEBUG=True),
        ):
            call_command("seed_demo", stdout=io.StringIO())
            obra = m.Obra.objects.first()
            report = m.Informe.objects.first()
            base = f"/obras/{obra.pk}"
            pages = {
                "dashboard": "/",
                "obra": base,
                "pdr": f"{base}/pdr",
                "pdr-checklist": f"{base}/pdr?tab=checklist",
                "pdr-historico": f"{base}/pdr?tab=historico",
                "avance": f"{base}/avance",
                "avance-actividades": f"{base}/avance?curva=actividades",
                "edp": f"{base}/edp",
                "adicionales": f"{base}/adicionales",
                "rdi": f"{base}/rdi",
                "rdi-registro": f"{base}/rdi/{m.Rdi.objects.filter(obra=obra).first().pk}",
                "fotos": f"{base}/fotos",
                "informes": f"{base}/informes",
                "informe": f"{base}/informes/{report.pk}",
                "ventas": "/ventas",
                "ventas-libro": "/ventas/documentos",
                "ventas-documento": "/ventas/documentos/nuevo",
                "ventas-importar": "/ventas/importar",
                "ui": "/_ui",
            }
            errors = []
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                for name, (width, height) in VIEWPORTS.items():
                    # Desactiva las animaciones para capturar el estado final de los gráficos.
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        reduced_motion="reduce",
                        locale="es-CL",
                        timezone_id="America/Santiago",
                    )
                    page.on("pageerror", lambda error: errors.append(f"JS {page.url}: {error}"))
                    page.on(
                        "response",
                        lambda response: (
                            errors.append(f"HTTP {response.status}: {response.url}")
                            if response.status >= 400
                            else None
                        ),
                    )
                    page.goto(self.live_server_url + "/login")
                    page.screenshot(path=str(out / f"login-{name}.png"), full_page=True)
                    page.locator("#email").fill("gerencia@tocal.cl")
                    page.locator("#password").fill("tocal2026")
                    page.get_by_role("button", name="Ingresar").click()
                    page.wait_for_url(self.live_server_url + "/")
                    for slug, path in pages.items():
                        page.goto(self.live_server_url + path)
                        page.wait_for_load_state("networkidle")
                        # Recorre la página para cargar los gráficos antes de capturarla.
                        page.evaluate(SCROLL_THROUGH)
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(400)
                        # Abre cada pestaña para cargar sus gráficos.
                        pending = page.evaluate(PENDING_CHARTS)
                        if pending:
                            errors.append(f"Gráficos sin dibujar en {path}: {pending}")
                        page.screenshot(path=str(out / f"{slug}-{name}.png"), full_page=True)
                        tabs = page.locator("[data-curve-tab], [data-tabs] [role=tab]")
                        for index in range(tabs.count()):
                            tabs.nth(index).click()
                            page.evaluate(SCROLL_THROUGH)
                            page.wait_for_timeout(300)
                            pending = page.evaluate(PENDING_CHARTS)
                            if pending:
                                errors.append(
                                    f"Pestaña {index + 1} sin dibujar en {path}: {pending}"
                                )
                        if tabs.count():
                            tabs.first.click()
                        if name == "mobile":
                            overflow = page.evaluate(
                                "document.documentElement.scrollWidth - innerWidth"
                            )
                            if overflow > 0:
                                errors.append(f"Scroll horizontal {overflow}px en {path}")
                    page.close()
                browser.close()
            self.assertEqual(errors, [])
