# Ejercicio 3 - Rachas

La idea es encontrar, para cada cliente, cuántos meses seguidos estuvo en un mismo nivel de deuda, a partir del archivo `data/rachas.xlsx`.

## Para correrlo

Solo se necesita Python 3.10 o superior y `openpyxl` para leer el Excel. SQLite ya viene con Python.

```bash
pip install -r ../requirements.txt

python rachas.py cargar                                    # arma rachas.db a partir del Excel
python rachas.py consultar --fecha-base 2024-12-31 --n 3   # la consulta que pide el ejercicio
python rachas.py consultar --fecha-base 2024-06-15 --n 4 --salida resultados/mi_corrida.csv

python rachas.py calidad                                   # problemas de datos que se encontraron
python rachas.py detalle --identificacion 869YG73INQB5W1NQT --fecha-base 2024-12-31   # un cliente mes a mes

python -m unittest -v                                      # pruebas
```

Los scripts de `sql/` también se pueden correr a mano, en orden, desde cualquier cliente de SQLite (yo usé DB Browser for SQLite para revisar). Lo único que hace Python es pasar el Excel a las tablas `stg_*` y ejecutar los `.sql`; la lógica está toda en SQL.

```
ejercicio_3_rachas/
├── data/rachas.xlsx
├── sql/
│   ├── 01_ddl.sql               # creación de tablas
│   ├── 02_calidad_datos.sql     # reglas de calidad sobre lo que llega del Excel
│   ├── 03_limpieza.sql          # paso a las tablas limpias
│   ├── 04_rachas.sql            # la consulta del ejercicio
│   └── 05_detalle_cliente.sql   # apoyo para revisar un cliente
├── rachas.py
├── resultados/                  # algunas salidas de ejemplo
└── tests/test_rachas.py
```

## Por qué SQLite

De las opciones que daba el enunciado escogí SQLite porque cualquiera puede replicar la solución sin montar un servidor: viene con Python y la base es un solo archivo. Tiene funciones de ventana y CTE recursivas, que era lo que necesitaba.

Casi todo es SQL estándar. Lo único que cambiaría en otro motor son las funciones de fecha: en PostgreSQL usaría `date_trunc` e `interval`, y en Impala `add_months` y `last_day`.

## Primero, revisar los datos

Antes de escribir la consulta me puse a revisar el Excel, porque el enunciado deja claro que la calidad de los datos es responsabilidad de uno. Encontré cuatro cosas:

**Una fila repetida.** `9NWFWJ38XN31WBFXG` aparece dos veces en agosto de 2023 con el mismo saldo. Esa es fácil: se deja una.

**Un cliente con dos saldos en el mismo mes.** `R7Q4Z9AULIORDJQ9D` tiene en diciembre de 2024 un saldo de 571.481 y otro de 1.142.962. Me llamó la atención que el segundo es exactamente el doble del primero, que es lo que pasa cuando un registro se suma dos veces (por ejemplo, un cruce que duplica filas antes de agregar). Por eso me quedé con el menor. Como el cambio no es menor (uno queda en N1 y el otro en N2), lo dejé marcado como advertencia para confirmarlo con negocio.

**Un retiro con una identificación rara.** `1LFTDYT2H0I9ZGED3S8` tiene 19 caracteres, cuando todas las demás tienen 17, y no existe en la hoja de historia. Es casi seguro que se trata de `1LFTDYT2H0I9ZG3S8` con un "ED" de más, pero preferí no corregirlo por mi cuenta: si me equivoco, le aplico un retiro a otro cliente y le cambio el resultado. Lo rechacé y quedó documentado. Si se confirma, la corrección es una línea.

**Clientes con saldo después de retirarse.** `0TTW5R9RRCJ0A9E5F` y `THJ9OBJH3W6ANRCMS` tienen saldos en meses posteriores a su fecha de retiro (14 registros en total). Los dejé, porque el enunciado usa el retiro solo para no imputar meses faltantes; en ningún lado dice que haya que borrar saldos que sí llegaron. Además un cliente retirado puede seguir debiendo, por ejemplo si está en cobranza. También quedaron marcados.

Por esto organicé la base en capas. Lo que llega del Excel entra tal cual a unas tablas de staging (`stg_historia`, `stg_retiros`), sin restricciones y con el número de fila del archivo, para que un dato malo no tumbe el cargue y se pueda rastrear. De ahí se pasa a las tablas limpias (`historia`, `retiros`), que sí tienen llaves y validaciones. Cada problema que se encuentra queda registrado en `dq_incidencias` con lo que se hizo, así que ninguna decisión queda escondida. Al final quedan 2.923 de 2.925 filas de historia y 4 de 5 retiros.

Además de las reglas que se dispararon, dejé otras que hoy no encuentran nada pero sirven si el archivo cambia: identificaciones vacías o mal formadas, fechas que no existen (SQLite convierte `2024-02-30` en `2024-03-01` sin avisar, así que eso hay que revisarlo a mano), saldos negativos o no numéricos, espacios o minúsculas en la identificación, cortes que no caen en fin de mes y retiros repetidos.

Una aclaración: el enunciado no dice cómo es una identificación válida. Lo de los 17 caracteres alfanuméricos lo saqué de los datos, porque toda la hoja de historia cumple ese patrón.

Los rangos de los niveles (N0 a N4) los guardé en una tabla (`ref_niveles_deuda`) en lugar de escribirlos en un `CASE`, para que si cambia un umbral no haya que tocar la consulta.

## La consulta

`sql/04_rachas.sql` recibe dos parámetros: `:fecha_base` y `:n`. La armé por pasos (CTE), cada uno con un solo propósito:

1. **La fecha base.** Calculo el último corte cerrado a esa fecha. Si estoy parado el 15 de junio, el corte de junio todavía no existe, así que el último es el 31 de mayo. Todo lo que pasa después de la fecha base se ignora.
2. **El calendario.** Con una CTE recursiva genero todos los fines de mes desde el primer corte hasta el último disponible. Preferí generarlo en lugar de tomar los meses de la tabla porque, si algún mes no tuviera datos de nadie, desaparecería y dos meses separados parecerían seguidos.
3. **La serie de cada cliente.** Cruzo cada cliente con el calendario desde su primera aparición. Si en un mes no tiene registro, ese mes cuenta como N0, a menos que el corte sea posterior a su retiro; en ese caso el mes simplemente no existe para él.
4. **El nivel** de cada mes, con la tabla de referencia.
5. **Las rachas.** Para identificarlas uso la técnica de *gaps and islands* (explicada abajo).
6. **La selección.** Me quedo con las rachas de al menos `n` meses y elijo la más larga; si hay empate, la que terminó más cerca de la fecha base.

### Cómo se identifican las rachas

Convierto cada mes en un número (`año * 12 + mes`) y le resto un contador (`ROW_NUMBER()`) por cliente y nivel. Mientras los meses son seguidos, los dos suben de a uno y la resta da siempre lo mismo. Cuando hay un salto, la resta cambia. Entonces todos los meses con la misma resta forman una racha:

| mes | nivel | número de mes | contador del nivel | resta |
|---|---|---|---|---|
| ene-2024 | N2 | 24289 | 1 | 24288 |
| feb-2024 | N2 | 24290 | 2 | 24288 |
| mar-2024 | N1 | 24291 | 1 | 24290 |
| abr-2024 | N2 | 24292 | 3 | 24289 |
| may-2024 | N2 | 24293 | 4 | 24289 |

Aquí N2 tiene dos rachas de dos meses (ene-feb y abr-may). Si tocara elegir entre ellas, gana abr-may por ser la más reciente.

### Un ejemplo real

`869YG73INQB5W1NQT` muestra casi todas las reglas juntas (se puede ver con `python rachas.py detalle`):

- Hay meses en los que no aparece (marzo, mayo y septiembre de 2023, y febrero y marzo de 2024), así que esos meses cuentan como N0. Los de 2024 forman una racha de dos meses en N0.
- De agosto a octubre de 2024 está en N2: es su única racha de tres meses.
- Se retiró el 5 de diciembre de 2024. El corte de diciembre (día 31) es posterior al retiro, así que ese mes no se imputa y su serie termina en noviembre.

Con `n = 3` el resultado para este cliente es `3 | 2024-10-31 | N2`.

### Supuestos

Hay algunas cosas que el enunciado no precisa, y esto fue lo que decidí:

- **Hasta qué mes imputo.** Hasta el último corte que existe en los datos (diciembre de 2024). Si alguien consulta con fecha base mayo de 2025, no relleno enero a mayo de 2025 con N0: no es que el cliente no haya aparecido, es que todavía no hay datos de nadie para esos meses.
- **"Superior a la fecha de retiro" lo tomé estricto.** Si el retiro fue el mismo día del corte, ese mes sí se imputa.
- **Si el retiro es posterior a la fecha base, no tiene efecto,** porque a esa fecha el cliente todavía no se había retirado.
- **Un mes que falta después del retiro corta la racha,** porque ese mes no existe para el cliente.
- **Los clientes que no tienen ninguna racha de al menos `n` meses no salen en el resultado.**

## Resultados

Con `fecha_base = 2024-12-31` y `n = 3` salen **92 clientes** (el detalle está en `resultados/rachas_2024-12-31_n3.csv`). Por nivel: 30 en N2, 30 en N4, 16 en N0, 15 en N3 y 1 en N1.

Si se sube a `n = 6` solo quedan dos:

| identificacion | racha | fecha_fin | nivel |
|---|---|---|---|
| DWJ0GFUKS12L7Y0G9 | 6 | 2023-11-30 | N2 |
| IGOQX9XYBSRDMOZXT | 6 | 2023-12-31 | N4 |

## Cómo lo validé

Escribí pruebas pequeñas para cada regla: meses faltantes, retiro (incluido el caso del retiro el mismo día del corte), empates, fecha base a mitad de mes, rachas que pasan de un año a otro, los límites exactos de cada nivel y los problemas de calidad.

Además escribí la misma lógica otra vez en Python, sin gaps and islands, recorriendo cada cliente mes a mes, y la comparé con el SQL en 30 combinaciones de fecha base y `n` sobre el Excel real. Dieron exactamente lo mismo en todas. Si dos formas distintas de resolverlo coinciden, es difícil que las dos tengan el mismo error.

Por último, revisé a mano con `rachas.py detalle` los clientes con incidencias (`R7Q4…`, `869YG…`, `THJ9…`).

## Pendientes

- Confirmar con negocio las tres decisiones de calidad: el saldo duplicado, el retiro con la identificación mal escrita y los saldos posteriores al retiro.
- Si los datos crecieran mucho, guardaría la serie mensual ya imputada en una tabla en vez de recalcularla en cada consulta.
- En un proceso real, las reglas de calidad irían en una herramienta como Great Expectations o en tests de dbt dentro del pipeline (es lo que planteo en los ejercicios 1 y 2).
