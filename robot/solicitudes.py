"""Fase D de los canales: las solicitudes (`docs/canales.md` §2).

Una solicitud es una propuesta normal con el cambio que se pide. El robot la comprueba como cualquier otra; si quien
la envía no puede hacer ese cambio directamente, no la fusiona: le pone la etiqueta `solicitud:<tipo>` y espera.

- **Canal nuevo** (`solicitud:canal`): `canales/<c>/canal.json` y `miembros.json` de un canal que no existe, con
  quien propone como único Propietario. La aprueba el Dueño poniendo la etiqueta `aprobada`: el robot mira quién la
  puso (el `sender` del evento `labeled`), y solo en esa ejecución, con el commit de ese momento, la fusiona. Si
  `aprobada` la pone otra cuenta, el robot la quita. Una subida posterior no queda aprobada: hace falta volver a
  ponerla.
- **Verificación** (archivo de solicitud): `solicitudes/verificacion/<c>.json`, que pone el Propietario del canal y
  se fusiona directamente si cumple los requisitos. El Dueño la resuelve después con su propia propuesta (pone
  `verificacion` en `canal.json` y `estado`, `respuesta` y `resuelta` en la solicitud).
- **Juego nuevo, edición nueva y cambio en la ficha central** (`solicitud:juego`, `solicitud:edicion`,
  `solicitud:central`; fase D3b): una propuesta que solo toca `juegos/<j>/` (y sus imágenes, en
  `catalogo/juegos/<j>/`). La envía un Administrador o un Propietario del canal; el canal es el `alta.canal` de los
  archivos nuevos o, en un cambio de la ficha central, la marca `<!-- canal: <c> -->` del cuerpo de la propuesta (si
  vienen las dos, tienen que coincidir). En la ficha central, el canal tiene que tener parche de ese juego en `main`.
  Si el canal está verificado en `main`, se fusiona directamente; si no, espera `aprobada` como el canal nuevo. Lo del
  canal oficial que no es un juego nuevo (ediciones y ficha central) sigue con las reglas por campo de siempre.
- **Etiqueta global** (archivo de solicitud): `solicitudes/etiquetas/<n>.json`, con `<n>` = `nombre_de_archivo(nombre)`.
  La pone un Administrador o un Propietario del canal y se fusiona directamente; el Dueño la resuelve después con su
  propia propuesta (crea la etiqueta en `normas/etiquetas.json` y pone `estado`, `respuesta` y `resuelta`).

Una solicitud va sola: si la propuesta toca algo más, se rechaza («Una solicitud va sola»). El rechazo de una
solicitud que espera lo hace la app (comentario con `<!-- rechazo -->` y cerrar): el robot no lo lee.

Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import datetime
import json
import re
import unicodedata
from dataclasses import dataclass

import canales

APROBADA = "aprobada"
PREFIJO_ETIQUETA = "solicitud:"
CARPETA = "solicitudes/"
RUTA_VERIFICACION = re.compile(r"solicitudes/verificacion/([a-z0-9_]{3,20})\.json")
CARPETA_ETIQUETAS = "solicitudes/etiquetas/"
RUTA_ETIQUETA = re.compile(r"solicitudes/etiquetas/([a-z0-9](?:[a-z0-9-]{0,22}[a-z0-9])?)\.json")
RUTA_NORMAS = "normas/normas.json"
CARPETA_IMAGENES = "catalogo/juegos/"
# Las únicas rutas de imagen de un juego (como las escribe el parcheador): `catalogo/juegos/<j>/<tipo>[-<fecha>].<ext>`,
# en minúsculas y sin subcarpetas.
TIPOS_IMAGEN = ("icono", "banner", "fondo", "logo", "portada")
RUTA_IMAGEN = re.compile(r"catalogo/juegos/([A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?)/"
                         r"(?:" + "|".join(TIPOS_IMAGEN) + r")(?:-\d{8}-\d{6})?\.(?:png|jpg|jpeg|webp)")


def error_de_ruta_de_imagen(ruta: str):
    """Por qué `ruta` no es la de una imagen de juego, o None."""
    if RUTA_IMAGEN.fullmatch(ruta):
        return None
    return (f"`{ruta}`: las imágenes de un juego van en `{CARPETA_IMAGENES}<juego>/<tipo>.<ext>` (o "
            f"`<tipo>-<aaaammdd>-<hhmmss>.<ext>`), con `<tipo>` uno de {', '.join(TIPOS_IMAGEN)} y `.png`, `.jpg`, "
            "`.jpeg` o `.webp`, en minúsculas y sin subcarpetas.")
# La marca con la que la app dice de qué canal es un cambio en la ficha central (en el cuerpo de la propuesta).
MARCA_CANAL = re.compile(r"<!--[ \t]*canal:[ \t]*([^\s>]*)[ \t]*-->")
DE_PROGRAMA = ("juego", "edicion", "central")

DIAS_CUENTA = 30
TOPE_CANALES_POR_CUENTA = 3
TOPE_ABIERTAS = 10  # solicitudes de juego, edición o ficha central abiertas por cuenta; de etiqueta, por canal
TOPE_ARCHIVOS_ETIQUETA = 2000  # archivos de `solicitudes/etiquetas/` en `main` (pendientes y resueltos)
LARGO_MOTIVO = 300
LARGO_NOMBRE_ETIQUETA = 24
DIAS_SIN_MALWARE = 90
CAMPOS_VERIFICACION = ("esquema", "canal", "motivo", "pedidaPor", "fecha", "estado", "respuesta", "resuelta")
CAMPOS_ETIQUETA = ("esquema", "canal", "nombre", "paraQue", "pedidaPor", "fecha", "estado", "respuesta", "resuelta")
TOPE_ARCHIVO = 16 * 1024


@dataclass(frozen=True)
class Solicitud:
    tipo: str      # «canal», «verificacion», «etiqueta», «juego», «edicion» o «central»
    canal: str
    clave: str = ""        # el juego (juego, edición, ficha central) o el nombre del archivo (etiqueta)
    directa: bool = False  # de juego, edición o ficha central de un canal verificado: se fusiona sin aprobación

    @property
    def etiqueta(self) -> str:
        return PREFIJO_ETIQUETA + self.tipo

    @property
    def necesita_aprobacion(self) -> bool:
        """Las de propuesta esperan la etiqueta `aprobada` (salvo las de un canal verificado); las de archivo se
        fusionan y las resuelve el Dueño luego."""
        return self.tipo == "canal" or (self.tipo in DE_PROGRAMA and not self.directa)


def nombre_de_archivo(nombre) -> str:
    """El `<n>` de `solicitudes/etiquetas/<n>.json`: el nombre en minúsculas, sin acentos, con lo que no es una letra
    a-z o un número cambiado por `-` (sin repetir ni en los extremos), como mucho 24. Vacío si no queda nada."""
    if not isinstance(nombre, str):
        return ""
    texto = "".join(c for c in unicodedata.normalize("NFKD", nombre.casefold()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")[:LARGO_NOMBRE_ETIQUETA].strip("-")


def _leer_suelto(leer_despues, ruta):
    try:
        datos = leer_despues(ruta) if leer_despues is not None else None
        return json.loads(datos) if datos is not None and len(datos) <= 4 * 1024 * 1024 else None
    except (ValueError, RecursionError, TypeError):
        return None


def _canal_de_alta(leer_despues, ruta):
    objeto = _leer_suelto(leer_despues, ruta)
    alta = objeto.get("alta") if isinstance(objeto, dict) else None
    canal = alta.get("canal") if isinstance(alta, dict) else None
    return canal if isinstance(canal, str) else None


def _juego_central(ruta: str):
    """El juego de una ruta de `juegos/<j>/…` o `catalogo/juegos/<j>/…`, o None."""
    partes = ruta.split("/")
    if partes[0] == "juegos" and len(partes) >= 3:
        return partes[1]
    if ruta.startswith(CARPETA_IMAGENES) and len(partes) >= 4:
        return partes[2]
    return None


def marca_de_canal(cuerpo):
    """El @ de la marca `<!-- canal: <c> -->` del cuerpo de la propuesta, o None. ValueError si hay varias distintas
    o el @ no vale."""
    marcas = set(MARCA_CANAL.findall(cuerpo[:65536] if isinstance(cuerpo, str) else ""))
    if len(marcas) > 1:
        raise ValueError("El cuerpo de la propuesta lleva varias marcas `<!-- canal: … -->` distintas: tiene que "
                         "llevar una sola, la del canal que pide el cambio.")
    marca = next(iter(marcas), None)
    if marca is not None and not canales.ID_CANAL.match(marca):
        raise ValueError("La marca `<!-- canal: … -->` del cuerpo de la propuesta no lleva un @ de canal válido.")
    return marca


def clasificar(cambios, existe_en_main, leer_despues=None, cuerpo=None, migrado=True, leer_antes=None):
    """La solicitud que es la propuesta, o None si no es una. `cambios` son (ruta, estado), `existe_en_main(ruta)`
    dice si ese archivo está en `main`, `leer_despues(ruta)` da sus bytes tras la propuesta (o None) y `cuerpo` es el
    texto de la propuesta (por la marca del canal). Sin `migrado` (`main` aún sin archivos sueltos) no hay solicitudes
    de juegos. `leer_antes(ruta)` da los bytes de `main` (sin él, una edición nueva que cambie `juego.json` se juzga
    como ficha central). ValueError con el motivo si mezcla una solicitud con otros cambios."""
    rutas = [r for r, _ in cambios]
    if any(r.startswith(CARPETA) for r in rutas):
        if len(rutas) == 1 and cambios[0][1] != "D":
            if m := RUTA_VERIFICACION.fullmatch(rutas[0]):
                return Solicitud("verificacion", m[1])
            if m := RUTA_ETIQUETA.fullmatch(rutas[0]):
                objeto = _leer_suelto(leer_despues, rutas[0])
                canal = objeto.get("canal") if isinstance(objeto, dict) else None
                return Solicitud("etiqueta", canal if isinstance(canal, str) else "", m[1])
            if rutas[0].startswith(CARPETA_ETIQUETAS):
                raise ValueError(f"`{rutas[0]}`: el archivo se llama como la etiqueta, en minúsculas, sin acentos y "
                                 "con `-` en lugar de espacios (como mucho 24), y termina en `.json`. Hazlo desde el "
                                 "parcheador.")
        raise ValueError("Una solicitud va sola: la propuesta solo puede añadir o cambiar "
                         "`solicitudes/verificacion/<canal>.json` o añadir `solicitudes/etiquetas/<nombre>.json` (lo "
                         "demás, en propuestas aparte).")
    if migrado and (programa := _de_programa(cambios, existe_en_main, leer_despues, cuerpo, leer_antes)) is not None:
        return programa
    nuevos ={canales.canal_de_la_ruta(r)[0] for r, e in cambios
              if r.startswith(canales.CARPETA_CANALES) and r.endswith("/canal.json") and e == "A"
              and r.count("/") == 2}
    nuevos = {c for c in nuevos if not existe_en_main(f"{canales.CARPETA_CANALES}{c}/canal.json")
              and not existe_en_main(f"{canales.CARPETA_CANALES}{c}/miembros.json")}
    # Solo es una solicitud si es exactamente eso: un @ válido con sus dos archivos y nada más. Lo que no lo sea se
    # juzga con las reglas de siempre, que ya rechazan crear un canal (y dicen por qué: @ raro, varios canales…).
    if len(nuevos) != 1:
        return None
    canal = next(iter(nuevos))
    esperadas = {f"{canales.CARPETA_CANALES}{canal}/canal.json", f"{canales.CARPETA_CANALES}{canal}/miembros.json"}
    if set(rutas) != esperadas or any(e != "A" for _, e in cambios) or not canales.ID_CANAL.match(canal):
        return None
    return Solicitud("canal", canal)


def _solo_anade_ediciones(cambios, nuevos, leer_antes, leer_despues) -> bool:
    """¿La propuesta solo añade ediciones? Sus archivos nuevos y, en `juego.json`, solo los ids de esas ediciones
    añadidos al final de `ediciones` (nada más cambia). Una edición que ya existe, una imagen o cualquier otro cambio de
    la ficha: no (se juzga como ficha central, que pide tener parche del juego)."""
    ids_nuevos = [r.rsplit("/", 1)[1][:-len(".json")] for r in nuevos if "/ediciones/" in r and r.endswith(".json")]
    for ruta, estado in cambios:
        if ruta in nuevos:
            continue
        if estado != "M" or not (ruta.endswith("/juego.json") and ruta.count("/") == 2) or leer_antes is None:
            return False
        antes, despues = _leer_suelto(leer_antes, ruta), _leer_suelto(leer_despues, ruta)
        if not isinstance(antes, dict) or not isinstance(despues, dict):
            return False
        if {k: v for k, v in antes.items() if k != "ediciones"} != {k: v for k, v in despues.items() if k != "ediciones"}:
            return False
        lista_antes, lista_despues = antes.get("ediciones"), despues.get("ediciones")
        if not isinstance(lista_antes, list) or not isinstance(lista_despues, list):
            return False
        anadidas = lista_despues[len(lista_antes):]
        if lista_despues[:len(lista_antes)] != lista_antes or not all(isinstance(e, str) for e in anadidas) \
                or sorted(anadidas) != sorted(ids_nuevos):
            return False
    return True


def _de_programa(cambios, existe_en_main, leer_despues, cuerpo, leer_antes=None):
    """Juego nuevo, edición nueva o cambio en la ficha central de un canal (ver arriba), o None."""
    por_juego = {}
    for ruta, estado in cambios:
        if (j := _juego_central(ruta)) is not None:
            por_juego.setdefault(j, []).append((ruta, estado))
    if not por_juego:
        return None
    marca = marca_de_canal(cuerpo)
    nuevos = [r for r, e in cambios if e != "D" and r.startswith("juegos/") and not existe_en_main(r)
              and (r.endswith("/juego.json") and r.count("/") == 2
                   or "/ediciones/" in r and r.count("/") == 3)]
    tipo = "juego" if any(r.endswith("/juego.json") for r in nuevos) else "edicion" if nuevos else "central"
    altas = {c for r in nuevos if (c := _canal_de_alta(leer_despues, r)) is not None}
    if len(altas) > 1:
        raise ValueError("Los archivos nuevos de `juegos/` tienen `alta.canal` distintos: un juego o una edición se da "
                         "de alta desde un solo canal.")
    alta = next(iter(altas), None)
    if alta is not None and marca is not None and alta != marca:
        raise ValueError(f"La marca `<!-- canal: {marca} -->` del cuerpo no coincide con `alta.canal` (@{alta}).")
    canal = alta or marca
    # Lo del canal oficial (y lo que no dice de qué canal es) sigue con las reglas de siempre, salvo un juego nuevo.
    if tipo != "juego" and (canal is None or canal == canales.CANAL_OFICIAL):
        return None
    juego = next(iter(por_juego))
    if len(por_juego) != 1 or len(por_juego[juego]) != len(cambios) or any(e == "D" for _, e in cambios):
        raise ValueError(f"Una solicitud va sola: un juego nuevo, una edición nueva o un cambio en la ficha central "
                         f"solo toca `juegos/{juego}/` (y sus imágenes en `{CARPETA_IMAGENES}{juego}/`), sin borrar "
                         "nada. El parche del canal va en una propuesta aparte, cuando el juego esté publicado.")
    # Una «edición nueva» solo añade la edición: si de paso cambia la ficha (o una edición que ya está), es un cambio en
    # la ficha central y se juzga como tal (hace falta tener parche del juego).
    if tipo == "edicion" and not _solo_anade_ediciones(cambios, nuevos, leer_antes, leer_despues):
        tipo = "central"
    return Solicitud(tipo, canal or "", juego)


def _hoy_vale(fecha, hoy: datetime.date) -> bool:
    try:
        dia = datetime.date.fromisoformat(fecha) if isinstance(fecha, str) and len(fecha) == 10 else None
    except ValueError:
        dia = None
    return dia is not None and abs((dia - hoy).days) <= 1


def version_de_normas(datos) -> int:
    """La `version` de `normas/normas.json` de `main` (0 si aún no hay normas)."""
    if datos is None:
        return 0
    try:
        objeto = canales.leer_json_estricto(datos, RUTA_NORMAS, 1024 * 1024)
    except canales.JsonMalo:
        return -1  # ilegible: ningún canal nuevo puede decir que las ha aceptado
    version = objeto.get("version") if isinstance(objeto, dict) else None
    return version if isinstance(version, int) and not isinstance(version, bool) and version >= 0 else -1


def comprobar_canal_nuevo(sol: Solicitud, leer, autor_id, cuenta_de, creada_el, hoy: datetime.date,
                          version_normas: int, parecido, abiertas, paquetes_de_otros=None) -> list:
    """Motivos de rechazo de una solicitud de canal nuevo.

    `leer(ruta, lado)` da los bytes; `cuenta_de(id)` el nombre actual de la cuenta; `creada_el(id)` la fecha en que se
    creó (None si no se sabe); `parecido(texto)` por qué un @ o un nombre se confunde con otro canal o uno reservado;
    `abiertas()` cuántas solicitudes de canal nuevo tiene abiertas esta cuenta (sin contar esta);
    `paquetes_de_otros` = {repositorio en minúsculas: @} de los canales de `main`.
    """
    c = sol.canal
    ruta_canal, ruta_miembros = f"canales/{c}/canal.json", f"canales/{c}/miembros.json"
    if autor_id is None:
        return ["Una solicitud de canal nuevo la abre y la sube una sola cuenta: abre una propuesta nueva desde la "
                "tuya."]
    motivos = []
    if not canales.ID_CANAL.match(c):
        return [f"`{c}` no puede ser el @ de un canal (de 3 a 20 minúsculas, números y `_`)."]
    if c in canales.ARROBAS_DEL_PROGRAMA:
        return [f"@{c} está reservado por el programa y no puede ser el @ de un canal."]
    creada = creada_el(autor_id)
    if creada is None or (hoy - creada).days < DIAS_CUENTA:
        motivos.append(f"Para pedir un canal la cuenta tiene que tener al menos {DIAS_CUENTA} días.")
    if abiertas() >= TOPE_CANALES_POR_CUENTA:
        motivos.append(f"Ya tienes {TOPE_CANALES_POR_CUENTA} solicitudes de canal nuevo abiertas: espera a que se "
                       "resuelvan o retira alguna.")
    if (problema := parecido(c)):
        motivos.append(f"El @{c} {problema}.")
    try:
        canal = canales.leer_json_estricto(leer(ruta_canal, "despues"), ruta_canal, canales.TOPES["canal.json"])
        miembros = canales.leer_json_estricto(leer(ruta_miembros, "despues"), ruta_miembros,
                                              canales.TOPES["miembros.json"])
    except canales.JsonMalo as error:
        return motivos + [str(error)]
    errores = canales.validar_canal(canal, c, ruta_canal)
    if not errores:
        errores = [f"`{ruta_canal}` › {m}" for m in canales.repositorios_ajenos(
            canal.get("paquetes", []), c, paquetes_de_otros or {})]
    motivos += errores
    if not errores:
        if (problema := parecido(canal["nombre"])):
            motivos.append(f"`{ruta_canal}` › `nombre`: «{canal['nombre']}» {problema}.")
        if canal.get("estado") != "activo" or canal.get("oculto", False):
            motivos.append(f"`{ruta_canal}`: un canal nuevo empieza `activo` y sin ocultar.")
        if canal.get("verificacion") is not None:
            motivos.append(f"`{ruta_canal}`: la verificación la pone el Dueño del programa; un canal nuevo no la lleva.")
        if canal.get("idAnteriores"):
            motivos.append(f"`{ruta_canal}`: un canal nuevo no tiene @ anteriores.")
        if not _hoy_vale(canal.get("creado"), hoy):
            motivos.append(f"`{ruta_canal}` › `creado`: tiene que ser la fecha de hoy ({hoy.isoformat()}, UTC).")
        if canal.get("normasAceptadas") != version_normas or version_normas < 0:
            motivos.append(f"`{ruta_canal}` › `normasAceptadas`: tienes que aceptar las normas vigentes "
                           f"(versión {max(version_normas, 0)}).")
    filas, errores = canales.leer_miembros(miembros, ruta_miembros)
    motivos += errores
    if not errores:
        fila = filas.get(autor_id)
        if len(filas) != 1 or fila is None or fila.rol != 4 or not fila.activo:
            motivos.append(f"`{ruta_miembros}`: un canal nuevo empieza con un solo miembro, tú, como Propietario "
                           "activo (los demás se invitan cuando exista).")
        elif cuenta_de(autor_id) != fila.cuenta:
            motivos.append(f"`{ruta_miembros}`: `cuenta` tiene que ser el nombre actual de tu cuenta.")
    return motivos


def comprobar_verificacion(sol: Solicitud, leer, autor_id, rol_en_canal: int, hoy: datetime.date,
                           archivos_main: dict, huella_vetada=lambda huella: False) -> list:
    """Motivos de rechazo de una solicitud de verificación (`solicitudes/verificacion/<c>.json`) que envía el
    Propietario del canal. Requisitos (CmsAjustesCanalVerificacion): una versión pública, 2 miembros activos, un
    enlace de contacto y ninguna versión retirada por malware en los últimos 90 días. El motivo de una retirada es texto
    libre, así que «por malware» es: retirada en esos 90 días y con un paquete cuyo hash está en la lista negra
    (`huella_vetada(hash)`)."""
    c = sol.canal
    ruta = f"{CARPETA}verificacion/{c}.json"
    if autor_id is None:
        return ["La solicitud la abre y la sube una sola cuenta: abre una propuesta nueva desde la tuya."]
    if rol_en_canal < 4:
        return [f"La verificación de @{c} la pide un Propietario del canal."]
    try:
        objeto = canales.leer_json_estricto(leer(ruta, "despues"), ruta, 16 * 1024)
        canal = canales.leer_json_estricto(leer(f"canales/{c}/canal.json", "antes"), f"canales/{c}/canal.json",
                                           canales.TOPES["canal.json"])
        miembros = canales.leer_json_estricto(leer(f"canales/{c}/miembros.json", "antes"),
                                              f"canales/{c}/miembros.json", canales.TOPES["miembros.json"])
    except canales.JsonMalo as error:
        return [str(error)]
    except TypeError:
        return [f"@{c} no existe en `main`."]
    motivos = []
    if not isinstance(objeto, dict) or set(objeto) - set(CAMPOS_VERIFICACION):
        return [f"`{ruta}`: solo valen {', '.join(f'`{k}`' for k in CAMPOS_VERIFICACION)}."]
    if objeto.get("esquema") != 1 or objeto.get("canal") != c:
        motivos.append(f"`{ruta}`: tiene que llevar `\"esquema\": 1` y `\"canal\": \"{c}\"`.")
    if (problema := canales.error_de_texto(objeto.get("motivo"), LARGO_MOTIVO, 1, 3)):
        motivos.append(f"`{ruta}` › `motivo`: {problema}.")
    if objeto.get("pedidaPor") != autor_id:
        motivos.append(f"`{ruta}` › `pedidaPor`: tiene que ser el id de tu cuenta ({autor_id}).")
    if not _hoy_vale(objeto.get("fecha"), hoy):
        motivos.append(f"`{ruta}` › `fecha`: tiene que ser la fecha de hoy ({hoy.isoformat()}, UTC).")
    if any(k in objeto for k in ("estado", "respuesta", "resuelta")):
        motivos.append(f"`{ruta}`: `estado`, `respuesta` y `resuelta` los pone el Dueño al resolverla.")
    if not isinstance(canal, dict):
        motivos.append(f"`canales/{c}/canal.json` de `main` no se puede leer.")
    else:
        verificacion = canal.get("verificacion") if isinstance(canal.get("verificacion"), dict) else {}
        if verificacion.get("verificado") is True:
            motivos.append(f"@{c} ya está verificado.")
        if canal.get("estado") != "activo":
            motivos.append(f"@{c} no está activo.")
        contacto = canal.get("contacto") if isinstance(canal.get("contacto"), dict) else {}
        if not (contacto.get("enlaces") or contacto.get("web") or contacto.get("correo")):
            motivos.append(f"Para pedir la verificación, @{c} necesita al menos un enlace de contacto.")
    filas, _ = canales.leer_miembros(miembros, f"canales/{c}/miembros.json")
    if sum(1 for m in filas.values() if m.activo) < 2:
        motivos.append(f"Para pedir la verificación, @{c} necesita al menos 2 miembros activos.")
    publica, malware = _versiones_del_canal(c, archivos_main, hoy, huella_vetada)
    if not publica:
        motivos.append(f"Para pedir la verificación, @{c} necesita al menos una versión pública.")
    if malware:
        motivos.append(f"@{c} tiene una versión retirada por malware en los últimos {DIAS_SIN_MALWARE} días.")
    return motivos


def _compacta(clave) -> str:
    """La clave de una etiqueta sin guiones: «hen-tai», «hentai» y «hen tai» son la misma."""
    return (clave or "").replace("-", "")


def comprobar_etiqueta(sol: Solicitud, leer, autor_id, rol_en_canal: int, hoy: datetime.date, archivos_main: dict,
                       etiquetas_main, parecido_reservado=None) -> list:
    """Motivos de rechazo de una solicitud de etiqueta global (`solicitudes/etiquetas/<n>.json`) que envía un
    Administrador o un Propietario del canal. `archivos_main` son {ruta: bytes} de `solicitudes/etiquetas/` en `main`
    (para el tope de 10 pendientes por canal) y `etiquetas_main` los bytes de `normas/etiquetas.json` de `main` (o
    None). `parecido_reservado(nombre)` da por qué el nombre se confunde con un nombre reservado (como en los canales:
    «Orniz…» solo es del Dueño), o None. Dos nombres que solo se distinguen por espacios o guiones son el mismo."""
    ruta = f"{CARPETA_ETIQUETAS}{sol.clave}.json"
    if autor_id is None:
        return ["La solicitud la abre y la sube una sola cuenta: abre una propuesta nueva desde la tuya."]
    if leer(ruta, "antes") is not None:
        return [f"`{ruta}` ya existe: ya se pidió una etiqueta con ese nombre (si está resuelta, mira la respuesta)."]
    try:
        objeto = canales.leer_json_estricto(leer(ruta, "despues"), ruta, TOPE_ARCHIVO)
    except canales.JsonMalo as error:
        return [str(error)]
    if not isinstance(objeto, dict) or set(objeto) - set(CAMPOS_ETIQUETA):
        return [f"`{ruta}`: solo valen {', '.join(f'`{k}`' for k in CAMPOS_ETIQUETA)}."]
    c = sol.canal
    if not canales.ID_CANAL.match(c):
        return [f"`{ruta}` › `canal`: tiene que ser el @ de tu canal."]
    try:
        canal = canales.leer_json_estricto(leer(f"canales/{c}/canal.json", "antes"), f"canales/{c}/canal.json",
                                           canales.TOPES["canal.json"])
    except canales.JsonMalo as error:
        return [str(error)]
    except TypeError:
        return [f"@{c} no existe en `main`."]
    if rol_en_canal < 3:
        return [f"Una etiqueta global para @{c} la pide un Administrador o un Propietario del canal."]
    motivos = []
    if not isinstance(canal, dict) or canal.get("estado") != "activo":
        motivos.append(f"@{c} no está activo.")
    if objeto.get("esquema") != 1:
        motivos.append(f"`{ruta}`: tiene que llevar `\"esquema\": 1`.")
    nombre = objeto.get("nombre")
    if (problema := canales.error_de_texto(nombre, LARGO_NOMBRE_ETIQUETA, 1, 0)):
        motivos.append(f"`{ruta}` › `nombre`: {problema}.")
    elif not nombre_de_archivo(nombre):
        motivos.append(f"`{ruta}` › `nombre`: necesita al menos una letra (a-z) o un número.")
    elif nombre_de_archivo(nombre) != sol.clave:
        motivos.append(f"`{ruta}`: el archivo tiene que llamarse `{nombre_de_archivo(nombre)}.json`, como el nombre.")
    elif parecido_reservado is not None and (problema := parecido_reservado(nombre)):
        motivos.append(f"`{ruta}` › `nombre`: «{nombre}» {problema}.")
    if (problema := canales.error_de_texto(objeto.get("paraQue"), LARGO_MOTIVO, 1, 3)):
        motivos.append(f"`{ruta}` › `paraQue`: {problema}.")
    if objeto.get("pedidaPor") != autor_id:
        motivos.append(f"`{ruta}` › `pedidaPor`: tiene que ser el id de tu cuenta ({autor_id}).")
    if not _hoy_vale(objeto.get("fecha"), hoy):
        motivos.append(f"`{ruta}` › `fecha`: tiene que ser la fecha de hoy ({hoy.isoformat()}, UTC).")
    if any(k in objeto for k in ("estado", "respuesta", "resuelta")):
        motivos.append(f"`{ruta}`: `estado`, `respuesta` y `resuelta` los pone el Dueño al resolverla.")
    # Una que ya existe (por su id o su nombre) no se pide: se usa.
    try:
        globales = json.loads(etiquetas_main) if etiquetas_main is not None else {}
    except (ValueError, RecursionError):
        globales = {}
    lista = globales.get("etiquetas") if isinstance(globales, dict) else None
    for e in lista if isinstance(lista, list) else []:
        if not isinstance(e, dict):
            continue
        claves = {_compacta(nombre_de_archivo(e.get("id"))), _compacta(nombre_de_archivo(e.get("nombre")))}
        if _compacta(sol.clave) in claves - {""}:
            visible = e.get("nombre") if isinstance(e.get("nombre"), str) else e.get("id")
            motivos.append(f"Ya existe la etiqueta «{visible}»: ponla en tus parches, no hace falta pedirla.")
            break
    if len(archivos_main) >= TOPE_ARCHIVOS_ETIQUETA:
        motivos.append("Hay demasiadas solicitudes de etiqueta sin limpiar: espera a que el Dueño del programa las "
                       "resuelva.")
    else:
        pendientes = 0
        # Una pedida con el mismo nombre salvo espacios o guiones («hentai.json» frente a «hen-tai.json»): ya está.
        for otra_ruta in archivos_main:
            otra_clave = m[1] if (m := RUTA_ETIQUETA.fullmatch(otra_ruta)) else None
            if otra_clave is not None and otra_clave != sol.clave and _compacta(otra_clave) == _compacta(sol.clave):
                motivos.append(f"Ya se pidió una etiqueta con ese nombre (`{otra_ruta}`): si está resuelta, mira la "
                               "respuesta.")
                break
        for datos in archivos_main.values():
            otra = _leer_suelto(lambda _r: datos, "")
            if isinstance(otra, dict) and otra.get("canal") == c and "estado" not in otra:
                pendientes += 1
        if pendientes >= TOPE_ABIERTAS:
            motivos.append(f"@{c} ya tiene {TOPE_ABIERTAS} solicitudes de etiqueta pendientes: espera a que se "
                           "resuelvan.")
    return motivos


def _versiones_del_canal(canal: str, archivos_main: dict, hoy: datetime.date, huella_vetada) -> tuple:
    """(¿alguna versión pública?, ¿alguna retirada por malware en los últimos 90 días?) de los parches del canal."""
    import json
    prefijo = f"canales/{canal}/parches/"
    publica = malware = False
    for ruta, datos in archivos_main.items():
        if not ruta.startswith(prefijo):
            continue
        try:
            parche = json.loads(datos)
        except (ValueError, RecursionError):
            continue
        for e in (parche.get("ediciones") or []) if isinstance(parche, dict) else []:
            for v in (e.get("versiones") or []) if isinstance(e, dict) else []:
                if not isinstance(v, dict):
                    continue
                publica = publica or v.get("estado") in ("publico", "anterior")
                paquete = v.get("paquete") if isinstance(v.get("paquete"), dict) else {}
                if v.get("estado") == "retirada" and isinstance(paquete.get("hash"), str) \
                        and huella_vetada(paquete["hash"].strip().lower()):
                    try:
                        cuando = datetime.date.fromisoformat(str(v.get("fechaRetirada") or v.get("fecha"))[:10])
                    except ValueError:
                        cuando = hoy
                    malware = malware or (hoy - cuando).days <= DIAS_SIN_MALWARE
    return publica, malware


def aprobacion(entorno, ids_duenos) -> str:
    """Qué dice este evento de la aprobación: «aprobada» (el Dueño acaba de poner `aprobada`), «ajena» (la ha puesto
    otra cuenta: hay que quitarla) o «nada»."""
    if entorno.get("PR_ACCION") != "labeled" or entorno.get("PR_ETIQUETA") != APROBADA:
        return "nada"
    sender = entorno.get("PR_ACTOR_ID") or ""
    return "aprobada" if sender.isdigit() and int(sender) in ids_duenos else "ajena"
