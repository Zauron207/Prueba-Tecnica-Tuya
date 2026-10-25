-- 01_modelo_observabilidad.sql
-- Tablas de la herramienta de veeduria (calidad + trazabilidad) del dataset de
-- telefonos del ejercicio 1. SQL estandar, en Databricks serian tablas Delta.
--
-- La idea: cada corrida del pipeline deja guardado que corrio, con que version,
-- que leyo y escribio, y como le fue en las reglas de calidad. Los KPIs se
-- calculan encima de esto.

-- Reglas de calidad. Se definen una vez y se evaluan en cada corrida.
-- Los umbrales estan aca y no en el codigo, asi negocio los ajusta sin desplegar.
CREATE TABLE dq_regla (
    id_regla            VARCHAR(50)  PRIMARY KEY,      -- p. ej. 'TEL_FORMATO_E164'
    descripcion         VARCHAR(500) NOT NULL,
    dimension           VARCHAR(20)  NOT NULL,         -- COMPLETITUD, VALIDEZ, UNICIDAD, CONSISTENCIA, OPORTUNIDAD, EXACTITUD
    tabla_objetivo      VARCHAR(200) NOT NULL,
    columna_objetivo    VARCHAR(200),
    expresion           VARCHAR(2000) NOT NULL,        -- condición que debe cumplir cada registro
    umbral_advertencia  DECIMAL(5, 2) NOT NULL,        -- % mínimo de cumplimiento para verde
    umbral_critico      DECIMAL(5, 2) NOT NULL,        -- debajo de esto: rojo
    es_bloqueante       BOOLEAN      NOT NULL,         -- si falla, se detiene la publicación a gold
    responsable         VARCHAR(100) NOT NULL,         -- data steward de la regla
    activa              BOOLEAN      NOT NULL DEFAULT TRUE,
    CHECK (umbral_critico <= umbral_advertencia)
);

-- Una fila por cada paso de cada corrida del pipeline
CREATE TABLE pipeline_ejecucion (
    id_ejecucion        VARCHAR(50)  PRIMARY KEY,      -- id del run en el orquestador
    pipeline            VARCHAR(100) NOT NULL,         -- 'dataset_telefonos'
    paso                VARCHAR(100) NOT NULL,         -- 'bronze_ingesta', 'silver_normalizacion', ...
    version_pipeline    VARCHAR(20)  NOT NULL,         -- tag de Git desplegado (v1.4.2)
    commit_sha          CHAR(40)     NOT NULL,
    ambiente            VARCHAR(10)  NOT NULL,         -- DEV, QA, PROD
    fecha_inicio        TIMESTAMP    NOT NULL,
    fecha_fin           TIMESTAMP,
    estado              VARCHAR(20)  NOT NULL,         -- EXITOSO, FALLIDO, BLOQUEADO_POR_CALIDAD
    registros_leidos    BIGINT,
    registros_escritos  BIGINT,
    registros_cuarentena BIGINT
);

-- Como salio cada regla en cada corrida. Es la que mas usa el tablero.
CREATE TABLE dq_resultado (
    id_ejecucion        VARCHAR(50)  NOT NULL REFERENCES pipeline_ejecucion (id_ejecucion),
    id_regla            VARCHAR(50)  NOT NULL REFERENCES dq_regla (id_regla),
    fecha_corte         DATE         NOT NULL,
    fuente              VARCHAR(50)  NOT NULL,         -- permite ver la calidad por sistema origen ('TODAS' = total)
    registros_evaluados BIGINT       NOT NULL,
    registros_fallidos  BIGINT       NOT NULL,
    pct_cumplimiento    DECIMAL(5, 2) NOT NULL,
    semaforo            VARCHAR(5)   NOT NULL,         -- VERDE, AMBAR, ROJO
    muestra_fallidos    VARCHAR(4000),                 -- ids de ejemplo (enmascarados) para investigar
    PRIMARY KEY (id_ejecucion, id_regla, fuente)
);

-- Linaje por tabla: que leyo y que escribio cada corrida.
-- Lo llena OpenLineage solo (desde Spark/dbt), esta tabla es para poder
-- consultarlo facil desde el tablero.
CREATE TABLE linaje_dataset (
    id_ejecucion        VARCHAR(50)  NOT NULL REFERENCES pipeline_ejecucion (id_ejecucion),
    dataset_origen      VARCHAR(200) NOT NULL,
    dataset_destino     VARCHAR(200) NOT NULL,
    version_origen      BIGINT,                        -- versión Delta leída (permite reproducir)
    version_destino     BIGINT,                        -- versión Delta escrita (permite rollback)
    PRIMARY KEY (id_ejecucion, dataset_origen, dataset_destino)
);

-- Linaje por registro: de donde salio cada numero de gold.
-- Para responder "por que este cliente tiene este telefono como principal?"
CREATE TABLE linaje_telefono (
    id_cliente          VARCHAR(64)  NOT NULL,         -- tokenizado
    telefono_hash       CHAR(64)     NOT NULL,         -- SHA-256 del E.164, no el número en claro
    fuente              VARCHAR(50)  NOT NULL,
    id_registro_fuente  VARCHAR(100) NOT NULL,
    fecha_captura       TIMESTAMP    NOT NULL,
    valor_original      VARCHAR(100),                  -- enmascarado: como llegó de la fuente
    reglas_aplicadas    VARCHAR(500),                  -- p. ej. 'QUITAR_INDICATIVO,FIJO_ANTIGUO'
    id_ejecucion        VARCHAR(50)  NOT NULL REFERENCES pipeline_ejecucion (id_ejecucion),
    PRIMARY KEY (id_cliente, telefono_hash, fuente, id_registro_fuente)
);

-- Foto diaria de los KPIs ya calculados. El tablero lee de aca: es rapido y la
-- historia no cambia si despues se reprocesa el dataset.
CREATE TABLE kpi_telefonos_diario (
    fecha_corte         DATE         NOT NULL,
    kpi                 VARCHAR(50)  NOT NULL,
    segmento            VARCHAR(50)  NOT NULL,         -- 'TOTAL', fuente, región, producto...
    valor               DECIMAL(18, 4) NOT NULL,
    meta                DECIMAL(18, 4),
    id_ejecucion        VARCHAR(50)  NOT NULL,
    PRIMARY KEY (fecha_corte, kpi, segmento)
);


-- Algunas reglas de ejemplo para arrancar
INSERT INTO dq_regla VALUES
('TEL_NO_NULO',          'El teléfono no está vacío',                                    'COMPLETITUD',  'silver.telefonos', 'telefono_original', 'telefono_original IS NOT NULL',                      99.00, 95.00, FALSE, 'steward_clientes', TRUE),
('TEL_FORMATO_E164',     'El número normalizado cumple +57 y 10 dígitos',                'VALIDEZ',      'gold.telefonos_cliente', 'telefono_e164', 'telefono_e164 RLIKE ''^\\+57(3[0-5][0-9]{8}|60[1245678][0-9]{7})$''', 100.00, 100.00, TRUE, 'steward_clientes', TRUE),
('TEL_NO_RELLENO',       'El número no es un patrón de relleno',                         'EXACTITUD',    'silver.telefonos', 'estado',            'estado <> ''SOSPECHOSO''',                           97.00, 90.00, FALSE, 'steward_clientes', TRUE),
('TEL_UNICO_CLIENTE',    'Sin duplicados por (cliente, número) en gold',                 'UNICIDAD',     'gold.telefonos_cliente', NULL,          'COUNT(*) = 1 GROUP BY id_cliente, telefono_e164',    100.00, 100.00, TRUE, 'ingenieria_datos', TRUE),
('TEL_UN_PRINCIPAL',     'Cada cliente tiene a lo sumo un principal por tipo',           'UNICIDAD',     'gold.contacto_principal_cliente', NULL, 'COUNT(*) <= 1 GROUP BY id_cliente, tipo_telefono',  100.00, 100.00, TRUE, 'ingenieria_datos', TRUE),
('TEL_COMPARTIDO',       'El número no está asociado a más de 3 clientes',               'CONSISTENCIA', 'gold.telefonos_cliente', 'telefono_e164', 'COUNT(DISTINCT id_cliente) <= 3 GROUP BY telefono_e164', 99.50, 98.00, FALSE, 'steward_clientes', TRUE),
('TEL_FRESCURA_CARGA',   'La carga del día terminó antes de las 6:00 a. m.',             'OPORTUNIDAD',  'gold.contacto_principal_cliente', NULL, 'fecha_fin_ejecucion < fecha_corte + 6 horas',        100.00, 100.00, FALSE, 'ingenieria_datos', TRUE);
