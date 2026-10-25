"""De donde salen los bytes de cada imagen segun su src.

Cada origen (archivo local, URL...) es una clase con la misma interfaz y el
resolver le pregunta a cada uno si sabe manejar ese src. Si mañana toca leer
de S3 se crea otra clase y no se toca nada de lo que ya esta.
"""

import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import unquote, urlsplit


class ImageLoadError(Exception):
    """No se pudo traer la imagen. El mensaje va tal cual al reporte."""


class ImageSource(ABC):
    @abstractmethod
    def can_handle(self, src: str) -> bool:
        """True si este origen sabe cargar ese src."""

    @abstractmethod
    def load(self, src: str, base_dir: Path) -> bytes:
        """Bytes de la imagen, o ImageLoadError si no se pudo."""


class LocalFileSource(ImageSource):
    """Rutas relativas al HTML, absolutas y file://"""

    def can_handle(self, src: str) -> bool:
        scheme = urlsplit(src).scheme.lower()
        # ojo: una ruta de Windows tipo C:/img.png urlsplit la lee como esquema "c"
        return scheme in ("", "file") or len(scheme) == 1

    def load(self, src: str, base_dir: Path) -> bytes:
        path = self._to_path(src, base_dir)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise ImageLoadError(f"Archivo no encontrado: {path.as_posix()}") from None
        except IsADirectoryError:
            raise ImageLoadError(f"La ruta es un directorio: {path.as_posix()}") from None
        except OSError as exc:
            raise ImageLoadError(f"No se pudo leer {path.as_posix()}: {exc.strerror or exc}") from None

    @staticmethod
    def _to_path(src: str, base_dir: Path) -> Path:
        parts = urlsplit(src)
        if parts.scheme.lower() == "file":
            raw_path = unquote(parts.path)
            # file:///C:/img.png queda /C:/img.png, hay que quitar la primera barra
            if len(raw_path) > 2 and raw_path[0] == "/" and raw_path[2] == ":":
                raw_path = raw_path[1:]
            return Path(raw_path)
        if len(parts.scheme) == 1:  # C:/... de Windows
            return Path(src)
        # ?query y #fragmento no son parte del nombre del archivo, se botan.
        # unquote es para los %20 y similares
        path = Path(unquote(parts.path))
        return path if path.is_absolute() else base_dir / path


class HttpSource(ImageSource):
    """Imagenes por http/https, y las que vienen como //cdn... sin protocolo."""

    def __init__(self, timeout: float = 10.0, max_bytes: int = 20 * 1024 * 1024):
        self._timeout = timeout
        self._max_bytes = max_bytes

    def can_handle(self, src: str) -> bool:
        return src.startswith("//") or urlsplit(src).scheme.lower() in ("http", "https")

    def load(self, src: str, base_dir: Path) -> bytes:
        url = f"https:{src}" if src.startswith("//") else src
        request = urllib.request.Request(url, headers={"User-Agent": "html-embedder/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                data = response.read(self._max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise ImageLoadError(f"HTTP {exc.code} al descargar {url}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ImageLoadError(f"No se pudo descargar {url}: {reason}") from None
        if len(data) > self._max_bytes:
            raise ImageLoadError(f"La imagen supera el máximo de {self._max_bytes} bytes: {url}")
        return data


class DisabledRemoteSource(HttpSource):
    """Para --sin-remotas: reconoce la URL pero no la descarga, asi el reporte
    dice por que no se convirtio en vez de un "origen no soportado"."""

    def load(self, src: str, base_dir: Path) -> bytes:
        raise ImageLoadError("Descarga de imágenes remotas desactivada (--sin-remotas)")


class ImageResolver:
    """Le pasa el src al primer origen que sepa manejarlo."""

    def __init__(self, sources: list[ImageSource]):
        self._sources = sources

    def load(self, src: str, base_dir: Path) -> bytes:
        for source in self._sources:
            if source.can_handle(src):
                return source.load(src, base_dir)
        raise ImageLoadError(f"Origen no soportado: {src}")
