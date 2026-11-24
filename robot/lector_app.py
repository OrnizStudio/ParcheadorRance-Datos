"""El catálogo tal como lo lee el parcheador (`Parcheador.Core/Catalogos/LectorCatalogo.cs`).

Regla: lo que la app rechaza, el robot lo rechaza. Si el robot dejara publicar un catálogo que la app no puede leer,
todos los parcheadores se quedarían con el que tienen en caché, sin enterarse de nada más, hasta que alguien lo
arreglara. Y si dejara subir `versionCatalogo` a un número que ya no cabe en el `int` de la app, ninguna versión
posterior podría ser «más nueva»: el catálogo se quedaría congelado para siempre en todos los parcheadores.

Este archivo copia el modelo de `Catalogo.cs`, `Juego.cs` y `Versiones.cs` (nombres en camelCase, tipos y campos
obligatorios) y las comprobaciones de `LectorCatalogo.Validar`. Si cambia el modelo de la app, cambia esto.
Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import json

INT32 = (-(2 ** 31), 2 ** 31 - 1)
INT64 = (-(2 ** 63), 2 ** 63 - 1)

# `versionCatalogo`: cuánto puede subir de una vez y hasta dónde. La app 0.2.x la guarda en un `int` (hasta
# 2 147 483 647); el tope deja mucho margen por debajo para que nunca se acerque. Una propuesta normal sube 1.
SALTO_MAXIMO_VERSION = 1000
VERSION_MAXIMA = 2 ** 30 - 1
# Desde un `main` con una versión absurda solo la arregla quien manda en todo el repositorio, y como mucho hasta aquí
# (es la versión de rescate del Modo equipo, `VersionesCatalogo.Rescate`): muy lejos del tope, para que el arreglo no
# deje a nadie la puerta abierta para volver a congelarlo (cuarta revisión, 2.4).
VERSION_RESCATE = 2 ** 29
QUIEN_RESCATA = "el Dueño del programa"

# El lector de la app (System.Text.Json) no pasa de 64 niveles de anidación.
PROFUNDIDAD_MAXIMA = 64

# Más cifras que esto no caben ni en un `long`: no hace falta ni convertirlas.
CIFRAS_MAXIMAS = 20

# ─────────────────────────────── El modelo de la app ───────────────────────────────
# Cada campo: (tipo, obligatorio). Tipos: "int" y "long" (enteros que no admiten null), "int?" y "long?" (admiten
# null), "long|texto?" (GogId: número o texto con un número), "bool" (true/false, sin null), "texto" (texto o null),
# "hash" (texto `algoritmo:hex`, sin null), "enum" (cualquier cosa: la app tolera valores desconocidos), el nombre de
# otro objeto del modelo (objeto o null), ["tipo"] (lista o null; sus elementos no pueden ser null) y
# {"texto"} (diccionario de texto a texto, o null).

MODELO = {
    "Catalogo": {
        "esquema": ("int", True), "versionCatalogo": ("int", True), "launcher": ("InfoLauncher", False),
        "grupo": ("Grupo", False), "etiquetas": (["Etiqueta"], False), "juegos": (["Juego"], False),
    },
    "InfoLauncher": {
        "ultimaVersion": ("texto", False), "url": ("texto", False), "tamano": ("long?", False),
        "hash": ("texto", False), "versionMinima": ("texto", False), "motivoUrgente": ("texto", False),
        "novedades": (["texto"], False),
    },
    "Grupo": {"nombre": ("texto", False), "logo": ("texto", False), "enlaces": (["Enlace"], False)},
    "Enlace": {"tipo": ("texto", False), "url": ("texto", False), "nombre": ("texto", False)},
    "Etiqueta": {
        "id": ("texto", True), "nombre": ("texto", False), "color": ("texto", False), "icono": ("texto", False),
        "descripcion": ("texto", False),
    },
    "Juego": {
        "id": ("texto", True), "habilitado": ("bool", False), "disponibilidad": ("enum", False),
        "pruebas": ("bool", False), "orden": ("int", False), "titulo": ("texto", False),
        "tituloCorto": ("texto", False), "tituloOriginal": ("texto", False), "relacionado": ("texto", False),
        "etiquetas": (["texto"], False), "estado": ("enum", False), "progreso": ("Progreso", False),
        "sinopsis": ("texto", False), "imagenes": ("Imagenes", False), "creditos": (["Credito"], False),
        "deteccion": ("Deteccion", False), "ediciones": (["Edicion"], False), "opciones": (["Opcion"], False),
        "parche": ("Parche", False),
    },
    "Progreso": {"traduccion": ("int", False), "revision": ("int", False), "imagenes": ("int", False)},
    "Imagenes": {
        "icono": ("texto", False), "banner": ("texto", False), "fondo": ("texto", False), "logo": ("texto", False),
        "portada": ("texto", False),
    },
    "Credito": {"rol": ("texto", False), "personas": (["texto"], False)},
    "Deteccion": {
        "steamAppId": ("long?", False), "gogId": ("long|texto?", False), "ejecutables": (["texto"], False),
    },
    "Edicion": {
        "id": ("texto", True), "nombre": ("texto", False), "grupo": ("texto", False),
        "notaEdicion": ("texto", False), "disponibilidad": ("enum", False), "pruebas": ("bool", False),
        "huella": (["ArchivoHuella"], False), "huellasParcheadas": (["HuellaParcheada"], False),
        "ignorar": (["texto"], False), "ignorados": ("ResumenIgnorados", False), "estado": ("enum", False),
        "progreso": ("Progreso", False), "parche": ("Parche", False), "versiones": (["VersionParche"], False),
        "imagenes": ("Imagenes", False), "etiquetas": (["texto"], False), "contenido": ("Contenido", False),
        "lanzar": ("Lanzamiento", False), "tiendas": (["Tienda"], False), "restricciones": ({"texto"}, False),
        "avisoRestricciones": ("texto", False),
    },
    "ArchivoHuella": {
        "ruta": ("texto", True), "tamano": ("long", True), "hashParcial": ("hash", True), "hash": ("hash", True),
    },
    "ResumenIgnorados": {"archivos": ("int", False), "bytes": ("long", False)},
    "HuellaParcheada": {"version": ("texto", True), "archivos": (["ArchivoHuella"], False)},
    "Contenido": {"texto": ("bool", False), "imagenes": ("bool", False), "testing": ("enum", False)},
    "Lanzamiento": {"steam": ("bool", False), "ejecutable": ("texto", False), "argumentos": ("texto", False)},
    "Tienda": {"nombre": ("texto", False), "url": ("texto", False), "gratis": ("bool", False)},
    "Opcion": {
        "id": ("texto", True), "nombre": ("texto", False), "tipo": ("enum", False), "padre": ("texto", False),
        "valores": (["ValorOpcion"], False), "porDefecto": ("texto", False), "nota": ("texto", False),
    },
    "ValorOpcion": {"id": ("texto", True), "nombre": ("texto", False), "fija": ({"texto"}, False)},
    "Parche": {
        "version": ("texto", False), "fecha": ("texto", False), "notas": ("texto", False),
        "pruebas": ("bool", False), "paquetes": (["PaqueteParche"], False),
    },
    "PaqueteParche": {
        "edicion": ("texto", True), "url": ("texto", True), "tamano": ("long", True), "hash": ("hash", True),
    },
    "VersionParche": {
        "version": ("texto", False), "estado": ("enum", False), "fecha": ("texto", False),
        "autor": ("texto", False), "notas": ("texto", False), "motivo": ("texto", False),
        "motivoPublico": ("bool", False), "fechaRetirada": ("texto", False), "paquete": ("PaqueteVersion", False),
    },
    "PaqueteVersion": {"url": ("texto", False), "tamano": ("long", False), "hash": ("texto", False)},
}


class JsonIlegible(ValueError):
    def __init__(self, motivo, sintaxis=False):
        super().__init__(motivo)
        self.sintaxis = sintaxis  # un error de escritura (coma, comilla…), no de contenido


def _sin_repetidas(pares):
    vistas = set()
    for clave, _ in pares:
        if clave in vistas:
            raise JsonIlegible(f"repite la clave `{_corta(clave)}` en el mismo objeto")
        vistas.add(clave)
    return dict(pares)


def _entero(texto):
    if len(texto.lstrip("-")) > CIFRAS_MAXIMAS:
        raise JsonIlegible(f"tiene un número de {len(texto.lstrip('-'))} cifras")
    return int(texto)


def _constante(nombre):
    raise JsonIlegible(f"usa `{nombre}`, que no es JSON")


def _decimal(texto):
    valor = float(texto)
    if valor in (float("inf"), float("-inf")):
        raise JsonIlegible(f"tiene un número demasiado grande (`{_corta(texto)}`)")
    return valor


def _corta(texto, largo=40):
    texto = "".join(c if c.isprintable() and not 0xD800 <= ord(c) <= 0xDFFF else "?" for c in str(texto))
    return texto if len(texto) <= largo else texto[:largo] + "…"


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
            maximo = max(maximo, hondo)
        elif c in "]}":
            hondo -= 1
    return maximo


def leer(datos):
    """El catálogo como objeto de Python, o JsonIlegible con el motivo. `datos` son los bytes del archivo (o texto).

    UTF-8 estricto (sin BOM: la app no lo escribe), sin claves repetidas, sin `NaN` ni `Infinity`, sin números
    enormes y con 64 niveles de anidación como mucho.
    """
    if isinstance(datos, (bytes, bytearray)):
        if datos.startswith(b"\xef\xbb\xbf"):
            raise JsonIlegible("empieza con una marca BOM; guárdalo como UTF-8 sin BOM")
        try:
            datos = bytes(datos).decode("utf-8")
        except UnicodeDecodeError as e:
            raise JsonIlegible(f"no es UTF-8 válido (byte {e.start})") from None
    if _profundidad(datos) > PROFUNDIDAD_MAXIMA:
        raise JsonIlegible(f"tiene más de {PROFUNDIDAD_MAXIMA} niveles de `[` y `{{` uno dentro de otro")
    try:
        return json.loads(datos, object_pairs_hook=_sin_repetidas, parse_int=_entero, parse_constant=_constante,
                          parse_float=_decimal)
    except json.JSONDecodeError as e:
        raise JsonIlegible(f"no es un JSON válido (línea {e.lineno}, columna {e.colno}): {e.msg}", True) from None
    except (RecursionError, ValueError) as e:
        if isinstance(e, JsonIlegible):
            raise
        raise JsonIlegible("no es un JSON que se pueda leer") from None


def _tiene_sustituto(texto: str) -> bool:
    return any(0xD800 <= ord(c) <= 0xDFFF for c in texto)


def _es_entero(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _hash_valido(valor) -> bool:
    # ValorHash.TryParse: `algoritmo:hex`, algo antes de los dos puntos y un número par de cifras hexadecimales.
    if not isinstance(valor, str) or not valor.strip():
        return False
    algoritmo, dos_puntos, hexa = valor.partition(":")
    return bool(algoritmo) and bool(dos_puntos) and bool(hexa) and len(hexa) % 2 == 0 \
        and all(c in "0123456789abcdefABCDEF" for c in hexa)


def ruta_segura(ruta) -> bool:
    """`RutaSegura.EsRelativaSegura` de la app: relativa, sin `..`, sin unidad y sin raíz."""
    if not isinstance(ruta, str) or not ruta.strip() or ":" in ruta or "\0" in ruta or ruta[0] in "/\\":
        return False
    for segmento in ruta.replace("\\", "/").split("/"):
        if segmento in ("", ".", "..") or segmento[-1] in ". ":
            return False
    return True


def _tipo(valor, tipo, donde, errores):
    if isinstance(tipo, list):
        if valor is None:
            return
        if not isinstance(valor, list):
            errores.append(f"{donde} tiene que ser una lista `[ … ]`.")
            return
        for i, elemento in enumerate(valor):
            if elemento is None:
                errores.append(f"{donde}[{i}] es `null`.")
            else:
                _tipo(elemento, tipo[0], f"{donde}[{i}]", errores)
        return
    if isinstance(tipo, set):
        if valor is None:
            return
        if not isinstance(valor, dict) or not all(isinstance(v, str) for v in valor.values()):
            errores.append(f"{donde} tiene que ser un objeto con textos `{{ \"clave\": \"valor\" }}`.")
        return
    if tipo in MODELO:
        if valor is None:
            return
        if not isinstance(valor, dict):
            errores.append(f"{donde} tiene que ser un objeto `{{ … }}`.")
            return
        for campo, (subtipo, obligatorio) in MODELO[tipo].items():
            if campo not in valor:
                if obligatorio:
                    errores.append(f"{donde} no tiene `{campo}`, que es obligatorio.")
                continue
            if obligatorio and valor[campo] is None:
                # La app no admite `null` en un campo obligatorio (cuarta revisión, 2.6).
                errores.append(f"{donde} › `{campo}` no puede ser `null`: es obligatorio.")
                continue
            _tipo(valor[campo], subtipo, f"{donde} › `{campo}`", errores)
        return
    if tipo == "enum":
        return
    if tipo == "texto":
        if valor is not None and not isinstance(valor, str):
            errores.append(f"{donde} tiene que ser un texto entre comillas.")
        return
    if tipo == "bool":
        if not isinstance(valor, bool):
            errores.append(f"{donde} tiene que ser `true` o `false`.")
        return
    if tipo == "hash":
        if not _hash_valido(valor):
            errores.append(f"{donde} tiene que ser un hash `algoritmo:hex` (por ejemplo `blake3:…`).")
        return
    if tipo == "long|texto?":
        if valor is None:
            return
        if isinstance(valor, str):
            texto = valor.strip()
            numero = texto[1:] if texto[:1] in "+-" else texto
            if texto != valor or not numero.isascii() or not numero.isdigit():
                errores.append(f"{donde} tiene que ser un número (o un número entre comillas).")
                return
            valor = int(texto)
        tipo = "long?"
    nulo = tipo.endswith("?")
    base = tipo.rstrip("?")
    if valor is None and nulo:
        return
    minimo, maximo = INT32 if base == "int" else INT64
    if not _es_entero(valor):
        errores.append(f"{donde} tiene que ser un número entero, sin decimales ni comillas.")
    elif not minimo <= valor <= maximo:
        errores.append(f"{donde} vale {valor}, que no cabe en el parcheador (de {minimo} a {maximo}).")


def _sustitutos(valor, donde, errores, limite=5):
    """Textos con medio carácter (`\\ud800` suelto): la app no los puede leer."""
    pendientes = [(valor, donde)]
    while pendientes and len(errores) < limite:
        actual, sitio = pendientes.pop()
        if isinstance(actual, str):
            if _tiene_sustituto(actual):
                errores.append(f"{sitio} tiene un carácter partido (`\\uD800`–`\\uDFFF` suelto).")
        elif isinstance(actual, list):
            pendientes += [(v, f"{sitio}[{i}]") for i, v in enumerate(actual)]
        elif isinstance(actual, dict):
            for clave, v in actual.items():
                if _tiene_sustituto(clave):
                    errores.append(f"{sitio} tiene una clave con un carácter partido (`\\uD800`–`\\uDFFF` suelto).")
                pendientes.append((v, f"{sitio} › `{_corta(clave)}`"))


def errores_de_la_app(cat) -> list:
    """Por qué la app no podría leer este catálogo (lista vacía: lo lee). `cat` ya es un objeto de Python."""
    errores = []
    _sustitutos(cat, "El catálogo", errores)
    if errores:
        return errores
    if not isinstance(cat, dict):
        return ["`catalogo.json` tiene que ser un objeto `{ … }`."]
    _tipo(cat, "Catalogo", "`catalogo.json`", errores)
    if errores:
        return errores[:20]

    # LectorCatalogo.Validar
    if cat["esquema"] != 1:
        errores.append(f"`esquema` vale {cat['esquema']} y el parcheador solo entiende el 1.")
    for juego in cat.get("juegos") or []:
        jid = juego["id"] or ""
        for edicion in juego.get("ediciones") or []:
            donde = f"`{_corta(jid)}` › edición `{_corta(edicion['id'] or '')}`"
            archivos = list(edicion.get("huella") or [])
            for parcheada in edicion.get("huellasParcheadas") or []:
                if not (parcheada["version"] or "").strip():
                    errores.append(f"{donde}: hay una huella parcheada sin versión.")
                archivos += parcheada.get("archivos") or []
            for archivo in archivos:
                if not ruta_segura(archivo["ruta"]):
                    errores.append(f"{donde}: la ruta de huella `{_corta(archivo['ruta'])}` no es válida "
                                   "(relativa, sin `..`, sin `:` y sin `/` al principio).")
            ejecutable = (edicion.get("lanzar") or {}).get("ejecutable")
            if ejecutable is not None and not ruta_segura(ejecutable):
                errores.append(f"{donde}: el ejecutable `{_corta(ejecutable)}` no es una ruta relativa válida.")
        ids = [o["id"] for o in juego.get("opciones") or []]
        if any(not (i or "").strip() for i in ids) or len(set(ids)) != len(ids):
            errores.append(f"`{_corta(jid)}`: hay una opción sin `id` o repetida.")
    return errores[:20]


def errores_de_version(version, version_antes, puede_rescatar=False) -> list:
    """`versionCatalogo` tiene que subir, poco y sin acercarse al tope del `int` de la app.

    `version_antes` es la de `main` (None si no hay o no se puede leer). Si la de `main` ya es absurda (fuera de
    1…VERSION_MAXIMA), solo quien `puede_rescatar` la devuelve a un valor normal, como mucho VERSION_RESCATE: los
    parcheadores nuevos aceptan bajar desde una versión absurda.
    """
    if not _es_entero(version):
        return ["Falta `versionCatalogo` (un número entero)."]
    if not 1 <= version <= VERSION_MAXIMA:
        return [f"`versionCatalogo` vale {version} y tiene que estar entre 1 y {VERSION_MAXIMA}: un número más alto "
                "dejaría a los parcheadores sin poder recibir catálogos nuevos."]
    if not _es_entero(version_antes) or not 1 <= version_antes <= VERSION_MAXIMA:
        if not puede_rescatar:
            return [f"`versionCatalogo` de `main` no es un número normal ({_corta(version_antes)}). Arreglarlo lo hace "
                    f"solo {QUIEN_RESCATA}: hasta entonces no se acepta ningún cambio del catálogo."]
        if version > VERSION_RESCATE:
            return [f"Para arreglar `versionCatalogo` ponlo como mucho a {VERSION_RESCATE} (es el número de rescate: "
                    "queda por encima de cualquier versión normal anterior y lejos del tope)."]
        return []
    if version <= version_antes:
        return [f"`versionCatalogo` tiene que subir: ahora vale {version_antes} y la propuesta lo deja en {version}. "
                "Si no sube, los parcheadores de los usuarios no se enteran del cambio. "
                f"Ponlo a {version_antes + 1} (si otra propuesta se ha publicado antes que la tuya, actualiza la tuya "
                "y vuelve a subirlo)."]
    if version > version_antes + SALTO_MAXIMO_VERSION:
        return [f"`versionCatalogo` salta de {version_antes} a {version}. Basta con subirlo 1 (a {version_antes + 1}); "
                f"como mucho {SALTO_MAXIMO_VERSION} de una vez."]
    return []
