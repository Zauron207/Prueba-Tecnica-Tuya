-- 03_limpieza.sql
-- Pasa de staging a las tablas limpias con las mismas reglas de 02, y al final
-- revisa un par de cosas que solo se pueden ver con los datos ya limpios.

DELETE FROM historia;
DELETE FROM retiros;

-- duplicados: queda el menor saldo (ver H7 en 02_calidad_datos.sql)
INSERT INTO historia (identificacion, corte_mes, saldo)
SELECT
    identificacion,
    corte_mes,
    MIN(saldo) AS saldo
FROM vw_stg_historia
WHERE id_valido    = 1
  AND fecha_valida = 1
  AND saldo_valido = 1
GROUP BY identificacion, corte_mes;

-- duplicados: queda el retiro mas reciente
INSERT INTO retiros (identificacion, fecha_retiro)
SELECT
    identificacion,
    MAX(fecha_retiro) AS fecha_retiro
FROM vw_stg_retiros
WHERE id_valido    = 1
  AND fecha_valida = 1
GROUP BY identificacion;


-- ---------------------------------------------------------------------------
-- Consistencia entre tablas
-- ---------------------------------------------------------------------------

-- C1: retiro de alguien que no esta en historia. No cambia el calculo, pero
-- quiere decir que las llaves de las dos fuentes no cuadran.
INSERT INTO dq_incidencias (tabla_origen, fila_origen, identificacion, regla, severidad, accion, detalle)
SELECT
    'retiros',
    NULL,
    r.identificacion,
    'C1_RETIRO_SIN_HISTORIA',
    'ADVERTENCIA',
    'CONSERVADO',
    'Retiro ' || r.fecha_retiro || ' de un cliente sin registros en historia'
FROM retiros AS r
WHERE NOT EXISTS (
    SELECT 1
    FROM historia AS h
    WHERE h.identificacion = r.identificacion
);

-- C2: saldos en cortes despues de la fecha de retiro.
-- Los dejo. El enunciado solo usa el retiro para no imputar N0 en meses que
-- faltan, no dice que haya que borrar saldos que si llegaron. Ademas alguien
-- retirado puede seguir debiendo (ej. cartera en cobranza). Quedan marcados.
INSERT INTO dq_incidencias (tabla_origen, fila_origen, identificacion, regla, severidad, accion, detalle)
SELECT
    'historia',
    NULL,
    h.identificacion,
    'C2_SALDO_POSTERIOR_A_RETIRO',
    'ADVERTENCIA',
    'CONSERVADO',
    'Corte ' || h.corte_mes || ' con saldo ' || h.saldo
        || ', pero el retiro fue el ' || r.fecha_retiro
FROM historia AS h
INNER JOIN retiros AS r
    ON r.identificacion = h.identificacion
WHERE h.corte_mes > r.fecha_retiro;
