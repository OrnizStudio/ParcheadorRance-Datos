"""Canales: quién es miembro de cada canal y qué puede cambiar en `canales/<canal>/` (docs/canales.md del parcheador).

Fase A: hay un solo canal, `canales/ornizen/` (el oficial). Los roles salen de su `miembros.json`, por el id numérico
de la cuenta de GitHub (una cuenta se puede renombrar y otra quedarse con el nombre viejo), y siempre de `main`:
añadirse en la propia propuesta no da permiso para esa propuesta.

Lo que hay aquí no habla con GitHub ni con git: recibe textos y devuelve motivos de rechazo, igual que `comprobar`
de `permisos.py`.
"""
from __future__ import annotations

import datetime
import json
import re
import hashlib
import pathlib
import unicodedata
from dataclasses import dataclass, field

CARPETA_CANALES = "canales/"
CANAL_OFICIAL = "ornizen"
ID_CANAL = re.compile(r"^[a-z0-9_]{3,20}\Z")
# @ que ningún canal puede tener, ni siquiera creado por el Dueño: `programa` es el prefijo de las ramas de la zona
# PROGRAMA de Modo equipo (`programa/…`), y la app descarta un canal con ese @ (LectorCanalesCuenta.IdValido). Solo el
# @ exacto: un nombre como «Programa de traducción» sí vale.
ARROBAS_DEL_PROGRAMA = ("programa",)
CUENTA_GITHUB = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")
HASH_VALIDO = re.compile(r"^blake3:[0-9a-f]{64}\Z")
# «.» y «..» no son repositorios (la app usa esta lista como lista blanca de descargas). Todas las expresiones acaban
# en `\Z` y no en `$`: `$` deja pasar un salto de línea al final («a/b\n»).
REPOSITORIO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/(?!\.\.?\Z)[A-Za-z0-9._-]{1,100}\Z")
RUTA_SEGURA = re.compile(r"^[a-z0-9._/-]+\Z")
# Los repositorios de esta organización son del programa: solo los declara el canal oficial (sin distinguir mayúsculas).
ORGANIZACION_OFICIAL = "ornizstudio"
EXTENSIONES_LOGO = (".png", ".webp", ".jpg", ".jpeg")
# El id de un juego (el de `particion.ID_VALIDO`, que no se importa aquí para no traer el catálogo).
ID_JUEGO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?\Z")


def tipo_de_imagen(datos: bytes):
    """«png», «webp» o «jpeg» según los primeros bytes (no según el nombre), o None."""
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if datos.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(datos) >= 12 and datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "webp"
    return None


TIPO_POR_EXTENSION = {".png": "png", ".webp": "webp", ".jpg": "jpeg", ".jpeg": "jpeg"}

# Topes (docs/canales.md §7.7). Se miran con el tamaño de git, antes de leer nada.
TOPES = {"canal.json": 16 * 1024, "miembros.json": 128 * 1024, "lista-negra.json": 256 * 1024, "ficha.json": 16 * 1024}
TOPE_LOGO = 512 * 1024
# Consultas a GitHub (el nombre de una cuenta por su id, su rol en el canal oficial) que una propuesta puede provocar.
# Cada una gasta cuota del token del robot: sin tope, una propuesta con cientos de filas lo dejaría sin cuota y sin
# poder comprobar ninguna otra (tercera revisión, N2). El Dueño tiene más margen (migraciones de una vez).
# Cada fila puede costar hasta 4 (el nombre y el rol de la cuenta, y los de quien puso el veto): el tope de consultas
# cubre siempre el máximo de filas, para que nunca salga «demasiadas cuentas» por debajo de él.
TOPE_CONSULTAS = 4 * 20 + 10
TOPE_CONSULTAS_DUENO = 300
# Filas de `miembros.json` o de la lista negra que una propuesta puede añadir o cambiar de cuenta de una vez (sin
# contar al Dueño). Se mira antes de consultar nada.
TOPE_FILAS_CON_CUENTA = 20
TOPE_ARCHIVOS_PROPUESTA = 300
TOPE_BYTES_PROPUESTA = 20 * 1024 * 1024
PROFUNDIDAD_MAXIMA = 32

MAX_MIEMBROS_ACTIVOS = 500
MAX_INVITACIONES = 100
MAX_ETIQUETAS_MIEMBRO = 5
LARGO_ETIQUETA_MIEMBRO = 24
MAX_LISTA_NEGRA = 5000
LARGO_MOTIVO = 300
LARGO_NOMBRE = 60
LARGO_DESCRIPCION = 300
MAX_ENLACES = 8
MAX_PAQUETES = 3

# Los roles de un canal. Los números son los de `permisos.Rol` (se importan desde allí para no duplicarlos).
TEXTO_ROL = ("colaborador", "editor", "administrador", "propietario")


# ───────────────────────────────────────── JSON estricto ─────────────────────────────────────────

class JsonMalo(ValueError):
    """El archivo no se puede aceptar tal cual: el texto ya lleva el archivo y, si se sabe, la línea."""


def _sin_repetidas(pares):
    vistas = {}
    for clave, valor in pares:
        if clave in vistas:
            raise JsonMalo(f"la clave `{clave}` está repetida")
        vistas[clave] = valor
    return vistas


def _sin_nan(valor):
    raise JsonMalo(f"`{valor}` no es un número válido")


def _decimal_finito(texto):
    valor = float(texto)
    if valor != valor or valor in (float("inf"), float("-inf")):
        raise JsonMalo(f"`{texto[:20]}` no es un número válido")
    return valor


def _entero_razonable(texto):
    # Python no convierte enteros de más de 4300 cifras (ValueError); aquí ni hace falta acercarse.
    if len(texto.lstrip("-")) > 30:
        raise JsonMalo(f"un número tiene {len(texto)} cifras")
    return int(texto)


def _profundidad(texto: str) -> int:
    """La anidación más honda de `[` y `{` fuera de las cadenas, sin parsear (un JSON hondísimo tumbaría a Python)."""
    hondo = maximo = 0
    en_cadena = escapado = False
    for c in texto:
        if en_cadena:
            if escapado:
                escapado = False
            elif c == "\\":
                escapado = True
            elif c == '"':
                en_cadena = False
        elif c == '"':
            en_cadena = True
        elif c in "[{":
            hondo += 1
            if hondo > maximo:
                maximo = hondo
                if maximo > PROFUNDIDAD_MAXIMA:
                    return maximo
        elif c in "]}":
            hondo -= 1
    return maximo


def leer_json_estricto(datos: bytes, ruta: str, tope: int | None = None):
    """Bytes de un archivo → objeto. UTF-8 estricto sin BOM, sin claves repetidas, sin NaN, profundidad ≤ 32.

    Lanza `JsonMalo` con un texto para el comentario del robot.
    """
    if tope is not None and len(datos) > tope:
        raise JsonMalo(f"`{ruta}` pesa {len(datos)} bytes y el máximo son {tope}.")
    if datos.startswith(b"\xef\xbb\xbf"):
        raise JsonMalo(f"`{ruta}` empieza con una marca BOM: guárdalo como UTF-8 sin BOM.")
    try:
        texto = datos.decode("utf-8", errors="strict")
    except UnicodeDecodeError as e:
        raise JsonMalo(f"`{ruta}` no es texto UTF-8 válido (byte {e.start}).")
    if _profundidad(texto) > PROFUNDIDAD_MAXIMA:
        raise JsonMalo(f"`{ruta}` está anidado a más de {PROFUNDIDAD_MAXIMA} niveles.")
    try:
        return json.loads(texto, object_pairs_hook=_sin_repetidas, parse_constant=_sin_nan,
                          parse_float=_decimal_finito, parse_int=_entero_razonable)
    except JsonMalo as e:
        raise JsonMalo(f"`{ruta}`: {e}.")
    except json.JSONDecodeError as e:
        raise JsonMalo(f"`{ruta}` no es un JSON válido (línea {e.lineno}, columna {e.colno}): {e.msg}.")
    except RecursionError:
        raise JsonMalo(f"`{ruta}` está anidado demasiado hondo.")
    except (ValueError, OverflowError, MemoryError) as e:
        # Cualquier otra cosa que el parser no digiera: un rechazo con comentario, nunca que el robot se caiga.
        raise JsonMalo(f"`{ruta}` no se puede leer ({type(e).__name__}).")


# ───────────────────────────────────────── Utilidades ─────────────────────────────────────────

def _es_entero(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _es_id(valor) -> bool:
    return _es_entero(valor) and 0 < valor < 2 ** 53


def _es_fecha(valor) -> bool:
    if not isinstance(valor, str) or not FECHA.match(valor):
        return False
    try:
        datetime.date.fromisoformat(valor)
        return True
    except ValueError:
        return False


def _campos_desconocidos(donde: str, objeto: dict, conocidos) -> list:
    return [f"{donde}: el campo `{c}` no existe (solo valen {', '.join(f'`{k}`' for k in conocidos)})."
            for c in objeto if c not in conocidos]


# Invisibles, de control y de dirección: dejan escribir dos nombres que se ven iguales.
_INVISIBLES = set("​‌‍‎‏⁠⁡⁢⁣⁤﻿­͏ᅟᅠㅤﾠ")
_BIDI = set("‪‫‬‭‮⁦⁧⁨⁩؜")
_ALFABETOS_CONFUNDIBLES = ("LATIN", "CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE")


def _alfabeto(c: str):
    try:
        nombre = unicodedata.name(c)
    except ValueError:
        return None
    return next((a for a in _ALFABETOS_CONFUNDIBLES if nombre.startswith(a + " ")), None)


# Letras que se confunden con las latinas aunque NFKC no las cambie (cirílico, griego, versalitas, dígitos…). Lo de
# estilo (ancho completo, letras matemáticas, en círculo, superíndices) ya lo deshace NFKC.
_CONFUNDIBLES = str.maketrans({
    # cirílico
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "ѕ": "s", "і": "i", "ї": "i", "ј": "j", "ԁ": "d", "ԛ": "q", "ԝ": "w", "һ": "h", "ӏ": "l",
    "п": "n", "г": "r", "ь": "b", "з": "e", "я": "r", "ᴙ": "r",
    # griego
    "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "κ": "k", "μ": "u", "ν": "v", "ο": "o", "ρ": "p", "τ": "t",
    "υ": "u", "χ": "x", "ω": "w", "ζ": "z", "γ": "y",
    # versalitas y otras latinas
    "ᴀ": "a", "ʙ": "b", "ᴄ": "c", "ᴅ": "d", "ᴇ": "e", "ꜰ": "f", "ɢ": "g", "ʜ": "h", "ɪ": "i", "ᴊ": "j", "ᴋ": "k",
    "ʟ": "l", "ᴍ": "m", "ɴ": "n", "ᴏ": "o", "ᴘ": "p", "ʀ": "r", "ꜱ": "s", "ᴛ": "t", "ᴜ": "u", "ᴠ": "v", "ᴡ": "w",
    "ʏ": "y", "ᴢ": "z", "ı": "i", "ȷ": "j", "ɑ": "a", "ɡ": "g", "ɩ": "i", "ɵ": "o", "ø": "o", "đ": "d", "ł": "l",
    "ß": "b",
    # dígitos y signos que pasan por letras
    "0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g", "|": "l", "!": "l", "$": "s",
    "@": "a", "ǀ": "l", "¡": "i",
    # i y l se confunden entre sí
    "i": "l",
})
_PARES_CONFUNDIBLES = (("rn", "m"), ("vv", "w"), ("cl", "d"))

# Nombres que solo usa el Dueño del programa: todo lo que se parezca a «Orniz» (ornizen, 0rnizen, Ｏｒｎｉｚ, ᴏʀɴɪᴢ…).
RESERVADOS = ("orniz",)


# Los confundibles completos de Unicode (UTS #39, `confusables.txt` 16.0.0, copiado sin tocar). Su SHA-256 está fijado:
# si el archivo falta o cambia, el robot falla (no compara nombres con media tabla).
RUTA_CONFUSABLES = pathlib.Path(__file__).resolve().parent / "confusables.txt"
SHA256_CONFUSABLES = "95bd0aad6dced5ebc63436f459c06ab21a8d107cd842fb57f5c3a1e91bca8611"
_uts39 = None


def _tabla_uts39() -> dict:
    """{carácter: su prototipo} de `confusables.txt` (solo las filas de un carácter)."""
    global _uts39
    if _uts39 is None:
        datos = RUTA_CONFUSABLES.read_bytes()
        if hashlib.sha256(datos).hexdigest() != SHA256_CONFUSABLES:
            raise RuntimeError(f"`{RUTA_CONFUSABLES.name}` no es el de Unicode 16.0.0 (el SHA-256 no coincide).")
        tabla = {}
        for linea in datos.decode("utf-8-sig").splitlines():
            if not linea.strip() or linea.startswith("#"):
                continue
            origen, destino = linea.split(";")[:2]
            origen = [int(x, 16) for x in origen.split()]
            if len(origen) == 1:
                tabla[origen[0]] = "".join(chr(int(x, 16)) for x in destino.split())
        _uts39 = tabla
    return _uts39


# Con lo que lleve delante («NEGATIVE CIRCLED», «NEGATIVE SQUARED»…) y las letras de bandera (REGIONAL INDICATOR).
_LETRA_LATINA = re.compile(r"(?:[A-Z]+ )*(?:LATIN (?:SMALL|CAPITAL) LETTER|REGIONAL INDICATOR SYMBOL LETTER) ([A-Z])"
                           r"(?: WITH .*| [A-Z]+)?")


def _letra_base(c: str) -> str:
    """Una letra latina con adorno que ni NFKC ni UTS #39 llevan a su letra («LATIN SMALL LETTER R WITH FISHHOOK»,
    «… DOTLESS J», «… Z WITH RETROFLEX HOOK»): su letra base, por el nombre Unicode. Lo demás, tal cual."""
    if "a" <= c <= "z" or ord(c) < 0x80:
        return c
    try:
        m = _LETRA_LATINA.fullmatch(unicodedata.name(c))
    except ValueError:
        return c
    return m[1].lower() if m else c


def esqueleto_uts39(texto: str) -> str:
    """El esqueleto de UTS #39: NFD, cada carácter a su prototipo y NFD otra vez."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", texto).translate(_tabla_uts39()))


def esqueleto(texto: str) -> str:
    """La forma «de cómo se ve» de un nombre, para comparar: los confundibles de Unicode (UTS #39), NFKC, minúsculas,
    sin tildes, nuestra tabla de confundibles a latinas y solo a–z. Dos nombres con el mismo esqueleto se confunden a
    simple vista (el @ y el nombre de un canal)."""
    t = unicodedata.normalize("NFKC", esqueleto_uts39(unicodedata.normalize("NFKC", texto))).casefold()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c))
    # Dos pasadas: una letra puede llevar a otra que también se confunde (ɪ → i → l).
    t = unicodedata.normalize("NFKC", t).translate(_CONFUNDIBLES).translate(_CONFUNDIBLES)
    t = "".join(map(_letra_base, t)).translate(_CONFUNDIBLES)
    t = "".join(c for c in t if "a" <= c <= "z")  # antes de los pares: «O r n i z» también cuenta
    for par, letra in _PARES_CONFUNDIBLES:
        t = t.replace(par, letra)
    return t


NO_COMPARABLE = ("casi no tiene letras normales (a–z) y no se puede comparar con los demás canales: escríbelo con "
                 "letras latinas")


def esqueleto_dudoso(texto: str) -> bool:
    """¿Se pierde casi todo al sacar el esqueleto? (letras raras que ni NFKC ni las tablas llevan a a–z: el esqueleto
    vacío o de menos de la mitad de las letras y cifras del texto no sirve para comparar, y se rechaza)."""
    if not isinstance(texto, str):
        return False
    visibles = sum(1 for c in texto if unicodedata.category(c)[0] in "LNS")
    return visibles > 0 and len(esqueleto(texto)) * 2 < visibles


def nombre_reservado(texto) -> bool:
    """¿Se parece (aunque sea dentro de un nombre más largo) a un nombre reservado del Dueño?"""
    if not isinstance(texto, str):
        return False
    e = esqueleto(texto)
    return any(esqueleto(r) in e for r in RESERVADOS)


def error_de_nombre(texto):
    """Lo que, además de `error_de_texto`, no vale en el nombre de un canal: letras «de estilo» que se hacen pasar por
    normales (ancho completo, matemáticas, en círculo, superíndices: NFKC las cambia) y las versalitas."""
    if not isinstance(texto, str):
        return None
    if unicodedata.normalize("NFKC", texto) != texto:
        return "usa letras de estilo (anchas, matemáticas, en círculo…): escríbelo con letras normales"
    for c in texto:
        try:
            if "SMALL CAPITAL" in unicodedata.name(c):
                return f"usa versalitas (U+{ord(c):04X}): escríbelo con letras normales"
        except ValueError:
            pass
    return None


def largo_visible(texto: str) -> int:
    """Caracteres que se ven (aproximación de grafemas: sin contar marcas que se combinan con el anterior)."""
    return sum(1 for c in texto if not unicodedata.combining(c) and unicodedata.category(c) not in ("Mn", "Me"))


def error_de_texto(texto, maximo: int, minimo: int = 0, saltos: int = 0):
    """Por qué un nombre o descripción no vale, o None."""
    if not isinstance(texto, str):
        return "tiene que ser un texto"
    if unicodedata.normalize("NFC", texto) != texto:
        return "no está en forma Unicode NFC (guárdalo con el parcheador)"
    if texto != texto.strip():
        return "tiene espacios al principio o al final"
    for c in texto:
        if c in _INVISIBLES or c in _BIDI:
            return f"tiene un carácter invisible o de dirección (U+{ord(c):04X})"
        if c == "\n":
            continue
        if unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co", "Cn"):
            return f"tiene un carácter de control o sin asignar (U+{ord(c):04X})"
    if texto.count("\n") > saltos:
        return "tiene saltos de línea" if saltos == 0 else f"tiene más de {saltos} saltos de línea"
    alfabetos = {a for a in map(_alfabeto, texto) if a}
    if len(alfabetos) > 1:
        return "mezcla alfabetos que se confunden (" + " y ".join(sorted(a.lower() for a in alfabetos)) + ")"
    largo = largo_visible(texto)
    if largo < minimo:
        return "está vacío" if minimo == 1 else f"tiene menos de {minimo} caracteres"
    if largo > maximo:
        return f"tiene {largo} caracteres y el máximo es {maximo}"
    return None


def _url_https(valor) -> bool:
    return isinstance(valor, str) and valor.startswith("https://") and len(valor) <= 500 \
        and not any(c.isspace() or ord(c) < 32 for c in valor)


# ───────────────────────────────────────── Rutas ─────────────────────────────────────────

def canal_de_la_ruta(ruta: str):
    """`canales/<c>/…` → (`<c>`, resto); cualquier otra ruta → None."""
    if not ruta.startswith(CARPETA_CANALES):
        return None
    partes = ruta[len(CARPETA_CANALES):].split("/", 1)
    return (partes[0], partes[1] if len(partes) == 2 else "")


def error_de_ruta(ruta: str):
    """Las rutas de `canales/` solo con minúsculas ASCII, dígitos, `-`, `_`, `.` y `/`, sin `..`."""
    if not RUTA_SEGURA.match(ruta):
        return "solo puede tener minúsculas sin acentos, números, `-`, `_`, `.` y `/`"
    if any(p in ("", ".", "..") for p in ruta.split("/")):
        return "tiene una carpeta vacía, `.` o `..`"
    return None


# ───────────────────────────────────────── Miembros ─────────────────────────────────────────

@dataclass(frozen=True)
class Miembro:
    id: int
    cuenta: str
    rol: int          # 1–4, como `permisos.Rol`
    estado: str       # «activo» o «invitado»
    fila: dict = field(compare=False, hash=False, default_factory=dict)

    @property
    def activo(self) -> bool:
        return self.estado == "activo"


CAMPOS_MIEMBROS = ("esquema", "miembros")
CAMPOS_MIEMBRO = ("id", "cuenta", "rol", "desde", "estado", "invitadoPor", "etiquetas")


def leer_miembros(objeto, ruta: str):
    """El contenido de `miembros.json` → ({id: Miembro}, errores)."""
    if not isinstance(objeto, dict):
        return {}, [f"`{ruta}` tiene que ser un objeto `{{ … }}`."]
    errores = _campos_desconocidos(f"`{ruta}`", objeto, CAMPOS_MIEMBROS)
    if objeto.get("esquema") != 1:
        errores.append(f"`{ruta}`: falta `\"esquema\": 1`.")
    filas = objeto.get("miembros")
    if not isinstance(filas, list):
        return {}, errores + [f"`{ruta}`: `miembros` tiene que ser una lista."]
    miembros = {}
    for i, fila in enumerate(filas):
        donde = f"`{ruta}` › miembro {i + 1}"
        if not isinstance(fila, dict):
            errores.append(f"{donde}: tiene que ser un objeto.")
            continue
        errores += _campos_desconocidos(donde, fila, CAMPOS_MIEMBRO)
        mid, cuenta, rol, estado = fila.get("id"), fila.get("cuenta"), fila.get("rol"), fila.get("estado")
        malos = []
        if not _es_id(mid):
            malos.append("`id` (el número de la cuenta de GitHub)")
        if not isinstance(cuenta, str) or not CUENTA_GITHUB.match(cuenta):
            malos.append("`cuenta`")
        if rol not in TEXTO_ROL:
            malos.append("`rol` (propietario, administrador, editor o colaborador)")
        if estado not in ("activo", "invitado"):
            malos.append("`estado` (activo o invitado)")
        if "desde" in fila and not _es_fecha(fila["desde"]):
            malos.append("`desde` (aaaa-mm-dd)")
        if "invitadoPor" in fila and not _es_id(fila["invitadoPor"]):
            malos.append("`invitadoPor` (el número de la cuenta que invita)")
        etiquetas = fila.get("etiquetas", [])
        if not isinstance(etiquetas, list) or len(etiquetas) > MAX_ETIQUETAS_MIEMBRO or any(
                error_de_texto(e, LARGO_ETIQUETA_MIEMBRO, 1) for e in etiquetas) or len(set(etiquetas)) != len(etiquetas):
            malos.append(f"`etiquetas` (como mucho {MAX_ETIQUETAS_MIEMBRO}, sin repetir, de 1 a {LARGO_ETIQUETA_MIEMBRO} caracteres)")
        if malos:
            errores.append(f"{donde}: no vale " + ", ".join(malos) + ".")
            continue
        if mid in miembros:
            errores.append(f"{donde}: la cuenta {mid} está repetida.")
            continue
        miembros[mid] = Miembro(mid, cuenta, TEXTO_ROL.index(rol) + 1, estado, fila)

    activos = sum(1 for m in miembros.values() if m.activo)
    if activos > MAX_MIEMBROS_ACTIVOS:
        errores.append(f"`{ruta}`: tiene {activos} miembros y el máximo son {MAX_MIEMBROS_ACTIVOS}.")
    if len(miembros) - activos > MAX_INVITACIONES:
        errores.append(f"`{ruta}`: tiene {len(miembros) - activos} invitaciones sin aceptar y el máximo son {MAX_INVITACIONES}.")
    if not errores and not any(m.activo and m.rol == 4 for m in miembros.values()):
        errores.append(f"`{ruta}`: el canal se quedaría sin ningún Propietario activo. Siempre tiene que quedar al menos uno.")
    return miembros, errores


def rol_en_canal(miembros: dict, cuenta_id) -> int:
    """El rol (1–4) de esa cuenta en el canal, o 0. Una invitación sin aceptar no da nada."""
    m = miembros.get(cuenta_id)
    return m.rol if m is not None and m.activo else 0


# ───────────────────────────────────────── Lista negra del canal ─────────────────────────────────────────

CAMPOS_LISTA = ("esquema", "archivos", "huellas", "usuarios")


@dataclass
class ListaNegra:
    archivos: list = field(default_factory=list)   # [{patron, motivo}]
    huellas: list = field(default_factory=list)    # [{hash, motivo, fecha}]
    usuarios: dict = field(default_factory=dict)   # {id: fila}


def leer_lista_negra(objeto, ruta: str):
    """El contenido de `lista-negra.json` → (ListaNegra, errores)."""
    lista = ListaNegra()
    if objeto is None:
        return lista, []
    if not isinstance(objeto, dict):
        return lista, [f"`{ruta}` tiene que ser un objeto `{{ … }}`."]
    errores = _campos_desconocidos(f"`{ruta}`", objeto, CAMPOS_LISTA)
    if objeto.get("esquema") != 1:
        errores.append(f"`{ruta}`: falta `\"esquema\": 1`.")

    def filas(clave, campos, valida):
        valor = objeto.get(clave, [])
        if not isinstance(valor, list):
            errores.append(f"`{ruta}`: `{clave}` tiene que ser una lista.")
            return []
        buenas = []
        for i, fila in enumerate(valor):
            donde = f"`{ruta}` › `{clave}` {i + 1}"
            if not isinstance(fila, dict):
                errores.append(f"{donde}: tiene que ser un objeto.")
                continue
            errores.extend(_campos_desconocidos(donde, fila, campos))
            problema = valida(fila) or error_de_texto(fila.get("motivo"), LARGO_MOTIVO, 1)
            if problema:
                errores.append(f"{donde}: {problema}.")
                continue
            if "fecha" in fila and not _es_fecha(fila["fecha"]):
                errores.append(f"{donde}: `fecha` tiene que ser aaaa-mm-dd.")
                continue
            buenas.append(fila)
        return buenas

    lista.archivos = filas("archivos", ("patron", "motivo", "fecha"),
                           lambda f: None if isinstance(f.get("patron"), str) and f["patron"].strip("/ ")
                           and len(f["patron"]) <= 200 else "el `patron` está vacío o es demasiado largo")
    lista.huellas = filas("huellas", ("hash", "motivo", "fecha"),
                          lambda f: None if isinstance(f.get("hash"), str) and HASH_VALIDO.match(f["hash"])
                          else "el `hash` tiene que ser `blake3:` y 64 caracteres")
    for fila in filas("usuarios", ("id", "cuenta", "motivo", "fecha", "por"),
                      lambda f: None if _es_id(f.get("id")) and ("cuenta" not in f or (
                          isinstance(f["cuenta"], str) and CUENTA_GITHUB.match(f["cuenta"])))
                      and ("por" not in f or _es_id(f["por"]))
                      else "falta el `id` de la cuenta, o la `cuenta` o `por` no valen"):
        if fila["id"] in lista.usuarios:
            errores.append(f"`{ruta}`: la cuenta {fila['id']} está repetida en `usuarios`.")
        lista.usuarios[fila["id"]] = fila
    total = len(lista.archivos) + len(lista.huellas) + len(lista.usuarios)
    if total > MAX_LISTA_NEGRA:
        errores.append(f"`{ruta}`: tiene {total} entradas y el máximo son {MAX_LISTA_NEGRA}.")
    return lista, errores


# ───────────────────────────────────────── canal.json ─────────────────────────────────────────

CAMPOS_CANAL = ("esquema", "id", "nombre", "descripcion", "logo", "contacto", "paquetes", "adultos", "normasAceptadas",
                "creado", "estado", "oculto", "verificacion", "idAnteriores")
CAMPOS_CONTACTO = ("issues", "correo", "web", "enlaces")
CAMPOS_VERIFICACION = ("verificado", "desde", "motivo", "historial")
CAMPOS_HISTORIAL = ("fecha", "accion", "motivo", "por")

# Quién cambia cada campo de canal.json (docs/canales.md §4.2). 3 = Administrador, 4 = Propietario del canal, 5 = Dueño.
ROL_CAMPO_CANAL = {
    "nombre": 3, "descripcion": 3, "logo": 3, "contacto": 3, "adultos": 3,
    "paquetes": 4, "normasAceptadas": 4, "estado": 4,
    "verificacion": 5, "oculto": 5, "id": 5, "creado": 5, "idAnteriores": 5, "esquema": 5,
}


def dueno_de_repositorio(repositorio: str) -> str:
    """La cuenta u organización de un «dueño/nombre», para comparar (sin distinguir mayúsculas, como GitHub)."""
    return repositorio.split("/", 1)[0].casefold()


def repositorios_ajenos(paquetes, canal: str, de_otros: dict, antes=()) -> list:
    """Motivos si `paquetes` declara un repositorio que en `main` ya es de otro canal (`de_otros` = {repositorio en
    minúsculas: @}). Los que el canal ya tenía (`antes`) no cuentan: un canal no se queda sin poder cambiar nada por algo
    que ya estaba así."""
    if not isinstance(paquetes, list):
        return []
    tenia = {p.casefold() for p in antes if isinstance(p, str)} if isinstance(antes, list) else set()
    motivos = []
    for p in paquetes:
        if isinstance(p, str) and p.casefold() not in tenia and de_otros.get(p.casefold(), canal) != canal:
            motivos.append(f"`paquetes`: `{p}` ya es el repositorio de @{de_otros[p.casefold()]}. Cada repositorio de "
                           "paquetes es de un solo canal.")
    return motivos


def validar_canal(objeto, carpeta: str, ruta: str) -> list:
    if not isinstance(objeto, dict):
        return [f"`{ruta}` tiene que ser un objeto `{{ … }}`."]
    errores = _campos_desconocidos(f"`{ruta}`", objeto, CAMPOS_CANAL)
    if objeto.get("esquema") != 1:
        errores.append(f"`{ruta}`: falta `\"esquema\": 1`.")
    if objeto.get("id") != carpeta:
        errores.append(f"`{ruta}`: `id` tiene que ser `{carpeta}`, el nombre de su carpeta.")
    for campo, maximo, minimo, saltos in (("nombre", LARGO_NOMBRE, 1, 0), ("descripcion", LARGO_DESCRIPCION, 0, 3)):
        if campo == "descripcion" and campo not in objeto:
            continue
        problema = error_de_texto(objeto.get(campo), maximo, minimo, saltos)
        if problema is None and campo == "nombre":
            problema = error_de_nombre(objeto.get(campo))
        if problema:
            errores.append(f"`{ruta}`: `{campo}` {problema}.")
    logo = objeto.get("logo")
    if logo is not None and (not isinstance(logo, str) or "/" in logo or not RUTA_SEGURA.match(logo)
                             or not logo.endswith(EXTENSIONES_LOGO)):
        errores.append(f"`{ruta}`: `logo` tiene que ser el nombre de una imagen de la carpeta del canal "
                       f"({', '.join(EXTENSIONES_LOGO)}).")
    contacto = objeto.get("contacto", {})
    if not isinstance(contacto, dict):
        errores.append(f"`{ruta}`: `contacto` tiene que ser un objeto.")
    else:
        errores += _campos_desconocidos(f"`{ruta}` › `contacto`", contacto, CAMPOS_CONTACTO)
        if "issues" in contacto and not isinstance(contacto["issues"], bool):
            errores.append(f"`{ruta}`: `contacto.issues` tiene que ser true o false.")
        correo = contacto.get("correo")
        if correo is not None and (not isinstance(correo, str) or len(correo) > 254
                                   or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+\Z", correo)):
            errores.append(f"`{ruta}`: `contacto.correo` no es una dirección de correo.")
        if contacto.get("web") is not None and not _url_https(contacto["web"]):
            errores.append(f"`{ruta}`: `contacto.web` tiene que empezar por `https://`.")
        enlaces = contacto.get("enlaces", [])
        if not isinstance(enlaces, list) or len(enlaces) > MAX_ENLACES or not all(
                isinstance(e, dict) and set(e) <= {"tipo", "url"} and isinstance(e.get("tipo"), str)
                and 0 < len(e["tipo"]) <= 24 and _url_https(e.get("url")) for e in enlaces):
            errores.append(f"`{ruta}`: `contacto.enlaces` tiene que ser una lista de como mucho {MAX_ENLACES} "
                           "`{ \"tipo\": …, \"url\": \"https://…\" }`.")
    paquetes = objeto.get("paquetes", [])
    if not isinstance(paquetes, list) or len(paquetes) > MAX_PAQUETES \
            or len({str(p).casefold() for p in paquetes}) != len(paquetes) \
            or not all(isinstance(p, str) and REPOSITORIO.match(p) for p in paquetes):
        errores.append(f"`{ruta}`: `paquetes` tiene que ser una lista de como mucho {MAX_PAQUETES} repositorios "
                       "`dueño/nombre`, sin repetir (sin distinguir mayúsculas).")
    elif carpeta != CANAL_OFICIAL and any(dueno_de_repositorio(p) == ORGANIZACION_OFICIAL for p in paquetes):
        errores.append(f"`{ruta}`: `paquetes` no puede llevar repositorios de OrnizStudio: son del canal oficial.")
    for campo in ("adultos", "oculto"):
        if campo in objeto and not isinstance(objeto[campo], bool):
            errores.append(f"`{ruta}`: `{campo}` tiene que ser true o false.")
    if "normasAceptadas" in objeto and (not _es_entero(objeto["normasAceptadas"]) or objeto["normasAceptadas"] < 0):
        errores.append(f"`{ruta}`: `normasAceptadas` tiene que ser un número entero.")
    if not _es_fecha(objeto.get("creado")):
        errores.append(f"`{ruta}`: `creado` tiene que ser una fecha aaaa-mm-dd.")
    if objeto.get("estado") not in ("activo", "retirado", "bloqueado"):
        errores.append(f"`{ruta}`: `estado` tiene que ser activo, retirado o bloqueado.")
    verificacion = objeto.get("verificacion")
    if verificacion is not None:
        if not isinstance(verificacion, dict) or not isinstance(verificacion.get("verificado"), bool):
            errores.append(f"`{ruta}`: `verificacion` tiene que llevar `verificado` (true o false).")
        else:
            errores += _campos_desconocidos(f"`{ruta}` › `verificacion`", verificacion, CAMPOS_VERIFICACION)
            if verificacion.get("desde") is not None and not _es_fecha(verificacion["desde"]):
                errores.append(f"`{ruta}`: `verificacion.desde` tiene que ser aaaa-mm-dd.")
            if "motivo" in verificacion and error_de_texto(verificacion["motivo"], 500, 1, 3):
                errores.append(f"`{ruta}`: `verificacion.motivo` {error_de_texto(verificacion['motivo'], 500, 1, 3)}.")
            historial = verificacion.get("historial", [])
            if not isinstance(historial, list) or not all(
                    isinstance(h, dict) and set(h) <= set(CAMPOS_HISTORIAL) and _es_fecha(h.get("fecha"))
                    and h.get("accion") in ("verificar", "quitar") and _es_id(h.get("por"))
                    and not error_de_texto(h.get("motivo"), 500, 1, 3) for h in historial):
                errores.append(f"`{ruta}`: `verificacion.historial` tiene filas que no valen "
                               "(`fecha`, `accion` verificar/quitar, `motivo` y `por`).")
    anteriores = objeto.get("idAnteriores", [])
    if not isinstance(anteriores, list) or not all(
            isinstance(a, dict) and set(a) <= {"id", "hasta", "desde"} and isinstance(a.get("id"), str)
            and ID_CANAL.match(a["id"]) and _es_fecha(a.get("hasta")) for a in anteriores):
        errores.append(f"`{ruta}`: `idAnteriores` tiene que ser una lista de `{{ \"id\": …, \"hasta\": aaaa-mm-dd }}`.")
    return errores


# ───────────────────────────────────────── ficha.json ─────────────────────────────────────────
# La ficha pública del canal (docs/canales.md §1.4): lo que el canal cuenta de sí mismo en su ficha del parcheador. Va
# aparte de `canal.json` porque la cambian el Propietario y los Administradores (el Editor no) y para que un error en
# ella no deje al canal sin publicarse. Lo que se calcula (desde cuándo existe, sus cifras y su equipo) no se guarda.

CAMPOS_FICHA = ("esquema", "descripcion", "idiomas", "tipos", "enlaces", "enCurso", "destacado")
CAMPOS_ENLACE_FICHA = ("tipo", "texto", "url")
CAMPOS_EN_CURSO = ("nombre", "tipo", "progreso", "actualizado")
LARGO_DESCRIPCION_FICHA = 500
SALTOS_DESCRIPCION_FICHA = 3
MAX_IDIOMAS_FICHA = 8
# Lista cerrada (ISO 639-1): la app sabe nombrarlos todos en español y en inglés.
IDIOMAS_FICHA = ("es", "en", "ca", "gl", "eu", "pt", "fr", "it", "de", "nl", "pl", "ru", "uk", "ja", "zh", "ko")
TIPOS_FICHA = ("completa", "parcial", "mod")
TIPOS_ENLACE_FICHA = ("discord", "web", "apoyo", "github", "otro")
MAX_ENLACES_FICHA = 4
LARGO_TEXTO_ENLACE_FICHA = 40
LARGO_URL_FICHA = 300
MAX_EN_CURSO = 5
LARGO_NOMBRE_EN_CURSO = 60
ROL_FICHA = 3  # Administrador (y el Propietario del canal, y el Dueño)
# Un nombre de máquina con al menos un punto, en ASCII (un dominio con acentos va en punycode, `xn--…`: así no se
# escribe una dirección que se ve igual que otra con letras de otro alfabeto).
_HOST_URL = re.compile(r"^(?=.{4,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_RESTO_URL = re.compile(r"^[A-Za-z0-9\-._~%!$&'()*+,;=:@/?#]*\Z")


def error_de_etiqueta_idn(etiqueta: str):
    """Por qué una parte `xn--…` de un nombre de sitio engaña, o None. Se descodifica (punycode) y se rechaza si no
    es punycode de verdad, si sale todo ASCII (`xn--` sin acentos), si mezcla alfabetos, si tiene invisibles, o si
    está entera en otro alfabeto y cada letra se confunde con una latina (`xn--80ak6aa92e` = «аррӏе» en cirílico, que
    se lee «apple»). Un dominio con acentos de verdad (`xn--espaol-zwa` = «español») vale."""
    if not etiqueta.startswith("xn--"):
        return None
    codigo = etiqueta[4:]
    try:
        unicode_ = codigo.encode("ascii").decode("punycode")
        canonico = unicode_.encode("punycode").decode("ascii")
    except (UnicodeError, ValueError):
        return "no es punycode válido"
    if not unicode_ or canonico != codigo:
        return "no es punycode válido"
    if unicode_.isascii():
        return "es punycode de algo sin acentos (escríbelo tal cual)"
    if unicodedata.normalize("NFC", unicode_.lower()) != unicode_:
        return "no está en minúsculas ni en forma NFC"
    if (problema := error_de_texto(unicode_, 63)):
        return problema
    letras = [c for c in unicode_ if c not in "-0123456789"]
    if letras and not any(_alfabeto(c) == "LATIN" for c in letras) and all(esqueleto(c) for c in letras):
        return f"se lee como «{esqueleto(unicode_)}» con letras de otro alfabeto"
    return None


def error_de_url_ficha(url):
    """Por qué una dirección de la ficha no vale, o None. Solo `https://`, en ASCII imprimible, de hasta 300, sin
    usuario ni contraseña, sin puerto (salvo 443) y con un nombre de máquina de verdad (ni una IP ni `localhost`)."""
    if not isinstance(url, str):
        return "tiene que ser un texto"
    if len(url) > LARGO_URL_FICHA:
        return f"tiene {len(url)} caracteres y el máximo es {LARGO_URL_FICHA}"
    if not url.startswith("https://"):
        return "tiene que empezar por `https://`"
    resto = url[len("https://"):]
    corte = min((resto.find(c) for c in "/?#" if c in resto), default=len(resto))
    autoridad, camino = resto[:corte], resto[corte:]
    if "@" in autoridad:
        return "no puede llevar usuario ni contraseña (`usuario:clave@`)"
    host, dos_puntos, puerto = autoridad.partition(":")
    if dos_puntos and puerto != "443":
        return "no puede llevar un puerto"
    if not _HOST_URL.match(host):
        return "no tiene un nombre de sitio válido (en minúsculas y sin acentos; con acentos, en `xn--…`)"
    for etiqueta in host.split("."):
        if (problema := error_de_etiqueta_idn(etiqueta)):
            return f"no tiene un nombre de sitio válido: `{etiqueta}` {problema}"
    if not _RESTO_URL.match(camino) or "\\" in url:
        return "tiene espacios, acentos u otros caracteres que no van en una dirección (escríbelos con `%`)"
    return None


def validar_ficha(objeto, ruta: str, hoy: datetime.date | None = None) -> list:
    """Motivos por los que `ficha.json` no vale (lista vacía = vale). `hoy` (para que `enCurso.actualizado` no sea
    futuro) se puede fijar en las pruebas; se deja un día de margen por los husos horarios."""
    hoy = hoy or datetime.date.today()
    if not isinstance(objeto, dict):
        return [f"`{ruta}` tiene que ser un objeto `{{ … }}`."]
    errores = _campos_desconocidos(f"`{ruta}`", objeto, CAMPOS_FICHA)
    if objeto.get("esquema") != 1:
        errores.append(f"`{ruta}`: falta `\"esquema\": 1`.")
    if "descripcion" in objeto and (problema := error_de_texto(objeto["descripcion"], LARGO_DESCRIPCION_FICHA, 0,
                                                                 SALTOS_DESCRIPCION_FICHA)):
        errores.append(f"`{ruta}`: `descripcion` {problema}.")

    for campo, validos, maximo in (("idiomas", IDIOMAS_FICHA, MAX_IDIOMAS_FICHA), ("tipos", TIPOS_FICHA, len(TIPOS_FICHA))):
        lista = objeto.get(campo, [])
        if not isinstance(lista, list) or len(lista) > maximo \
                or not all(isinstance(x, str) and x in validos for x in lista) or len(set(lista)) != len(lista):
            errores.append(f"`{ruta}`: `{campo}` tiene que ser una lista sin repetir de como mucho {maximo} de estos: "
                           + ", ".join(f"`{v}`" for v in validos) + ".")

    enlaces = objeto.get("enlaces", [])
    if not isinstance(enlaces, list) or len(enlaces) > MAX_ENLACES_FICHA:
        errores.append(f"`{ruta}`: `enlaces` tiene que ser una lista de como mucho {MAX_ENLACES_FICHA}.")
    else:
        vistas = set()
        for i, e in enumerate(enlaces, 1):
            donde = f"`{ruta}` › `enlaces` {i}"
            if not isinstance(e, dict):
                errores.append(f"{donde} tiene que ser `{{ \"tipo\": …, \"texto\": …, \"url\": \"https://…\" }}`.")
                continue
            errores += _campos_desconocidos(donde, e, CAMPOS_ENLACE_FICHA)
            if e.get("tipo") not in TIPOS_ENLACE_FICHA:
                errores.append(f"{donde}: `tipo` tiene que ser " + ", ".join(f"`{v}`" for v in TIPOS_ENLACE_FICHA) + ".")
            if (problema := error_de_texto(e.get("texto"), LARGO_TEXTO_ENLACE_FICHA, 1)):
                errores.append(f"{donde}: `texto` {problema}.")
            if (problema := error_de_url_ficha(e.get("url"))):
                errores.append(f"{donde}: `url` {problema}.")
            elif e["url"] in vistas:
                errores.append(f"{donde}: `url` está repetida.")
            else:
                vistas.add(e["url"])

    en_curso = objeto.get("enCurso", [])
    if not isinstance(en_curso, list) or len(en_curso) > MAX_EN_CURSO:
        errores.append(f"`{ruta}`: `enCurso` tiene que ser una lista de como mucho {MAX_EN_CURSO} proyectos.")
    else:
        nombres = set()
        for i, p in enumerate(en_curso, 1):
            donde = f"`{ruta}` › `enCurso` {i}"
            if not isinstance(p, dict):
                errores.append(f"{donde} tiene que ser `{{ \"nombre\": …, \"tipo\": …, \"progreso\": …, "
                               "\"actualizado\": aaaa-mm-dd }}`.")
                continue
            errores += _campos_desconocidos(donde, p, CAMPOS_EN_CURSO)
            if (problema := error_de_texto(p.get("nombre"), LARGO_NOMBRE_EN_CURSO, 1)):
                errores.append(f"{donde}: `nombre` {problema}.")
            elif unicodedata.normalize("NFKC", p["nombre"]).casefold() in nombres:
                errores.append(f"{donde}: `nombre` ya está en otro proyecto de la lista.")
            else:
                nombres.add(unicodedata.normalize("NFKC", p["nombre"]).casefold())
            if p.get("tipo") not in TIPOS_FICHA:
                errores.append(f"{donde}: `tipo` tiene que ser " + ", ".join(f"`{v}`" for v in TIPOS_FICHA) + ".")
            if not _es_entero(p.get("progreso")) or not 0 <= p["progreso"] <= 100:
                errores.append(f"{donde}: `progreso` tiene que ser un número entero de 0 a 100.")
            if not _es_fecha(p.get("actualizado")):
                errores.append(f"{donde}: `actualizado` tiene que ser una fecha aaaa-mm-dd.")
            elif datetime.date.fromisoformat(p["actualizado"]) > hoy + datetime.timedelta(days=1):
                errores.append(f"{donde}: `actualizado` ({p['actualizado']}) es una fecha futura.")

    destacado = objeto.get("destacado")
    if destacado is not None and not (isinstance(destacado, str) and ID_JUEGO.match(destacado)):
        errores.append(f"`{ruta}`: `destacado` tiene que ser el id de un juego con parche de este canal, o null.")
    return errores


# ───────────────────────────────────────── Lo que ve el robot de un canal ─────────────────────────────────────────

@dataclass
class EstadoCanal:
    """Lo que hay de un canal en `main` o en la propuesta (los textos ya leídos; None si el archivo no existe)."""
    canal: object = None
    miembros: object = None
    lista_negra: object = None


@dataclass(frozen=True)
class CambioCanal:
    """Un archivo de `canales/` que cambia (lo que ya trae `permisos.Cambio`, más su contenido en los dos lados)."""
    ruta: str
    estado: str
    tamano: int
    antes: bytes | None
    despues: bytes | None


def _mismo_contenido(resto: str, antes, despues) -> bool:
    """¿El archivo dice lo mismo antes y después (solo cambia el formato, o el orden de los miembros)?"""
    if resto == "miembros.json":
        m_a, e_a = leer_miembros(antes, resto)
        m_d, e_d = leer_miembros(despues, resto)
        if e_a or e_d:
            return False
        resto_a = {k: v for k, v in antes.items() if k != "miembros"}
        resto_d = {k: v for k, v in despues.items() if k != "miembros"}
        return resto_a == resto_d and {i: m.fila for i, m in m_a.items()} == {i: m.fila for i, m in m_d.items()}
    return antes == despues


def escribir_como_la_app(valor) -> str:
    """El texto que escribe el parcheador (Equipo, `EscritorCatalogo.Escribir`): objetos y listas de valores simples en
    una línea (`{ "a": 1, "b": 2 }`, `[1, 2]`), el resto con dos espacios por nivel, y un salto de línea al final."""
    return _valor_app(valor, 0) + "\n"


def _valor_app(valor, nivel: int) -> str:
    def simple(v):
        return not isinstance(v, (dict, list))
    if isinstance(valor, dict):
        if not valor:
            return "{}"
        if all(simple(v) for v in valor.values()):
            return "{ " + ", ".join(f"{_cadena_app(k)}: {_valor_app(v, nivel)}" for k, v in valor.items()) + " }"
        dentro = "  " * (nivel + 1)
        return ("{\n" + ",\n".join(f"{dentro}{_cadena_app(k)}: {_valor_app(v, nivel + 1)}" for k, v in valor.items())
                + "\n" + "  " * nivel + "}")
    if isinstance(valor, list):
        if not valor:
            return "[]"
        if all(simple(v) for v in valor):
            return "[" + ", ".join(_valor_app(v, nivel) for v in valor) + "]"
        dentro = "  " * (nivel + 1)
        return "[\n" + ",\n".join(f"{dentro}{_valor_app(v, nivel + 1)}" for v in valor) + "\n" + "  " * nivel + "]"
    if valor is True:
        return "true"
    if valor is False:
        return "false"
    if valor is None:
        return "null"
    if isinstance(valor, str):
        return _cadena_app(valor)
    return str(valor)


def _cadena_app(texto: str) -> str:
    return json.dumps(texto, ensure_ascii=False)


_DECODIFICADOR = json.JSONDecoder()


def _saltar_espacios(texto: str, i: int) -> int:
    while i < len(texto) and texto[i] in " \t\r\n":
        i += 1
    return i


def _filas_con_posicion(texto: str):
    """[(inicio, fin, id)] de cada fila de `miembros` en el texto, o None si no se encuentra."""
    try:
        i = _saltar_espacios(texto, 0)
        if texto[i] != "{":
            return None
        i += 1
        while True:
            i = _saltar_espacios(texto, i)
            if texto[i] != '"':
                return None
            clave, i = json.decoder.scanstring(texto, i + 1)
            i = _saltar_espacios(texto, i)
            if texto[i] != ":":
                return None
            i = _saltar_espacios(texto, i + 1)
            if clave == "miembros":
                if texto[i] != "[":
                    return None
                filas, i = [], i + 1
                while True:
                    i = _saltar_espacios(texto, i)
                    if texto[i] == "]" and not filas:
                        return filas
                    valor, fin = _DECODIFICADOR.raw_decode(texto, i)
                    filas.append((i, fin, valor.get("id") if isinstance(valor, dict) else None))
                    i = _saltar_espacios(texto, fin)
                    if texto[i] == "]":
                        return filas
                    if texto[i] != ",":
                        return None
                    i += 1
            _, i = _DECODIFICADOR.raw_decode(texto, i)
            i = _saltar_espacios(texto, i)
            if texto[i] != ",":
                return None
            i += 1
    except (ValueError, IndexError):
        return None


def _solo_su_fila_en_el_texto(antes: bytes, despues: bytes, objeto_despues, autor_id) -> bool:
    """Quien solo puede tocar su propia fila no puede, de paso, reformatear ni reordenar el resto del archivo (cada
    publicación mueve `main`). Vale si el resto queda idéntico byte a byte o si el archivo queda tal cual lo escribe el
    parcheador, con los demás miembros en el mismo orden."""
    a, d = antes.decode("utf-8"), despues.decode("utf-8")
    filas_a = _filas_con_posicion(a)
    if filas_a is None:
        return False
    if d == escribir_como_la_app(objeto_despues):
        filas_d = _filas_con_posicion(d) or []
        return [i for _, _, i in filas_a if i != autor_id] == [i for _, _, i in filas_d if i != autor_id]
    filas_d = _filas_con_posicion(d)
    if filas_d is None:
        return False
    en_a = [k for k, (_, _, i) in enumerate(filas_a) if i == autor_id]
    en_d = [k for k, (_, _, i) in enumerate(filas_d) if i == autor_id]
    if len(en_a) != 1:
        return False
    k = en_a[0]
    ini_a, fin_a, _ = filas_a[k]
    if len(en_d) == 1:
        ini_d, fin_d, _ = filas_d[en_d[0]]
        return a[:ini_a] == d[:ini_d] and a[fin_a:] == d[fin_d:] and _fila_sin_hinchar(a[ini_a:fin_a], d[ini_d:fin_d])
    if en_d:
        return False
    # Sale del canal: su fila desaparece con una de las comas que la separan.
    candidatos = []
    if k > 0:
        candidatos.append(a[:filas_a[k - 1][1]] + a[fin_a:])
    if k + 1 < len(filas_a):
        candidatos.append(a[:ini_a] + a[filas_a[k + 1][0]:])
    if len(filas_a) == 1:
        candidatos.append(a[:ini_a] + a[fin_a:])
    return d in candidatos


def _fila_sin_hinchar(texto_antes: str, texto_despues: str) -> bool:
    r"""La fila propia nueva no lleva nada de más (tercera revisión, N5): o es exactamente como la escribe el parcheador
    (nivel 2: raíz → `miembros` → fila), o es la fila de antes, con su mismo formato, cambiando solo los valores que
    cambian (cada valor viejo aparece una sola vez en la fila). Así nadie la hincha con espacios o escapes `\u` hasta
    el tope del archivo."""
    try:
        fila_a, fila_d = _DECODIFICADOR.decode(texto_antes), _DECODIFICADOR.decode(texto_despues)
    except ValueError:
        return False
    if not isinstance(fila_a, dict) or not isinstance(fila_d, dict):
        return False
    if texto_despues == _valor_app(fila_d, 2):
        return True
    if list(fila_a) != list(fila_d):
        return False
    texto = texto_antes
    for clave in fila_a:
        if fila_a[clave] == fila_d[clave]:
            continue
        if not all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in (fila_a[clave], fila_d[clave])):
            return False
        viejo, nuevo = (_cadena_app(v) if isinstance(v, str) else str(v) for v in (fila_a[clave], fila_d[clave]))
        # El valor de esa clave en concreto (`"rol": "editor"` y `"cuenta": "editor"` llevan el mismo texto).
        patron = re.compile(re.escape(_cadena_app(clave)) + r"(\s*:\s*)" + re.escape(viejo))
        if len(patron.findall(texto)) != 1:
            return False
        texto = patron.sub(lambda m: _cadena_app(clave) + m.group(1) + nuevo, texto)
    return texto == texto_despues


def _diferencias(a: dict, b: dict):
    falta = object()
    return sorted(k for k in a.keys() | b.keys() if a.get(k, falta) != b.get(k, falta))


NOMBRE_ROL = {0: "sin rol", 1: "Colaborador", 2: "Editor", 3: "Administrador", 4: "Propietario del canal", 5: "Dueño del programa"}


def comprobar_canales(cambios: list, rol_por_canal: dict, autor_id: int, es_dueno: bool, leer=None,
                      ids_duenos=frozenset(), cuenta_de=None, rol_externo=None, veto_general=None,
                      nombre_parecido=None, paquetes_de_otros=None) -> list:
    """Motivos de rechazo de lo que la propuesta cambia en `canales/` (lista vacía = se acepta).

    `cambios` son `CambioCanal` (solo los de `canales/`). `rol_por_canal` = {canal: rol del autor en `main`} (1–4;
    0 o sin clave = ninguno). El Dueño del programa puede con todo, salvo las reglas de formato y el veto a un Dueño.
    `leer(ruta, lado)` da los archivos del canal que la propuesta no cambia (la lista negra y los miembros de `main`).
    `ids_duenos` son los ids del Dueño (nadie los puede vetar). `cuenta_de(id)` da el nombre actual de esa cuenta en
    GitHub (None si no existe): sirve para que nadie escriba el nombre de otra persona junto a un id. `rol_externo(canal,
    id)` es el rol que esa cuenta tiene en el canal por fuera del archivo (en la fase A, el equipo de GitHub en el canal
    oficial): con él se sabe el rol real de a quién se veta, igual que lo calcula el robot para los permisos.
    `veto_general(id)` da el motivo si la cuenta está en la lista negra general (fase D) y `nombre_parecido(canal,
    nombre)` por qué el nombre de un canal se confunde con otro canal o con un nombre reservado.
    `paquetes_de_otros` = {repositorio en minúsculas: @} de los `canal.json` de `main`: nadie declara el de otro canal.
    """
    leer = leer or (lambda ruta, lado: None)
    veto_general = veto_general or (lambda cuenta_id: None)
    nombre_parecido = nombre_parecido or _solo_orniz
    quedan = [TOPE_CONSULTAS_DUENO if es_dueno else TOPE_CONSULTAS]

    def con_tope(consultar):
        """La misma consulta, con lo ya sabido guardado y un tope de consultas nuevas por ejecución."""
        sabidas = {}

        def consulta(*clave):
            if clave not in sabidas:
                if quedan[0] <= 0:
                    raise DemasiadasConsultas
                quedan[0] -= 1
                sabidas[clave] = consultar(*clave)
            return sabidas[clave]
        return consulta
    if cuenta_de is not None:
        cuenta_de = con_tope(cuenta_de)
    rol_externo = con_tope(rol_externo) if rol_externo is not None else (lambda canal, cuenta_id: 0)
    motivos = []
    por_canal = {}
    for c in cambios:
        canal, resto = canal_de_la_ruta(c.ruta)
        problema = error_de_ruta(c.ruta)
        if problema:
            motivos.append(f"`{c.ruta}`: la ruta {problema}.")
            continue
        if not ID_CANAL.match(canal):
            motivos.append(f"`{c.ruta}`: `{canal}` no puede ser el @ de un canal (de 3 a 20 minúsculas, números y `_`).")
            continue
        if canal in ARROBAS_DEL_PROGRAMA:
            motivos.append(f"`{c.ruta}`: @{canal} está reservado por el programa y no puede ser el @ de un canal.")
            continue
        por_canal.setdefault(canal, []).append((resto, c))

    if len(por_canal) > 1 and not es_dueno:
        motivos.append("La propuesta toca varios canales (" + ", ".join(f"@{c}" for c in sorted(por_canal))
                       + "). Cada propuesta solo puede cambiar un canal: sepáralas.")
        return motivos

    for canal, archivos in sorted(por_canal.items()):
        rol = 5 if es_dueno else rol_por_canal.get(canal, 0)
        try:
            motivos += _comprobar_un_canal(canal, archivos, rol, autor_id, leer, frozenset(ids_duenos), cuenta_de,
                                           lambda cuenta_id, _c=canal: rol_externo(_c, cuenta_id), veto_general,
                                           nombre_parecido, paquetes_de_otros)
        except DemasiadasConsultas:
            motivos.append(f"La propuesta cambia demasiadas cuentas de @{canal} a la vez (el robot tendría que consultar "
                           f"más de {TOPE_CONSULTAS_DUENO if es_dueno else TOPE_CONSULTAS} a GitHub). Divídela en "
                           "varias más pequeñas.")
    return list(dict.fromkeys(motivos))


class DemasiadasConsultas(Exception):
    """La propuesta pediría más consultas a GitHub de las que se permiten en una ejecución (`TOPE_CONSULTAS`)."""


def _leer(c: CambioCanal, lado: str, nombre: str):
    datos = c.antes if lado == "antes" else c.despues
    if datos is None:
        return None
    return leer_json_estricto(datos, c.ruta, TOPES.get(nombre))


def _comprobar_un_canal(canal: str, archivos, rol: int, autor_id: int, leer, ids_duenos, cuenta_de,
                       rol_externo=lambda cuenta_id: 0, veto_general=lambda cuenta_id: None,
                       nombre_parecido=None, paquetes_de_otros=None) -> list:
    motivos = []
    arroba = f"@{canal}"
    solo_aceptar = False
    if rol == 0:
        # Sin rol en el canal solo se puede aceptar la invitación propia o salir (y nada más en la propuesta).
        if [r for r, _ in archivos] != ["miembros.json"]:
            return [f"No eres miembro de {arroba}: no puedes cambiar nada de `canales/{canal}/`."]
        solo_aceptar = True

    for resto, c in archivos:
        if resto.startswith("parches/"):
            continue  # los parches del canal (fase B) los juzga sueltos.py, con el rol en el canal
        if resto == "ficha.json":
            motivos += _comprobar_ficha(canal, c, rol, leer)
            continue
        if resto in ("canal.json", "miembros.json", "lista-negra.json"):
            try:
                antes = _leer(c, "antes", resto)
            except JsonMalo as e:
                if rol < 5:
                    motivos.append(f"`{c.ruta}` de `main` no se puede leer ({e}). Hasta que el Dueño del programa lo "
                                   "arregle, no se acepta ningún cambio sobre él.")
                    continue
                antes = None  # el Dueño lo está arreglando: se juzga como si no existiera
            try:
                despues = _leer(c, "despues", resto)
            except JsonMalo as e:
                motivos.append(str(e))
                continue
            if c.despues is not None and c.tamano > TOPES[resto]:
                motivos.append(f"`{c.ruta}` pesa más de {TOPES[resto] // 1024} KB.")
                continue
            if c.antes is None or c.despues is None:
                if rol < 5:
                    que = "Crear" if c.antes is None else "Borrar"
                    motivos.append(f"`{c.ruta}`: {que} `{resto}` de un canal solo lo hace el Dueño del programa "
                                   "(un canal nuevo se pide con una solicitud).")
                    continue
                if c.despues is None:
                    continue
            if resto == "canal.json":
                propios = _comprobar_canal_json(canal, c.ruta, antes, despues, rol, nombre_parecido, paquetes_de_otros)
            elif resto == "miembros.json":
                vetados, ilegibles = _vetados(canal, archivos, leer, rol)
                motivos += ilegibles
                propios = _comprobar_miembros(c.ruta, antes, despues, rol, autor_id, solo_aceptar, vetados, cuenta_de,
                                              veto_general)
            else:
                propios = _comprobar_lista_negra(c.ruta, antes, despues, rol, autor_id, ids_duenos,
                                                 _miembros_de_main(canal, archivos, leer), cuenta_de, rol_externo)
            motivos += propios
            if propios or rol >= 5 or antes is None or despues is None:
                continue
            # Lo que sí se permite, pero sin mover `main` por nada: ni un archivo que dice lo mismo, ni (con rol bajo, que
            # solo toca su propia fila) reformatear o reordenar lo de los demás.
            if _mismo_contenido(resto, antes, despues):
                motivos.append(f"`{c.ruta}`: no cambia nada de lo que dice (solo el formato o el orden). Cada publicación "
                               "mueve `main` y obliga a rehacer las que están en curso: deja el archivo como estaba.")
            elif resto == "miembros.json" and (solo_aceptar or rol < 3) \
                    and not _solo_su_fila_en_el_texto(c.antes, c.despues, despues, autor_id):
                motivos.append(f"`{c.ruta}`: solo puedes cambiar tu propia fila, y el resto del archivo tiene que quedar "
                               "igual (sin reordenar ni cambiar el formato). Hazlo desde el parcheador.")
            continue

        if "/" not in resto and resto.endswith(EXTENSIONES_LOGO):
            if rol < 3:
                motivos.append(f"`{c.ruta}`: el logo del canal lo cambia un Administrador de {arroba} "
                               f"(tu rol: {NOMBRE_ROL[rol]}).")
            elif c.despues is not None and c.tamano > TOPE_LOGO:
                motivos.append(f"`{c.ruta}`: el logo pesa {c.tamano // 1024} KB y el máximo son {TOPE_LOGO // 1024} KB.")
            elif c.despues is not None:
                esperado = TIPO_POR_EXTENSION[resto[resto.rfind("."):]]
                tipo = tipo_de_imagen(c.despues)
                if tipo is None:
                    motivos.append(f"`{c.ruta}`: no es una imagen PNG, WebP ni JPEG de verdad (se mira su contenido, no el nombre).")
                elif tipo != esperado:
                    motivos.append(f"`{c.ruta}`: por dentro es {tipo.upper()}, no {esperado.upper()}: cámbiale la extensión.")
            continue

        if rol < 5:
            motivos.append(f"`{c.ruta}`: en la carpeta de un canal solo van `canal.json`, `miembros.json`, "
                           "`lista-negra.json`, `ficha.json` y su logo.")
    return motivos


def _comprobar_ficha(canal: str, c: CambioCanal, rol: int, leer) -> list:
    """`ficha.json`: la cambia (y la crea o la borra) un Administrador del canal; tiene que valer entera, decir algo
    distinto de lo que había y, si lleva `destacado`, ese juego tiene que tener parche de este canal tras la propuesta."""
    if rol < ROL_FICHA:
        return [f"`{c.ruta}`: la ficha pública la cambia un Administrador de @{canal} (tu rol: {NOMBRE_ROL[rol]})."]
    if c.despues is None:
        return []  # borrarla deja la ficha vacía: se puede
    if c.tamano > TOPES["ficha.json"]:
        return [f"`{c.ruta}` pesa más de {TOPES['ficha.json'] // 1024} KB."]
    try:
        despues = _leer(c, "despues", "ficha.json")
    except JsonMalo as e:
        return [str(e)]
    motivos = validar_ficha(despues, c.ruta)
    if motivos:
        return motivos
    destacado = despues.get("destacado")
    if destacado is not None and leer(f"{CARPETA_CANALES}{canal}/parches/{destacado}.json", "despues") is None:
        motivos.append(f"`{c.ruta}` › `destacado`: `{destacado}` no es un juego con parche de @{canal}.")
    try:
        antes = _leer(c, "antes", "ficha.json")
    except JsonMalo:
        antes = None  # la de `main` está rota: la nueva la arregla
    if not motivos and rol < 5 and antes is not None and antes == despues:
        motivos.append(f"`{c.ruta}`: no cambia nada de lo que dice (solo el formato o el orden). Cada publicación "
                       "mueve `main` y obliga a rehacer las que están en curso: deja el archivo como estaba.")
    return motivos


PARECE_ORNIZ = "se parece a Orniz, que es del Dueño del programa"


def _solo_orniz(canal, nombre):
    """Sin la lista de canales y reservados de `main` (pruebas sueltas de este módulo): solo «Orniz»."""
    if esqueleto_dudoso(nombre):
        return NO_COMPARABLE
    return PARECE_ORNIZ if canal != CANAL_OFICIAL and nombre_reservado(nombre) else None


def _comprobar_canal_json(canal, ruta, antes, despues, rol, nombre_parecido=None, paquetes_de_otros=None) -> list:
    motivos = validar_canal(despues, canal, ruta)
    if not motivos and isinstance(despues, dict):
        motivos += [f"`{ruta}` › {m}" for m in repositorios_ajenos(
            despues.get("paquetes", []), canal, paquetes_de_otros or {},
            antes.get("paquetes", []) if isinstance(antes, dict) else [])]
    nombre_parecido = nombre_parecido or _solo_orniz
    if rol < 5 and isinstance(despues, dict) and isinstance(despues.get("nombre"), str) \
            and not (isinstance(antes, dict) and antes.get("nombre") == despues.get("nombre")) \
            and (parecido := nombre_parecido(canal, despues["nombre"])):
        motivos.append(f"`{ruta}` › `nombre`: «{despues['nombre']}» {parecido}.")
    if motivos or not isinstance(antes, dict):
        return motivos
    for campo in _diferencias(antes, despues):
        hace_falta = ROL_CAMPO_CANAL.get(campo, 5)
        if campo == "estado" and "bloqueado" in (antes.get("estado"), despues.get("estado")):
            hace_falta = 5
        if rol < hace_falta:
            motivos.append(f"`{ruta}` › `{campo}`: lo cambia el {NOMBRE_ROL[hace_falta]} (tu rol: {NOMBRE_ROL[rol]}).")
    return motivos


def _puede_sobre(rol: int, otro: int) -> bool:
    """Cada uno gestiona solo por debajo de su rol: un Propietario del canal no toca a otro Propietario (solo puede
    irse él). El Dueño del programa, a cualquiera."""
    return rol >= 5 or rol > otro


def _vetados(canal, archivos, leer, rol):
    """(cuentas de la lista negra del canal —la de `main` y la de la propuesta a la vez—, motivos si no se lee)."""
    ruta = f"{CARPETA_CANALES}{canal}/lista-negra.json"
    cambio = next((c for resto, c in archivos if resto == "lista-negra.json"), None)
    lados = (("antes", cambio.antes), ("despues", cambio.despues)) if cambio else (("antes", leer(ruta, "antes")),)
    vetados, motivos = set(), []
    for lado, datos in lados:
        if datos is None:
            continue
        try:
            vetados |= set(leer_lista_negra(leer_json_estricto(datos, ruta, TOPES["lista-negra.json"]), ruta)[0].usuarios)
        except JsonMalo as e:
            if lado == "antes" and rol < 5:
                motivos.append(f"`{ruta}` de `main` no se puede leer ({e}): sin ella no se sabe quién está vetado. "
                               "Hasta que el Dueño del programa lo arregle, no se aceptan cambios de miembros.")
            # La de la propuesta: su error ya sale al comprobar ese archivo.
    return vetados, motivos


def _miembros_de_main(canal, archivos, leer) -> dict:
    """{id: Miembro} de `main` (para saber el rol de a quién se veta)."""
    ruta = f"{CARPETA_CANALES}{canal}/miembros.json"
    cambio = next((c for resto, c in archivos if resto == "miembros.json"), None)
    datos = cambio.antes if cambio else leer(ruta, "antes")
    if datos is None:
        return {}
    try:
        return leer_miembros(leer_json_estricto(datos, ruta, TOPES["miembros.json"]), ruta)[0]
    except JsonMalo:
        return {}  # `leer_canales` ya para al robot si los miembros de `main` están rotos


def _cuenta_que_no_es(cuenta_de, cuenta_id, cuenta: str, donde: str):
    """Motivo si `cuenta` no es el nombre actual en GitHub de la cuenta `cuenta_id` (o None si cuadra)."""
    if cuenta_de is None:
        return None
    real = cuenta_de(cuenta_id)
    if not real:
        return f"{donde}: la cuenta {cuenta_id} no existe en GitHub."
    if real.lower() != cuenta.lower():
        return (f"{donde}: la cuenta {cuenta_id} se llama `{real}` en GitHub, no `{cuenta}` "
                "(el nombre tiene que ser el de esa cuenta; no se puede poner el de otra persona).")
    return None


def _comprobar_miembros(ruta, antes, despues, rol, autor_id, solo_aceptar, vetados, cuenta_de=None,
                        veto_general=lambda cuenta_id: None) -> list:
    m_despues, motivos = leer_miembros(despues, ruta)
    if motivos:
        return motivos
    m_antes, _ = leer_miembros(antes, ruta) if antes is not None else ({}, [])

    for mid in sorted(set(m_despues) & vetados):
        motivos.append(f"`{ruta}`: `{m_despues[mid].cuenta}` está en la lista negra del canal: no puede ser miembro.")
    # Lista negra general (fase D): ni entrar ni seguir. Se mira a todos los que la propuesta añade o cambia (los
    # demás ya se revisan al vetarlos); cada trozo se lee una vez (`listas.Consultas`).
    for mid in [m for m in sorted(m_despues) if m_antes.get(m) != m_despues[m]]:
        if motivo := veto_general(mid):
            motivos.append(f"`{ruta}`: `{m_despues[mid].cuenta}` está en la lista negra del programa ({motivo}): no "
                           "puede ser miembro de ningún canal.")

    # El nombre que acompaña a un id nuevo o cambiado tiene que ser el de esa cuenta (también para el Dueño). Se pregunta
    # a GitHub, así que antes se mira qué filas puede tocar quien propone: sin rol (o con rol bajo) solo la suya, y el
    # resto ya se rechaza abajo sin preguntar nada (tercera revisión, N2).
    por_comprobar = [mid for mid, d in sorted(m_despues.items())
                     if m_antes.get(mid) is None or m_antes[mid].cuenta != d.cuenta]
    if rol < 5 and (solo_aceptar or rol < 3):
        por_comprobar = [mid for mid in por_comprobar if mid == autor_id]
    if rol < 5 and len(por_comprobar) > TOPE_FILAS_CON_CUENTA:
        return motivos + [f"`{ruta}`: la propuesta añade o cambia {len(por_comprobar)} miembros a la vez y el máximo son "
                          f"{TOPE_FILAS_CON_CUENTA}. Divídela en varias."]
    for mid in por_comprobar:
        problema = _cuenta_que_no_es(cuenta_de, mid, m_despues[mid].cuenta, f"`{ruta}`")
        if problema:
            motivos.append(problema)

    if rol >= 5:
        return motivos

    for mid in sorted(m_antes.keys() | m_despues.keys()):
        a, d = m_antes.get(mid), m_despues.get(mid)
        if a is not None and d is not None and a.fila == d.fila:
            continue
        quien = (d or a).cuenta
        if mid == autor_id:
            if a is not None and d is None:
                continue  # salir del canal (si era el último Propietario ya lo ha parado `leer_miembros`)
            if a is not None and d is not None:
                otros = {k for k in _diferencias(a.fila, d.fila)}
                # Aceptar la propia invitación y/o poner al día el propio nombre tras renombrar la cuenta.
                if otros <= {"estado", "cuenta"} and (a.estado == d.estado or (a.estado == "invitado" and d.estado == "activo")):
                    continue
            motivos.append(f"`{ruta}`: no puedes cambiar tu propia fila (solo aceptar tu invitación, corregir tu nombre "
                           "de cuenta o salir del canal).")
            continue
        if solo_aceptar or rol < 3:
            motivos.append(f"`{ruta}`: invitar, cambiar o quitar miembros es cosa de un Administrador del canal "
                           f"(tu rol: {NOMBRE_ROL[rol]}).")
            break
        if a is None:
            if d.estado != "invitado":
                motivos.append(f"`{ruta}`: `{quien}` tiene que entrar como `invitado`; pasa a `activo` cuando él mismo "
                               "acepta la invitación.")
            if d.rol == 4:
                motivos.append(f"`{ruta}`: no se puede invitar a nadie como Propietario. Invítalo con otro rol y, cuando "
                               "acepte, un Propietario lo asciende.")
            elif not _puede_sobre(rol, d.rol):
                motivos.append(f"`{ruta}`: como {NOMBRE_ROL[rol]} solo puedes invitar por debajo de tu rol "
                               f"(`{quien}` iría de {NOMBRE_ROL[d.rol]}).")
            if d.fila.get("invitadoPor") != autor_id:
                motivos.append(f"`{ruta}`: en `{quien}`, `invitadoPor` tiene que ser tu cuenta ({autor_id}).")
            continue
        if not _puede_sobre(rol, a.rol):
            motivos.append(f"`{ruta}`: como {NOMBRE_ROL[rol]} no puedes cambiar ni quitar a `{quien}` "
                           f"({NOMBRE_ROL[a.rol]}).")
            continue
        if d is None:
            continue
        if a.estado != d.estado:
            motivos.append(f"`{ruta}`: solo `{quien}` puede aceptar su invitación.")
        if d.rol != a.rol:
            if d.rol == 4 and (rol < 4 or not d.activo):
                motivos.append(f"`{ruta}`: hacer Propietario a alguien solo lo hace otro Propietario, y sobre un miembro activo.")
            elif d.rol != 4 and not _puede_sobre(rol, d.rol):
                motivos.append(f"`{ruta}`: como {NOMBRE_ROL[rol]} no puedes dar a `{quien}` el rol {NOMBRE_ROL[d.rol]}.")
        for campo in ("invitadoPor", "desde"):
            if a.fila.get(campo) != d.fila.get(campo):
                motivos.append(f"`{ruta}`: `{campo}` de `{quien}` no se cambia.")
    return motivos


# Un veto antiguo sin `por` se trata como puesto por un Administrador: un Administrador no lo deshace, un Propietario sí.
ROL_VETO_SIN_POR = 3


def _comprobar_lista_negra(ruta, antes, despues, rol, autor_id, ids_duenos, miembros_main, cuenta_de=None,
                           rol_externo=lambda cuenta_id: 0) -> list:
    l_despues, motivos = leer_lista_negra(despues, ruta)
    if motivos:
        return motivos
    # El Dueño del programa está por encima de cualquier veto: nadie lo puede vetar, ni él mismo.
    for mid in sorted(set(l_despues.usuarios) & ids_duenos):
        motivos.append(f"`{ruta}`: la cuenta {mid} es del Dueño del programa y no se puede vetar.")
    if rol < 3:
        return motivos + [f"`{ruta}`: la lista negra del canal la cambia un Administrador (tu rol: {NOMBRE_ROL[rol]})."]
    l_antes, _ = leer_lista_negra(antes, ruta)
    cambiadas = [m for m in l_antes.usuarios.keys() | l_despues.usuarios.keys()
                 if l_antes.usuarios.get(m) != l_despues.usuarios.get(m)]
    if rol < 5 and len(cambiadas) > TOPE_FILAS_CON_CUENTA:
        # Cada veto que cambia pide a GitHub el rol de esa cuenta: se para antes de preguntar nada (N2).
        return motivos + [f"`{ruta}`: la propuesta pone o quita {len(cambiadas)} vetos a la vez y el máximo son "
                          f"{TOPE_FILAS_CON_CUENTA}. Divídela en varias."]

    def rol_de(cuenta_id) -> int:
        if cuenta_id in ids_duenos:
            return 5
        m = miembros_main.get(cuenta_id)
        # El mismo rol que le da el robot (archivo o, en el canal oficial, el equipo de GitHub), sin contar el veto.
        return max(m.rol if m is not None else 0, int(rol_externo(cuenta_id) or 0))

    for mid in sorted(l_antes.usuarios.keys() | l_despues.usuarios.keys()):
        a, d = l_antes.usuarios.get(mid), l_despues.usuarios.get(mid)
        if a == d:
            continue
        objetivo = rol_de(mid)
        if a is not None:
            # Quitar (o cambiar) un veto: solo sobre alguien por debajo de tu rol, y sin deshacer lo de alguien que
            # está a tu altura o por encima (salvo que el veto sea tuyo).
            puso = a.get("por")
            rol_puso = ROL_VETO_SIN_POR if puso is None else rol_de(puso)
            if rol < 5 and not (_puede_sobre(rol, objetivo) and (puso == autor_id or _puede_sobre(rol, rol_puso))):
                motivos.append(f"`{ruta}`: como {NOMBRE_ROL[rol]} no puedes quitar ni cambiar el veto a la cuenta {mid} "
                               f"(es {NOMBRE_ROL[objetivo]}; lo puso {NOMBRE_ROL[rol_puso] if puso != autor_id else 'tu cuenta'}).")
                continue
        if d is not None:
            if rol < 5 and not _puede_sobre(rol, objetivo):
                motivos.append(f"`{ruta}`: como {NOMBRE_ROL[rol]} solo puedes vetar a quien está por debajo de tu rol "
                               f"(la cuenta {mid} es {NOMBRE_ROL[objetivo]}).")
            if rol < 5 and d.get("por") != autor_id:
                motivos.append(f"`{ruta}`: en el veto a la cuenta {mid}, `por` tiene que ser tu cuenta ({autor_id}).")
            if "cuenta" in d and (a is None or a.get("cuenta") != d["cuenta"]):
                problema = _cuenta_que_no_es(cuenta_de, mid, d["cuenta"], f"`{ruta}`")
                if problema:
                    motivos.append(problema)
    if rol >= 4:
        return motivos
    quitados = [f"`{f['patron']}`" for f in l_antes.archivos if f not in l_despues.archivos] \
        + [f"`{f['hash'][:15]}…`" for f in l_antes.huellas if f not in l_despues.huellas]
    if quitados:
        motivos.append(f"`{ruta}`: un Administrador puede añadir a la lista negra y quitar vetos de cuentas por debajo de "
                       "su rol, pero quitar archivos o huellas es del Propietario del canal (" + ", ".join(quitados) + ").")
    return motivos


# ───────────────────────────────────────── El Dueño del programa ─────────────────────────────────────────

def leer_duenos(texto: str):
    """`normas/propietario.json` → (ids, cuentas en minúsculas).

    `duenos` (`[{ "id", "cuenta" }]`) es lo que vale desde la fase A; `propietario` (solo cuentas) se queda para los
    parcheadores 0.2.x y para el robot mientras no haya ids.
    """
    datos = json.loads(texto)
    if not isinstance(datos, dict):
        raise ValueError("`normas/propietario.json` tiene que ser un objeto.")
    ids, cuentas = set(), set()
    for fila in datos.get("duenos") or []:
        if not isinstance(fila, dict) or not _es_id(fila.get("id")):
            raise ValueError("`normas/propietario.json`: cada fila de `duenos` necesita su `id` numérico.")
        ids.add(fila["id"])
        if isinstance(fila.get("cuenta"), str):
            cuentas.add(fila["cuenta"].strip().lower())
    viejas = datos.get("propietario")
    if isinstance(viejas, str):
        viejas = [viejas]
    if isinstance(viejas, list):
        cuentas |= {c.strip().lower() for c in viejas if isinstance(c, str) and c.strip()}
    if not ids and not cuentas:
        raise ValueError("`normas/propietario.json` no dice quién es el Dueño (`duenos` o `propietario`).")
    return ids, cuentas
