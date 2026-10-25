"""
Pruebas del ejercicio 4.  Correr desde ejercicio_4_html_base64:  python -m unittest -v

Cada prueba crea sus archivos en una carpeta temporal, asi no dependen de la
carpeta de ejemplos ni de tener internet.
"""

import base64
import contextlib
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path

from html_embedder import HtmlImageEmbedder
from html_embedder.__main__ import main as cli_main
from html_embedder.encoder import Base64ImageEncoder, detect_mime_type
from html_embedder.parser import ImgTagParser
from html_embedder.sources import ImageLoadError, ImageResolver, ImageSource, LocalFileSource

# png de 1x1
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)
PNG_DATA_URI = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()
GIF_BYTES = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\x00\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"


class FakeRemoteSource(ImageSource):
    """Hace de servidor web falso para no depender de internet."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def can_handle(self, src):
        return src.startswith("http")

    def load(self, src, base_dir):
        self.calls += 1
        if src not in self.responses:
            raise ImageLoadError(f"HTTP 404 al descargar {src}")
        return self.responses[src]


class TempSiteTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="")
        return path

    def embedder(self, **kwargs):
        # sin descargas reales por defecto
        kwargs.setdefault("resolver", ImageResolver([LocalFileSource()]))
        return HtmlImageEmbedder(**kwargs)


class ParserTest(unittest.TestCase):
    def test_ubica_etiquetas_con_posicion_exacta(self):
        html = '<p>hola</p>\n<img src="a.png">\n  <IMG\n alt="x"\n SRC=b.png />'
        tags = ImgTagParser().find_images(html)
        self.assertEqual([t.src for t in tags], ["a.png", "b.png"])
        for tag in tags:
            self.assertEqual(html[tag.start : tag.end], tag.raw)

    def test_ignora_comentarios_scripts_y_img_sin_src(self):
        html = (
            '<!-- <img src="comentada.png"> -->'
            "<script>var s = '<img src=\"script.png\">';</script>"
            '<img alt="sin src">'
            '<img src="real.png">'
        )
        self.assertEqual([t.src for t in ImgTagParser().find_images(html)], ["real.png"])

    def test_with_src_solo_cambia_src(self):
        html = "<img data-src='lazy.png' class=\"x\" src='a.png' alt=a>"
        tag = ImgTagParser().find_images(html)[0]
        self.assertEqual(tag.with_src("NUEVO"), "<img data-src='lazy.png' class=\"x\" src=\"NUEVO\" alt=a>")


class EncoderTest(unittest.TestCase):
    def test_detecta_tipo_por_contenido(self):
        self.assertEqual(detect_mime_type(PNG_BYTES, "foto.jpg"), "image/png")
        self.assertEqual(detect_mime_type(GIF_BYTES), "image/gif")
        self.assertEqual(detect_mime_type(b"<svg xmlns='...'></svg>"), "image/svg+xml")

    def test_rechaza_contenido_que_no_coincide_con_la_extension(self):
        with self.assertRaises(ImageLoadError):
            detect_mime_type(b"<html>error 404</html>", "logo.png")

    def test_rechaza_archivo_vacio(self):
        with self.assertRaises(ImageLoadError):
            Base64ImageEncoder().encode(b"", "a.png")

    def test_data_uri(self):
        self.assertEqual(Base64ImageEncoder().encode(PNG_BYTES, "a.png"), PNG_DATA_URI)


class EmbedderTest(TempSiteTestCase):
    def test_reemplaza_imagenes_y_no_modifica_el_original(self):
        self.write("img/a.png", PNG_BYTES)
        original = '<html><body>\n<img src="img/a.png" alt="A">\n</body></html>\n'
        html_path = self.write("index.html", original)

        report = self.embedder().process([self.root])

        self.assertEqual(html_path.read_text(encoding="utf-8"), original)
        output = (self.root / "index_base64.html").read_text(encoding="utf-8")
        self.assertEqual(output, f'<html><body>\n<img src="{PNG_DATA_URI}" alt="A">\n</body></html>\n')
        self.assertEqual(report.to_dict(), {"success": {html_path.as_posix(): ["img/a.png"]}, "fail": {}})

    def test_recorre_subdirectorios_y_resuelve_rutas_relativas(self):
        self.write("img/a.png", PNG_BYTES)
        self.write("blog/2024/post.html", '<img src="../../img/a.png">')
        self.write("blog/nota.txt", "no es html")

        report = self.embedder().process([self.root])

        self.assertEqual(report.total_success, 1)
        self.assertTrue((self.root / "blog/2024/post_base64.html").exists())

    def test_reporta_fallos_con_motivo(self):
        self.write("img/a.png", PNG_BYTES)
        self.write("img/falsa.png", b"texto")
        html_path = self.write("index.html", '<img src="img/a.png"><img src="img/no.png"><img src="img/falsa.png">')

        report = self.embedder().process([html_path])

        key = html_path.as_posix()
        self.assertEqual(report.success[key], ["img/a.png"])
        self.assertEqual(set(report.fail[key]), {"img/no.png", "img/falsa.png"})
        self.assertIn("no encontrado", report.fail[key]["img/no.png"])
        # la que fallo se queda con su src original
        output = (self.root / "index_base64.html").read_text(encoding="utf-8")
        self.assertIn('src="img/no.png"', output)

    def test_acepta_lista_mixta_de_archivos_y_directorios_sin_duplicar(self):
        self.write("img/a.png", PNG_BYTES)
        html_path = self.write("sitio/index.html", '<img src="../img/a.png">')

        report = self.embedder().process([html_path, self.root / "sitio", str(html_path)])

        self.assertEqual(list(report.success), [html_path.as_posix()])

    def test_no_reprocesa_archivos_generados(self):
        self.write("img/a.png", PNG_BYTES)
        self.write("index.html", '<img src="img/a.png">')

        self.embedder().process([self.root])
        report = self.embedder().process([self.root])

        self.assertEqual(len(report.outputs), 1)
        self.assertFalse((self.root / "index_base64_base64.html").exists())

    def test_salida_en_otro_directorio_replica_estructura(self):
        self.write("sitio/img/a.png", PNG_BYTES)
        self.write("sitio/blog/post.html", '<img src="../img/a.png">')
        salida = self.root / "salida"

        self.embedder(output_dir=salida).process([self.root / "sitio"])

        self.assertTrue((salida / "blog/post_base64.html").exists())

    def test_imagen_ya_embebida_y_query_string(self):
        self.write("img/a.png", PNG_BYTES)
        html = f'<img src="{PNG_DATA_URI}"><img src="img/a.png?v=3#x">'
        html_path = self.write("index.html", html)

        report = self.embedder().process([html_path])

        self.assertEqual(report.success[html_path.as_posix()], ["img/a.png?v=3#x"])
        self.assertEqual(report.fail, {})

    def test_imagen_remota_con_origen_inyectado_y_cache(self):
        remote = FakeRemoteSource({"https://cdn.test/a.png": PNG_BYTES})
        resolver = ImageResolver([LocalFileSource(), remote])
        html_path = self.write(
            "index.html",
            '<img src="https://cdn.test/a.png"><img src="https://cdn.test/a.png"><img src="https://cdn.test/b.png">',
        )

        report = HtmlImageEmbedder(resolver=resolver).process([html_path])

        key = html_path.as_posix()
        self.assertEqual(report.success[key], ["https://cdn.test/a.png"])
        self.assertIn("404", report.fail[key]["https://cdn.test/b.png"])
        self.assertEqual(remote.calls, 2)  # a.png se pidio una sola vez (cache)
        output = (self.root / "index_base64.html").read_text(encoding="utf-8")
        self.assertEqual(output.count(PNG_DATA_URI), 2)

    def test_conserva_codificacion_y_saltos_de_linea(self):
        self.write("a.gif", GIF_BYTES)
        html_path = self.root / "viejo.html"
        html_path.write_bytes('<p>Año</p>\r\n<img src="a.gif">\r\n'.encode("cp1252"))

        self.embedder().process([html_path])

        raw = (self.root / "viejo_base64.html").read_bytes()
        self.assertTrue(raw.startswith('<p>Año</p>\r\n'.encode("cp1252")))
        self.assertIn(b"data:image/gif;base64,", raw)

    def test_ruta_inexistente_no_detiene_el_proceso(self):
        self.write("index.html", "<p>sin imágenes</p>")
        report = self.embedder().process([self.root / "no_existe", self.root])
        self.assertEqual(len(report.outputs), 1)


class CliTest(TempSiteTestCase):
    def tearDown(self):
        # la CLI llama logging.basicConfig, se limpia para no ensuciar las otras pruebas
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        super().tearDown()

    def test_cli_genera_reporte_json(self):
        self.write("img/a.png", PNG_BYTES)
        self.write("index.html", '<img src="img/a.png"><img src="img/x.png">')
        reporte = self.root / "reporte.json"

        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
            code = cli_main([str(self.root), "--sin-remotas", "--reporte", str(reporte)])

        self.assertEqual(code, 0)
        data = json.loads(reporte.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"success", "fail"})


if __name__ == "__main__":
    unittest.main()
