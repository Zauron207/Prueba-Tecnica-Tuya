-- 04_rachas.sql
-- Racha mas larga de cada cliente dentro de un mismo nivel de deuda.
--
-- Parametros:
--   :fecha_base -> fecha en la que "nos paramos" (YYYY-MM-DD)
--   :n          -> minimo de meses para que una racha cuente
--
-- Para correrlo:
--   python rachas.py consultar --fecha-base 2024-12-31 --n 3
-- o desde la CLI de sqlite3:
--   .param set :fecha_base '2024-12-31'
--   .param set :n 3
--   .read sql/04_rachas.sql
-- (DB Browser for SQLite pide los parametros solo)
--
-- Supuestos, mas detalle en el README:
--   - solo cuentan cortes cerrados a la fecha_base. Si es 15 de junio, el ultimo
--     corte es 31 de mayo
--   - el calendario llega hasta el ultimo corte que hay en los datos. No imputo
--     meses de los que todavia no hay info de nadie
--   - mes faltante despues de la primera aparicion = N0, excepto si el corte es
--     posterior al retiro. En ese caso el mes no existe y la racha se corta

WITH
parametros AS (
    SELECT
        DATE(:fecha_base)                                      AS fecha_base,
        CAST(:n AS INTEGER)                                    AS n,
        -- ultimo fin de mes <= fecha_base
        -- 2024-12-31 -> 2024-12-31 / 2024-12-15 -> 2024-11-30
        DATE(:fecha_base, '+1 day', 'start of month', '-1 day') AS ultimo_corte_cerrado
),

limites_calendario AS (
    SELECT
        MIN(h.corte_mes) AS primer_corte,
        MAX(h.corte_mes) AS ultimo_corte
    FROM historia AS h
    CROSS JOIN parametros AS p
    WHERE h.corte_mes <= p.ultimo_corte_cerrado
),

-- Genero todos los fines de mes del rango en vez de sacar los cortes de la
-- tabla. Si hubiera un mes sin datos de nadie, igual tiene que estar, si no dos
-- meses separados se verian seguidos.
-- El '+1 day' / '-1 day' es porque 31-ene '+1 month' en SQLite da 3 de marzo.
calendario (corte_mes) AS (
    SELECT primer_corte
    FROM limites_calendario
    WHERE primer_corte IS NOT NULL

    UNION ALL

    SELECT DATE(c.corte_mes, '+1 day', '+1 month', '-1 day')
    FROM calendario AS c
    CROSS JOIN limites_calendario AS l
    WHERE c.corte_mes < l.ultimo_corte
),

historia_vigente AS (
    SELECT
        h.identificacion,
        h.corte_mes,
        h.saldo
    FROM historia AS h
    CROSS JOIN limites_calendario AS l
    WHERE h.corte_mes <= l.ultimo_corte
),

-- primera aparicion y retiro de cada cliente.
-- Si el retiro es despues de la fecha_base no pasa nada: ningun corte del
-- calendario va a ser mayor que el, o sea que a esa fecha "todavia no se retiro".
clientes AS (
    SELECT
        hv.identificacion,
        MIN(hv.corte_mes) AS primera_aparicion,
        r.fecha_retiro
    FROM historia_vigente AS hv
    LEFT JOIN retiros AS r
        ON r.identificacion = hv.identificacion
    GROUP BY hv.identificacion, r.fecha_retiro
),

-- todos los meses de cada cliente desde que aparece. Los que no tienen
-- registro quedan marcados como imputados.
serie_mensual AS (
    SELECT
        c.identificacion,
        cal.corte_mes,
        hv.saldo,
        CASE WHEN hv.identificacion IS NULL THEN 1 ELSE 0 END AS es_imputado
    FROM clientes AS c
    INNER JOIN calendario AS cal
        ON cal.corte_mes >= c.primera_aparicion
    LEFT JOIN historia_vigente AS hv
        ON  hv.identificacion = c.identificacion
        AND hv.corte_mes      = cal.corte_mes
    WHERE hv.identificacion IS NOT NULL       -- tiene dato
       OR c.fecha_retiro IS NULL              -- no tiene dato y no se ha retirado
       OR cal.corte_mes <= c.fecha_retiro     -- no tiene dato pero es antes del retiro
),

serie_clasificada AS (
    SELECT
        s.identificacion,
        s.corte_mes,
        CASE WHEN s.es_imputado = 1 THEN 'N0' ELSE n.nivel END AS nivel,
        -- mes como numero (anio*12 + mes) para poder restar meses como enteros
        CAST(strftime('%Y', s.corte_mes) AS INTEGER) * 12
            + CAST(strftime('%m', s.corte_mes) AS INTEGER) AS indice_mes
    FROM serie_mensual AS s
    LEFT JOIN ref_niveles_deuda AS n
        ON  s.saldo >= n.limite_inferior
        AND (n.limite_superior IS NULL OR s.saldo < n.limite_superior)
),

-- gaps and islands:
-- por cliente y nivel, si los meses son seguidos indice_mes y ROW_NUMBER suben
-- de a 1 los dos, entonces la resta da lo mismo. Cuando hay un salto (otro
-- nivel en medio, o un mes despues del retiro que no se imputo) la resta cambia.
-- Esa resta es el id de la racha.
islas AS (
    SELECT
        identificacion,
        nivel,
        corte_mes,
        indice_mes
            - ROW_NUMBER() OVER (
                PARTITION BY identificacion, nivel
                ORDER BY corte_mes
            ) AS id_racha
    FROM serie_clasificada
),

rachas AS (
    SELECT
        identificacion,
        nivel,
        COUNT(*)       AS racha,
        MIN(corte_mes) AS fecha_inicio,
        MAX(corte_mes) AS fecha_fin
    FROM islas
    GROUP BY identificacion, nivel, id_racha
),

-- racha >= n, la mas larga, y si empatan la que termino mas cerca de la fecha_base.
-- No hay empate en (racha, fecha_fin) porque en un mes el cliente tiene un solo
-- nivel, entonces el ROW_NUMBER siempre da el mismo resultado.
rachas_priorizadas AS (
    SELECT
        r.identificacion,
        r.racha,
        r.fecha_fin,
        r.nivel,
        ROW_NUMBER() OVER (
            PARTITION BY r.identificacion
            ORDER BY r.racha DESC, r.fecha_fin DESC
        ) AS prioridad
    FROM rachas AS r
    CROSS JOIN parametros AS p
    WHERE r.racha >= p.n
)

SELECT
    identificacion,
    racha,
    fecha_fin,
    nivel
FROM rachas_priorizadas
WHERE prioridad = 1
ORDER BY identificacion;
