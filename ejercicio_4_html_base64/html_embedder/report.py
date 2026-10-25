"""El objeto de resultado: que imagenes salieron bien y cuales fallaron."""

import json
from dataclasses import dataclass, field


@dataclass
class ProcessingReport:
    """El objeto que pide el enunciado, organizado por archivo:

        {
            "success": {"ruta/archivo.html": ["img/logo.png", ...]},
            "fail":    {"ruta/archivo.html": {"img/no_existe.png": "motivo"}}
        }

    En fail guardo tambien el motivo, que es lo primero que alguien va a
    preguntar para poder arreglarlo.
    """

    success: dict[str, list[str]] = field(default_factory=dict)
    fail: dict[str, dict[str, str]] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)  # html original -> html nuevo

    def add_success(self, html_file: str, src: str) -> None:
        images = self.success.setdefault(html_file, [])
        if src not in images:
            images.append(src)

    def add_fail(self, html_file: str, src: str, reason: str) -> None:
        self.fail.setdefault(html_file, {})[src] = reason

    def add_output(self, html_file: str, output_file: str) -> None:
        self.outputs[html_file] = output_file

    @property
    def total_success(self) -> int:
        return sum(len(images) for images in self.success.values())

    @property
    def total_fail(self) -> int:
        return sum(len(images) for images in self.fail.values())

    def to_dict(self) -> dict:
        return {"success": self.success, "fail": self.fail}

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
