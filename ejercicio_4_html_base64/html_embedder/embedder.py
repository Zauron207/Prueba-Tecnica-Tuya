"""El proceso completo: recorre los HTML, mete las imagenes y escribe el archivo nuevo."""

import logging
from pathlib import Path

from .collector import HtmlFile, HtmlFileCollector
from .encoder import Base64ImageEncoder
from .parser import ImgTagParser
from .report import ProcessingReport
from .sources import HttpSource, ImageLoadError, ImageResolver, LocalFileSource

logger = logging.getLogger(__name__)

DEFAULT_SUFFIX = "_base64"
FILE_LEVEL_KEY = "__archivo__"  # clave en fail cuando lo que falla es el HTML entero


class HtmlImageEmbedder:
    """Clase principal, coordina las demas.

    El resolver y el encoder se pueden pasar por constructor. Asi se puede
    apagar la descarga de imagenes remotas, o en las pruebas meter uno falso
    sin tener que tocar esta clase.
    """

    def __init__(
        self,
        resolver: ImageResolver | None = None,
        encoder: Base64ImageEncoder | None = None,
        output_dir: str | Path | None = None,
        suffix: str = DEFAULT_SUFFIX,
    ):
        self._resolver = resolver or ImageResolver([LocalFileSource(), HttpSource()])
        self._encoder = encoder or Base64ImageEncoder()
        self._output_dir = Path(output_dir) if output_dir else None
        self._suffix = suffix
        self._collector = HtmlFileCollector(output_suffix=suffix)

    def process(self, inputs) -> ProcessingReport:
        """Procesa una lista de archivos HTML y/o carpetas."""
        if isinstance(inputs, (str, Path)):
            inputs = [inputs]

        report = ProcessingReport()
        cache: dict[tuple[Path, str], str | ImageLoadError] = {}
        used_outputs: set[Path] = set()

        for html_file in self._collector.collect(inputs):
            self._process_file(html_file, report, cache, used_outputs)

        logger.info(
            "Proceso terminado: %d imágenes convertidas, %d fallidas",
            report.total_success,
            report.total_fail,
        )
        return report

    def _process_file(self, html_file: HtmlFile, report, cache, used_outputs) -> None:
        key = html_file.path.as_posix()
        try:
            html, encoding = self._read_html(html_file.path)
        except (OSError, UnicodeDecodeError) as exc:
            report.add_fail(key, FILE_LEVEL_KEY, f"No se pudo leer el archivo: {exc}")
            return

        base_dir = html_file.path.parent
        replacements = []
        for tag in ImgTagParser().find_images(html):
            if tag.src.lower().startswith("data:"):
                logger.debug("%s: imagen ya embebida, se deja igual", key)
                continue

            result = self._encode_cached(tag.src, base_dir, cache)
            if isinstance(result, ImageLoadError):
                report.add_fail(key, tag.src, str(result))
                continue
            report.add_success(key, tag.src)
            replacements.append((tag, result))

        new_html = self._apply_replacements(html, replacements)
        output_path = self._output_path(html_file, used_outputs)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(new_html, encoding=encoding, newline="")
        except OSError as exc:
            report.add_fail(key, FILE_LEVEL_KEY, f"No se pudo escribir {output_path}: {exc}")
            return
        report.add_output(key, output_path.as_posix())
        logger.info("%s -> %s", key, output_path)

    @staticmethod
    def _apply_replacements(html: str, replacements) -> str:
        # voy pegando: texto original hasta la etiqueta + etiqueta nueva + ...
        # Lo junto al final con join porque las imagenes en base64 pueden pesar
        # varios MB y concatenar strings en el ciclo es lento.
        parts, cursor = [], 0
        for tag, data_uri in replacements:
            parts.append(html[cursor : tag.start])
            parts.append(tag.with_src(data_uri))
            cursor = tag.end
        parts.append(html[cursor:])
        return "".join(parts)

    def _encode_cached(self, src, base_dir, cache):
        # cache por corrida, guarda tambien los errores: si la misma imagen sale
        # en varios lados se lee una vez, y una URL caida no se espera N veces
        cache_key = (base_dir.resolve(), src)
        if cache_key not in cache:
            try:
                data = self._resolver.load(src, base_dir)
                cache[cache_key] = self._encoder.encode(data, src)
            except ImageLoadError as exc:
                cache[cache_key] = exc
        return cache[cache_key]

    def _output_path(self, html_file: HtmlFile, used_outputs: set) -> Path:
        """Nombre del archivo nuevo = nombre + sufijo. Nunca se sobreescribe el original."""
        name = f"{html_file.path.stem}{self._suffix}{html_file.path.suffix}"
        if self._output_dir is None:
            candidate = html_file.path.with_name(name)
        else:
            candidate = self._output_dir / html_file.relative_path.parent / name

        # si dos entradas terminan en la misma salida (ej. dos index.html sueltos
        # de carpetas distintas) le pongo _2, _3... para que no se pisen
        counter = 2
        unique = candidate
        while unique.resolve() in used_outputs:
            unique = candidate.with_name(f"{candidate.stem}_{counter}{candidate.suffix}")
            counter += 1
        used_outputs.add(unique.resolve())
        return unique

    @staticmethod
    def _read_html(path: Path) -> tuple[str, str]:
        """Lee el HTML y devuelve (texto, encoding) para escribir el nuevo igual.

        Pruebo utf-8 y si falla cp1252 (tipico de archivos viejos hechos en
        Windows). latin-1 va de ultimo porque nunca falla.
        """
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            return raw.decode("utf-8-sig"), "utf-8-sig"
        for encoding in ("utf-8", "cp1252", "latin-1"):
            try:
                return raw.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise UnicodeDecodeError("desconocida", raw, 0, 1, "codificación no soportada")
