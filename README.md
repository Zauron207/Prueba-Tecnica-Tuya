# Prueba técnica - Ingeniería de Datos Tuya

Aquí está mi solución a los cuatro ejercicios de la prueba. Cada uno tiene su carpeta con un README donde explico lo que hice y por qué; este archivo es el resumen general.

| # | Ejercicio | Carpeta |
|---|---|---|
| 1 | Dataset confiable de teléfonos con CI/CD | [`ejercicio_1_dataset_telefonos`](ejercicio_1_dataset_telefonos/) |
| 2 | Veeduría de calidad, trazabilidad y KPIs | [`ejercicio_2_kpis_calidad`](ejercicio_2_kpis_calidad/) |
| 3 | Rachas de nivel de deuda (SQL) | [`ejercicio_3_rachas`](ejercicio_3_rachas/) |
| 4 | Imágenes de HTML a base64 (Python) | [`ejercicio_4_html_base64`](ejercicio_4_html_base64/) |

## Cómo correrlo

Se necesita Python 3.10 o superior. La única librería externa es `openpyxl`, para leer el Excel del ejercicio 3.

```bash
pip install -r requirements.txt

# Ejercicio 3
cd ejercicio_3_rachas
python rachas.py cargar
python rachas.py consultar --fecha-base 2024-12-31 --n 3
python -m unittest -v
cd ..

# Ejercicio 4
cd ejercicio_4_html_base64
python -m html_embedder ejemplos/sitio ejemplos/pagina_suelta.html --output-dir salida
python -m unittest -v
cd ..

# Ejercicio 1 (la parte implementada)
cd ejercicio_1_dataset_telefonos
python -m unittest -v
```

Las mismas pruebas corren solas en GitHub Actions con cada push ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Resumen

**Ejercicio 1, dataset de teléfonos.** Propongo un pipeline por capas (bronze, silver, gold) que normaliza los números según el plan de numeración colombiano, los clasifica, les da un puntaje de confianza y elige el mejor número de cada cliente. Lo que más me importaba del diseño es que el resultado real de los contactos (llamadas contestadas, SMS entregados) vuelva al pipeline, porque un número con buen formato no necesariamente sirve, y que las pruebas de datos bloqueen los despliegues en el CI/CD. La regla de normalización está implementada y probada.

**Ejercicio 2, veeduría y KPIs.** Cada corrida del pipeline deja registro de sí misma (reglas de calidad, versión del código, linaje por tabla y por registro), y encima de eso se calculan los KPIs y se arma un tablero para negocio. Propongo ocho KPIs con su fórmula y meta, alertas y quién es responsable de qué.

**Ejercicio 3, rachas.** Lo hice en SQLite para que se pueda replicar sin instalar nada. Antes de escribir la consulta revisé el Excel y encontré cuatro problemas de datos (un duplicado, un cliente con dos saldos en el mismo mes, un retiro con la identificación mal escrita y saldos posteriores al retiro); en el README explico qué decidí en cada caso. La consulta genera el calendario de meses, imputa N0 en los meses faltantes respetando el retiro y encuentra las rachas con la técnica de *gaps and islands*. Con `fecha_base = 2024-12-31` y `n = 3` salen 92 clientes. Para validarlo comparé el SQL con la misma lógica escrita en Python en 30 combinaciones de parámetros.

**Ejercicio 4, HTML a base64.** Es un paquete orientado a objetos, solo con la librería estándar, donde cada clase hace una cosa. Uso `HTMLParser` para encontrar las imágenes (así ignora comentarios y scripts), pero cambio solo el `src` sobre el texto original para no dañar el formato del HTML. El tipo de imagen se revisa por su contenido y no por la extensión, así que un `.png` que en realidad es texto termina en `fail`.

## Estructura

```
.
├── ejercicio_1_dataset_telefonos/   # diseño + regla de normalización implementada
├── ejercicio_2_kpis_calidad/        # diseño + modelo SQL de observabilidad
├── ejercicio_3_rachas/              # Excel, scripts SQL, carga en Python, pruebas
├── ejercicio_4_html_base64/         # paquete, ejemplos, pruebas
├── .github/workflows/ci.yml
└── requirements.txt
```
