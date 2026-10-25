-- =============================================================================
-- 01_ddl.sql
-- Estructura de la base de datos del ejercicio de rachas (SQLite).
--
-- Organicé las tablas en capas, parecido a como se haría en un lakehouse:
--   stg_*  -> datos tal como vienen del Excel, sin validar, con la fila de origen
--             para poder rastrear cualquier registro hasta el archivo fuente.
--   ref_*  -> tablas de referencia / parametrización de negocio.
--   historia, retiros -> datos limpios, tipados, sin duplicados (los que consume
--             la consulta de rachas).
--   dq_*   -> bitácora de incidencias de calidad de datos.
--
-- El script es idempotente: borra y recrea todo, así que se puede correr
-- varias veces sin dejar basura de ejecuciones anteriores.
-- =============================================================================

PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS vw_stg_historia;
DROP VIEW  IF EXISTS vw_stg_retiros;
DROP TABLE IF EXISTS dq_incidencias;
DROP TABLE IF EXISTS historia;
DROP TABLE IF EXISTS retiros;
DROP TABLE IF EXISTS ref_niveles_deuda;
DROP TABLE IF EXISTS stg_historia;
DROP TABLE IF EXISTS stg_retiros;


-- -----------------------------------------------------------------------------
-- Staging
-- saldo se declara NUMERIC a propósito: SQLite convierte a número lo que pueda
-- y deja como TEXT lo que no. Así después puedo detectar valores no numéricos
-- con typeof() en vez de que el cargue falle.
-- -----------------------------------------------------------------------------
CREATE TABLE stg_historia (
    fila_origen     INTEGER PRIMARY KEY,  -- número de fila en la hoja "historia"
    identificacion  TEXT,
    corte_mes       TEXT,
    saldo           NUMERIC
);

CREATE TABLE stg_retiros (
    fila_origen     INTEGER PRIMARY KEY,  -- número de fila en la hoja "retiros"
    identificacion  TEXT,
    fecha_retiro    TEXT
);


-- -----------------------------------------------------------------------------
-- Referencia: niveles de deuda
-- Los rangos quedan como datos y no "quemados" en un CASE. Si negocio cambia
-- un umbral, se actualiza la tabla y la consulta no se toca.
-- Convención: limite_inferior incluido (>=), limite_superior excluido (<).
-- -----------------------------------------------------------------------------
CREATE TABLE ref_niveles_deuda (
    nivel            TEXT    PRIMARY KEY,
    limite_inferior  INTEGER NOT NULL,
    limite_superior  INTEGER,             -- NULL = sin tope
    CHECK (limite_superior IS NULL OR limite_superior > limite_inferior)
);

INSERT INTO ref_niveles_deuda (nivel, limite_inferior, limite_superior) VALUES
    ('N0',         0,    300000),
    ('N1',    300000,   1000000),
    ('N2',   1000000,   3000000),
    ('N3',   3000000,   5000000),
    ('N4',   5000000,      NULL);


-- -----------------------------------------------------------------------------
-- Capa limpia
-- Las restricciones CHECK son una segunda línea de defensa: si algo se escapa
-- de las validaciones de 02_calidad_datos.sql, el INSERT falla en vez de
-- dejar entrar un dato malo en silencio.
-- -----------------------------------------------------------------------------
CREATE TABLE historia (
    identificacion  TEXT    NOT NULL CHECK (length(identificacion) = 17),
    corte_mes       TEXT    NOT NULL
        CHECK (corte_mes = DATE(corte_mes, 'start of month', '+1 month', '-1 day')),
    saldo           NUMERIC NOT NULL CHECK (saldo >= 0),
    PRIMARY KEY (identificacion, corte_mes)
);

CREATE TABLE retiros (
    identificacion  TEXT PRIMARY KEY CHECK (length(identificacion) = 17),
    fecha_retiro    TEXT NOT NULL CHECK (fecha_retiro = DATE(fecha_retiro))
);


-- -----------------------------------------------------------------------------
-- Bitácora de calidad de datos
-- Cada regla que se dispara deja una fila aquí con la acción tomada, para que
-- cualquier decisión sobre los datos sea auditable.
-- -----------------------------------------------------------------------------
CREATE TABLE dq_incidencias (
    id_incidencia   INTEGER PRIMARY KEY AUTOINCREMENT,
    tabla_origen    TEXT NOT NULL,
    fila_origen     INTEGER,
    identificacion  TEXT,
    regla           TEXT NOT NULL,
    severidad       TEXT NOT NULL CHECK (severidad IN ('ERROR', 'ADVERTENCIA')),
    accion          TEXT NOT NULL
        CHECK (accion IN ('RECHAZADO', 'CORREGIDO', 'DESCARTADO', 'CONSERVADO')),
    detalle         TEXT,
    fecha_registro  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX ix_dq_incidencias_regla ON dq_incidencias (regla);
