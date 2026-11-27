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
  `verificacion` en `canal.json` y `estado`, `motivo` y `fecha` en la solicitud).

Una solicitud va sola: si la propuesta toca algo más, no es una solicitud y se juzga (y se rechaza) como siempre. Los juegos, ediciones, la ficha central y las
etiquetas globales por solicitud llegan en la entrega siguiente.

Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

import canales

APROBADA = "aprobada"
PREFIJO_ETIQUETA = "solicitud:"
CARPETA = "solicitudes/"
RUTA_VERIFICACION = re.compile(r"solicitudes/verificacion/([a-z0-9_]{3,20})\.json")
RUTA_NORMAS = "normas/normas.json"

DIAS_CUENTA = 30
TOPE_CANALES_POR_CUENTA = 3
LARGO_MOTIVO = 300
DIAS_SIN_MALWARE = 90
CAMPOS_VERIFICACION = ("esquema", "canal", "motivo", "pedidaPor", "fecha", "estado", "respuesta", "resuelta")


@dataclass(frozen=True)
class Solicitud:
    tipo: str      # «canal» o «verificacion»
    canal: str

    @property
    def etiqueta(self) -> str:
        return PREFIJO_ETIQUETA + self.tipo

    @property
    def necesita_aprobacion(self) -> bool:
        """Las de propuesta esperan la etiqueta `aprobada`; las de archivo se fusionan y las resuelve el Dueño luego."""
        return self.tipo == "canal"


def clasificar(cambios, existe_en_main):
    """La solicitud que es la propuesta, o None si no es una. `cambios` son (ruta, estado) y `existe_en_main(ruta)`
    dice si ese archivo está en `main`. ValueError con el motivo si mezcla una solicitud con otros cambios."""
    rutas = [r for r, _ in cambios]
    verificaciones = [m for r in rutas if (m := RUTA_VERIFICACION.fullmatch(r))]
    if verificaciones or any(r.startswith(CARPETA) for r in rutas):
        if len(rutas) != 1 or len(verificaciones) != 1 or cambios[0][1] == "D":
            raise ValueError("Una solicitud va sola: la propuesta solo puede añadir o cambiar "
                             "`solicitudes/verificacion/<canal>.json` (lo demás, en propuestas aparte).")
        return Solicitud("verificacion", verificaciones[0][1])
    nuevos = {canales.canal_de_la_ruta(r)[0] for r, e in cambios
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
                          version_normas: int, parecido, abiertas) -> list:
    """Motivos de rechazo de una solicitud de canal nuevo.

    `leer(ruta, lado)` da los bytes; `cuenta_de(id)` el nombre actual de la cuenta; `creada_el(id)` la fecha en que se
    creó (None si no se sabe); `parecido(texto)` por qué un @ o un nombre se confunde con otro canal o uno reservado;
    `abiertas()` cuántas solicitudes de canal nuevo tiene abiertas esta cuenta (sin contar esta).
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
