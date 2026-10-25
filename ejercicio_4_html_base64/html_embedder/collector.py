"""Arma la lista de HTML a procesar a partir de archivos y/o carpetas."""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

HTML_EXTENSIONS = frozenset({".html", ".htm"})


@dataclass(frozen=True)
class HtmlFile:
    path: Path
    # ruta relativa a la carpeta que se paso como entrada, sirve para copiar la
    # misma estructura de subcarpetas cuando se usa --output-dir
    relative_path: Path


class HtmlFileCollector:
    """Recibe archivos y carpetas y devuelve los HTML a procesar.

    - las carpetas se recorren completas (subcarpetas incluidas)
    - se saltan los que ya terminan en el sufijo de salida, si no al correrlo
      dos veces procesa sus propios resultados
    - si un archivo llega repetido se procesa una vez
    """

    def __init__(self, output_suffix: str):
        self._output_suffix = output_suffix

    def collect(self, inputs):
        found = {}
        for raw in inputs:
            path = Path(raw)
            if path.is_dir():
                candidates = ((p, p.relative_to(path)) for p in sorted(path.rglob("*")) if p.is_file())
            elif path.is_file():
                candidates = [(path, Path(path.name))]
            else:
                logger.warning("La ruta no existe y se omite: %s", path)
                continue

            for file_path, relative in candidates:
                if not self._is_processable(file_path):
                    continue
                found.setdefault(file_path.resolve(), HtmlFile(file_path, relative))
        return list(found.values())

    def _is_processable(self, path: Path) -> bool:
        if path.suffix.lower() not in HTML_EXTENSIONS:
            return False
        return not path.stem.endswith(self._output_suffix)
