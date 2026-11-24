#!/usr/bin/env python3
"""Robot de permisos del repositorio de datos del Parcheador Rance.

Mira qué cambia una propuesta (pull request) y decide si quien la hace tiene permiso, según su rol:

  Dueño          (del programa, `normas/propietario.json`) todo, también las normas generales (`normas/`), el
                 robot (`robot/`), `.github/` y las etiquetas del catálogo.
  Propietario    (del canal) como un Administrador, y además lo suyo del canal (`canales/<canal>/`).
  Administrador  solo `catalogo/` (el catálogo y las imágenes de los juegos), y menos crear, editar o borrar
                 etiquetas del catálogo. Lo de fuera de `catalogo/` y de `canales/` es del Dueño.
  Editor         el contenido de los juegos que ya existen (y sus imágenes). No puede añadir, quitar,
                 publicar ni ocultar juegos, ni tocar el parcheador, el grupo o las etiquetas del catálogo.
  Colaborador    solo textos y notas, etiquetas y estado de la traducción de lo que ya existe.

Desde la fase A de canales (docs/canales.md del parcheador) los roles salen de `canales/ornizen/miembros.json`, por
el id numérico de la cuenta; mientras dure la transición cuenta el mayor entre ese archivo y el equipo de GitHub,
salvo que la cuenta esté en la lista negra del canal. Lo de `canales/` lo decide `canales.py`.

Y, para todos (también Administradores y Dueño): ningún parche puede tocar los archivos de la lista
general (`normas/archivos-prohibidos.json`) ni de la del grupo (`grupo.archivosProhibidos` del catálogo):
protección anticopia y cracks. Ver «Archivos prohibidos» más abajo.

Este archivo tiene dos partes:

  1. Las reglas (`comprobar`): no hablan con GitHub ni con git; reciben los datos y devuelven los motivos
     de rechazo. Se prueban con `python -I -m unittest discover -s robot/pruebas`.
  2. La parte de GitHub (`main`): averigua el rol, lee el cambio con git, comenta el resultado y fusiona.

Solo usa la biblioteca estándar de Python. Nunca ejecuta nada de la propuesta: solo lee sus archivos.
"""
from __future__ import annotations

import copy
import datetime
import enum
import fnmatch
import html
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field

import canales
import lector_app  # el catálogo tal como lo lee el parcheador

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
    PROPIETARIO = 4  # Propietario del canal: como Administrador en el catálogo, y lo suyo en `canales/<canal>/`
    DUENO = 5        # Dueño del programa: figura en `normas/propietario.json`

    @property
    def nombre(self) -> str:
        return canales.NOMBRE_ROL[int(self)]


@dataclass(frozen=True)
class Permisos:
    """Lo que puede hacer una persona: un rol para todo el repositorio y, en el futuro, roles por juego.

    Las reglas nunca miran `rol_global` para decidir sobre un juego: preguntan `en_juego(id)`. Así, cuando
    existan los líderes por juego, bastará con rellenar `por_juego` (ver `leer_equipo`).
    """
    rol_global: Rol
    por_juego: dict = field(default_factory=dict)
    por_canal: dict = field(default_factory=dict)  # {canal: Rol} en `main` (invitaciones sin aceptar, no)
    cuenta_id: int | None = None  # el id numérico de la cuenta: para aceptar su propia invitación o salir

    @property
    def es_dueno(self) -> bool:
        return self.rol_global >= Rol.DUENO

    def en_juego(self, juego_id: str) -> Rol:
        return max(self.rol_global, self.por_juego.get(juego_id, Rol.NINGUNO))

    def el_menor(self, otro: "Permisos") -> "Permisos":
        juegos = set(self.por_juego) & set(otro.por_juego)
        canales_ = set(self.por_canal) & set(otro.por_canal)
        return Permisos(min(self.rol_global, otro.rol_global),
                        {j: min(self.por_juego[j], otro.por_juego[j]) for j in juegos},
                        {c: min(self.por_canal[c], otro.por_canal[c]) for c in canales_},
                        self.cuenta_id if self.cuenta_id == otro.cuenta_id else None)


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


def comprobar(cambios, antes, despues, permisos: Permisos, prohibidos=(), leer_paquete=None, leer_archivo=None,
              ids_duenos=frozenset(), cuenta_de=None, rol_externo=None) -> list:
    """Devuelve los motivos por los que la propuesta no se acepta (lista vacía = se acepta).

    `antes` y `despues` son el texto de `catalogo/catalogo.json` en `main` y tras aplicar la propuesta
    (None si no existe). `prohibidos` son los patrones de `normas/archivos-prohibidos.json` (de `main`) y
    `leer_paquete(paquete)` devuelve las rutas que escribe un paquete del catálogo (ver `rutas_del_paquete`);
    sin él no se abren los paquetes (solo en las pruebas: `main` siempre lo pasa). `leer_archivo(ruta, lado)` da los
    bytes de un archivo en `main` (`"antes"`) o tras la propuesta (`"despues"`), o None si no existe: hace falta para
    lo que cambia en `canales/`. `ids_duenos` son los ids del Dueño (nadie los veta) y `cuenta_de(id)` el nombre actual
    de una cuenta en GitHub (para que nadie ponga el nombre de otra persona junto a un id).
    """
    motivos = []
    if not cambios:
        return ["La propuesta no cambia ningún archivo."]
    # Python compilado (`.pyc`, `.pyo`, `__pycache__/`): nunca, para nadie, tampoco para el Dueño. Son restos de
    # ejecutar Python en la copia de trabajo, y Python los carga en lugar del `.py` si los encuentra junto a él. Borrarlos
    # sí se puede (para limpiar).
    compilados = [c.ruta for c in cambios if c.estado != "D" and es_python_compilado(c.ruta)]
    if compilados:
        return [f"`{ruta}`: es Python compilado (o está en `__pycache__/`). No se suben al repositorio: bórralo de la "
                "propuesta (ya están en `.gitignore`)." for ruta in compilados]
    de_canales = [c for c in cambios if c.ruta.startswith(canales.CARPETA_CANALES)]
    # El catálogo y todo lo que no es `canales/` se juzga con el rol del canal oficial (`rol_global`): un rol en otro
    # canal no cuenta. En `canales/` hace falta saber el id de la cuenta (aceptar la invitación propia, salir…).
    sin_rol_oficial = permisos.rol_global == Rol.NINGUNO and not permisos.por_juego
    if (sin_rol_oficial and len(de_canales) != len(cambios)) or (permisos.cuenta_id is None and not permisos.es_dueno
                                                                  and sin_rol_oficial):
        return [_SIN_ROL]
    # Lo de `canales/` se decide por la cuenta (aceptar la invitación propia, `invitadoPor`, `por` de un veto…). Si la
    # propuesta la ha abierto una cuenta y el último cambio lo ha subido otra, no hay «una» cuenta: no se acepta.
    if de_canales and permisos.cuenta_id is None and not permisos.es_dueno:
        return ["La propuesta cambia `canales/` y la han tocado varias cuentas (quien la abrió y quien subió el último "
                "cambio no son la misma). Los cambios de un canal los propone y los sube una sola cuenta: abre una "
                "propuesta nueva desde tu cuenta."]
    # En `canales/` solo archivos normales (ni enlaces simbólicos, ni submódulos, ni cambios de tipo), sea cual sea el
    # rol y antes de mirar nada más.
    for c in de_canales:
        if c.estado not in ("A", "M", "D") or (c.estado != "D" and c.modo != "100644"):
            return [f"`{c.ruta}`: en `canales/` solo valen archivos normales (sin enlaces simbólicos, submódulos, "
                    "permisos de ejecución ni cambios de tipo)."]
    motivos += _comprobar_tamanos(cambios, permisos)

    if de_canales:
        leer = leer_archivo or (lambda ruta, lado: None)
        motivos += canales.comprobar_canales(
            [canales.CambioCanal(c.ruta, c.estado, c.tamano, leer(c.ruta, "antes"),
                                 None if c.estado == "D" else leer(c.ruta, "despues")) for c in de_canales],
            {k: int(v) for k, v in permisos.por_canal.items()}, permisos.cuenta_id, permisos.es_dueno, leer,
            ids_duenos, cuenta_de, rol_externo)

    cat_antes = _leer_json(antes)
    cat_despues = None
    toca_catalogo = any(c.ruta == RUTA_CATALOGO for c in cambios)
    manda = _manda_en_todo(permisos)
    if toca_catalogo and not isinstance(cat_antes, dict) and not manda:
        # Sin el catálogo de `main` no se puede comparar campo a campo qué cambia: hasta que lo arregle quien manda en
        # todo, nadie más lo toca (cuarta revisión, 2.5).
        return [f"El `{RUTA_CATALOGO}` de `main` no se puede leer, así que no se puede comprobar qué cambias. Hasta que "
                f"lo arregle {lector_app.QUIEN_RESCATA}, solo él puede cambiar el catálogo."]
    if toca_catalogo:
        cat_despues, errores = validar_catalogo(despues, cat_antes, puede_rescatar=manda)
        motivos += errores
        if cat_despues is not None:
            # Para todos los roles, también Administradores y Propietario: no hay excepción posible.
            motivos += comprobar_archivos_protegidos(cat_antes, cat_despues,
                                                     list(prohibidos) + _prohibidos_del_canal(leer_archivo),
                                                     leer_paquete)
            motivos += comprobar_largos(cat_antes, cat_despues)

    juegos_antes = _juegos_por_id(cat_antes)
    motivos += _comprobar_archivos(cambios, juegos_antes, permisos)
    if toca_catalogo and cat_despues is not None and isinstance(cat_antes, dict):
        motivos += _comprobar_campos(cat_antes, cat_despues, permisos)
    return motivos


def _comprobar_tamanos(cambios, permisos: Permisos) -> list:
    """Topes de la propuesta entera (docs/canales.md §7.7). El Dueño se los salta (migraciones de una vez)."""
    if permisos.es_dueno:
        return []
    motivos = []
    if len(cambios) > canales.TOPE_ARCHIVOS_PROPUESTA:
        motivos.append(f"La propuesta cambia {len(cambios)} archivos y el máximo son {canales.TOPE_ARCHIVOS_PROPUESTA}: "
                       "divídela en varias.")
    total = sum(c.tamano for c in cambios)
    if total > canales.TOPE_BYTES_PROPUESTA:
        motivos.append(f"La propuesta pesa {total / 1048576:.1f} MB y el máximo son "
                       f"{canales.TOPE_BYTES_PROPUESTA // 1048576} MB: divídela en varias.")
    for c in cambios:
        if c.modo == "100755":
            motivos.append(f"`{c.ruta}`: en el repositorio de datos no van archivos ejecutables (quítale el permiso de ejecución).")
    return motivos


def _prohibidos_del_canal(leer_archivo) -> list:
    """Los archivos de la lista negra del canal oficial: cuentan la de `main` y la de la propuesta a la vez (solo
    añade a la general, igual que la antigua `grupo.archivosProhibidos`)."""
    if leer_archivo is None:
        return []
    ruta = f"{canales.CARPETA_CANALES}{canales.CANAL_OFICIAL}/lista-negra.json"
    resultado, vistos = [], set()
    for lado in ("antes", "despues"):
        datos = leer_archivo(ruta, lado)
        if datos is None:
            continue
        try:
            lista, _ = canales.leer_lista_negra(canales.leer_json_estricto(datos, ruta), ruta)
        except canales.JsonMalo:
            continue  # el error ya sale en la parte de canales
        for fila in lista.archivos:
            clave = fila["patron"].strip().lower()
            if clave not in vistos:
                vistos.add(clave)
                resultado.append(Prohibido(fila["patron"].strip(), fila.get("motivo", ""), f"del canal @{canales.CANAL_OFICIAL}"))
    return resultado


def _manda_en_todo(permisos: Permisos) -> bool:
    """Quien puede con todo el repositorio: el único que arregla un catálogo de `main` roto o con versión absurda."""
    return permisos.es_dueno


def validar_catalogo(datos, cat_antes, puede_rescatar=False):
    """Comprobaciones que valen para cualquier rol: que el catálogo se pueda leer y publicar.

    `datos` son los bytes del archivo (o su texto, en las pruebas). Lo que la app no puede leer no se acepta
    nunca (ver `lector_app.py`): un catálogo ilegible o con un `versionCatalogo` absurdo congelaría el catálogo de
    todos los parcheadores.
    """
    if datos is None:
        return None, ["No se puede borrar `catalogo/catalogo.json`: sin él el parcheador no tiene catálogo."]
    tamano = len(datos) if isinstance(datos, (bytes, bytearray)) else len(datos.encode("utf-8", "surrogatepass"))
    if tamano > TAMANO_MAXIMO_CATALOGO:
        return None, ["`catalogo.json` pesa más de 8 MB y el parcheador no lo descargaría."]
    try:
        cat = lector_app.leer(datos)
    except lector_app.JsonIlegible as e:
        return None, [f"`catalogo.json` {e}." + (" Suele ser una coma o una comilla de más o de menos." if e.sintaxis else "")]
    errores = lector_app.errores_de_la_app(cat)
    if errores:
        return None, errores
    version_antes = cat_antes.get("versionCatalogo") if isinstance(cat_antes, dict) else None
    errores = lector_app.errores_de_version(cat["versionCatalogo"], version_antes, puede_rescatar)

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
            errores += validar_ignorados(donde, edicion)
    return (cat if not errores else None), errores


# ───────────────────────────────────── Topes de largo ─────────────────────────────────────
#
# Lo que escribe el equipo tiene tope, el mismo que pone el parcheador en cada campo (`LimitesTexto` en
# Parcheador.Equipo; si cambia allí, cambia aquí): un texto enorme hincha el catálogo que descargan todos y
# descoloca las pantallas. Vale para cualquier rol.
#
# Solo se mira lo que la propuesta escribe o cambia: un texto largo que ya estaba publicado no bloquea las
# propuestas que no lo tocan. Se cuenta como el parcheador: sin los espacios de los lados y en unidades
# UTF-16 (un emoji de los nuevos cuenta dos), para no rechazar aquí lo que allí cabe ni al revés.

LARGO_SINOPSIS = 4000
LARGO_NOVEDADES = 4000
LARGO_NOTA_EDICION = 1000
LARGO_VERSION = 40


def _largo(texto: str) -> int:
    return len(texto.strip().encode("utf-16-le", "surrogatepass")) // 2


def _textos_con_tope(catalogo):
    """{clave: (dónde, nombre del campo, texto, máximo)} de cada texto con tope del catálogo."""
    textos = {}
    if not isinstance(catalogo, dict):
        return textos

    def apuntar(clave, donde, nombre, valor, maximo):
        if isinstance(valor, str):
            textos[clave] = (donde, nombre, valor, maximo)

    def parche(clave, donde, valor):
        if isinstance(valor, dict):
            apuntar(clave + ("notas",), donde, "las novedades (`notas`)", valor.get("notas"), LARGO_NOVEDADES)
            apuntar(clave + ("version",), donde, "la versión (`version`)", valor.get("version"), LARGO_VERSION)

    for juego in catalogo.get("juegos") or []:
        if not isinstance(juego, dict):
            continue
        jid = juego.get("id")
        donde = f"`{jid}`"
        apuntar((jid, "sinopsis"), donde, "la sinopsis", juego.get("sinopsis"), LARGO_SINOPSIS)
        parche((jid, "parche"), donde, juego.get("parche"))
        for edicion in juego.get("ediciones") or []:
            if not isinstance(edicion, dict):
                continue
            eid = edicion.get("id")
            aqui = f"{donde} › edición `{eid}`"
            apuntar((jid, eid, "notaEdicion"), aqui, "la nota de la edición (`notaEdicion`)", edicion.get("notaEdicion"), LARGO_NOTA_EDICION)
            parche((jid, eid, "parche"), aqui, edicion.get("parche"))
            for lista in ("versiones", "huellasParcheadas"):
                for i, version in enumerate(edicion.get(lista) or []):
                    # Por posición y no por versión: una versión kilométrica no puede ser su propia clave.
                    parche((jid, eid, lista, i), f"{aqui} › `{lista}`", version)
    return textos


def comprobar_largos(cat_antes, cat_despues) -> list:
    """Los textos que la propuesta escribe o cambia y se pasan de su tope."""
    antes = _textos_con_tope(cat_antes)
    motivos = []
    for clave, (donde, nombre, texto, maximo) in _textos_con_tope(cat_despues).items():
        largo = _largo(texto)
        if largo <= maximo or (clave in antes and antes[clave][2] == texto):
            continue
        motivos.append(f"{donde}: {nombre} tiene {largo} caracteres y el máximo es {maximo}. Acórtala y vuelve a proponerlo.")
    return motivos


# ───────────────────────────────────── Archivos ignorados ─────────────────────────────────────
#
# Cada edición puede llevar `ignorar`: patrones al estilo de un `.gitignore` con los archivos de la carpeta del
# juego que no cuentan para reconocerla (configuración, caché: lo que el juego o el usuario cambian). Tiene
# límites, para que nadie deje la huella en «todo ignorado menos el .exe». Son los mismos que aplica el
# parcheador (`ReglasIgnorados` en Parcheador.Core); si cambian allí, cambian aquí.
#
#   - Patrones prohibidos: los que valen para cualquier archivo (`*`, `**`, `**/*`, `*.*`, `*/*`…), los
#     vacíos, los que salen de la carpeta (`..`, rutas absolutas) y los de ejecutables (`.exe`, `.dll`).
#   - Como mucho 50 patrones de 200 caracteres.
#   - Nunca pueden encajar con un archivo que el parche modifica (`huellasParcheadas` y, en los paquetes
#     nuevos, su manifiesto) ni con un archivo de la `huella` (lo ignorado no entra en la huella).
#   - En la huella tiene que quedar al menos el 80 % de los bytes y el 70 % de los archivos.
#
# El robot no ve la carpeta del juego: los porcentajes los comprueba con `ignorados` (`archivos` y `bytes`),
# el resumen que escribe el parcheador junto a la lista. Quien lo falsee a mano se salta el porcentaje, pero
# no las demás reglas. Tampoco puede comprobar aquí el tope de un patrón solo ni «los 10 archivos más
# grandes»: eso lo hace el parcheador, que sí tiene la carpeta delante.

IGNORAR_MAXIMO_PATRONES = 50
IGNORAR_LARGO_MAXIMO = 200
IGNORAR_MINIMO_BYTES = 0.80
IGNORAR_MINIMO_ARCHIVOS = 0.70
_IGNORAR_CUALQUIERA = ("q7x", "q7x.q7x", "q7x/q7x", "q7x/q7x.q7x", "q7x/q7x/q7x.q7x")
_IGNORAR_EJECUTABLES = ("q7x.exe", "q7x.dll", "q7x/q7x.exe", "q7x/q7x.dll")


def _es_ejecutable(ruta: str) -> bool:
    return ruta.lower().endswith((".exe", ".dll"))


def regex_ignorar(patron: str):
    """El patrón como expresión regular, igual que `OpcionesHuella.Convertir` del parcheador: `*` = cualquier
    cosa dentro de un nombre, `**` = cualquier número de carpetas, `?` = un carácter; sin distinguir
    mayúsculas; un patrón sin `/` vale en cualquier carpeta."""
    patron = patron.strip().replace("\\", "/").lstrip("/")
    if "/" not in patron:
        patron = "**/" + patron
    partes, i = ["^"], 0
    while i < len(patron):
        c = patron[i]
        if c == "*" and patron[i + 1:i + 2] == "*":
            if patron[i + 2:i + 3] == "/":
                partes.append("(?:.*/)?")
                i += 3
            else:
                partes.append(".*")
                i += 2
            continue
        partes.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
        i += 1
    return re.compile("".join(partes) + "$", re.IGNORECASE)


def error_de_patron(patron):
    """Por qué ese patrón no vale por sí mismo, o None si vale."""
    if not isinstance(patron, str) or not patron.strip():
        return "está vacío o no es un texto"
    limpio = patron.strip().replace("\\", "/")
    if len(limpio) > IGNORAR_LARGO_MAXIMO:
        return f"es demasiado largo (más de {IGNORAR_LARGO_MAXIMO} caracteres)"
    if limpio.startswith("/") or ":" in limpio or any(parte in ("..", ".") for parte in limpio.split("/")):
        return "tiene que ser una ruta relativa dentro de la carpeta del juego (sin `..`, sin unidad y sin `/` al principio)"
    if any(ord(c) < 32 or ord(c) == 127 for c in limpio):
        return "tiene caracteres que no valen"
    regex = regex_ignorar(limpio)
    if any(regex.match(prueba) for prueba in _IGNORAR_CUALQUIERA):
        return "vale para cualquier archivo: ignoraría la carpeta entera"
    if _es_ejecutable(limpio) or any(regex.match(prueba) for prueba in _IGNORAR_EJECUTABLES):
        return "los ejecutables (`.exe` y `.dll`) no se pueden ignorar"
    return None


def _rutas(archivos):
    return [a["ruta"] for a in archivos or [] if isinstance(a, dict) and isinstance(a.get("ruta"), str)]


def validar_ignorados(donde: str, edicion: dict) -> list:
    """Las reglas de `ignorar` e `ignorados` de una edición. Valen para cualquier rol."""
    ignorar, resumen = edicion.get("ignorar"), edicion.get("ignorados")
    if ignorar is None and resumen is None:
        return []
    if ignorar is None or not isinstance(ignorar, list):
        return [f"{donde}: `ignorar` tiene que ser una lista de patrones (y `ignorados` solo va con ella)."]
    if not ignorar:
        return [f"{donde}: `ignorados` sobra si la lista `ignorar` está vacía."] if resumen is not None else []
    if len(ignorar) > IGNORAR_MAXIMO_PATRONES:
        return [f"{donde}: `ignorar` tiene {len(ignorar)} patrones y el máximo es {IGNORAR_MAXIMO_PATRONES}."]

    errores, patrones = [], []
    for patron in ignorar:
        error = error_de_patron(patron)
        if error:
            errores.append(f"{donde}: el patrón de `ignorar` {patron!r} no vale: {error}.")
        else:
            patrones.append((patron, regex_ignorar(patron)))

    def encaja(ruta):
        ruta = ruta.replace("\\", "/")
        return next((patron for patron, regex in patrones if regex.match(ruta)), None)

    huella = edicion.get("huella") if isinstance(edicion.get("huella"), list) else []
    for ruta in _rutas(huella):
        patron = encaja(ruta)
        if patron:
            errores.append(f"{donde}: `{ruta}` está en la `huella` y también lo ignora `{patron}`. Lo ignorado no "
                           "entra en la huella: vuelve a registrar la edición con el parcheador.")
            break
    for parcheada in edicion.get("huellasParcheadas") or []:
        if not isinstance(parcheada, dict):
            continue
        for ruta in _rutas(parcheada.get("archivos")):
            patron = encaja(ruta)
            if patron:
                errores.append(f"{donde}: el patrón `{patron}` ignoraría `{ruta}`, que es un archivo que el parche "
                               f"modifica (versión `{parcheada.get('version')}`). Los archivos del parche no se pueden ignorar.")

    if not isinstance(resumen, dict) or not _es_entero(resumen.get("archivos")) or not _es_entero(resumen.get("bytes")) \
            or resumen["archivos"] < 0 or resumen["bytes"] < 0:
        errores.append(f"{donde}: con `ignorar` tiene que ir `ignorados` (`{{ \"archivos\": …, \"bytes\": … }}`): cuánto deja "
                       "fuera la lista. Lo escribe el parcheador al registrar la edición.")
        return errores
    en_huella = len(huella)
    bytes_huella = sum(a["tamano"] for a in huella if isinstance(a, dict) and _es_entero(a.get("tamano")) and a["tamano"] > 0)
    archivos, tamano = en_huella + resumen["archivos"], bytes_huella + resumen["bytes"]
    if archivos > 0 and en_huella < archivos * IGNORAR_MINIMO_ARCHIVOS:
        errores.append(f"{donde}: se ignoran {resumen['archivos']} de {archivos} archivos. En la huella tiene que quedar "
                       f"al menos el {IGNORAR_MINIMO_ARCHIVOS:.0%} de los archivos.")
    if tamano > 0 and bytes_huella < tamano * IGNORAR_MINIMO_BYTES:
        errores.append(f"{donde}: se ignora el {resumen['bytes'] / tamano:.0%} del tamaño de la carpeta. En la huella "
                       f"tiene que quedar al menos el {IGNORAR_MINIMO_BYTES:.0%}.")
    return errores


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
# cracks. Hay dos listas y cuentan las dos a la vez:
#
#   general    `normas/archivos-prohibidos.json`. Vale para todos los parches. Solo la cambia el
#              Propietario (`normas/` es suyo, ver `_comprobar_archivos`). Se lee siempre de `main`.
#   del grupo  `grupo.archivosProhibidos` en el catálogo (la ficha del grupo). Vale para los parches de este
#              catálogo, que son los del grupo. La cambian quienes pueden cambiar `grupo`: Administradores y
#              Propietario. Solo puede **añadir**: no hay forma de escribir excepciones, así que nunca quita
#              nada de la general. Cuenta la de `main` y la de la propuesta a la vez: quitar una entrada
#              surte efecto en la propuesta siguiente, no en la misma.
#
# De dónde sale qué archivos toca un parche: lo único fiable es el `manifiesto.json` de dentro del `.zip`
# (es lo que ejecuta el parcheador). `huellasParcheadas` del catálogo se escribe a mano o con el publicador
# y el parcheador no la contrasta con el paquete, así que se mira también, pero no basta. Por eso el robot
# descarga cada paquete nuevo, comprueba que su tamaño y su hash son los del catálogo (los mismos que exige
# el parcheador antes de instalarlo) y lee las rutas de su manifiesto. Nunca ejecuta nada del paquete.

RUTA_PROHIBIDOS = "normas/archivos-prohibidos.json"
CARPETA_NORMAS = "normas/"

# Carpetas que solo cambia el Propietario (ni siquiera los Administradores): las normas generales y lo que
# las hace cumplir. Si un Administrador pudiera cambiar el robot o sus flujos de trabajo, podría quitar
# cualquier regla, también la de que `normas/` es del Propietario.
SOLO_PROPIETARIO = {
    CARPETA_NORMAS: "lo que hay en las normas generales (la lista general de archivos prohibidos y la cuenta del Propietario)",
    "robot/": "el robot de permisos",
    ".github/": "la configuración de GitHub (los flujos de trabajo que ejecutan el robot)",
}


# Lo único que cambia un Administrador (y, con sus límites, Editores y Colaboradores). Es una lista blanca a
# propósito: cualquier otro archivo (en la raíz o en cualquier carpeta), salvo `canales/`, es del Dueño. El robot y las pruebas
# se ejecutan con el `main` descargado como carpeta de trabajo, así que un `venv.py`, `unittest.py`,
# `sitecustomize.py`, `.gitattributes`… en la raíz podría acabar ejecutándose con el permiso de escritura del robot.
# Se compara tal cual, distinguiendo mayúsculas: `Catalogo/` es otra carpeta para git y no vale.
CARPETA_CATALOGO = "catalogo/"


def es_python_compilado(ruta: str) -> bool:
    partes = ruta.replace("\\", "/").lower().split("/")
    return "__pycache__" in partes or partes[-1].endswith((".pyc", ".pyo"))


def _carpeta_del_propietario(ruta: str):
    ruta = ruta.lower()
    return next((c for c in SOLO_PROPIETARIO if ruta.startswith(c)), None)


def _fuera_del_catalogo(ruta: str) -> bool:
    return not ruta.startswith(CARPETA_CATALOGO)
CAMPO_PROHIBIDOS_GRUPO = "archivosProhibidos"
TAMANO_MAXIMO_PAQUETE = 4 * 1024 * 1024 * 1024
TAMANO_MAXIMO_MANIFIESTO = 16 * 1024 * 1024
NOMBRE_MANIFIESTO = "manifiesto.json"


@dataclass(frozen=True)
class Prohibido:
    patron: str
    motivo: str = ""
    lista: str = "general"  # «general» o «del grupo X»: sale en el aviso

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


def _leer_patrones(patrones, donde: str, lista: str):
    """Lista JSON de `{patron, motivo}` → (lista de `Prohibido`, errores)."""
    if not isinstance(patrones, list):
        return [], [f"{donde} tiene que ser una lista de `{{ \"patron\": …, \"motivo\": … }}`."]
    resultado, errores = [], []
    for p in patrones:
        if not isinstance(p, dict) or not isinstance(p.get("patron"), str) or not p["patron"].strip("/ "):
            errores.append(f"{donde}: hay un patrón vacío o mal escrito ({p!r}).")
            continue
        resultado.append(Prohibido(p["patron"].strip(), str(p.get("motivo") or ""), lista))
    return resultado, errores


def leer_prohibidos(texto: str) -> list:
    """La lista general (`normas/archivos-prohibidos.json`) → lista de `Prohibido`. Si está mal, falla:
    mejor no aceptar nada que aceptar sin comprobar."""
    datos = json.loads(texto)
    patrones = datos.get("patrones") if isinstance(datos, dict) else None
    if not isinstance(patrones, list) or not patrones:
        raise ValueError(f"`{RUTA_PROHIBIDOS}` no tiene una lista `patrones`.")
    resultado, errores = _leer_patrones(patrones, f"`{RUTA_PROHIBIDOS}`", "general")
    if errores:
        raise ValueError(errores[0])
    return resultado


def prohibidos_del_grupo(catalogo):
    """La lista propia del grupo (`grupo.archivosProhibidos` del catálogo) → (lista de `Prohibido`, errores)."""
    grupo = catalogo.get("grupo") if isinstance(catalogo, dict) else None
    if not isinstance(grupo, dict) or grupo.get(CAMPO_PROHIBIDOS_GRUPO) is None:
        return [], []
    nombre = grupo.get("nombre")
    lista = f"del grupo {nombre}" if isinstance(nombre, str) and nombre.strip() else "del grupo"
    return _leer_patrones(grupo[CAMPO_PROHIBIDOS_GRUPO], f"`grupo.{CAMPO_PROHIBIDOS_GRUPO}`", lista)


def archivo_prohibido(ruta: str, prohibidos):
    return next((p for p in prohibidos if p.coincide(ruta)), None)


def mensaje_protegido(donde: str, ruta: str, norma: Prohibido) -> str:
    origen = (f"`{RUTA_PROHIBIDOS}`" if norma.lista == "general"
              else f"`canales/{canales.CANAL_OFICIAL}/lista-negra.json`" if norma.lista.startswith("del canal")
              else f"`grupo.{CAMPO_PROHIBIDOS_GRUPO}` del catálogo")
    return (f"{donde}: Este parche toca un archivo protegido ({ruta}). Los parches no pueden modificar "
            f"archivos de protección anticopia. Lo bloquea la lista **{norma.lista}**: norma `{norma.patron}` "
            f"de {origen}" + (f" — {norma.motivo}" if norma.motivo else "."))


class PaqueteIlegible(Exception):
    """No se ha podido leer el paquete o no es el que dice el catálogo."""


def comprobar_archivos_protegidos(cat_antes, cat_despues: dict, prohibidos, leer_paquete) -> list:
    # Primero la general: si un archivo está en las dos, el aviso dice «general».
    del_grupo_antes, _ = prohibidos_del_grupo(cat_antes)
    del_grupo, motivos = prohibidos_del_grupo(cat_despues)
    vistos = {(p.patron.lower(), p.lista) for p in del_grupo}
    del_grupo += [p for p in del_grupo_antes if (p.patron.lower(), p.lista) not in vistos]
    todos = list(prohibidos) + del_grupo

    for donde, ruta in _rutas_parcheadas(cat_despues):
        norma = archivo_prohibido(ruta, todos)
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
                norma = archivo_prohibido(ruta, todos)
                if norma:
                    motivos.append(mensaje_protegido(donde, ruta, norma))
            motivos += _ignorados_que_toca(cat_despues, donde, paquete, rutas)
    return _sin_repetidos(motivos)


def _ignorados_que_toca(catalogo: dict, donde: str, paquete: dict, rutas) -> list:
    """Un paquete nuevo no puede tocar un archivo que su edición ignora (se mira con su manifiesto)."""
    motivos = []
    for juego in catalogo.get("juegos") or []:
        if not isinstance(juego, dict) or not donde.startswith(f"`{juego.get('id')}`"):
            continue
        for edicion in juego.get("ediciones") or []:
            if not isinstance(edicion, dict) or edicion.get("id") != paquete.get("edicion"):
                continue
            patrones = [(p, regex_ignorar(p)) for p in edicion.get("ignorar") or [] if error_de_patron(p) is None]
            for ruta in rutas:
                patron = next((p for p, regex in patrones if regex.match(ruta.replace("\\", "/"))), None)
                if patron:
                    motivos.append(f"{donde}: el paquete toca `{ruta}`, que la edición ignora con `{patron}`. Un parche "
                                   "no puede modificar un archivo ignorado: quita el patrón o el archivo del parche.")
    return motivos


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
        if c.ruta == RUTA_CATALOGO or c.ruta.startswith(canales.CARPETA_CANALES):
            continue  # lo decide _comprobar_campos (catálogo) o canales.py (`canales/`)
        if c.ruta.lower().startswith(canales.CARPETA_CANALES) and not permisos.es_dueno:
            motivos.append(f"`{c.ruta}`: la carpeta de los canales se escribe `canales/`, en minúsculas.")
            continue
        carpeta = _carpeta_del_propietario(c.ruta)
        if carpeta is not None:
            if not permisos.es_dueno:
                motivos.append(f"`{c.ruta}`: {SOLO_PROPIETARIO[carpeta]} (`{carpeta}`) solo lo cambia el "
                               "Dueño del programa." + (" Un canal puede añadir archivos a su propia lista en "
                                                        "`canales/<canal>/lista-negra.json`."
                                                        if carpeta == CARPETA_NORMAS else ""))
            continue
        if _fuera_del_catalogo(c.ruta):
            if not permisos.es_dueno:
                motivos.append(f"`{c.ruta}`: lo que está fuera de `catalogo/` y `canales/` solo lo cambia el "
                               "Dueño del programa. Un Administrador cambia `catalogo/catalogo.json` y lo que hay "
                               "en `catalogo/`.")
            continue
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


_SIN_ROL = ("Tu cuenta no tiene ningún rol en el canal @ornizen (Administrador, Editor o Colaborador), "
            "así que el robot no puede aceptar cambios tuyos. Si eres del equipo, pide a un Administrador "
            "que te invite y acepta la invitación desde el parcheador.")


def _comprobar_campos(antes: dict, despues: dict, permisos: Permisos) -> list:
    motivos = []

    # ── Raíz del catálogo: el parcheador (`launcher`), el grupo… son de Administrador. Las etiquetas
    #    (`etiquetas`) son globales, valen para todos los juegos: crearlas, editarlas o borrarlas es solo
    #    del Propietario. Ponerlas o quitarlas en un juego (`juegos[].etiquetas`) no es esto: va con el juego.
    for clave in _claves_distintas(antes, despues):
        if clave == "etiquetas":
            if not permisos.es_dueno:
                motivos.append("`etiquetas`: las etiquetas del catálogo son globales y solo las crea, edita o "
                               "borra el Dueño del programa (los demás roles ponen y quitan en sus juegos etiquetas "
                               "que ya existen, pero no las crean ni las editan).")
        elif clave not in RAIZ_LIBRE and permisos.rol_global < Rol.ADMINISTRADOR:
            motivos.append(f"`{clave}`: esta parte del catálogo solo la cambia un Administrador.")

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
    except (ValueError, RecursionError):  # JSONDecodeError, enteros de miles de cifras, anidación absurda
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


RUTA_PROPIETARIO = "normas/propietario.json"


def leer_propietarios(texto: str) -> set:
    """`normas/propietario.json` → cuentas (en minúsculas) del Dueño del programa (formato de antes, sin ids)."""
    return canales.leer_duenos(texto)[1]


@dataclass(frozen=True)
class Canales:
    """Lo que hay en `main` de cada canal: sus miembros y las cuentas de su lista negra."""
    miembros: dict = field(default_factory=dict)  # {canal: {id: canales.Miembro}}
    vetados: dict = field(default_factory=dict)   # {canal: set de ids}

    def rol(self, canal: str, cuenta_id) -> Rol:
        if cuenta_id in self.vetados.get(canal, ()):
            return Rol.NINGUNO
        return Rol(canales.rol_en_canal(self.miembros.get(canal, {}), cuenta_id))


def _archivos_de_canales_en_carpeta(raiz: pathlib.Path):
    """{ruta: bytes} de `canales/*/miembros.json` y `lista-negra.json` de una carpeta (las pruebas). Un enlace
    simbólico o algo que no sea un archivo normal es un error, no se sigue."""
    archivos = {}
    carpeta = raiz / canales.CARPETA_CANALES
    if carpeta.is_symlink():
        raise ValueError("`canales/` es un enlace simbólico")
    for dir_canal in sorted(carpeta.iterdir()) if carpeta.is_dir() else []:
        if dir_canal.is_symlink():
            raise ValueError(f"`canales/{dir_canal.name}` es un enlace simbólico")
        if not dir_canal.is_dir():
            continue
        for nombre in ("miembros.json", "lista-negra.json"):
            archivo = dir_canal / nombre
            ruta = f"canales/{dir_canal.name}/{nombre}"
            if archivo.is_symlink() or (archivo.exists() and not archivo.is_file()):
                raise ValueError(f"`{ruta}` no es un archivo normal")
            if archivo.is_file():
                archivos[ruta] = archivo.read_bytes()
    return archivos


def archivo_de_git(revision: str, ruta: str, tope: int):
    """Bytes de `ruta` en `revision` (None si no existe). Si no es un archivo normal (100644) o pasa del tope, error:
    nunca se sigue un enlace simbólico ni se carga un archivo enorme."""
    salida = git("ls-tree", "-z", "--full-tree", revision, "--", ruta).stdout.decode()
    entradas = [e for e in salida.split("\0") if e]
    if not entradas:
        return None
    modo, tipo, sha = entradas[0].split("\t", 1)[0].split(" ")
    if modo != "100644" or tipo != "blob":
        raise ValueError(f"`{ruta}` no es un archivo normal en `{revision}` (modo {modo})")
    tamano = int(git("cat-file", "-s", sha).stdout.decode().strip())
    if tamano > tope:
        raise ValueError(f"`{ruta}` pesa {tamano} bytes en `{revision}` y el máximo son {tope}")
    return git("cat-file", "blob", sha).stdout


def _archivos_de_canales_en_git(revision: str):
    salida = git("ls-tree", "-r", "-z", "--full-tree", "--name-only", revision, "--", canales.CARPETA_CANALES).stdout.decode()
    archivos = {}
    for ruta in sorted(e for e in salida.split("\0") if e):
        partes = ruta.split("/")
        if len(partes) == 3 and partes[2] in ("miembros.json", "lista-negra.json"):
            archivos[ruta] = archivo_de_git(revision, ruta, canales.TOPES[partes[2]])
    return archivos


def leer_canales(raiz: pathlib.Path | None = None, revision: str | None = None) -> Canales:
    """`canales/*/miembros.json` y `lista-negra.json` de `main`: con git de `revision` (el robot, de `origin/main`
    recién traído) o de la carpeta `raiz` (las pruebas). Si uno está mal, falla: mejor no aceptar nada que aceptar con
    roles que no son."""
    archivos = _archivos_de_canales_en_git(revision) if revision else _archivos_de_canales_en_carpeta(raiz)
    miembros, vetados = {}, {}
    for ruta, datos in archivos.items():
        canal, nombre = ruta.split("/")[1:3]
        objeto = canales.leer_json_estricto(datos, ruta, canales.TOPES[nombre])
        if nombre == "miembros.json":
            leidos, errores = canales.leer_miembros(objeto, ruta)
            if errores:
                raise ValueError(errores[0])
            miembros[canal] = leidos
        else:
            lista, errores = canales.leer_lista_negra(objeto, ruta)
            if errores:
                raise ValueError(errores[0])
            vetados[canal] = set(lista.usuarios)
    return Canales(miembros, vetados)


def permisos_de(usuario: str, api, equipo: dict, propietarios=frozenset(), cuenta_id=None,
                canales_main: Canales | None = None, ids_duenos=frozenset()) -> Permisos:
    """Lo que puede la cuenta: su rol en cada canal (`canales/<c>/miembros.json` de `main`, por id) y, para el catálogo
    de hoy, el del canal oficial.

    Transición de la fase A: en el canal oficial cuenta el mayor entre el archivo y el equipo de GitHub (los equipos
    se quitan en la fase B), salvo que la cuenta esté en la lista negra del canal: entonces no tiene nada.
    Dueño del programa: su id en `normas/propietario.json` → `duenos`. Si el archivo aún no tiene ids, como antes: la
    cuenta en `propietario` y además `admin` del repositorio.
    """
    canales_main = canales_main or Canales()
    if not usuario or usuario.endswith("[bot]"):
        return Permisos(Rol.NINGUNO)
    vetado = cuenta_id is not None and cuenta_id in canales_main.vetados.get(canales.CANAL_OFICIAL, ())

    de_github = Rol.NINGUNO
    respuesta = api("GET", f"/collaborators/{usuario}/permission", tolerar=(404,))
    if respuesta:
        de_github = ROL_DE_GITHUB.get(respuesta.get("role_name") or respuesta.get("permission"), Rol.NINGUNO)

    if cuenta_id is not None and cuenta_id in ids_duenos:
        es_dueno = True
    else:
        es_dueno = not ids_duenos and de_github == Rol.ADMINISTRADOR and usuario.lower() in propietarios
    if es_dueno:
        return Permisos(Rol.DUENO, cuenta_id=cuenta_id)

    por_canal = {c: canales_main.rol(c, cuenta_id) for c in canales_main.miembros} if cuenta_id is not None else {}
    oficial = Rol.NINGUNO if vetado else max(por_canal.get(canales.CANAL_OFICIAL, Rol.NINGUNO), de_github)
    if por_canal or oficial:
        por_canal[canales.CANAL_OFICIAL] = oficial
    por_canal = {c: r for c, r in por_canal.items() if r}

    extra = equipo.get(usuario.lower())
    if extra is None:
        return Permisos(oficial, por_canal=por_canal, cuenta_id=cuenta_id)
    return Permisos(max(oficial, extra.rol_global), dict(extra.por_juego), por_canal, cuenta_id)


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


def traer(numero: int, cabeza: str) -> str:
    """Trae el `main` de ahora mismo y la propuesta, y fija ese `main` (su commit): las reglas (`normas/`, los
    miembros de `canales/`) y la comparación salen del mismo commit, nunca de la copia con la que arrancó el robot."""
    git("fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main",
        f"+refs/pull/{numero}/head:refs/remotes/propuesta/cabeza")
    if git("rev-parse", "refs/remotes/propuesta/cabeza").stdout.decode().strip() != cabeza:
        raise RuntimeError("La propuesta ha cambiado mientras se comprobaba; el robot volverá a mirarla.")
    return git("rev-parse", "refs/remotes/origin/main").stdout.decode().strip()


def leer_propuesta(base: str, cabeza: str):
    """Une la propuesta con `base` (el commit de `main` traído por `traer`, sin ejecutar nada) y devuelve lo que cambia.

    Devuelve (cambios, catálogo antes, catálogo después, leer_archivo) o None si hay conflicto con `main`.
    """
    union = git("merge-tree", "--write-tree", base, cabeza, comprobar_salida=False)
    if union.returncode != 0:
        return None
    arbol = union.stdout.decode().split()[0]

    cambios = []
    bruto = git("diff", "--raw", "-z", "--no-renames", "--no-abbrev", base, arbol).stdout.decode()
    partes = bruto.split("\0")
    for i in range(0, len(partes) - 1, 2):
        _, modo_nuevo, _, _, estado = partes[i].lstrip(":").split(" ")
        ruta = partes[i + 1]
        tamano = 0
        if estado != "D":
            tamano = int(git("cat-file", "-s", f"{arbol}:{ruta}").stdout.decode().strip())
        cambios.append(Cambio(ruta, estado[0], modo_nuevo, tamano))

    def leer(revision):
        salida = git("show", f"{revision}:{RUTA_CATALOGO}", comprobar_salida=False)
        return salida.stdout if salida.returncode == 0 else None

    def leer_archivo(ruta, lado):
        """Bytes del archivo en `main` o tras la propuesta (None si no existe). Solo se usa con los de `canales/`,
        y el tamaño se mira antes con `cat-file -s` (un archivo enorme no se llega a cargar)."""
        revision = base if lado == "antes" else arbol
        tamano = git("cat-file", "-s", f"{revision}:{ruta}", comprobar_salida=False)
        if tamano.returncode != 0:
            return None
        nombre = ruta.rsplit("/", 1)[-1]
        if int(tamano.stdout.decode().strip()) > canales.TOPES.get(nombre, canales.TOPE_LOGO):
            return b" " * (canales.TOPES.get(nombre, canales.TOPE_LOGO) + 1)  # basta para que se rechace por tamaño
        return git("cat-file", "blob", f"{revision}:{ruta}").stdout  # también los logos: se mira qué son de verdad

    # `main` se lee con tolerancia (solo sirve para comparar); la propuesta, en bytes: `validar_catalogo` exige
    # UTF-8 estricto, como el parcheador.
    antes = leer(base)
    return cambios, (antes.decode("utf-8", errors="replace") if antes is not None else None), leer(arbol), leer_archivo


TOPE_MOTIVOS = 40
LARGO_MOTIVO = 1500
LARGO_CODIGO = 200
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]+")
_PROSA = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\\": "\\\\", "[": "\\[", "]": "\\]", "|": "\\|"})
# Dentro de `<code>` GitHub sigue leyendo Markdown: ahí también se escapan los de énfasis (`__pycache__` no es negrita).
_CODIGO = str.maketrans({"*": "\\*", "_": "\\_", "~": "\\~"})


def _sin_enlaces(texto: str) -> str:
    texto = texto.translate(_PROSA)
    # Ni menciones (`@cuenta` avisa a esa persona), ni referencias a propuestas (`#12`), ni enlaces automáticos.
    texto = re.sub(r"@", "@\u2060", texto)
    texto = re.sub(r"#(?=\d)", "#\u2060", texto)
    return texto.replace("://", ":\u2060//").replace("www.", "www\u2060.")


def linea_segura(motivo: str) -> str:
    """Un motivo listo para ir en el comentario, aunque lleve nombres de archivo, claves o cuentas de la propuesta
    (tercera revisión, N4): en una sola línea y recortado, con lo que va entre acentos graves como `<code>`, y sin HTML,
    enlaces, imágenes ni menciones en ninguna parte. Si algo de la propuesta trae su propio acento grave, como mucho
    cambia qué trozo sale en código: nunca se interpreta."""
    trozos = _CONTROL.sub(" ", str(motivo)).split("`")
    if len(trozos) % 2 == 0:  # un acento grave suelto: el último trozo es texto normal
        trozos[-2:] = [trozos[-2] + "ˋ" + trozos[-1]]
    salida, quedan = [], LARGO_MOTIVO
    for i, trozo in enumerate(trozos):
        if quedan <= 0:
            salida.append("…")
            break
        tope = min(quedan, LARGO_CODIGO) if i % 2 else quedan
        if len(trozo) > tope:
            trozo = trozo[:tope] + "…"
        quedan -= len(trozo)
        seguro = _sin_enlaces(trozo)
        salida.append(seguro if i % 2 == 0 else "<code>" + seguro.translate(_CODIGO) + "</code>")
    return "".join(salida)


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


def aviso_fallo_instalacion(fusionar: bool) -> str:
    """El comentario cuando no se ha podido instalar BLAKE3 (robot/instalar.sh): un fallo de red pasajero.

    Tiene que quedar claro que NO es un rechazo: la propuesta ni siquiera se ha llegado a mirar.
    """
    que = ("La propuesta ya estaba aceptada, pero no se ha podido publicar"
           if fusionar else "La propuesta todavía no se ha comprobado")
    return ("### ⏳ Fallo temporal del robot de permisos (no es un rechazo)\n\n"
            f"{que}: el robot no ha podido instalar lo que necesita (BLAKE3, desde PyPI) por un corte de red, "
            "ni siquiera tras varios intentos. **No hay nada mal en la propuesta.**\n\n"
            "Para volver a intentarlo: en la pestaña «Checks», «Re-run failed jobs» (hace falta permiso de "
            "escritura), o sube cualquier cambio a esta misma propuesta.")


SHA = re.compile(r"^[0-9a-f]{40}$")


def cabeza_del_evento(propuesta: dict, entorno) -> str:
    """El commit que se comprueba es el del evento que lanzó la ejecución (`PR_CABEZA`), no el que la API diga ahora.

    Si no coinciden, alguien ha subido otro commit desde entonces (o se está relanzando una ejecución vieja): lo que
    se sabe de quién empujó ya no vale para ese commit nuevo. Se para; la ejecución del commit nuevo lo comprueba.
    """
    evento = (entorno.get("PR_CABEZA") or "").strip().lower()
    if not SHA.match(evento):
        raise RuntimeError("Falta `PR_CABEZA` (el commit de la propuesta en el evento): revisa el flujo de trabajo.")
    actual = ((propuesta.get("head") or {}).get("sha") or "").lower()
    if actual != evento:
        raise RuntimeError(f"La propuesta ha cambiado desde el evento que lanzó esta ejecución (era {evento[:7]}, ahora "
                           f"es {actual[:7]}). No se publica nada: la comprobación del último cambio decide.")
    return evento


def motivo_de_base(propuesta: dict):
    """Las propuestas solo valen contra `main` (se mira también al editarla: cambiar la base lanza el robot)."""
    base = (propuesta.get("base") or {}).get("ref")
    if base != "main":
        return f"La propuesta va contra `{base}`: el robot solo publica propuestas contra `main`."
    return None


def cuentas_de_la_ejecucion(entorno, autor: str, autor_id: int, id_de_cuenta) -> list:
    """[(cuenta, id)] que cuentan para el rol: quien abrió la propuesta, quien lanzó el evento (`PR_ACTOR`, p. ej. quien
    subió el último commit) y quien ha lanzado esta ejecución (`PR_DISPARADOR`: distinto si alguien la relanza).
    `id_de_cuenta(nombre)` da el id actual de una cuenta por su nombre (None si no existe)."""
    actor = entorno.get("PR_ACTOR") or autor
    # Las cuentas van por id: sin el id de quien ha subido el último cambio no se adivina por su nombre (un nombre
    # se puede soltar y otra cuenta quedárselo).
    if not (entorno.get("PR_ACTOR_ID") or "").isdigit():
        raise RuntimeError("Falta `PR_ACTOR_ID` (el id de la cuenta que ha subido el último cambio): revisa el flujo de trabajo.")
    actor_id = int(entorno["PR_ACTOR_ID"])
    if actor.lower() == autor.lower() and actor_id != autor_id:
        actor = f"{actor} (otra cuenta con ese nombre)"
    cuentas = [(autor, autor_id), (actor, actor_id)]
    disparador = (entorno.get("PR_DISPARADOR") or "").strip()
    if disparador and disparador.lower() not in (autor.lower(), actor.lower()):
        disparador_id = id_de_cuenta(disparador)
        if not isinstance(disparador_id, int):
            raise RuntimeError(f"No se encuentra la cuenta `{disparador}`, que ha lanzado esta ejecución.")
        cuentas.append((disparador, disparador_id))
    vistas, resultado = set(), []
    for cuenta, cuenta_id in cuentas:
        if cuenta_id not in vistas:
            vistas.add(cuenta_id)
            resultado.append((cuenta, cuenta_id))
    return resultado


# La cuenta con la que GitHub firma los commits hechos en la web o por su API: no es una persona, no cuenta.
ID_WEB_FLOW = 19864447
TOPE_COMMITS = 250       # lo más que devuelve GitHub de los commits de una propuesta
TOPE_SUBIDAS = 100       # subidas a la propuesta que el robot sigue hacia atrás, de la cabeza a cuando se abrió
TOPE_PAGINAS_POR_COMMIT = 10  # de 100 en 100: lo que se lee de las ejecuciones del robot con un mismo commit
TOPE_SUBIDAS_POR_COMMIT = 200  # subidas de esta propuesta con un mismo commit (contadas después de filtrar)
TOPE_CUENTAS = 10        # cuentas distintas que han intervenido
FLUJO_DEL_ROBOT = ".github/workflows/permisos.yml"
# Los eventos en los que quien lanza la ejecución es quien ha subido la cabeza de la propuesta.
ACCIONES_DE_SUBIDA = ("opened", "synchronize")
# El nombre de cada ejecución del robot (`run-name` en permisos.yml): número de la propuesta, acción del evento y
# commit sobre el que se subió la cabeza (`before`, solo en `synchronize`). Lo escribe GitHub con los datos del evento
# y el flujo de `main`: nadie puede ponérselo a mano a la ejecución de otro.
NOMBRE_DE_EJECUCION = re.compile(r"Robot de permisos · #([0-9]+) · ([a-z_]+) · antes (ninguno|[0-9a-f]{40})")
SHA_COMPLETO = re.compile(r"[0-9a-f]{40}")
# La línea exacta de `permisos.yml` que da ese nombre. Si el flujo de `main` no la tiene, ninguna ejecución vale.
RUN_NAME = ('run-name: "Robot de permisos · #${{ github.event.pull_request.number }} · ${{ github.event.action }} · '
            "antes ${{ github.event.before || 'ninguno' }}\"")


class SinSaberQuien(Exception):
    """No se puede saber con certeza qué cuentas han subido los cambios de la propuesta: se rechaza."""


class DemasiadasEjecuciones(SinSaberQuien):
    """Un commit tiene más ejecuciones del robot de las que se leen: ese eslabón de la cadena no se puede comprobar."""

    def __init__(self, sha: str, motivo: str):
        super().__init__(motivo)
        self.sha = sha


def _cuenta(usuario):
    return (usuario["login"], usuario["id"]) if isinstance(usuario, dict) and isinstance(usuario.get("id"), int) \
        and isinstance(usuario.get("login"), str) else None


def _commits(api, numero: int, propuesta: dict) -> list:
    if int(propuesta.get("commits") or 0) > TOPE_COMMITS:
        raise SinSaberQuien(f"la propuesta tiene más de {TOPE_COMMITS} commits: abre una nueva con los cambios juntos.")
    commits, pagina = [], 1
    while True:
        trozo = api("GET", f"/pulls/{numero}/commits?per_page=100&page={pagina}") or []
        commits += trozo
        if len(commits) > TOPE_COMMITS:
            raise SinSaberQuien(f"la propuesta tiene más de {TOPE_COMMITS} commits: abre una nueva con los cambios juntos.")
        if len(trozo) < 100:
            return commits
        pagina += 1


def _del_robot_y_de_esta_copia(ejecucion: dict, repo: str) -> bool:
    return (ejecucion.get("path") or "").split("@")[0] == FLUJO_DEL_ROBOT \
        and ejecucion.get("event") == "pull_request_target" \
        and (ejecucion.get("head_repository") or {}).get("full_name") == repo


def _actores(ejecucion: dict) -> list:
    cuentas = [_cuenta(ejecucion.get(papel)) for papel in ("actor", "triggering_actor")]
    if None in cuentas:
        raise SinSaberQuien("una ejecución del robot sobre esta propuesta no dice qué cuenta la lanzó.")
    return cuentas


def desde_cuando_hay_nombres(base: str) -> str:
    """Cuándo llegó a `main` el `run-name` del robot (UTC, como `created_at`). Las ejecuciones de antes llevan como
    nombre el título de la propuesta, que se puede escribir a mano: no valen como prueba de una subida. Se mira la
    fusión en `main` (primer padre), no el commit de la rama, que es más antiguo. Si el flujo de `main` no tiene
    exactamente el `run-name` que lee el robot (alguien lo quitó o lo cambió), ninguna vale (sexta revisión, punto 2):
    `git log -S` daría la fecha del commit que lo quita."""
    try:
        flujo = (archivo_de_git(base, FLUJO_DEL_ROBOT, 256 * 1024) or b"").decode("utf-8")
    except (OSError, ValueError, UnicodeDecodeError, subprocess.CalledProcessError):
        flujo = ""
    if RUN_NAME not in flujo.splitlines():
        return "9999-12-31T23:59:59Z"
    salida = git("log", "-1", "--no-patch", "--first-parent", "--diff-merges=first-parent", "-S", "run-name:", "--format=%ct", base,
                 "--", FLUJO_DEL_ROBOT).stdout.decode().strip()
    if not salida.isdigit():
        return "9999-12-31T23:59:59Z"
    return datetime.datetime.fromtimestamp(int(salida), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _subidas_con(api, sha: str, numero: int, repo: str, desde: str, guardadas: dict) -> list:
    """[(acción, antes, ejecución)]: las ejecuciones del robot de esta propuesta que vieron subir `sha` (`opened` o
    `synchronize`, por su nombre). Filtra primero y cuenta después (sexta revisión, punto 1): las ejecuciones de otras
    copias o propuestas con el mismo commit no cuentan para el tope de subidas. Solo si hay tantas que no se pueden
    leer (más de TOPE_PAGINAS_POR_COMMIT páginas), ese commit no se puede comprobar: DemasiadasEjecuciones."""
    if sha not in guardadas:
        subidas, filtro = [], urllib.parse.quote(">=" + desde, safe="")
        for pagina in range(1, TOPE_PAGINAS_POR_COMMIT + 2):
            trozo = (api("GET", f"/actions/workflows/{FLUJO_DEL_ROBOT.rsplit('/', 1)[1]}/runs?event=pull_request_target"
                                f"&head_sha={sha}&created={filtro}&per_page=100&page={pagina}") or {}).get("workflow_runs") or []
            if pagina > TOPE_PAGINAS_POR_COMMIT:
                if trozo:
                    raise DemasiadasEjecuciones(sha, (
                        f"el commit {sha[:7]} tiene más de {TOPE_PAGINAS_POR_COMMIT * 100} comprobaciones del robot (casi "
                        "todas de otras copias o propuestas) y el robot no puede leerlas todas para ver quién lo subió. "
                        "Abre una propuesta nueva desde una rama con commits nuevos (por ejemplo, rehaciendo los tuyos), "
                        "o pide al Dueño del programa que relance esta comprobación."))
                break
            for ejecucion in trozo:
                nombre = NOMBRE_DE_EJECUCION.fullmatch(str(ejecucion.get("display_title") or ""))
                if nombre and int(nombre[1]) == numero and nombre[2] in ACCIONES_DE_SUBIDA \
                        and ejecucion.get("head_sha") == sha and str(ejecucion.get("created_at") or "") >= desde \
                        and _del_robot_y_de_esta_copia(ejecucion, repo):
                    subidas.append((nombre[2], nombre[3], ejecucion))
            if len(subidas) > TOPE_SUBIDAS_POR_COMMIT:
                raise SinSaberQuien(f"el commit {sha[:7]} se ha subido más de {TOPE_SUBIDAS_POR_COMMIT} veces a esta "
                                    "propuesta: cierra esta y abre una nueva con los cambios juntos.")
            if len(trozo) < 100:
                break
        guardadas[sha] = subidas
    return guardadas[sha]


def _cadena_de_subidas(api, sha: str, numero: int, repo: str, desde: str):
    """Sigue las subidas hacia atrás desde `sha` hasta la que abrió la propuesta: cada `synchronize` dice quién subió
    qué commit y sobre cuál. Devuelve (actores de todas las subidas vistas, None, None) si llega a `opened`, o
    (actores, commit que nadie vio subir, motivo o None) si la cadena se rompe. Un commit con demasiadas ejecuciones
    para leerlas es un eslabón que falta (con su propio motivo), no un error: así el Dueño aún puede relanzarla."""
    pendientes, vistos, actores, guardadas, roto, motivo, abierta = [sha], set(), [], {}, None, None, False
    while pendientes:
        actual = pendientes.pop()
        if actual in vistos:
            continue
        vistos.add(actual)
        if len(vistos) > TOPE_SUBIDAS:
            raise SinSaberQuien(f"la propuesta tiene más de {TOPE_SUBIDAS} subidas: cierra esta y abre una nueva con los "
                                "cambios juntos.")
        try:
            subidas = _subidas_con(api, actual, numero, repo, desde, guardadas)
        except DemasiadasEjecuciones as error:
            subidas = []
            if roto is None:
                roto, motivo = actual, str(error)
        if not subidas and roto is None:
            roto = actual
        for accion, antes, ejecucion in subidas:
            actores += _actores(ejecucion)
            if accion == "opened":
                abierta = True
            elif antes != "ninguno":
                pendientes.append(antes)
    return actores, (None if abierta else roto or sha), (None if abierta else motivo)


def _relanzada_por_el_dueno(api, ejecucion_actual, intento, numero: int, cabeza: str, repo: str, es_dueno) -> bool:
    """Si esta ejecución es un relanzamiento de verdad (intento 2 o más) hecho por el Dueño, sobre la misma cabeza:
    relanzarla es responder de lo que hay en la propuesta (quinta revisión, punto 1). Se comprueba en la API, no solo
    en el entorno."""
    if not (str(intento or "").isdigit() and int(intento) > 1 and str(ejecucion_actual or "").isdigit()):
        return False
    ejecucion = api("GET", f"/actions/runs/{int(ejecucion_actual)}") or {}
    nombre = NOMBRE_DE_EJECUCION.fullmatch(str(ejecucion.get("display_title") or ""))
    disparador = _cuenta(ejecucion.get("triggering_actor"))
    return isinstance(ejecucion.get("run_attempt"), int) and ejecucion["run_attempt"] > 1 \
        and ejecucion.get("head_sha") == cabeza and _del_robot_y_de_esta_copia(ejecucion, repo) \
        and nombre is not None and int(nombre[1]) == numero \
        and disparador is not None and es_dueno(disparador[1])


def cuentas_de_la_propuesta(api, numero: int, propuesta: dict, cabeza: str, accion: str, ejecucion_actual,
                            es_dueno, actores_actuales=(), antes=None, intento=None, desde="") -> list:
    """[(cuenta, id)] de todos los que han subido algo a la propuesta (tercera revisión N3, cuarta 2.1, 2.2 y L8,
    quinta 1–4).

    El `sender` de `edited`, `reopened` o `ready_for_review` es quien pulsa, no quien subió los commits. Cuentan:
    - **quien subió cada commit**, siguiendo la cadena de subidas hacia atrás: la cabeza la subió quien lanza un
      `opened` o `synchronize` (esta ejecución) o, en cualquier otro evento, quien lanzó la ejecución que vio subirla.
      Cada `synchronize` dice sobre qué commit se subió (`before`), y así hasta la que abrió la propuesta. Las
      ejecuciones se reconocen por su nombre (`run-name`: propuesta, acción y `before`), que pone GitHub. Si un
      eslabón falta (se subió con la propuesta cerrada, se borró la ejecución, es de antes del `run-name`…), nadie
      sabe quién subió ese commit y se rechaza: subir otro encima no lo arregla. Solo vale que el Dueño **relance**
      esta ejecución (un relanzamiento de verdad, comprobado en la API): responde de lo que hay en la propuesta.
    - **quien abrió la propuesta y quien lanza esta ejecución** (`actores_actuales`): cuentan como subidores en
      `opened` y `synchronize` y al relanzar, también para L8.
    - **autor y committer de cada commit** (sin la firma de GitHub, `web-flow`). Se pueden falsear, pero falsearlos
      solo añade cuentas, y eso solo puede bajar el rol. Un commit cuyo correo no es de ninguna cuenta se rechaza,
      salvo que todo lo haya subido el Dueño (L8: `publicar-version.ps1` desde otro equipo o con otro correo).
    """
    cabeza_repo = (propuesta.get("head") or {}).get("repo") or {}
    repo, rama = cabeza_repo.get("full_name"), (propuesta.get("head") or {}).get("ref")
    if not repo or not rama:
        raise SinSaberQuien("no se sabe de qué copia viene la propuesta (¿se ha borrado?).")

    cuentas, sin_cuenta = [], []
    for commit in _commits(api, numero, propuesta):
        sha = str(commit.get("sha") or "")
        for papel in ("author", "committer"):
            usuario = commit.get(papel)
            if isinstance(usuario, dict) and usuario.get("id") == ID_WEB_FLOW:
                continue
            cuenta = _cuenta(usuario)
            if cuenta is None:
                correo = ((commit.get("commit") or {}).get(papel) or {}).get("email") or "sin correo"
                sin_cuenta.append(f"el commit {sha[:7]} lleva como {'autor' if papel == 'author' else 'committer'} un "
                                  f"correo ({correo}) que no es de ninguna cuenta de GitHub")
            else:
                cuentas.append(cuenta)

    # Quien subió cada commit: la cadena de subidas, desde la cabeza (o desde el `before` de esta subida).
    desde = max(str(propuesta.get("created_at") or ""), desde or "")
    if accion == "opened":
        subidores, roto, motivo = list(actores_actuales), None, None
    elif accion == "synchronize":
        if not SHA_COMPLETO.fullmatch(antes or ""):
            raise SinSaberQuien("no se sabe sobre qué commit se ha subido la cabeza (falta `PR_ANTES`): revisa el flujo.")
        subidores, roto, motivo = _cadena_de_subidas(api, antes, numero, repo, desde)
        subidores += list(actores_actuales)
    else:
        subidores, roto, motivo = _cadena_de_subidas(api, cabeza, numero, repo, desde)
    if roto is not None:
        # El relanzamiento del Dueño se mira antes de rechazar, también si el eslabón que falta es un commit con
        # demasiadas ejecuciones ajenas: él responde de lo que hay en la propuesta, sea cual sea el motivo.
        if not _relanzada_por_el_dueno(api, ejecucion_actual, intento, numero, cabeza, repo, es_dueno):
            if motivo:
                raise SinSaberQuien(motivo)
            raise SinSaberQuien(
                f"el robot no ha visto subir el commit {roto[:7]} a esta propuesta (se subió con ella cerrada, se borró "
                "su comprobación o es de antes de que el robot las nombrara), así que no sabe quién lo subió, y subir "
                "otro encima no lo arregla. Cierra esta propuesta y abre una nueva desde una rama con solo tus commits, "
                "o pide al Dueño del programa que relance esta comprobación (relanzarla es responder de lo que hay en "
                "ella).")
        subidores += list(actores_actuales)
    # L8: un correo sin cuenta no dice quién es, pero da igual si todo lo que hay en la propuesta lo ha subido el Dueño
    # (comprobado por las ejecuciones, que no se falsean): él responde de lo que sube.
    if sin_cuenta and not (subidores and all(es_dueno(i) for _, i in subidores)):
        raise SinSaberQuien(sin_cuenta[0] + ". Haz los commits con el correo de tu cuenta (o desde el parcheador).")
    return cuentas + subidores


def unir_cuentas(*listas) -> list:
    """Las cuentas sin repetir (por id), en orden, o SinSaberQuien si son demasiadas."""
    vistas, resultado = set(), []
    for lista in listas:
        for cuenta, cuenta_id in lista:
            if cuenta_id not in vistas:
                vistas.add(cuenta_id)
                resultado.append((cuenta, cuenta_id))
    if len(resultado) > TOPE_CUENTAS:
        raise SinSaberQuien(f"han intervenido {len(resultado)} cuentas en la propuesta y el máximo son {TOPE_CUENTAS}: "
                            "abre una nueva desde una sola cuenta.")
    return resultado


def combinar(todos: list) -> Permisos:
    """El rol más bajo de las cuentas que han intervenido: nadie gana permisos por subir un commit a la propuesta de
    otra persona con más rol, ni por relanzar la ejecución de otra. El Dueño no baja a nadie (puede con todo), así que
    no cuenta salvo que sea el único; así la cuenta de la propuesta sigue siendo una cuando el Dueño la relanza."""
    sin_dueno = [p for p in todos if not p.es_dueno] or todos[:1]
    resultado = sin_dueno[0]
    for otro in sin_dueno[1:]:
        resultado = resultado.el_menor(otro)
    return resultado


def main() -> int:
    fusionar = "--fusionar" in sys.argv[1:]
    repositorio = os.environ["GITHUB_REPOSITORY"]
    numero = int(os.environ["PR_NUMERO"])
    api = crear_api(repositorio, os.environ["GITHUB_TOKEN"])

    if "--fallo-instalacion" in sys.argv[1:]:
        # Lo lanza el flujo de trabajo cuando robot/instalar.sh falla. Sustituye el comentario del robot
        # (si había un rechazo anterior, ya no vale: esta vez no se ha comprobado nada) y termina en error
        # para que la comprobación no quede como aprobada.
        texto = aviso_fallo_instalacion(fusionar)
        comentar(api, numero, texto)
        resumen(texto)
        return 1

    propuesta = api("GET", f"/pulls/{numero}")
    cabeza = cabeza_del_evento(propuesta, os.environ)
    autor, autor_id = propuesta["user"]["login"], propuesta["user"]["id"]
    cuentas = cuentas_de_la_ejecucion(
        os.environ, autor, autor_id,
        lambda nombre: (api("GET", f"https://api.github.com/users/{urllib.parse.quote(nombre)}", tolerar=(404,)) or {}).get("id"))
    base_mal = motivo_de_base(propuesta)

    def rechazar(motivo):
        texto = f"### ❌ El robot de permisos no puede aceptar esta propuesta\n\n- {linea_segura(motivo)}"
        comentar(api, numero, texto)
        resumen(texto)
        return 1
    if base_mal:
        return rechazar(base_mal)
    equipo = leer_equipo(None)

    # Las reglas se leen del mismo commit de `main` con el que se compara la propuesta (recién traído).
    base = traer(numero, cabeza)
    try:
        ids_duenos, propietarios = canales.leer_duenos(
            (archivo_de_git(base, RUTA_PROPIETARIO, 64 * 1024) or b"").decode("utf-8"))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise RuntimeError(f"No se puede leer `{RUTA_PROPIETARIO}` de `main`: {error}")

    # Todos los que han subido algo a la propuesta (ver `cuentas_de_la_propuesta`).
    try:
        cuentas = unir_cuentas(cuentas, cuentas_de_la_propuesta(
            api, numero, propuesta, cabeza, (os.environ.get("PR_ACCION") or "").strip(), os.environ.get("GITHUB_RUN_ID"),
            lambda cuenta_id: cuenta_id in ids_duenos, cuentas, (os.environ.get("PR_ANTES") or "").strip(),
            os.environ.get("GITHUB_RUN_ATTEMPT"), desde_cuando_hay_nombres(base)))
    except SinSaberQuien as e:
        return rechazar(f"No se puede saber quién ha subido los cambios de esta propuesta: {e}")
    # Si los miembros de `main` no se pueden leer, nadie tiene rol salvo el Dueño, que es quien lo arregla (si
    # el robot fallara del todo, ni siquiera él podría publicar el arreglo).
    canales_roto = None
    try:
        canales_main = leer_canales(revision=base)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        canales_main, canales_roto = Canales(), str(error)

    def cuenta_de(cuenta_id):
        """El nombre actual de la cuenta con ese id en GitHub (None si no existe)."""
        return (api("GET", f"https://api.github.com/user/{int(cuenta_id)}", tolerar=(404,)) or {}).get("login")

    def de(usuario, cuenta_id):
        return permisos_de(usuario, api, equipo, propietarios, cuenta_id, canales_main, ids_duenos)
    permisos = combinar([de(cuenta, cuenta_id) for cuenta, cuenta_id in cuentas])
    if canales_roto and not permisos.es_dueno:
        permisos = Permisos(Rol.NINGUNO)
    # Solo se menciona (`@`) a quien abrió la propuesta: el resto pueden ser autores de commits falseados, y una
    # mención avisaría a una cuenta ajena (cuarta revisión, 2.3).
    quien = f"@{autor}" + (" (también: " + ", ".join(_sin_enlaces(c) for c, _ in cuentas[1:]) + ")"
                           if len(cuentas) > 1 else "")

    def rol_externo(canal, cuenta_id):
        """El rol que la cuenta tiene en el canal fuera de su archivo: en la fase A, el equipo de GitHub en el canal
        oficial (lo mismo que `permisos_de`, sin contar el veto: es el rol de a quién se veta o se le quita el veto)."""
        if canal != canales.CANAL_OFICIAL:
            return 0
        nombre = cuenta_de(cuenta_id)
        if not nombre:
            return 0
        respuesta = api("GET", f"/collaborators/{urllib.parse.quote(nombre)}/permission", tolerar=(404,)) or {}
        return int(ROL_DE_GITHUB.get(respuesta.get("role_name") or respuesta.get("permission"), Rol.NINGUNO))

    # La lista de archivos prohibidos se lee de `main` (el mismo commit), nunca de la propuesta.
    try:
        prohibidos = leer_prohibidos((archivo_de_git(base, RUTA_PROHIBIDOS, 1024 * 1024) or b"").decode("utf-8"))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise RuntimeError(f"No se puede leer `{RUTA_PROHIBIDOS}` de `main`: {error}")

    leido = leer_propuesta(base, cabeza)
    if canales_roto and not permisos.es_dueno:
        motivos = [f"Los miembros de los canales que hay en `main` no se pueden leer ({canales_roto}). Hasta que el "
                   "Dueño del programa lo arregle, el robot no acepta propuestas de nadie más."]
    elif leido is None:
        motivos = ["La propuesta choca con cambios que ya están publicados en `main`. Actualízala con lo "
                   "último de `main` y vuelve a subirla."]
    else:
        cambios, antes, despues, leer_archivo = leido
        motivos = comprobar(cambios, antes, despues, permisos, prohibidos=prohibidos, leer_paquete=rutas_del_paquete,
                            leer_archivo=leer_archivo, ids_duenos=frozenset(ids_duenos), cuenta_de=cuenta_de,
                            rol_externo=rol_externo)

    if motivos:
        lista = "\n".join(f"- {linea_segura(m)}" for m in motivos[:TOPE_MOTIVOS])
        if len(motivos) > TOPE_MOTIVOS:
            lista += f"\n- … y {len(motivos) - TOPE_MOTIVOS} motivos más (corrige estos primero)."
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
    # Si `main` se ha movido desde que se trajo, lo comprobado ya no vale: se vuelve a mirar en la siguiente vuelta.
    actual = (api("GET", "/git/ref/heads/main") or {}).get("object", {}).get("sha")
    if actual != base:
        texto = (aprobado + "\n\n⚠️ Pero no se ha publicado: `main` ha cambiado mientras se comprobaba. Actualiza la "
                 "propuesta con lo último de `main` (o vuelve a lanzar la comprobación) y el robot lo intenta otra vez.")
        comentar(api, numero, texto)
        resumen(texto)
        return 1
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
