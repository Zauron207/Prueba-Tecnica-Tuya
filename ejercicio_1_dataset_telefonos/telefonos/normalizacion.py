"""
Normalizacion y validacion de telefonos colombianos.

Es la regla principal de la capa silver (ver README). La deje como funcion pura
y sin dependencias para poder probarla en el CI y usarla igual desde Spark
(como UDF) o desde un batch normal.

Numeracion vigente (cambio de sept. 2021):
  movil: 10 digitos, empieza por 3        -> 3XX XXX XXXX
  fijo:  60 + region + 7 digitos          -> 60R XXX XXXX
         R: 1 Bogota/Cundinamarca, 2 Valle/Cauca/Nariño, 4 Antioquia/Cordoba/Choco,
            5 Caribe, 6 Eje Cafetero, 7 Santanderes/Arauca, 8 resto
En formato internacional (E.164) se le pone +57 adelante.
"""

import re
from dataclasses import dataclass
from enum import Enum

INDICATIVO_PAIS = "57"
REGIONES_FIJO = frozenset("1245678")

_MOVIL = re.compile(r"3[0-5]\d{8}")
_FIJO = re.compile(r"60[1245678]\d{7}")


class TipoTelefono(str, Enum):
    MOVIL = "MOVIL"
    FIJO = "FIJO"
    DESCONOCIDO = "DESCONOCIDO"


class EstadoTelefono(str, Enum):
    VALIDO = "VALIDO"            # bien como llego (o solo cambiaron espacios, guiones...)
    CORREGIDO = "CORREGIDO"      # se pudo pasar al formato nuevo (ej. fijo viejo)
    SOSPECHOSO = "SOSPECHOSO"    # formato bien pero tiene pinta de numero de relleno
    INVALIDO = "INVALIDO"        # no sirve para contactar


@dataclass(frozen=True)
class ResultadoTelefono:
    original: str | None
    e164: str | None             # +57XXXXXXXXXX si se pudo normalizar
    tipo: TipoTelefono
    estado: EstadoTelefono
    motivo: str | None = None

    @property
    def es_contactable(self) -> bool:
        return self.estado in (EstadoTelefono.VALIDO, EstadoTelefono.CORREGIDO)


def _solo_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


def _quitar_indicativo_pais(digitos: str) -> str:
    """Quita el +57 / 0057 / 57 cuando sobra delante de los 10 digitos."""
    for prefijo in ("00" + INDICATIVO_PAIS, INDICATIVO_PAIS):
        if digitos.startswith(prefijo) and len(digitos) == len(prefijo) + 10:
            return digitos[len(prefijo):]
    return digitos


def _es_relleno(numero: str) -> bool:
    """Los tipicos de relleno: 3000000000, 3111111111, 3001234567..."""
    abonado = numero[3:]  # los 7 digitos despues del prefijo
    if len(set(abonado)) == 1:
        return True
    return abonado in ("1234567", "7654321", "0123456")


def normalizar_telefono(valor: str | None, region_cliente: str | None = None) -> ResultadoTelefono:
    """Normaliza a E.164 y clasifica el numero.

    region_cliente = digito de region (1-8) segun la ciudad del cliente. Solo se
    usa para completar fijos viejos de 7 digitos que llegan sin indicativo.
    """
    if valor is None or not str(valor).strip():
        return ResultadoTelefono(valor, None, TipoTelefono.DESCONOCIDO, EstadoTelefono.INVALIDO, "vacío")

    texto = str(valor).strip()
    # Excel a veces convierte el telefono a numero y le pega ".0"
    if re.fullmatch(r"\d+\.0", texto):
        texto = texto[:-2]

    digitos = _quitar_indicativo_pais(_solo_digitos(texto))
    if not digitos:
        return ResultadoTelefono(valor, None, TipoTelefono.DESCONOCIDO, EstadoTelefono.INVALIDO, "sin dígitos")

    estado = EstadoTelefono.VALIDO
    motivo = None

    # fijo como se marcaba antes de 2021: indicativo + 7 digitos, ej (4) 444 1234
    if len(digitos) == 8 and digitos[0] in REGIONES_FIJO:
        digitos = "60" + digitos
        estado, motivo = EstadoTelefono.CORREGIDO, "fijo con formato anterior a 2021"
    # fijo de 7 digitos sin indicativo: solo se completa si sabemos la region
    elif len(digitos) == 7:
        if region_cliente not in REGIONES_FIJO:
            return ResultadoTelefono(
                valor, None, TipoTelefono.FIJO, EstadoTelefono.INVALIDO,
                "fijo de 7 dígitos sin región conocida",
            )
        digitos = "60" + region_cliente + digitos
        estado, motivo = EstadoTelefono.CORREGIDO, "fijo completado con la región del cliente"

    if _MOVIL.fullmatch(digitos):
        tipo = TipoTelefono.MOVIL
    elif _FIJO.fullmatch(digitos):
        tipo = TipoTelefono.FIJO
    else:
        return ResultadoTelefono(
            valor, None, TipoTelefono.DESCONOCIDO, EstadoTelefono.INVALIDO,
            f"formato no reconocido ({len(digitos)} dígitos)",
        )

    e164 = f"+{INDICATIVO_PAIS}{digitos}"
    if _es_relleno(digitos):
        return ResultadoTelefono(valor, e164, tipo, EstadoTelefono.SOSPECHOSO, "patrón de número de relleno")
    return ResultadoTelefono(valor, e164, tipo, estado, motivo)
