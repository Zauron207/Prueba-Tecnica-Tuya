"""Pruebas de la normalizacion.  python -m unittest -v"""

import unittest

from telefonos import EstadoTelefono, TipoTelefono, normalizar_telefono


class NormalizacionTest(unittest.TestCase):
    def assertNormaliza(self, valor, e164, tipo, estado, **kwargs):
        resultado = normalizar_telefono(valor, **kwargs)
        self.assertEqual((resultado.e164, resultado.tipo, resultado.estado), (e164, tipo, estado), valor)

    def test_moviles_en_distintas_presentaciones(self):
        for valor in ("3001234568", "300 123 4568", "(300) 123-4568", "+57 300 123 4568",
                      "573001234568", "00573001234568", "3001234568.0"):
            with self.subTest(valor=valor):
                self.assertNormaliza(valor, "+573001234568", TipoTelefono.MOVIL, EstadoTelefono.VALIDO)

    def test_fijo_formato_vigente(self):
        self.assertNormaliza("601 345 6789", "+576013456789", TipoTelefono.FIJO, EstadoTelefono.VALIDO)
        self.assertNormaliza("+57 604 444 1234", "+576044441234", TipoTelefono.FIJO, EstadoTelefono.VALIDO)

    def test_fijo_formato_antiguo_con_indicativo(self):
        # asi se marcaba en Medellin antes del 2021
        self.assertNormaliza("(4) 444 1234", "+576044441234", TipoTelefono.FIJO, EstadoTelefono.CORREGIDO)

    def test_fijo_de_7_digitos_depende_de_la_region(self):
        self.assertNormaliza("444 1234", None, TipoTelefono.FIJO, EstadoTelefono.INVALIDO)
        self.assertNormaliza("444 1234", "+576044441234", TipoTelefono.FIJO, EstadoTelefono.CORREGIDO,
                             region_cliente="4")

    def test_numeros_de_relleno(self):
        for valor in ("3000000000", "3111111111", "3001234567", "6011111111"):
            with self.subTest(valor=valor):
                self.assertEqual(normalizar_telefono(valor).estado, EstadoTelefono.SOSPECHOSO)
                self.assertFalse(normalizar_telefono(valor).es_contactable)

    def test_invalidos(self):
        for valor in (None, "", "   ", "sin teléfono", "12345", "3001234", "2001234567",
                      "6031234567", "30012345678", "+1 305 555 0100"):
            with self.subTest(valor=valor):
                self.assertEqual(normalizar_telefono(valor).estado, EstadoTelefono.INVALIDO)


if __name__ == "__main__":
    unittest.main()
