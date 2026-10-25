"""
Pruebas del ejercicio 3.  Correr desde ejercicio_3_rachas:  python -m unittest -v

Hay dos tipos:
- casos chiquitos hechos a mano, uno por regla, que corren los mismos .sql
  del proceso real sobre una base en memoria
- una reconciliacion con el Excel real: la misma logica escrita en Python
  "a lo bruto" (mes a mes, sin gaps and islands) contra lo que da el SQL.
  Si dos implementaciones distintas dan igual, es dificil que las dos esten mal
"""

import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import rachas


def month_end(year, month):
    following = date(year + month // 12, month % 12 + 1, 1)
    return (following - timedelta(days=1)).isoformat()


def build_db(historia, retiros=()):
    """Base en memoria con los scripts reales.
    historia = [(identificacion, corte_mes, saldo)], retiros = [(identificacion, fecha_retiro)]"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    rachas.run_sql_file(conn, "01_ddl.sql")
    conn.executemany(
        "INSERT INTO stg_historia (fila_origen, identificacion, corte_mes, saldo) VALUES (?, ?, ?, ?)",
        [(i, *row) for i, row in enumerate(historia, start=2)],
    )
    conn.executemany(
        "INSERT INTO stg_retiros (fila_origen, identificacion, fecha_retiro) VALUES (?, ?, ?)",
        [(i, *row) for i, row in enumerate(retiros, start=2)],
    )
    rachas.run_sql_file(conn, "02_calidad_datos.sql")
    rachas.run_sql_file(conn, "03_limpieza.sql")
    return conn


def as_tuples(rows):
    return [tuple(row) for row in rows]


# ids de 17 caracteres para los casos de prueba
CLIENTE_A = "AAAAAAAAAAAAAAAA1"
CLIENTE_B = "BBBBBBBBBBBBBBBB2"

N0, N1, N2, N3, N4 = 100_000, 500_000, 2_000_000, 4_000_000, 6_000_000


def serie(cliente, year, month, saldos):
    """Meses seguidos desde (year, month). None = ese mes el cliente no aparece."""
    rows = []
    for offset, saldo in enumerate(saldos):
        y, m = divmod(month - 1 + offset, 12)
        if saldo is not None:
            rows.append((cliente, month_end(year + y, m + 1), saldo))
    return rows


class NivelesTest(unittest.TestCase):
    def test_limites_de_los_rangos(self):
        # el valor exacto del limite ya es del nivel de arriba (300.000 es N1)
        limites = [0, 299_999, 300_000, 999_999, 1_000_000, 2_999_999,
                   3_000_000, 4_999_999, 5_000_000, 50_000_000]
        esperados = ["N0", "N0", "N1", "N1", "N2", "N2", "N3", "N3", "N4", "N4"]
        conn = build_db([])
        for saldo, esperado in zip(limites, esperados):
            nivel = conn.execute(
                """
                SELECT nivel FROM ref_niveles_deuda
                WHERE ? >= limite_inferior
                  AND (limite_superior IS NULL OR ? < limite_superior)
                """,
                (saldo, saldo),
            ).fetchone()[0]
            self.assertEqual(nivel, esperado, f"saldo {saldo}")


class RachasTest(unittest.TestCase):
    def test_racha_simple(self):
        conn = build_db(serie(CLIENTE_A, 2024, 1, [N2, N2, N2, N1]))
        self.assertEqual(
            as_tuples(rachas.query_rachas(conn, "2024-04-30", 3)),
            [(CLIENTE_A, 3, "2024-03-31", "N2")],
        )

    def test_filtra_rachas_menores_a_n(self):
        conn = build_db(serie(CLIENTE_A, 2024, 1, [N2, N2, N1, N1]))
        self.assertEqual(rachas.query_rachas(conn, "2024-04-30", 3), [])

    def test_mes_faltante_se_imputa_como_n0(self):
        # ene N0, feb no aparece (cuenta como N0), mar N0 -> 3 meses en N0
        conn = build_db(serie(CLIENTE_A, 2024, 1, [N0, None, N0, N3]))
        self.assertEqual(
            as_tuples(rachas.query_rachas(conn, "2024-04-30", 3)),
            [(CLIENTE_A, 3, "2024-03-31", "N0")],
        )

    def test_mes_faltante_corta_racha_de_otro_nivel(self):
        # el hueco de febrero es N0, entonces el N4 no llega a 3 seguidos
        conn = build_db(serie(CLIENTE_A, 2024, 1, [N4, None, N4, N4]))
        self.assertEqual(
            as_tuples(rachas.query_rachas(conn, "2024-04-30", 2)),
            [(CLIENTE_A, 2, "2024-04-30", "N4")],
        )

    def test_no_imputa_antes_de_la_primera_aparicion(self):
        # B aparece en marzo, enero y febrero no se le imputan
        historia = serie(CLIENTE_A, 2024, 1, [N1, N1, N1, N1]) + serie(CLIENTE_B, 2024, 3, [N0, N0])
        conn = build_db(historia)
        resultado = dict((r["identificacion"], r["racha"]) for r in rachas.query_rachas(conn, "2024-04-30", 1))
        self.assertEqual(resultado[CLIENTE_B], 2)

    def test_imputa_hasta_el_ultimo_corte_disponible(self):
        # B deja de aparecer en feb pero A tiene datos hasta abril,
        # entonces feb, mar y abr de B son N0
        historia = serie(CLIENTE_A, 2024, 1, [N1, N1, N1, N1]) + serie(CLIENTE_B, 2024, 1, [N3])
        conn = build_db(historia)
        resultado = {r["identificacion"]: tuple(r) for r in rachas.query_rachas(conn, "2024-04-30", 3)}
        self.assertEqual(resultado[CLIENTE_B], (CLIENTE_B, 3, "2024-04-30", "N0"))

    def test_no_imputa_despues_del_retiro(self):
        # retiro el 10 de marzo -> el corte del 31 de marzo ya es posterior,
        # marzo y abril no existen para A y su racha N0 queda de 1
        historia = serie(CLIENTE_A, 2024, 1, [N3, N0, None, None]) + serie(CLIENTE_B, 2024, 1, [N1] * 4)
        conn = build_db(historia, retiros=[(CLIENTE_A, "2024-03-10")])
        resultado = {r["identificacion"]: tuple(r) for r in rachas.query_rachas(conn, "2024-04-30", 1)}
        self.assertEqual(resultado[CLIENTE_A], (CLIENTE_A, 1, "2024-02-29", "N0"))

    def test_retiro_en_el_mismo_dia_del_corte_si_imputa(self):
        # "superior a la fecha de retiro" es estricto: retiro el mismo dia del
        # corte -> ese mes todavia se imputa
        historia = serie(CLIENTE_A, 2024, 1, [N0, None]) + serie(CLIENTE_B, 2024, 1, [N1, N1])
        conn = build_db(historia, retiros=[(CLIENTE_A, "2024-02-29")])
        resultado = {r["identificacion"]: tuple(r) for r in rachas.query_rachas(conn, "2024-02-29", 2)}
        self.assertEqual(resultado[CLIENTE_A], (CLIENTE_A, 2, "2024-02-29", "N0"))

    def test_hueco_despues_del_retiro_corta_la_racha(self):
        # los saldos despues del retiro se quedan, pero un hueco despues del
        # retiro no se imputa y parte la racha
        historia = serie(CLIENTE_A, 2024, 1, [N2, N2, None, N2, N2])
        conn = build_db(historia, retiros=[(CLIENTE_A, "2024-01-15")])
        self.assertEqual(
            as_tuples(rachas.query_rachas(conn, "2024-05-31", 1)),
            [(CLIENTE_A, 2, "2024-05-31", "N2")],
        )

    def test_empate_en_longitud_gana_la_mas_reciente(self):
        conn = build_db(serie(CLIENTE_A, 2024, 1, [N4, N4, N4, N1, N2, N2, N2]))
        self.assertEqual(
            as_tuples(rachas.query_rachas(conn, "2024-07-31", 3)),
            [(CLIENTE_A, 3, "2024-07-31", "N2")],
        )

    def test_gana_la_racha_mas_larga_aunque_sea_antigua(self):
        conn = build_db(serie(CLIENTE_A, 2024, 1, [N3, N3, N3, N3, N1, N2, N2, N2]))
        self.assertEqual(
            as_tuples(rachas.query_rachas(conn, "2024-08-31", 3)),
            [(CLIENTE_A, 4, "2024-04-30", "N3")],
        )

    def test_fecha_base_ignora_datos_posteriores(self):
        conn = build_db(serie(CLIENTE_A, 2024, 1, [N1, N1, N1, N4, N4, N4, N4]))
        self.assertEqual(
            as_tuples(rachas.query_rachas(conn, "2024-03-31", 3)),
            [(CLIENTE_A, 3, "2024-03-31", "N1")],
        )

    def test_fecha_base_a_mitad_de_mes_usa_el_corte_anterior(self):
        # parados el 15 de abril, el corte de abril todavia no existe
        conn = build_db(serie(CLIENTE_A, 2024, 1, [N1, N1, N1, N1]))
        self.assertEqual(
            as_tuples(rachas.query_rachas(conn, "2024-04-15", 1)),
            [(CLIENTE_A, 3, "2024-03-31", "N1")],
        )

    def test_fecha_base_anterior_a_todos_los_datos(self):
        conn = build_db(serie(CLIENTE_A, 2024, 1, [N1, N1]))
        self.assertEqual(rachas.query_rachas(conn, "2023-06-30", 1), [])

    def test_racha_cruza_cambio_de_anio(self):
        conn = build_db(serie(CLIENTE_A, 2023, 11, [N2, N2, N2, N2]))
        self.assertEqual(
            as_tuples(rachas.query_rachas(conn, "2024-02-29", 4)),
            [(CLIENTE_A, 4, "2024-02-29", "N2")],
        )


class CalidadDatosTest(unittest.TestCase):
    def test_duplicado_con_saldo_distinto_conserva_el_menor(self):
        historia = [(CLIENTE_A, "2024-01-31", 571_481), (CLIENTE_A, "2024-01-31", 1_142_962)]
        conn = build_db(historia)
        self.assertEqual(conn.execute("SELECT saldo FROM historia").fetchall()[0][0], 571_481)
        reglas = [r[0] for r in conn.execute("SELECT regla FROM dq_incidencias")]
        self.assertEqual(reglas, ["H7_DUPLICADO_SALDO_DIFERENTE"])

    def test_rechaza_registros_invalidos(self):
        historia = [
            ("CORTO", "2024-01-31", 100),                 # id inválido
            (CLIENTE_A, "31/01/2024", 100),               # fecha inválida
            (CLIENTE_A, "2024-02-30", 100),               # fecha imposible
            (CLIENTE_A, "2024-03-31", -5),                # saldo negativo
            (CLIENTE_A, "2024-04-30", "abc"),             # saldo no numérico
            (CLIENTE_A, "2024-05-31", 100),               # válido
        ]
        conn = build_db(historia)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM historia").fetchone()[0], 1)
        reglas = sorted(r[0] for r in conn.execute("SELECT regla FROM dq_incidencias"))
        self.assertEqual(
            reglas,
            ["H1_IDENTIFICACION_INVALIDA", "H2_CORTE_MES_INVALIDO", "H2_CORTE_MES_INVALIDO",
             "H3_SALDO_INVALIDO", "H3_SALDO_INVALIDO"],
        )

    def test_normaliza_identificacion_y_fin_de_mes(self):
        conn = build_db([(" aaaaaaaaaaaaaaaa1 ", "2024-01-15", 100)])
        self.assertEqual(
            tuple(conn.execute("SELECT identificacion, corte_mes FROM historia").fetchone()),
            (CLIENTE_A, "2024-01-31"),
        )


class ReconciliacionExcelTest(unittest.TestCase):
    """SQL vs la misma logica hecha en Python puro, sobre el Excel real."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db_path = Path(cls.tmp.name) / "rachas_test.db"
        rachas.build_database(rachas.DEFAULT_EXCEL, db_path)
        cls.conn = rachas.connect(db_path)
        cls.historia = cls.conn.execute("SELECT identificacion, corte_mes, saldo FROM historia").fetchall()
        cls.retiros = dict(cls.conn.execute("SELECT identificacion, fecha_retiro FROM retiros").fetchall())
        cls.niveles = cls.conn.execute(
            "SELECT nivel, limite_inferior, limite_superior FROM ref_niveles_deuda"
        ).fetchall()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def _nivel(self, saldo):
        for nivel, inferior, superior in self.niveles:
            if saldo >= inferior and (superior is None or saldo < superior):
                return nivel
        raise ValueError(saldo)

    def referencia(self, fecha_base, n):
        """Recorre cada cliente mes a mes y arma las rachas a mano."""
        base = date.fromisoformat(fecha_base)
        ultimo_corte = (base + timedelta(days=1)).replace(day=1) - timedelta(days=1)
        registros = [r for r in self.historia if r[1] <= ultimo_corte.isoformat()]
        if not registros:
            return []

        def indice(corte):
            return int(corte[:4]) * 12 + int(corte[5:7])

        def corte_de(indice_mes):
            year, month = divmod(indice_mes - 1, 12)
            return month_end(year, month + 1)

        ultimo = max(indice(r[1]) for r in registros)
        por_cliente = {}
        for cliente, corte, saldo in registros:
            por_cliente.setdefault(cliente, {})[indice(corte)] = saldo

        resultado = []
        for cliente, meses in por_cliente.items():
            retiro = self.retiros.get(cliente)
            rachas_cliente = []  # [largo, nivel, indice_fin]
            for mes in range(min(meses), ultimo + 1):
                if mes in meses:
                    nivel = self._nivel(meses[mes])
                elif retiro is None or corte_de(mes) <= retiro:
                    nivel = "N0"
                else:
                    continue  # despues del retiro, el mes no existe
                actual = rachas_cliente[-1] if rachas_cliente else None
                if actual and actual[1] == nivel and actual[2] == mes - 1:
                    actual[0] += 1
                    actual[2] = mes
                else:
                    rachas_cliente.append([1, nivel, mes])

            candidatas = [r for r in rachas_cliente if r[0] >= n]
            if candidatas:
                largo, nivel, fin = max(candidatas, key=lambda r: (r[0], r[2]))
                resultado.append((cliente, largo, corte_de(fin), nivel))
        return sorted(resultado)

    def test_sql_coincide_con_referencia(self):
        fechas = ["2024-12-31", "2024-12-30", "2024-06-15", "2023-11-30", "2023-03-01", "2025-05-31"]
        for fecha_base in fechas:
            for n in (1, 2, 3, 4, 6):
                with self.subTest(fecha_base=fecha_base, n=n):
                    sql = as_tuples(rachas.query_rachas(self.conn, fecha_base, n))
                    self.assertEqual(sql, self.referencia(fecha_base, n))

    def test_incidencias_conocidas_del_archivo(self):
        reglas = dict(self.conn.execute(
            "SELECT regla, COUNT(*) FROM dq_incidencias GROUP BY regla"
        ).fetchall())
        self.assertEqual(reglas["H6_DUPLICADO_EXACTO"], 1)
        self.assertEqual(reglas["H7_DUPLICADO_SALDO_DIFERENTE"], 1)
        self.assertEqual(reglas["R1_IDENTIFICACION_INVALIDA"], 1)


if __name__ == "__main__":
    unittest.main()
