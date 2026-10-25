-- 02_calidad_datos.sql
-- Validaciones sobre staging. Corre despues de cargar el Excel.
--
-- Las dos vistas de abajo limpian los campos y marcan si cada uno es valido
-- (1/0). Tanto las reglas de este archivo como 03_limpieza.sql leen de ahi,
-- asi la definicion de "dato valido" esta en un solo lado.
--
-- El formato de identificacion (17 caracteres, letras mayusculas y numeros) no
-- lo dice el enunciado, lo saque de revisar el archivo: toda la hoja historia
-- lo cumple.

DELETE FROM dq_incidencias;

DROP VIEW IF EXISTS vw_stg_historia;
CREATE VIEW vw_stg_historia AS
WITH normalizada AS (
    SELECT
        fila_origen,
        identificacion                     AS identificacion_original,
        UPPER(TRIM(identificacion))        AS identificacion,
        TRIM(corte_mes)                    AS corte_mes_original,
        DATE(TRIM(corte_mes))              AS corte_mes_fecha,
        saldo
    FROM stg_historia
)
SELECT
    fila_origen,
    identificacion_original,
    identificacion,
    corte_mes_original,
    DATE(corte_mes_fecha, 'start of month', '+1 month', '-1 day') AS corte_mes,  -- llevado a fin de mes
    saldo,
    CASE
        WHEN length(identificacion) = 17
         AND identificacion NOT GLOB '*[^A-Z0-9]*' THEN 1
        ELSE 0
    END AS id_valido,
    -- ojo: DATE() de SQLite no falla con fechas imposibles, '2024-02-30' lo
    -- vuelve '2024-03-01'. Por eso comparo contra el texto original.
    CASE
        WHEN corte_mes_fecha IS NOT NULL
         AND corte_mes_fecha = substr(corte_mes_original, 1, 10) THEN 1
        ELSE 0
    END AS fecha_valida,
    CASE
        WHEN typeof(saldo) IN ('integer', 'real') AND saldo >= 0 THEN 1
        ELSE 0
    END AS saldo_valido
FROM normalizada;


DROP VIEW IF EXISTS vw_stg_retiros;
CREATE VIEW vw_stg_retiros AS
SELECT
    fila_origen,
    identificacion                         AS identificacion_original,
    UPPER(TRIM(identificacion))            AS identificacion,
    TRIM(fecha_retiro)                     AS fecha_retiro_original,
    DATE(TRIM(fecha_retiro))               AS fecha_retiro,
    CASE
        WHEN length(UPPER(TRIM(identificacion))) = 17
         AND UPPER(TRIM(identificacion)) NOT GLOB '*[^A-Z0-9]*' THEN 1
        ELSE 0
    END AS id_valido,
    CASE
        WHEN DATE(TRIM(fecha_retiro)) IS NOT NULL
         AND DATE(TRIM(fecha_retiro)) = substr(TRIM(fecha_retiro), 1, 10) THEN 1
        ELSE 0
    END AS fecha_valida
FROM stg_retiros;


-- ---------------------------------------------------------------------------
-- Reglas sobre historia
-- ---------------------------------------------------------------------------

-- H1: sin identificacion valida no se sabe de quien es el saldo -> se rechaza
INSERT INTO dq_incidencias (tabla_origen, fila_origen, identificacion, regla, severidad, accion, detalle)
SELECT
    'historia',
    fila_origen,
    identificacion_original,
    'H1_IDENTIFICACION_INVALIDA',
    'ERROR',
    'RECHAZADO',
    'Se esperaban 17 caracteres alfanuméricos; llegó: ' || COALESCE(quote(identificacion_original), 'NULL')
FROM vw_stg_historia
WHERE id_valido = 0;

-- H2: fecha de corte vacia o que no se puede leer
INSERT INTO dq_incidencias (tabla_origen, fila_origen, identificacion, regla, severidad, accion, detalle)
SELECT
    'historia',
    fila_origen,
    identificacion,
    'H2_CORTE_MES_INVALIDO',
    'ERROR',
    'RECHAZADO',
    'Valor recibido: ' || COALESCE(quote(corte_mes_original), 'NULL')
FROM vw_stg_historia
WHERE fecha_valida = 0;

-- H3: saldo vacio, no numerico o negativo. Los niveles arrancan en 0, un
-- negativo no tiene nivel.
INSERT INTO dq_incidencias (tabla_origen, fila_origen, identificacion, regla, severidad, accion, detalle)
SELECT
    'historia',
    fila_origen,
    identificacion,
    'H3_SALDO_INVALIDO',
    'ERROR',
    'RECHAZADO',
    'Valor recibido: ' || COALESCE(quote(saldo), 'NULL')
FROM vw_stg_historia
WHERE saldo_valido = 0;

-- H4: identificacion con espacios o minusculas, se corrige
INSERT INTO dq_incidencias (tabla_origen, fila_origen, identificacion, regla, severidad, accion, detalle)
SELECT
    'historia',
    fila_origen,
    identificacion,
    'H4_IDENTIFICACION_NORMALIZADA',
    'ADVERTENCIA',
    'CORREGIDO',
    quote(identificacion_original) || ' -> ' || quote(identificacion)
FROM vw_stg_historia
WHERE id_valido = 1
  AND identificacion_original <> identificacion;

-- H5: corte que no cae en fin de mes, se pasa al fin de su mes
INSERT INTO dq_incidencias (tabla_origen, fila_origen, identificacion, regla, severidad, accion, detalle)
SELECT
    'historia',
    fila_origen,
    identificacion,
    'H5_CORTE_NO_ES_FIN_DE_MES',
    'ADVERTENCIA',
    'CORREGIDO',
    corte_mes_original || ' -> ' || corte_mes
FROM vw_stg_historia
WHERE fecha_valida = 1
  AND substr(corte_mes_original, 1, 10) <> corte_mes;

-- H6 / H7: mismo cliente y mismo corte mas de una vez.
--   H6 = repetido identico, se deja uno.
--   H7 = saldos distintos, me quedo con el menor.
--
-- Lo del menor: el unico caso del archivo es R7Q4Z9AULIORDJQ9D en 2024-12-31,
-- con 571.481 y 1.142.962. El segundo es justo el doble del primero, eso huele
-- a un registro sumado dos veces (un join que duplico antes de agregar). Queda
-- como advertencia para que negocio confirme.
WITH validos AS (
    SELECT *
    FROM vw_stg_historia
    WHERE id_valido = 1 AND fecha_valida = 1 AND saldo_valido = 1
),
grupos AS (
    SELECT
        identificacion,
        corte_mes,
        MIN(saldo)                      AS saldo_conservado,
        COUNT(DISTINCT saldo)           AS saldos_distintos,
        group_concat(DISTINCT saldo)    AS lista_saldos
    FROM validos
    GROUP BY identificacion, corte_mes
    HAVING COUNT(*) > 1
),
filas_descartadas AS (
    SELECT
        v.fila_origen,
        v.identificacion,
        v.corte_mes,
        v.saldo,
        g.saldo_conservado,
        g.saldos_distintos,
        g.lista_saldos,
        -- la fila que se queda es la de menor saldo (si empatan, la primera del archivo)
        ROW_NUMBER() OVER (
            PARTITION BY v.identificacion, v.corte_mes
            ORDER BY v.saldo, v.fila_origen
        ) AS orden
    FROM validos AS v
    INNER JOIN grupos AS g
        ON  g.identificacion = v.identificacion
        AND g.corte_mes      = v.corte_mes
)
INSERT INTO dq_incidencias (tabla_origen, fila_origen, identificacion, regla, severidad, accion, detalle)
SELECT
    'historia',
    fila_origen,
    identificacion,
    CASE WHEN saldos_distintos = 1 THEN 'H6_DUPLICADO_EXACTO'
         ELSE 'H7_DUPLICADO_SALDO_DIFERENTE' END,
    'ADVERTENCIA',
    'DESCARTADO',
    'Corte ' || corte_mes || ': saldos encontrados [' || lista_saldos
        || '], se conserva ' || saldo_conservado
FROM filas_descartadas
WHERE orden > 1;


-- ---------------------------------------------------------------------------
-- Reglas sobre retiros
-- ---------------------------------------------------------------------------

-- R1: identificacion con formato invalido.
-- Aca cae '1LFTDYT2H0I9ZGED3S8' (19 caracteres). Casi seguro es
-- '1LFTDYT2H0I9ZG3S8' con un "ED" de mas, pero no lo corrijo solo: si me
-- equivoco le meto un retiro a otro cliente y le cambio el resultado.
-- Lo dejo rechazado y documentado.
INSERT INTO dq_incidencias (tabla_origen, fila_origen, identificacion, regla, severidad, accion, detalle)
SELECT
    'retiros',
    fila_origen,
    identificacion_original,
    'R1_IDENTIFICACION_INVALIDA',
    'ERROR',
    'RECHAZADO',
    'Se esperaban 17 caracteres alfanuméricos; llegó '
        || COALESCE(quote(identificacion_original), 'NULL')
        || ' (' || COALESCE(length(identificacion_original), 0) || ' caracteres)'
FROM vw_stg_retiros
WHERE id_valido = 0;

-- R2: fecha de retiro vacia o que no se puede leer
INSERT INTO dq_incidencias (tabla_origen, fila_origen, identificacion, regla, severidad, accion, detalle)
SELECT
    'retiros',
    fila_origen,
    identificacion,
    'R2_FECHA_RETIRO_INVALIDA',
    'ERROR',
    'RECHAZADO',
    'Valor recibido: ' || COALESCE(quote(fecha_retiro_original), 'NULL')
FROM vw_stg_retiros
WHERE fecha_valida = 0;

-- R3: cliente con varios retiros, queda el mas reciente
WITH ordenados AS (
    SELECT
        fila_origen,
        identificacion,
        fecha_retiro,
        ROW_NUMBER() OVER (
            PARTITION BY identificacion
            ORDER BY fecha_retiro DESC, fila_origen
        ) AS orden
    FROM vw_stg_retiros
    WHERE id_valido = 1 AND fecha_valida = 1
)
INSERT INTO dq_incidencias (tabla_origen, fila_origen, identificacion, regla, severidad, accion, detalle)
SELECT
    'retiros',
    fila_origen,
    identificacion,
    'R3_RETIRO_DUPLICADO',
    'ADVERTENCIA',
    'DESCARTADO',
    'Se descarta fecha ' || fecha_retiro || ' y se conserva la más reciente'
FROM ordenados
WHERE orden > 1;
