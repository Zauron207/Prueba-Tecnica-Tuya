"""
Mete las imagenes de archivos HTML dentro del mismo HTML, en base64.

    from html_embedder import HtmlImageEmbedder

    report = HtmlImageEmbedder().process(["sitio/", "otra/pagina.html"])
    print(report.to_dict())   # {"success": {...}, "fail": {...}}
"""

from .embedder import HtmlImageEmbedder
from .report import ProcessingReport

__all__ = ["HtmlImageEmbedder", "ProcessingReport"]
