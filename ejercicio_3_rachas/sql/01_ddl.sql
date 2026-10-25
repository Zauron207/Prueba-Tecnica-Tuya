-- 01_ddl.sql
-- Crea las tablas del ejercicio de rachas (SQLite).
--
-- Las separe en capas:
--   stg_*     ---- lo que viene del Excel tal cual, sin validar, con la fila de
--                  origen para poder rastrear todo hasta el archivo fuenteee
--   ref_*     ---- parametros de negocio (rangos de niveles)
--   historia, retiros ---- datos ya limpios, son los que usa la consulta
--   dq_incidencias    ---- log de lo que encontre en la revision de calidad
--
-- Se puede correr varias veces, siempre borra y crea de nuevo.

PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS vw_stg_historia;
DROP VIEW  IF EXISTS vw_stg_retiros;
DROP TABLE IF EXISTS dq_incidencias;
DROP TABLE IF EXISTS historia;
DROP TABLE IF EXISTS retiros;
DROP TABLE IF EXISTS ref_niveles_deuda;
DROP TABLE IF EXISTS stg_historia;
DROP TABLE IF EXISTS stg_retiros;


-- Staging: sin restricciones para que el cargue no se caiga por un dato malo.
-- el saldo va como NUMERIC a proposito: SQLite convierte a numero lo que puede
-- y lo que no (ej "abc") lo deja como texto, asi despues lo pillo con typeof().
CREATE TABLE stg_historia (
    fila_origen     INTEGER PRIMARY KEY,  -- fila en la hoja "historia"
    identificacion  TEXT,
    corte_mes       TEXT,
    saldo           NUMERIC
);

CREATE TABLE stg_retiros (
    fila_origen     INTEGER PRIMARY KEY,  -- fila en la hoja "retiros"
    identificacion  TEXT,
    fecha_retiro    TEXT
);


-- Niveles de deuda. Los deje en tabla y no en un CASE para no tener que tocar
-- la consulta si negocio cambia un rango.
-- limite_inferior se incluye (>=), limite_superior no (<).
CREATE TABLE ref_niveles_deuda (
    nivel            TEXT    PRIMARY KEY,
    limite_inferior  INTEGER NOT NULL,
    limite_superior  INTEGER,             -- NULL = sin tope (N4)
    CHECK (limite_superior IS NULL OR limite_superior > limite_inferior)
);

INSERT INTO ref_niveles_deuda (nivel, limite_inferior, limite_superior) VALUES
    ('N0',         0,    300000),
    ('N1',    300000,   1000000),
    ('N2',   1000000,   3000000),
    ('N3',   3000000,   5000000),
    ('N4',   5000000,      NULL);


-- Tablas limpias. Los CHECK son por si acaso: si algo malo se cuela de las
-- validaciones, prefiero que el insert falle a que entre callado.
CREATE TABLE historia (
    identificacion  TEXT    NOT NULL CHECK (length(identificacion) = 17),
    corte_mes       TEXT    NOT NULL
        CHECK (corte_mes = DATE(corte_mes, 'start of month', '+1 month', '-1 day')),  -- fin de mes
    saldo           NUMERIC NOT NULL CHECK (saldo >= 0),
    PRIMARY KEY (identificacion, corte_mes)
);

CREATE TABLE retiros (
    identificacion  TEXT PRIMARY KEY CHECK (length(identificacion) = 17),
    fecha_retiro    TEXT NOT NULL CHECK (fecha_retiro = DATE(fecha_retiro))
);


-- Log de calidad: una fila por cada problema encontrado y que se hizo con el.
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
