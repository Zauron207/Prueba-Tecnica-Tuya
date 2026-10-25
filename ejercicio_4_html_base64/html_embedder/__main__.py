"""Linea de comandos.

    python -m html_embedder ejemplos/sitio
    python -m html_embedder pagina1.html carpeta/ --output-dir salida --reporte reporte.json
    python -m html_embedder ejemplos/sitio --sin-remotas -v
"""

import argparse
import logging
import sys
from pathlib import Path

from .embedder import DEFAULT_SUFFIX, HtmlImageEmbedder
from .sources import DisabledRemoteSource, HttpSource, ImageResolver, LocalFileSource


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="html_embedder",
        description="Reemplaza las imágenes <img> de archivos HTML por su versión en base64.",
    )
    parser.add_argument("rutas", nargs="+", help="Archivos HTML y/o directorios (se recorren subdirectorios)")
    parser.add_argument("--output-dir", type=Path, help="Carpeta de salida (por defecto, junto al original)")
    parser.add_argument("--sufijo", default=DEFAULT_SUFFIX, help=f"Sufijo del archivo nuevo (defecto: {DEFAULT_SUFFIX})")
    parser.add_argument("--reporte", type=Path, help="Guarda el objeto success/fail en un archivo JSON")
    parser.add_argument("--sin-remotas", action="store_true", help="No descarga imágenes http/https")
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout en segundos para imágenes remotas")
    parser.add_argument("-v", "--verbose", action="store_true", help="Muestra el detalle del proceso")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )

    remote = DisabledRemoteSource() if args.sin_remotas else HttpSource(timeout=args.timeout)
    sources = [LocalFileSource(), remote]

    embedder = HtmlImageEmbedder(
        resolver=ImageResolver(sources),
        output_dir=args.output_dir,
        suffix=args.sufijo,
    )
    report = embedder.process(args.rutas)

    print(report.to_json())
    if args.reporte:
        args.reporte.parent.mkdir(parents=True, exist_ok=True)
        args.reporte.write_text(report.to_json(), encoding="utf-8")

    print(
        f"\nImágenes convertidas: {report.total_success} | fallidas: {report.total_fail} "
        f"| HTML generados: {len(report.outputs)}",
        file=sys.stderr,
    )
    # sale con 0 aunque fallen imagenes, el detalle queda en el reporte.
    # Solo es error si no se genero ningun archivo
    return 0 if report.outputs else 1


if __name__ == "__main__":
    sys.exit(main())
