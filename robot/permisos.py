#!/usr/bin/env python3
"""Robot de permisos del repositorio de datos del Parcheador Rance.

Mira qué cambia una propuesta (pull request) y decide si quien la hace tiene permiso, según su rol:

  Administrador  todo.
  Editor         el contenido de los juegos que ya existen (y sus imágenes). No puede añadir, quitar,
                 publicar ni ocultar juegos, ni tocar el parcheador, el grupo o las etiquetas del catálogo.
  Colaborador    solo textos y notas, etiquetas y estado de la traducción de lo que ya existe.

Y, para todos (también Administradores y Propietario): ningún parche puede tocar los archivos de
`normas/archivos-prohibidos.json` (protección anticopia y cracks). Ver «Archivos prohibidos» más abajo.

Este archivo tiene dos partes:

  1. Las reglas (`comprobar`): no hablan con GitHub ni con git; reciben los datos y devuelven los motivos
     de rechazo. Se prueban con `python -m unittest discover -s robot/pruebas`.
  2. La parte de GitHub (`main`): averigua el rol, lee el cambio con git, comenta el resultado y fusiona.

Solo usa la biblioteca estándar de Python. Nunca ejecuta nada de la propuesta: solo lee sus archivos.
"""
from __future__ import annotations

import copy
import enum
import fnmatch
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field

RUTA_CATALOGO = "catalogo/catalogo.json"
CARPETA_JUEGOS = "catalogo/juegos/"
TAMANO_MAXIMO_CATALOGO = 8 * 1024 * 1024  # el mismo tope que aplica el parcheador al descargarlo
TAMANO_MAXIMO_IMAGEN = 5 * 1024 * 1024
EXTENSIONES_IMAGEN = (".png", ".jpg", ".jpeg", ".webp")
ID_VALIDO = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
HASH_VALIDO = re.compile(r"^blake3:[0-9a-f]{64}$")


# ───────────────────────────────────────── Roles y permisos ─────────────────────────────────────────

class Rol(enum.IntEnum):
    NINGUNO = 0
    COLABORADOR = 1
    EDITOR = 2
    ADMINISTRADOR = 3

    @property
    def nombre(self) -> str:
        return {0: "sin rol", 1: "Colaborador", 2: "Editor", 3: "Administrador"}[int(self)]


@dataclass(frozen=True)
class Permisos:
    """Lo que puede hacer una persona: un rol para todo el repositorio y, en el futuro, roles por juego.

    Las reglas nunca miran `rol_global` para decidir sobre un juego: preguntan `en_juego(id)`. Así, cuando
    existan los líderes por juego, bastará con rellenar `por_juego` (ver `leer_equipo`).
    """
    rol_global: Rol
    por_juego: dict = field(default_factory=dict)

    def en_juego(self, juego_id: str) -> Rol:
        return max(self.rol_global, self.por_juego.get(juego_id, Rol.NINGUNO))

    def el_menor(self, otro: "Permisos") -> "Permisos":
        juegos = set(self.por_juego) & set(otro.por_juego)
        return Permisos(min(self.rol_global, otro.rol_global),
                        {j: min(self.por_juego[j], otro.por_juego[j]) for j in juegos})


# Campos que puede cambiar un Colaborador (ARQUITECTURA §8, rol 4): textos y notas, etiquetas y estado
# de la traducción. Nada más: ni créditos, ni imágenes, ni paquetes.
CAMPOS_COLABORADOR_JUEGO = ("sinopsis", "etiquetas", "estado", "progreso")
CAMPOS_COLABORADOR_EDICION = ("notaEdicion", "etiquetas", "estado", "progreso", "contenido")
CAMPOS_COLABORADOR_PARCHE = ("notas",)

# Campos de un juego que deciden si el público lo ve. Un Editor no publica ni oculta juegos.
CAMPOS_PUBLICAR_JUEGO = ("habilitado", "pruebas")

# Claves de la raíz del catálogo que cualquiera con permiso sobre un juego puede tocar.
RAIZ_LIBRE = ("juegos", "versionCatalogo")


# ───────────────────────────────────────────── Reglas ─────────────────────────────────────────────

@dataclass(frozen=True)
class Cambio:
    """Un archivo que la propuesta añade (A), modifica (M) o borra (D)."""
    ruta: str
    estado: str
    modo: str = "100644"
    tamano: int = 0


def comprobar(cambios, antes, despues, permisos: Permisos, prohibidos=(), leer_paquete=None) -> list:
    """Devuelve los motivos por los que la propuesta no se acepta (lista vacía = se acepta).

    `antes` y `despues` son el texto de `catalogo/catalogo.json` en `main` y tras aplicar la propuesta
    (None si no existe). `prohibidos` son los patrones de `normas/archivos-prohibidos.json` (de `main`) y
    `leer_paquete(paquete)` devuelve las rutas que escribe un paquete del catálogo (ver `rutas_del_paquete`);
    sin él no se abren los paquetes (solo en las pruebas: `main` siempre lo pasa).
    """
    motivos = []
    if not cambios:
        return ["La propuesta no cambia ningún archivo."]
    if permisos.rol_global == Rol.NINGUNO and not permisos.por_juego:
        return [_SIN_ROL]

    cat_antes = _leer_json(antes)
    cat_despues = None
    toca_catalogo = any(c.ruta == RUTA_CATALOGO for c in cambios)
    if toca_catalogo:
        cat_despues, errores = validar_catalogo(despues, cat_antes)
        motivos += errores
        if cat_despues is not None:
            # Para todos los roles, también Administradores y Propietario: no hay excepción posible.
            motivos += comprobar_archivos_protegidos(cat_antes, cat_despues, prohibidos, leer_paquete)

    juegos_antes = _juegos_por_id(cat_antes)
    motivos += _comprobar_archivos(cambios, juegos_antes, permisos)
    if toca_catalogo and cat_despues is not None and isinstance(cat_antes, dict):
        motivos += _comprobar_campos(cat_antes, cat_despues, permisos)
    return motivos


def validar_catalogo(texto, cat_antes):
    """Comprobaciones que valen para cualquier rol: que el catálogo se pueda leer y publicar."""
    if texto is None:
        return None, ["No se puede borrar `catalogo/catalogo.json`: sin él el parcheador no tiene catálogo."]
    if len(texto.encode("utf-8")) > TAMANO_MAXIMO_CATALOGO:
        return None, ["`catalogo.json` pesa más de 8 MB y el parcheador no lo descargaría."]
    try:
        cat = json.loads(texto)
    except json.JSONDecodeError as e:
        return None, [f"`catalogo.json` no es un JSON válido (línea {e.lineno}, columna {e.colno}): {e.msg}. "
                      "Suele ser una coma o una comilla de más o de menos."]
    if not isinstance(cat, dict):
        return None, ["`catalogo.json` tiene que ser un objeto `{ … }`."]

    errores = []
    if not _es_entero(cat.get("esquema")) or cat["esquema"] < 1:
        errores.append("Falta `esquema` (un número entero, hoy `1`).")
    version = cat.get("versionCatalogo")
    if not _es_entero(version):
        errores.append("Falta `versionCatalogo` (un número entero).")
    elif isinstance(cat_antes, dict) and _es_entero(cat_antes.get("versionCatalogo")) \
            and version <= cat_antes["versionCatalogo"]:
        errores.append(
            f"`versionCatalogo` tiene que subir: ahora vale {cat_antes['versionCatalogo']} y la propuesta "
            f"lo deja en {version}. Si no sube, los parcheadores de los usuarios no se enteran del cambio. "
            f"Ponlo a {cat_antes['versionCatalogo'] + 1} (si otra propuesta se ha publicado antes que la "
            "tuya, actualiza la tuya y vuelve a subirlo).")

    juegos = cat.get("juegos", [])
    if not isinstance(juegos, list) or not all(isinstance(j, dict) for j in juegos):
        return None, errores + ["`juegos` tiene que ser una lista de objetos."]

    etiquetas = {e.get("id") for e in cat.get("etiquetas") or [] if isinstance(e, dict)}
    vistos = set()
    for juego in juegos:
        jid = juego.get("id")
        if not isinstance(jid, str) or not ID_VALIDO.match(jid):
            errores.append(f"Hay un juego con un `id` no válido ({jid!r}): solo minúsculas, números, `-`, `_` y `.`.")
            continue
        if jid in vistos:
            errores.append(f"El juego `{jid}` está repetido.")
        vistos.add(jid)
        errores += _validar_etiquetas(f"`{jid}`", juego, etiquetas)
        errores += _validar_parche(f"`{jid}`", juego.get("parche"))
        ediciones = juego.get("ediciones") or []
        if not isinstance(ediciones, list) or not all(isinstance(e, dict) for e in ediciones):
            errores.append(f"`{jid}`: `ediciones` tiene que ser una lista de objetos.")
            continue
        ids_edicion = [e.get("id") for e in ediciones]
        if any(not isinstance(i, str) or not ID_VALIDO.match(i) for i in ids_edicion) \
                or len(set(ids_edicion)) != len(ids_edicion):
            errores.append(f"`{jid}`: hay una edición sin `id`, con un `id` no válido o repetida.")
            continue
        for edicion in ediciones:
            donde = f"`{jid}` › edición `{edicion['id']}`"
            errores += _validar_etiquetas(donde, edicion, etiquetas)
            errores += _validar_parche(donde, edicion.get("parche"))
    return (cat if not errores else None), errores


def _validar_etiquetas(donde, objeto, definidas):
    usadas = objeto.get("etiquetas") or []
    if not isinstance(usadas, list):
        return [f"{donde}: `etiquetas` tiene que ser una lista."]
    return [f"{donde}: la etiqueta `{e}` no existe en el catálogo. Solo se pueden poner etiquetas ya creadas."
            for e in usadas if e not in definidas]


def _validar_parche(donde, parche):
    if parche is None:
        return []
    if not isinstance(parche, dict):
        return [f"{donde}: `parche` tiene que ser un objeto."]
    errores = []
    for paquete in parche.get("paquetes") or []:
        if not isinstance(paquete, dict):
            errores.append(f"{donde}: cada paquete tiene que ser un objeto.")
            continue
        url = paquete.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            errores.append(f"{donde}: la `url` del paquete tiene que empezar por `https://` ({url!r}).")
        if not _es_entero(paquete.get("tamano")) or paquete["tamano"] <= 0:
            errores.append(f"{donde}: falta el `tamano` del paquete (en bytes).")
        if not isinstance(paquete.get("hash"), str) or not HASH_VALIDO.match(paquete["hash"]):
            errores.append(f"{donde}: el `hash` del paquete tiene que ser `blake3:` seguido de 64 caracteres "
                           "(lo da `parcheador-publicador paquete`).")
    return errores


# ───────────────────────────────────── Archivos prohibidos ─────────────────────────────────────
#
# Ningún parche puede modificar ni añadir archivos de protección anticopia (DRM) ni los típicos de los
# cracks: la lista está en `normas/archivos-prohibidos.json` y se lee siempre de `main`.
#
# De dónde sale qué archivos toca un parche: lo único fiable es el `manifiesto.json` de dentro del `.zip`
# (es lo que ejecuta el parcheador). `huellasParcheadas` del catálogo se escribe a mano o con el publicador
# y el parcheador no la contrasta con el paquete, así que se mira también, pero no basta. Por eso el robot
# descarga cada paquete nuevo, comprueba que su tamaño y su hash son los del catálogo (los mismos que exige
# el parcheador antes de instalarlo) y lee las rutas de su manifiesto. Nunca ejecuta nada del paquete.

RUTA_PROHIBIDOS = "normas/archivos-prohibidos.json"
TAMANO_MAXIMO_PAQUETE = 4 * 1024 * 1024 * 1024
TAMANO_MAXIMO_MANIFIESTO = 16 * 1024 * 1024
NOMBRE_MANIFIESTO = "manifiesto.json"


@dataclass(frozen=True)
class Prohibido:
    patron: str
    motivo: str = ""

    def coincide(self, ruta: str) -> bool:
        """Sin distinguir mayúsculas. `nombre*.dll` mira el nombre del archivo en cualquier carpeta;
        `carpeta/` (con barra al final), cualquier carpeta de la ruta con ese nombre; un patrón con una barra
        en medio, la ruta entera."""
        partes = [p for p in ruta.replace("\\", "/").lower().split("/") if p]
        if not partes:
            return False
        patron = self.patron.replace("\\", "/").lower()
        if patron.endswith("/"):
            return any(fnmatch.fnmatchcase(p, patron.rstrip("/")) for p in partes[:-1])
        if "/" in patron:
            return fnmatch.fnmatchcase("/".join(partes), patron.lstrip("/"))
        return fnmatch.fnmatchcase(partes[-1], patron)


def leer_prohibidos(texto: str) -> list:
    """`normas/archivos-prohibidos.json` → lista de `Prohibido`. Si está mal, falla: mejor no aceptar nada
    que aceptar sin comprobar."""
    datos = json.loads(texto)
    patrones = datos.get("patrones") if isinstance(datos, dict) else None
    if not isinstance(patrones, list) or not patrones:
        raise ValueError(f"`{RUTA_PROHIBIDOS}` no tiene una lista `patrones`.")
    resultado = []
    for p in patrones:
        if not isinstance(p, dict) or not isinstance(p.get("patron"), str) or not p["patron"].strip("/ "):
            raise ValueError(f"`{RUTA_PROHIBIDOS}`: hay un patrón vacío o mal escrito ({p!r}).")
        resultado.append(Prohibido(p["patron"].strip(), str(p.get("motivo") or "")))
    return resultado


def archivo_prohibido(ruta: str, prohibidos):
    return next((p for p in prohibidos if p.coincide(ruta)), None)


def mensaje_protegido(donde: str, ruta: str, norma: Prohibido) -> str:
    return (f"{donde}: Este parche toca un archivo protegido ({ruta}). Los parches no pueden modificar "
            f"archivos de protección anticopia. Norma `{norma.patron}` de `{RUTA_PROHIBIDOS}`"
            + (f" — {norma.motivo}" if norma.motivo else "."))


class PaqueteIlegible(Exception):
    """No se ha podido leer el paquete o no es el que dice el catálogo."""


def comprobar_archivos_protegidos(cat_antes, cat_despues: dict, prohibidos, leer_paquete) -> list:
    motivos = []
    for donde, ruta in _rutas_parcheadas(cat_despues):
        norma = archivo_prohibido(ruta, prohibidos)
        if norma:
            motivos.append(mensaje_protegido(donde, ruta, norma))

    if leer_paquete is not None:
        ya_publicados = {_clave_paquete(p) for _, p in _paquetes(cat_antes)}
        revisados = set()
        for donde, paquete in _paquetes(cat_despues):
            clave = _clave_paquete(paquete)
            if clave in ya_publicados or clave in revisados:
                continue  # ya se revisó cuando se publicó (o más arriba en esta misma propuesta)
            revisados.add(clave)
            try:
                rutas = leer_paquete(paquete)
            except PaqueteIlegible as error:
                motivos.append(f"{donde}: no se ha podido revisar el paquete `{paquete.get('url')}`: {error} "
                               "Sin revisarlo no se puede saber si toca archivos protegidos.")
                continue
            for ruta in rutas:
                norma = archivo_prohibido(ruta, prohibidos)
                if norma:
                    motivos.append(mensaje_protegido(donde, ruta, norma))
    return _sin_repetidos(motivos)


def _rutas_parcheadas(catalogo: dict):
    """(dónde, ruta) de cada archivo de `huellasParcheadas`: lo que el catálogo dice que deja cada parche."""
    for juego in catalogo.get("juegos") or []:
        for edicion in juego.get("ediciones") or []:
            if not isinstance(edicion, dict):
                continue
            for huella in edicion.get("huellasParcheadas") or []:
                if not isinstance(huella, dict):
                    continue
                donde = f"`{juego.get('id')}` › edición `{edicion.get('id')}` › versión `{huella.get('version')}`"
                for archivo in huella.get("archivos") or []:
                    if isinstance(archivo, dict) and isinstance(archivo.get("ruta"), str):
                        yield donde, archivo["ruta"]


def _paquetes(catalogo):
    """(dónde, paquete) de cada paquete de parche del catálogo, esté donde esté (`parche` del juego o de la
    edición, historial de `versiones`…): cualquier objeto de una lista `paquetes` dentro de `juegos`."""
    if not isinstance(catalogo, dict):
        return

    def recorrer(valor, donde):
        if isinstance(valor, dict):
            for clave, hijo in valor.items():
                if clave == "paquetes" and isinstance(hijo, list):
                    for paquete in hijo:
                        if isinstance(paquete, dict):
                            yield donde + (f" › paquete `{paquete.get('edicion')}`" if paquete.get("edicion") else ""), paquete
                else:
                    yield from recorrer(hijo, donde)
        elif isinstance(valor, list):
            for hijo in valor:
                yield from recorrer(hijo, donde)

    for juego in catalogo.get("juegos") or []:
        if isinstance(juego, dict):
            yield from recorrer(juego, f"`{juego.get('id')}`")


def _clave_paquete(paquete: dict):
    return (paquete.get("url"), paquete.get("tamano"), paquete.get("hash"))


def rutas_del_paquete(paquete: dict, calcular_hash=None, abrir=None) -> list:
    """Descarga el paquete, comprueba tamaño y hash y devuelve las rutas del juego que escribe su manifiesto.

    `calcular_hash()` da un objeto con `update(bytes)` y `hexdigest()` (por defecto, BLAKE3) y `abrir(url)`
    un flujo de bytes (por defecto, una descarga https); las pruebas los cambian.
    """
    url, tamano, valor_hash = paquete.get("url"), paquete.get("tamano"), paquete.get("hash")
    if not isinstance(url, str) or not url.startswith("https://") or not _es_entero(tamano) \
            or not isinstance(valor_hash, str) or not HASH_VALIDO.match(valor_hash):
        raise PaqueteIlegible("le falta la dirección `https`, el tamaño o el hash.")
    if tamano > TAMANO_MAXIMO_PAQUETE:
        raise PaqueteIlegible("pesa más de 4 GB.")
    if calcular_hash is None:
        try:
            import blake3  # instalado por el flujo de trabajo, con su hash fijado (robot/requisitos.txt)
        except ImportError:
            raise PaqueteIlegible("el robot no tiene BLAKE3 instalado (avisa a un Administrador).")
        calcular_hash = blake3.blake3
    abrir = abrir or _abrir_https

    with tempfile.TemporaryFile() as temporal:
        suma, leidos = calcular_hash(), 0
        try:
            with abrir(url) as flujo:
                while bloque := flujo.read(1024 * 1024):
                    leidos += len(bloque)
                    if leidos > tamano:
                        raise PaqueteIlegible(f"pesa más de lo que dice el catálogo ({tamano} bytes).")
                    suma.update(bloque)
                    temporal.write(bloque)
        except (OSError, urllib.error.URLError) as error:
            raise PaqueteIlegible(f"no se ha podido descargar ({error}).")
        if leidos != tamano:
            raise PaqueteIlegible(f"pesa {leidos} bytes y el catálogo dice {tamano}.")
        if "blake3:" + suma.hexdigest() != valor_hash:
            raise PaqueteIlegible("su hash no es el que dice el catálogo.")

        temporal.seek(0)
        try:
            with zipfile.ZipFile(temporal) as zip_:
                entrada = next((i for i in zip_.infolist() if i.filename == NOMBRE_MANIFIESTO), None)
                if entrada is None:
                    raise PaqueteIlegible(f"no tiene `{NOMBRE_MANIFIESTO}`.")
                if entrada.file_size > TAMANO_MAXIMO_MANIFIESTO:
                    raise PaqueteIlegible(f"su `{NOMBRE_MANIFIESTO}` es demasiado grande.")
                with zip_.open(entrada) as archivo:
                    manifiesto = json.loads(archivo.read(TAMANO_MAXIMO_MANIFIESTO + 1).decode("utf-8-sig"))
        except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, OSError) as error:
            raise PaqueteIlegible(f"no es un paquete válido ({error}).")

    operaciones = manifiesto.get("operaciones") if isinstance(manifiesto, dict) else None
    if not isinstance(operaciones, list):
        raise PaqueteIlegible(f"su `{NOMBRE_MANIFIESTO}` no tiene `operaciones`.")
    rutas = []
    for op in operaciones:
        if not isinstance(op, dict) or not isinstance(op.get("ruta"), str):
            raise PaqueteIlegible(f"su `{NOMBRE_MANIFIESTO}` tiene una operación sin `ruta`.")
        rutas.append(op["ruta"])
    return rutas


def _abrir_https(url: str):
    peticion = urllib.request.Request(url, headers={"User-Agent": "robot-permisos"})
    return urllib.request.urlopen(peticion, timeout=60)


def _comprobar_archivos(cambios, juegos_antes, permisos: Permisos) -> list:
    motivos = []
    for c in cambios:
        if c.modo in ("120000", "160000"):
            motivos.append(f"`{c.ruta}`: no se admiten enlaces simbólicos ni submódulos.")
            continue
        if c.ruta == RUTA_CATALOGO:
            continue  # lo que se puede cambiar dentro del catálogo lo decide _comprobar_campos
        if permisos.rol_global >= Rol.ADMINISTRADOR:
            continue

        juego = _juego_de_la_ruta(c.ruta)
        if juego is None:
            motivos.append(f"`{c.ruta}`: este archivo solo lo puede cambiar un Administrador. Con tu rol "
                           "se cambian `catalogo/catalogo.json` y, si eres Editor, las imágenes de "
                           "`catalogo/juegos/<juego>/`.")
            continue
        rol = permisos.en_juego(juego)
        if juego not in juegos_antes:
            motivos.append(f"`{c.ruta}`: el juego `{juego}` todavía no existe en el catálogo. Dar de alta "
                           "un juego nuevo (y subir sus imágenes) es cosa de un Administrador.")
        elif rol < Rol.EDITOR:
            motivos.append(f"`{c.ruta}`: las imágenes de un juego las cambian los Editores y los "
                           f"Administradores (tu rol en `{juego}`: {rol.nombre}).")
        elif c.estado != "D":
            if not c.ruta.lower().endswith(EXTENSIONES_IMAGEN):
                motivos.append(f"`{c.ruta}`: en la carpeta de un juego solo van imágenes "
                               f"({', '.join(EXTENSIONES_IMAGEN)}).")
            elif c.tamano > TAMANO_MAXIMO_IMAGEN:
                motivos.append(f"`{c.ruta}`: la imagen pesa {c.tamano / 1048576:.1f} MB y el máximo son 5 MB.")
    return _sin_repetidos(motivos)


_SIN_ROL = ("Tu cuenta no tiene ningún rol en este repositorio (Administrador, Editor o Colaborador), "
            "así que el robot no puede aceptar cambios tuyos. Si eres del equipo, pide a un Administrador "
            "que te añada.")


def _comprobar_campos(antes: dict, despues: dict, permisos: Permisos) -> list:
    motivos = []

    # ── Raíz del catálogo: el parcheador (`launcher`), el grupo, las etiquetas… son de Administrador.
    if permisos.rol_global < Rol.ADMINISTRADOR:
        for clave in _claves_distintas(antes, despues):
            if clave not in RAIZ_LIBRE:
                motivos.append(f"`{clave}`: esta parte del catálogo solo la cambia un Administrador"
                               + (" (los demás roles ponen y quitan etiquetas que ya existen, pero no las "
                                  "crean ni las editan)." if clave == "etiquetas" else "."))

    # ── Juegos que aparecen o desaparecen.
    j_antes, j_despues = _juegos_por_id(antes), _juegos_por_id(despues)
    if permisos.rol_global < Rol.ADMINISTRADOR:
        for jid in j_despues.keys() - j_antes.keys():
            motivos.append(f"Juego nuevo `{jid}`: dar de alta un juego es cosa de un Administrador.")
        for jid in j_antes.keys() - j_despues.keys():
            motivos.append(f"Juego `{jid}`: quitar un juego del catálogo es cosa de un Administrador.")

    # ── Juegos que ya existían y cambian.
    for jid in j_antes.keys() & j_despues.keys():
        a, d = j_antes[jid], j_despues[jid]
        if a == d:
            continue
        rol = permisos.en_juego(jid)
        if rol >= Rol.ADMINISTRADOR:
            continue
        if rol == Rol.EDITOR:
            for clave in _claves_distintas(a, d):
                if clave in CAMPOS_PUBLICAR_JUEGO:
                    motivos.append(f"`{jid}` › `{clave}`: publicar u ocultar un juego entero es cosa de un "
                                   "Administrador. Como Editor puedes publicar y retirar sus versiones.")
        elif rol == Rol.COLABORADOR:
            for donde in _fuera_de_lo_permitido_al_colaborador(a, d):
                motivos.append(f"`{jid}` › {donde}: un Colaborador solo puede cambiar textos y notas "
                               "(`sinopsis`, `notaEdicion`, `parche.notas`), `etiquetas` y el estado de la "
                               "traducción (`estado`, `progreso`, `contenido`).")
        else:
            motivos.append(f"`{jid}`: no tienes ningún rol en este juego.")
    return _sin_repetidos(motivos)


def _fuera_de_lo_permitido_al_colaborador(antes: dict, despues: dict) -> list:
    """Qué partes de un juego cambian fuera de los campos del Colaborador."""
    fuera = []
    a, d = copy.deepcopy(antes), copy.deepcopy(despues)
    for clave in CAMPOS_COLABORADOR_JUEGO:
        a.pop(clave, None), d.pop(clave, None)
    fuera += [f"`parche.{c}`" for c in _parche_fuera(a.pop("parche", None), d.pop("parche", None))]

    ed_a, ed_d = _ediciones_por_id(a.pop("ediciones", None)), _ediciones_por_id(d.pop("ediciones", None))
    fuera += [f"edición nueva `{i}`" for i in ed_d.keys() - ed_a.keys()]
    fuera += [f"edición quitada `{i}`" for i in ed_a.keys() - ed_d.keys()]
    for eid in ed_a.keys() & ed_d.keys():
        ea, ed = ed_a[eid], ed_d[eid]
        for clave in CAMPOS_COLABORADOR_EDICION:
            ea.pop(clave, None), ed.pop(clave, None)
        fuera += [f"edición `{eid}` › `parche.{c}`" for c in _parche_fuera(ea.pop("parche", None), ed.pop("parche", None))]
        fuera += [f"edición `{eid}` › `{c}`" for c in _claves_distintas(ea, ed)]

    fuera += [f"`{c}`" for c in _claves_distintas(a, d)]
    return fuera


def _parche_fuera(antes, despues) -> list:
    if antes == despues:
        return []
    if not isinstance(antes, dict) or not isinstance(despues, dict):
        return ["(crear o quitar la versión)"]
    return [c for c in _claves_distintas(antes, despues) if c not in CAMPOS_COLABORADOR_PARCHE]


# ─────────────────────────────────────────── Utilidades ───────────────────────────────────────────

def _es_entero(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _leer_json(texto):
    if texto is None:
        return None
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return None


def _juegos_por_id(catalogo) -> dict:
    if not isinstance(catalogo, dict) or not isinstance(catalogo.get("juegos"), list):
        return {}
    return {j["id"]: j for j in catalogo["juegos"] if isinstance(j, dict) and isinstance(j.get("id"), str)}


def _ediciones_por_id(ediciones) -> dict:
    if not isinstance(ediciones, list):
        return {}
    return {e.get("id"): e for e in ediciones if isinstance(e, dict)}


def _juego_de_la_ruta(ruta: str):
    """`catalogo/juegos/<id>/archivo` → `<id>`; cualquier otra ruta → None."""
    if not ruta.startswith(CARPETA_JUEGOS):
        return None
    partes = ruta[len(CARPETA_JUEGOS):].split("/")
    return partes[0] if len(partes) >= 2 and ID_VALIDO.match(partes[0]) else None


def _claves_distintas(a: dict, b: dict) -> list:
    return sorted(k for k in a.keys() | b.keys() if a.get(k, _FALTA) != b.get(k, _FALTA))


_FALTA = object()


def _sin_repetidos(lista: list) -> list:
    return list(dict.fromkeys(lista))


# ──────────────────────────────── De dónde salen los roles (GitHub) ────────────────────────────────

# Rol de GitHub en este repositorio → rol del proyecto. Los equipos de la organización tienen cada uno
# un nivel distinto, y eso es lo único que el robot puede consultar sin una clave propia:
#   administradores → admin · editores → write · colaboradores → triage
ROL_DE_GITHUB = {
    "admin": Rol.ADMINISTRADOR,
    "maintain": Rol.EDITOR,
    "write": Rol.EDITOR,
    "triage": Rol.COLABORADOR,
}


def leer_equipo(texto_equipo_json):
    """FUTURO (líderes por juego, sin implementar): permisos escritos en `equipo.json`.

    Cuando se haga, este es el único sitio que hay que rellenar. Formato previsto:

        { "esquema": 1,
          "personas": { "usuario-de-github": { "rol": "editor", "juegos": { "rance02": "administrador" } } } }

    Debe devolver `{ usuario en minúsculas: Permisos(rol_global, por_juego) }`. Importante: el archivo se
    lee siempre de `main`, nunca de la propuesta (si no, cualquiera se daría permisos a sí mismo), y solo
    lo puede cambiar un Administrador (ya es así: está fuera de `catalogo/`).
    """
    return {}


def permisos_de(usuario: str, api, equipo: dict) -> Permisos:
    """El rol de GitHub de la persona, ampliado con lo que diga `equipo.json` (hoy, nada)."""
    rol = Rol.NINGUNO
    if usuario and not usuario.endswith("[bot]"):
        respuesta = api("GET", f"/collaborators/{usuario}/permission", tolerar=(404,))
        if respuesta:
            rol = ROL_DE_GITHUB.get(respuesta.get("role_name") or respuesta.get("permission"), Rol.NINGUNO)
    extra = equipo.get(usuario.lower())
    if extra is None:
        return Permisos(rol)
    return Permisos(max(rol, extra.rol_global), dict(extra.por_juego))


# ────────────────────────────────────── GitHub y git (main) ──────────────────────────────────────

MARCA = "<!-- robot-permisos -->"


def crear_api(repositorio: str, token: str):
    def api(metodo: str, ruta: str, datos=None, tolerar=()):
        url = ruta if ruta.startswith("https://") else f"https://api.github.com/repos/{repositorio}{ruta}"
        peticion = urllib.request.Request(
            url, method=metodo, data=None if datos is None else json.dumps(datos).encode(),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "robot-permisos"})
        try:
            with urllib.request.urlopen(peticion, timeout=30) as respuesta:
                cuerpo = respuesta.read()
                return json.loads(cuerpo) if cuerpo else {}
        except urllib.error.HTTPError as e:
            if e.code in tolerar:
                return None
            raise RuntimeError(f"GitHub respondió {e.code} a {metodo} {ruta}: {e.read().decode(errors='replace')[:300]}")
    return api


def git(*argumentos, comprobar_salida=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *argumentos], capture_output=True, check=comprobar_salida)


def leer_propuesta(numero: int, cabeza: str):
    """Une la propuesta con el `main` de ahora mismo (sin ejecutar nada) y devuelve lo que cambia.

    Devuelve (cambios, catálogo antes, catálogo después) o None si hay conflicto con `main`.
    """
    git("fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main",
        f"+refs/pull/{numero}/head:refs/remotes/propuesta/cabeza")
    if git("rev-parse", "refs/remotes/propuesta/cabeza").stdout.decode().strip() != cabeza:
        raise RuntimeError("La propuesta ha cambiado mientras se comprobaba; el robot volverá a mirarla.")
    union = git("merge-tree", "--write-tree", "origin/main", cabeza, comprobar_salida=False)
    if union.returncode != 0:
        return None
    arbol = union.stdout.decode().split()[0]

    cambios = []
    bruto = git("diff", "--raw", "-z", "--no-renames", "--no-abbrev", "origin/main", arbol).stdout.decode()
    partes = bruto.split("\0")
    for i in range(0, len(partes) - 1, 2):
        _, modo_nuevo, _, _, estado = partes[i].lstrip(":").split(" ")
        ruta = partes[i + 1]
        tamano = 0
        if estado != "D":
            tamano = int(git("cat-file", "-s", f"{arbol}:{ruta}").stdout.decode().strip())
        cambios.append(Cambio(ruta, estado[0], modo_nuevo, tamano))

    def texto(revision):
        salida = git("show", f"{revision}:{RUTA_CATALOGO}", comprobar_salida=False)
        return salida.stdout.decode("utf-8", errors="replace") if salida.returncode == 0 else None

    return cambios, texto("origin/main"), texto(arbol)


def comentar(api, numero: int, texto: str, solo_si_existe=False) -> None:
    """Un único comentario del robot por propuesta: se crea la primera vez y después se va actualizando."""
    cuerpo = f"{MARCA}\n{texto}"
    comentarios = api("GET", f"/issues/{numero}/comments?per_page=100") or []
    propio = next((c for c in comentarios if MARCA in (c.get("body") or "")), None)
    if propio:
        api("PATCH", f"/issues/comments/{propio['id']}", {"body": cuerpo})
    elif not solo_si_existe:
        api("POST", f"/issues/{numero}/comments", {"body": cuerpo})


def resumen(texto: str) -> None:
    print(texto)
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as archivo:
            archivo.write(texto + "\n")


def main() -> int:
    fusionar = "--fusionar" in sys.argv[1:]
    repositorio = os.environ["GITHUB_REPOSITORY"]
    numero = int(os.environ["PR_NUMERO"])
    api = crear_api(repositorio, os.environ["GITHUB_TOKEN"])

    propuesta = api("GET", f"/pulls/{numero}")
    cabeza = propuesta["head"]["sha"]
    autor = propuesta["user"]["login"]
    # Cuenta el rol más bajo entre quien abrió la propuesta y quien ha subido el último cambio: así nadie
    # gana permisos por añadir cambios a la propuesta de otra persona con más rol.
    actor = os.environ.get("PR_ACTOR") or autor
    equipo = leer_equipo(None)
    permisos = permisos_de(autor, api, equipo)
    if actor != autor:
        permisos = permisos.el_menor(permisos_de(actor, api, equipo))
    quien = f"@{autor}" + (f" (último cambio de @{actor})" if actor != autor else "")

    # La lista de archivos prohibidos se lee de `main` (esta copia), nunca de la propuesta.
    ruta_prohibidos = pathlib.Path(__file__).resolve().parents[1] / RUTA_PROHIBIDOS
    try:
        prohibidos = leer_prohibidos(ruta_prohibidos.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"No se puede leer `{RUTA_PROHIBIDOS}` de `main`: {error}")

    leido = leer_propuesta(numero, cabeza)
    if leido is None:
        motivos = ["La propuesta choca con cambios que ya están publicados en `main`. Actualízala con lo "
                   "último de `main` y vuelve a subirla."]
    else:
        motivos = comprobar(*leido, permisos, prohibidos=prohibidos, leer_paquete=rutas_del_paquete)

    if motivos:
        lista = "\n".join(f"- {m}" for m in motivos)
        texto = (f"### ❌ El robot de permisos no puede aceptar esta propuesta\n\n"
                 f"{quien} · rol: **{permisos.rol_global.nombre}**\n\n{lista}\n\n"
                 "Corrige lo indicado y sube el cambio a esta misma propuesta: el robot la vuelve a mirar "
                 "solo. Si crees que es un error, avisa a un Administrador.")
        comentar(api, numero, texto)
        resumen(texto)
        return 1

    aprobado = (f"### ✅ Propuesta aceptada por el robot de permisos\n\n"
                f"{quien} · rol: **{permisos.rol_global.nombre}**")
    if not fusionar:
        comentar(api, numero, aprobado + "\n\nSe publica sola en unos segundos.", solo_si_existe=True)
        resumen(aprobado)
        return 0

    if propuesta.get("draft"):
        resumen(aprobado + "\n\nEs un borrador: no se publica hasta que se marque como lista.")
        return 0
    resultado = api("PUT", f"/pulls/{numero}/merge",
                    {"sha": cabeza, "merge_method": "squash"}, tolerar=(405, 409, 422))
    if resultado is None:
        texto = (aprobado + "\n\n⚠️ Pero no se ha podido publicar sola: se ha cruzado con otro cambio. "
                 "Actualiza la propuesta con lo último de `main` y el robot lo vuelve a intentar.")
        comentar(api, numero, texto)
        resumen(texto)
        return 1
    comentar(api, numero, aprobado + "\n\nPublicada. Los parcheadores la verán en unos minutos.", solo_si_existe=True)
    resumen(aprobado + "\n\nPublicada.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        resumen(f"### ⚠️ El robot de permisos ha fallado\n\n{error}")
        sys.exit(1)
