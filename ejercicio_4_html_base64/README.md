# Ejercicio 4 - Imágenes de HTML a base64

Un paquete en Python que recibe archivos HTML (o carpetas con HTML adentro), busca las etiquetas `<img>`, convierte cada imagen a base64 y genera un HTML nuevo con las imágenes metidas dentro del mismo archivo. El original no se toca.

Todo está hecho con la librería estándar, como pedía el enunciado.

## Para correrlo

Con Python 3.10 o superior basta, no hay que instalar nada.

```bash
# una carpeta (recorre también las subcarpetas)
python -m html_embedder ejemplos/sitio

# archivos y carpetas mezclados, con salida en otra carpeta y el reporte en JSON
python -m html_embedder ejemplos/sitio ejemplos/pagina_suelta.html --output-dir salida --reporte salida/reporte.json

# sin descargar imágenes de internet y mostrando el detalle
python -m html_embedder ejemplos/sitio --sin-remotas -v

python -m unittest -v
```

También se puede usar desde código:

```python
from html_embedder import HtmlImageEmbedder

report = HtmlImageEmbedder().process(["ejemplos/sitio", "ejemplos/pagina_suelta.html"])
report.to_dict()   # {"success": {...}, "fail": {...}}
```

En `ejemplos/` hay un sitio pequeño para probarlo: una página con varias imágenes, otra en una subcarpeta que sube de nivel (`../img/`), una imagen de internet y una página suelta para probar la entrada por archivo. Dejé dos imágenes que deben fallar a propósito: una que no existe y un `.png` que en realidad es un texto. Los casos más raros (comentarios, `<script>`, `src` sin comillas, etiquetas en varias líneas, `data-src`...) están en las pruebas.

## El resultado

El enunciado pide un objeto con `success` y `fail`. Lo organicé por archivo, para que se sepa en qué página está cada imagen, y en los fallos agregué el motivo, porque es lo primero que alguien va a necesitar para arreglarlo:

```json
{
  "success": {
    "ejemplos/sitio/index.html": ["img/logo.png", "img/banner.png", "img/icono.svg", "img/foto%20perfil.gif"]
  },
  "fail": {
    "ejemplos/sitio/index.html": {
      "img/no_existe.jpg": "Archivo no encontrado: ejemplos/sitio/img/no_existe.jpg",
      "img/no_es_imagen.png": "La extensión indica image/png, pero el contenido no corresponde a ese formato"
    }
  }
}
```

Si lo que falla es el HTML completo (por ejemplo, no se puede leer), aparece con la clave `__archivo__`. El resultado completo de los ejemplos está en [`ejemplos/reporte_ejemplo.json`](ejemplos/reporte_ejemplo.json).

## Cómo lo organicé

```
html_embedder/
├── __main__.py   # la línea de comandos
├── embedder.py   # HtmlImageEmbedder, coordina todo
├── collector.py  # arma la lista de HTML a partir de archivos y carpetas
├── parser.py     # encuentra cada <img> y dónde está exactamente
├── sources.py    # de dónde salen los bytes de la imagen (disco, internet...)
├── encoder.py    # revisa que sea una imagen de verdad y arma el base64
└── report.py     # el objeto success / fail
```

La idea fue que cada clase hiciera una sola cosa y que `HtmlImageEmbedder` solo coordinara. Las piezas que pueden cambiar (de dónde se leen las imágenes y cómo se codifican) se le pasan por constructor. Eso me sirvió mucho en las pruebas: para probar las imágenes de internet le paso un "servidor" falso y no dependo de tener conexión.

Los orígenes de imagen comparten la misma interfaz. Hoy hay tres: archivos locales, descargas por HTTP y uno que rechaza las URLs cuando se usa `--sin-remotas`. Si mañana las imágenes vinieran de otro lado (S3, por ejemplo), se agrega una clase y no se toca lo demás.

## Decisiones

**Cómo encontrar las imágenes sin dañar el HTML.** Esta fue la decisión que más pensé. Con una expresión regular sola se encuentran `<img>` que están dentro de comentarios o de un `<script>` y que no deberían tocarse. Si uso `HTMLParser` y vuelvo a generar el HTML desde el parser, se pierde el formato original (comillas, mayúsculas, espacios). Lo que hice fue usar el parser solo para saber dónde está cada etiqueta, y luego cambiar únicamente el `src` de esa etiqueta sobre el texto original. Comparé la entrada con la salida y el resto del archivo queda idéntico.

**Revisar que la imagen sea una imagen.** El tipo de archivo lo saco de los primeros bytes (cada formato tiene una firma; un PNG, por ejemplo, siempre empieza igual) y no de la extensión. En la primera versión confiaba en la extensión y el `.png` de prueba, que en realidad es un texto, pasaba como éxito y quedaba una imagen rota. Ahora termina en `fail`. La extensión solo la uso para formatos que no reviso por contenido, como AVIF o TIFF.

**Nunca tocar el original.** El archivo nuevo queda como `nombre_base64.html` al lado del original, o en la carpeta de `--output-dir` con la misma estructura de subcarpetas. Al recorrer carpetas me salto los que ya terminan en `_base64`, porque si no, al correrlo dos veces aparecía un `index_base64_base64.html`.

**Qué tipos de `src` acepta:**

- rutas relativas (`img/a.png`, `../img/a.png`), que se resuelven desde la carpeta del HTML y no desde donde se ejecuta el comando;
- rutas absolutas y `file://`;
- nombres con `%20` u otros caracteres codificados;
- `?v=3` o `#algo` al final, que se ignoran para buscar el archivo;
- `http://`, `https://` y `//cdn...`, que se descargan con `urllib` (con timeout);
- `data:...`, que ya están en base64 y se dejan como están;
- `<img>` sin `src`, que se ignora.

**Otros detalles.** Si la misma imagen aparece varias veces, se lee una sola vez; también guardo los errores, para no esperar el timeout de una URL caída en cada archivo. El HTML nuevo se arma en partes y se une al final, porque las imágenes en base64 pueden pesar varios MB y concatenar texto en un ciclo es lento. El archivo nuevo sale con la misma codificación del original (probé con un archivo en cp1252, típico de Windows) y con los mismos saltos de línea. Y si una imagen falla, el proceso sigue: esa queda en `fail` con su `src` original.

## Pruebas

`tests/test_embedder.py` crea los archivos de cada caso en una carpeta temporal, así las pruebas no dependen de la carpeta de ejemplos ni de internet. Cubren que las etiquetas se ubiquen bien, que se ignoren comentarios y scripts, que solo cambie el `src` (y no `data-src`), que se detecten los archivos falsos o vacíos, que el original quede igual, las subcarpetas y rutas relativas, que no se procese dos veces el mismo archivo ni la propia salida, las imágenes remotas y el caché, la codificación y la línea de comandos.

## Lo que no cubre

- Imágenes en `srcset`, `<picture>` o en el CSS (`background-image`). El enunciado dice que todas están en `<img>`, pero sería lo siguiente que agregaría.
- Archivos HTML muy grandes, porque el archivo se lee completo en memoria. Para páginas normales no es problema.
