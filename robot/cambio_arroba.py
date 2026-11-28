"""Cambiar el @ de un canal (docs/canales.md §7.1, decisión §9.3).

Lo hace el Propietario del canal (o el Dueño del programa), como mucho una vez cada 30 días. La propuesta mueve la
carpeta entera: borra todo `canales/<viejo>/` y añade lo mismo en `canales/<nuevo>/`, byte a byte, salvo
`canal.json`, donde solo cambian `id` (el nuevo) e `idAnteriores` (con una fila más al final:
`{ "id": viejo, "desde": …, "hasta": hoy }`; `desde` es opcional). El Dueño del programa no tiene el límite de 30 días.

El @ viejo queda **bloqueado 24 horas** para todos, contadas desde el cambio (no desde la propuesta): la hora la apunta
el robot en `catalogo/canales.json` (`redirige[].cambio`) al publicar lo fusionado. Pasadas las 24 h queda libre para
cualquiera, también para el propio canal (que, si no es el Dueño, tiene además su límite de 30 días), y se juzga como
un @ nuevo cualquiera. Mientras tanto, y hasta 90 días si nadie lo toma, la app lo redirige al nuevo; si otro canal lo
toma, gana el canal y la redirección se quita.

El @ nuevo pasa lo mismo que el de un canal nuevo: que valga como @, que no sea del programa, que no exista ni esté
bloqueado, y que no se confunda con otro canal o un nombre reservado (sin contarse a sí mismo: su nombre no cambia).
"""

from __future__ import annotations

import datetime
import json

import canales

DIAS_ENTRE_CAMBIOS = 30
DIAS_REDIRECCION = 90
HORAS_BLOQUEO = 24
# Las filas de `idAnteriores` que se aceptan (a un cambio cada 30 días, son más de 80 años).
TOPE_ANTERIORES = 1000
PROPIETARIO = 4

# Lo que puede haber en la carpeta de un canal fuera de `parches/` (y el logo, que dice su `canal.json`).
FIJOS = ("canal.json", "miembros.json", "ficha.json", "lista-negra.json")


def detectar(cambios):
    """(viejo, nuevo) si la propuesta tiene la forma de un cambio de @: solo `canales/`, una carpeta con todo borrado y
    otra con todo añadido que trae su `canal.json`. Si no, None (y se juzga como cualquier otra)."""
    carpetas = {}
    for c in cambios:
        partes = canales.canal_de_la_ruta(c.ruta)
        if partes is None or not partes[1]:
            return None
        carpetas.setdefault(partes[0], []).append((partes[1], c.estado))
    if len(carpetas) != 2:
        return None
    viejos = [a for a, filas in carpetas.items() if all(e == "D" for _, e in filas)]
    nuevos = [a for a, filas in carpetas.items() if all(e == "A" for _, e in filas)
              and any(r == "canal.json" for r, _ in filas)]
    if len(viejos) == 1 and len(nuevos) == 1 and viejos[0] != nuevos[0]:
        return viejos[0], nuevos[0]
    return None


def _fecha(valor):
    if not isinstance(valor, str) or len(valor) != 10:
        return None
    try:
        return datetime.date.fromisoformat(valor)
    except ValueError:
        return None


def ultimo_cambio(canal_json) -> datetime.date | None:
    """El último `hasta` de `idAnteriores` (el día del último cambio de @), o None."""
    filas = canal_json.get("idAnteriores") if isinstance(canal_json, dict) else None
    fechas = [f for f in (_fecha(a.get("hasta")) for a in filas if isinstance(a, dict))
              if f is not None] if isinstance(filas, list) else []
    return max(fechas, default=None)


def hora_utc(texto):
    """Un instante `aaaa-mm-ddThh:mm:ssZ` (o con `+00:00`) → datetime en UTC, o None."""
    if not isinstance(texto, str) or not 20 <= len(texto) <= 32:
        return None
    try:
        valor = datetime.datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    return valor.astimezone(datetime.timezone.utc) if valor.tzinfo is not None else None


def texto_hora(valor: datetime.datetime) -> str:
    return valor.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def horas_de_cambio(canales_main) -> dict:
    """{(canal, @ viejo, hasta): instante del cambio} de `redirige` en `catalogo/canales.json` de `main` (bytes o el
    objeto ya leído). Lo ilegible no cuenta."""
    objeto = canales_main
    if isinstance(canales_main, (bytes, str)):
        try:
            objeto = json.loads(canales_main)
        except (ValueError, RecursionError):
            objeto = None
    filas = objeto.get("canales") if isinstance(objeto, dict) else objeto
    resultado = {}
    for entrada in filas if isinstance(filas, list) else []:
        if not isinstance(entrada, dict) or not isinstance(entrada.get("id"), str):
            continue
        for r in entrada.get("redirige") or [] if isinstance(entrada.get("redirige"), list) else []:
            if isinstance(r, dict) and isinstance(r.get("id"), str) and isinstance(r.get("hasta"), str) \
                    and (hora := hora_utc(r.get("cambio"))) is not None:
                resultado[(entrada["id"], r["id"], r["hasta"])] = hora
    return resultado


def bloqueados_por_cambio(archivos_main: dict, canales_main, ahora: datetime.datetime) -> dict:
    """{@: instante en que queda libre} de los @ que algún canal de `main` ha dejado hace menos de 24 horas.

    La hora es la del cambio que apuntó el robot al publicarlo. Si aún no la ha apuntado (lo acaba de fusionar), se
    cuenta como bloqueado hasta el final del día siguiente a `hasta` (el cambio fue, como tarde, ese día): pasado eso
    seguro que han pasado las 24 h. Un @ que ahora es de un canal no sale (ya existe)."""
    horas = horas_de_cambio(canales_main)
    vivos = {ruta.split("/")[1] for ruta in archivos_main
             if ruta.startswith(canales.CARPETA_CANALES) and ruta.count("/") == 2 and ruta.endswith("/canal.json")}
    resultado = {}
    for ruta, datos in archivos_main.items():
        partes = ruta.split("/")
        if len(partes) != 3 or partes[0] != "canales" or partes[2] != "canal.json":
            continue
        try:
            canal = json.loads(datos)
        except (ValueError, RecursionError, TypeError):
            continue
        filas = canal.get("idAnteriores") if isinstance(canal, dict) else None
        for fila in filas if isinstance(filas, list) else []:
            arroba = fila.get("id") if isinstance(fila, dict) else None
            hasta = _fecha(fila.get("hasta")) if isinstance(fila, dict) else None
            if not isinstance(arroba, str) or arroba in vivos or not canales.ID_CANAL.match(arroba):
                continue
            hora = horas.get((partes[1], arroba, fila.get("hasta")))
            if hora is not None:
                libre = hora + datetime.timedelta(hours=HORAS_BLOQUEO)
            elif hasta is not None:
                libre = datetime.datetime.combine(hasta + datetime.timedelta(days=2), datetime.time(),
                                                  datetime.timezone.utc)
            else:
                continue  # sin fecha que valga: no se sabe cuándo fue (validar_canal no deja escribirlo así)
            if ahora < libre:
                resultado[arroba] = max(libre, resultado.get(arroba, libre))
    return resultado


def _sin(objeto: dict, *claves) -> str:
    return json.dumps({k: v for k, v in objeto.items() if k not in claves}, sort_keys=True, ensure_ascii=False)


def comprobar(viejo: str, nuevo: str, cambios, leer, despues_sueltos: dict, *, autor_id, rol, es_dueno: bool,
              hoy: datetime.date, existe, parecido, bloqueados: dict, solicitud_abierta) -> list:
    """Motivos de rechazo de un cambio de @ de `viejo` a `nuevo`.

    `leer(ruta, lado)` da los bytes de `main` («antes») o de tras la propuesta («despues»); `despues_sueltos` las rutas
    de los archivos sueltos tras la propuesta (para ver que no queda ningún parche en la carpeta vieja); `rol` es el
    del autor en `viejo` (de los miembros activos de `main`); `existe(arroba)` None si el @ está libre, o por qué no
    (es de un canal de `main`, o lo ha dejado uno hace menos de 24 h); `parecido(texto)` por qué se confunde con otro canal
    o con un nombre reservado, o None; `bloqueados` los @ vetados por el Dueño; `solicitud_abierta(arroba)` el texto de
    una solicitud suya sin resolver en `main`, o None.
    """
    arroba, ruta_vieja, ruta_nueva = f"@{viejo}", f"canales/{viejo}/canal.json", f"canales/{nuevo}/canal.json"
    if autor_id is None and not es_dueno:
        return ["Un cambio de @ lo abre y lo sube una sola cuenta: abre una propuesta nueva desde la tuya."]
    if viejo == canales.CANAL_OFICIAL:
        return [f"{arroba} es el canal oficial: su @ no cambia."]
    if not es_dueno and rol != PROPIETARIO:
        return [f"El @ de {arroba} solo lo cambia su Propietario (o el Dueño del programa)."]
    if viejo in bloqueados:
        return [f"{arroba} está bloqueado por el Dueño del programa ({bloqueados[viejo]}): su @ no cambia."]
    if not canales.ID_CANAL.match(nuevo):
        return [f"`{nuevo}` no puede ser el @ de un canal (de 3 a 20 minúsculas, números y `_`)."]
    if nuevo in canales.ARROBAS_DEL_PROGRAMA:
        return [f"@{nuevo} está reservado por el programa y no puede ser el @ de un canal."]
    if (ocupado := existe(nuevo)):
        return [f"@{nuevo} {ocupado}."]
    if nuevo in bloqueados:
        return [f"@{nuevo} está bloqueado por el Dueño del programa."]

    try:
        antes = canales.leer_json_estricto(leer(ruta_vieja, "antes"), ruta_vieja, canales.TOPES["canal.json"])
        despues = canales.leer_json_estricto(leer(ruta_nueva, "despues"), ruta_nueva, canales.TOPES["canal.json"])
    except canales.JsonMalo as error:
        return [str(error)]
    if not isinstance(antes, dict):
        return [f"`{ruta_vieja}` de `main` no se puede leer: hasta que el Dueño del programa lo arregle, su @ no cambia."]

    motivos = []
    if antes.get("estado") != "activo" and not es_dueno:
        motivos.append(f"{arroba} no está activo: un canal retirado o en pausa no cambia de @.")
    if (problema := parecido(nuevo)):
        motivos.append(f"El @{nuevo} {problema}.")
    if (abierta := solicitud_abierta(viejo)):
        motivos.append(f"{arroba} tiene una solicitud sin resolver ({abierta}): espera a que se resuelva y cambia el @ "
                       "después.")
    ultimo = ultimo_cambio(antes)
    if ultimo is not None and (hoy - ultimo).days < DIAS_ENTRE_CAMBIOS and not es_dueno:
        siguiente = ultimo + datetime.timedelta(days=DIAS_ENTRE_CAMBIOS)
        motivos.append(f"{arroba} cambió de @ el {ultimo.isoformat()}: como mucho, una vez cada {DIAS_ENTRE_CAMBIOS} "
                       f"días (el próximo, desde el {siguiente.isoformat()}).")

    # canal.json: el nuevo vale como canal.json de su carpeta y solo cambian `id` e `idAnteriores`.
    errores = canales.validar_canal(despues, nuevo, ruta_nueva)
    if errores:
        return motivos + errores
    if _sin(antes, "id", "idAnteriores") != _sin(despues, "id", "idAnteriores"):
        motivos.append(f"`{ruta_nueva}`: en un cambio de @ solo cambian `id` e `idAnteriores`; lo demás se cambia "
                       "aparte, desde Ajustes del canal.")
    previas = antes.get("idAnteriores") or []
    filas = despues.get("idAnteriores")
    if not isinstance(filas, list) or len(filas) != len(previas) + 1 or filas[:-1] != previas:
        motivos.append(f"`{ruta_nueva}` › `idAnteriores`: tiene que ser el de antes con una fila más al final, la del "
                       f"@ viejo (`{{ \"id\": \"{viejo}\", \"hasta\": \"{hoy.isoformat()}\" }}`).")
    else:
        fila = filas[-1]
        hasta, desde = _fecha(fila.get("hasta")), fila.get("desde")
        if fila.get("id") != viejo:
            motivos.append(f"`{ruta_nueva}` › `idAnteriores`: la fila nueva es la de @{viejo}.")
        if hasta is None or abs((hasta - hoy).days) > 1:
            motivos.append(f"`{ruta_nueva}` › `idAnteriores`: `hasta` tiene que ser la fecha de hoy ({hoy.isoformat()}, "
                           "UTC).")
        if desde is not None and (_fecha(desde) is None or hasta is None or _fecha(desde) > hasta):
            motivos.append(f"`{ruta_nueva}` › `idAnteriores`: `desde` tiene que ser una fecha anterior a `hasta`.")
    if len(filas if isinstance(filas, list) else []) > TOPE_ANTERIORES:
        motivos.append(f"`{ruta_nueva}` › `idAnteriores`: como mucho {TOPE_ANTERIORES} @ anteriores.")

    # Lo demás: lo mismo, byte a byte, y que no quede nada en la carpeta vieja.
    viejos = {canales.canal_de_la_ruta(c.ruta)[1]: c for c in cambios if c.estado == "D"}
    nuevos = {canales.canal_de_la_ruta(c.ruta)[1]: c for c in cambios if c.estado == "A"}
    for resto in sorted(set(viejos) | set(nuevos)):
        if resto not in nuevos:
            motivos.append(f"`canales/{viejo}/{resto}` se borra pero no está en `canales/{nuevo}/`: la carpeta se "
                           "mueve entera.")
        elif resto not in viejos:
            motivos.append(f"`canales/{nuevo}/{resto}` no estaba en `canales/{viejo}/`: en un cambio de @ no se añade "
                           "nada.")
        elif resto != "canal.json":
            if nuevos[resto].modo != "100644":
                motivos.append(f"`canales/{nuevo}/{resto}`: solo archivos normales.")
            elif leer(f"canales/{viejo}/{resto}", "antes") != leer(f"canales/{nuevo}/{resto}", "despues"):
                motivos.append(f"`canales/{nuevo}/{resto}` no es igual que `canales/{viejo}/{resto}`: en un cambio de @ "
                               "se mueve sin cambiar; lo demás va en otra propuesta.")
    logo = antes.get("logo")
    quedan = [f"canales/{viejo}/{n}" for n in (*FIJOS, *((logo,) if isinstance(logo, str) else ()))
              if leer(f"canales/{viejo}/{n}", "despues") is not None]
    quedan += sorted(r for r in despues_sueltos if r.startswith(f"canales/{viejo}/"))
    if quedan:
        motivos.append(f"`{quedan[0]}` sigue en la carpeta vieja: la carpeta se mueve entera.")
    return motivos
