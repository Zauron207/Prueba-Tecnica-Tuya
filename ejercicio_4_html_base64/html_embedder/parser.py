"""Encuentra las etiquetas <img> dentro del HTML."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser

# el atributo src dentro de la etiqueta. El \s del inicio es para que no
# agarre data-src. Acepta comillas dobles, simples o sin comillas.
_SRC_ATTRIBUTE = re.compile(
    r"""(?P<prefix>\ssrc\s*=\s*)(?P<value>"[^"]*"|'[^']*'|[^\s"'>]+)""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ImgTag:
    src: str
    start: int  # posicion del "<" en el texto
    raw: str    # la etiqueta tal cual esta en el archivo

    @property
    def end(self) -> int:
        return self.start + len(self.raw)

    def with_src(self, new_src: str) -> str:
        """La misma etiqueta pero con otro src. Lo demas no se toca."""
        return _SRC_ATTRIBUTE.sub(
            lambda m: f'{m.group("prefix")}"{new_src}"', self.raw, count=1
        )


class ImgTagParser(HTMLParser):
    """Busca los <img> y donde estan exactamente.

    Por que no solo una regex: encontraria <img> dentro de comentarios y de
    <script>. HTMLParser ya sabe saltarse eso.
    Por que no regenerar el HTML desde el parser: se pierde el formato
    original (comillas, mayusculas, espacios). Entonces uso el parser solo para
    ubicar las etiquetas y el reemplazo lo hago sobre el texto original.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._line_offsets = [0]
        self._html = ""
        self.tags: list[ImgTag] = []

    def find_images(self, html: str) -> list[ImgTag]:
        self.reset()
        self.tags = []
        self._html = html
        # getpos() da (linea, columna). Guardo donde empieza cada linea para
        # pasarlo a posicion absoluta. HTMLParser cuenta lineas por "\n", igual aca.
        self._line_offsets = [0]
        for index, char in enumerate(html):
            if char == "\n":
                self._line_offsets.append(index + 1)
        self.feed(html)
        self.close()
        return self.tags

    def handle_starttag(self, tag, attrs):
        if tag != "img":
            return
        src = dict(attrs).get("src")
        if not src:
            return  # <img> sin src, nada que hacer
        line, column = self.getpos()
        raw = self.get_starttag_text()
        start = self._line_offsets[line - 1] + column
        if self._html[start : start + len(raw)] != raw:
            # no deberia pasar, pero si la posicion no cuadra mejor no tocar
            # nada que dañar el archivo
            return
        self.tags.append(ImgTag(src=src.strip(), start=start, raw=raw))

    # <img ... /> entra por aca, se maneja igual
    handle_startendtag = handle_starttag
