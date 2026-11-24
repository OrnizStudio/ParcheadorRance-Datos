"""Fase B de los canales: las reglas de los archivos sueltos del catálogo (`docs/canales.md` §1.4, §1.7 y §4.2).

Desde la migración, la fuente del catálogo son `juegos/<j>/juego.json`, `juegos/<j>/ediciones/<e>.json` y
`canales/<c>/parches/<j>.json` (ver `particion.py`), y `catalogo/catalogo.json` lo regenera el robot.

Quién puede cambiar cada campo no se decide aquí: `permisos.py` junta los archivos de `main` y los de la propuesta
en dos catálogos y los pasa por las mismas reglas de siempre (roles por campo, versiones, paquetes, archivos
prohibidos, largos y lo que la app puede leer). Aquí va lo que no existía en el catálogo de una pieza:

- la forma de las rutas y de cada archivo (claves conocidas, `esquema`, JSON estricto, topes de tamaño);
- `alta`: la pone quien propone (su id, el día de hoy y un canal donde es Administrador o más) y no cambia;
- el `estado` central de un juego (`activo`, `retirado`, `bloqueado`) solo lo cambia el Dueño;
- la `huella` de una edición que ya existe no cambia (un juego actualizado es otra edición), salvo el Dueño;
- `versiones` solo crece: nadie quita una versión ni le cambia la versión, la fecha, el autor o el paquete;
- cada edición tiene su archivo y está en su juego, y cada parche apunta a un juego que existe;
- los paquetes nuevos de un canal están en uno de sus repositorios (`canal.json` → `paquetes`);
- ningún paquete nuevo de un canal lleva una huella de su lista negra (`lista-negra.json` → `huellas`).

Desde la fase D publica parches cualquier canal: cada parche se juzga con el rol del autor en su canal.

Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import datetime
import json
import re

import lector_app
import particion

EDITOR, ADMINISTRADOR, DUENO = 2, 3, 5
# Rol mínimo en el canal para registrar una edición nueva de un juego que ya existe.
MINIMO_ALTA_EDICION = EDITOR
QUIEN_ALTA_EDICION = "un Editor, un Administrador o un Propietario"

# Rutas. Los ids, como en `particion.id_valido` (sirven de nombre de carpeta o de archivo).
_ID = r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?"
RUTA_JUEGO = re.compile(rf"juegos/({_ID})/juego\.json")
RUTA_EDICION = re.compile(rf"juegos/({_ID})/ediciones/({_ID})\.json")
RUTA_PARCHE = re.compile(rf"canales/([a-z0-9_]{{3,20}})/parches/({_ID})\.json")
CARPETA_JUEGOS = "juegos/"
OTROS_SUELTOS = (particion.RUTA_ETIQUETAS, particion.RUTA_PARCHEADOR)

TOPES = {"juego": 256 * 1024, "edicion": 4 * 1024 * 1024, "parche": 4 * 1024 * 1024}
TOPE_TOTAL = 64 * 1024 * 1024  # lo que se lee de los archivos sueltos de un lado (main o la propuesta)

CLAVES_JUEGO = ("esquema", *particion.JUEGO_CENTRAL, "estado", "alta", "ediciones")
CLAVES_EDICION = ("esquema", *particion.EDICION_CENTRAL, "alta")
CLAVES_PARCHE = ("esquema", "juego", *particion.JUEGO_CANAL, *particion.JUEGO_CANAL_ENCIMA, "ediciones")
CLAVES_PARCHE_EDICION = ("id", *particion.EDICION_CANAL)
CLAVES_ALTA = ("canal", "cuenta", "fecha")
# Lo que se puede cambiar de una versión ya publicada: retirarla (y por qué) y sus notas.
CAMPOS_VERSION_CAMBIABLES = ("estado", "motivo", "motivoPublico", "fechaRetirada", "notas")


def tipo_de_ruta(ruta: str):
    """("juego", j) · ("edicion", j, e) · ("parche", canal, j) · None si no es un archivo suelto del catálogo."""
    if m := RUTA_JUEGO.fullmatch(ruta):
        return ("juego", m[1]) if particion.id_valido(m[1]) else None
    if m := RUTA_EDICION.fullmatch(ruta):
        return ("edicion", m[1], m[2]) if particion.id_valido(m[1]) and particion.id_valido(m[2]) else None
    if m := RUTA_PARCHE.fullmatch(ruta):
        return ("parche", m[1], m[2]) if particion.id_valido(m[2]) else None
    return None


def es_suelto(ruta: str) -> bool:
    """Lo que cuenta para juntar el catálogo: los tres tipos de arriba y las etiquetas y el bloque del parcheador."""
    return tipo_de_ruta(ruta) is not None or ruta in OTROS_SUELTOS


def de_los_sueltos(ruta: str) -> bool:
    """Todo lo que está en `juegos/` (bien formado o no) o en la carpeta `parches/` de un canal: lo juzga este módulo."""
    partes = ruta.split("/")
    return ruta.startswith(CARPETA_JUEGOS) or (len(partes) >= 3 and partes[0] == "canales" and partes[2] == "parches")


def migrado(archivos_main: dict) -> bool:
    """Si `main` ya tiene el catálogo en archivos sueltos (desde la migración de la fase B). La marca es
    `programa/parcheador.json`, la misma que miran el Modo equipo y `publicar-version.ps1`: la migración lo escribe
    todo a la vez."""
    return particion.RUTA_PARCHEADOR in archivos_main


def _leer(datos, ruta, motivos):
    try:
        return lector_app.leer(datos)
    except lector_app.JsonIlegible as error:
        motivos.append(f"`{ruta}`: {error}.")
        return None


def _hoy_vale(fecha, hoy: datetime.date) -> bool:
    try:
        dia = datetime.date.fromisoformat(fecha) if isinstance(fecha, str) and len(fecha) == 10 else None
    except ValueError:
        dia = None
    return dia is not None and abs((dia - hoy).days) <= 1


def _alta_bien_formada(alta) -> bool:
    if not isinstance(alta, dict) or set(alta) - set(CLAVES_ALTA) or set(alta) != set(CLAVES_ALTA):
        return False
    canal, cuenta, fecha = alta["canal"], alta["cuenta"], alta["fecha"]
    return (isinstance(canal, str) and re.fullmatch(r"[a-z0-9_]{3,20}", canal) is not None
            and (cuenta is None or (isinstance(cuenta, int) and not isinstance(cuenta, bool) and 0 < cuenta < 2 ** 53))
            and (fecha is None or (isinstance(fecha, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha) is not None)))


def _juego_de(tipo) -> str:
    return tipo[2] if tipo[0] == "parche" else tipo[1]


def _estado_central(archivos: dict, jid: str) -> str:
    """El `estado` central del juego en `archivos` («activo» si no se puede leer: lo que no se lee ya lo para otra
    regla)."""
    datos = archivos.get(f"juegos/{jid}/juego.json")
    if datos is None:
        return "activo"
    try:
        objeto = lector_app.leer(datos)
    except lector_app.JsonIlegible:
        return "activo"
    estado = objeto.get("estado", "activo") if isinstance(objeto, dict) else "activo"
    return estado if isinstance(estado, str) else "activo"


def comprobar(cambios, antes: dict, despues: dict, rol_por_canal: dict, autor_id, es_dueno: bool,
              hoy: datetime.date | None = None) -> list:
    """Motivos de rechazo de lo que la propuesta cambia en los archivos sueltos (lista vacía = nada que objetar aquí).

    `cambios` son (ruta, estado) de la propuesta que cumplen `de_los_sueltos`. `antes` y `despues` son {ruta: bytes}
    con los archivos sueltos (y los `canal.json`) de `main` y tras la propuesta. `rol_por_canal` = {canal: rol del
    autor} (1–4, como `permisos.Rol`), leído de `main`.
    """
    hoy = hoy or datetime.datetime.now(datetime.timezone.utc).date()
    motivos = []
    for ruta, estado in cambios:
        tipo = tipo_de_ruta(ruta)
        if tipo is None:
            if not es_dueno:
                motivos.append(f"`{ruta}`: en `juegos/` solo van `juegos/<juego>/juego.json` y "
                               "`juegos/<juego>/ediciones/<edición>.json`, y en la carpeta `parches/` de un canal, "
                               "`<juego>.json` (ids con letras, números, `.`, `_` y `-`). Las imágenes siguen en "
                               "`catalogo/juegos/<juego>/`.")
            continue
        if not es_dueno and (estado_main := _estado_central(antes, _juego_de(tipo))) != "activo":
            motivos.append(f"`{ruta}`: el juego «{_juego_de(tipo)}» está {estado_main} por el Dueño del programa; "
                           "sus archivos solo los cambia él.")
            continue
        if tipo[0] == "parche" and not es_dueno and (estado in ("A", "D") or ruta not in antes or ruta not in despues):
            # Añadir un juego al canal o quitarlo es de Administrador o más del canal (docs/canales.md §4.2).
            if rol_por_canal.get(tipo[1], 0) < ADMINISTRADOR:
                motivos.append(f"`{ruta}`: añadir un juego al canal o quitarlo lo hace un Administrador o un "
                               f"Propietario de @{tipo[1]}.")
                continue
        if estado == "D" and tipo[0] == "juego" and not es_dueno:
            motivos.append(f"`{ruta}`: quitar un juego de `juegos/` es del Dueño del programa (lo central es de todos "
                           "los canales).")
            continue
        if estado == "D":
            # Quitar un juego o una edición lo deciden las reglas del catálogo (y la coherencia de abajo); quitar un
            # parche con versiones publicadas borraría su historial, que solo borra el Dueño.
            if tipo[0] == "parche" and not es_dueno and ruta in antes:
                previo = _leer(antes[ruta], ruta, [])
                if isinstance(previo, dict) and any(
                        isinstance(e, dict) and any(isinstance(v, dict) for v in e.get("versiones") or [])
                        for e in previo.get("ediciones") or []):
                    motivos.append(f"`{ruta}`: este parche tiene versiones publicadas y su historial no se borra; "
                                   "para quitarlo del catálogo, ocúltalo o retira sus versiones (solo el Dueño del "
                                   "programa borra historial).")
            continue
        datos = despues.get(ruta)
        if datos is None:
            continue
        if len(datos) > TOPES[tipo[0]]:
            motivos.append(f"`{ruta}` pesa {len(datos) // 1024} KB y el máximo son {TOPES[tipo[0]] // 1024} KB.")
            continue
        objeto = _leer(datos, ruta, motivos)
        if objeto is None:
            continue
        forma = _forma(ruta, tipo, objeto)
        motivos += forma
        if es_dueno or forma:
            continue  # con la forma mal, las reglas de abajo no se fían de nada
        previo = None
        if ruta in antes:
            previo = _leer(antes[ruta], ruta, [])
        motivos += _reglas(ruta, tipo, previo, objeto, rol_por_canal, autor_id, hoy)
    motivos += _coherencia(cambios, despues, es_dueno)
    return list(dict.fromkeys(motivos))


def _forma(ruta, tipo, objeto) -> list:
    if not isinstance(objeto, dict):
        return [f"`{ruta}` tiene que ser un objeto JSON."]
    claves = {"juego": CLAVES_JUEGO, "edicion": CLAVES_EDICION, "parche": CLAVES_PARCHE}[tipo[0]]
    motivos = []
    sobran = [k for k in objeto if k not in claves]
    if sobran:
        motivos.append(f"`{ruta}`: campos que no van aquí: {', '.join(f'`{k}`' for k in sobran[:10])}.")
    if objeto.get("esquema") != 1:
        motivos.append(f"`{ruta}`: `esquema` tiene que ser 1.")
    if tipo[0] == "juego":
        if objeto.get("id") != tipo[1]:
            motivos.append(f"`{ruta}`: `id` tiene que ser «{tipo[1]}», el nombre de la carpeta.")
        if objeto.get("estado", "activo") not in particion.ESTADOS_JUEGO:
            motivos.append(f"`{ruta}`: `estado` es `activo`, `retirado` o `bloqueado`.")
        ediciones = objeto.get("ediciones")
        if ediciones is not None and not (isinstance(ediciones, list) and all(isinstance(e, str) for e in ediciones)):
            motivos.append(f"`{ruta}`: `ediciones` es la lista de ids de sus ediciones, en orden.")
    elif tipo[0] == "edicion":
        if objeto.get("id") != tipo[2]:
            motivos.append(f"`{ruta}`: `id` tiene que ser «{tipo[2]}», el nombre del archivo.")
    else:
        if objeto.get("juego") != tipo[2]:
            motivos.append(f"`{ruta}`: `juego` tiene que ser «{tipo[2]}», el nombre del archivo.")
        ediciones = objeto.get("ediciones")
        if ediciones is not None and not isinstance(ediciones, list):
            motivos.append(f"`{ruta}`: `ediciones` es una lista.")
        else:
            vistas = set()
            for e in ediciones or []:
                if not isinstance(e, dict) or not isinstance(e.get("id"), str):
                    motivos.append(f"`{ruta}`: cada edición del parche es un objeto con su `id`.")
                    break
                fuera = [k for k in e if k not in CLAVES_PARCHE_EDICION]
                if fuera:
                    motivos.append(f"`{ruta}` › edición `{e['id']}`: campos que no van en el parche: "
                                   f"{', '.join(f'`{k}`' for k in fuera[:10])} (lo central va en "
                                   f"`juegos/{tipo[2]}/ediciones/{e['id']}.json`).")
                if e["id"].lower() in vistas:
                    motivos.append(f"`{ruta}`: la edición `{e['id']}` está repetida.")
                vistas.add(e["id"].lower())
                versiones = e.get("versiones")
                if versiones is not None and not isinstance(versiones, list):
                    motivos.append(f"`{ruta}` › edición `{e['id']}`: `versiones` es una lista.")
                    continue
                nombres = [v.get("version") for v in versiones or [] if isinstance(v, dict)]
                if len(nombres) != len(versiones or []) or not all(isinstance(n, str) for n in nombres):
                    motivos.append(f"`{ruta}` › edición `{e['id']}`: cada versión es un objeto con su `version`.")
                elif len({n.casefold() for n in nombres}) != len(nombres):
                    motivos.append(f"`{ruta}` › edición `{e['id']}`: hay versiones repetidas en `versiones`; cada "
                                   "versión del parche sale una sola vez.")
    if tipo[0] in ("juego", "edicion") and "alta" in objeto and not _alta_bien_formada(objeto["alta"]):
        motivos.append(f"`{ruta}`: `alta` es `{{\"canal\", \"cuenta\", \"fecha\"}}` (canal, id numérico de la cuenta "
                       "y AAAA-MM-DD).")
    return motivos


def _reglas(ruta, tipo, previo, objeto, rol_por_canal, autor_id, hoy) -> list:
    if not isinstance(objeto, dict):
        return []
    motivos = []
    if tipo[0] in ("juego", "edicion"):
        que = "el juego" if tipo[0] == "juego" else "la edición"
        if previo is None and tipo[0] == "juego":
            # Decisión del usuario (docs/vocabulario.md, «Quién da de alta un juego»): en la fase B solo el Dueño, en
            # PROGRAMA › Juegos. Con la fase D se sumarán los canales verificados (docs/canales.md §4.2).
            return [f"`{ruta}`: dar de alta un juego nuevo es del Dueño del programa (PROGRAMA › Juegos). Pídeselo y, "
                    "cuando esté, añade su parche al canal."]
        if previo is None:
            alta = objeto.get("alta")
            if not _alta_bien_formada(alta):
                motivos.append(f"`{ruta}`: {que} es nuevo y le falta `alta` (quién lo da de alta). Hazlo desde el "
                               "parcheador.")
            else:
                if alta["cuenta"] != autor_id:
                    motivos.append(f"`{ruta}` › `alta.cuenta`: tiene que ser el id de tu cuenta ({autor_id}).")
                if not _hoy_vale(alta["fecha"], hoy):
                    motivos.append(f"`{ruta}` › `alta.fecha`: tiene que ser la fecha de hoy ({hoy.isoformat()}, UTC).")
                if alta["canal"] != particion.CANAL_OFICIAL:
                    motivos.append(f"`{ruta}` › `alta.canal`: por ahora solo da de alta el canal oficial "
                                   f"(@{particion.CANAL_OFICIAL}).")
                elif rol_por_canal.get(alta["canal"], 0) < MINIMO_ALTA_EDICION:
                    motivos.append(f"`{ruta}` › `alta.canal`: dar de alta una edición lo hace {QUIEN_ALTA_EDICION} "
                                   f"del canal, y en @{alta['canal']} no lo eres.")
            if tipo[0] == "juego" and objeto.get("estado", "activo") != "activo":
                motivos.append(f"`{ruta}`: un juego nuevo empieza `activo`; retirarlo o bloquearlo es del Dueño del "
                               "programa.")
        elif isinstance(previo, dict):
            if previo.get("alta") != objeto.get("alta"):
                motivos.append(f"`{ruta}` › `alta`: quién dio de alta {que} no se cambia (solo el Dueño del programa).")
            if tipo[0] == "juego" and previo.get("estado", "activo") != objeto.get("estado", "activo"):
                motivos.append(f"`{ruta}` › `estado`: retirar, bloquear o reactivar un juego es del Dueño del programa.")
            if tipo[0] == "edicion" and previo.get("huella") != objeto.get("huella"):
                motivos.append(f"`{ruta}` › `huella`: la huella de una edición publicada no se cambia: si el juego se "
                               "ha actualizado, es otra edición (regístrala como nueva).")
    else:
        motivos += _versiones_solo_crecen(ruta, previo, objeto)
    return motivos


def _versiones_solo_crecen(ruta, previo, objeto) -> list:
    if not isinstance(previo, dict):
        return []
    motivos = []
    nuevas = {e.get("id"): e for e in objeto.get("ediciones") or [] if isinstance(e, dict) and isinstance(e.get("id"), str)}
    viejas = previo.get("ediciones")
    for viejo in viejas if isinstance(viejas, list) else []:
        if not isinstance(viejo, dict) or not isinstance(viejo.get("id"), str):
            continue
        eid = viejo.get("id")
        antes_v = [v for v in viejo.get("versiones") or [] if isinstance(v, dict)]
        if not antes_v:
            continue
        despues_v = {}
        for v in (nuevas.get(eid) or {}).get("versiones") or []:
            if isinstance(v, dict):
                despues_v.setdefault(v.get("version"), v)
        for v in antes_v:
            nombre = v.get("version")
            ahora = despues_v.get(nombre)
            donde = f"`{ruta}` › edición `{eid}` › versión `{nombre}`"
            if ahora is None:
                motivos.append(f"{donde}: las versiones no se borran del historial; para quitarla, retírala "
                               "(solo el Dueño del programa borra historial).")
                continue
            fijas = sorted(k for k in set(v) | set(ahora)
                           if k not in CAMPOS_VERSION_CAMBIABLES and v.get(k) != ahora.get(k))
            if fijas:
                motivos.append(f"{donde}: de una versión ya publicada solo se cambia si está retirada (y por qué) y "
                               f"sus notas; no {', '.join(f'`{k}`' for k in fijas)}.")
    return motivos


def _coherencia(cambios, despues, es_dueno) -> list:
    """Lo que tiene que cuadrar entre archivos tras la propuesta, mirado solo donde la propuesta toca."""
    if es_dueno:
        return []
    juegos_tocados = {t[1] if t[0] != "parche" else t[2] for r, _ in cambios if (t := tipo_de_ruta(r))}
    motivos = []
    for jid in sorted(juegos_tocados):
        ruta_juego = f"juegos/{jid}/juego.json"
        archivos_ed = {t[2] for r in despues if (t := tipo_de_ruta(r)) and t[0] == "edicion" and t[1] == jid}
        if ruta_juego not in despues:
            if archivos_ed:
                motivos.append(f"`juegos/{jid}/`: hay ediciones pero no `juego.json`.")
            parches = [r for r in despues if (t := tipo_de_ruta(r)) and t[0] == "parche" and t[2] == jid]
            if parches:
                motivos.append(f"`{parches[0]}`: el juego «{jid}» no existe en `juegos/`.")
            continue
        try:
            central = lector_app.leer(despues[ruta_juego])
        except lector_app.JsonIlegible:
            continue  # ya sale el error del archivo
        lista = central.get("ediciones") if isinstance(central, dict) else None
        lista = [e for e in lista if isinstance(e, str)] if isinstance(lista, list) else []
        sin_archivo = [e for e in lista if e not in archivos_ed]
        sin_lista = sorted(archivos_ed - set(lista))
        if sin_archivo:
            motivos.append(f"`{ruta_juego}`: las ediciones {', '.join(f'`{e}`' for e in sin_archivo[:10])} no tienen "
                           f"su archivo en `juegos/{jid}/ediciones/`.")
        if sin_lista:
            motivos.append(f"`juegos/{jid}/ediciones/`: {', '.join(f'`{e}`' for e in sin_lista[:10])} no están en la "
                           f"lista `ediciones` de `{ruta_juego}`.")
        if len({e.lower() for e in lista}) != len(lista):
            motivos.append(f"`{ruta_juego}`: hay ediciones repetidas en `ediciones`.")
    return motivos


# ─────────────────────────────────── Paquetes del canal ───────────────────────────────────

def _paquetes(parche) -> list:
    """Todos los paquetes (objetos con `url` y `hash`) de un archivo de parche: el del juego, los de cada edición y
    los de cada versión."""
    paquetes = []
    if not isinstance(parche, dict):
        return paquetes

    def del_parche(p):
        if isinstance(p, dict):
            paquetes.extend(q for q in p.get("paquetes") or [] if isinstance(q, dict))
    del_parche(parche.get("parche"))
    for e in parche.get("ediciones") or []:
        if not isinstance(e, dict):
            continue
        del_parche(e.get("parche"))
        for v in e.get("versiones") or []:
            if isinstance(v, dict) and isinstance(v.get("paquete"), dict):
                paquetes.append(v["paquete"])
    return paquetes


def _urls(parche) -> set:
    return {p["url"] for p in _paquetes(parche) if isinstance(p.get("url"), str)}


def _hashes(parche) -> set:
    return {p["hash"].strip().lower() for p in _paquetes(parche) if isinstance(p.get("hash"), str)}


def _hashes_de_huella(edicion) -> set:
    """Los hashes de la huella de una edición (`hash` y `hashParcial` de cada archivo)."""
    if not isinstance(edicion, dict):
        return set()
    return {f[k].strip().lower() for f in edicion.get("huella") or [] if isinstance(f, dict)
            for k in ("hash", "hashParcial") if isinstance(f.get(k), str)}


TOPE_HUELLAS_CONSULTADAS = 2000


def comprobar_huellas(cambios, antes: dict, despues: dict, vetada, es_dueno: bool) -> list:
    """Ningún paquete nuevo de un parche lleva una huella vetada y ninguna edición nueva o cambiada tiene en su
    huella un hash vetado. `vetada(canal, hash)` da el motivo (lista negra del canal, con `canal`, o la general) o None.
    Solo se miran los hashes que la propuesta añade."""
    if es_dueno:
        return []
    motivos, consultas = [], 0
    for ruta, estado in cambios:
        tipo = tipo_de_ruta(ruta)
        if estado == "D" or tipo is None or tipo[0] == "juego" or ruta not in despues:
            continue
        try:
            nuevo = lector_app.leer(despues[ruta])
            viejo = lector_app.leer(antes[ruta]) if ruta in antes else None
        except lector_app.JsonIlegible:
            continue
        if tipo[0] == "parche":
            canal, nuevos, que = tipo[1], _hashes(nuevo) - _hashes(viejo), "un paquete lleva"
        else:
            canal, nuevos, que = None, _hashes_de_huella(nuevo) - _hashes_de_huella(viejo), "la huella de la edición lleva"
        for huella in sorted(nuevos):
            consultas += 1
            if consultas > TOPE_HUELLAS_CONSULTADAS:
                return motivos + [f"La propuesta añade más de {TOPE_HUELLAS_CONSULTADAS} hashes: divídela en varias."]
            if motivo := vetada(canal, huella):
                motivos.append(f"`{ruta}`: {que} `{huella[:20]}…`, que está en la lista negra ({motivo}).")
    return motivos


def _cola_de_release(url: str, prefijos: tuple) -> bool:
    """Lo que va tras `.../releases/download/` es `<etiqueta>/<archivo>`, sin `..` ni `.`, sin `?` ni `#` y sin
    nada codificado con `%` (`%2e%2e`, `%2f`): así no hay forma de salir de las Releases del repositorio."""
    prefijo = next(p for p in prefijos if url.startswith(p))
    partes = url[len(prefijo):].split("/")
    return (len(partes) == 2 and all(partes) and all(p not in (".", "..") for p in partes)
            and not any(c in url[len(prefijo):] for c in "%?#\\ \t\r\n"))


def comprobar_paquetes(cambios, antes: dict, despues: dict, paquetes_por_canal: dict, es_dueno: bool) -> list:
    """Cada paquete nuevo de un parche tiene que estar en las Releases de uno de los repositorios del canal
    (`canal.json` → `paquetes`, leído de `main`). Los que ya estaban no se miran (los de antes de los canales)."""
    if es_dueno:
        return []
    motivos = []
    for ruta, estado in cambios:
        tipo = tipo_de_ruta(ruta)
        if estado == "D" or tipo is None or tipo[0] != "parche" or ruta not in despues:
            continue
        try:
            nuevo = lector_app.leer(despues[ruta])
            viejo = lector_app.leer(antes[ruta]) if ruta in antes else None
        except lector_app.JsonIlegible:
            continue
        repos = paquetes_por_canal.get(tipo[1]) or []
        prefijos = tuple(f"https://github.com/{r}/releases/download/" for r in repos)
        for url in sorted(_urls(nuevo) - _urls(viejo)):
            if not prefijos or not url.startswith(prefijos) or not _cola_de_release(url, prefijos):
                motivos.append(f"`{ruta}`: el paquete `{url}` no está en las Releases de los repositorios de "
                               f"@{tipo[1]} ({', '.join(f'`{r}`' for r in repos) or 'ninguno'}; se cambian en "
                               "`canal.json` → `paquetes`).")
    return motivos


def paquetes_de_los_canales(archivos_main: dict) -> dict:
    """{canal: [repositorios]} de los `canal.json` de `main` (los ilegibles, sin repositorios)."""
    resultado = {}
    for ruta, datos in archivos_main.items():
        m = re.fullmatch(r"canales/([a-z0-9_]{3,20})/canal\.json", ruta)
        if not m:
            continue
        try:
            canal = json.loads(datos)
        except (ValueError, RecursionError):
            continue
        paquetes = canal.get("paquetes") if isinstance(canal, dict) else None
        resultado[m[1]] = [p for p in paquetes if isinstance(p, str)] if isinstance(paquetes, list) else []
    return resultado


# ─────────────────────────────────── Catálogos para comparar ───────────────────────────────────

def catalogos_para_reglas(antes: dict, despues: dict, canal: str = particion.CANAL_OFICIAL) -> tuple:
    """(catálogo de `main`, catálogo tras la propuesta) del canal `canal`, con todos los juegos, también los que no
    tienen parche del canal y los retirados o bloqueados: con ellos se juzgan los roles, campo a campo. ErrorParticion
    si los de la propuesta no se pueden juntar."""
    try:
        cat_antes = particion.juntar(antes, 1, canal=canal, todos=True)
    except particion.ErrorParticion:
        cat_antes = {"esquema": 1, "versionCatalogo": 1, "juegos": []}
    return cat_antes, particion.juntar(despues, 2, canal=canal, todos=True)


def catalogos_para_comparar(antes: dict, despues: dict, version_main, canal: str = particion.CANAL_OFICIAL):
    """(texto del catálogo de `main`, bytes del catálogo tras la propuesta) juntando los archivos sueltos, con la
    versión de `main` y la siguiente: así las reglas de siempre ven lo que cambia como si fuera `catalogo.json`.
    ErrorParticion si los de la propuesta no se pueden juntar (los de `main`, si no se pueden, cuentan como vacíos)."""
    version = version_main if isinstance(version_main, int) and not isinstance(version_main, bool) \
        and 0 < version_main < lector_app.VERSION_MAXIMA else 1
    try:
        cat_antes = particion.juntar(antes, version, canal=canal)
    except particion.ErrorParticion:
        cat_antes = {"esquema": 1, "versionCatalogo": version, "juegos": []}
    cat_despues = particion.juntar(despues, version + 1, canal=canal)
    return (particion.texto_json(cat_antes).decode("utf-8"), particion.texto_json(cat_despues))
