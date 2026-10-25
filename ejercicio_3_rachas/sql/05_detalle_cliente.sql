-- 05_detalle_cliente.sql
-- Consulta de apoyo: la serie mes a mes de UN cliente, con nivel, si se imputo
-- y a que racha pertenece. La use para revisar a mano lo que sale en 04.
--
-- Parametros: :fecha_base y :identificacion
--
-- OJO: es la misma logica de 04_rachas.sql hasta las islas. Si se cambia alla
-- hay que cambiarla aca tambien.

WITH
parametros AS (
    SELECT DATE(:fecha_base, '+1 day', 'start of month', '-1 day') AS ultimo_corte_cerrado
),
limites_calendario AS (
    SELECT MIN(h.corte_mes) AS primer_corte, MAX(h.corte_mes) AS ultimo_corte
    FROM historia AS h
    CROSS JOIN parametros AS p
    WHERE h.corte_mes <= p.ultimo_corte_cerrado
),
calendario (corte_mes) AS (
    SELECT primer_corte FROM limites_calendario WHERE primer_corte IS NOT NULL
    UNION ALL
    SELECT DATE(c.corte_mes, '+1 day', '+1 month', '-1 day')
    FROM calendario AS c
    CROSS JOIN limites_calendario AS l
    WHERE c.corte_mes < l.ultimo_corte
),
historia_cliente AS (
    SELECT h.identificacion, h.corte_mes, h.saldo
    FROM historia AS h
    CROSS JOIN limites_calendario AS l
    WHERE h.identificacion = :identificacion
      AND h.corte_mes <= l.ultimo_corte
),
cliente AS (
    SELECT
        hc.identificacion,
        MIN(hc.corte_mes) AS primera_aparicion,
        r.fecha_retiro
    FROM historia_cliente AS hc
    LEFT JOIN retiros AS r
        ON r.identificacion = hc.identificacion
    GROUP BY hc.identificacion, r.fecha_retiro
),
serie AS (
    SELECT
        c.identificacion,
        cal.corte_mes,
        hc.saldo,
        c.fecha_retiro,
        CASE WHEN hc.identificacion IS NULL THEN 1 ELSE 0 END AS es_imputado
    FROM cliente AS c
    INNER JOIN calendario AS cal
        ON cal.corte_mes >= c.primera_aparicion
    LEFT JOIN historia_cliente AS hc
        ON hc.corte_mes = cal.corte_mes
    WHERE hc.identificacion IS NOT NULL
       OR c.fecha_retiro IS NULL
       OR cal.corte_mes <= c.fecha_retiro
),
clasificada AS (
    SELECT
        s.*,
        CASE WHEN s.es_imputado = 1 THEN 'N0' ELSE n.nivel END AS nivel,
        CAST(strftime('%Y', s.corte_mes) AS INTEGER) * 12
            + CAST(strftime('%m', s.corte_mes) AS INTEGER) AS indice_mes
    FROM serie AS s
    LEFT JOIN ref_niveles_deuda AS n
        ON  s.saldo >= n.limite_inferior
        AND (n.limite_superior IS NULL OR s.saldo < n.limite_superior)
),
islas AS (
    SELECT
        clasificada.*,
        indice_mes - ROW_NUMBER() OVER (PARTITION BY nivel ORDER BY corte_mes) AS id_racha
    FROM clasificada
)
SELECT
    corte_mes,
    saldo,
    nivel,
    es_imputado,
    fecha_retiro,
    COUNT(*)     OVER (PARTITION BY nivel, id_racha)                      AS largo_racha,   -- largo de la racha del mes
    ROW_NUMBER() OVER (PARTITION BY nivel, id_racha ORDER BY corte_mes)   AS mes_en_racha   -- posicion dentro de ella
FROM islas
ORDER BY corte_mes;
