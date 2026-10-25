-- 02_kpis.sql
-- Calculo de los KPIs de telefonos sobre gold (ejercicio 1). Corre al final de
-- cada corrida del pipeline y guarda en kpi_telefonos_diario.
-- Sintaxis Spark SQL / Databricks. :fecha_corte e :id_ejecucion los manda el orquestador.

INSERT INTO kpi_telefonos_diario (fecha_corte, kpi, segmento, valor, meta, id_ejecucion)

-- clientes activos con su mejor movil (si tienen)
WITH clientes AS (
    SELECT
        c.id_cliente,
        c.region,
        p.telefono_e164,
        p.score_confianza,
        p.fecha_ultima_confirmacion,
        p.ultimo_resultado_contacto,
        p.fecha_ultimo_contacto,
        p.autoriza_contacto
    FROM gold.clientes_activos AS c
    LEFT JOIN gold.contacto_principal_cliente AS p
        ON  p.id_cliente    = c.id_cliente
        AND p.tipo_telefono = 'MOVIL'
),

kpis AS (
    -- cobertura: % de clientes activos con al menos un movil valido
    SELECT 'COBERTURA_MOVIL_VALIDO' AS kpi, region AS segmento,
           100.0 * AVG(CASE WHEN telefono_e164 IS NOT NULL THEN 1 ELSE 0 END) AS valor,
           95.0 AS meta
    FROM clientes
    GROUP BY region

    UNION ALL

    -- % con movil confirmado en el ultimo año
    SELECT 'MOVIL_ACTUALIZADO_12M', region,
           100.0 * AVG(CASE WHEN fecha_ultima_confirmacion >= ADD_MONTHS(:fecha_corte, -12) THEN 1 ELSE 0 END),
           70.0
    FROM clientes
    GROUP BY region

    UNION ALL

    -- contactabilidad: de los contactados en los ultimos 30 dias, en cuantos
    -- contesto el titular. Este es el que mas le importa a negocio
    SELECT 'CONTACTO_EFECTIVO_30D', region,
           100.0 * AVG(CASE WHEN ultimo_resultado_contacto = 'CONTACTO_TITULAR' THEN 1 ELSE 0 END),
           60.0
    FROM clientes
    WHERE fecha_ultimo_contacto >= DATE_SUB(:fecha_corte, 30)
    GROUP BY region

    UNION ALL

    -- % de principales con autorizacion de contacto vigente (habeas data)
    SELECT 'AUTORIZACION_CONTACTO', region,
           100.0 * AVG(CASE WHEN autoriza_contacto THEN 1 ELSE 0 END),
           100.0
    FROM clientes
    WHERE telefono_e164 IS NOT NULL
    GROUP BY region

    UNION ALL

    -- score promedio del numero principal
    SELECT 'SCORE_PROMEDIO', region, AVG(score_confianza), 75.0
    FROM clientes
    WHERE telefono_e164 IS NOT NULL
    GROUP BY region

    UNION ALL

    -- por fuente: % de registros que llegaron usables
    SELECT 'PCT_VALIDOS_FUENTE', fuente,
           100.0 * AVG(CASE WHEN estado IN ('VALIDO', 'CORREGIDO') THEN 1 ELSE 0 END),
           90.0
    FROM silver.telefonos
    WHERE fecha_carga = :fecha_corte
    GROUP BY fuente

    UNION ALL

    -- % de numeros que tienen mas de un cliente
    SELECT 'PCT_NUMEROS_COMPARTIDOS', 'TOTAL',
           100.0 * AVG(CASE WHEN clientes_por_numero > 1 THEN 1 ELSE 0 END),
           2.0
    FROM (
        SELECT telefono_e164, COUNT(DISTINCT id_cliente) AS clientes_por_numero
        FROM gold.telefonos_cliente
        WHERE es_vigente
        GROUP BY telefono_e164
    ) AS numeros
)

SELECT :fecha_corte, kpi, segmento, ROUND(valor, 4), meta, :id_ejecucion
FROM kpis;


-- ---------------------------------------------------------------------------
-- Consultas del tablero
-- ---------------------------------------------------------------------------

-- tendencia de un KPI por region, ultimos 90 dias
SELECT fecha_corte, segmento, valor, meta
FROM kpi_telefonos_diario
WHERE kpi = 'COBERTURA_MOVIL_VALIDO'
  AND fecha_corte >= DATE_SUB(CURRENT_DATE, 90)
ORDER BY fecha_corte, segmento;

-- semaforo de la ultima corrida en PROD
SELECT r.id_regla, g.descripcion, g.dimension, r.fuente,
       r.pct_cumplimiento, r.semaforo, g.es_bloqueante, g.responsable
FROM dq_resultado AS r
INNER JOIN dq_regla AS g
    ON g.id_regla = r.id_regla
WHERE r.id_ejecucion = (
    SELECT id_ejecucion
    FROM pipeline_ejecucion
    WHERE pipeline = 'dataset_telefonos' AND ambiente = 'PROD' AND paso = 'gold_publicacion'
    ORDER BY fecha_inicio DESC
    LIMIT 1
)
ORDER BY CASE r.semaforo WHEN 'ROJO' THEN 1 WHEN 'AMBAR' THEN 2 ELSE 3 END, r.id_regla;

-- de donde salio el telefono principal de un cliente
SELECT l.fuente, l.fecha_captura, l.valor_original, l.reglas_aplicadas,
       e.version_pipeline, e.commit_sha, e.fecha_inicio AS fecha_procesamiento
FROM linaje_telefono AS l
INNER JOIN pipeline_ejecucion AS e
    ON e.id_ejecucion = l.id_ejecucion
WHERE l.id_cliente = :id_cliente
ORDER BY l.fecha_captura DESC;
