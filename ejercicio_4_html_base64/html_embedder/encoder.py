"""Pasa los bytes de una imagen a data URI en base64."""

import base64
import mimetypes
from urllib.parse import urlsplit

from .sources import ImageLoadError

# firmas (primeros bytes) de los formatos mas comunes. Me fio mas de esto que
# de la extension: un ".png" puede ser un JPG o hasta una pagina de error 404.
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"\x00\x00\x01\x00", "image/x-icon"),
)

# los que se revisar por contenido. Si la extension dice uno de estos y la
# firma no coincide, el archivo esta malo.
_VERIFIABLE = {mime for _, mime in _SIGNATURES} | {"image/webp", "image/svg+xml", "image/vnd.microsoft.icon"}


def detect_mime_type(data: bytes, src: str = "") -> str:
    """Tipo MIME de la imagen. Si no parece imagen lanza ImageLoadError."""
    for signature, mime in _SIGNATURES:
        if data.startswith(signature):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if b"<svg" in data[:1024].lower():
        return "image/svg+xml"

    guessed, _ = mimetypes.guess_type(urlsplit(src).path)
    if guessed in _VERIFIABLE:
        raise ImageLoadError(f"La extensión indica {guessed}, pero el contenido no corresponde a ese formato")
    # formatos que no reviso por contenido (avif, tiff...): ahi si toca confiar
    # en la extension, siempre que sea de imagen
    if guessed and guessed.startswith("image/"):
        return guessed
    raise ImageLoadError("El contenido no corresponde a un formato de imagen reconocido")


class Base64ImageEncoder:
    def encode(self, data: bytes, src: str = "") -> str:
        if not data:
            raise ImageLoadError("La imagen está vacía (0 bytes)")
        mime = detect_mime_type(data, src)
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
